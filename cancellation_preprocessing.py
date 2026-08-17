# -*- coding: utf-8 -*-
"""AQPP 前置冲销处理。

本模块只处理具有明确 SAP 原发票引用的取消/冲销关系：

1. 同期全额冲销：原发票及取消发票均不进入普通 AQPP；
2. 同期部分冲销且订单物料键一致：原发票与取消发票共同进入聚合，AQPP 使用净额；
3. 原发票缺失、类型不符、币种不一致或键不一致：保留在待确认明细；
4. 为被移出 AQPP 的冲销业务生成订单物料注册表，避免订单/发运在外连接后重新进入 Not Test。

所有入口均复制 DataFrame，不修改调用方的原始对象。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from config import (
    AMOUNT_TOLERANCE,
    CANCELLATION_INVOICE_TYPES,
    CANCELLATION_ORIGINAL_TYPE_MAP,
    QUANTITY_TOLERANCE,
)
from data_standardization import first_existing_column, normalize_identifier
from tolerance_utils import scalar_is_zero


@dataclass(frozen=True)
class CancellationPreprocessResult:
    """冲销预处理结果；各 DataFrame 均为独立副本。"""

    invoice_inventory: pd.DataFrame
    matchable_invoices: pd.DataFrame
    review_invoices: pd.DataFrame
    cancellation_details: pd.DataFrame
    cancellation_registry: pd.DataFrame
    cancellation_summary: pd.DataFrame


def _numeric_sum(frame: pd.DataFrame, column: str) -> float:
    return float(pd.to_numeric(frame[column], errors='coerce').fillna(0).sum())


def _unique_text(values) -> str:
    cleaned = pd.Series(values, dtype='string').dropna().str.strip()
    return '|'.join(dict.fromkeys(value for value in cleaned if value))


def _valid_key_rows(frame: pd.DataFrame, order_col: str, material_col: str) -> pd.DataFrame:
    """返回订单号和物料均完整的键；不修改输入。"""
    if order_col not in frame.columns or material_col not in frame.columns:
        return pd.DataFrame(columns=[order_col, material_col])
    keys = pd.DataFrame({
        order_col: normalize_identifier(frame[order_col]),
        material_col: normalize_identifier(frame[material_col]),
    })
    valid = keys[order_col].notna() & keys[material_col].notna()
    return keys.loc[valid].drop_duplicates().reset_index(drop=True)


def _same_currency(frame: pd.DataFrame) -> bool:
    currency_col = first_existing_column(
        frame, ('标准-发票币种', '发票币种', '订单币种')
    )
    if currency_col is None:
        return True
    currencies = normalize_identifier(frame[currency_col]).dropna().unique()
    return len(currencies) <= 1


def _pair_keys_compatible(
    original: pd.DataFrame,
    cancellation: pd.DataFrame,
    order_col: str,
    material_col: str,
) -> bool:
    """部分冲销仅在取消行的订单物料键可明确落到原发票键时自动净额化。"""
    if (
        original.empty or cancellation.empty
        or order_col not in original.columns or material_col not in original.columns
        or order_col not in cancellation.columns or material_col not in cancellation.columns
    ):
        return False
    original_complete = (
        normalize_identifier(original[order_col]).notna()
        & normalize_identifier(original[material_col]).notna()
    ).all()
    cancellation_complete = (
        normalize_identifier(cancellation[order_col]).notna()
        & normalize_identifier(cancellation[material_col]).notna()
    ).all()
    if not original_complete or not cancellation_complete:
        return False
    original_keys = {
        tuple(row) for row in _valid_key_rows(original, order_col, material_col).itertuples(index=False, name=None)
    }
    cancellation_keys = {
        tuple(row) for row in _valid_key_rows(cancellation, order_col, material_col).itertuples(index=False, name=None)
    }
    return bool(original_keys) and bool(cancellation_keys) and cancellation_keys.issubset(original_keys)


def _set_pair_fields(
    out: pd.DataFrame,
    indices,
    *,
    code: str,
    status: str,
    pair_id: str,
    original_invoice_no: str | None,
    cancellation_invoice_nos: str,
    role: str,
    amount_nets: dict[str, float],
    quantity_nets: dict[str, float],
) -> None:
    out.loc[indices, '冲销处理编码'] = code
    out.loc[indices, '冲销处理状态'] = status
    if '冲销配对状态' in out.columns:
        out.loc[indices, '冲销配对状态'] = status
    out.loc[indices, '冲销配对编号'] = pair_id
    out.loc[indices, '配对原发票号'] = original_invoice_no
    out.loc[indices, '配对取消发票号'] = cancellation_invoice_nos
    out.loc[indices, '冲销业务角色'] = role
    for column, value in amount_nets.items():
        out.loc[indices, f'冲销净额-{column}'] = round(value, 2)
    for column, value in quantity_nets.items():
        out.loc[indices, f'冲销净额-{column}'] = round(value, 6)


def _empty_summary(amount_columns, quantity_columns) -> pd.DataFrame:
    columns = [
        '冲销处理编码', '冲销处理状态', '配对组数', '原发票数', '取消发票数',
        '原发票行数', '取消发票行数',
    ]
    columns += [f'冲销净额-{column}' for column in amount_columns]
    columns += [f'冲销净额-{column}' for column in quantity_columns]
    return pd.DataFrame(columns=columns)


def preprocess_cancellations(
    invoice_inventory: pd.DataFrame,
    *,
    channel: str,
    order_col: str,
    material_col: str,
    amount_columns,
    quantity_columns,
    amount_tolerance: float = AMOUNT_TOLERANCE,
    quantity_tolerance: float = QUANTITY_TOLERANCE,
) -> CancellationPreprocessResult:
    """配对冲销并生成 AQPP 输入、待确认明细和冲销业务键。

    参数中的金额列可同时传入含税金额和 OMS ZFN1；只有所有可用金额列、数量列
    都在各自容差内归零，才判定为同期全额冲销。
    """
    out = invoice_inventory.copy().reset_index(drop=True)
    amount_columns = tuple(column for column in amount_columns if column in out.columns)
    quantity_columns = tuple(column for column in quantity_columns if column in out.columns)

    string_columns = (
        '冲销处理编码', '冲销处理状态', '冲销配对编号', '配对原发票号',
        '配对取消发票号', '冲销业务角色', 'AQPP前置处理',
    )
    for column in string_columns:
        out[column] = pd.Series(pd.NA, index=out.index, dtype='string')
    for column in (*amount_columns, *quantity_columns):
        out[f'冲销净额-{column}'] = pd.Series(float('nan'), index=out.index, dtype='float64')

    invoice_no_col = first_existing_column(out, ('SAP发票号', 'SAP发票编号'))
    reference_col = first_existing_column(out, ('SAP冲销发票号', '冲销发票号'))
    type_col = '发票类型代码规范' if '发票类型代码规范' in out.columns else first_existing_column(
        out, ('发票类型', '发票类型代码')
    )
    if invoice_no_col is None or reference_col is None or type_col is None:
        matchable = out['发票类型可参与匹配'].fillna(False).astype(bool)
        empty = _empty_summary(amount_columns, quantity_columns)
        return CancellationPreprocessResult(
            out,
            out.loc[matchable].copy(),
            out.loc[~matchable].copy(),
            out.iloc[0:0].copy(),
            pd.DataFrame(columns=[order_col, material_col, '冲销处理编码', '冲销处理状态', '冲销配对编号']),
            empty,
        )

    normalized_invoice_no = normalize_identifier(out[invoice_no_col])
    normalized_reference = normalize_identifier(out[reference_col])
    normalized_type = normalize_identifier(out[type_col])
    cancellation_mask = normalized_type.isin(CANCELLATION_INVOICE_TYPES)

    # 保留原有的轻量配对字段，并增加正式处理字段。
    out['冲销原发票号'] = normalized_reference
    if '冲销配对状态' not in out.columns:
        out['冲销配对状态'] = '不适用'

    pair_records = []
    registry_parts = []
    pair_counter = 0

    # 缺少原发票号的取消发票不能自动配对。
    missing_ref_indices = out.index[cancellation_mask & normalized_reference.isna()]
    for invoice_no, indices in out.loc[missing_ref_indices].groupby(normalized_invoice_no.loc[missing_ref_indices], dropna=False).groups.items():
        pair_counter += 1
        pair_id = f'{channel}-CA-{pair_counter:06d}'
        cancel = out.loc[list(indices)]
        amount_nets = {column: _numeric_sum(cancel, column) for column in amount_columns}
        quantity_nets = {column: _numeric_sum(cancel, column) for column in quantity_columns}
        cancel_nos = _unique_text(normalized_invoice_no.loc[list(indices)])
        _set_pair_fields(
            out, list(indices), code='CA-05', status='冲销原发票号缺失', pair_id=pair_id,
            original_invoice_no=None, cancellation_invoice_nos=cancel_nos, role='取消发票',
            amount_nets=amount_nets, quantity_nets=quantity_nets,
        )
        out.loc[list(indices), 'AQPP前置处理'] = '排除-冲销关系待确认'
        pair_records.append({
            '冲销处理编码': 'CA-05', '冲销处理状态': '冲销原发票号缺失', '冲销配对编号': pair_id,
            '原发票数': 0, '取消发票数': normalized_invoice_no.loc[list(indices)].nunique(),
            '原发票行数': 0, '取消发票行数': len(indices),
            **{f'冲销净额-{column}': value for column, value in {**amount_nets, **quantity_nets}.items()},
        })
        keys = _valid_key_rows(cancel, order_col, material_col)
        if not keys.empty:
            keys['冲销处理编码'] = 'CA-05'; keys['冲销处理状态'] = '冲销原发票号缺失'; keys['冲销配对编号'] = pair_id
            registry_parts.append(keys)

    reference_values = normalized_reference.loc[cancellation_mask & normalized_reference.notna()].drop_duplicates()
    for original_invoice_no in reference_values:
        pair_counter += 1
        pair_id = f'{channel}-CA-{pair_counter:06d}'
        cancel_indices = out.index[cancellation_mask & normalized_reference.eq(original_invoice_no)]
        cancellation = out.loc[cancel_indices]
        cancel_types = set(normalized_type.loc[cancel_indices].dropna())
        expected_original_types = set()
        for invoice_type in cancel_types:
            configured_types = CANCELLATION_ORIGINAL_TYPE_MAP.get(invoice_type, ())
            if isinstance(configured_types, str):
                expected_original_types.add(configured_types)
            else:
                expected_original_types.update(configured_types)
        original_indices = out.index[
            normalized_invoice_no.eq(original_invoice_no) & ~cancellation_mask
        ]
        original = out.loc[original_indices]
        actual_original_types = set(normalized_type.loc[original_indices].dropna())

        all_indices = list(original_indices) + list(cancel_indices)
        pair_frame = out.loc[all_indices]
        amount_nets = {column: _numeric_sum(pair_frame, column) for column in amount_columns}
        quantity_nets = {column: _numeric_sum(pair_frame, column) for column in quantity_columns}
        cancel_nos = _unique_text(normalized_invoice_no.loc[cancel_indices])

        has_original = len(original_indices) > 0
        type_matches = (
            has_original and bool(actual_original_types)
            and actual_original_types.issubset(expected_original_types)
        )
        currency_matches = _same_currency(pair_frame)
        has_comparison = bool(amount_columns) and bool(quantity_columns)
        comparison_complete = all(
            pd.to_numeric(pair_frame[column], errors='coerce').notna().all()
            for column in (*amount_columns, *quantity_columns)
        )
        amount_zero = bool(amount_columns) and all(
            scalar_is_zero(value, amount_tolerance) for value in amount_nets.values()
        )
        quantity_zero = bool(quantity_columns) and all(
            scalar_is_zero(value, quantity_tolerance) for value in quantity_nets.values()
        )
        full_cancellation = (
            has_comparison and comparison_complete and amount_zero and quantity_zero
            and currency_matches and type_matches
        )
        keys_compatible = has_original and _pair_keys_compatible(
            original, cancellation, order_col, material_col
        )

        if not has_original:
            code, status = 'CA-02', '跨期冲销-原发票未在本期清单'
            aqpp_action = '排除-待补原发票'
        elif not type_matches:
            code, status = 'CA-06', '冲销原发票类型不符'
            aqpp_action = '排除-冲销关系待确认'
        elif not currency_matches:
            code, status = 'CA-04', '冲销币种不一致待确认'
            aqpp_action = '排除-冲销关系待确认'
        elif full_cancellation:
            code, status = 'CA-01', '同期全额冲销-净额为零'
            aqpp_action = '排除-同期全额冲销'
        elif keys_compatible and comparison_complete:
            code, status = 'CA-03', '同期部分冲销-剩余净额参与AQPP'
            aqpp_action = '纳入-冲销后剩余净额'
        else:
            code, status = 'CA-04', '部分冲销或订单物料键不一致待确认'
            aqpp_action = '排除-冲销关系待确认'

        _set_pair_fields(
            out, original_indices, code=code, status=status, pair_id=pair_id,
            original_invoice_no=original_invoice_no, cancellation_invoice_nos=cancel_nos,
            role='原发票', amount_nets=amount_nets, quantity_nets=quantity_nets,
        )
        _set_pair_fields(
            out, cancel_indices, code=code, status=status, pair_id=pair_id,
            original_invoice_no=original_invoice_no, cancellation_invoice_nos=cancel_nos,
            role='取消发票', amount_nets=amount_nets, quantity_nets=quantity_nets,
        )
        out.loc[all_indices, 'AQPP前置处理'] = aqpp_action

        if code == 'CA-03':
            # 只有键一致的部分冲销才允许原发票和取消发票一起聚合为剩余净额。
            out.loc[all_indices, '发票类型可参与匹配'] = True
            out.loc[all_indices, '发票类型处理方式'] = '冲销后剩余净额参与匹配'
            out.loc[all_indices, '特殊发票标记'] = True
        else:
            out.loc[all_indices, '发票类型可参与匹配'] = False
            out.loc[all_indices, '发票类型处理方式'] = status
            out.loc[all_indices, '特殊发票标记'] = True

        pair_records.append({
            '冲销处理编码': code, '冲销处理状态': status, '冲销配对编号': pair_id,
            '原发票数': normalized_invoice_no.loc[original_indices].nunique(),
            '取消发票数': normalized_invoice_no.loc[cancel_indices].nunique(),
            '原发票行数': len(original_indices), '取消发票行数': len(cancel_indices),
            **{f'冲销净额-{column}': value for column, value in {**amount_nets, **quantity_nets}.items()},
        })

        # 任何已识别冲销关系均注册其业务键；匹配流程仅在该键缺少剩余有效发票时分流。
        keys = _valid_key_rows(pair_frame, order_col, material_col)
        if not keys.empty:
            keys['冲销处理编码'] = code; keys['冲销处理状态'] = status; keys['冲销配对编号'] = pair_id
            registry_parts.append(keys)

    matchable_mask = out['发票类型可参与匹配'].fillna(False).astype(bool)
    processed_mask = out['冲销处理编码'].notna()
    details = out.loc[processed_mask].copy()
    registry = pd.concat(registry_parts, ignore_index=True, sort=False) if registry_parts else pd.DataFrame(
        columns=[order_col, material_col, '冲销处理编码', '冲销处理状态', '冲销配对编号']
    )
    if not registry.empty:
        registry = registry.drop_duplicates().reset_index(drop=True)

    pair_frame = pd.DataFrame(pair_records)
    if pair_frame.empty:
        summary = _empty_summary(amount_columns, quantity_columns)
    else:
        aggregations = {
            '配对组数': ('冲销配对编号', 'nunique'),
            '原发票数': ('原发票数', 'sum'),
            '取消发票数': ('取消发票数', 'sum'),
            '原发票行数': ('原发票行数', 'sum'),
            '取消发票行数': ('取消发票行数', 'sum'),
        }
        for column in (*amount_columns, *quantity_columns):
            aggregations[f'冲销净额-{column}'] = (f'冲销净额-{column}', 'sum')
        summary = pair_frame.groupby(
            ['冲销处理编码', '冲销处理状态'], as_index=False, dropna=False
        ).agg(**aggregations)
        for column in amount_columns:
            summary[f'冲销净额-{column}'] = summary[f'冲销净额-{column}'].round(2)
        for column in quantity_columns:
            summary[f'冲销净额-{column}'] = summary[f'冲销净额-{column}'].round(6)

    return CancellationPreprocessResult(
        invoice_inventory=out,
        matchable_invoices=out.loc[matchable_mask].copy(),
        review_invoices=out.loc[~matchable_mask].copy(),
        cancellation_details=details,
        cancellation_registry=registry,
        cancellation_summary=summary,
    )


def aggregate_cancellation_registry(registry: pd.DataFrame, key_columns) -> pd.DataFrame:
    """把可能一键多配对的注册表压缩为一行，供外连接结果分流。"""
    key_columns = list(key_columns)
    if registry is None or registry.empty:
        return pd.DataFrame(columns=key_columns + ['冲销处理编码', '冲销处理状态', '冲销配对编号'])
    work = registry.dropna(subset=key_columns).copy()
    if work.empty:
        return pd.DataFrame(columns=key_columns + ['冲销处理编码', '冲销处理状态', '冲销配对编号'])
    return work.groupby(key_columns, as_index=False).agg({
        '冲销处理编码': _unique_text,
        '冲销处理状态': _unique_text,
        '冲销配对编号': _unique_text,
    })


def split_registered_cancellation_rows(
    outer_frame: pd.DataFrame,
    registry: pd.DataFrame,
    key_columns,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """按冲销注册表分流外连接记录，并安全处理同名冲销字段。

    无发票记录仍会保留全空的冲销字段，直接merge会生成``_x/_y``后缀。
    本函数使用临时前缀合并，再回填标准字段；不修改两个输入DataFrame。
    """
    key_columns = list(key_columns)
    compressed = aggregate_cancellation_registry(registry, key_columns)
    if compressed.empty:
        return outer_frame.copy(), outer_frame.iloc[0:0].copy()

    metadata_columns = ('冲销处理编码', '冲销处理状态', '冲销配对编号')
    rename_map = {column: f'_注册-{column}' for column in metadata_columns}
    compressed = compressed.rename(columns=rename_map)
    merged = outer_frame.merge(compressed, on=key_columns, how='left')
    registered_mask = merged['_注册-冲销处理编码'].notna()
    registered = merged.loc[registered_mask].copy()
    remaining = merged.loc[~registered_mask].copy()
    for column in metadata_columns:
        registered[column] = registered[rename_map[column]]
    temporary_columns = list(rename_map.values())
    return (
        remaining.drop(columns=temporary_columns),
        registered.drop(columns=temporary_columns),
    )

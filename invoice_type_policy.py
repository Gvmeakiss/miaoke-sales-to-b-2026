# -*- coding: utf-8 -*-
"""集中处理发票类型参与范围、特殊标记和待确认类型。"""

from __future__ import annotations

import pandas as pd

from config import (
    CANCELLATION_INVOICE_TYPES,
    INVOICE_DESCRIPTION_RULES,
    INVOICE_TYPE_DEFAULT_ACTION,
    INVOICE_TYPE_RULES,
    PBC_INVOICE_SCOPE_TYPES,
)
from data_standardization import first_existing_column, normalize_identifier


def apply_invoice_type_policy(df: pd.DataFrame) -> pd.DataFrame:
    """增加发票类型规范列；返回副本，不删除任何记录、不改变金额符号。"""
    out = df.copy()
    code_col = first_existing_column(out, ('发票类型', '发票类型代码'))
    desc_col = first_existing_column(out, ('发票类型.1', '发票类型描述'))
    code = normalize_identifier(out[code_col]) if code_col else pd.Series(pd.NA, index=out.index, dtype='string')
    description = out[desc_col].astype('string').str.strip() if desc_col else pd.Series(pd.NA, index=out.index, dtype='string')

    # 仅在代码缺失时使用明确的中文描述映射，避免模糊包含造成误分类。
    for text, mapped_code in INVOICE_DESCRIPTION_RULES.items():
        code.loc[code.isna() & description.eq(text)] = mapped_code

    out['发票类型代码规范'] = code
    out['发票类型描述规范'] = description
    out['发票类型处理方式'] = code.map(
        {key: value['action'] for key, value in INVOICE_TYPE_RULES.items()}
    ).fillna(INVOICE_TYPE_DEFAULT_ACTION)
    out['发票类型业务分类'] = code.map(
        {key: value['business'] for key, value in INVOICE_TYPE_RULES.items()}
    ).fillna('未知/待确认')
    out['特殊发票标记'] = code.map(
        {key: value['special'] for key, value in INVOICE_TYPE_RULES.items()}
    ).fillna(True).astype(bool)
    out['发票类型可参与匹配'] = out['发票类型处理方式'].isin(
        ['正常参与匹配', '特殊场景参与匹配']
    )
    out['发票金额方向处理'] = '沿用源清单金额符号，未取得借贷标识前不自动翻转'

    # 冲销发票不直接进入AQPP；先检查其引用的原发票是否存在于同一输入清单。
    invoice_no_col = first_existing_column(out, ('SAP发票号', 'SAP发票编号'))
    cancellation_ref_col = first_existing_column(out, ('SAP冲销发票号', '冲销发票号'))
    invoice_numbers = (
        set(normalize_identifier(out[invoice_no_col]).dropna()) if invoice_no_col else set()
    )
    cancellation_ref = (
        normalize_identifier(out[cancellation_ref_col])
        if cancellation_ref_col else pd.Series(pd.NA, index=out.index, dtype='string')
    )
    is_cancellation = out['发票类型代码规范'].isin(CANCELLATION_INVOICE_TYPES)
    out['冲销原发票号'] = cancellation_ref
    out['冲销配对状态'] = '不适用'
    out.loc[is_cancellation & cancellation_ref.isna(), '冲销配对状态'] = '待确认-缺少原发票号'
    out.loc[is_cancellation & cancellation_ref.notna(), '冲销配对状态'] = '待确认-原发票未在清单'
    out.loc[
        is_cancellation & cancellation_ref.isin(invoice_numbers), '冲销配对状态'
    ] = '已找到原发票-待净额核对'
    return out


def join_unique(values) -> str:
    """聚合订单物料下的多种发票类型，保留所有类型而不是只取first。"""
    cleaned = (
        str(value).strip() for value in values
        if pd.notna(value) and str(value).strip()
    )
    return '|'.join(dict.fromkeys(cleaned))


def select_policy_excluded_for_not_test(review_invoices: pd.DataFrame) -> pd.DataFrame:
    """仅返回发票类型规则排除、且未进入冲销前置处理的发票。

    已有冲销处理编码的记录继续沿用冲销配对、净额和业务键分流逻辑，不进入
    普通Not Test；无冲销处理编码的待确认类型才按三单存在关系进入现有NT编码。
    """
    if review_invoices is None or review_invoices.empty:
        return pd.DataFrame() if review_invoices is None else review_invoices.copy()
    if '冲销处理编码' not in review_invoices.columns:
        return review_invoices.copy()
    return review_invoices.loc[review_invoices['冲销处理编码'].isna()].copy()


def select_tob_oms_reporting_scope(invoice_inventory: pd.DataFrame) -> pd.DataFrame:
    """限定ToB-OMS匹配与金额核对范围。

    保留两类记录：
    1. 按当前AQPP发票类型政策可参与匹配的类型，以保持既有OMS匹配范围；
    2. PBC业务范围明确归属ToB-OMS的政策排除类型，供现有Not Test展示。

    ToC和“其他”中不参与AQPP的类型不得因DMS销售单号为空而进入
    ToB-OMS的Not Test、发票类型汇总或匹配率分母。
    """
    if invoice_inventory is None or invoice_inventory.empty:
        return pd.DataFrame() if invoice_inventory is None else invoice_inventory.copy()
    code_col = first_existing_column(
        invoice_inventory,
        ('发票类型代码规范', '发票类型', '发票类型代码'),
    )
    if code_col is None:
        return invoice_inventory.iloc[0:0].copy()
    normalized_code = normalize_identifier(invoice_inventory[code_col])
    aqpp_type_codes = {
        code for code, rule in INVOICE_TYPE_RULES.items()
        if rule.get('action') in {'正常参与匹配', '特殊场景参与匹配'}
    }
    tob_oms_codes = set(PBC_INVOICE_SCOPE_TYPES.get('ToB-OMS', set()))
    return invoice_inventory.loc[
        normalized_code.isin(aqpp_type_codes | tob_oms_codes)
    ].copy()


def aggregate_with_selective_unique_join(
    frame: pd.DataFrame,
    key_columns,
    aggregation: dict,
    unique_join_columns,
) -> pd.DataFrame:
    """高效聚合宽表，仅对重复业务键执行多值文本拼接。

    绝大多数订单物料键只有一行，对这些键使用C层实现的``first``；只有确实
    存在多行的键才调用``join_unique``。返回新DataFrame，不修改输入及传入字典。
    """
    key_columns = list(key_columns)
    join_columns = [
        column for column in dict.fromkeys(unique_join_columns)
        if column in frame.columns and column in aggregation
    ]
    fast_aggregation = dict(aggregation)
    for column in join_columns:
        fast_aggregation[column] = 'first'
    result = frame.groupby(
        key_columns, as_index=False, sort=False, dropna=False
    ).agg(fast_aggregation)

    duplicate_mask = frame.duplicated(key_columns, keep=False)
    if not duplicate_mask.any() or not join_columns:
        return result
    duplicate_rows = frame.loc[duplicate_mask, key_columns + join_columns]
    overrides = duplicate_rows.groupby(
        key_columns, as_index=False, sort=False, dropna=False
    )[join_columns].agg(join_unique)
    result = result.merge(overrides, on=key_columns, how='left', suffixes=('', '__多值'))
    for column in join_columns:
        override_column = f'{column}__多值'
        result[column] = result[override_column].where(
            result[override_column].notna() & result[override_column].ne(''),
            result[column],
        )
    return result.drop(columns=[f'{column}__多值' for column in join_columns])

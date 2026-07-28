# -*- coding: utf-8 -*-
"""发票类型与 OMS 订单、发运数据的静态钩稽能力诊断。"""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from data_standardization import first_existing_column, normalize_identifier


OMS_MATCHABILITY_COLUMNS = [
    '发票类型代码', '发票类型描述', '政策处理方式',
    '清单行数', 'SAP发票数', '当前AQPP输入行数',
    '匹配键完整行数', '匹配键缺失行数', '有效OMS订单物料键数',
    '订单命中键数', '发运命中键数', '三单齐全键数',
    '仅订单无发运键数', '仅发运无订单键数', '订单发运均未命中键数',
    '三单齐全率', '发票金额', '三单齐全键对应发票金额',
    'OMS数据匹配能力', '当前AQPP处理结论',
]


def build_oms_order_item_key(order_number: pd.Series, material_number: pd.Series) -> pd.Series:
    """生成 OMS 订单号+物料号匹配键；任一字段为空时返回缺失。

    返回新 Series，不修改传入的订单号或物料号。
    """
    order = normalize_identifier(order_number)
    material = normalize_identifier(material_number)
    valid = (
        order.notna() & order.str.strip().ne('')
        & material.notna() & material.str.strip().ne('')
    )
    key = pd.Series(pd.NA, index=order.index, dtype='string')
    key.loc[valid] = order.loc[valid] + '||' + material.loc[valid]
    return key


def _as_key_set(values: Iterable) -> set[str]:
    """清理匹配键集合中的空值。"""
    keys = pd.Series(values, dtype='string').dropna().str.strip()
    return set(keys.loc[keys.ne('')])


def _join_unique(values: Iterable) -> str:
    cleaned = pd.Series(values, dtype='string').dropna().str.strip()
    return '|'.join(dict.fromkeys(value for value in cleaned if value))


def _pct(numerator: int, denominator: int) -> str:
    return 'N/A' if denominator == 0 else f'{numerator / denominator:.1%}'


def _data_capability(valid_keys: int, order_hits: int, delivery_hits: int, both_hits: int) -> str:
    """仅依据本期匹配键覆盖判断数据能力，不替代业务范围政策。"""
    if valid_keys == 0:
        return '无法匹配-OMS匹配键全部缺失'
    if both_hits == 0:
        if order_hits == 0 and delivery_hits == 0:
            return '无法匹配-订单和发运均未命中'
        if order_hits > 0 and delivery_hits == 0:
            return '无法匹配-缺发运命中'
        if order_hits == 0 and delivery_hits > 0:
            return '无法匹配-缺订单命中'
        return '无法匹配-订单和发运未同时命中同一键'
    if both_hits == valid_keys:
        return '可匹配-全部有效键三单齐全'
    return '部分可匹配'


def _aqpp_conclusion(aqpp_input_rows: int, both_hits: int) -> str:
    """区分政策未纳入与数据无法钩稽，避免把两类原因混为一谈。"""
    if aqpp_input_rows == 0:
        if both_hits:
            return '数据键可钩稽，但按发票类型/冲销政策不直接进入AQPP'
        return '按发票类型/冲销政策不进入AQPP，且本期无三单齐全键'
    if both_hits == 0:
        return '已在AQPP输入范围，但本期无三单齐全键'
    return '已进入AQPP输入范围，按明细完整性继续分类'


def build_oms_invoice_type_matchability(
    invoice_inventory: pd.DataFrame,
    *,
    order_keys: Iterable,
    delivery_keys: Iterable,
    invoice_order_col: str,
    invoice_material_col: str,
    amount_col: str = '实际金额（ZFN1）',
) -> pd.DataFrame:
    """按发票类型汇总 OMS 匹配键、订单和发运覆盖情况。

    参数：
        invoice_inventory: OMS 渠道发票清单，可含冲销前置处理结果。
        order_keys/delivery_keys: 已按生产逻辑构造的 OMS 订单物料键。
        invoice_order_col/invoice_material_col: 发票侧 OMS 订单号、物料号字段。
        amount_col: OMS AQPP 使用的发票金额字段。

    返回：
        每种发票类型一行并附总计的诊断表。函数只建立必要的窄表，
        不修改原始 DataFrame，也不改变任何发票类型参与政策。
    """
    if invoice_inventory is None or invoice_inventory.empty:
        return pd.DataFrame(columns=OMS_MATCHABILITY_COLUMNS)
    missing = [
        column for column in (invoice_order_col, invoice_material_col)
        if column not in invoice_inventory.columns
    ]
    if missing:
        raise ValueError(f"OMS发票类型匹配能力诊断缺少字段: {', '.join(missing)}")

    type_col = first_existing_column(
        invoice_inventory, ('发票类型代码规范', '发票类型', '发票类型代码')
    )
    description_col = first_existing_column(
        invoice_inventory, ('发票类型描述规范', '发票类型.1', '发票类型描述')
    )
    invoice_no_col = first_existing_column(
        invoice_inventory, ('SAP发票号', 'SAP发票编号')
    )

    # 只复制汇总所需字段，避免对 100+ 列发票宽表做第二次完整复制。
    work = pd.DataFrame(index=invoice_inventory.index)
    work['_类型'] = (
        normalize_identifier(invoice_inventory[type_col]).fillna('未知')
        if type_col else '未知'
    )
    work['_描述'] = (
        invoice_inventory[description_col].astype('string').str.strip().fillna('未知/待确认')
        if description_col else '未知/待确认'
    )
    if '发票类型处理方式' in invoice_inventory.columns:
        work['_政策'] = invoice_inventory['发票类型处理方式'].astype('string').fillna('未配置')
    else:
        work['_政策'] = '未配置'
    if '发票类型可参与匹配' in invoice_inventory.columns:
        work['_AQPP输入'] = invoice_inventory['发票类型可参与匹配'].fillna(False).astype(bool)
    else:
        work['_AQPP输入'] = False
    work['_发票号'] = (
        normalize_identifier(invoice_inventory[invoice_no_col])
        if invoice_no_col else pd.Series(pd.NA, index=work.index, dtype='string')
    )
    work['_金额'] = (
        pd.to_numeric(invoice_inventory[amount_col], errors='coerce').fillna(0)
        if amount_col in invoice_inventory.columns else 0.0
    )
    work['_键'] = build_oms_order_item_key(
        invoice_inventory[invoice_order_col], invoice_inventory[invoice_material_col]
    )
    order_key_set = _as_key_set(order_keys)
    delivery_key_set = _as_key_set(delivery_keys)
    work['_订单命中'] = work['_键'].isin(order_key_set)
    work['_发运命中'] = work['_键'].isin(delivery_key_set)
    work['_三单齐全'] = work['_订单命中'] & work['_发运命中']

    rows = []
    for invoice_type, group in work.groupby('_类型', dropna=False, sort=True):
        valid_rows = group.loc[group['_键'].notna()]
        distinct_keys = valid_rows.drop_duplicates('_键')
        valid_key_count = int(distinct_keys['_键'].nunique())
        order_hits = int(distinct_keys['_订单命中'].sum())
        delivery_hits = int(distinct_keys['_发运命中'].sum())
        both_hits = int(distinct_keys['_三单齐全'].sum())
        aqpp_input_rows = int(group['_AQPP输入'].sum())
        rows.append({
            '发票类型代码': str(invoice_type),
            '发票类型描述': _join_unique(group['_描述']),
            '政策处理方式': _join_unique(group['_政策']),
            '清单行数': len(group),
            'SAP发票数': int(group['_发票号'].nunique()),
            '当前AQPP输入行数': aqpp_input_rows,
            '匹配键完整行数': len(valid_rows),
            '匹配键缺失行数': int(group['_键'].isna().sum()),
            '有效OMS订单物料键数': valid_key_count,
            '订单命中键数': order_hits,
            '发运命中键数': delivery_hits,
            '三单齐全键数': both_hits,
            '仅订单无发运键数': int((distinct_keys['_订单命中'] & ~distinct_keys['_发运命中']).sum()),
            '仅发运无订单键数': int((~distinct_keys['_订单命中'] & distinct_keys['_发运命中']).sum()),
            '订单发运均未命中键数': int((~distinct_keys['_订单命中'] & ~distinct_keys['_发运命中']).sum()),
            '三单齐全率': _pct(both_hits, valid_key_count),
            '发票金额': round(float(group['_金额'].sum()), 2),
            '三单齐全键对应发票金额': round(float(group.loc[group['_三单齐全'], '_金额'].sum()), 2),
            'OMS数据匹配能力': _data_capability(valid_key_count, order_hits, delivery_hits, both_hits),
            '当前AQPP处理结论': _aqpp_conclusion(aqpp_input_rows, both_hits),
        })

    summary = pd.DataFrame(rows, columns=OMS_MATCHABILITY_COLUMNS)
    all_valid_keys = work.loc[work['_键'].notna()].drop_duplicates('_键')
    total_valid = int(all_valid_keys['_键'].nunique())
    total_both = int(all_valid_keys['_三单齐全'].sum())
    total = pd.DataFrame([{
        '发票类型代码': '总计',
        '发票类型描述': 'OMS渠道发票清单总计',
        '政策处理方式': '',
        '清单行数': len(work),
        'SAP发票数': int(work['_发票号'].nunique()),
        '当前AQPP输入行数': int(work['_AQPP输入'].sum()),
        '匹配键完整行数': int(work['_键'].notna().sum()),
        '匹配键缺失行数': int(work['_键'].isna().sum()),
        '有效OMS订单物料键数': total_valid,
        '订单命中键数': int(all_valid_keys['_订单命中'].sum()),
        '发运命中键数': int(all_valid_keys['_发运命中'].sum()),
        '三单齐全键数': total_both,
        '仅订单无发运键数': int((all_valid_keys['_订单命中'] & ~all_valid_keys['_发运命中']).sum()),
        '仅发运无订单键数': int((~all_valid_keys['_订单命中'] & all_valid_keys['_发运命中']).sum()),
        '订单发运均未命中键数': int((~all_valid_keys['_订单命中'] & ~all_valid_keys['_发运命中']).sum()),
        '三单齐全率': _pct(total_both, total_valid),
        '发票金额': round(float(work['_金额'].sum()), 2),
        '三单齐全键对应发票金额': round(float(work.loc[work['_三单齐全'], '_金额'].sum()), 2),
        'OMS数据匹配能力': '汇总',
        '当前AQPP处理结论': '各类型结论见上表',
    }], columns=OMS_MATCHABILITY_COLUMNS)
    return pd.concat([summary, total], ignore_index=True)

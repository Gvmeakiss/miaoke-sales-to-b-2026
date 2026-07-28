# -*- coding: utf-8 -*-
"""输入字段及匹配键标准化工具。

所有函数均返回副本，不会原地修改调用方传入的 DataFrame。
"""

from __future__ import annotations

import pandas as pd


DELIVERY_AMOUNT_ALIASES = ('发货金额', '运输单金额', '交货单金额', 'delivery_amount')
DELIVERY_CURRENCY_ALIASES = ('发货币种', '运输单币种', '交货单币种', 'delivery_currency')
DELIVERY_UNIT_ALIASES = ('发货数量单位', '运输单数量单位', '交货单数量单位', 'delivery_unit')


def normalize_identifier(series: pd.Series) -> pd.Series:
    """把单号/编码转为可空字符串，去空格及Excel浮点尾缀“.0”。"""
    result = series.astype('string').str.strip()
    result = result.str.replace(r'\.0$', '', regex=True)
    return result.mask(result.eq(''))


def normalize_numeric(series: pd.Series) -> pd.Series:
    """安全转换数值；无法转换的值保留为 NaN，供后续缺失检查处理。"""
    return pd.to_numeric(series, errors='coerce')


def first_existing_column(df: pd.DataFrame, candidates, required=False, label='字段'):
    """按明确的候选顺序返回首个存在列；不做模糊包含匹配。"""
    for column in candidates:
        if column in df.columns:
            return column
    if required:
        raise ValueError(f'缺少{label}，候选字段为：{list(candidates)}')
    return None


def _copy_alias(df: pd.DataFrame, target: str, aliases, numeric=False) -> None:
    source = first_existing_column(df, aliases)
    if source is not None:
        df[target] = normalize_numeric(df[source]) if numeric else df[source].astype('string').str.strip()


def standardize_order_input(df: pd.DataFrame) -> pd.DataFrame:
    """标准化订单单号、物料、金额和数量；返回新 DataFrame。"""
    out = df.copy()
    for column in ('platform_order_no', 'main_order_no', 'sale_order_no', 'item_code'):
        if column in out.columns:
            out[column] = normalize_identifier(out[column])
    for column in ('line_amount', 'pay_amount', 'item_num'):
        if column in out.columns:
            out[column] = normalize_numeric(out[column])
    return out


def standardize_delivery_input(df: pd.DataFrame) -> pd.DataFrame:
    """标准化发运匹配键、数量，并在源字段存在时建立发运金额/币种/单位规范列。"""
    out = df.copy()
    for column in ('订单号', 'external_order_no', 'main_order_no', '主单号', '料号', 'document_no'):
        if column in out.columns:
            out[column] = normalize_identifier(out[column])
    if '已发货数量' in out.columns:
        out['已发货数量'] = normalize_numeric(out['已发货数量'])
    _copy_alias(out, '发货金额', DELIVERY_AMOUNT_ALIASES, numeric=True)
    _copy_alias(out, '发货币种', DELIVERY_CURRENCY_ALIASES)
    _copy_alias(out, '发货数量单位', DELIVERY_UNIT_ALIASES)
    return out


def standardize_invoice_input(df: pd.DataFrame) -> pd.DataFrame:
    """标准化发票关键字段，显式区分销售单位数量与基本单位数量。"""
    out = df.copy()
    for column in ('OMS销售单号', 'OMS出库单号', 'DMS销售单号', '物料编码'):
        if column in out.columns:
            out[column] = normalize_identifier(out[column])
    for column in (
        '含税金额', '无税金额', '实际金额（ZFN1）', '开票数量（销售单位）',
        '开票数量（基本单位数量）', '订单汇率',
    ):
        if column in out.columns:
            out[column] = normalize_numeric(out[column])

    # 2026发票表有重复“基本计量单位”表头，pandas通常将第二列命名为“.1”。
    # AQPP数量统一使用基本单位数量，因此优先取与开票基本数量相邻的第二列。
    _copy_alias(out, '标准-发票数量单位', ('基本计量单位.1', '基本计量单位'))
    _copy_alias(out, '标准-发票币种', ('订单币种', '发票币种'))
    return out

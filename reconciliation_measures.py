# -*- coding: utf-8 -*-
"""三单金额与数量口径构建。

函数返回副本。项目采用AQPP无交货金额模式：金额只比较SIV与SOV；
GDNV仅作为信息字段保留，缺失时不推算、不补零。
"""

from __future__ import annotations

import pandas as pd

from config import (
    ASSUME_BASE_CURRENCY_WHEN_ORDER_MISSING,
    ASSUME_BASIC_QUANTITY_UNIT,
    BASE_CURRENCY,
    OMS_FINANCE_CONFIRMED_CURRENCY_CONSISTENCY,
)
from data_standardization import first_existing_column, normalize_numeric


CHANNEL_COLUMNS = {
    'OMS': {
        'SIV': ('开票金额',),
        'SOV': ('订单金额',),
        'GDNV': ('发货金额', '运输单金额', '交货单金额'),
        'SIQ': ('开票数量',),
        'SOQ': ('订单数量',),
        'GDNQ': ('发货数量',),
    },
    'DMS': {
        'SIV': ('SAP开票含税金额',),
        'SOV': ('DMS订单金额',),
        'GDNV': ('DMS发货金额', '发货金额', '运输单金额', '交货单金额'),
        'SIQ': ('SAP开票基本数量',),
        'SOQ': ('DMS订单数量',),
        'GDNQ': ('DMS发货数量',),
    },
}

PRESENCE_COLUMNS = {
    'OMS': {
        '存在销售订单': ('订单金额', '订单数量', '订单-销售订单号', '订单-主订单号'),
        '存在发运单': ('发货数量', '发货-发货单号', '发货-订单号'),
        '存在销售发票': ('开票金额', '开票数量', 'OMS销售单号', '发票-SAP发票号'),
    },
    'DMS': {
        '存在销售订单': ('DMS订单金额', 'DMS订单数量', '订单-平台订单号'),
        '存在发运单': ('DMS发货数量', '发货-发货单号', '发货-外部订单号'),
        '存在销售发票': ('SAP开票含税金额', 'SAP开票基本数量', '发票-SAP发票号'),
    },
}


def _normalized_values(df, columns):
    """提取并标准化可用文本字段；空字符串按缺失处理。"""
    available = [column for column in columns if column in df.columns]
    if not available:
        return pd.DataFrame(index=df.index), available
    values = df[available].astype('string').apply(
        lambda col: col.str.strip().str.upper().replace('', pd.NA)
    )
    return values, available


def _currency_status(df, columns, finance_confirmed_when_missing=False):
    """币种完整时比较三方；源数据缺订单/发运币种时仅对CNY作明确假设。"""
    values, _ = _normalized_values(df, columns)
    if values.empty:
        return pd.Series('待确认-无币种字段', index=df.index, dtype='string')
    known_count = values.notna().sum(axis=1)
    conflict = values.nunique(axis=1, dropna=True).gt(1)
    non_base = values.apply(lambda col: col.notna() & col.ne(BASE_CURRENCY)).any(axis=1)
    complete = known_count.eq(len(columns))
    status = pd.Series('待确认-字段不完整', index=df.index, dtype='string')
    status.loc[known_count.eq(0)] = '待确认-无币种字段'
    status.loc[complete & ~conflict] = '一致'
    if ASSUME_BASE_CURRENCY_WHEN_ORDER_MISSING:
        assumed = known_count.gt(0) & ~complete & ~conflict & ~non_base
        status.loc[assumed] = '假定一致-订单发运未提供币种，按CNY'
    status.loc[known_count.gt(0) & ~complete & ~conflict & non_base] = '待确认-非本位币缺少订单发运币种'
    if finance_confirmed_when_missing:
        confirmed = known_count.gt(0) & ~complete & ~conflict & non_base
        status.loc[confirmed] = '财务确认一致-订单发运未提供币种，按发票币种'
    status.loc[conflict] = '不一致'
    return status


def _quantity_unit_status(df, columns):
    """单位完整时比较三方；字段缺失时仅按配置声明基本单位假设。"""
    values, _ = _normalized_values(df, columns)
    if values.empty:
        return pd.Series('待确认-无单位字段', index=df.index, dtype='string')
    known_count = values.notna().sum(axis=1)
    conflict = values.nunique(axis=1, dropna=True).gt(1)
    complete = known_count.eq(len(columns))
    status = pd.Series('待确认-字段不完整', index=df.index, dtype='string')
    status.loc[known_count.eq(0)] = '待确认-无单位字段'
    status.loc[complete & ~conflict] = '一致'
    if ASSUME_BASIC_QUANTITY_UNIT:
        status.loc[known_count.gt(0) & ~complete & ~conflict] = '假定一致-三方数量字段按基本单位'
    status.loc[conflict] = '不一致'
    return status


def build_three_way_measures(df: pd.DataFrame, channel: str) -> pd.DataFrame:
    """建立标准口径、三单存在标记和币种/单位校验状态并返回副本。"""
    channel = channel.upper()
    if channel not in CHANNEL_COLUMNS:
        raise ValueError(f'不支持的渠道：{channel}')
    out = df.copy()
    for target, candidates in CHANNEL_COLUMNS[channel].items():
        source = first_existing_column(out, candidates)
        out[target] = normalize_numeric(out[source]) if source else pd.Series(float('nan'), index=out.index)

    for target, candidates in PRESENCE_COLUMNS[channel].items():
        available = [column for column in candidates if column in out.columns]
        out[target] = out[available].notna().any(axis=1) if available else False

    # 无交货金额模式只要求SIV、SOV；GDNV不参与AQPP金额分类。
    out['AQPP金额口径完整'] = out[['SIV', 'SOV']].notna().all(axis=1)
    out['AQPP数量口径完整'] = out[['SIQ', 'SOQ', 'GDNQ']].notna().all(axis=1)
    out['币种校验状态'] = _currency_status(
        out,
        ('标准-发票币种', '订单币种', '发货币种'),
        finance_confirmed_when_missing=(
            channel == 'OMS' and OMS_FINANCE_CONFIRMED_CURRENCY_CONSISTENCY
        ),
    )
    out['数量单位校验状态'] = _quantity_unit_status(
        out,
        ('标准-发票数量单位', '订单数量单位', '发货数量单位'),
    )
    return out

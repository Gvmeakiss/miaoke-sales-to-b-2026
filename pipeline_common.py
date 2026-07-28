# -*- coding: utf-8 -*-
"""OMS/DMS共用的PKL读取、字段契约及渠道筛选工具。"""

from pathlib import Path

import pandas as pd


SOURCE_REQUIRED_COLUMNS = {
    '订单': ('platform_order_no', 'main_order_no', 'sale_order_no', 'order_status', 'item_code', 'pay_amount', 'item_num'),
    '发运': ('订单号', 'external_order_no', 'main_order_no', '料号', '已发货数量'),
    '发票': ('OMS销售单号', 'DMS销售单号', '物料编码', '发票类型', '含税金额', '实际金额（ZFN1）', '开票数量（基本单位数量）'),
}


def nonblank(series: pd.Series) -> pd.Series:
    """统一判断标识字段非空，兼容空字符串。"""
    return series.notna() & series.astype('string').str.strip().ne('')


def require_columns(df: pd.DataFrame, columns, label: str) -> None:
    """校验预处理PKL字段契约。"""
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise ValueError(f'{label}PKL缺少标准字段：{missing}；请重新运行preprocess_2026.py --force')


def load_preprocessed_sources(config: dict):
    """直接读取已标准化PKL，不在匹配阶段重复复制和标准化宽表。"""
    paths = {
        '订单': Path(config['order_pkl']),
        '发运': Path(config['delivery_pkl']),
        '发票': Path(config['invoice_pkl']),
    }
    for label, path in paths.items():
        if not path.exists():
            raise FileNotFoundError(f'未找到{label}PKL：{path}\n请先运行preprocess_2026.py')
    frames = {label: pd.read_pickle(path) for label, path in paths.items()}
    for label, frame in frames.items():
        require_columns(frame, SOURCE_REQUIRED_COLUMNS[label], label)
    return frames['订单'], frames['发运'], frames['发票']


def filter_order_status(df: pd.DataFrame, excluded_statuses) -> pd.DataFrame:
    """集中执行订单状态排除；只复制保留后的渠道工作集。"""
    return df.loc[~df['order_status'].isin(excluded_statuses)].copy()


def filter_target_year(df: pd.DataFrame, target_year: int, date_columns) -> pd.DataFrame:
    """未匹配附属集合按任一业务日期属于目标年度进行筛选。"""
    if df.empty:
        return df
    keep = pd.Series(False, index=df.index)
    for column in date_columns:
        if column in df.columns:
            keep |= pd.to_datetime(df[column], errors='coerce').dt.year.eq(target_year)
    return df.loc[keep]

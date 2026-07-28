#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 2026H1 的订单 SQL、发运 SQL、月度发票 Excel 标准化为三份 PKL。"""

from __future__ import annotations

import argparse
from pathlib import Path
import re

import pandas as pd

from data_standardization import (
    standardize_delivery_input,
    standardize_invoice_input,
    standardize_order_input,
)

from config import (
    DELIVERY_PKL,
    DELIVERY_SQL,
    INVOICE_DIR,
    INVOICE_PKL,
    ORDER_PKL,
    ORDER_SQL,
    PKL_DIR,
)

ORDER_COLUMNS = [
    'platform_order_no', 'main_order_no', 'sale_order_no', 'order_type',
    'order_status', 'create_time', 'update_time', 'channel_name', 'item_code',
    'line_amount', 'pay_amount', 'item_num',
]
DELIVERY_COLUMNS = [
    'business_type', '订单号', 'external_order_no', '业务时间', '料号', '名称',
    '已发货数量', 'document_no', 'main_order_no',
]
REQUIRED_INVOICE_COLUMNS = {
    'OMS销售单号', 'OMS出库单号', 'DMS销售单号', '物料编码',
    '含税金额', '实际金额（ZFN1）', '开票数量（基本单位数量）',
}


def parse_sql_value_line(line: str):
    line = line.strip().lstrip('\ufeff')
    if not line.upper().startswith('VALUES'):
        return None
    left, right = line.find('('), line.rfind(')')
    if left < 0 or right <= left:
        return None
    text = line[left + 1:right]
    values, current, quoted = [], [], False
    i = 0
    while i < len(text):
        char = text[i]
        if char == "'":
            if quoted and i + 1 < len(text) and text[i + 1] == "'":
                current.append("'")
                i += 1
            else:
                quoted = not quoted
        elif char == ',' and not quoted:
            token = ''.join(current).strip()
            values.append(None if token.upper() == 'NULL' else token)
            current = []
        else:
            current.append(char)
        i += 1
    token = ''.join(current).strip()
    values.append(None if token.upper() == 'NULL' else token)
    return values


def read_sql(path: Path, columns: list[str]) -> pd.DataFrame:
    rows = []
    with path.open('r', encoding='utf-16', errors='strict') as handle:
        for line_number, line in enumerate(handle, 1):
            values = parse_sql_value_line(line)
            if values is None:
                continue
            if len(values) != len(columns):
                raise ValueError(
                    f'{path.name} 第 {line_number} 行字段数为 {len(values)}，预期 {len(columns)}'
                )
            rows.append(values)
    if not rows:
        raise ValueError(f'{path} 未解析到任何 VALUES 数据')
    return pd.DataFrame(rows, columns=columns)


def normalize_order(df: pd.DataFrame) -> pd.DataFrame:
    for column in ['line_amount', 'pay_amount', 'item_num']:
        df[column] = pd.to_numeric(df[column], errors='coerce')
    for column in ['create_time', 'update_time']:
        df[column] = pd.to_datetime(df[column], errors='coerce')
    return standardize_order_input(df)


def normalize_delivery(df: pd.DataFrame) -> pd.DataFrame:
    df['已发货数量'] = pd.to_numeric(df['已发货数量'], errors='coerce')
    df['业务时间'] = pd.to_datetime(df['业务时间'], errors='coerce')
    # 匹配脚本使用“主单号”；保留原字段的同时提供兼容列。
    df['主单号'] = df['main_order_no']
    return standardize_delivery_input(df)


def invoice_files() -> list[Path]:
    files = sorted(INVOICE_DIR.glob('2026-*.XLSX'))
    expected = {f'2026-{month:02d}.XLSX' for month in range(1, 7)}
    actual = {path.name for path in files}
    if actual != expected:
        raise FileNotFoundError(
            f'发票文件不完整；缺少={sorted(expected - actual)}，多出={sorted(actual - expected)}'
        )
    return files


def read_invoices() -> pd.DataFrame:
    frames, canonical_columns = [], None
    for path in invoice_files():
        print(f'  读取发票 {path.name} ...')
        frame = pd.read_excel(path, engine='openpyxl', dtype={
            'OMS销售单号': 'string', 'OMS出库单号': 'string',
            'DMS销售单号': 'string', '物料编码': 'string',
        })
        if canonical_columns is None:
            canonical_columns = list(frame.columns)
        elif list(frame.columns) != canonical_columns:
            raise ValueError(f'{path.name} 的表头或列顺序与其他月份不一致')
        frame['数据源文件'] = path.name
        frames.append(frame)
    result = pd.concat(frames, ignore_index=True)
    missing = REQUIRED_INVOICE_COLUMNS - set(result.columns)
    if missing:
        raise ValueError(f'发票清单缺少关键字段：{sorted(missing)}')
    return standardize_invoice_input(result)


def validate_sources_only() -> None:
    for path in [ORDER_SQL, DELIVERY_SQL]:
        if not path.exists():
            raise FileNotFoundError(path)
    files = invoice_files()
    order_header = ORDER_SQL.read_text(encoding='utf-16', errors='strict')[:1000]
    delivery_header = DELIVERY_SQL.read_text(encoding='utf-16', errors='strict')[:1000]
    for expected in ORDER_COLUMNS:
        if not re.search(rf'\b{re.escape(expected)}\b', order_header):
            raise ValueError(f'订单 SQL 头部缺少字段 {expected}')
    for expected in DELIVERY_COLUMNS:
        if expected not in delivery_header:
            raise ValueError(f'发运 SQL 头部缺少字段 {expected}')
    sample = pd.read_excel(files[0], engine='openpyxl', nrows=2)
    missing = REQUIRED_INVOICE_COLUMNS - set(sample.columns)
    if missing:
        raise ValueError(f'发票清单缺少关键字段：{sorted(missing)}')
    print('源文件结构验证通过。')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--validate-only', action='store_true', help='只验证文件及字段，不生成 PKL')
    parser.add_argument('--force', action='store_true', help='即使 PKL 已存在也重新生成')
    args = parser.parse_args()

    validate_sources_only()
    if args.validate_only:
        return

    PKL_DIR.mkdir(parents=True, exist_ok=True)
    if args.force or not ORDER_PKL.exists():
        print('解析订单 SQL ...')
        order = normalize_order(read_sql(ORDER_SQL, ORDER_COLUMNS))
        order.to_pickle(ORDER_PKL)
        print(f'  订单：{len(order):,} 行 -> {ORDER_PKL}')
    else:
        print(f'订单 PKL 已存在，跳过：{ORDER_PKL}')

    if args.force or not DELIVERY_PKL.exists():
        print('解析发运 SQL ...')
        delivery = normalize_delivery(read_sql(DELIVERY_SQL, DELIVERY_COLUMNS))
        delivery.to_pickle(DELIVERY_PKL)
        print(f'  发运：{len(delivery):,} 行 -> {DELIVERY_PKL}')
    else:
        print(f'发运 PKL 已存在，跳过：{DELIVERY_PKL}')

    if args.force or not INVOICE_PKL.exists():
        print('合并月度发票 Excel ...')
        invoice = read_invoices()
        invoice.to_pickle(INVOICE_PKL)
        print(f'  发票：{len(invoice):,} 行 -> {INVOICE_PKL}')
    else:
        print(f'发票 PKL 已存在，跳过：{INVOICE_PKL}')


if __name__ == '__main__':
    main()

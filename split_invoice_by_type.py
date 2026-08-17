#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""将原始发票PKL按发票类型分卷，流式生成Excel。"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd
try:
    import xlsxwriter
except ImportError as exc:
    raise ImportError('拆分发票清单需要 XlsxWriter，请先执行：python3 -m pip install XlsxWriter') from exc

from config import INVOICE_PKL


CODE_DIR = Path(__file__).resolve().parent
BASE_DIR = CODE_DIR.parent
OUTPUT_DIR = BASE_DIR / 'output' / '2026H1' / '原始发票清单按类型拆分'
MAX_DATA_ROWS = 1_048_575


def safe_name(value) -> str:
    """生成安全文件名。"""
    text = '未知类型' if pd.isna(value) or not str(value).strip() else str(value).strip()
    return re.sub(r'[\\/:*?"<>|]', '_', text)


def excel_value(value):
    """将 pandas/numpy 标量转换为 XlsxWriter 可写值；空值写为空白。"""
    if pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if isinstance(value, np.generic):
        return value.item()
    return value


def write_workbook(frame: pd.DataFrame, path: Path) -> None:
    """以恒定内存写出单个发票明细工作簿，不修改输入 DataFrame。"""
    workbook = xlsxwriter.Workbook(path, {
        'constant_memory': True,
        'strings_to_urls': False,
        'nan_inf_to_errors': True,
    })
    # 宽表在压缩前的工作表 XML 可能超过 4GB，启用 Excel 兼容的 ZIP64 容器。
    workbook.use_zip64()
    worksheet = workbook.add_worksheet('发票清单')
    header_fmt = workbook.add_format({
        'bold': True, 'font_color': '#FFFFFF', 'bg_color': '#1F4E78',
        'border': 1, 'align': 'center', 'valign': 'vcenter',
    })
    amount_fmt = workbook.add_format({'num_format': '#,##0.00;[Red]-#,##0.00'})
    quantity_fmt = workbook.add_format({'num_format': '#,##0.00;[Red]-#,##0.00'})
    date_fmt = workbook.add_format({'num_format': 'yyyy-mm-dd'})

    worksheet.hide_gridlines(2)
    worksheet.freeze_panes(1, 0)
    worksheet.set_row(0, 28)
    worksheet.write_row(0, 0, frame.columns.tolist(), header_fmt)
    worksheet.autofilter(0, 0, len(frame), len(frame.columns) - 1)

    for col_no, column in enumerate(frame.columns):
        name = str(column)
        width = min(24, max(12, len(name) * 2 + 2))
        fmt = None
        if '金额' in name or '价' in name or '税额' in name:
            fmt = amount_fmt
        elif '数量' in name:
            fmt = quantity_fmt
        elif '日期' in name or name.endswith('日'):
            fmt = date_fmt
        worksheet.set_column(col_no, col_no, width, fmt)

    for row_no, row in enumerate(frame.itertuples(index=False, name=None), start=1):
        worksheet.write_row(row_no, 0, [excel_value(value) for value in row])
    workbook.close()


def main() -> None:
    invoice = pd.read_pickle(INVOICE_PKL)
    if '发票类型' not in invoice.columns:
        raise ValueError('原始发票清单缺少“发票类型”字段')
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    type_key = invoice['发票类型'].astype('string').fillna('未知类型').str.strip().replace('', '未知类型')
    invoice = invoice.assign(_拆分发票类型=type_key)
    results = []
    for invoice_type, frame in invoice.groupby('_拆分发票类型', sort=True, dropna=False):
        description = frame['发票类型.1'].dropna().astype(str).str.strip().replace('', pd.NA).dropna()
        description_text = description.iloc[0] if not description.empty else '无描述'
        frame = frame.drop(columns=['_拆分发票类型'])
        part_count = (len(frame) + MAX_DATA_ROWS - 1) // MAX_DATA_ROWS
        for part_no, start in enumerate(range(0, len(frame), MAX_DATA_ROWS), start=1):
            part = frame.iloc[start:start + MAX_DATA_ROWS]
            suffix = f'_第{part_no}卷' if part_count > 1 else ''
            stem = f"发票类型_{safe_name(invoice_type)}_{safe_name(description_text)}{suffix}"
            xlsx_path = OUTPUT_DIR / f'{stem}.xlsx'
            write_workbook(part, xlsx_path)
            results.append((str(invoice_type), description_text, part_no, len(part), xlsx_path.name))
            print(f'已生成：{xlsx_path.name}（{len(part):,}行）', flush=True)

    manifest = pd.DataFrame(results, columns=['发票类型', '发票类型描述', '分卷', '数据行数', '文件名'])
    manifest.to_csv(OUTPUT_DIR / '拆分文件清单.csv', index=False, encoding='utf-8-sig')
    print(f'拆分完成：{len(results)}个Excel，合计{manifest["数据行数"].sum():,}行')


if __name__ == '__main__':
    main()

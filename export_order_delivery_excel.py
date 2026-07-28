#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把现有订单、发运 PKL 导出为 Excel；单文件超过 100 万行时自动拆分。"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import pandas as pd

from config import DELIVERY_PKL, ORDER_PKL, OUTPUT_DIR, OUTPUT_PREFIX

# Excel 理论上限约 1,048,575 行（含表头）；业务约定超过 100 万数据行即拆分。
MAX_ROWS_PER_FILE = 1_000_000


def _export_chunks(df: pd.DataFrame, out_dir: Path, stem: str, max_rows: int) -> list[Path]:
    """按 max_rows 切分写入一个或多个 xlsx，返回生成路径列表。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    total = len(df)
    if total == 0:
        path = out_dir / f'{stem}.xlsx'
        pd.DataFrame(columns=list(df.columns)).to_excel(path, index=False)
        print(f'  {stem}: 0 行 -> {path.name}')
        return [path]

    parts = max(1, math.ceil(total / max_rows))
    written: list[Path] = []
    for index in range(parts):
        start = index * max_rows
        end = min(start + max_rows, total)
        chunk = df.iloc[start:end]
        if parts == 1:
            path = out_dir / f'{stem}.xlsx'
        else:
            path = out_dir / f'{stem}_part{index + 1:03d}_共{parts}份.xlsx'
        print(f'  写入 {path.name}（{len(chunk):,} 行）...')
        chunk.to_excel(path, index=False, engine='openpyxl')
        written.append(path)
    if parts > 1:
        print(f'  {stem}: 共 {total:,} 行，已拆成 {parts} 个文件（每文件最多 {max_rows:,} 行）')
    else:
        print(f'  {stem}: {total:,} 行 -> {written[0].name}（未超 {max_rows:,}，无需拆分）')
    return written


def main():
    parser = argparse.ArgumentParser(description='导出订单/发运清单为 Excel，超 100 万行自动拆分')
    parser.add_argument(
        '--max-rows',
        type=int,
        default=MAX_ROWS_PER_FILE,
        help=f'单文件最大数据行数，默认 {MAX_ROWS_PER_FILE}',
    )
    parser.add_argument(
        '--out-dir',
        type=Path,
        default=None,
        help='输出目录，默认 output/2026H1/原始清单',
    )
    args = parser.parse_args()
    if args.max_rows <= 0:
        raise ValueError('--max-rows 必须为正整数')

    out_dir = args.out_dir or (OUTPUT_DIR / '原始清单')
    print(f'输出目录: {out_dir}')
    print(f'单文件上限: {args.max_rows:,} 行')

    for label, pkl_path, stem in (
        ('订单', ORDER_PKL, f'{OUTPUT_PREFIX}订单清单'),
        ('发运', DELIVERY_PKL, f'{OUTPUT_PREFIX}发运单清单'),
    ):
        if not pkl_path.exists():
            raise FileNotFoundError(f'未找到{label} PKL: {pkl_path}\n请先运行 preprocess_2026.py')
        print(f'\n读取{label}: {pkl_path}')
        frame = pd.read_pickle(pkl_path)
        print(f'  {label}行数: {len(frame):,}，列数: {len(frame.columns)}')
        _export_chunks(frame, out_dir, stem, args.max_rows)

    print('\n订单、发运 Excel 导出完成。')


if __name__ == '__main__':
    main()

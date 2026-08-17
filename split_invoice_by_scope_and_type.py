#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按原始PBC渠道归属和发票类型拆分发票清单。

本脚本只执行“匹配前范围路由”，不应用发票类型参与政策、不执行冲销净额化，
也不因OMS订单号/物料号缺失而改变渠道归属。所有原始发票行只会进入一个范围，
并在该范围内按发票类型分别导出Excel；超过Excel行数上限时自动分卷。

函数均不修改调用方传入的DataFrame；主程序只读取标准化发票PKL并写入独立输出目录。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import xlsxwriter

from config import (
    INVOICE_DESCRIPTION_RULES,
    INVOICE_PKL,
    INVOICE_TYPE_RULES,
    PBC_INVOICE_SCOPE_DEFAULT,
    PBC_INVOICE_SCOPE_TYPES,
)
from data_standardization import normalize_identifier, normalize_numeric
from split_invoice_by_type import MAX_DATA_ROWS, safe_name, write_workbook


CODE_DIR = Path(__file__).resolve().parent
BASE_DIR = CODE_DIR.parent
OUTPUT_DIR = BASE_DIR / 'output' / '2026H1' / '发票清单按匹配范围及类型拆分'

SCOPE_FOLDERS = {
    'ToB-DMS': '01_ToB-DMS匹配范围',
    'ToB-OMS': '02_ToB-OMS匹配范围',
    'ToC': '03_ToC非三单范围',
    '其他': '04_其他非三单范围',
}

SCOPE_ORDER = tuple(SCOPE_FOLDERS)
SCOPE_DESCRIPTIONS = {
    'ToB-DMS': 'DMS销售单号非空，优先归入DMS；不受发票类型、冲销状态或关键键完整性影响',
    'ToB-OMS': 'DMS销售单号为空，且发票类型属于配置的OMS原始PBC范围',
    'ToC': 'DMS销售单号为空，且发票类型为ZA02',
    '其他': 'DMS销售单号为空，且属于其他业务类型；未配置/缺失类型也默认归入此范围',
}


def _validate_scope_config() -> None:
    """校验非DMS类型集合互斥，防止同一原始行被重复分配。"""
    seen: dict[str, str] = {}
    for scope, invoice_types in PBC_INVOICE_SCOPE_TYPES.items():
        for invoice_type in invoice_types:
            previous = seen.get(invoice_type)
            if previous is not None:
                raise ValueError(f'发票类型{invoice_type}同时配置在{previous}和{scope}')
            seen[invoice_type] = scope


def classify_invoice_scope(invoice: pd.DataFrame) -> pd.Series:
    """返回每行原始发票的唯一PBC范围，不修改输入DataFrame。

    参数：
        invoice: 至少包含“DMS销售单号”和“发票类型”的原始发票明细。

    返回：
        与输入索引一致的字符串Series，取值为ToB-DMS、ToB-OMS、ToC或其他。

    空值及异常值：
        DMS销售单号空字符串按缺失处理；缺失、空白或未配置的发票类型归入“其他”。
    """
    missing = [column for column in ('DMS销售单号', '发票类型') if column not in invoice.columns]
    if missing:
        raise ValueError(f'原始发票清单缺少范围拆分字段：{missing}')
    _validate_scope_config()

    dms_order = normalize_identifier(invoice['DMS销售单号'])
    invoice_type = normalize_identifier(invoice['发票类型'])
    scope = pd.Series(PBC_INVOICE_SCOPE_DEFAULT, index=invoice.index, dtype='string')

    # DMS优先级最高：即使其发票类型属于OMS/ToC/其他清单，也仍按DMS渠道归属。
    dms_mask = dms_order.notna()
    scope.loc[dms_mask] = 'ToB-DMS'

    non_dms = ~dms_mask
    for target_scope in ('ToB-OMS', 'ToC', '其他'):
        type_set = PBC_INVOICE_SCOPE_TYPES.get(target_scope, set())
        scope.loc[non_dms & invoice_type.isin(type_set)] = target_scope
    return scope


def _numeric_sum(frame: pd.DataFrame, column: str) -> float:
    """安全汇总数值列；字段不存在或全为空时返回0。"""
    if column not in frame.columns:
        return 0.0
    return float(normalize_numeric(frame[column]).fillna(0).sum())


def _invoice_count(frame: pd.DataFrame) -> int:
    """按SAP发票号去重计数；字段不存在时返回0。"""
    if 'SAP发票号' not in frame.columns:
        return 0
    return int(normalize_identifier(frame['SAP发票号']).nunique(dropna=True))


def _type_description(frame: pd.DataFrame, invoice_type: str) -> str:
    """优先采用原始描述，缺失时回退集中配置。"""
    if '发票类型.1' in frame.columns:
        values = normalize_identifier(frame['发票类型.1']).dropna()
        if not values.empty:
            return str(values.iloc[0])
    rule = INVOICE_TYPE_RULES.get(invoice_type, {})
    if rule.get('business'):
        return str(rule['business'])
    for description, code in INVOICE_DESCRIPTION_RULES.items():
        if code == invoice_type:
            return description
    return '未配置/待确认'


def _summary_record(scope: str, frame: pd.DataFrame, file_count: int) -> dict:
    """生成范围级核对记录，不修改输入DataFrame。"""
    return {
        '匹配范围': scope,
        '是否属于三单匹配渠道': '是' if scope in {'ToB-DMS', 'ToB-OMS'} else '否',
        '范围划分依据': SCOPE_DESCRIPTIONS[scope],
        '清单行数': int(len(frame)),
        'SAP发票数': _invoice_count(frame),
        '开票数量（基本单位）': _numeric_sum(frame, '开票数量（基本单位数量）'),
        '发票不含税金额': _numeric_sum(frame, '无税金额'),
        '发票含税金额': _numeric_sum(frame, '含税金额'),
        'OMS实际金额（ZFN1）': _numeric_sum(frame, '实际金额（ZFN1）'),
        '拆分文件数': int(file_count),
    }


def _write_manifest(scope_summary: pd.DataFrame, file_manifest: pd.DataFrame, path: Path) -> None:
    """写出格式化核对工作簿；公式总计附带缓存值，便于不开Excel也能复核。"""
    workbook = xlsxwriter.Workbook(path)
    workbook.set_properties({
        'title': '发票清单按匹配范围及类型拆分核对',
        'subject': '原始PBC完整性核对',
        'comments': '仅做匹配前渠道归属，不执行冲销、类型政策或关键键筛选',
    })
    header = workbook.add_format({
        'bold': True, 'font_color': '#FFFFFF', 'bg_color': '#1F4E78',
        'align': 'center', 'valign': 'vcenter', 'border': 1,
    })
    title = workbook.add_format({
        'bold': True, 'font_color': '#FFFFFF', 'bg_color': '#17365D',
        'font_size': 14, 'align': 'left', 'valign': 'vcenter',
    })
    text_fmt = workbook.add_format({'align': 'left', 'valign': 'top', 'text_wrap': True})
    int_fmt = workbook.add_format({'num_format': '#,##0', 'align': 'right'})
    num_fmt = workbook.add_format({'num_format': '#,##0.00;[Red](#,##0.00);-', 'align': 'right'})
    total_text = workbook.add_format({'bold': True, 'font_color': '#C00000', 'top': 1})
    total_int = workbook.add_format({'bold': True, 'font_color': '#C00000', 'top': 1, 'num_format': '#,##0'})
    total_num = workbook.add_format({'bold': True, 'font_color': '#C00000', 'top': 1, 'num_format': '#,##0.00;[Red](#,##0.00);-'})

    def write_table(sheet_name: str, frame: pd.DataFrame, title_text: str, total_columns: set[str]) -> None:
        ws = workbook.add_worksheet(sheet_name)
        ws.hide_gridlines(2)
        ws.freeze_panes(2, 0)
        ws.merge_range(0, 0, 0, len(frame.columns) - 1, title_text, title)
        ws.set_row(0, 26)
        ws.set_row(1, 26)
        for col, name in enumerate(frame.columns):
            ws.write(1, col, name, header)
            width = min(60, max(14, len(str(name)) * 2 + 2))
            if name in {'范围划分依据', '相对路径', '文件名', '发票类型描述'}:
                width = 42
            ws.set_column(col, col, width)
        for row_no, row in enumerate(frame.itertuples(index=False, name=None), start=2):
            ws.set_row(row_no, 30)
            for col_no, value in enumerate(row):
                name = str(frame.columns[col_no])
                if pd.isna(value):
                    ws.write_blank(row_no, col_no, None)
                elif name in total_columns:
                    fmt = int_fmt if name in {'清单行数', 'SAP发票数', '拆分文件数', '分卷'} else num_fmt
                    ws.write_number(row_no, col_no, float(value), fmt)
                else:
                    ws.write(row_no, col_no, value, text_fmt)
        ws.autofilter(1, 0, len(frame) + 1, len(frame.columns) - 1)

    write_table(
        '范围汇总', scope_summary,
        '原始发票PBC范围汇总（冲销及关键键缺失不改变归属）',
        {'清单行数', 'SAP发票数', '开票数量（基本单位）', '发票不含税金额', '发票含税金额', 'OMS实际金额（ZFN1）', '拆分文件数'},
    )
    ws = workbook.get_worksheet_by_name('范围汇总')
    total_row = len(scope_summary) + 2
    ws.write(total_row, 0, '总计', total_text)
    for col_no, name in enumerate(scope_summary.columns):
        if name not in {'清单行数', 'SAP发票数', '开票数量（基本单位）', '发票不含税金额', '发票含税金额', 'OMS实际金额（ZFN1）', '拆分文件数'}:
            continue
        first = xlsxwriter.utility.xl_rowcol_to_cell(2, col_no)
        last = xlsxwriter.utility.xl_rowcol_to_cell(total_row - 1, col_no)
        cached = float(scope_summary[name].sum())
        fmt = total_int if name in {'清单行数', 'SAP发票数', '拆分文件数'} else total_num
        ws.write_formula(total_row, col_no, f'=SUM({first}:{last})', fmt, cached)

    write_table(
        '类型文件清单', file_manifest,
        '各范围按发票类型拆分文件清单',
        {'分卷', '清单行数', 'SAP发票数', '开票数量（基本单位）', '发票不含税金额', '发票含税金额', 'OMS实际金额（ZFN1）'},
    )

    notes = workbook.add_worksheet('口径说明')
    notes.hide_gridlines(2)
    notes.set_column('A:A', 22)
    notes.set_column('B:B', 100)
    notes.write('A1', '项目', header)
    notes.write('B1', '说明', header)
    note_rows = [
        ('拆分目的', '用于原始SAP发票PBC完整性核对；每一行只进入一个范围和一个发票类型文件。'),
        ('处理边界', '不应用发票类型AQPP参与政策，不执行冲销配对/净额化，不检查OMS订单号或物料号是否完整。'),
        ('DMS优先', SCOPE_DESCRIPTIONS['ToB-DMS']),
        ('OMS范围', SCOPE_DESCRIPTIONS['ToB-OMS']),
        ('To C范围', SCOPE_DESCRIPTIONS['ToC']),
        ('其他范围', SCOPE_DESCRIPTIONS['其他']),
        ('金额字段', '含税金额和无税金额用于原始PBC核对；OMS实际金额（ZFN1）是OMS AQPP主金额，仅并列展示，不替代含税总额。'),
        ('完整性控制', '范围汇总总计必须与原始发票PKL的行数、数量及三个金额字段一致。'),
    ]
    for row_no, (item, explanation) in enumerate(note_rows, start=1):
        notes.write(row_no, 0, item, text_fmt)
        notes.write(row_no, 1, explanation, text_fmt)
    workbook.close()


def main() -> None:
    """读取原始发票PKL，按匹配前归属拆分并生成完整性核对表。"""
    invoice = pd.read_pickle(INVOICE_PKL)
    scope = classify_invoice_scope(invoice)
    if scope.isna().any() or not scope.isin(SCOPE_ORDER).all():
        raise ValueError('存在未能唯一分配的原始发票行')

    # 目标目录只存放本脚本的生成物；重跑时清理旧分卷，避免旧文件混入核对范围。
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    file_records: list[dict] = []
    summary_records: list[dict] = []
    for scope_name in SCOPE_ORDER:
        scope_dir = OUTPUT_DIR / SCOPE_FOLDERS[scope_name]
        scope_dir.mkdir(parents=True, exist_ok=True)
        scope_frame = invoice.loc[scope.eq(scope_name)]
        type_key = normalize_identifier(scope_frame['发票类型']).fillna('未知类型')
        scope_with_type = scope_frame.assign(_拆分发票类型=type_key)
        scope_file_count = 0

        for invoice_type, typed_frame in scope_with_type.groupby('_拆分发票类型', sort=True, dropna=False):
            invoice_type = str(invoice_type)
            typed_frame = typed_frame.drop(columns=['_拆分发票类型'])
            description = _type_description(typed_frame, invoice_type)
            part_count = max(1, (len(typed_frame) + MAX_DATA_ROWS - 1) // MAX_DATA_ROWS)
            for part_no, start in enumerate(range(0, len(typed_frame), MAX_DATA_ROWS), start=1):
                part = typed_frame.iloc[start:start + MAX_DATA_ROWS]
                suffix = f'_第{part_no}卷' if part_count > 1 else ''
                filename = f'发票类型_{safe_name(invoice_type)}_{safe_name(description)}{suffix}.xlsx'
                path = scope_dir / filename
                write_workbook(part, path)
                scope_file_count += 1
                file_records.append({
                    '匹配范围': scope_name,
                    '是否属于三单匹配渠道': '是' if scope_name in {'ToB-DMS', 'ToB-OMS'} else '否',
                    '发票类型代码': invoice_type,
                    '发票类型描述': description,
                    '分卷': part_no,
                    '清单行数': int(len(part)),
                    'SAP发票数': _invoice_count(part),
                    '开票数量（基本单位）': _numeric_sum(part, '开票数量（基本单位数量）'),
                    '发票不含税金额': _numeric_sum(part, '无税金额'),
                    '发票含税金额': _numeric_sum(part, '含税金额'),
                    'OMS实际金额（ZFN1）': _numeric_sum(part, '实际金额（ZFN1）'),
                    '文件名': filename,
                    '相对路径': str(path.relative_to(OUTPUT_DIR)),
                })
                print(f'已生成：{scope_name}/{filename}（{len(part):,}行）', flush=True)
        summary_records.append(_summary_record(scope_name, scope_frame, scope_file_count))

    scope_summary = pd.DataFrame(summary_records)
    file_manifest = pd.DataFrame(file_records)
    scope_summary.to_csv(
        OUTPUT_DIR / '范围汇总.csv', index=False, encoding='utf-8-sig', float_format='%.2f'
    )
    file_manifest.to_csv(
        OUTPUT_DIR / '类型文件清单.csv', index=False, encoding='utf-8-sig', float_format='%.2f'
    )
    _write_manifest(scope_summary, file_manifest, OUTPUT_DIR / '拆分清单及口径核对.xlsx')

    expected_rows = len(invoice)
    exported_rows = int(scope_summary['清单行数'].sum())
    if exported_rows != expected_rows:
        raise AssertionError(f'拆分行数不勾稽：输出{exported_rows:,}，原始{expected_rows:,}')
    for column, label in (
        ('无税金额', '发票不含税金额'),
        ('含税金额', '发票含税金额'),
        ('实际金额（ZFN1）', 'OMS实际金额（ZFN1）'),
    ):
        source_total = _numeric_sum(invoice, column)
        output_total = float(scope_summary[label].sum())
        if abs(source_total - output_total) > 0.01:
            raise AssertionError(f'{label}不勾稽：输出{output_total:.2f}，原始{source_total:.2f}')
    print(f'拆分完成：{len(file_manifest)}个明细Excel，合计{exported_rows:,}行；行数及金额均与原始发票PKL一致。')


if __name__ == '__main__':
    main()

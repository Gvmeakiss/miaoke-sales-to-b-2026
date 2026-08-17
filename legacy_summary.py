# -*- coding: utf-8 -*-
"""按 FY25 展示结构生成兼容汇总表，同时保留完整 AQPP Not Test 场景。"""

from __future__ import annotations

import pandas as pd

from aqpp_scenarios import NOT_TEST_DESCRIPTIONS
from config import AMOUNT_TAIL_TOLERANCE, AMOUNT_TOLERANCE, QUANTITY_TOLERANCE
from tolerance_utils import absolute_less_than, equal_with_tolerance, greater_with_tolerance


LEGACY_SUMMARY_COLUMNS = [
    '分类', '小分类', '记录数', '占比', '发票金额', '发票金额占比',
    '订单发票金额差异', '差异占发票小记比例',
]

LEGACY_CODE_TO_MAIN = {
    '10': '1.完全匹配',
    '8': '2.数量一致金额有差异',
    '9': '2.数量一致金额有差异',
    '3': '3.金额一致数量有差异',
    '6': '3.金额一致数量有差异',
    '11': '3.金额一致数量有差异',
    '1': '4.均有差异',
    '2': '4.均有差异',
    '4': '4.均有差异',
    '5': '4.均有差异',
    '12': '4.均有差异',
    '13': '4.均有差异',
}

MAIN_ROWS = (
    '1.完全匹配',
    '2.数量一致金额有差异',
    '3.金额一致数量有差异',
    '4.均有差异',
)

SUB_ROWS = {
    '1.完全匹配': ('1.1 尾差≤0.01',),
    '2.数量一致金额有差异': ('2.1 尾差<1', '2.2 其他'),
    '3.金额一致数量有差异': (),
    '4.均有差异': (
        '4.1 未完全发货', '4.2 未完全开票', '4.3 过量发货',
        '4.4 预制发票', '4.5 其他',
    ),
}

NT_CODES = ('NT-00', 'NT-28', 'NT-29', 'NT-30', 'NT-31', 'NT-32', 'NT-33')

EXTRA_CATEGORY_TO_NT = {
    '仅订单': 'NT-28',
    '仅发货单': 'NT-29',
    '仅发运单': 'NT-29',
    '仅订单及发货单': 'NT-31',
    '仅订单及发运单': 'NT-31',
    '仅发票': 'NT-30',
}


def _numeric(frame: pd.DataFrame, column: str | None) -> pd.Series:
    if column and column in frame.columns:
        return pd.to_numeric(frame[column], errors='coerce').fillna(0)
    return pd.Series(0.0, index=frame.index, dtype='float64')


def _amount_series(frame: pd.DataFrame, amount_col: str | None) -> pd.Series:
    candidates = (
        amount_col, '开票金额', 'SAP开票含税金额', '含税金额', '实际金额（ZFN1）'
    )
    selected = next((column for column in candidates if column and column in frame.columns), None)
    return _numeric(frame, selected)


def _difference_series(
    frame: pd.DataFrame,
    order_inv_diff_col: str | None,
    inv_minus_order_col: str | None,
) -> pd.Series:
    """统一为订单金额减发票金额；单据缺失导致的空值按0展示为“-”。"""
    if order_inv_diff_col and order_inv_diff_col in frame.columns:
        return _numeric(frame, order_inv_diff_col)
    if inv_minus_order_col and inv_minus_order_col in frame.columns:
        return -_numeric(frame, inv_minus_order_col)
    if '订单-发票金额' in frame.columns:
        return _numeric(frame, '订单-发票金额')
    if 'SAP-DMS订单金额' in frame.columns:
        return -_numeric(frame, 'SAP-DMS订单金额')
    return pd.Series(0.0, index=frame.index, dtype='float64')


def _build_narrow_source(
    df_data: pd.DataFrame,
    amount_col: str | None,
    order_inv_diff_col: str | None,
    inv_minus_order_col: str | None,
) -> pd.DataFrame:
    """只复制汇总字段，避免对宽表做完整副本。"""
    work = pd.DataFrame(index=df_data.index)
    eligible = df_data.get(
        'AQPP可分类',
        df_data.get('AQPP分类', pd.Series('Not Test', index=df_data.index)).ne('Not Test'),
    ).fillna(False).astype(bool)
    legacy_code = df_data.get(
        '去年场景编码', pd.Series(pd.NA, index=df_data.index, dtype='string')
    ).astype('string').str.replace(r'\.0$', '', regex=True)
    aqpp_code = df_data.get(
        'AQPP场景编码', pd.Series('NT-00', index=df_data.index, dtype='string')
    ).astype('string')

    work['_AQPP可分类'] = eligible
    work['_大类'] = legacy_code.map(LEGACY_CODE_TO_MAIN).where(eligible)
    work['_小分类'] = pd.Series(pd.NA, index=work.index, dtype='string')
    work['_NT编码'] = aqpp_code.where(~eligible, pd.NA)
    work.loc[~eligible & ~work['_NT编码'].isin(NT_CODES), '_NT编码'] = 'NT-00'
    work['_发票金额'] = _amount_series(df_data, amount_col)
    work['_金额差异'] = _difference_series(
        df_data, order_inv_diff_col, inv_minus_order_col
    )

    siq = _numeric(df_data, 'SIQ')
    soq = _numeric(df_data, 'SOQ')
    gdnq = _numeric(df_data, 'GDNQ')
    amount_abs = work['_金额差异'].abs()

    # 完全匹配中的非零尾差是父类的披露子集，不参与小记的再次加总。
    exact_tail = (
        work['_大类'].eq('1.完全匹配')
        & amount_abs.gt(1e-12)
        & absolute_less_than(amount_abs, AMOUNT_TOLERANCE)
    )
    work.loc[exact_tail, '_小分类'] = '1.1 尾差≤0.01'

    category_2 = work['_大类'].eq('2.数量一致金额有差异')
    tail_lt_one = absolute_less_than(amount_abs, AMOUNT_TAIL_TOLERANCE)
    work.loc[category_2 & tail_lt_one, '_小分类'] = '2.1 尾差<1'
    work.loc[category_2 & ~tail_lt_one, '_小分类'] = '2.2 其他'

    category_4 = work['_大类'].eq('4.均有差异')
    order_gt_delivery = greater_with_tolerance(soq, gdnq, QUANTITY_TOLERANCE)
    order_lt_delivery = greater_with_tolerance(gdnq, soq, QUANTITY_TOLERANCE)
    order_eq_delivery = equal_with_tolerance(soq, gdnq, QUANTITY_TOLERANCE)
    order_eq_invoice = equal_with_tolerance(soq, siq, QUANTITY_TOLERANCE)
    delivery_eq_invoice = equal_with_tolerance(gdnq, siq, QUANTITY_TOLERANCE)
    delivery_gt_invoice = greater_with_tolerance(gdnq, siq, QUANTITY_TOLERANCE)
    invoice_gt_delivery = greater_with_tolerance(siq, gdnq, QUANTITY_TOLERANCE)

    work.loc[category_4 & order_gt_delivery & delivery_eq_invoice, '_小分类'] = '4.1 未完全发货'
    work.loc[
        category_4 & work['_小分类'].isna() & order_eq_delivery & delivery_gt_invoice,
        '_小分类',
    ] = '4.2 未完全开票'
    work.loc[
        category_4 & work['_小分类'].isna() & order_lt_delivery,
        '_小分类',
    ] = '4.3 过量发货'
    work.loc[
        category_4 & work['_小分类'].isna() & order_eq_invoice & invoice_gt_delivery,
        '_小分类',
    ] = '4.4 预制发票'
    work.loc[category_4 & work['_小分类'].isna(), '_小分类'] = '4.5 其他'
    return work.reset_index(drop=True)


def _extra_nt_source(
    extra_categories: dict[str, pd.DataFrame],
    amount_col: str | None,
    order_inv_diff_col: str | None,
    inv_minus_order_col: str | None,
) -> pd.DataFrame:
    """把外连接产生的无发票/无匹配键集合补入完整NT矩阵。"""
    parts = []
    for category_name, nt_code in EXTRA_CATEGORY_TO_NT.items():
        frame = extra_categories.get(category_name)
        if frame is None or frame.empty:
            continue
        part = pd.DataFrame(index=frame.index)
        part['_AQPP可分类'] = False
        part['_大类'] = pd.NA
        part['_小分类'] = pd.NA
        part['_NT编码'] = nt_code
        part['_发票金额'] = _amount_series(frame, amount_col)
        part['_金额差异'] = _difference_series(
            frame, order_inv_diff_col, inv_minus_order_col
        )
        parts.append(part.reset_index(drop=True))
    if not parts:
        return pd.DataFrame(columns=[
            '_AQPP可分类', '_大类', '_小分类', '_NT编码', '_发票金额', '_金额差异'
        ])
    return pd.concat(parts, ignore_index=True, sort=False)


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    if denominator is None or pd.isna(denominator) or abs(float(denominator)) < 1e-12:
        return None
    return float(numerator) / float(denominator)


def build_fy25_format_summary(
    df_data: pd.DataFrame,
    *,
    amount_col: str | None,
    amount_label: str,
    invoice_total_amount: float,
    order_inv_diff_col: str | None = None,
    inv_minus_order_col: str | None = None,
    extra_categories: dict[str, pd.DataFrame] | None = None,
    invoice_stats: dict | tuple | None = None,
    invoice_stats_label: str = '渠道发票清单',
) -> pd.DataFrame:
    """生成截图式FY25兼容汇总；返回新DataFrame且不修改输入。

    主分类使用明确的“去年场景编码”映射；Not Test使用AQPP完整NT编码。
    NT-28/29/31来自订单发运外连接集合，NT-30/32/33主要来自发票驱动结果。
    """
    if df_data is None:
        df_data = pd.DataFrame()
    base = _build_narrow_source(
        df_data, amount_col, order_inv_diff_col, inv_minus_order_col
    )
    extras = _extra_nt_source(
        extra_categories or {}, amount_col, order_inv_diff_col, inv_minus_order_col
    )
    source = pd.concat([base, extras], ignore_index=True, sort=False)
    total_count = len(source)

    def make_row(category: str, subcategory: str, selected: pd.DataFrame) -> dict:
        count = len(selected)
        amount = float(selected['_发票金额'].sum()) if not selected.empty else 0.0
        difference = float(selected['_金额差异'].sum()) if not selected.empty else 0.0
        return {
            '分类': category,
            '小分类': subcategory,
            '记录数': count,
            '占比': _safe_ratio(count, total_count),
            '发票金额': round(amount, 2),
            '发票金额占比': _safe_ratio(amount, invoice_total_amount),
            '订单发票金额差异': round(difference, 2),
            '差异占发票小记比例': None,
        }

    rows = []
    for main_category in MAIN_ROWS:
        rows.append(make_row(
            main_category, '', source.loc[source['_大类'].eq(main_category)]
        ))
        for subcategory in SUB_ROWS[main_category]:
            rows.append(make_row(
                '', subcategory, source.loc[source['_小分类'].eq(subcategory)]
            ))

    aqpp_rows = source.loc[source['_AQPP可分类'].fillna(False).astype(bool)]
    subtotal = make_row('小计', '', aqpp_rows)
    rows.append(subtotal)

    not_test_rows = source.loc[~source['_AQPP可分类'].fillna(False).astype(bool)]
    rows.append(make_row('5. not test', '', not_test_rows))
    for nt_code in NT_CODES:
        description = NOT_TEST_DESCRIPTIONS[nt_code]
        rows.append(make_row(
            '', f'{nt_code} {description}', source.loc[source['_NT编码'].eq(nt_code)]
        ))

    rows.append(make_row('总计', '', source))

    if invoice_stats is not None:
        if isinstance(invoice_stats, dict):
            invoice_count = int(invoice_stats.get('清单行数', 0))
            invoice_amount = float(invoice_stats.get('发票金额', 0.0))
            invoice_number_count = int(invoice_stats.get('SAP发票数', 0))
            match_key_count = int(invoice_stats.get('匹配键数', 0))
            note = f'SAP发票数 {invoice_number_count:,}；匹配键数 {match_key_count:,}'
        else:
            invoice_count, invoice_amount = invoice_stats[:2]
            note = ''
        rows.append({
            '分类': invoice_stats_label,
            '小分类': note,
            '记录数': int(invoice_count),
            '占比': _safe_ratio(int(invoice_count), total_count),
            '发票金额': round(float(invoice_amount), 2),
            '发票金额占比': _safe_ratio(float(invoice_amount), invoice_total_amount),
            '订单发票金额差异': 0.0,
            '差异占发票小记比例': None,
        })

    subtotal_amount = float(subtotal['发票金额'])
    for row in rows:
        row['差异占发票小记比例'] = _safe_ratio(
            row['订单发票金额差异'], subtotal_amount
        )

    summary = pd.DataFrame(rows, columns=LEGACY_SUMMARY_COLUMNS)
    return summary.rename(columns={'发票金额': amount_label})

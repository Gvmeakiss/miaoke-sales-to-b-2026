# -*- coding: utf-8 -*-
"""AQPP无交货金额模式：V1-V3 × Q1-Q8，共24组，并映射去年场景。"""

from __future__ import annotations

import pandas as pd

from config import AQPP_ALLOWED_CURRENCY_STATUSES, AQPP_ALLOWED_UNIT_STATUSES
from tolerance_utils import (
    absolute_equal_to_boundary,
    absolute_greater_than,
    equal_with_tolerance,
    greater_with_tolerance,
)


VALUE_SCENARIOS = {
    'V1': '发票金额 = 订单金额',
    'V2': '发票金额 > 订单金额',
    'V3': '发票金额 < 订单金额',
}

VALUE_LABELS = {
    'V1': '金额无差异',
    'V2': '发票金额大于订单金额',
    'V3': '发票金额小于订单金额',
}

QUANTITY_SCENARIOS = {
    'Q1': '发票数量 = 订单数量 = 发货数量',
    'Q2': '发票数量 > 订单数量 = 发货数量',
    'Q3': '发票数量 < 订单数量 = 发货数量',
    'Q4': '订单数量 > 发票数量 = 发货数量',
    'Q5': '订单数量 < 发票数量 = 发货数量',
    'Q6': '发货数量 > 发票数量 = 订单数量',
    'Q7': '发货数量 < 发票数量 = 订单数量',
    'Q8': '发票数量、订单数量、发货数量三者均不同',
}

QUANTITY_LABELS = {
    'Q1': '数量无差异',
    'Q2': '发票数量大于订单和发货数量',
    'Q3': '发票数量小于订单和发货数量',
    'Q4': '订单数量大于发票和发货数量',
    'Q5': '订单数量小于发票和发货数量',
    'Q6': '发货数量大于发票和订单数量',
    'Q7': '发货数量小于发票和订单数量',
    'Q8': '发票、订单、发货数量三者均不同',
}

NOT_TEST_DESCRIPTIONS = {
    'NT-00': '关键字段缺失或AQPP关系无法唯一判断',
    'NT-28': '仅订单',
    'NT-29': '仅发运单',
    'NT-30': '仅开票',
    'NT-31': '仅订单及发运单',
    'NT-32': '订单及开票，无发运单',
    'NT-33': '仅发运单及开票',
}

NOT_TEST_TO_FY25 = {
    'NT-00': None,
    'NT-28': '7',
    'NT-29': '7',
    'NT-30': '14',
    'NT-31': '7',
    'NT-32': '14',
    'NT-33': '14',
}

FY25_NOT_TEST_LABELS = {
    '7': '缺失发票（无发票无开票金额），N/A',
    '14': '有发票、订单或发运单缺失，Not Test',
}

LEGACY_DESCRIPTIONS = {
    '1': '订单数量=发票≠发货,订单金额<发票金额',
    '2': '订单数量=发票≠发货,订单金额>发票金额',
    '3': '订单数量=发票≠发货,金额一致',
    '4': '订单数量≠发票≠发货,订单金额<发票金额',
    '5': '订单数量≠发票≠发货,订单金额>发票金额',
    '6': '订单数量≠发票≠发货,金额一致',
    '7': '缺失发票',
    '8': '无差异,订单金额<发票金额',
    '9': '无差异,订单金额>发票金额',
    '10': '无差异,无差异',
    '11': '订单数量=发货≠发票,金额一致',
    '12': '订单数量=发货≠发票,订单金额<发票金额',
    '13': '订单数量=发货≠发票,订单金额>发票金额',
}

AQPP_SCENARIO_REPORT_COLUMNS = [
    '场景编号', '场景代码', '识别场景(数量差异类型,金额差异类型)',
    'AQPP数量分类代码', 'AQPP数量关系',
    'AQPP金额分类代码', 'AQPP金额关系',
    'FY25场景编号', 'FY25识别场景',
    '记录数', '占比', '发票不含税金额', '发票金额', '发票金额占比',
    '订单发票金额差异', '差异金额占比',
]


def _equal(a: pd.Series, b: pd.Series, tolerance: float) -> pd.Series:
    """严格按规范使用 abs(a-b) < tolerance，不直接进行浮点等值判断。"""
    return equal_with_tolerance(a, b, tolerance)


def classify_value(
    siv: pd.Series,
    sov: pd.Series,
    tolerance: float,
    include_boundary_as_equal: bool = False,
) -> pd.Series:
    """判断V1-V3；可按渠道配置将金额容差边界纳入V1。"""
    siv = pd.to_numeric(siv, errors='coerce')
    sov = pd.to_numeric(sov, errors='coerce')
    valid = siv.notna() & sov.notna()
    result = pd.Series(pd.NA, index=siv.index, dtype='string')
    result.loc[valid & _equal(siv, sov, tolerance)] = 'V1'
    if include_boundary_as_equal:
        result.loc[valid & absolute_equal_to_boundary(siv.sub(sov), tolerance)] = 'V1'
    result.loc[valid & greater_with_tolerance(siv, sov, tolerance)] = 'V2'
    result.loc[valid & greater_with_tolerance(sov, siv, tolerance)] = 'V3'
    return result


def classify_quantity(siq: pd.Series, soq: pd.Series, gdnq: pd.Series, tolerance: float) -> pd.Series:
    """判断Q1-Q8；所有关系均使用数量容差，不能唯一分类时返回NA。"""
    siq = pd.to_numeric(siq, errors='coerce')
    soq = pd.to_numeric(soq, errors='coerce')
    gdnq = pd.to_numeric(gdnq, errors='coerce')
    valid = siq.notna() & soq.notna() & gdnq.notna()
    si_so = _equal(siq, soq, tolerance)
    si_gd = _equal(siq, gdnq, tolerance)
    so_gd = _equal(soq, gdnq, tolerance)

    result = pd.Series(pd.NA, index=siq.index, dtype='string')
    result.loc[valid & si_so & si_gd & so_gd] = 'Q1'
    result.loc[valid & so_gd & greater_with_tolerance(siq, soq, tolerance)] = 'Q2'
    result.loc[valid & so_gd & greater_with_tolerance(soq, siq, tolerance)] = 'Q3'
    result.loc[valid & si_gd & greater_with_tolerance(soq, siq, tolerance)] = 'Q4'
    result.loc[valid & si_gd & greater_with_tolerance(siq, soq, tolerance)] = 'Q5'
    result.loc[valid & si_so & greater_with_tolerance(gdnq, siq, tolerance)] = 'Q6'
    result.loc[valid & si_so & greater_with_tolerance(siq, gdnq, tolerance)] = 'Q7'
    # Q8要求三组差值都严格大于容差；恰落在边界的记录不会被静默归类。
    all_different = (
        valid
        & absolute_greater_than(siq.sub(soq), tolerance)
        & absolute_greater_than(siq.sub(gdnq), tolerance)
        & absolute_greater_than(soq.sub(gdnq), tolerance)
    )
    result.loc[all_different] = 'Q8'
    return result


def _not_test_code(has_order, has_delivery, has_invoice) -> pd.Series:
    """根据三单存在组合分配NT-28至NT-33，其余异常归NT-00。"""
    result = pd.Series('NT-00', index=has_order.index, dtype='string')
    result.loc[has_order & ~has_delivery & ~has_invoice] = 'NT-28'
    result.loc[~has_order & has_delivery & ~has_invoice] = 'NT-29'
    result.loc[~has_order & ~has_delivery & has_invoice] = 'NT-30'
    result.loc[has_order & has_delivery & ~has_invoice] = 'NT-31'
    result.loc[has_order & ~has_delivery & has_invoice] = 'NT-32'
    result.loc[~has_order & has_delivery & has_invoice] = 'NT-33'
    return result


def classify_not_test_presence(has_order, has_delivery, has_invoice) -> pd.Series:
    """按三单实际存在关系返回现有 NT-00、NT-28 至 NT-33 编码。"""
    return _not_test_code(
        pd.Series(has_order).fillna(False).astype(bool),
        pd.Series(has_delivery).fillna(False).astype(bool),
        pd.Series(has_invoice).fillna(False).astype(bool),
    )


def assign_aqpp_scenarios(
    df: pd.DataFrame,
    amount_tolerance: float,
    quantity_tolerance: float,
    include_amount_boundary_as_equal: bool = False,
) -> pd.DataFrame:
    """按AQPP 24组及Not Test规则分类；返回副本，不修改原DataFrame。"""
    out = df.copy()
    value_code = classify_value(
        out['SIV'],
        out['SOV'],
        amount_tolerance,
        include_boundary_as_equal=include_amount_boundary_as_equal,
    )
    quantity_code = classify_quantity(out['SIQ'], out['SOQ'], out['GDNQ'], quantity_tolerance)
    has_order = out['存在销售订单'].fillna(False).astype(bool)
    has_delivery = out['存在发运单'].fillna(False).astype(bool)
    has_invoice = out['存在销售发票'].fillna(False).astype(bool)
    all_documents = has_order & has_delivery & has_invoice
    currency_status = out.get(
        '币种校验状态', pd.Series('一致', index=out.index, dtype='string')
    ).astype('string')
    unit_status = out.get(
        '数量单位校验状态', pd.Series('一致', index=out.index, dtype='string')
    ).astype('string')
    currency_ok = currency_status.isin(AQPP_ALLOWED_CURRENCY_STATUSES)
    unit_ok = unit_status.isin(AQPP_ALLOWED_UNIT_STATUSES)
    eligible = all_documents & value_code.notna() & quantity_code.notna() & currency_ok & unit_ok

    value_index = value_code.str[1:].astype('Int64')
    quantity_index = quantity_code.str[1:].astype('Int64')
    scenario_number = (value_index - 1) * 8 + quantity_index
    scenario_code = pd.Series(pd.NA, index=out.index, dtype='string')
    scenario_code.loc[eligible] = 'AQPP-' + scenario_number.loc[eligible].astype('Int64').astype('string').str.zfill(2)
    scenario_code.loc[~eligible] = _not_test_code(has_order, has_delivery, has_invoice).loc[~eligible]

    category = pd.Series('Not Test', index=out.index, dtype='string')
    category.loc[eligible & scenario_number.eq(1)] = '完全匹配'
    category.loc[eligible & quantity_code.eq('Q1') & value_code.ne('V1')] = '金额差异'
    category.loc[eligible & quantity_code.ne('Q1') & value_code.eq('V1')] = '数量差异'
    category.loc[eligible & quantity_code.ne('Q1') & value_code.ne('V1')] = '数量+金额差异'

    out['AQPP金额场景编码'] = value_code
    out['AQPP金额场景'] = value_code.map(VALUE_SCENARIOS).fillna('待确认')
    out['AQPP数量场景编码'] = quantity_code
    out['AQPP数量场景'] = quantity_code.map(QUANTITY_SCENARIOS).fillna('待确认')
    out['AQPP场景编码'] = scenario_code
    out['AQPP场景描述'] = scenario_code.map(NOT_TEST_DESCRIPTIONS).fillna(
        out['AQPP金额场景'] + '；' + out['AQPP数量场景']
    )
    out['AQPP分类'] = category
    out['AQPP可分类'] = eligible
    return out


def _build_legacy_mapping():
    """集中建立24组AQPP到去年场景的多对一映射，保留AQPP细分信息。"""
    value_relation = {'V1': '金额一致', 'V2': '订单<发票', 'V3': '订单>发票'}
    quantity_family = {
        'Q1': '全部一致',
        'Q2': '订单=发货≠发票', 'Q3': '订单=发货≠发票',
        'Q4': '其他数量差异', 'Q5': '其他数量差异', 'Q8': '其他数量差异',
        'Q6': '订单=发票≠发货', 'Q7': '订单=发票≠发货',
    }
    code_by_family = {
        ('全部一致', '金额一致'): '10', ('全部一致', '订单<发票'): '8', ('全部一致', '订单>发票'): '9',
        ('订单=发货≠发票', '金额一致'): '11', ('订单=发货≠发票', '订单<发票'): '12', ('订单=发货≠发票', '订单>发票'): '13',
        ('订单=发票≠发货', '金额一致'): '3', ('订单=发票≠发货', '订单<发票'): '1', ('订单=发票≠发货', '订单>发票'): '2',
        ('其他数量差异', '金额一致'): '6', ('其他数量差异', '订单<发票'): '4', ('其他数量差异', '订单>发票'): '5',
    }
    mapping = {}
    for value_code, relation in value_relation.items():
        for quantity_code, family in quantity_family.items():
            legacy_code = code_by_family[(family, relation)]
            scenario_no = (int(value_code[1:]) - 1) * 8 + int(quantity_code[1:])
            aqpp_code = f'AQPP-{scenario_no:02d}'
            mapping[aqpp_code] = {
                'AQPP金额场景编码': value_code,
                'AQPP金额场景': VALUE_SCENARIOS[value_code],
                'AQPP金额分类': VALUE_LABELS[value_code],
                'AQPP数量场景编码': quantity_code,
                'AQPP数量场景': QUANTITY_SCENARIOS[quantity_code],
                'AQPP数量分类': QUANTITY_LABELS[quantity_code],
                'AQPP场景编码': aqpp_code,
                '场景编号': scenario_no,
                '去年场景编码': legacy_code,
                '去年场景描述': LEGACY_DESCRIPTIONS[legacy_code],
            }
    return mapping


AQPP_TO_LEGACY_MAPPING = _build_legacy_mapping()


def map_aqpp_to_legacy(df: pd.DataFrame) -> pd.DataFrame:
    """优先按独立映射表生成去年兼容字段；Not Test不静默套入错误场景。"""
    out = df.copy()
    records = [AQPP_TO_LEGACY_MAPPING.get(code) for code in out['AQPP场景编码']]
    out['去年场景编码'] = [record['去年场景编码'] if record else '待确认' for record in records]
    out['去年场景描述'] = [record['去年场景描述'] if record else '待确认/其他' for record in records]
    out['AQPP到去年场景映射状态'] = ['已映射' if record else '待确认' for record in records]
    # Not Test统一引用集中映射，避免汇总表与明细分别维护后产生口径差异。
    # NT-00仍保持待确认；其余NT按README约定映射至FY25场景7或14。
    for aqpp_code, fy25_code in NOT_TEST_TO_FY25.items():
        if fy25_code is None:
            continue
        mask = out['AQPP场景编码'].eq(aqpp_code)
        out.loc[mask, '去年场景编码'] = fy25_code
        out.loc[mask, '去年场景描述'] = FY25_NOT_TEST_LABELS[fy25_code]
        out.loc[mask, 'AQPP到去年场景映射状态'] = '已映射'
    return out


def build_aqpp_scenario_catalog() -> pd.DataFrame:
    """生成 AQPP-01 至 AQPP-24 的固定目录（含中文关系与 FY25 映射）。"""
    rows = []
    for record in AQPP_TO_LEGACY_MAPPING.values():
        rows.append({
            '场景编号': record['场景编号'],
            '场景代码': record['AQPP场景编码'],
            '识别场景(数量差异类型,金额差异类型)': (
                f"{record['AQPP数量分类']}，{record['AQPP金额分类']}"
            ),
            'AQPP数量分类代码': record['AQPP数量场景编码'],
            'AQPP数量关系': record['AQPP数量场景'],
            'AQPP金额分类代码': record['AQPP金额场景编码'],
            'AQPP金额关系': record['AQPP金额场景'],
            'FY25场景编号': int(record['去年场景编码']),
            'FY25识别场景': record['去年场景描述'],
        })
    return pd.DataFrame(rows).sort_values('场景编号', kind='stable').reset_index(drop=True)


def _pct_or_na(numerator: float, denominator: float) -> str:
    if denominator is None or abs(float(denominator)) < 1e-12:
        return 'N/A'
    return f"{(float(numerator) / float(denominator) * 100):.2f}%"


def build_aqpp_scenario_report(
    df: pd.DataFrame,
    amount_col: str | None = None,
    order_inv_diff_col: str | None = None,
    inv_minus_order_col: str | None = None,
    invoice_total_amount: float | None = None,
    untaxed_amount_col: str | None = None,
) -> pd.DataFrame:
    """按参考格式生成场景汇总，金额占比使用渠道发票清单净额。"""
    if df is None or df.empty or 'AQPP场景编码' not in df.columns:
        return pd.DataFrame(columns=AQPP_SCENARIO_REPORT_COLUMNS)

    work = df.copy()
    if amount_col is None:
        amount_col = next(
            (c for c in ('开票金额', 'SAP开票含税金额') if c in work.columns),
            None,
        )
    invoice_amount = (
        pd.to_numeric(work[amount_col], errors='coerce').fillna(0)
        if amount_col and amount_col in work.columns
        else pd.Series(0.0, index=work.index)
    )
    untaxed_amount = (
        pd.to_numeric(work[untaxed_amount_col], errors='coerce').fillna(0)
        if untaxed_amount_col and untaxed_amount_col in work.columns
        else pd.Series(0.0, index=work.index)
    )
    if invoice_total_amount is None:
        invoice_total_amount = float(invoice_amount.sum())
    if order_inv_diff_col and order_inv_diff_col in work.columns:
        amount_diff = pd.to_numeric(work[order_inv_diff_col], errors='coerce').fillna(0)
    elif inv_minus_order_col and inv_minus_order_col in work.columns:
        amount_diff = -pd.to_numeric(work[inv_minus_order_col], errors='coerce').fillna(0)
    elif '订单-发票金额' in work.columns:
        amount_diff = pd.to_numeric(work['订单-发票金额'], errors='coerce').fillna(0)
    elif 'SAP-DMS订单金额' in work.columns:
        amount_diff = -pd.to_numeric(work['SAP-DMS订单金额'], errors='coerce').fillna(0)
    else:
        amount_diff = pd.Series(0.0, index=work.index)

    eligible = work.get('AQPP可分类', work['AQPP分类'].ne('Not Test')).fillna(False).astype(bool)
    # 一次聚合得到全部场景统计，避免对50万级主结果按31个场景重复扫描。
    stats_source = pd.DataFrame({
        '场景代码': work['AQPP场景编码'].astype('string'),
        '发票金额': invoice_amount,
        '发票不含税金额': untaxed_amount,
        '订单发票金额差异': amount_diff,
    })
    scenario_stats = stats_source.groupby('场景代码', dropna=False).agg(
        记录数=('场景代码', 'size'),
        发票金额=('发票金额', 'sum'),
        发票不含税金额=('发票不含税金额', 'sum'),
        订单发票金额差异=('订单发票金额差异', 'sum'),
    ).to_dict('index')
    eligible_total = int(eligible.sum())
    not_test_total = int((~eligible).sum())

    def get_stats(code, total_count):
        values = scenario_stats.get(code, {})
        count = int(values.get('记录数', 0))
        amount = float(values.get('发票金额', 0.0))
        untaxed = float(values.get('发票不含税金额', 0.0))
        difference = float(values.get('订单发票金额差异', 0.0))
        return {
            '记录数': count,
            '占比': _pct_or_na(count, total_count),
            '发票金额': round(amount, 2),
            '发票不含税金额': round(untaxed, 2),
            '发票金额占比': _pct_or_na(amount, invoice_total_amount),
            '订单发票金额差异': round(difference, 2),
            '差异金额占比': _pct_or_na(difference, invoice_total_amount),
        }

    catalog = build_aqpp_scenario_catalog()
    rows = []
    for _, source in catalog.iterrows():
        code = source['场景代码']
        row = source.to_dict()
        row.update(get_stats(code, eligible_total))
        rows.append(row)

    for code in ('NT-00', 'NT-28', 'NT-29', 'NT-30', 'NT-31', 'NT-32', 'NT-33'):
        fy25 = NOT_TEST_TO_FY25[code]
        row = {
            '场景编号': int(code.split('-')[1]),
            '场景代码': code,
            '识别场景(数量差异类型,金额差异类型)': NOT_TEST_DESCRIPTIONS[code],
            'AQPP数量分类代码': '',
            'AQPP数量关系': '',
            'AQPP金额分类代码': '',
            'AQPP金额关系': '',
            'FY25场景编号': '' if fy25 is None else int(fy25),
            'FY25识别场景': '' if fy25 is None else FY25_NOT_TEST_LABELS.get(fy25, LEGACY_DESCRIPTIONS.get(fy25, '')),
        }
        row.update(get_stats(code, not_test_total))
        rows.append(row)

    return pd.DataFrame(rows)[AQPP_SCENARIO_REPORT_COLUMNS]

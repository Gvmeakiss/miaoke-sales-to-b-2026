# -*- coding: utf-8 -*-
"""
三单匹配场景划分 - 统一规范（参考 refer/difference_analysis.py）

四大类及下属细分场景：

【大类1】完全匹配
  - 1.完全匹配: 订单=发货=发票(数量)、金额一致

【大类2】数量一致、金额有差异
  - 2.1 尾差<1: 订单金额与发票金额差异在1以内（0.02 ≤ |差异| < 1）
  - 2.2 其他: 该大类下未计入2.1的所有其他情况

【大类3】金额一致、数量有差异
  - 3.金额一致数量有差异: 数量有差异但金额一致（无子类）

【大类4】均有差异
  - 4.1 未完全发货（订单数量>收货单数量=开票数量）: 避免与 4.4 重叠
  - 4.2 未完全开票: 订单数量 = 发货单数量 > 开票数量
  - 4.3 过量发货: 订单数量 < 发货单数量
  - 4.4 预制发票: 订单数量 = 开票数量 > 发货数量
  - 4.5 其他: 该大类下未计入上述小场景的所有其他可能

【大类5】有缺失
  - 5.缺失发票: 缺失发票
  - 5.Not test: 关键字段缺失

阈值：QTY_TOL=0.02, AMT_TOL=0.02（参考 difference_analysis.py，统一使用 0.02）
尾差<1：|订单-发票金额| < 1
"""

import pandas as pd
import numpy as np

from aqpp_scenarios import (
    LEGACY_DESCRIPTIONS,
    NOT_TEST_DESCRIPTIONS,
    assign_aqpp_scenarios,
    classify_not_test_presence,
    map_aqpp_to_legacy,
)
from config import (
    AMOUNT_TAIL_TOLERANCE,
    AMOUNT_TOLERANCE,
    DMS_AMOUNT_TOLERANCE_INCLUSIVE,
    QUANTITY_TOLERANCE,
)
from reconciliation_measures import build_three_way_measures
from tolerance_utils import (
    absolute_equal_to_boundary,
    absolute_greater_than,
    absolute_less_than,
    equal_with_tolerance,
    greater_with_tolerance,
)

QTY_TOL = QUANTITY_TOLERANCE
AMT_TOL = AMOUNT_TOLERANCE
AMT_TAIL_LT1 = AMOUNT_TAIL_TOLERANCE

# 场景标号 → 描述（内部用，兼容 refer）
SCENARIO_DESC = {
    1: '订单数量=发票≠发货,订单金额<发票金额',
    2: '订单数量=发票≠发货,订单金额>发票金额',
    3: '订单数量=发票≠发货,金额一致',
    4: '订单数量≠发票≠发货,订单金额<发票金额',
    5: '订单数量≠发票≠发货,订单金额>发票金额',
    6: '订单数量≠发票≠发货,金额一致',
    7: '缺失发票',
    8: '无差异,订单金额<发票金额',
    9: '无差异,订单金额>发票金额',
    10: '无差异,无差异',
    11: '订单数量=发货≠发票,金额一致',
    12: '订单数量=发货≠发票,订单金额<发票金额',
    13: '订单数量=发货≠发票,订单金额>发票金额',
}

# 场景标号 → 大类（新四大类+有缺失）
SCENARIO_TO_MAIN_CATEGORY = {
    10: '1.完全匹配',
    8: '2.数量一致金额有差异',
    9: '2.数量一致金额有差异',
    3: '3.金额一致数量有差异',
    6: '3.金额一致数量有差异',
    11: '3.金额一致数量有差异',
    1: '4.均有差异',
    2: '4.均有差异',
    4: '4.均有差异',
    5: '4.均有差异',
    12: '4.均有差异',
    13: '4.均有差异',
    7: '5.有缺失',
}


def _assign_sub_scenario_oms(df, scenario, amt_diff, ord_qty, dlv_qty, inv_qty, valid):
    """根据场景标号、金额差、数量计算细分场景（2.1/2.2、4.1-4.5）"""
    sub = pd.Series('', index=df.index, dtype=str)

    # 大类2: 2.1 尾差<1 / 2.2 其他
    in_cat2 = (scenario == 8) | (scenario == 9)
    amt_abs = amt_diff.abs()
    sub.loc[in_cat2 & (amt_abs < AMT_TAIL_LT1)] = '2.1 尾差<1'
    sub.loc[in_cat2 & (amt_abs >= AMT_TAIL_LT1)] = '2.2 其他'

    # 大类3: 无子类
    in_cat3 = (scenario == 3) | (scenario == 6) | (scenario == 11)
    sub.loc[in_cat3] = '3.金额一致数量有差异'

    # 大类4: 4.1-4.5（按优先级：4.1→4.3→4.2→4.4→4.5）
    # 4.1: 订单数量>收货单数量=开票数量，避免与 4.4(ord=inv>dlv) 重叠
    in_cat4 = scenario.isin([1, 2, 4, 5, 12, 13])
    dlv_filled = dlv_qty.fillna(0)
    ord_gt_dlv = greater_with_tolerance(ord_qty, dlv_filled, QTY_TOL)
    ord_lt_dlv = greater_with_tolerance(dlv_filled, ord_qty, QTY_TOL)
    ord_eq_dlv = equal_with_tolerance(ord_qty, dlv_filled, QTY_TOL)
    ord_eq_inv = equal_with_tolerance(ord_qty, inv_qty, QTY_TOL)
    dlv_eq_inv = equal_with_tolerance(dlv_filled, inv_qty, QTY_TOL)
    dlv_gt_inv = greater_with_tolerance(dlv_filled, inv_qty, QTY_TOL)
    inv_gt_dlv = greater_with_tolerance(inv_qty, dlv_filled, QTY_TOL)

    sub.loc[in_cat4 & ord_gt_dlv & dlv_eq_inv] = '4.1 未完全发货（订单数量>收货单数量=开票数量）'
    sub.loc[in_cat4 & ord_lt_dlv] = '4.3 过量发货'
    sub.loc[in_cat4 & (sub == '') & ord_eq_dlv & dlv_gt_inv] = '4.2 未完全开票'
    sub.loc[in_cat4 & (sub == '') & ord_eq_inv & inv_gt_dlv] = '4.4 预制发票'
    sub.loc[in_cat4 & (sub == '')] = '4.5 其他'

    # 大类1
    sub.loc[scenario == 10] = '1.完全匹配'

    # 5.有缺失
    sub.loc[scenario == 7] = '5.缺失发票'
    sub.loc[~valid] = '5.Not test'
    sub.loc[(scenario == 0) & valid] = '5.Not test'

    return sub


def assign_scenario_oms(df, qty_ord_inv_col='订单-开票数量', qty_ord_dlv_col='订单-发货数量', amt_col='订单-发票金额'):
    """
    为 OMS 匹配结果分配场景标号（1-13）、大类、细分场景。
    要求 df 包含：订单-开票数量、订单-发货数量、订单-发票金额；以及 订单数量、发货数量、开票数量。
    """
    if qty_ord_inv_col not in df.columns or amt_col not in df.columns:
        return df

    qty_ord_inv = pd.to_numeric(df[qty_ord_inv_col], errors='coerce').fillna(9e9)
    amt_diff = pd.to_numeric(df[amt_col], errors='coerce').fillna(0)

    ord_inv_eq = absolute_less_than(qty_ord_inv, QTY_TOL)
    amt_eq = absolute_less_than(amt_diff, AMT_TOL)
    amt_outside = absolute_greater_than(amt_diff, AMT_TOL)
    amt_lt = amt_outside & amt_diff.lt(0)
    amt_gt = amt_outside & amt_diff.gt(0)

    if qty_ord_dlv_col in df.columns:
        qty_ord_dlv = pd.to_numeric(df[qty_ord_dlv_col], errors='coerce').fillna(9e9)
        ord_dlv_eq = absolute_less_than(qty_ord_dlv, QTY_TOL)
    elif '订单数量' in df.columns and '发货数量' in df.columns:
        ord_qty = pd.to_numeric(df['订单数量'], errors='coerce').fillna(0)
        dlv_qty = pd.to_numeric(df['发货数量'], errors='coerce')
        ord_dlv_eq = dlv_qty.notna() & equal_with_tolerance(ord_qty, dlv_qty, QTY_TOL)
    else:
        ord_dlv_eq = pd.Series(False, index=df.index)

    valid = ~df['2.Not test'] if '2.Not test' in df.columns else pd.Series(True, index=df.index)

    # 获取数量列用于 4.x 细分
    ord_qty = pd.to_numeric(df['订单数量'], errors='coerce').fillna(0) if '订单数量' in df.columns else pd.Series(0.0, index=df.index)
    dlv_qty = pd.to_numeric(df['发货数量'], errors='coerce') if '发货数量' in df.columns else pd.Series(np.nan, index=df.index)
    inv_qty = pd.to_numeric(df['开票数量'], errors='coerce').fillna(0) if '开票数量' in df.columns else pd.Series(0.0, index=df.index)

    scenario = pd.Series(0, index=df.index, dtype=int)
    scenario[ord_dlv_eq & ord_inv_eq & amt_eq & valid] = 10
    scenario[ord_dlv_eq & ord_inv_eq & amt_lt & valid] = 8
    scenario[ord_dlv_eq & ord_inv_eq & amt_gt & valid] = 9
    scenario[ord_inv_eq & ~ord_dlv_eq & amt_eq & valid] = 3
    scenario[ord_dlv_eq & ~ord_inv_eq & amt_eq & valid] = 11
    scenario[~ord_dlv_eq & ~ord_inv_eq & amt_eq & valid] = 6
    scenario[ord_inv_eq & ~ord_dlv_eq & amt_lt & valid] = 1
    scenario[ord_inv_eq & ~ord_dlv_eq & amt_gt & valid] = 2
    scenario[ord_dlv_eq & ~ord_inv_eq & amt_lt & valid] = 12
    scenario[ord_dlv_eq & ~ord_inv_eq & amt_gt & valid] = 13
    scenario[~ord_dlv_eq & ~ord_inv_eq & amt_lt & valid] = 4
    scenario[~ord_dlv_eq & ~ord_inv_eq & amt_gt & valid] = 5

    df = df.copy()
    df['场景标号'] = scenario
    df['大类'] = df['场景标号'].map(SCENARIO_TO_MAIN_CATEGORY).fillna('5.有缺失')
    df['细分场景'] = _assign_sub_scenario_oms(df, scenario, amt_diff, ord_qty, dlv_qty, inv_qty, valid)
    df.loc[~valid, '大类'] = '5.有缺失'
    return df


def assign_scenario_dms(
    df,
    dms_order_qty_col='DMS订单数量',
    dms_dlv_qty_col='DMS发货数量',
    sap_qty_col='SAP开票基本数量',
    amt_diff_col='SAP-DMS订单金额',
):
    """
    为 DMS 匹配结果分配场景标号（1-13）、大类、细分场景。
    DMS 金额差异列 SAP-DMS订单金额 = 发票 - 订单，故 |SAP-DMS订单金额| = |订单-发票|。
    """
    if amt_diff_col not in df.columns:
        return df

    amt_diff_raw = pd.to_numeric(df[amt_diff_col], errors='coerce').fillna(0)
    # SAP-DMS订单金额 = 发票-订单，故 订单-发票 = -amt_diff_raw，取绝对值用于尾差判断
    amt_diff = -amt_diff_raw  # 转为 订单-发票 口径，与 OMS 一致

    amt_eq = absolute_less_than(amt_diff, AMT_TOL)
    # FY25兼容口径把=0.02视为“金额有差异”，并在去年格式汇总进入2.1尾差<1。
    amount_boundary = absolute_equal_to_boundary(amt_diff_raw, AMT_TOL)
    amt_outside = absolute_greater_than(amt_diff_raw, AMT_TOL) | amount_boundary
    # DMS 原逻辑：amt_diff_col=发票-订单，amt_lt=>发票>订单，amt_gt=>发票<订单
    amt_lt = amt_outside & amt_diff_raw.gt(0)
    amt_gt = amt_outside & amt_diff_raw.lt(0)

    ord_qty = pd.to_numeric(df[dms_order_qty_col], errors='coerce').fillna(0) if dms_order_qty_col in df.columns else pd.Series(0.0, index=df.index)
    dlv_qty = pd.to_numeric(df[dms_dlv_qty_col], errors='coerce') if dms_dlv_qty_col in df.columns else pd.Series(np.nan, index=df.index)
    inv_qty = pd.to_numeric(df[sap_qty_col], errors='coerce').fillna(0) if sap_qty_col in df.columns else pd.Series(0.0, index=df.index)

    qty_ord_inv = ord_qty - inv_qty
    qty_ord_dlv = ord_qty - dlv_qty.fillna(1e9)

    ord_inv_eq = absolute_less_than(qty_ord_inv, QTY_TOL)
    ord_dlv_eq = dlv_qty.notna() & absolute_less_than(qty_ord_dlv, QTY_TOL)

    valid = ~df['2.Not test'] if '2.Not test' in df.columns else pd.Series(True, index=df.index)

    scenario = pd.Series(0, index=df.index, dtype=int)
    scenario[ord_dlv_eq & ord_inv_eq & amt_eq & valid] = 10
    scenario[ord_dlv_eq & ord_inv_eq & amt_lt & valid] = 8
    scenario[ord_dlv_eq & ord_inv_eq & amt_gt & valid] = 9
    scenario[ord_inv_eq & ~ord_dlv_eq & amt_eq & valid] = 3
    scenario[ord_dlv_eq & ~ord_inv_eq & amt_eq & valid] = 11
    scenario[~ord_dlv_eq & ~ord_inv_eq & amt_eq & valid] = 6
    scenario[ord_inv_eq & ~ord_dlv_eq & amt_lt & valid] = 1
    scenario[ord_inv_eq & ~ord_dlv_eq & amt_gt & valid] = 2
    scenario[ord_dlv_eq & ~ord_inv_eq & amt_lt & valid] = 12
    scenario[ord_dlv_eq & ~ord_inv_eq & amt_gt & valid] = 13
    scenario[~ord_dlv_eq & ~ord_inv_eq & amt_lt & valid] = 4
    scenario[~ord_dlv_eq & ~ord_inv_eq & amt_gt & valid] = 5

    # 细分场景：DMS 用 |订单-发票| = |amt_diff_raw| 判断尾差
    amt_abs = amt_diff_raw.abs()
    sub = _assign_sub_scenario_dms(df, scenario, amt_abs, ord_qty, dlv_qty, inv_qty, valid)

    df = df.copy()
    df['场景标号'] = scenario
    df['大类'] = df['场景标号'].map(SCENARIO_TO_MAIN_CATEGORY).fillna('5.有缺失')
    df['细分场景'] = sub
    df.loc[~valid, '大类'] = '5.有缺失'
    return df


def _assign_sub_scenario_dms(df, scenario, amt_abs, ord_qty, dlv_qty, inv_qty, valid):
    """DMS 的细分场景（amt_abs 为 |发票-订单|）"""
    sub = pd.Series('', index=df.index, dtype=str)

    in_cat2 = (scenario == 8) | (scenario == 9)
    sub.loc[in_cat2 & (amt_abs < AMT_TAIL_LT1)] = '2.1 尾差<1'
    sub.loc[in_cat2 & (amt_abs >= AMT_TAIL_LT1)] = '2.2 其他'

    in_cat3 = (scenario == 3) | (scenario == 6) | (scenario == 11)
    sub.loc[in_cat3] = '3.金额一致数量有差异'

    in_cat4 = scenario.isin([1, 2, 4, 5, 12, 13])
    dlv_filled = dlv_qty.fillna(0)
    ord_gt_dlv = greater_with_tolerance(ord_qty, dlv_filled, QTY_TOL)
    ord_lt_dlv = greater_with_tolerance(dlv_filled, ord_qty, QTY_TOL)
    ord_eq_dlv = equal_with_tolerance(ord_qty, dlv_filled, QTY_TOL)
    ord_eq_inv = equal_with_tolerance(ord_qty, inv_qty, QTY_TOL)
    dlv_eq_inv = equal_with_tolerance(dlv_filled, inv_qty, QTY_TOL)
    dlv_gt_inv = greater_with_tolerance(dlv_filled, inv_qty, QTY_TOL)
    inv_gt_dlv = greater_with_tolerance(inv_qty, dlv_filled, QTY_TOL)

    sub.loc[in_cat4 & ord_gt_dlv & dlv_eq_inv] = '4.1 未完全发货（订单数量>收货单数量=开票数量）'
    sub.loc[in_cat4 & ord_lt_dlv] = '4.3 过量发货'
    sub.loc[in_cat4 & (sub == '') & ord_eq_dlv & dlv_gt_inv] = '4.2 未完全开票'
    sub.loc[in_cat4 & (sub == '') & ord_eq_inv & inv_gt_dlv] = '4.4 预制发票'
    sub.loc[in_cat4 & (sub == '')] = '4.5 其他'

    sub.loc[scenario == 10] = '1.完全匹配'
    sub.loc[scenario == 7] = '5.缺失发票'
    sub.loc[~valid] = '5.Not test'
    sub.loc[(scenario == 0) & valid] = '5.Not test'

    return sub


def assign_parallel_scenarios(df: pd.DataFrame, channel: str) -> pd.DataFrame:
    """按AQPP优先、映射去年场景、保留去年原始判断的顺序生成并行分类。

    返回新DataFrame，不修改调用方数据。AQPP采用无交货金额模式：金额比较
    SIV/SOV，数量比较SIQ/SOQ/GDNQ。去年原始逻辑仅用于交叉验证。
    """
    out = build_three_way_measures(df, channel)
    is_dms = channel.upper() == 'DMS'
    include_amount_boundary = is_dms and DMS_AMOUNT_TOLERANCE_INCLUSIVE
    if is_dms:
        out['尾差0.02'] = absolute_equal_to_boundary(
            out['SIV'].sub(out['SOV']), AMOUNT_TOLERANCE
        ).map({True: '是', False: '否'})
    out = assign_aqpp_scenarios(
        out,
        AMOUNT_TOLERANCE,
        QUANTITY_TOLERANCE,
        include_amount_boundary_as_equal=include_amount_boundary,
    )
    out = map_aqpp_to_legacy(out)

    # AQPP与FY25在DMS的0.02边界口径不同：AQPP按金额一致；FY25仍按金额尾差。
    # 正差表示发票>订单，对应FY25场景8；负差对应场景9。
    if include_amount_boundary:
        boundary = out['尾差0.02'].eq('是') & out['AQPP可分类'].fillna(False)
        invoice_gt_order = boundary & out['SIV'].gt(out['SOV'])
        invoice_lt_order = boundary & out['SIV'].lt(out['SOV'])
        out.loc[invoice_gt_order, '去年场景编码'] = '8'
        out.loc[invoice_lt_order, '去年场景编码'] = '9'
        out.loc[invoice_gt_order, '去年场景描述'] = LEGACY_DESCRIPTIONS['8']
        out.loc[invoice_lt_order, '去年场景描述'] = LEGACY_DESCRIPTIONS['9']
        out.loc[boundary, 'AQPP到去年场景映射状态'] = 'DMS尾差按FY25金额差异展示'

    legacy = (
        assign_scenario_oms(out)
        if not is_dms
        else assign_scenario_dms(out)
    )
    out['去年原始判断编码'] = legacy['场景标号'].astype('string')
    out['去年原始判断描述'] = legacy['场景标号'].map(SCENARIO_DESC).fillna('待确认')
    out['去年原始大类'] = legacy['大类']
    out['去年原始细分场景'] = legacy['细分场景']
    out['去年映射与原始判断一致'] = (
        out['去年场景编码'].astype('string') == out['去年原始判断编码'].astype('string')
    )

    # 保留原字段供既有下游兼容，但AQPP字段是今年主要分类口径。
    out['场景标号'] = legacy['场景标号']
    out['大类'] = legacy['大类']
    out['细分场景'] = legacy['细分场景']
    return out


def assign_existing_not_test_scenarios(df: pd.DataFrame, channel: str) -> pd.DataFrame:
    """将不执行普通AQPP的发票按实际三单存在关系归入现有Not Test编码。

    这些发票参与渠道金额完整性核对，但无论订单、发运是否齐全，都不进入
    AQPP-01至AQPP-24。三单均存在时归入NT-00；其余组合使用NT-28至NT-33。
    """
    out = build_three_way_measures(df, channel)
    if channel.upper() == 'DMS':
        out['尾差0.02'] = absolute_equal_to_boundary(
            out['SIV'].sub(out['SOV']), AMOUNT_TOLERANCE
        ).map({True: '是', False: '否'})
    codes = classify_not_test_presence(
        out['存在销售订单'], out['存在发运单'], out['存在销售发票']
    )
    out['AQPP场景编码'] = codes
    out['AQPP场景描述'] = codes.map(NOT_TEST_DESCRIPTIONS)
    out['AQPP分类'] = 'Not Test'
    out['AQPP可分类'] = False
    out['AQPP金额场景编码'] = pd.NA
    out['AQPP金额场景'] = '待确认'
    out['AQPP数量场景编码'] = pd.NA
    out['AQPP数量场景'] = '待确认'
    out = map_aqpp_to_legacy(out)
    out['去年原始判断编码'] = '待确认'
    out['去年原始判断描述'] = '待确认'
    out['去年原始大类'] = '5.有缺失'
    out['去年原始细分场景'] = '5.Not test'
    out['去年映射与原始判断一致'] = False
    out['场景标号'] = pd.to_numeric(out['去年场景编码'], errors='coerce').fillna(0).astype(int)
    out['大类'] = '5.有缺失'
    out['细分场景'] = '5.Not test'
    out['2.Not test'] = True
    return out

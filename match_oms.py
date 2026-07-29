# -*- coding: utf-8 -*-
"""
2026年1-6月 OMS 三单匹配（路径、年度和筛选条件由 config 配置）。
"""

import pandas as pd

from config import (
    get_oms_config, get_output_prefix, ORDER_STATUS_EXCLUDE, OUTPUT_DIR,
    TARGET_YEAR, CANCELLATION_PROCESSING_ENABLED,
)
from cancellation_preprocessing import preprocess_cancellations, split_registered_cancellation_rows
from data_standardization import first_existing_column, normalize_identifier
from invoice_matchability import (
    build_oms_invoice_type_matchability,
    build_oms_order_item_key,
)
from scenario_utils import assign_existing_not_test_scenarios, assign_parallel_scenarios
from invoice_type_policy import (
    apply_invoice_type_policy,
    join_unique,
    select_policy_excluded_for_not_test,
    select_tob_oms_reporting_scope,
)
from export_utils import export_with_classification
from pipeline_common import filter_order_status, filter_target_year, load_preprocessed_sources, nonblank

def _normalize_material_code(ser):
    """物料/料号/item 转字符串并去掉因 float 产生的 '.0'。"""
    return normalize_identifier(ser)


def _build_order_item_key(order_number, material_number):
    """生成无碰撞OMS匹配键；任一组成字段为空时返回缺失。"""
    return build_oms_order_item_key(order_number, material_number)


def load_oms_order_delivery_invoice():
    """读取预处理PKL；标准化由preprocess_2026负责。"""
    return load_preprocessed_sources(get_oms_config())


# ============================================================================
# 主流程
# ============================================================================
def main():
    prefix = get_output_prefix()
    print(f"开始 OMS 三单匹配（{prefix}）...")

    df_order, df_delivery, df_invoice = load_oms_order_delivery_invoice()
    print(f"  订单: {len(df_order):,} 行")
    print(f"  发货: {len(df_delivery):,} 行")
    print(f"  发票: {len(df_invoice):,} 行")

    # 发票列名兼容
    oms_col = first_existing_column(df_invoice, ['OMS销售单号', 'OMS订单号', '销售单号'], required=True, label='OMS销售单号')
    mat_col = first_existing_column(df_invoice, ['物料编码', '料号', '品号', '物料编号'], required=True, label='发票物料编码')

    # 2. 数据预处理
    print("\n数据预处理...")
    df_order = filter_order_status(df_order, ORDER_STATUS_EXCLUDE)
    print(f"  订单过滤后: {len(df_order):,} 行")

    # 订单数据源规范：platform_order_no（DMS订单号）为空 = OMS 订单（直接 OMS 下单）
    if 'platform_order_no' in df_order.columns:
        df_order = df_order.loc[~nonblank(df_order['platform_order_no'])].copy()
        print(f"  订单数据源: OMS 订单（DMS订单号 为空）{len(df_order):,} 行")

    # 发运数据源规范：external_order_no 为空 = OMS 发运；剔除已在 DMS 渠道匹配的发运
    if 'external_order_no' in df_delivery.columns:
        df_delivery = df_delivery.loc[~nonblank(df_delivery['external_order_no'])].copy()
        print(f"  发运数据源: OMS 发运（外部订单号 为空）{len(df_delivery):,} 行")

    if '业务时间' in df_delivery.columns:
        df_delivery['业务时间'] = pd.to_datetime(df_delivery['业务时间'], format='mixed', errors='coerce')

    # 先切OMS渠道，再对较小的渠道子集做类型治理，避免复制整张107列发票宽表。
    df_invoice = apply_invoice_type_policy(
        df_invoice.loc[~nonblank(df_invoice['DMS销售单号'])]
    )
    df_invoice = select_tob_oms_reporting_scope(df_invoice)
    df_invoice_inventory = df_invoice
    if CANCELLATION_PROCESSING_ENABLED:
        cancellation_result = preprocess_cancellations(
            df_invoice_inventory,
            channel='OMS',
            order_col=oms_col,
            material_col=mat_col,
            amount_columns=('实际金额（ZFN1）', '含税金额'),
            quantity_columns=('开票数量（基本单位数量）',),
        )
        df_invoice_inventory = cancellation_result.invoice_inventory
        df_invoice = cancellation_result.matchable_invoices
        df_invoice_review = cancellation_result.review_invoices
        cancellation_details = cancellation_result.cancellation_details
        cancellation_registry = cancellation_result.cancellation_registry
        cancellation_summary = cancellation_result.cancellation_summary
    else:
        matchable_mask = df_invoice['发票类型可参与匹配']
        df_invoice_review = df_invoice.loc[~matchable_mask].copy()
        df_invoice = df_invoice.loc[matchable_mask].copy()
        cancellation_details = pd.DataFrame()
        cancellation_registry = pd.DataFrame()
        cancellation_summary = pd.DataFrame()
    print(f"  可参与匹配发票: {len(df_invoice):,} 行；待确认类型: {len(df_invoice_review):,} 行")
    if not cancellation_summary.empty:
        print(f"  冲销处理组数: {int(cancellation_summary['配对组数'].sum()):,}")
    df_invoice_policy_excluded = select_policy_excluded_for_not_test(df_invoice_review)

    # 发票 → order-item
    inv_with_oms = pd.DataFrame()
    review_with_oms = pd.DataFrame()
    df_invoice_invalid_key_aqpp = pd.DataFrame()
    df_invoice_review_invalid_key = pd.DataFrame()
    if oms_col in df_invoice.columns and mat_col in df_invoice.columns:
        oms_number = normalize_identifier(df_invoice[oms_col])
        material_number = _normalize_material_code(df_invoice[mat_col])
        valid_invoice_key = (
            oms_number.notna() & oms_number.str.strip().ne('')
            & material_number.notna() & material_number.str.strip().ne('')
        )
        inv_with_oms = df_invoice[valid_invoice_key].copy()
        df_invoice_invalid_key_aqpp = df_invoice[~valid_invoice_key].copy()
        if '实际金额（ZFN1）' in df_invoice_invalid_key_aqpp.columns:
            df_invoice_invalid_key_aqpp['开票金额'] = pd.to_numeric(
                df_invoice_invalid_key_aqpp['实际金额（ZFN1）'], errors='coerce'
            )
        inv_with_oms['order-item'] = _build_order_item_key(
            inv_with_oms[oms_col], inv_with_oms[mat_col]
        )

        review_oms_number = normalize_identifier(df_invoice_policy_excluded[oms_col])
        review_material_number = _normalize_material_code(df_invoice_policy_excluded[mat_col])
        valid_review_key = review_oms_number.notna() & review_material_number.notna()
        review_with_oms = df_invoice_policy_excluded.loc[valid_review_key].copy()
        df_invoice_review_invalid_key = df_invoice_policy_excluded.loc[~valid_review_key].copy()
        if '实际金额（ZFN1）' in df_invoice_review_invalid_key.columns:
            df_invoice_review_invalid_key['开票金额'] = pd.to_numeric(
                df_invoice_review_invalid_key['实际金额（ZFN1）'], errors='coerce'
            )
        review_with_oms['order-item'] = _build_order_item_key(
            review_with_oms[oms_col], review_with_oms[mat_col]
        )

    df_invoice_used = inv_with_oms
    df_invoice_invalid_key = pd.concat(
        [df_invoice_invalid_key_aqpp, df_invoice_review_invalid_key],
        ignore_index=True,
        sort=False,
    )

    # 3. 匹配键
    print("\n创建匹配键 order-item...")
    # 2026 订单源 main_order_no 当前全空，因此实际回退到 sale_order_no；保留主单优先以兼容后续月份。
    main = df_order['main_order_no'].replace(r'^\s*$', pd.NA, regex=True)
    df_order['_oms_main'] = main.fillna(df_order['sale_order_no'])
    df_order['order-item'] = _build_order_item_key(df_order['_oms_main'], df_order['item_code'])
    df_order.drop(columns=['_oms_main'], inplace=True)

    if '主单号' in df_delivery.columns and '订单号' in df_delivery.columns and '料号' in df_delivery.columns:
        main = df_delivery['主单号'].replace(r'^\s*$', pd.NA, regex=True)
        df_delivery['_oms_main'] = main.fillna(df_delivery['订单号'])
        df_delivery['order-item'] = _build_order_item_key(df_delivery['_oms_main'], df_delivery['料号'])
        df_delivery.drop(columns=['_oms_main'], inplace=True)
    elif '订单号' in df_delivery.columns and '料号' in df_delivery.columns:
        df_delivery['order-item'] = _build_order_item_key(df_delivery['订单号'], df_delivery['料号'])
    else:
        raise ValueError("发货缺少 订单号 或 料号")

    # 诊断表同时展示“业务政策是否纳入”和“当前数据能否钩稽”。该统计只读取
    # 已构造的键，不改变 AQPP 输入范围，也不把本期缺单据自动固化为类型黑名单。
    oms_type_matchability = build_oms_invoice_type_matchability(
        df_invoice_inventory,
        order_keys=df_order['order-item'],
        delivery_keys=df_delivery['order-item'],
        invoice_order_col=oms_col,
        invoice_material_col=mat_col,
        amount_col='实际金额（ZFN1）',
    )

    # 4. 聚合
    df_order['pay_amount'] = pd.to_numeric(df_order['pay_amount'], errors='coerce').round(2)
    df_order['item_num'] = pd.to_numeric(df_order['item_num'], errors='coerce').round(2)
    order_agg_dict = {'pay_amount': 'sum', 'item_num': 'sum'}
    for col in ['sale_order_no', 'platform_order_no', 'main_order_no', 'channel_name', 'order_type', 'order_status', 'create_time', 'update_time', 'item_code']:
        if col in df_order.columns:
            order_agg_dict[col] = 'first'
    order_agg = df_order.groupby('order-item', as_index=False).agg(order_agg_dict)
    order_agg.rename(columns={'pay_amount': '订单金额', 'item_num': '订单数量',
        'sale_order_no': '订单-销售订单号', 'platform_order_no': '订单-平台订单号', 'main_order_no': '订单-主订单号',
        'channel_name': '订单-渠道名称', 'order_type': '订单-订单类型', 'order_status': '订单-订单状态',
        'create_time': '订单-创建时间', 'update_time': '订单-更新时间', 'item_code': '订单-商品代码'}, inplace=True)

    df_delivery['已发货数量'] = pd.to_numeric(df_delivery['已发货数量'], errors='coerce').round(2)
    delivery_agg_dict = {'已发货数量': 'sum'}
    if '发货金额' in df_delivery.columns:
        delivery_agg_dict['发货金额'] = 'sum'
    for optional_column in ('发货币种', '发货数量单位'):
        if optional_column in df_delivery.columns:
            delivery_agg_dict[optional_column] = 'first'
    for col in ['订单号', '主单号', 'external_order_no', '业务时间', '料号', '名称', 'business_type', 'document_no']:
        if col in df_delivery.columns:
            delivery_agg_dict[col] = 'first'
    delivery_agg = df_delivery.groupby('order-item', as_index=False).agg(delivery_agg_dict)
    delivery_agg.rename(columns={'已发货数量': '发货数量', '订单号': '发货-订单号', '主单号': '发货-主单号',
        'external_order_no': '发货-外部订单号', '业务时间': '发货-业务时间', '料号': '发货-料号',
        '名称': '发货-商品名称', 'business_type': '发货-业务类型', 'document_no': '发货-发货单号'}, inplace=True)

    # 明确使用OMS实际金额及基本单位开票数量，避免模糊循环因列顺序变化选错字段。
    amount_col = first_existing_column(
        df_invoice_used, ['实际金额（ZFN1）'], required=True, label='OMS实际金额（ZFN1）'
    )
    quantity_col = first_existing_column(
        df_invoice_used, ['开票数量（基本单位数量）'], required=True, label='开票基本单位数量'
    )
    untaxed_amount_col = first_existing_column(df_invoice_used, ['无税金额'])

    invoice_review_agg = pd.DataFrame()
    if df_invoice_used.empty or not amount_col or not quantity_col:
        invoice_agg = pd.DataFrame({'order-item': [], '开票金额': [], '开票数量': []})
    else:
        df_invoice_used[amount_col] = pd.to_numeric(df_invoice_used[amount_col], errors='coerce').round(2)
        df_invoice_used[quantity_col] = pd.to_numeric(df_invoice_used[quantity_col], errors='coerce').round(2)
        invoice_agg_dict = {amount_col: 'sum', quantity_col: 'sum'}
        if untaxed_amount_col:
            df_invoice_used[untaxed_amount_col] = pd.to_numeric(
                df_invoice_used[untaxed_amount_col], errors='coerce'
            ).round(2)
            invoice_agg_dict[untaxed_amount_col] = 'sum'
        invoice_extra_map = {}
        for candidates, label in [
            (['SAP发票号', 'SAP发票编号'], '发票-SAP发票号'),
            (['销售组织', '销售组织代码'], '发票-销售组织'),
            (['发票类型', '发票类型.1'], '发票-发票类型'),
            (['开票记账日期', '发票创建日期', '开票日期', '发票日期'], '发票-开票日期'),
            (['DMS销售单号'], '发票-DMS销售单号'),
            (['标准-发票币种'], '标准-发票币种'),
            (['标准-发票数量单位'], '标准-发票数量单位'),
        ]:
            for col in df_invoice_used.columns:
                if any(c in str(col) for c in candidates) and col not in invoice_agg_dict:
                    invoice_agg_dict[col] = join_unique if label == '发票-发票类型' else 'first'
                    invoice_extra_map[col] = label
                    break
        for policy_column in (
            '发票类型代码规范', '发票类型描述规范', '发票类型处理方式',
            '发票类型业务分类', '发票金额方向处理', '冲销处理编码',
            '冲销处理状态', '冲销配对编号', '冲销业务角色', '配对原发票号',
            '配对取消发票号', 'AQPP前置处理',
        ):
            if policy_column in df_invoice_used.columns:
                invoice_agg_dict[policy_column] = join_unique
        if '特殊发票标记' in df_invoice_used.columns:
            invoice_agg_dict['特殊发票标记'] = 'max'
        if oms_col in df_invoice_used.columns and oms_col not in invoice_agg_dict:
            invoice_agg_dict[oms_col] = 'first'
        if mat_col in df_invoice_used.columns and mat_col not in invoice_agg_dict:
            invoice_agg_dict[mat_col] = 'first'
        invoice_agg = df_invoice_used.groupby('order-item', as_index=False).agg(invoice_agg_dict)
        invoice_agg.rename(columns={
            amount_col: '开票金额',
            quantity_col: '开票数量',
            **({untaxed_amount_col: '发票不含税金额'} if untaxed_amount_col else {}),
            **invoice_extra_map,
        }, inplace=True)
        if not review_with_oms.empty:
            for column in (amount_col, quantity_col, untaxed_amount_col):
                if column and column in review_with_oms.columns:
                    review_with_oms[column] = pd.to_numeric(
                        review_with_oms[column], errors='coerce'
                    ).round(2)
            invoice_review_agg = review_with_oms.groupby('order-item', as_index=False).agg(
                invoice_agg_dict
            )
            invoice_review_agg.rename(columns={
                amount_col: '开票金额',
                quantity_col: '开票数量',
                **({untaxed_amount_col: '发票不含税金额'} if untaxed_amount_col else {}),
                **invoice_extra_map,
            }, inplace=True)
    for c in ['开票金额', '开票数量']:
        if c not in invoice_agg.columns:
            invoice_agg[c] = pd.Series(dtype=float)

    # 5. 匹配与分类
    df_matched = invoice_agg.merge(delivery_agg, on='order-item', how='left')
    df_matched = df_matched.merge(order_agg, on='order-item', how='left')

    df_matched['订单-发货数量'] = pd.to_numeric(df_matched['订单数量'], errors='coerce') - pd.to_numeric(df_matched['发货数量'], errors='coerce')
    df_matched['订单-开票数量'] = pd.to_numeric(df_matched['订单数量'], errors='coerce') - pd.to_numeric(df_matched['开票数量'], errors='coerce')
    df_matched['发货-开票数量'] = pd.to_numeric(df_matched['发货数量'], errors='coerce') - pd.to_numeric(df_matched['开票数量'], errors='coerce')
    df_matched['订单-发票金额'] = (pd.to_numeric(df_matched['订单金额'], errors='coerce') - pd.to_numeric(df_matched['开票金额'], errors='coerce')).round(2)

    key_cols = ['订单金额', '订单数量', '发货数量', '开票金额', '开票数量']
    df_matched['2.Not test'] = df_matched[key_cols].isna().any(axis=1)
    df_matched = assign_parallel_scenarios(df_matched, channel='OMS')

    if not invoice_review_agg.empty:
        df_review_matched = invoice_review_agg.merge(
            delivery_agg, on='order-item', how='left'
        ).merge(order_agg, on='order-item', how='left')
        df_review_matched['订单-发货数量'] = pd.to_numeric(
            df_review_matched['订单数量'], errors='coerce'
        ) - pd.to_numeric(df_review_matched['发货数量'], errors='coerce')
        df_review_matched['订单-开票数量'] = pd.to_numeric(
            df_review_matched['订单数量'], errors='coerce'
        ) - pd.to_numeric(df_review_matched['开票数量'], errors='coerce')
        df_review_matched['发货-开票数量'] = pd.to_numeric(
            df_review_matched['发货数量'], errors='coerce'
        ) - pd.to_numeric(df_review_matched['开票数量'], errors='coerce')
        df_review_matched['订单-发票金额'] = (
            pd.to_numeric(df_review_matched['订单金额'], errors='coerce')
            - pd.to_numeric(df_review_matched['开票金额'], errors='coerce')
        ).round(2)
        df_review_matched = assign_existing_not_test_scenarios(
            df_review_matched, channel='OMS'
        )
        df_matched = pd.concat([df_matched, df_review_matched], ignore_index=True, sort=False)

    # 仅保留真正没有任何OMS渠道发票的订单/发运键。
    df_nottested = order_agg.merge(delivery_agg, on='order-item', how='outer')
    invoice_presence = pd.concat([
        invoice_agg[['order-item']],
        invoice_review_agg[['order-item']] if not invoice_review_agg.empty else pd.DataFrame(columns=['order-item']),
    ], ignore_index=True).drop_duplicates()
    invoice_presence['_存在渠道发票'] = True
    df_nottested = df_nottested.merge(invoice_presence, on='order-item', how='left')
    df_nottested = df_nottested.loc[
        df_nottested['_存在渠道发票'].isna()
    ].drop(columns=['_存在渠道发票']).copy()
    registry_for_join = cancellation_registry.copy()
    if not registry_for_join.empty:
        registry_for_join['order-item'] = _build_order_item_key(
            registry_for_join[oms_col], registry_for_join[mat_col]
        )
        df_nottested, cancellation_outer = split_registered_cancellation_rows(
            df_nottested,
            registry_for_join.dropna(subset=['order-item']),
            ['order-item'],
        )
    else:
        cancellation_outer = pd.DataFrame()

    print("\nAQPP分类统计:")
    for category in ['完全匹配', '金额差异', '数量差异', '数量+金额差异', 'Not Test']:
        cnt = (df_matched['AQPP分类'] == category).sum()
        print(f"  {category}: {cnt:,}")

    # 7. df_nottested 分类（仅订单、仅发货单、仅订单及发货单）及目标年度过滤
    has_ord = '订单数量' in df_nottested.columns
    has_dlv = '发货数量' in df_nottested.columns
    ord_na = df_nottested['订单数量'].isna() if has_ord else pd.Series(True, index=df_nottested.index)
    dlv_na = df_nottested['发货数量'].isna() if has_dlv else pd.Series(True, index=df_nottested.index)

    date_cols_oms = ['订单-创建时间', '发货-业务时间', '发票-开票日期']
    extra_categories = {
        '仅订单': filter_target_year(df_nottested[~ord_na & dlv_na], TARGET_YEAR, date_cols_oms),
        '仅发货单': filter_target_year(df_nottested[ord_na & ~dlv_na], TARGET_YEAR, date_cols_oms),
        '仅订单及发货单': filter_target_year(df_nottested[~ord_na & ~dlv_na], TARGET_YEAR, date_cols_oms),
        # 关键匹配键不完整的发票不能参与聚合，但必须保留在未匹配明细中。
        '仅发票': df_invoice_invalid_key,
    }
    if not cancellation_outer.empty:
        exact_mask = cancellation_outer['冲销处理编码'].astype('string').eq('CA-01')
        extra_categories['已冲销净额0'] = cancellation_outer.loc[exact_mask].copy()
        extra_categories['冲销业务待确认'] = cancellation_outer.loc[~exact_mask].copy()

    # OMS 发票总条数、总金额：仅 OMS 发票（已剔除 DMS 匹配发票）
    amt_col_inv = amount_col if amount_col else next(
        (c for c in df_invoice_used.columns if '实际金额' in str(c) or ('金额' in str(c) and 'ZFN1' in str(c))), None
    )
    df_invoice_reporting_scope = pd.concat(
        [df_invoice, df_invoice_policy_excluded],
        ignore_index=True,
        sort=False,
    )
    invoice_no_col = next(
        (column for column in ('SAP发票号', 'SAP发票编号') if column in df_invoice_reporting_scope.columns),
        None,
    )
    invoice_stats = {
        '清单行数': len(df_invoice_reporting_scope),
        'SAP发票数': int(df_invoice_reporting_scope[invoice_no_col].nunique()) if invoice_no_col else 0,
        '匹配键数': len(invoice_agg) + len(invoice_review_agg),
        '发票金额': float(pd.to_numeric(df_invoice_reporting_scope[amt_col_inv], errors='coerce').sum()) if amt_col_inv and amt_col_inv in df_invoice_reporting_scope.columns else 0.0,
        'AQPP范围发票金额': float(pd.to_numeric(df_invoice[amt_col_inv], errors='coerce').sum()) if amt_col_inv and amt_col_inv in df_invoice.columns else 0.0,
    }

    # 8. 导出三份：汇总 / 明细(三单匹配) / 其他未匹配
    print('\n导出...')
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_base = f'{prefix}匹配结果-销售（toB OMS）'
    out_summary = OUTPUT_DIR / f'{out_base}汇总.xlsx'
    out_detail = OUTPUT_DIR / f'{out_base}明细.xlsx'
    out_unmatched = OUTPUT_DIR / f'{out_base}明细-其他未匹配.xlsx'
    df_export = df_matched

    export_with_classification(
        df_export, str(out_detail), "OMS",
        order_inv_diff_col='订单-发票金额',
        extra_categories=extra_categories,
        invoice_stats=invoice_stats,
        special_invoices=df_invoice_review,
        invoice_inventory=df_invoice_inventory,
        aqpp_input_invoices=df_invoice_used,
        invalid_key_invoices=df_invoice_invalid_key_aqpp,
        invoice_matchability_summary=oms_type_matchability,
        cancellation_details=cancellation_details,
        cancellation_summary=cancellation_summary,
        separate_bridge_exclusions=True,
        summary_file=str(out_summary),
        detail_file=str(out_detail),
        unmatched_file=str(out_unmatched),
    )

    print(f'\nOMS 三单匹配完成（{prefix}）')


if __name__ == '__main__':
    main()

# -*- coding: utf-8 -*-
"""2026H1 DMS三单匹配入口；导入模块时不执行数据处理。"""


def main():
    # -*- coding: utf-8 -*-
    """
    DMS 三单匹配（统一脚本，由 config 配置时间范围、路径、筛选条件）

    输入：order_pkl、delivery_pkl、invoice_pkl（与 OMS 共用，由 preprocess 产出）。
    取数：订单 platform_order_no（DMS订单号）非空 = DMS 订单；发货 external_order_no 非空；排除 OBSOLETE/CANCEL。
    """

    import pandas as pd
    from config import (
        get_dms_config, get_output_prefix, ORDER_STATUS_EXCLUDE, OUTPUT_DIR,
        TARGET_YEAR, CANCELLATION_PROCESSING_ENABLED,
    )
    from cancellation_preprocessing import (
        preprocess_cancellations,
        split_registered_cancellation_rows,
    )
    from data_standardization import normalize_identifier
    from scenario_utils import assign_parallel_scenarios
    from invoice_type_policy import (
        aggregate_with_selective_unique_join,
        apply_invoice_type_policy,
        join_unique,
    )
    from export_utils import export_with_classification
    from pipeline_common import filter_order_status, filter_target_year, load_preprocessed_sources, nonblank


    print(f"开始 DMS 三单匹配（{get_output_prefix()}）...")

    # ============================================================================
    # 1. 读取订单、发货、发票（与 OMS 共用 pkl）
    # ============================================================================
    print('\n1. 读取数据...')

    cfg = get_dms_config()
    print('  从预处理PKL读取（与 OMS 共用）...')
    df_order, df_delivery, df_invoice = load_preprocessed_sources(cfg)
    df_order_dms = df_order.loc[nonblank(df_order['platform_order_no'])].copy()
    df_order_dms = filter_order_status(df_order_dms, ORDER_STATUS_EXCLUDE)
    df_delivery_dms = df_delivery.loc[nonblank(df_delivery['external_order_no'])].copy()
    print(f"  DMS 订单行数: {len(df_order_dms):,}")
    print(f"  DMS 发货行数: {len(df_delivery_dms):,}")
    print(f"  发票总行数: {len(df_invoice):,}, 列数: {len(df_invoice.columns)}")

    # ============================================================================
    # 2. 发票类型治理 + DMS数据源规范
    # ============================================================================
    print('\n2. 发票类型治理...')
    dms_order_col = 'DMS销售单号'
    df_invoice_inventory = apply_invoice_type_policy(
        df_invoice.loc[nonblank(df_invoice[dms_order_col])]
    )
    if CANCELLATION_PROCESSING_ENABLED:
        cancellation_result = preprocess_cancellations(
            df_invoice_inventory,
            channel='DMS',
            order_col=dms_order_col,
            material_col='物料编码',
            amount_columns=('含税金额',),
            quantity_columns=('开票数量（基本单位数量）',),
        )
        df_invoice_inventory = cancellation_result.invoice_inventory
        df_invoice_dms = cancellation_result.matchable_invoices
        df_invoice_review = cancellation_result.review_invoices
        cancellation_details = cancellation_result.cancellation_details
        cancellation_registry = cancellation_result.cancellation_registry.rename(columns={
            dms_order_col: 'DMS订单', '物料编码': '物料编码',
        })
        cancellation_summary = cancellation_result.cancellation_summary
    else:
        matchable_mask = df_invoice_inventory['发票类型可参与匹配']
        df_invoice_dms = df_invoice_inventory.loc[matchable_mask].copy()
        df_invoice_review = df_invoice_inventory.loc[~matchable_mask].copy()
        cancellation_details = pd.DataFrame()
        cancellation_registry = pd.DataFrame()
        cancellation_summary = pd.DataFrame()
    print(f"  可参与匹配发票: {len(df_invoice_dms):,}；待确认类型: {len(df_invoice_review):,}")
    if not cancellation_summary.empty:
        print(f"  冲销处理组数: {int(cancellation_summary['配对组数'].sum()):,}")
    print(f"  DMS 发票行数: {len(df_invoice_dms):,}")

    # ============================================================================
    # 3. 聚合（DMS 订单 + 物料编码）
    # ============================================================================
    print('\n3. 按 DMS 订单 + 物料 聚合...')

    amount_col = untaxed_amount_col = quantity_sales_col = quantity_base_col = material_col = None
    for c in df_invoice_dms.columns:
        cs = str(c)
        if cs == '含税金额': amount_col = c
        elif cs == '无税金额': untaxed_amount_col = c
        elif cs == '开票数量（销售单位）': quantity_sales_col = c
        elif cs == '开票数量（基本单位数量）': quantity_base_col = c
        elif cs == '物料编码': material_col = c
    if not amount_col:
        for c in df_invoice_dms.columns:
            if '含税金额' in str(c): amount_col = c; break
    if not quantity_sales_col:
        for c in df_invoice_dms.columns:
            if '开票数量' in str(c) and '销售单位' in str(c): quantity_sales_col = c; break
    if not quantity_base_col:
        for c in df_invoice_dms.columns:
            if '开票数量' in str(c) and '基本单位' in str(c): quantity_base_col = c; break
    if not material_col:
        for c in df_invoice_dms.columns:
            if str(c) == '物料编码' or ('物料' in str(c) and '编码' in str(c)): material_col = c; break

    if not amount_col:
        raise ValueError('未找到发票金额列（含税金额）')
    if not quantity_sales_col or not quantity_base_col:
        raise ValueError('未找到发票数量列（开票数量 销售/基本单位）')
    if not material_col:
        raise ValueError('未找到发票物料编码列')

    df_invoice_dms[amount_col] = pd.to_numeric(df_invoice_dms[amount_col], errors='coerce')
    if untaxed_amount_col:
        df_invoice_dms[untaxed_amount_col] = pd.to_numeric(df_invoice_dms[untaxed_amount_col], errors='coerce')
    df_invoice_dms[quantity_sales_col] = pd.to_numeric(df_invoice_dms[quantity_sales_col], errors='coerce')
    df_invoice_dms[quantity_base_col] = pd.to_numeric(df_invoice_dms[quantity_base_col], errors='coerce')
    df_invoice_dms[dms_order_col] = normalize_identifier(df_invoice_dms[dms_order_col])
    df_invoice_dms[material_col] = normalize_identifier(df_invoice_dms[material_col])

    # 政策允许与“键可聚合”是两层口径。键缺失的发票不得被groupby静默丢弃，
    # 必须保留在NT-30及PBC桥接中。
    df_invoice_policy_allowed = df_invoice_dms
    valid_invoice_key = df_invoice_dms[dms_order_col].notna() & df_invoice_dms[material_col].notna()
    df_invoice_invalid_key = df_invoice_dms.loc[~valid_invoice_key].copy()
    df_invoice_dms = df_invoice_dms.loc[valid_invoice_key].copy()

    # 发票聚合：金额和数量用sum，其他字段用first保留
    invoice_agg_dict = {
        amount_col: 'sum',
        quantity_sales_col: 'sum',
        quantity_base_col: 'sum'
    }
    if untaxed_amount_col:
        invoice_agg_dict[untaxed_amount_col] = 'sum'

    invoice_extra_candidates = [
        (['SAP发票号', 'SAP发票编号', 'SAP账单号', '发票号', '发票编号'], '发票-SAP发票号'),
        (['SAP订单号'], '发票-SAP订单号'),
        (['OMS销售单号', 'OMS订单号', 'OMS主订单号', 'OMS系统订单号'], '发票-OMS订单号'),
        (['公司代码', '公司'], '发票-公司代码'),
        (['发票备注', '备注', '发票说明'], '发票-发票备注'),
        (['发票类型', '发票类型.1'], '发票-发票类型'),
        (['销售组织', '销售组织代码'], '发票-销售组织'),
        (['客户名称', '客户'], '发票-客户名称'),
        (['物料描述', '名称', '物料名称'], '发票-物料名称'),
        (['开票记账日期', '发票创建日期', '开票日期', '发票日期'], '发票-开票日期'),
        (['数据源文件'], '发票-数据源文件'),
        (['标准-发票币种'], '标准-发票币种'),
        (['标准-发票数量单位'], '标准-发票数量单位'),
    ]
    invoice_extra_map, invoice_extra_cols, selective_join_columns = {}, [], []
    for candidates, label in invoice_extra_candidates:
        for col in candidates:
            if col in df_invoice_dms.columns:
                invoice_agg_dict[col] = join_unique if label == '发票-发票类型' else 'first'
                if label == '发票-发票类型':
                    selective_join_columns.append(col)
                invoice_extra_map[col] = label
                invoice_extra_cols.append(col)
                break

    for policy_column in (
        '发票类型代码规范', '发票类型描述规范', '发票类型处理方式',
        '发票类型业务分类', '发票金额方向处理', '冲销处理编码',
        '冲销处理状态', '冲销配对编号', '冲销业务角色', '配对原发票号',
        '配对取消发票号', 'AQPP前置处理',
    ):
        if policy_column in df_invoice_dms.columns:
            invoice_agg_dict[policy_column] = join_unique
            selective_join_columns.append(policy_column)
    if '特殊发票标记' in df_invoice_dms.columns:
        invoice_agg_dict['特殊发票标记'] = 'max'

    pivot_invoice = aggregate_with_selective_unique_join(
        df_invoice_dms,
        [dms_order_col, material_col],
        invoice_agg_dict,
        selective_join_columns,
    )
    pivot_invoice.rename(columns={
        dms_order_col: 'DMS订单',
        material_col: '物料编码',
        amount_col: 'SAP开票含税金额',
        **({untaxed_amount_col: 'SAP开票不含税金额'} if untaxed_amount_col else {}),
        quantity_sales_col: 'SAP开票销售数量',
        quantity_base_col: 'SAP开票基本数量'
    }, inplace=True)

    # 重命名额外字段
    for col in invoice_extra_cols:
        if col in pivot_invoice.columns:
            pivot_invoice.rename(columns={col: invoice_extra_map[col]}, inplace=True)

    pivot_invoice['SAP开票含税金额'] = pivot_invoice['SAP开票含税金额'].round(2)
    pivot_invoice['SAP开票销售数量'] = pivot_invoice['SAP开票销售数量'].round(2)
    pivot_invoice['SAP开票基本数量'] = pivot_invoice['SAP开票基本数量'].round(2)
    print(f"  发票聚合: {len(pivot_invoice):,} 条")

    # 订单聚合
    df_order_dms['pay_amount'] = pd.to_numeric(df_order_dms['pay_amount'], errors='coerce')
    df_order_dms['item_num'] = pd.to_numeric(df_order_dms['item_num'], errors='coerce')
    df_order_dms['item_code'] = normalize_identifier(df_order_dms['item_code'])

    # 订单聚合：金额和数量用sum，其他字段用first保留
    order_agg_dict = {'pay_amount': 'sum', 'item_num': 'sum'}
    order_extra_candidates = [
        (['sale_order_no'], '订单-销售订单号'),
        (['main_order_no'], '订单-主订单号'),
        (['channel_name'], '订单-渠道名称'),
        (['order_type'], '订单-订单类型'),
        (['order_status'], '订单-订单状态'),
        (['create_time'], '订单-创建时间'),
        (['update_time'], '订单-更新时间')
    ]
    order_extra_map, order_extra_cols = {}, []
    for candidates, label in order_extra_candidates:
        for col in candidates:
            if col in df_order_dms.columns:
                order_agg_dict[col] = 'first'
                order_extra_map[col] = label
                order_extra_cols.append(col)
                break

    pivot_order = df_order_dms.groupby(['platform_order_no', 'item_code'], as_index=False).agg(order_agg_dict)
    pivot_order.rename(columns={
        'platform_order_no': 'DMS订单',
        'item_code': '物料编码',
        'pay_amount': 'DMS订单金额',
        'item_num': 'DMS订单数量'
    }, inplace=True)

    # 重命名额外字段
    for col in order_extra_cols:
        if col in pivot_order.columns:
            pivot_order.rename(columns={col: order_extra_map[col]}, inplace=True)

    # 添加平台订单号和商品代码作为订单字段（虽然它们已经在DMS订单和物料编码中）
    pivot_order['订单-平台订单号'] = pivot_order['DMS订单']
    pivot_order['订单-商品代码'] = pivot_order['物料编码']

    pivot_order['DMS订单金额'] = pivot_order['DMS订单金额'].round(2)
    pivot_order['DMS订单数量'] = pivot_order['DMS订单数量'].round(2)
    print(f"  DMS 订单聚合: {len(pivot_order):,} 条")

    # 发货聚合：数量用sum，其他字段用first保留
    df_delivery_dms['已发货数量'] = pd.to_numeric(df_delivery_dms['已发货数量'], errors='coerce')
    df_delivery_dms['料号'] = normalize_identifier(df_delivery_dms['料号'])

    delivery_agg_dict = {'已发货数量': 'sum'}
    if '发货金额' in df_delivery_dms.columns:
        delivery_agg_dict['发货金额'] = 'sum'
    for optional_column in ('发货币种', '发货数量单位'):
        if optional_column in df_delivery_dms.columns:
            delivery_agg_dict[optional_column] = 'first'
    delivery_extra_candidates = [
        (['document_no'], '发货-发货单号'),
        (['订单号'], '发货-订单号'),
        (['主单号'], '发货-主单号'),
        (['业务时间'], '发货-业务时间'),
        (['名称'], '发货-物料名称'),
        (['business_type'], '发货-业务类型')
    ]
    delivery_extra_map, delivery_extra_cols = {}, []
    for candidates, label in delivery_extra_candidates:
        for col in candidates:
            if col in df_delivery_dms.columns:
                delivery_agg_dict[col] = 'first'
                delivery_extra_map[col] = label
                delivery_extra_cols.append(col)
                break

    pivot_delivery = df_delivery_dms.groupby(['external_order_no', '料号'], as_index=False).agg(delivery_agg_dict)
    pivot_delivery.rename(columns={
        'external_order_no': 'DMS订单',
        '料号': '物料编码',
        '已发货数量': 'DMS发货数量'
    }, inplace=True)

    # 重命名额外字段
    for col in delivery_extra_cols:
        if col in pivot_delivery.columns:
            pivot_delivery.rename(columns={col: delivery_extra_map[col]}, inplace=True)

    # 添加外部订单号和料号作为发货字段
    pivot_delivery['发货-外部订单号'] = pivot_delivery['DMS订单']
    pivot_delivery['发货-料号'] = pivot_delivery['物料编码']

    pivot_delivery['DMS发货数量'] = pivot_delivery['DMS发货数量'].round(2)
    print(f"  DMS 发货聚合: {len(pivot_delivery):,} 条")

    # ============================================================================
    # 4. 匹配、差异、分类
    # ============================================================================
    print('\n4. 匹配与差异计算...')

    df_join = pivot_invoice.merge(pivot_order, on=['DMS订单', '物料编码'], how='left')
    df_join = df_join.merge(pivot_delivery, on=['DMS订单', '物料编码'], how='left')

    df_join['SAP-DMS订单金额'] = (df_join['SAP开票含税金额'] - df_join['DMS订单金额']).round(2)
    df_join['SAP-DMS订单数量(基本单位)'] = (df_join['SAP开票基本数量'] - df_join['DMS订单数量']).round(2)
    df_join['SAP-DMS发货数量(基本单位)'] = (df_join['SAP开票基本数量'] - df_join['DMS发货数量']).round(2)
    df_join['SAP-DMS发货数量'] = df_join['SAP-DMS发货数量(基本单位)']

    # 四大类+细分场景（统一规范，参考 refer/difference_analysis.py）
    df_join['2.Not test'] = df_join[
        ['DMS订单金额', 'DMS订单数量', 'DMS发货数量', 'SAP开票含税金额', 'SAP开票基本数量']
    ].isna().any(axis=1)
    df_join = assign_parallel_scenarios(df_join, channel='DMS')

    # df_nottested: 订单+发货 无发票（DMS 订单 outer join 发货 outer join 发票，过滤无开票）
    df_nottested = pivot_order.merge(pivot_delivery, on=['DMS订单', '物料编码'], how='outer')
    df_nottested = df_nottested.merge(pivot_invoice, on=['DMS订单', '物料编码'], how='outer')
    df_nottested = df_nottested[df_nottested['SAP开票基本数量'].isna()].copy()

    # 已识别冲销业务键不能在删除冲销发票后重新落入“仅订单及发货单”。
    if not cancellation_registry.empty:
        df_nottested, cancellation_outer = split_registered_cancellation_rows(
            df_nottested,
            cancellation_registry,
            ['DMS订单', '物料编码'],
        )
    else:
        cancellation_outer = pd.DataFrame()

    date_cols_dms = ['订单-创建时间', '发货-业务时间', '发票-开票日期']
    has_ord = df_nottested['DMS订单金额'].notna()
    has_dlv = df_nottested['DMS发货数量'].notna()
    extra_categories = {
        '仅订单': filter_target_year(df_nottested[has_ord & ~has_dlv], TARGET_YEAR, date_cols_dms),
        '仅发货单': filter_target_year(df_nottested[~has_ord & has_dlv], TARGET_YEAR, date_cols_dms),
        '仅订单及发货单': filter_target_year(df_nottested[has_ord & has_dlv], TARGET_YEAR, date_cols_dms),
        '仅发票': df_invoice_invalid_key,
    }
    if not cancellation_outer.empty:
        exact_mask = cancellation_outer['冲销处理编码'].astype('string').eq('CA-01')
        extra_categories['已冲销净额0'] = cancellation_outer.loc[exact_mask].copy()
        extra_categories['冲销业务待确认'] = cancellation_outer.loc[~exact_mask].copy()

    # 统一统计粒度：清单行数/SAP发票数来自政策允许发票，匹配键数来自聚合结果。
    invoice_no_col = next(
        (column for column in ('SAP发票号', 'SAP发票编号') if column in df_invoice_policy_allowed.columns),
        None,
    )
    invoice_stats = {
        '清单行数': len(df_invoice_policy_allowed),
        'SAP发票数': int(df_invoice_policy_allowed[invoice_no_col].nunique()) if invoice_no_col else 0,
        '匹配键数': len(pivot_invoice),
        '发票金额': float(pd.to_numeric(df_invoice_policy_allowed[amount_col], errors='coerce').sum()),
    }

    print('  AQPP分类统计:')
    for category in ['完全匹配', '金额差异', '数量差异', '数量+金额差异', 'Not Test']:
        cnt = (df_join['AQPP分类'] == category).sum()
        print(f"    {category}: {cnt:,}")

    # ============================================================================
    # 5. 导出三份：汇总 / 明细(三单匹配) / 其他未匹配
    # ============================================================================
    print('\n5. 导出（汇总 / 三单匹配明细 / 其他未匹配）...')

    EXCEL_MAX = 1_048_575

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _prefix = get_output_prefix()
    out_base = f'{_prefix}匹配结果-销售（toB DMS）'
    out_summary = OUTPUT_DIR / f'{out_base}汇总.xlsx'
    out_detail = OUTPUT_DIR / f'{out_base}明细.xlsx'
    out_unmatched = OUTPUT_DIR / f'{out_base}明细-其他未匹配.xlsx'
    df_export = df_join

    # 超限时先保存 CSV 全量（参考原逻辑）
    if len(df_export) > EXCEL_MAX:
        csv_path = out_detail.with_suffix('.csv')
        df_export.to_csv(str(csv_path), index=False, encoding='utf-8-sig')
        print(f"  全量主明细: 已保存CSV全量 {csv_path} ({len(df_export):,} 行)")

    export_with_classification(
        df_export, str(out_detail), "DMS",
        inv_minus_order_col='SAP-DMS订单金额',
        amount_label='SAP开票含税金额',
        extra_categories=extra_categories,
        invoice_stats=invoice_stats,
        special_invoices=df_invoice_review,
        invoice_inventory=df_invoice_inventory,
        aqpp_input_invoices=df_invoice_dms,
        invalid_key_invoices=df_invoice_invalid_key,
        cancellation_details=cancellation_details,
        cancellation_summary=cancellation_summary,
        summary_file=str(out_summary),
        detail_file=str(out_detail),
        unmatched_file=str(out_unmatched),
    )

    print(f'\nDMS 三单匹配完成（{get_output_prefix()}）。')


if __name__ == '__main__':
    main()

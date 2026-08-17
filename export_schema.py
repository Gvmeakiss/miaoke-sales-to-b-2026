# -*- coding: utf-8 -*-
"""
导出字段规范 - 参考 refer/three_lists.py

统一命名：订单日期、订单类型、发票类型、匹配订单号、发货单号 等，使导出清单规范化。
"""

import pandas as pd

# 明细中不展示的诊断/交叉验证字段
DETAIL_DROP_COLUMNS = [
    # 场景分类用于拆分sheet，不在明细中重复展示；其余字段已有等价信息。
    'AQPP分类', '场景分类', '去年场景编码',
    'AQPP金额场景', '金额场景', 'AQPP数量场景', '数量场景',
    'GDNV', '发货金额口径',
    'AQPP金额场景编码', 'AQPP数量场景编码', 'AQPP可分类', 'AQPP到去年场景映射状态',
    '去年原始判断编码', '去年原始判断描述', '去年映射与原始判断一致',
    '去年原始大类', '去年原始细分场景',
    'AQPP金额口径完整', 'AQPP数量口径完整', '币种校验状态', '数量单位校验状态',
    '发票金额方向处理',
    # 类型治理字段仅供内部筛选；对外明细保留原始“发票类型”即可。
    '发票类型代码规范', '发票类型描述规范', '发票类型处理方式',
    '发票类型业务分类', '发票类型可参与匹配', '特殊发票标记',
]

# 英文口径列改为中文展示名
EXPORT_RENAME = {
    '订单-创建时间': '订单日期',
    '订单-订单类型': '订单类型',
    'AQPP场景编码': '场景编码',
    'AQPP场景描述': '场景描述',
    'SIV': '发票金额口径',
    'SOV': '订单金额口径',
    'SIQ': '发票数量口径',
    'SOQ': '订单数量口径',
    'GDNQ': '发货数量口径',
}

# 规范字段优先顺序（核心标识与业务关键字段优先）
EXPORT_COLUMN_ORDER = [
    # 1. 审计索引与场景结论
    '公司代码', '场景编码', '场景描述', '去年场景描述',
    # 2. 三单追溯标识
    '匹配订单号', 'order-item', 'DMS订单', '物料编码',
    '发票-客户名称', '发票-物料名称',
    '发票-SAP发票号', '发票类型', '发票-发票类型', '发票-开票日期', '发票-销售组织',
    '冲销处理编码', '冲销处理状态', '冲销配对编号', '冲销业务角色',
    '配对原发票号', '配对取消发票号', '冲销原发票号', '冲销配对状态', 'AQPP前置处理',
    '订单-主订单号', '订单-销售订单号', '订单-平台订单号', '订单日期', '订单类型',
    '订单-订单状态', '订单-渠道名称', '订单-商品代码', '订单-更新时间',
    '发货单号', '发货-订单号', '发货-主单号', '发货-外部订单号',
    '发货-业务时间', '发货-料号', '发货-商品名称', '发货-业务类型',
    # 3. 金额口径与金额差异
    '发票金额口径', '开票金额', '发票含税金额', 'SAP开票含税金额', '发票不含税金额', 'SAP开票不含税金额',
    '订单金额口径', '订单金额', 'DMS订单金额',
    '订单-发票金额', 'SAP-DMS订单金额', '尾差0.02',
    # 4. 数量口径与数量差异
    '发票数量口径', '开票数量', 'SAP开票基本数量', 'SAP开票销售数量',
    '订单数量口径', '订单数量', 'DMS订单数量',
    '发货数量口径', '发货数量', 'DMS发货数量',
    '订单-发货数量', '订单-开票数量', '发货-开票数量',
    'SAP-DMS订单数量(基本单位)', 'SAP-DMS发货数量(基本单位)', 'SAP-DMS发货数量',
    # 5. 完整性及去年兼容字段
    '存在销售订单', '存在发运单', '存在销售发票',
    '大类', '细分场景', '2.Not test',
]


def _resolve_match_order_series(df):
    """获取匹配订单号：OMS主单为空时回退销售单，DMS使用DMS订单。"""
    if 'DMS订单' in df.columns:
        return df['DMS订单']
    if '订单-主订单号' in df.columns:
        main = df['订单-主订单号'].replace(r'^\s*$', pd.NA, regex=True)
        if '订单-销售订单号' in df.columns:
            return main.fillna(df['订单-销售订单号'])
        return main
    return None


def apply_export_schema(df):
    """
    对匹配结果 DataFrame 应用导出规范：
    1. 删除明细不需要的诊断字段
    2. 添加/规范 匹配订单号、订单日期、订单类型、发票类型、发货单号
    3. 英文口径列改为中文
    4. 按优先顺序调整列顺序（不删除其余业务列）
    """
    if df.empty:
        return df
    out = df.copy()
    out = out.drop(columns=[c for c in DETAIL_DROP_COLUMNS if c in out.columns], errors='ignore')

    match_series = _resolve_match_order_series(out)
    if match_series is not None and '匹配订单号' not in out.columns:
        out['匹配订单号'] = match_series

    if '订单-创建时间' in out.columns and '订单日期' not in out.columns:
        out['订单日期'] = out['订单-创建时间']
        out = out.drop(columns=['订单-创建时间'], errors='ignore')
    if '订单-订单类型' in out.columns and '订单类型' not in out.columns:
        out['订单类型'] = out['订单-订单类型']
        out = out.drop(columns=['订单-订单类型'], errors='ignore')

    inv_type_col = next(
        (c for c in out.columns if '发票' in str(c) and '类型' in str(c) and c not in (
            '发票类型代码规范', '发票类型描述规范', '发票类型处理方式', '发票类型业务分类', '发票类型可参与匹配',
        )),
        None,
    )
    if inv_type_col and '发票类型' not in out.columns:
        out['发票类型'] = out[inv_type_col]
        if inv_type_col in ('发票-发票类型', '发票类型.1'):
            out = out.drop(columns=[inv_type_col], errors='ignore')

    if '发货-发货单号' in out.columns:
        out['发货单号'] = out['发货-发货单号']
    elif '发货-订单号' in out.columns:
        out['发货单号'] = out['发货-订单号']
    elif '发货-主单号' in out.columns:
        out['发货单号'] = out['发货-主单号']

    rename_map = {old: new for old, new in EXPORT_RENAME.items() if old in out.columns and new not in out.columns}
    # 若目标列已存在（如订单金额），则丢掉重复的英文口径列
    for old, new in EXPORT_RENAME.items():
        if old in out.columns and new in out.columns and old != new:
            out = out.drop(columns=[old], errors='ignore')
    out = out.rename(columns=rename_map)

    order_set = [c for c in EXPORT_COLUMN_ORDER if c in out.columns]
    rest = [c for c in out.columns if c not in order_set]
    out = out[order_set + rest]
    return out

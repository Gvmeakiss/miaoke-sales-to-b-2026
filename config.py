# -*- coding: utf-8 -*-
"""2026 年 1-6 月 toB 三单匹配配置。"""

from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent
BASE = CODE_DIR.parent
INPUT_DIR = BASE / 'input'
OUTPUT_DIR = BASE / 'output' / '2026H1'
PKL_DIR = BASE / 'pkl' / '2026H1'

ORDER_SQL = INPUT_DIR / '订单清单：25.12.01-26.06.30.sql'
DELIVERY_SQL = INPUT_DIR / '发运单清单：25.12.01-26.06.30.sql'
INVOICE_DIR = INPUT_DIR / '发票清单：26.01.01-26.06.30'

OUTPUT_PREFIX = '2026年1-6月'
TARGET_YEAR = 2026
ORDER_PKL = PKL_DIR / '2026年1-6月订单.pkl'
DELIVERY_PKL = PKL_DIR / '2026年1-6月发运.pkl'
INVOICE_PKL = PKL_DIR / '2026年1-6月SAP发票.pkl'


def get_oms_config():
    return {
        'order_pkl': ORDER_PKL,
        'delivery_pkl': DELIVERY_PKL,
        'invoice_pkl': INVOICE_PKL,
    }


def get_dms_config():
    return {
        'order_pkl': ORDER_PKL,
        'delivery_pkl': DELIVERY_PKL,
        'invoice_pkl': INVOICE_PKL,
    }


def get_output_prefix():
    return OUTPUT_PREFIX


ORDER_STATUS_EXCLUDE = ['OBSOLETE', 'CANCEL']
# 发票类型规则集中配置。贸易类已通过2026H1订单、发运、发票键覆盖检查；
# 退货、借贷项和冲销类不直接进入普通AQPP，先保留业务诊断及配对信息。
INVOICE_TYPE_RULES = {
    'ZA01': {'action': '正常参与匹配', 'business': '标准发票', 'special': False},
    'ZA02': {'action': '仅保留非toB待确认明细', 'business': '标准发票（2C）', 'special': True},
    'ZA03': {'action': '正常参与匹配', 'business': '现货贸易发票', 'special': False},
    'ZA04': {'action': '正常参与匹配', 'business': '期货贸易发票', 'special': False},
    'ZA05': {'action': '正常参与匹配', 'business': '代拍贸易发票', 'special': False},
    'ZA06': {'action': '仅保留特殊业务明细', 'business': '行政/工厂发票', 'special': True},
    'ZA07': {'action': '特殊场景参与匹配', 'business': '工厂成品销售发票', 'special': True},
    'ZB01': {'action': '特殊场景参与匹配', 'business': '物流赔偿发票', 'special': True},
    'ZB02': {'action': '仅保留退货待确认明细', 'business': '标准退货发票', 'special': True},
    'ZB05': {'action': '仅保留金额调整明细', 'business': '借项发票', 'special': True},
    'ZB06': {'action': '仅保留金额调整明细', 'business': '贷项发票', 'special': True},
    'ZQ01': {'action': '仅保留冲销配对明细', 'business': '取消标准发票（2B）', 'special': True},
    'ZQ03': {'action': '仅保留冲销配对明细', 'business': '取消现货贸易发票', 'special': True},
    'ZQ06': {'action': '仅保留冲销配对明细', 'business': '取消物流赔偿发票', 'special': True},
    'ZQ07': {'action': '仅保留冲销配对明细', 'business': '取消标准退货发票', 'special': True},
    'ZQ09': {'action': '仅保留冲销配对明细', 'business': '取消贷项发票', 'special': True},
    'ZQ10': {'action': '仅保留冲销配对明细', 'business': '取消行政/工厂发票', 'special': True},
}
INVOICE_DESCRIPTION_RULES = {
    '标准发票（2B)': 'ZA01',
    '标准发票（2C)': 'ZA02',
    '现货贸易发票': 'ZA03',
    '期货贸易发票': 'ZA04',
    '代拍贸易发票': 'ZA05',
    '行政/工厂发票': 'ZA06',
    '工厂成品销售发票': 'ZA07',
    '物流赔偿发票': 'ZB01',
    '标准退货发票': 'ZB02',
    '借项发票': 'ZB05',
    '贷项发票': 'ZB06',
    '取消标准发票（2B)': 'ZQ01',
    '取消现货贸易发票': 'ZQ03',
    '取消物流赔偿发票': 'ZQ06',
    '取消标准退货发票': 'ZQ07',
    '取消贷项发票': 'ZQ09',
    '取消行政/工厂发票': 'ZQ10',
}
INVOICE_TYPE_DEFAULT_ACTION = '仅保留待确认明细'

# 原始发票 PBC 的渠道/业务范围拆分规则。
#
# 该配置只回答“原始发票行本来属于哪个完整性核对范围”，不执行发票类型政策、
# 冲销净额化或匹配键完整性判断。DMS销售单号非空时始终优先归入ToB-DMS；
# 仅当DMS销售单号为空时，才按下列类型归入OMS、To C或其他。
# 因此冲销发票和OMS关键键缺失行仍保留在其原渠道文件夹，四个范围无遗漏、无重复。
PBC_INVOICE_SCOPE_TYPES = {
    'ToB-OMS': {
        'ZA04', 'ZA01', 'ZA03', 'ZA06', 'ZA07', 'ZQ10',
        'ZB02', 'ZB01', 'ZQ07', 'ZQ01', 'ZQ06', 'ZQ03',
    },
    'ToC': {'ZA02'},
    '其他': {'ZB05', 'ZB06', 'ZA05', 'ZQ09'},
}
PBC_INVOICE_SCOPE_DEFAULT = '其他'

CANCELLATION_INVOICE_TYPES = {'ZQ01', 'ZQ03', 'ZQ06', 'ZQ07', 'ZQ09', 'ZQ10'}
# 取消/冲销发票与原发票类型的明确关系。冲销必须优先使用SAP原发票引用，
# 不能仅凭订单号、金额相反等弱条件自动配对。
CANCELLATION_ORIGINAL_TYPE_MAP = {
    # 2026H1存在一组ZQ01按SAP原发票号明确冲销ZA07，且金额、数量均归零；
    # 因此ZQ01允许两种原发票类型，仍必须满足原发票引用及净额校验。
    'ZQ01': ('ZA01', 'ZA07'),
    'ZQ03': ('ZA03',),
    'ZQ06': ('ZB01',),
    'ZQ07': ('ZB02',),
    'ZQ09': ('ZB06',),
    'ZQ10': ('ZA06',),
}
CANCELLATION_PROCESSING_ENABLED = True

# 金额和数量分别使用集中配置的容差。所有AQPP及去年场景判断均引用这里，
# 不允许在主流程中散落硬编码阈值或直接用浮点数做 a == b 判断。
AMOUNT_TOLERANCE = 0.02
QUANTITY_TOLERANCE = 0.02
AMOUNT_TAIL_TOLERANCE = 1.0

# DMS业务确认：AQPP金额一致使用abs(diff)<=0.02；数量三方同时一致时归入
# AQPP-01。OMS仍沿用严格abs(diff)<0.02。FY25兼容汇总仍把=0.02列作金额尾差。
DMS_AMOUNT_TOLERANCE_INCLUSIVE = True

# 浮点运算保护带。默认业务边界仍是严格的 ``abs(diff) < tolerance``；
# DMS的±0.02例外由上方单独开关控制。保护带仅消除二进制浮点边界误判。
FLOAT_BOUNDARY_EPSILON = 1e-9

# 2026H1订单及发运源未提供币种/数量单位字段。只有发票币种为本位币时，
# 才允许在明确假设下进入AQPP；非本位币必须取得订单/发运币种后再判断。
BASE_CURRENCY = 'CNY'
ASSUME_BASE_CURRENCY_WHEN_ORDER_MISSING = True
# 财务已确认OMS订单、发运与发票的货币种类一致。OMS源缺订单/发运币种时，
# 允许沿用发票币种（包括USD）进入AQPP；该确认不外推到DMS。
OMS_FINANCE_CONFIRMED_CURRENCY_CONSISTENCY = True
ASSUME_BASIC_QUANTITY_UNIT = True
AQPP_ALLOWED_CURRENCY_STATUSES = {
    '一致',
    '假定一致-订单发运未提供币种，按CNY',
    '财务确认一致-订单发运未提供币种，按发票币种',
}
AQPP_ALLOWED_UNIT_STATUSES = {
    '一致',
    '假定一致-三方数量字段按基本单位',
}

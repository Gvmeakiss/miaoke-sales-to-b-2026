#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证 2026 PKL 的字段、渠道区分和关键匹配键。"""

import pandas as pd

from config import DELIVERY_PKL, INVOICE_PKL, ORDER_PKL


def require(df, columns, label):
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise ValueError(f'{label}缺少字段：{missing}')


def nonblank(series):
    return series.notna() & series.astype(str).str.strip().ne('')


def norm(series):
    return series.astype('string').str.strip().str.replace(r'\.0$', '', regex=True)


def main():
    order = pd.read_pickle(ORDER_PKL)
    delivery = pd.read_pickle(DELIVERY_PKL)
    invoice = pd.read_pickle(INVOICE_PKL)
    require(order, ['platform_order_no', 'main_order_no', 'sale_order_no', 'item_code', 'pay_amount', 'item_num'], '订单')
    require(delivery, ['订单号', 'external_order_no', 'main_order_no', '主单号', '料号', '已发货数量', 'document_no'], '发运')
    require(invoice, ['OMS销售单号', 'OMS出库单号', 'DMS销售单号', '物料编码', '含税金额', '实际金额（ZFN1）', '开票数量（基本单位数量）'], '发票')

    dms_orders = nonblank(order['platform_order_no'])
    dms_invoices = nonblank(invoice['DMS销售单号'])
    dms_deliveries = nonblank(delivery['external_order_no'])
    print(f'订单：{len(order):,} 行；DMS={dms_orders.sum():,}，OMS={(~dms_orders).sum():,}')
    print(f'发运：{len(delivery):,} 行；DMS={dms_deliveries.sum():,}，OMS={(~dms_deliveries).sum():,}')
    print(f'发票：{len(invoice):,} 行；DMS={dms_invoices.sum():,}，OMS={(~dms_invoices).sum():,}')

    # 2026 订单源的 main_order_no 当前为空；OMS订单键须回退到 sale_order_no。
    oms_order = order[~dms_orders]
    main_count = int(nonblank(oms_order['main_order_no']).sum())
    sale_count = int(nonblank(oms_order['sale_order_no']).sum())
    if sale_count == 0:
        raise ValueError('OMS订单 sale_order_no 全为空，无法匹配')
    print(f'OMS订单键：main_order_no非空={main_count:,}；sale_order_no非空={sale_count:,}')

    # 拆单发运须使用 main_order_no；用发票 OMS销售单号+物料进行实际命中复核。
    oms_invoice = invoice[~dms_invoices]
    inv_oms_keys = set(zip(norm(oms_invoice['OMS销售单号']), norm(oms_invoice['物料编码'])))
    split_delivery = delivery[(~dms_deliveries) & nonblank(delivery['main_order_no'])]
    main_keys = set(zip(norm(split_delivery['main_order_no']), norm(split_delivery['料号'])))
    child_keys = set(zip(norm(split_delivery['订单号']), norm(split_delivery['料号'])))
    main_hits = len(inv_oms_keys & main_keys)
    child_hits = len(inv_oms_keys & child_keys)
    if main_hits <= child_hits:
        raise ValueError(f'OMS拆单键异常：主单命中={main_hits}，子单命中={child_hits}')
    print(f'OMS拆单发运命中：main_order_no+料号={main_hits:,}；订单号+料号={child_hits:,}')

    # document_no 应与发票 OMS出库单号对应；在本期发票范围内应有高命中率。
    inv_doc_keys = set(zip(norm(invoice['OMS出库单号']), norm(invoice['物料编码'])))
    inv_doc_keys = {key for key in inv_doc_keys if key[0] is not pd.NA and pd.notna(key[0])}
    delivery_doc_keys = set(zip(norm(delivery['document_no']), norm(delivery['料号'])))
    doc_hits = len(inv_doc_keys & delivery_doc_keys)
    doc_rate = doc_hits / len(inv_doc_keys) if inv_doc_keys else 0
    if doc_rate < 0.95:
        raise ValueError(f'OMS出库单号/document_no 命中率过低：{doc_rate:.2%}')
    print(f'发运单号命中：{doc_hits:,}/{len(inv_doc_keys):,}（{doc_rate:.2%}）')
    print('2026 PKL 字段验证通过。')


if __name__ == '__main__':
    main()

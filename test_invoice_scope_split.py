# -*- coding: utf-8 -*-
"""原始发票PBC范围拆分的小样本测试，不生成Excel。"""

import unittest

import pandas as pd

from split_invoice_by_scope_and_type import classify_invoice_scope


class InvoiceScopeSplitTest(unittest.TestCase):
    def test_pre_match_scope_keeps_cancellations_and_missing_oms_key(self):
        invoice = pd.DataFrame({
            'DMS销售单号': ['D-1', 'D-2', None, None, None, None, None],
            'OMS销售单号': [None, None, 'O-1', None, 'O-2', 'O-3', None],
            '发票类型': ['ZA01', 'ZQ01', 'ZA01', 'ZQ10', 'ZA02', 'ZA05', '未知'],
        })

        result = classify_invoice_scope(invoice)

        self.assertEqual(result.tolist(), [
            'ToB-DMS',  # DMS优先
            'ToB-DMS',  # 冲销类型仍留DMS
            'ToB-OMS',
            'ToB-OMS',  # OMS销售单号缺失不改变原PBC范围
            'ToC',
            '其他',
            '其他',
        ])

    def test_input_dataframe_is_not_modified(self):
        invoice = pd.DataFrame({'DMS销售单号': [None], '发票类型': ['ZA02']})
        original = invoice.copy(deep=True)
        classify_invoice_scope(invoice)
        pd.testing.assert_frame_equal(invoice, original)


if __name__ == '__main__':
    unittest.main()

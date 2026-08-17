# -*- coding: utf-8 -*-
"""发票宽表选择性多值聚合测试。"""

import unittest

import pandas as pd

from invoice_type_policy import aggregate_with_selective_unique_join, join_unique


class InvoiceAggregationTests(unittest.TestCase):
    def test_only_duplicate_keys_need_unique_text_join(self):
        source = pd.DataFrame({
            '订单': ['A', 'A', 'B'], '物料': ['M1', 'M1', 'M2'],
            '金额': [100.0, -20.0, 50.0],
            '类型': ['ZA01', 'ZQ01', 'ZA03'],
            '状态': ['正常', '冲销', '正常'],
        })
        result = aggregate_with_selective_unique_join(
            source,
            ['订单', '物料'],
            {'金额': 'sum', '类型': join_unique, '状态': join_unique},
            ['类型', '状态'],
        ).set_index(['订单', '物料'])
        self.assertEqual(result.loc[('A', 'M1'), '金额'], 80.0)
        self.assertEqual(result.loc[('A', 'M1'), '类型'], 'ZA01|ZQ01')
        self.assertEqual(result.loc[('A', 'M1'), '状态'], '正常|冲销')
        self.assertEqual(result.loc[('B', 'M2'), '类型'], 'ZA03')


if __name__ == '__main__':
    unittest.main()

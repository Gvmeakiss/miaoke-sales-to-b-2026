# -*- coding: utf-8 -*-
"""FY25格式汇总的小样本测试，不读取或生成生产结果。"""

import unittest

import pandas as pd

from legacy_summary import build_fy25_format_summary


class LegacySummaryTests(unittest.TestCase):
    def test_complete_not_test_matrix_and_totals(self):
        data = pd.DataFrame({
            'AQPP可分类': [True, True, True, False],
            'AQPP分类': ['完全匹配', '金额差异', '数量+金额差异', 'Not Test'],
            'AQPP场景编码': ['AQPP-01', 'AQPP-09', 'AQPP-19', 'NT-32'],
            '去年场景编码': ['10', '8', '13', '14'],
            'SIQ': [10, 10, 8, 2],
            'SOQ': [10, 10, 10, 2],
            'GDNQ': [10, 10, 10, 0],
            'SAP开票含税金额': [100.0, 50.0, 30.0, 20.0],
            'SAP-DMS订单金额': [0.0, -0.5, -5.0, -1.0],
        })
        original_columns = data.columns.tolist()
        extra = {
            '仅订单': pd.DataFrame({'订单': ['1', '2']}),
            '仅发货单': pd.DataFrame({'发运': ['1']}),
            '仅订单及发货单': pd.DataFrame({'订单': ['3'], '发运': ['2']}),
            '仅发票': pd.DataFrame({'SAP开票含税金额': [10.0]}),
        }
        summary = build_fy25_format_summary(
            data,
            amount_col='SAP开票含税金额',
            amount_label='SAP开票含税金额',
            invoice_total_amount=210.0,
            inv_minus_order_col='SAP-DMS订单金额',
            extra_categories=extra,
            invoice_stats=(5, 210.0),
            invoice_stats_label='DMS发票清单',
        )

        by_category = summary.set_index('分类')
        by_subcategory = summary.set_index('小分类')
        self.assertEqual(by_category.loc['小计', '记录数'], 3)
        self.assertEqual(by_category.loc['5. not test', '记录数'], 6)
        self.assertEqual(by_category.loc['总计', '记录数'], 9)
        self.assertEqual(by_category.loc['总计', 'SAP开票含税金额'], 210.0)
        self.assertEqual(by_subcategory.loc['NT-28 仅订单', '记录数'], 2)
        self.assertEqual(by_subcategory.loc['NT-32 订单及开票，无发运单', '记录数'], 1)
        self.assertEqual(by_subcategory.loc['2.1 尾差<1', '记录数'], 1)
        self.assertEqual(by_subcategory.loc['4.2 未完全开票', '记录数'], 1)
        self.assertEqual(data.columns.tolist(), original_columns)


if __name__ == '__main__':
    unittest.main()

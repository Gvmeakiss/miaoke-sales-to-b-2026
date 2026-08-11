# -*- coding: utf-8 -*-
"""AQPP 24组、严格容差边界及币种/单位准入的小样本测试。"""

import unittest

import pandas as pd

from aqpp_scenarios import assign_aqpp_scenarios, classify_quantity, classify_value
from config import AMOUNT_TOLERANCE, QUANTITY_TOLERANCE
from reconciliation_measures import build_three_way_measures
from scenario_utils import assign_parallel_scenarios


class AqppScenarioTests(unittest.TestCase):
    def test_all_24_scenarios(self):
        values = {'V1': (100, 100), 'V2': (101, 100), 'V3': (99, 100)}
        quantities = {
            'Q1': (10, 10, 10), 'Q2': (11, 10, 10), 'Q3': (9, 10, 10),
            'Q4': (10, 11, 10), 'Q5': (10, 9, 10), 'Q6': (10, 10, 11),
            'Q7': (10, 10, 9), 'Q8': (9, 10, 11),
        }
        rows, expected = [], []
        for value_index, (value_code, (siv, sov)) in enumerate(values.items(), 1):
            for quantity_index, (_, (siq, soq, gdnq)) in enumerate(quantities.items(), 1):
                rows.append({
                    'SIV': siv, 'SOV': sov, 'SIQ': siq, 'SOQ': soq, 'GDNQ': gdnq,
                    '存在销售订单': True, '存在发运单': True, '存在销售发票': True,
                    '币种校验状态': '一致', '数量单位校验状态': '一致',
                })
                expected.append(f'AQPP-{(value_index - 1) * 8 + quantity_index:02d}')
        result = assign_aqpp_scenarios(
            pd.DataFrame(rows), AMOUNT_TOLERANCE, QUANTITY_TOLERANCE
        )
        self.assertEqual(result['AQPP场景编码'].tolist(), expected)

    def test_exact_tolerance_boundary_is_not_test(self):
        value_plus = classify_value(
            pd.Series([10.02, 9.98]), pd.Series([10.0, 10.0]), AMOUNT_TOLERANCE
        )
        quantity_plus = classify_quantity(
            pd.Series([10.02]), pd.Series([10.0]), pd.Series([10.0]), QUANTITY_TOLERANCE
        )
        self.assertTrue(value_plus.isna().all())
        self.assertTrue(quantity_plus.isna().all())

        row = pd.DataFrame([{
            'SIV': 10.02, 'SOV': 10.0, 'SIQ': 1, 'SOQ': 1, 'GDNQ': 1,
            '存在销售订单': True, '存在发运单': True, '存在销售发票': True,
            '币种校验状态': '一致', '数量单位校验状态': '一致',
        }])
        result = assign_aqpp_scenarios(row, AMOUNT_TOLERANCE, QUANTITY_TOLERANCE)
        self.assertEqual(result.iloc[0]['AQPP场景编码'], 'NT-00')

    def test_dms_exact_amount_boundary_is_complete_and_marked(self):
        source = pd.DataFrame({
            'SAP开票含税金额': [10.02, 9.98, 10.01],
            'DMS订单金额': [10.0, 10.0, 10.0],
            'SAP开票基本数量': [1, 1, 1],
            'DMS订单数量': [1, 1, 1],
            'DMS发货数量': [1, 1, 1],
            'SAP-DMS订单金额': [0.02, -0.02, 0.01],
            '2.Not test': [False, False, False],
            '标准-发票币种': ['CNY', 'CNY', 'CNY'],
            '标准-发票数量单位': ['EA', 'EA', 'EA'],
        })
        result = assign_parallel_scenarios(source, 'DMS')
        self.assertEqual(result['AQPP场景编码'].tolist(), ['AQPP-01'] * 3)
        self.assertEqual(result['AQPP分类'].tolist(), ['完全匹配'] * 3)
        self.assertEqual(result['尾差0.02'].tolist(), ['是', '是', '否'])
        self.assertEqual(result['去年场景编码'].tolist(), ['8', '9', '10'])
        self.assertEqual(result['场景标号'].tolist(), [8, 9, 10])
        self.assertEqual(result['大类'].tolist(), [
            '2.数量一致金额有差异', '2.数量一致金额有差异', '1.完全匹配'
        ])
        self.assertEqual(result['细分场景'].tolist(), [
            '2.1 尾差<1', '2.1 尾差<1', '1.完全匹配'
        ])

    def test_oms_exact_amount_boundary_remains_not_test(self):
        source = pd.DataFrame({
            '开票金额': [10.02], '订单金额': [10.0],
            '开票数量': [1], '订单数量': [1], '发货数量': [1],
            '订单-发票金额': [-0.02], '订单-开票数量': [0], '订单-发货数量': [0],
            '2.Not test': [False], '标准-发票币种': ['CNY'],
            '标准-发票数量单位': ['EA'],
        })
        result = assign_parallel_scenarios(source, 'OMS')
        self.assertEqual(result.iloc[0]['AQPP场景编码'], 'NT-00')
        self.assertNotIn('尾差0.02', result.columns)

    def test_oms_finance_confirmed_currency_assumption_is_explicit(self):
        source = pd.DataFrame({
            '开票金额': [100, 100], '订单金额': [100, 100],
            '开票数量': [1, 1], '订单数量': [1, 1], '发货数量': [1, 1],
            '标准-发票币种': ['CNY', 'USD'], '标准-发票数量单位': ['EA', 'EA'],
        })
        measured = build_three_way_measures(source, 'OMS')
        result = assign_aqpp_scenarios(measured, AMOUNT_TOLERANCE, QUANTITY_TOLERANCE)
        self.assertEqual(measured.iloc[0]['币种校验状态'], '假定一致-订单发运未提供币种，按CNY')
        self.assertEqual(
            measured.iloc[1]['币种校验状态'],
            '财务确认一致-订单发运未提供币种，按发票币种',
        )
        self.assertTrue(result.iloc[0]['AQPP可分类'])
        self.assertTrue(result.iloc[1]['AQPP可分类'])
        self.assertEqual(result.iloc[1]['AQPP场景编码'], 'AQPP-01')

    def test_dms_non_base_currency_without_order_currency_remains_blocked(self):
        source = pd.DataFrame({
            'SAP开票含税金额': [100], 'DMS订单金额': [100],
            'SAP开票基本数量': [1], 'DMS订单数量': [1], 'DMS发货数量': [1],
            '标准-发票币种': ['USD'], '标准-发票数量单位': ['EA'],
        })
        measured = build_three_way_measures(source, 'DMS')
        result = assign_aqpp_scenarios(measured, AMOUNT_TOLERANCE, QUANTITY_TOLERANCE)
        self.assertEqual(measured.iloc[0]['币种校验状态'], '待确认-非本位币缺少订单发运币种')
        self.assertFalse(result.iloc[0]['AQPP可分类'])
        self.assertEqual(result.iloc[0]['AQPP场景编码'], 'NT-00')

    def test_explicit_currency_or_unit_conflict_is_blocked(self):
        source = pd.DataFrame({
            '开票金额': [100, 100], '订单金额': [100, 100],
            '开票数量': [1, 1], '订单数量': [1, 1], '发货数量': [1, 1],
            '标准-发票币种': ['CNY', 'CNY'], '订单币种': ['USD', 'CNY'],
            '发货币种': ['CNY', 'CNY'],
            '标准-发票数量单位': ['EA', 'EA'], '订单数量单位': ['EA', 'KG'],
            '发货数量单位': ['EA', 'EA'],
        })
        measured = build_three_way_measures(source, 'OMS')
        result = assign_aqpp_scenarios(measured, AMOUNT_TOLERANCE, QUANTITY_TOLERANCE)
        self.assertEqual(measured.iloc[0]['币种校验状态'], '不一致')
        self.assertEqual(measured.iloc[1]['数量单位校验状态'], '不一致')
        self.assertFalse(result['AQPP可分类'].any())


if __name__ == '__main__':
    unittest.main()

# -*- coding: utf-8 -*-
"""不执行普通AQPP的发票按实际三单存在关系进入现有Not Test编码。"""

import unittest

import pandas as pd

from scenario_utils import assign_existing_not_test_scenarios
from invoice_type_policy import (
    select_policy_excluded_for_not_test,
    select_tob_oms_reporting_scope,
)


class ExistingNotTestInclusionTests(unittest.TestCase):
    def test_oms_reporting_scope_keeps_aqpp_types_and_tob_policy_types_only(self):
        inventory = pd.DataFrame({
            '发票类型代码规范': ['ZA04', 'ZA05', 'ZA06', 'ZB02', 'ZA02', 'ZB05', 'ZB06', 'ZQ09'],
        })
        selected = select_tob_oms_reporting_scope(inventory)
        self.assertEqual(
            selected['发票类型代码规范'].tolist(),
            ['ZA04', 'ZA05', 'ZA06', 'ZB02'],
        )

    def test_cancellation_preprocessing_rows_are_not_added_to_not_test(self):
        review = pd.DataFrame({
            '发票类型': ['ZB02', 'ZQ07', 'ZB05'],
            '冲销处理编码': [pd.NA, 'CA-01', pd.NA],
        })
        selected = select_policy_excluded_for_not_test(review)
        self.assertEqual(selected['发票类型'].tolist(), ['ZB02', 'ZB05'])

    def test_oms_presence_combinations_use_existing_nt_codes(self):
        source = pd.DataFrame({
            '开票金额': [100.0, 100.0, 100.0, 100.0],
            '开票数量': [1.0, 1.0, 1.0, 1.0],
            '订单金额': [pd.NA, 100.0, pd.NA, 100.0],
            '订单数量': [pd.NA, 1.0, pd.NA, 1.0],
            '发货数量': [pd.NA, pd.NA, 1.0, 1.0],
            '发票-SAP发票号': ['I1', 'I2', 'I3', 'I4'],
        })
        result = assign_existing_not_test_scenarios(source, 'OMS')
        self.assertEqual(
            result['AQPP场景编码'].tolist(),
            ['NT-30', 'NT-32', 'NT-33', 'NT-00'],
        )
        self.assertFalse(result['AQPP可分类'].any())
        self.assertEqual(set(result['AQPP分类']), {'Not Test'})

    def test_dms_all_documents_still_forced_to_nt00(self):
        source = pd.DataFrame({
            'SAP开票含税金额': [-100.0],
            'SAP开票基本数量': [-1.0],
            'DMS订单金额': [100.0],
            'DMS订单数量': [1.0],
            'DMS发货数量': [1.0],
            '发票-SAP发票号': ['R1'],
        })
        result = assign_existing_not_test_scenarios(source, 'DMS')
        self.assertEqual(result.iloc[0]['AQPP场景编码'], 'NT-00')
        self.assertFalse(result.iloc[0]['AQPP可分类'])


if __name__ == '__main__':
    unittest.main()

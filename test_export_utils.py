# -*- coding: utf-8 -*-
"""汇总范围、发票类型及PBC桥接的小样本测试。"""

import unittest

import pandas as pd

from export_utils import (
    add_company_code,
    build_full_not_test_detail,
    build_overall_summary,
    build_invoice_inventory_summary,
    build_invoice_scope_bridge,
    build_summary_scope,
)


class ExportUtilsTests(unittest.TestCase):
    def test_company_code_coalesces_sources_row_by_row(self):
        source = pd.DataFrame({
            '公司代码': ['1100', pd.NA, '公司代码缺失'],
            '销售组织': [pd.NA, 1160, 1190],
        })
        result = add_company_code(source)
        self.assertEqual(result['公司代码'].tolist(), ['1100', '1160', '1190'])

    def test_full_not_test_detail_matches_summary_components(self):
        base = pd.DataFrame({
            'AQPP分类': ['完全匹配', 'Not Test'],
            'AQPP可分类': [True, False],
            '开票金额': [100.0, 20.0],
        })
        extras = {
            '仅订单': pd.DataFrame({'订单号': ['O1']}),
            '仅发货单': pd.DataFrame({'发运号': ['D1']}),
            '仅订单及发货单': pd.DataFrame({'订单号': ['O2']}),
            '仅发票': pd.DataFrame({'开票金额': [-5.0]}),
        }
        result = build_full_not_test_detail(base, extras)
        self.assertEqual(len(result), 5)
        self.assertEqual(set(result['AQPP场景编码'].dropna()), {'NT-28', 'NT-29', 'NT-30', 'NT-31'})
        self.assertAlmostEqual(pd.to_numeric(result['开票金额'], errors='coerce').sum(), 15.0)

    def test_overall_summary_separates_channel_share_from_aqpp_scope_share(self):
        source = pd.DataFrame({
            'AQPP分类': ['完全匹配', 'Not Test'],
            '开票金额': [90.0, 50.0],
        })
        summary = build_overall_summary(
            source,
            '开票金额',
            invoice_total_amount=140.0,
            aqpp_total_amount=100.0,
        ).set_index('场景分类')
        self.assertEqual(summary.loc['完全匹配', '发票金额占比'], '64.3%')
        self.assertEqual(summary.loc['完全匹配', 'AQPP范围金额占比'], '90.0%')
        self.assertEqual(summary.loc['Not Test', 'AQPP范围金额占比'], '')

    def _inventory(self):
        return pd.DataFrame({
            'SAP发票号': ['I1', 'I2', 'I3'],
            '发票类型代码规范': ['ZA01', 'ZA01', 'ZB02'],
            '发票类型描述规范': ['标准发票', '标准发票', '退货发票'],
            '发票类型可参与匹配': [True, False, False],
            '含税金额': [100.0, -100.0, -20.0],
            '无税金额': [90.0, -90.0, -18.0],
            '开票数量（基本单位数量）': [1, -1, -1],
        })

    def test_invoice_type_is_one_row_even_when_cancellation_splits_policy(self):
        summary = build_invoice_inventory_summary(self._inventory(), 'SAP开票含税金额')
        za01 = summary.loc[summary['发票类型代码'].eq('ZA01')]
        self.assertEqual(len(za01), 1)
        self.assertEqual(za01.iloc[0]['是否参与匹配'], '部分（含冲销前置剔除）')

    def test_bridge_separates_valid_input_and_missing_key(self):
        inventory = self._inventory()
        valid = inventory.iloc[[0]]
        invalid = inventory.iloc[0:0]
        bridge = build_invoice_scope_bridge(
            inventory, 'SAP开票含税金额', valid, invalid
        ).set_index('桥接项目')
        self.assertEqual(bridge.loc['3. 匹配键完整的正式聚合输入', '清单行数'], 1)
        self.assertEqual(bridge.loc['5. 政策或冲销前置排除', '清单行数'], 2)
        self.assertEqual(bridge.loc['6. 校验差额（1-3-4-5）', '清单行数'], 0)
        self.assertEqual(bridge.loc['6. 校验差额（1-3-4-5）', '发票金额'], 0.0)

    def test_bridge_can_separate_policy_and_cancellation_exclusions(self):
        inventory = self._inventory()
        inventory['冲销处理编码'] = [pd.NA, 'CA-01', pd.NA]
        bridge = build_invoice_scope_bridge(
            inventory,
            'SAP开票含税金额',
            inventory.iloc[[0]],
            inventory.iloc[0:0],
            separate_exclusions=True,
        ).set_index('桥接项目')
        self.assertEqual(bridge.loc['5. 政策排除（未执行普通AQPP）', '清单行数'], 1)
        self.assertEqual(bridge.loc['6. 冲销前置处理', '清单行数'], 1)
        self.assertEqual(bridge.loc['7. 校验差额（1-3-4-5-6）', '发票金额'], 0.0)

    def test_summary_scope_adds_full_standard_nt(self):
        base = pd.DataFrame({
            'AQPP场景编码': ['AQPP-01'], 'AQPP场景描述': ['匹配'],
            'AQPP分类': ['完全匹配'], 'AQPP可分类': [True],
            '开票金额': [100.0],
        })
        extras = {
            '仅订单': pd.DataFrame({'订单号': ['O1', 'O2']}),
            '仅发货单': pd.DataFrame({'发运号': ['D1']}),
            '仅订单及发货单': pd.DataFrame({'订单号': ['O3']}),
            '仅发票': pd.DataFrame({'含税金额': [20.0]}),
        }
        scope = build_summary_scope(base, extras, '开票金额')
        self.assertEqual(len(scope), 6)
        self.assertEqual(set(scope['AQPP场景编码']), {'AQPP-01', 'NT-28', 'NT-29', 'NT-30', 'NT-31'})
        self.assertEqual(scope.loc[scope['AQPP场景编码'].eq('NT-30'), '开票金额'].sum(), 20.0)


if __name__ == '__main__':
    unittest.main()

# -*- coding: utf-8 -*-
"""冲销预处理小样本测试；不读取或执行全量三单数据。"""

import unittest

import pandas as pd

from cancellation_preprocessing import preprocess_cancellations, split_registered_cancellation_rows


def _invoice_row(
    invoice_no,
    invoice_type,
    amount,
    quantity,
    *,
    reference=None,
    order='D001',
    material='M001',
):
    return {
        'SAP发票号': invoice_no,
        'SAP冲销发票号': reference,
        '发票类型': invoice_type,
        '发票类型代码规范': invoice_type,
        '发票类型描述规范': invoice_type,
        '发票类型处理方式': '正常参与匹配' if invoice_type == 'ZA01' else '仅保留冲销配对明细',
        '发票类型业务分类': invoice_type,
        '发票类型可参与匹配': invoice_type == 'ZA01',
        '特殊发票标记': invoice_type != 'ZA01',
        'DMS销售单号': order,
        '物料编码': material,
        '含税金额': amount,
        '开票数量（基本单位数量）': quantity,
        '标准-发票币种': 'CNY',
    }


class CancellationPreprocessingTests(unittest.TestCase):
    def _run(self, rows):
        source = pd.DataFrame(rows)
        result = preprocess_cancellations(
            source,
            channel='DMS',
            order_col='DMS销售单号',
            material_col='物料编码',
            amount_columns=('含税金额',),
            quantity_columns=('开票数量（基本单位数量）',),
        )
        return source, result

    def test_full_cancellation_excludes_both_sides(self):
        source, result = self._run([
            _invoice_row('I001', 'ZA01', 100, 10),
            _invoice_row('C001', 'ZQ01', -100, -10, reference='I001'),
            _invoice_row('I002', 'ZA01', 50, 5, order='D002'),
        ])
        self.assertEqual(len(result.matchable_invoices), 1)
        self.assertEqual(result.matchable_invoices.iloc[0]['SAP发票号'], 'I002')
        self.assertEqual(set(result.cancellation_details['冲销处理编码']), {'CA-01'})
        self.assertEqual(len(result.cancellation_registry), 1)
        self.assertNotIn('冲销处理编码', source.columns, '入口不得修改原DataFrame')

    def test_partial_cancellation_uses_residual_net_when_keys_match(self):
        _, result = self._run([
            _invoice_row('I001', 'ZA01', 100, 10),
            _invoice_row('C001', 'ZQ01', -30, -3, reference='I001'),
        ])
        self.assertEqual(len(result.matchable_invoices), 2)
        self.assertEqual(set(result.matchable_invoices['冲销处理编码']), {'CA-03'})
        self.assertAlmostEqual(result.matchable_invoices['含税金额'].sum(), 70.0)
        self.assertAlmostEqual(result.matchable_invoices['开票数量（基本单位数量）'].sum(), 7.0)

    def test_missing_original_stays_outside_aqpp(self):
        _, result = self._run([
            _invoice_row('C001', 'ZQ01', -100, -10, reference='OLD001'),
        ])
        self.assertTrue(result.matchable_invoices.empty)
        self.assertEqual(result.cancellation_details.iloc[0]['冲销处理编码'], 'CA-02')

    def test_partial_cancellation_with_different_key_needs_review(self):
        _, result = self._run([
            _invoice_row('I001', 'ZA01', 100, 10, order='D001'),
            _invoice_row('C001', 'ZQ01', -30, -3, reference='I001', order='D999'),
        ])
        self.assertTrue(result.matchable_invoices.empty)
        self.assertEqual(set(result.cancellation_details['冲销处理编码']), {'CA-04'})

    def test_missing_comparison_value_cannot_be_treated_as_zero(self):
        _, result = self._run([
            _invoice_row('I001', 'ZA01', 100, 10),
            _invoice_row('C001', 'ZQ01', None, -10, reference='I001'),
        ])
        self.assertTrue(result.matchable_invoices.empty)
        self.assertEqual(set(result.cancellation_details['冲销处理编码']), {'CA-04'})

    def test_partial_cancellation_requires_every_line_to_have_complete_key(self):
        original_complete = _invoice_row('I001', 'ZA01', 100, 10)
        original_missing_key = _invoice_row('I001', 'ZA01', 50, 5)
        original_missing_key['物料编码'] = None
        _, result = self._run([
            original_complete,
            original_missing_key,
            _invoice_row('C001', 'ZQ01', -30, -3, reference='I001'),
        ])
        self.assertTrue(result.matchable_invoices.empty)
        self.assertEqual(set(result.cancellation_details['冲销处理编码']), {'CA-04'})

    def test_registry_merge_handles_existing_empty_cancellation_columns(self):
        outer = pd.DataFrame({
            'order-item': ['A-M1', 'B-M2'],
            '冲销处理编码': [pd.NA, pd.NA],
            '冲销处理状态': [pd.NA, pd.NA],
        })
        registry = pd.DataFrame({
            'order-item': ['A-M1'],
            '冲销处理编码': ['CA-01'],
            '冲销处理状态': ['同期全额冲销-净额为零'],
            '冲销配对编号': ['OMS-CA-000001'],
        })
        remaining, cancellation = split_registered_cancellation_rows(
            outer, registry, ['order-item']
        )
        self.assertEqual(remaining['order-item'].tolist(), ['B-M2'])
        self.assertEqual(cancellation.iloc[0]['冲销处理编码'], 'CA-01')
        self.assertFalse(any(column.endswith(('_x', '_y')) for column in cancellation.columns))


if __name__ == '__main__':
    unittest.main()

# -*- coding: utf-8 -*-
"""OMS 发票类型匹配能力诊断的小样本测试，不读取生产数据。"""

import unittest

import pandas as pd

from invoice_matchability import build_oms_invoice_type_matchability


class InvoiceMatchabilityTests(unittest.TestCase):
    def test_distinguishes_data_failure_from_policy_exclusion(self):
        invoices = pd.DataFrame({
            '发票类型代码规范': ['ZA01', 'ZA01', 'ZQ01', 'ZA06'],
            '发票类型描述规范': ['标准发票', '标准发票', '取消标准发票', '行政发票'],
            '发票类型处理方式': ['正常参与匹配', '正常参与匹配', '仅保留冲销配对明细', '仅保留特殊业务明细'],
            '发票类型可参与匹配': [True, True, False, False],
            'SAP发票号': ['1', '2', '3', '4'],
            'OMS销售单号': ['O1', 'O2', 'O1', pd.NA],
            '物料编码': ['M1', 'M2', 'M1', 'M3'],
            '实际金额（ZFN1）': [100, 200, -100, 50],
        })
        original_columns = invoices.columns.tolist()
        summary = build_oms_invoice_type_matchability(
            invoices,
            order_keys=['O1||M1'],
            delivery_keys=['O1||M1'],
            invoice_order_col='OMS销售单号',
            invoice_material_col='物料编码',
        ).set_index('发票类型代码')

        self.assertEqual(summary.loc['ZA01', 'OMS数据匹配能力'], '部分可匹配')
        self.assertEqual(summary.loc['ZA01', '三单齐全键数'], 1)
        self.assertIn('政策不直接进入AQPP', summary.loc['ZQ01', '当前AQPP处理结论'])
        self.assertEqual(summary.loc['ZA06', 'OMS数据匹配能力'], '无法匹配-OMS匹配键全部缺失')
        self.assertEqual(invoices.columns.tolist(), original_columns)


if __name__ == '__main__':
    unittest.main()

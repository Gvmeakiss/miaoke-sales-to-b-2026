# -*- coding: utf-8 -*-
"""集中实现金额及数量容差判断。

业务规则采用严格不等式 ``abs(a-b) < tolerance``。本模块额外使用极小的
浮点保护带，避免十进制边界在二进制浮点中被表示为略小于阈值。所有函数
均返回新Series或布尔值，不修改输入。
"""

from __future__ import annotations

import pandas as pd

from config import FLOAT_BOUNDARY_EPSILON


def _effective_inner_limit(tolerance: float, epsilon: float) -> float:
    """返回严格相等区间的有效上限。"""
    return max(float(tolerance) - float(epsilon), 0.0)


def equal_with_tolerance(a, b, tolerance: float, epsilon: float = FLOAT_BOUNDARY_EPSILON):
    """逐项判断 ``abs(a-b) < tolerance``；缺失值返回False。"""
    left = pd.to_numeric(a, errors='coerce')
    right = pd.to_numeric(b, errors='coerce')
    valid = left.notna() & right.notna()
    return valid & left.sub(right).abs().lt(_effective_inner_limit(tolerance, epsilon))


def greater_with_tolerance(a, b, tolerance: float, epsilon: float = FLOAT_BOUNDARY_EPSILON):
    """逐项判断a是否严格大于b且超过容差；边界保护带内返回False。"""
    left = pd.to_numeric(a, errors='coerce')
    right = pd.to_numeric(b, errors='coerce')
    valid = left.notna() & right.notna()
    return valid & left.sub(right).gt(float(tolerance) + float(epsilon))


def absolute_less_than(values, tolerance: float, epsilon: float = FLOAT_BOUNDARY_EPSILON):
    """逐项判断绝对值是否严格小于容差；缺失值返回False。"""
    numeric = pd.to_numeric(values, errors='coerce')
    return numeric.notna() & numeric.abs().lt(_effective_inner_limit(tolerance, epsilon))


def absolute_greater_than(values, tolerance: float, epsilon: float = FLOAT_BOUNDARY_EPSILON):
    """逐项判断绝对值是否严格大于容差；边界保护带内返回False。"""
    numeric = pd.to_numeric(values, errors='coerce')
    return numeric.notna() & numeric.abs().gt(float(tolerance) + float(epsilon))


def scalar_is_zero(value, tolerance: float, epsilon: float = FLOAT_BOUNDARY_EPSILON) -> bool:
    """标量净额是否严格落在零值容差内；缺失值返回False。"""
    numeric = pd.to_numeric(pd.Series([value]), errors='coerce').iloc[0]
    if pd.isna(numeric):
        return False
    return abs(float(numeric)) < _effective_inner_limit(tolerance, epsilon)

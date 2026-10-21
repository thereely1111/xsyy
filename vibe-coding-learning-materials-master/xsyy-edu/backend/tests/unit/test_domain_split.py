# -*- coding: utf-8 -*-
"""域拆分路由单测（2026-09-03）：数与式/方程与不等式/函数 三套独立提示词.

验证：
- 数与式 → domain_numbers
- 方程与不等式 → domain_equation
- 函数（单题）→ domain_function  ← 关键：此前单函数题错误落到合并 calculation 层
- 图形与几何 → domain_geometry（保持不动）
- 统计与概率 → domain_statistics（已优化）
- 未知/空域 → calculation 兜底（路由到 numbers）
"""
from __future__ import annotations

from prompt_router import build_animation_system_prompt
from tag_agent.content_profile import build_content_profile

DOMAIN_HEADER = {
    "numbers": "【知识域表达：数与式",
    "equation": "【知识域表达：方程与不等式",
    "function": "【知识域表达：函数类",
    "geometry": "【知识域表达：几何类",
    "statistics": "【知识域表达：统计概率类",
}


def _sys(question: str, primary: dict) -> str:
    p = build_content_profile(question, primary, meta={"engine": "agent", "confidence": 0.95})
    sys_p = build_animation_system_prompt(p.to_dict())
    assert sys_p is not None, "提示词拼装不应为 None"
    return sys_p


def test_numbers_routes_to_domain_numbers() -> None:
    sys_p = _sys(
        "计算 3/4 + 1/2",
        {"version": "数与式", "grade": "三上", "main_tag": "分数加法", "sub_tags": []},
    )
    assert DOMAIN_HEADER["numbers"] in sys_p
    assert DOMAIN_HEADER["equation"] not in sys_p


def test_equation_routes_to_domain_equation() -> None:
    sys_p = _sys(
        "解方程 2x + 3 = 11",
        {"version": "方程与不等式", "grade": "七上", "main_tag": "一元一次方程", "sub_tags": []},
    )
    assert DOMAIN_HEADER["equation"] in sys_p
    assert DOMAIN_HEADER["numbers"] not in sys_p


def test_function_single_question_routes_to_domain_function() -> None:
    """关键回归：单道函数题现在必须走专属 function 层，而非合并 calculation。"""
    sys_p = _sys(
        "已知一次函数 y = 2x + 1，画出它的图象",
        {"version": "函数", "grade": "八上", "main_tag": "一次函数", "sub_tags": []},
    )
    assert DOMAIN_HEADER["function"] in sys_p
    # 不应出现其他计算子域层标题
    assert DOMAIN_HEADER["numbers"] not in sys_p
    assert DOMAIN_HEADER["equation"] not in sys_p


def test_geometry_untouched() -> None:
    sys_p = _sys(
        "证明三角形全等",
        {"version": "图形与几何", "grade": "八上", "main_tag": "全等三角形", "sub_tags": []},
    )
    assert DOMAIN_HEADER["geometry"] in sys_p


def test_statistics_routes_and_optimized() -> None:
    sys_p = _sys(
        "统计 40 人身高并画条形图",
        {"version": "统计与概率", "grade": "七下", "main_tag": "统计", "sub_tags": ["统计图表"]},
    )
    assert DOMAIN_HEADER["statistics"] in sys_p
    # 优化要点应存在
    assert "数据忠于题干" in sys_p
    assert "样本空间" in sys_p


def test_unknown_domain_falls_back_to_numbers() -> None:
    p = build_content_profile("一段无法识别域的话", {"version": "数与代数", "grade": "七上"})
    assert p.display_class == "calculation"  # 兜底
    sys_p = build_animation_system_prompt(p.to_dict())
    assert sys_p is not None
    assert DOMAIN_HEADER["numbers"] in sys_p  # calculation 兜底路由到 numbers 文件

# -*- coding: utf-8 -*-
"""P1 分层提示词路由器 PromptRouter 单测（离线）.

运行：
    hermes-venv-python -m pytest tests/unit/test_prompt_router.py \
        --confcutdir=tests/unit -q
"""
from __future__ import annotations

import pytest

from prompt_router import (
    build_animation_system_prompt,
    build_solution_rules_prompt,
    build_teaching_plan_rules_prompt,
)
from tag_agent.content_profile import build_content_profile


def _profile(question, primary, **kw):
    p = build_content_profile(question, primary, meta={"engine": "agent", "confidence": 0.95}, **kw)
    return p.to_dict()


def test_no_profile_returns_none() -> None:
    assert build_animation_system_prompt(None) is None
    assert build_animation_system_prompt({}) is None


def test_junior_calculation_assembly() -> None:
    prof = _profile(
        "甲乙相向而行…相遇问题",
        {"version": "方程与不等式", "grade": "七上", "main_tag": "一元一次方程", "sub_tags": ["行程问题"]},
    )
    sys_p = build_animation_system_prompt(prof)
    assert sys_p is not None
    assert "象数演易" in sys_p                       # 00_base 纪律层
    assert "【学段风格：初中" in sys_p                  # stage_junior
    assert "【知识域表达：方程与不等式" in sys_p        # domain_equation（拆分后）
    assert "行程问题" in sys_p                          # 画像题型注入
    assert "本题教学画像" in sys_p


def test_primary_calculation_assembly() -> None:
    prof = _profile(
        "小明有 5 个苹果，小红给 3 个，一共几个？",
        {"version": "数与式", "grade": "一上", "main_tag": "加法", "sub_tags": ["加法应用"]},
    )
    sys_p = build_animation_system_prompt(prof)
    assert sys_p is not None
    assert "【学段风格：小学" in sys_p
    assert "圆角矩形" in sys_p or "拟物" in sys_p or "故事" in sys_p


def test_junior_geometry_assembly() -> None:
    prof = _profile(
        "证明三角形 ABC ≌ DEF",
        {"version": "图形与几何", "grade": "八上", "main_tag": "全等三角形", "sub_tags": ["全等证明"]},
    )
    sys_p = build_animation_system_prompt(prof)
    assert sys_p is not None
    assert "【学段风格：初中" in sys_p
    assert "【知识域表达：几何类" in sys_p
    assert "垂直" in sys_p or "辅助线" in sys_p


def test_statistics_assembly() -> None:
    prof = _profile(
        "统计 40 人身高分布并画条形图",
        {"version": "统计与概率", "grade": "七下", "main_tag": "统计", "sub_tags": ["统计图表"]},
    )
    sys_p = build_animation_system_prompt(prof)
    assert "【知识域表达：统计概率类" in sys_p
    assert "数据忠于题干" in sys_p


def test_solution_and_plan_rules_exist() -> None:
    sol = build_solution_rules_prompt()
    plan = build_teaching_plan_rules_prompt()
    assert "01_solution" in sol or "完整解答纪律层" in sol
    assert "02_teaching_plan" in plan or "教学节拍表纪律层" in plan

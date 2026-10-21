# -*- coding: utf-8 -*-
"""P0 教学画像 ContentProfile 单测（离线，不依赖 DB/LLM）.

运行（--confcutdir 使上层 conftest.py 不被加载，避免连接测试库）：
    hermes-venv-python -m pytest tests/unit/test_content_profile.py \
        --confcutdir=tests/unit -q
"""
from __future__ import annotations

import pytest

from tag_agent.content_profile import (
    STAGE_JUNIOR,
    STAGE_PRIMARY,
    ContentProfile,
    build_content_profile,
    domain_to_display_class,
    grade_to_stage,
    guess_question_type,
    pattern_keys_for_profile,
)

# ── grade_to_stage ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "grade,expected",
    [
        ("一上", STAGE_PRIMARY),
        ("一下", STAGE_PRIMARY),
        ("二上", STAGE_PRIMARY),
        ("三下", STAGE_PRIMARY),
        ("五下", STAGE_PRIMARY),
        ("六上", STAGE_JUNIOR),
        ("六下", STAGE_JUNIOR),
        ("七上", STAGE_JUNIOR),
        ("九下", STAGE_JUNIOR),
        ("七年级上", STAGE_JUNIOR),  # 别名
        ("六年级下", STAGE_JUNIOR),  # 别名
        ("", STAGE_JUNIOR),          # 空 → 初中兜底
        ("初中", STAGE_JUNIOR),      # 无法解析 → 初中兜底
    ],
)
def test_grade_to_stage(grade: str, expected: str) -> None:
    assert grade_to_stage(grade) == expected


# ── domain_to_display_class ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "domain,expected",
    [
        ("数与式", "numbers"),
        ("方程与不等式", "equation"),
        ("函数", "function"),
        ("图形与几何", "geometry"),
        ("统计与概率", "statistics"),
        ("未知域", "calculation"),  # 未知 → calculation 兜底（路由到 numbers）
        ("", "calculation"),
    ],
)
def test_domain_to_display_class(domain: str, expected: str) -> None:
    assert domain_to_display_class(domain) == expected


# ── guess_question_type ───────────────────────────────────────────────────────


def test_guess_question_type_by_tag() -> None:
    # 标签名命中优先
    assert guess_question_type("鸡兔同笼问题", "行程问题") == "鸡兔同笼问题"


def test_guess_question_type_by_question() -> None:
    assert guess_question_type("甲乙相向而行，几小时后相遇？") == "行程问题"
    # 题干含"三角形"但不含泛化"角"字（避免命中"角的度量"先行规则）
    assert guess_question_type("等腰三角形两边相等，求底边范围") == "三角形"


def test_guess_question_type_miss() -> None:
    assert guess_question_type("随便一段话", "") == ""


# ── build_content_profile ─────────────────────────────────────────────────────


def test_build_legacy_primary_shape() -> None:
    """legacy inject_knowledge_tags_full 的 primary 结构（version/grade/main_tag/sub_tags）."""
    p = build_content_profile(
        "鸡兔同笼，35 头 94 足，鸡兔各几只？",
        {
            "version": "方程与不等式",
            "grade": "六下",
            "main_tag": "鸡兔同笼",
            "sub_tags": ["鸡兔同笼问题"],
        },
        meta={"engine": "legacy", "confidence": 0.9},
    )
    assert p.stage == STAGE_JUNIOR
    assert p.display_class == "equation"
    assert p.domain == "方程与不等式"
    assert p.grade == "六下"
    assert p.tags["main_tag"] == "鸡兔同笼"
    assert p.tags["sub_tags"] == ["鸡兔同笼问题"]
    assert p.question_type == "鸡兔同笼问题"
    assert p.engine == "legacy"
    assert p.confidence == 0.9
    assert p.method_lock is None  # 动画/解答分离已取消（2026-09-03），恒占位不填充
    assert p.figure_info == {"has_figure": False, "figures": []}


def test_build_agent_outcome_shape() -> None:
    """agent outcome.knowledge_tags 结构（domain/grade/main_tag/sub_tags）."""
    p = build_content_profile(
        "甲 60 千米/时先出发，乙 80 千米/时追及，多久追上？",
        {
            "domain": "方程与不等式",
            "grade": "七上",
            "main_tag": "一元一次方程",
            "sub_tags": ["行程问题"],
        },
        meta={"engine": "agent", "action": "inject_official", "confidence": 0.97},
    )
    assert p.engine == "agent"
    assert p.domain == "方程与不等式"
    assert p.grade == "七上"
    assert p.tags["main_tag"] == "一元一次方程"
    assert p.tags["sub_tags"] == ["行程问题"]
    assert p.question_type == "行程问题"
    assert p.style_key == "junior_equation"


def test_build_primary_none() -> None:
    """未识别到标签（识别失败/低置信）→ 空画像但不抛错."""
    p = build_content_profile("随便一句话", None, meta={"engine": "legacy"})
    assert p.domain == ""
    assert p.grade == ""
    assert p.tags["main_tag"] == ""
    assert p.is_math_problem is True


def test_build_stage_primary_school() -> None:
    """小学题（识别放行后）→ primary_school + 幼龄化表现要求."""
    p = build_content_profile(
        "小明有 5 个苹果，小红有 3 个，一共有几个？",
        {"version": "数与式", "grade": "一上", "main_tag": "20以内加法", "sub_tags": ["加法应用"]},
        meta={"engine": "legacy", "confidence": 0.95},
    )
    assert p.stage == STAGE_PRIMARY
    assert p.visual_requirements["style_key"] == "primary_numbers"
    assert p.visual_requirements["motion_policy"] == "playful"


def test_build_geometry_display_class() -> None:
    p = build_content_profile(
        "证明三角形 ABC ≌ 三角形 DEF",
        {"version": "图形与几何", "grade": "八上", "main_tag": "全等三角形", "sub_tags": ["全等证明"]},
        meta={"engine": "agent", "confidence": 0.93},
    )
    assert p.display_class == "geometry"
    assert p.style_key == "junior_geometry"
    assert "几何标注规范" in p.visual_requirements.get("must_show", [])


# ── to_dict / from_dict 往返 ──────────────────────────────────────────────────


def test_dict_roundtrip() -> None:
    p = build_content_profile(
        "统计某班 40 人身高分布，画条形图",
        {"version": "统计与概率", "grade": "七下", "main_tag": "统计", "sub_tags": ["统计图表"]},
        second={"version": "数与式", "grade": "七下", "main_tag": "有理数", "sub_tags": ["运算"]},
        meta={"engine": "dual", "confidence": 0.88},
    )
    d = p.to_dict()
    p2 = ContentProfile.from_dict(d)
    assert p2.to_dict() == d


def test_from_dict_empty() -> None:
    p = ContentProfile.from_dict(None)
    assert isinstance(p, ContentProfile)
    assert p.domain == ""


# ── 题型细分（scene_pattern 命中，2026-09-05 新增）───────────────────────────

def test_guess_channel_subtypes() -> None:
    assert guess_question_type("一列火车长200米，以每秒20米的速度通过一座长1000米的隧道，求时间") == "火车过隧道"
    assert guess_question_type("一列火车长150米，完全通过一座长850米的桥需要多长时间") == "火车过桥"
    assert guess_question_type("一辆汽车要驶过一座大桥，桥长450米") == "汽车过桥"
    assert guess_question_type("一艘轮船要穿过桥洞，净空高5米船高3米") == "船过桥洞"
    # 无通道语义不误伤（保持原粗分）
    assert guess_question_type("甲乙相向而行，几小时后相遇") == "行程问题"


def test_pattern_keys_for_profile_mapping() -> None:
    assert pattern_keys_for_profile({"question_type": "火车过隧道"}) == ["tunnel_pass"]
    assert pattern_keys_for_profile({"question_type": "火车过桥", "parts": [{"question_type": "图形面积"}]}) == ["tunnel_pass"]
    assert pattern_keys_for_profile({"question_type": "行程问题"}) == []
    # 复合题：多小题各自命中 → 去重
    assert pattern_keys_for_profile({
        "question_type": "",
        "parts": [{"question_type": "火车过隧道"}, {"question_type": "船过桥洞"}],
    }) == ["tunnel_pass"]

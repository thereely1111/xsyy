# -*- coding: utf-8 -*-
"""复合多小题适配单测（2026-09-03 扩展；离线，不依赖 DB/LLM）.

运行：
    hermes-venv-python -m pytest tests/unit/test_composite.py \
        --confcutdir=tests/unit -q
"""
from __future__ import annotations

from tag_agent.content_profile import (
    DISPLAY_FUNCTION,
    DISPLAY_GEOMETRY,
    build_content_profile,
    detect_composite_parts,
)
from prompt_router import build_animation_system_prompt


# 一道自洽的"反比例函数×一次函数交点"复合三问（B 取 (-4,-2) 使两交点共双曲线）
COMPOSITE_Q = (
    "反比例函数 y=k/x（k≠0）的图象与一次函数 y=mx+n 的图象交于 A(2,4) 和 B(-4,-2) 两点。\n"
    "（1）求反比例函数和一次函数的解析式；\n"
    "（2）连接 OA、OB，求三角形 AOB 的面积；\n"
    "（3）根据图象，直接写出不等式 k/x > mx+n 的解集"
)


def test_detect_composite_parts_splits_three():
    parts = detect_composite_parts(COMPOSITE_Q)
    assert len(parts) == 3
    labels = [p["label"] for p in parts]
    assert labels == ["（1）", "（2）", "（3）"]


def test_detect_composite_parts_domains_mixed():
    parts = detect_composite_parts(COMPOSITE_Q)
    # 第1问函数、第2问几何、第3问函数 → 去重后展示大类应为 [function, geometry]
    assert parts[0]["domain"] == "函数"
    assert parts[0]["display_class"] == DISPLAY_FUNCTION
    assert parts[1]["domain"] == "图形与几何"
    assert parts[1]["display_class"] == DISPLAY_GEOMETRY
    assert parts[2]["domain"] == "函数"
    dcs = []
    for p in parts:
        if p["display_class"] not in dcs:
            dcs.append(p["display_class"])
    assert dcs == [DISPLAY_FUNCTION, DISPLAY_GEOMETRY]


def test_single_question_not_composite():
    q = "小明有12颗糖，给了小红3颗，又买了5颗，现在小明有几颗？"
    assert detect_composite_parts(q) == []
    prof = build_content_profile(q, {"version": "数与式", "grade": "一下", "main_tag": "加减法", "sub_tags": []})
    assert prof.is_composite is False
    assert prof.parts == []
    assert prof.domains == []


def test_build_content_profile_composite_roundtrip():
    primary = {"version": "函数", "grade": "八上", "main_tag": "一次函数", "sub_tags": ["反比例函数"]}
    prof = build_content_profile(COMPOSITE_Q, primary)
    assert prof.is_composite is True
    assert len(prof.parts) == 3
    assert prof.domains == [DISPLAY_FUNCTION, DISPLAY_GEOMETRY]
    assert prof.question_type == "反比例函数与一次函数交点"

    d = prof.to_dict()
    assert d["is_composite"] is True
    assert len(d["parts"]) == 3
    assert d["domains"] == [DISPLAY_FUNCTION, DISPLAY_GEOMETRY]
    # 序列化往返
    from tag_agent.content_profile import ContentProfile
    prof2 = ContentProfile.from_dict(d)
    assert prof2.is_composite is True
    assert prof2.domains == prof.domains
    assert len(prof2.parts) == 3


def test_prompt_router_multi_domain_injection():
    primary = {"version": "函数", "grade": "八上", "main_tag": "一次函数", "sub_tags": ["反比例函数"]}
    prof = build_content_profile(COMPOSITE_Q, primary)
    sys_prompt = build_animation_system_prompt(prof.to_dict())
    assert sys_prompt  # 非 None（分层库可用）
    # 函数域层与几何域层都应被注入
    assert "坐标系绘制纪律" in sys_prompt          # domain_function
    assert "图形必须数学精确" in sys_prompt         # domain_geometry
    # 复合通用案例 + 具体函数交点案例都应注入
    assert "复合多小题通用结构" in sys_prompt
    assert "反比例函数与一次函数交点" in sys_prompt


def test_render_parts_block_via_pipeline():
    # 复用 pipeline._render_parts_block（小题清单渲染）
    import importlib
    pipeline = importlib.import_module("pipeline")
    primary = {"version": "函数", "grade": "八上", "main_tag": "一次函数", "sub_tags": ["反比例函数"]}
    prof = build_content_profile(COMPOSITE_Q, primary)
    block = pipeline._render_parts_block(prof.parts)
    assert "【复合多小题】" in block
    assert "（1）" in block and "（2）" in block and "（3）" in block
    # 非复合返回空（占位应被清空）
    assert pipeline._render_parts_block([]) == ""


if __name__ == "__main__":
    import sys
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))

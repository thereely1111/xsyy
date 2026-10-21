# -*- coding: utf-8 -*-
"""P1 SVG 纪律 Lint 单测（离线，不依赖 DB/LLM）.

运行：
    hermes-venv-python -m pytest tests/unit/test_scene_lint.py \
        --confcutdir=tests/unit -q
"""
from __future__ import annotations

import pytest

from scene_lint import (
    LintIssue,
    LintResult,
    lint_scene_svg,
    lint_mode,
)

GOOD_SVG = """
<defs><style>
.svg-elem { fill: #1f2937; }
@keyframes grow { from{opacity:0} to{opacity:1} }
</style></defs>
<g id="persistent-layer">
  <rect x="340" y="240" width="200" height="80" class="svg-elem" x-show="sceneStep >= 1"/>
  <text x="360" y="280" class="svg-elem" x-show="sceneStep >= 1">甲车速度 60</text>
  <circle cx="400" cy="300" r="10" class="svg-elem" x-show="sceneStep >= 2"/>
  <path d="M0,0" class="svg-elem" x-show="sceneStep >= 2"/>
</g>
<g id="temporary-layer-step-1">
  <path d="M100,100 L300,300" class="dashed-line temp-1" x-show="sceneStep === 1"/>
</g>
<g id="temporary-layer-step-2">
  <path d="M200,200 L400,200" class="trace hl-1" x-show="sceneStep === 3"/>
</g>
"""

STEPS_OK = [{"bubblePos": {"x": 24, "y": 24}, "arrowTarget": {"x": 400, "y": 300}}]


def test_good_svg_passes() -> None:
    r = lint_scene_svg(GOOD_SVG, STEPS_OK, stage="junior_high")
    assert r.passed is True, [i.message for i in r.issues]
    assert r.hard_issues == []


def test_temporary_layer_range_rejected() -> None:
    bad = GOOD_SVG.replace('class="dashed-line temp-1" x-show="sceneStep === 1"',
                            'class="dashed-line temp-1" x-show="sceneStep >= 1"')
    r = lint_scene_svg(bad, STEPS_OK, stage="junior_high")
    assert r.passed is False
    rules = {i.rule for i in r.hard_issues}
    assert "temporary_layer_only_exact_step" in rules


def test_persistent_min_range() -> None:
    # 全部临时化：无 sceneStep >= N → 拒绝
    bad = """
    <g id="temporary-layer-step-1">
      <rect class="dashed-line" x-show="sceneStep === 1"/>
    </g>
    """
    r = lint_scene_svg(bad, [], stage="junior_high")
    assert r.passed is False
    assert "persistent_min_range" in {i.rule for i in r.hard_issues}


def test_motion_limit_junior() -> None:
    # 初中：3 处 infinite 循环 → 拒绝
    bad = GOOD_SVG + """
    <style>
      @keyframes a1 {0%{opacity:0}100%{opacity:1}}
      .x1{animation: a1 3s infinite}
      .x2{animation: a1 3s infinite}
      .x3{animation: a1 3s infinite}
    </style>
    """
    r = lint_scene_svg(bad, STEPS_OK, stage="junior_high")
    assert r.passed is False
    assert "motion_animation_limit" in {i.rule for i in r.hard_issues}


def test_motion_limit_primary_relaxed() -> None:
    # 小学：2 处循环 → 放行（幼龄化允许 ≤2）
    ok = GOOD_SVG + """
    <style>
      @keyframes a1 {0%{opacity:0}100%{opacity:1}}
      .x1{animation: a1 3s infinite}
      .x2{animation: a1 3s infinite}
    </style>
    """
    r = lint_scene_svg(ok, STEPS_OK, stage="primary_school")
    assert "motion_animation_limit" not in {i.rule for i in r.hard_issues}


def test_full_canvas_background_rejected() -> None:
    bad = GOOD_SVG + '<rect x="0" y="0" width="800" height="600" fill="#fdfbf7"/>'
    r = lint_scene_svg(bad, STEPS_OK, stage="junior_high")
    assert r.passed is False
    assert "no_full_canvas_background" in {i.rule for i in r.hard_issues}


@pytest.mark.parametrize(
    "fragment",
    ["$x^2$", "\\frac{1}{2}", "\\sqrt{9}", "$a+b$"],
)
def test_latex_rejected(fragment: str) -> None:
    bad = GOOD_SVG.replace(">甲车速度 60<", f">{fragment}<")
    r = lint_scene_svg(bad, STEPS_OK, stage="junior_high")
    assert r.passed is False
    assert "no_latex_in_svg" in {i.rule for i in r.hard_issues}


def test_coordinate_out_of_bounds_warns() -> None:
    steps_bad = [{"bubblePos": {"x": 24, "y": 24}, "arrowTarget": {"x": 9999, "y": 300}}]
    r = lint_scene_svg(GOOD_SVG, steps_bad, stage="junior_high")
    # 越界是告警级，不阻断
    assert r.passed is True
    assert "coordinate_in_bounds" in {i.rule for i in r.warnings}


def test_empty_scene_passes_no_crash() -> None:
    r = lint_scene_svg("", [], stage="junior_high")
    assert r.passed is False  # 空场景无持久层 → 拒绝
    assert "persistent_min_range" in {i.rule for i in r.hard_issues}


def test_lint_result_to_dict() -> None:
    res = LintResult(passed=False, issues=[
        LintIssue(rule="no_latex_in_svg", message="bad", level="hard"),
        LintIssue(rule="x_show_min_count", message="warn", level="warning"),
    ])
    d = res.to_dict()
    assert d["passed"] is False
    assert d["hard"][0]["rule"] == "no_latex_in_svg"
    assert d["warnings"][0]["rule"] == "x_show_min_count"


def test_lint_mode_env(monkeypatch) -> None:
    monkeypatch.setenv("SCENE_LINT_MODE", "off")
    assert lint_mode() == "off"
    monkeypatch.setenv("SCENE_LINT_MODE", "warn")
    assert lint_mode() == "warn"
    monkeypatch.setenv("SCENE_LINT_MODE", "strict")
    assert lint_mode() == "strict"
    monkeypatch.setenv("SCENE_LINT_MODE", "bogus")
    assert lint_mode() == "strict"  # 非法值回退 strict


# ── 几何重叠检测（防元素叠压，2026-09-03 增强）─────────────────────────────


def test_text_text_overlap_rejected() -> None:
    """两段独立文字深交叠（文字压字）→ hard 拒收。"""
    bad = GOOD_SVG + """
    <g id="overlap-tests">
      <text x="100" y="100" font-size="20" x-show="sceneStep >= 1">甲车速度 60</text>
      <text x="102" y="115" font-size="20" x-show="sceneStep >= 1">乙车速度 40</text>
    </g>
    """
    r = lint_scene_svg(bad, STEPS_OK, stage="junior_high")
    assert "text_text_overlap" in {i.rule for i in r.hard_issues}


def test_text_text_no_overlap_when_spaced() -> None:
    """行距充足（≥1.3 字号）的两段文字 → 不误报。"""
    ok = GOOD_SVG + """
    <g id="spaced-tests">
      <text x="100" y="100" font-size="18" x-show="sceneStep >= 1">第一行</text>
      <text x="100" y="150" font-size="18" x-show="sceneStep >= 1">第二行（距 50px）</text>
    </g>
    """
    r = lint_scene_svg(ok, STEPS_OK, stage="junior_high")
    assert "text_text_overlap" not in {i.rule for i in r.issues}


def test_text_on_shape_warns_not_blocks() -> None:
    """文字半压图形边界（未完全落入图形内）→ warning 不阻断。"""
    bad = GOOD_SVG + """
    <g id="shape-tests">
      <rect x="100" y="300" width="200" height="100" x-show="sceneStep === 3"/>
      <text x="270" y="360" font-size="16" x-show="sceneStep === 3">半压边界文本</text>
    </g>
    """
    r = lint_scene_svg(bad, STEPS_OK, stage="junior_high")
    assert r.passed is True  # warning 不阻断
    assert "text_on_shape_warn" in {i.rule for i in r.warnings}


def test_label_inside_figure_allowed() -> None:
    """完整落入图形内部的标签/数值 → 合法不告警。"""
    ok = GOOD_SVG + """
    <g id="figure-tests">
      <circle cx="400" cy="150" r="130" x-show="sceneStep >= 1"/>
      <text x="400" y="160" font-size="16" text-anchor="middle" x-show="sceneStep >= 1">圆的面积</text>
    </g>
    """
    r = lint_scene_svg(ok, STEPS_OK, stage="junior_high")
    assert "text_on_shape_warn" not in {i.rule for i in r.issues}


def test_shape_coincident_warns() -> None:
    """两个近乎重合的图形 → warning。"""
    bad = GOOD_SVG + """
    <g id="dup-tests">
      <circle cx="450" cy="120" r="90" x-show="sceneStep === 2"/>
      <circle cx="453" cy="118" r="88" x-show="sceneStep === 2"/>
    </g>
    """
    r = lint_scene_svg(bad, STEPS_OK, stage="junior_high")
    assert "shape_coincident_warn" in {i.rule for i in r.warnings}


def test_legit_geometry_intersection_no_shape_warn() -> None:
    """圆与直线相交（合法几何构图）→ 不触发 shape_coincident。"""
    ok = GOOD_SVG + """
    <g id="geo-tests">
      <circle cx="400" cy="150" r="140" x-show="sceneStep >= 1"/>
      <line x1="200" y1="150" x2="600" y2="150" x-show="sceneStep >= 1"/>
    </g>
    """
    r = lint_scene_svg(ok, STEPS_OK, stage="junior_high")
    assert "shape_coincident_warn" not in {i.rule for i in r.issues}


def test_cross_step_same_position_no_false_positive() -> None:
    """不同步骤（sceneStep === N）元素即使坐标相同也不互检（切步即换）。"""
    ok = GOOD_SVG + """
    <g id="cross-step-tests">
      <rect x="600" y="60" width="150" height="70" x-show="sceneStep === 1"/>
      <text x="610" y="105" font-size="15" x-show="sceneStep === 1">第一步</text>
      <rect x="600" y="60" width="150" height="70" x-show="sceneStep === 2"/>
      <text x="610" y="105" font-size="15" x-show="sceneStep === 2">第二步</text>
    </g>
    """
    r = lint_scene_svg(ok, STEPS_OK, stage="junior_high")
    assert "text_text_overlap" not in {i.rule for i in r.issues}
    assert "shape_coincident_warn" not in {i.rule for i in r.issues}


# ── v2 规则（2026-09-05 新增）────────────────────────────────────────────────

MOTION_SVG = """
<g id="rail" x-show="sceneStep >= 1">
  <rect x="40" y="252" width="720" height="6"/>
  <text x="400" y="300" x-show="sceneStep >= 1">隧道</text>
</g>
<g id="train" x-show="sceneStep >= 1">
  <rect x="60" y="210" width="112" height="40"/>
</g>
"""

MOTION_STEPS = [
    {"motions": {"train": "translate(0,0)"}},
    {"motions": {"train": "translate(280,0)"}},
    {"motions": {"train": "translate(560,0)"}},
]


def test_v2_default_warn_when_v2_mode_warn(monkeypatch) -> None:
    # v2 灰度默认 warn：引用不存在 id 只记 warning，不拒收
    monkeypatch.delenv("SCENE_LINT_V2_MODE", raising=False)
    steps = [{"motions": {"ghost": "translate(100,0)"}}, {"motions": {"ghost": "translate(200,0)"}}]
    r = lint_scene_svg(MOTION_SVG, steps, stage="junior_high")
    assert r.passed is True
    rules = {i.rule for i in r.warnings}
    assert "motion_ref_exists" in rules


def test_v2_motion_ref_hard_when_strict(monkeypatch) -> None:
    monkeypatch.setenv("SCENE_LINT_V2_MODE", "strict")
    steps = [{"motions": {"ghost": "translate(100,0)"}}, {"motions": {"ghost": "translate(200,0)"}}]
    r = lint_scene_svg(MOTION_SVG, steps, stage="junior_high")
    assert r.passed is False
    assert "motion_ref_exists" in {i.rule for i in r.hard_issues}


def test_v2_no_self_transform(monkeypatch) -> None:
    monkeypatch.setenv("SCENE_LINT_V2_MODE", "strict")
    svg = '<g id="train" transform="translate(10,10)" x-show="sceneStep >= 1"><rect x="60" y="210" width="40" height="40"/></g>'
    steps = [{"motions": {"train": "translate(0,0)"}}, {"motions": {"train": "translate(200,0)"}}]
    r = lint_scene_svg(svg, steps, stage="junior_high")
    assert "motion_no_self_transform" in {i.rule for i in r.hard_issues}


def test_v2_never_moved(monkeypatch) -> None:
    monkeypatch.setenv("SCENE_LINT_V2_MODE", "strict")
    steps = [
        {"motions": {"train": "translate(0,0)"}},
        {"motions": {"train": "translate(0,0)"}},
        {"motions": {"train": "translate(0,0)"}},
    ]
    r = lint_scene_svg(MOTION_SVG, steps, stage="junior_high")
    assert "motion_step_delta_min" in {i.rule for i in r.hard_issues}


def test_v2_occlusion_order_when_front_before_body(monkeypatch) -> None:
    monkeypatch.setenv("SCENE_LINT_V2_MODE", "strict")
    svg = """
    <g id="front-left" x-show="sceneStep >= 1"><rect x="200" y="230" width="40" height="90"/></g>
    <g id="train" x-show="sceneStep >= 1"><rect x="60" y="210" width="112" height="40"/></g>
    """
    steps = [{"motions": {"train": "translate(0,0)"}}, {"motions": {"train": "translate(300,0)"}}]
    r = lint_scene_svg(svg, steps, stage="junior_high")
    assert "occlusion_order" in {i.rule for i in r.hard_issues}


def test_v2_pattern_contract_missing_labels() -> None:
    # 命中 tunnel_pass 但无入口/出口/长度标注 → hard（pattern 命中即专项）
    svg = '<g id="band" x-show="sceneStep >= 1"><rect x="120" y="250" width="560" height="70"/></g>'
    steps = [{"motions": {}}, {"motions": {"train": "translate(100,0)"}}]
    r = lint_scene_svg(svg, steps, stage="junior_high", pattern_key="tunnel_pass")
    assert r.passed is False
    assert "pattern_contract" in {i.rule for i in r.hard_issues}

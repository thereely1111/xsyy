"""解题预检（识题阶段轻量校验）单测。

覆盖：
- _parse_solvability_verdict 健壮解析（模型 JSON 噪声/缺字段/矛盾题/解析失败 fail-safe）
- ENABLE_SOLVABILITY_CHECK 开关关闭时跳过（不触网）
- LLM 调用异常时 fail-open 放行（不触网）

全部离线，不需要模型网关。
"""
import asyncio
import os

import pipeline
from pipeline import LangChainPipeline, _parse_solvability_verdict


def test_parse_clean_solvable():
    out = _parse_solvability_verdict('{"solvable": true, "reason": "", "brief": "解析式 y=2x+1"}')
    assert out["solvable"] is True
    assert out["brief"] == "解析式 y=2x+1"
    assert out["reason"] == ""


def test_parse_wrapped_in_noise_and_markdown():
    # 模型常把 JSON 包进 ```json 代码块并附解释，必须仍能解析
    raw = '好的，下面是判定：\n```json\n{"solvable": false, "reason": "两交点不共同一曲线", "brief": ""}\n```\n请核对。'
    out = _parse_solvability_verdict(raw)
    assert out["solvable"] is False
    assert "不共同一曲线" in out["reason"]


def test_parse_string_false_and_missing_reason():
    out = _parse_solvability_verdict('{"solvable": "false"}')
    assert out["solvable"] is False
    # 缺少 reason 时补默认说明，避免空原因
    assert out["reason"]


def test_parse_garbage_fail_safe():
    # 解析失败一律放行，不误杀正常题
    assert _parse_solvability_verdict("我觉得这道题没问题")["solvable"] is True
    assert _parse_solvability_verdict("")["solvable"] is True
    assert _parse_solvability_verdict('{"solvable":')["solvable"] is True


def test_switch_off_skips_llm(monkeypatch):
    monkeypatch.setenv("ENABLE_SOLVABILITY_CHECK", "off")
    p = LangChainPipeline()
    # 开关关闭时直接返回 solvable=True，不调用 LLM（离线安全）
    out = asyncio.run(p._check_problem_solvable("任意题目", ""))
    assert out["solvable"] is True


def test_llm_exception_fail_open(monkeypatch):
    monkeypatch.setenv("ENABLE_SOLVABILITY_CHECK", "true")
    monkeypatch.setattr(
        LangChainPipeline, "_get_llm_analyzer",
        lambda self: (_ for _ in ()).throw(RuntimeError("gateway down")),
    )
    p = LangChainPipeline()
    # LLM 调用异常 → fail-open 放行，不把基础设施故障当题目错误
    out = asyncio.run(p._check_problem_solvable("任意题目", ""))
    assert out["solvable"] is True


class _FakeResp:
    def __init__(self, text):
        self.content = text


class _FakeAnalyzer:
    def __init__(self, text):
        self._text = text

    async def ainvoke(self, messages):
        return _FakeResp(self._text)


def test_model_says_unsolvable_text(monkeypatch):
    monkeypatch.setenv("ENABLE_SOLVABILITY_CHECK", "true")
    verdict_json = '{"solvable": false, "reason": "A(2,4)与B(-1,-2)代入 y=k/x 分别得 k=8 与 k=2，两交点不共同一反比例函数，条件矛盾", "brief": ""}'
    monkeypatch.setattr(
        LangChainPipeline, "_get_llm_analyzer",
        lambda self: _FakeAnalyzer(verdict_json),
    )
    p = LangChainPipeline()
    # 模型判定不可解 → 方法如实返回 unsolvable + 中文原因（文字题分支）
    out = asyncio.run(p._check_problem_solvable("反比例函数...交于 A(2,4) 和 B(-1,-2)...", ""))
    assert out["solvable"] is False
    assert "不共同一反比例函数" in out["reason"]


def test_model_says_solvable_image(monkeypatch, tmp_path):
    monkeypatch.setenv("ENABLE_SOLVABILITY_CHECK", "true")
    verdict_json = '{"solvable": true, "reason": "", "brief": "解析式 y=2x，面积=6"}'
    monkeypatch.setattr(
        LangChainPipeline, "_get_llm_analyzer",
        lambda self: _FakeAnalyzer(verdict_json),
    )
    # 造一个伪图片文件走图片分支（compress 会读它，fake analyzer 不真正看像素）
    img = tmp_path / "q.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n fake")
    p = LangChainPipeline()
    out = asyncio.run(p._check_problem_solvable("看图解题", str(img)))
    assert out["solvable"] is True
    assert out["brief"] == "解析式 y=2x，面积=6"

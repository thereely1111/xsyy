"""缓存集成验证测试。

验证目标：
1. 第二次相同请求是否命中缓存（来源应为 cache）。
2. 第二次调用耗时是否显著短于第一次调用。
"""

from __future__ import annotations

import time
from uuid import uuid4

try:
    from .main_service import AnimationGenerationService
except ImportError:  # pragma: no cover
    from main_service import AnimationGenerationService


def test_cache_source_and_latency(monkeypatch) -> None:
    service = AnimationGenerationService()

    # 使用唯一题目，避免被历史缓存污染。
    problem = f"缓存验证题目-{uuid4()}：已知直角三角形两直角边为 6 和 8，求斜边长度。"
    difficulty = "中等"
    extra_context = {"expected_keywords": ["cache_integration_check"]}

    original_call_backend = service._call_backend

    # 人为增加模型调用耗时，确保“首次慢、二次快”的差异可观测。
    def slow_call_backend(prompt: str, backend: str = "mock", extra_context: dict | None = None):
        time.sleep(0.25)
        return original_call_backend(prompt, backend=backend, extra_context=extra_context)

    monkeypatch.setattr(service, "_call_backend", slow_call_backend)

    start_first = time.perf_counter()
    first_result = service.generate_animation_teaching(
        problem=problem,
        difficulty=difficulty,
        backend="mock",
        extra_context=extra_context,
    )
    first_elapsed = time.perf_counter() - start_first

    start_second = time.perf_counter()
    second_result = service.generate_animation_teaching(
        problem=problem,
        difficulty=difficulty,
        backend="mock",
        extra_context=extra_context,
    )
    second_elapsed = time.perf_counter() - start_second

    speedup = first_elapsed / max(second_elapsed, 1e-9)

    # 这些输出可通过 pytest -s 直接观察。
    print(f"首次调用来源: {first_result.get('backend')}，from_cache={first_result.get('from_cache')}")
    print(f"二次调用来源: {second_result.get('backend')}，from_cache={second_result.get('from_cache')}")
    print(f"首次耗时: {first_elapsed:.4f}s，二次耗时: {second_elapsed:.4f}s，提速比: {speedup:.2f}x")

    assert first_result.get("from_cache") is False, "首次调用不应命中缓存。"
    assert first_result.get("backend") == "mock-backend", (
        f"首次调用来源异常: {first_result.get('backend')}"
    )

    assert second_result.get("from_cache") is True, "二次调用应命中缓存。"
    assert second_result.get("backend") == "cache", (
        f"二次调用来源应为 cache，实际为: {second_result.get('backend')}"
    )

    second_output = str(second_result.get("teaching_content", ""))
    assert "cache_integration_check" in second_output, "缓存返回内容缺少预期关键词。"

    assert second_elapsed < first_elapsed * 0.5, (
        "二次调用耗时未显著下降。"
        f" 首次: {first_elapsed:.4f}s, 二次: {second_elapsed:.4f}s, 提速比: {speedup:.2f}x"
    )

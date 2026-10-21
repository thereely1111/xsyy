"""基于 Pytest 的回归测试脚本（10 题黄金数据集）。

任务对应：
- 任务二：通过黄金数据集 + 多层断言 + 输出哈希对比保障质量。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

try:
    from .config import settings
    from .main_service import animation_generation_test_api
except ImportError:  # pragma: no cover
    from config import settings
    from main_service import animation_generation_test_api

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None


GOLDEN_DATASET = [
    {
        "id": "q1_model_awareness",
        "category": "model_awareness",
        "problem": "已知 y=2x+1，请指出线性模型中的斜率和截距，并说明斜率变化会带来什么影响。",
        "difficulty": "简单",
        "keywords": ["linear", "slope", "intercept"],
    },
    {
        "id": "q2_data_awareness",
        "category": "data_awareness",
        "problem": "某地一周 7 天气温如下表，请计算平均值并描述变化趋势。",
        "difficulty": "简单",
        "keywords": ["mean", "trend", "data"],
    },
    {
        "id": "q3_spatial_concept",
        "category": "spatial_concept",
        "problem": "一个正方体棱长为 3，请说明如何计算它的表面积和体积。",
        "difficulty": "中等",
        "keywords": ["cube", "surface area", "volume"],
    },
    {
        "id": "q4_geometric_intuition",
        "category": "geometric_intuition",
        "problem": "直角三角形两条直角边分别为 3 和 4，求斜边，并说明边上正方形面积关系。",
        "difficulty": "中等",
        "keywords": ["a^2+b^2=c^2", "square", "area"],
    },
    {
        "id": "q5_symbol_awareness",
        "category": "symbol_awareness",
        "problem": "解方程 2(x-3)=10，并解释括号与等号在式子中的含义。",
        "difficulty": "简单",
        "keywords": ["symbol", "equation", "equality"],
    },
    {
        "id": "q6_quantity_sense",
        "category": "quantity_sense",
        "problem": "一个水箱以每分钟 5 升的速度注水 12 分钟，请先估算再精确计算总水量。",
        "difficulty": "简单",
        "keywords": ["estimate", "quantity", "liters"],
    },
    {
        "id": "q7_number_sense",
        "category": "number_sense",
        "problem": "比较 0.375、3/8 和 37.5%，判断它们是否相等并说明理由。",
        "difficulty": "中等",
        "keywords": ["fraction", "decimal", "percent"],
    },
    {
        "id": "q8_reasoning_awareness",
        "category": "reasoning_awareness",
        "problem": "已知所有正方形都是长方形，且 A 是正方形，请推理证明 A 是长方形。",
        "difficulty": "中等",
        "keywords": ["if", "then", "inference"],
    },
    {
        "id": "q9_operation_ability",
        "category": "operation_ability",
        "problem": "计算 (18/3) + (4*5) - 7，并说明运算顺序。",
        "difficulty": "简单",
        "keywords": ["operation", "order", "result"],
    },
    {
        "id": "q10_geometry_instruction",
        "category": "geometry_instruction",
        "problem": "几何动画指令：先画点 A、B、C，再连线 AB、BC、AC，最后标注角 ABC。",
        "difficulty": "困难",
        "keywords": ["draw points", "connect", "angle"],
    },
]


def _compute_md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _invoke_test_api(case: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "problem": case["problem"],
        "difficulty": case["difficulty"],
        "backend": settings.regression.backend,
        "extra_context": {"expected_keywords": case["keywords"]},
    }

    if settings.regression.api_mode == "http":
        if requests is None:
            raise RuntimeError("未安装 requests，请先执行: pip install requests")

        response = requests.post(settings.regression.test_api_url, json=payload, timeout=30)
        body = response.json()
        body.setdefault("status_code", response.status_code)
        return body

    return animation_generation_test_api(payload)


def _assert_optional_json_structure(output: str) -> None:
    trimmed = output.strip()
    if not (trimmed.startswith("{") and trimmed.endswith("}")):
        return

    parsed = json.loads(trimmed)
    assert isinstance(parsed, dict)
    assert "keywords" in parsed


def _load_hash_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=True), encoding="utf-8")


@pytest.mark.parametrize("case", GOLDEN_DATASET, ids=[item["id"] for item in GOLDEN_DATASET])
def test_animation_generation_regression(case: dict[str, Any]) -> None:
    response = _invoke_test_api(case)

    # 多层断言
    assert int(response.get("status_code", 500)) == 200
    assert bool(response.get("success")) is True

    output = str(response.get("output", "")).strip()
    assert output, f"输出为空: {case['id']}"

    lowered = output.lower()
    for kw in case["keywords"]:
        assert kw.lower() in lowered, f"关键词 '{kw}' 未命中: {case['id']}"

    _assert_optional_json_structure(output)


def test_save_and_compare_output_hashes() -> None:
    artifacts_dir = Path(settings.regression.output_dir)
    latest_hashes_path = artifacts_dir / "latest_hashes.json"
    baseline_hashes_path = artifacts_dir / "baseline_hashes.json"

    latest_hashes: dict[str, str] = {}
    for case in GOLDEN_DATASET:
        response = _invoke_test_api(case)
        output = str(response.get("output", ""))
        latest_hashes[case["id"]] = _compute_md5(output)

    _save_json(latest_hashes_path, latest_hashes)

    baseline_hashes = _load_hash_file(baseline_hashes_path)
    if not baseline_hashes:
        # 首次运行：人工审核后建立基线。
        pytest.skip(
            f"未找到基线文件: {baseline_hashes_path}。"
            "请先人工审核 latest_hashes.json，再复制为 baseline_hashes.json。"
        )

    changed = {
        k: {"baseline": baseline_hashes.get(k), "latest": latest_hashes.get(k)}
        for k in latest_hashes
        if baseline_hashes.get(k) != latest_hashes.get(k)
    }

    if changed:
        diff_path = artifacts_dir / "hash_diff.json"
        _save_json(diff_path, changed)

    assert not changed, "回归输出哈希发生变化，请查看 artifacts/hash_diff.json 做人工复核。"

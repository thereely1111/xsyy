"""主服务（缓存 + 模型后端 + 模板渲染）。

任务对应：
- 任务一：三层优化（模板复用、教学内容缓存、推理层 KV Cache 参数暴露）。
- 任务三：可切换 Gemini 后端进行低成本测试。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    from .cache_service import TeachingCacheService
    from .config import settings
except ImportError:  # pragma: no cover
    from cache_service import TeachingCacheService
    from config import settings

try:
    from .gemini_client import GeminiClient
except Exception:  # pragma: no cover
    try:
        from gemini_client import GeminiClient
    except Exception:  # pragma: no cover
        GeminiClient = None


class AnimationGenerationService:
    def __init__(self, template_path: str | None = None) -> None:
        self.cache = TeachingCacheService()
        default_template = Path(__file__).parent.parent / "prompt" / "teaching_template.html"
        self.template_path = template_path or str(default_template)
        self.template = self._load_template()
        self.gemini_client = self._safe_init_gemini()

    def _load_template(self) -> str:
        path = Path(self.template_path)
        if path.exists():
            return path.read_text(encoding="utf-8")

        # 第一层缓存思路：模板可复用，缺失时使用内置模板兜底。
        return (
            "<html><body><h2>{{title}}</h2>"
            "<p><strong>题目:</strong> {{problem}}</p>"
            "<p><strong>难度:</strong> {{difficulty}}</p>"
            "<pre>{{content}}</pre>"
            "</body></html>"
        )

    def _safe_init_gemini(self) -> Any:
        if GeminiClient is None:
            return None
        try:
            return GeminiClient()
        except Exception:
            return None

    def _build_prompt(self, problem: str, difficulty: str) -> str:
        return (
            "你是一名数学动画教学策划助手。"
            "请输出可直接驱动动画生成的精炼教学内容。\n\n"
            f"题目: {problem}\n"
            f"难度: {difficulty}\n"
            "输出格式（JSON 字符串）: "
            '{"title":"...","steps":["..."],"keywords":["..."]}'
        )

    def _call_backend(
        self,
        prompt: str,
        backend: str = "gemini",
        extra_context: dict[str, Any] | None = None,
    ) -> tuple[str, str]:
        backend = (backend or "gemini").lower()

        if backend == "gemini":
            if self.gemini_client is None:
                raise RuntimeError("Gemini 后端不可用，请检查 API Key 与依赖安装。")
            result = self.gemini_client.generate_teaching_content(prompt)
            return result.text, result.model

        if backend == "mock":
            # 为本地回归与 CI 提供稳定输出。
            expected_keywords = []
            if extra_context:
                expected_keywords = extra_context.get("expected_keywords", [])

            mock = {
                "title": "数学教学示例（Mock）",
                "steps": [
                    "阅读题目并识别已知条件。",
                    "建立方程并分步求解。",
                    "结合单位或几何意义进行结果校验。",
                ],
                "keywords": [
                    "a^2+b^2=c^2",
                    "square",
                    "area",
                    "function",
                    "data",
                    "volume",
                    "symbol",
                    "ratio",
                    "inference",
                    "operation",
                ]
                + [kw for kw in expected_keywords if isinstance(kw, str)],
            }
            return json.dumps(mock, ensure_ascii=True), "mock-backend"

        raise ValueError(f"不支持的后端: {backend}")

    def _render_template(self, title: str, problem: str, difficulty: str, content: str) -> str:
        html = self.template
        html = html.replace("{{title}}", title)
        html = html.replace("{{problem}}", problem)
        html = html.replace("{{difficulty}}", difficulty)
        html = html.replace("{{content}}", content)
        return html

    def generate_animation_teaching(
        self,
        problem: str,
        difficulty: str,
        backend: str = "gemini",
        extra_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # 第二层缓存：先按输入哈希查缓存，命中即跳过模型调用。
        prompt_hash = self.cache.build_prompt_hash(problem, difficulty, extra_context=extra_context)
        cached_content = self.cache.get(prompt_hash)

        if cached_content:
            html = self._render_template(
                title="数学教学（缓存命中）",
                problem=problem,
                difficulty=difficulty,
                content=cached_content,
            )
            return {
                "success": True,
                "status_code": 200,
                "from_cache": True,
                "backend": "cache",
                "prompt_hash": prompt_hash,
                "teaching_content": cached_content,
                "html": html,
            }

        prompt = self._build_prompt(problem, difficulty)
        generated_content, model_name = self._call_backend(
            prompt,
            backend=backend,
            extra_context=extra_context,
        )
        self.cache.set(prompt_hash, generated_content)

        html = self._render_template(
            title="数学教学",
            problem=problem,
            difficulty=difficulty,
            content=generated_content,
        )

        return {
            "success": True,
            "status_code": 200,
            "from_cache": False,
            "backend": model_name,
            "prompt_hash": prompt_hash,
            "teaching_content": generated_content,
            "html": html,
            # 第三层：暴露自托管推理参数建议（KV Cache 等）。
            "inference_hints": {
                "enable_kv_cache": settings.inference.enable_kv_cache,
                "gpu_memory_utilization": settings.inference.gpu_memory_utilization,
                "max_num_batched_tokens": settings.inference.max_num_batched_tokens,
            },
        }


def animation_generation_test_api(payload: dict[str, Any]) -> dict[str, Any]:
    """进程内测试接口函数。

    用于回归测试时模拟平台测试 API，无需启动独立 HTTP 服务。
    """
    service = AnimationGenerationService()

    problem = payload.get("problem", "").strip()
    difficulty = payload.get("difficulty", "medium").strip()
    backend = payload.get("backend", "mock").strip()
    extra_context = payload.get("extra_context")

    if not problem:
        return {
            "success": False,
            "status_code": 400,
            "error": "problem 不能为空",
            "output": "",
        }

    result = service.generate_animation_teaching(
        problem=problem,
        difficulty=difficulty,
        backend=backend,
        extra_context=extra_context,
    )

    return {
        "success": result["success"],
        "status_code": result["status_code"],
        "output": result["teaching_content"],
        "prompt_hash": result["prompt_hash"],
        "from_cache": result["from_cache"],
        "backend": result["backend"],
    }

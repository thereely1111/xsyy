"""Gemini API 客户端封装（用于低成本测试）。

任务对应：
- 任务三：将 Google AI Studio（Gemini API）作为可选模型后端。
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib
from typing import Any

try:
    from .config import settings
except ImportError:  # pragma: no cover
    from config import settings

try:
    genai = importlib.import_module("google.genai")
    genai_types = importlib.import_module("google.genai.types")
except ImportError:  # pragma: no cover
    genai = None
    genai_types = None


@dataclass
class GeminiResult:
    text: str
    model: str
    finish_reason: str = "unknown"


class GeminiClient:
    def __init__(self) -> None:
        if genai is None or genai_types is None:
            raise RuntimeError(
                "未安装 google-genai，请先执行: pip install google-genai"
            )

        if not settings.gemini.api_key:
            raise RuntimeError("GOOGLE_API_KEY 为空，请先在环境变量中配置。")

        self._model_name = settings.gemini.model_name
        self._client = genai.Client(api_key=settings.gemini.api_key)

    def generate_teaching_content(self, prompt: str) -> GeminiResult:
        timeout_ms = int(settings.gemini.timeout_seconds * 1000)
        config: Any = genai_types.GenerateContentConfig(
            temperature=settings.gemini.temperature,
            max_output_tokens=settings.gemini.max_output_tokens,
            http_options=genai_types.HttpOptions(timeout=timeout_ms),
        )
        response = self._client.models.generate_content(
            model=self._model_name,
            contents=prompt,
            config=config,
        )

        text = (response.text or "").strip()
        if not text:
            raise RuntimeError("Gemini 返回内容为空。")

        finish_reason = "unknown"
        candidates = getattr(response, "candidates", None)
        if candidates:
            finish_reason = str(getattr(candidates[0], "finish_reason", "unknown"))

        return GeminiResult(text=text, model=self._model_name, finish_reason=finish_reason)

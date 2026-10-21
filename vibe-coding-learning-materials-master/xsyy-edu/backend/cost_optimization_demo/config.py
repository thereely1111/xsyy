"""集中配置：缓存、模型后端、推理参数、回归测试。"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class CacheConfig:
    redis_url: str = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    key_prefix: str = os.getenv("CACHE_KEY_PREFIX", "teaching_content")
    ttl_seconds: int = int(os.getenv("CACHE_TTL_SECONDS", "86400"))
    connect_timeout_seconds: float = float(os.getenv("REDIS_CONNECT_TIMEOUT_SECONDS", "2.0"))


@dataclass(frozen=True)
class GeminiConfig:
    # API Key 不写入源码，统一通过环境变量注入。
    api_key: str = os.getenv("GOOGLE_API_KEY", "")
    model_name: str = os.getenv("GEMINI_MODEL_NAME", "gemini-1.5-flash")
    temperature: float = float(os.getenv("GEMINI_TEMPERATURE", "0.2"))
    max_output_tokens: int = int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "1024"))
    timeout_seconds: int = int(os.getenv("GEMINI_TIMEOUT_SECONDS", "60"))


@dataclass(frozen=True)
class InferenceConfig:
    # 自托管推理（vLLM/TensorRT-LLM）建议参数，可用于启动脚本。
    gpu_memory_utilization: float = float(os.getenv("GPU_MEMORY_UTILIZATION", "0.85"))
    max_num_batched_tokens: int = int(os.getenv("MAX_NUM_BATCHED_TOKENS", "4096"))
    enable_kv_cache: bool = os.getenv("ENABLE_KV_CACHE", "true").lower() == "true"


@dataclass(frozen=True)
class RegressionConfig:
    api_mode: str = os.getenv("REGRESSION_API_MODE", "local")  # local | http
    backend: str = os.getenv("REGRESSION_BACKEND", "mock")  # mock | gemini
    test_api_url: str = os.getenv(
        "TEST_API_URL", "http://127.0.0.1:8000/api/test/animation-generation"
    )
    output_dir: str = os.getenv("REGRESSION_OUTPUT_DIR", "./artifacts")


@dataclass(frozen=True)
class Settings:
    cache: CacheConfig = CacheConfig()
    gemini: GeminiConfig = GeminiConfig()
    inference: InferenceConfig = InferenceConfig()
    regression: RegressionConfig = RegressionConfig()


settings = Settings()

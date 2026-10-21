# -*- coding: utf-8 -*-
"""AgentScope 模型构建（项目统一模型出口，OpenAI 兼容接口）.

2026-09-18 起：不再单独设置模型，主/备模型统一同步项目配置 kimi_config ——
主模型 KIMI_MODEL（qwen3.8-flash @ kuaipao.pro，与 agent-platform 平台默认模型一致），
备用模型 BACKUP_MODEL_*（gpt-5.5 @ kuaipao.pro）。

适配说明（2026-09-10）：
- 上游网关在波动期会把 Chat Completion 响应以「裸字符串 / dict」形式返回，
  导致 agentscope 原生 OpenAIChatModel 在 _parse_completion_response 中访问
  response.choices 时抛 `AttributeError: 'str' object has no attribute 'choices'`，
  进而整条识别链路掉到 legacy 关键词兜底。
- CompatibleOpenAIChatModel 继承原生 OpenAIChatModel，**call / 解析逻辑完全一致**；
  仅当 response 不是标准 ChatCompletion 对象（是 str / dict / bytes）时做容错反序列化，
  复用原生解析构造 ChatResponse，不丢内容、不崩。
- 稳定期（response 为标准 ChatCompletion 对象）行为与未改造完全一致。
- 网关稳定后，设环境变量 TAG_AGENT_MODEL_COMPAT=0 即可一键切回原生 OpenAIChatModel（零代码改动）。
"""
from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from types import SimpleNamespace

from agentscope.agent import Agent
from agentscope.credential import OpenAICredential
from agentscope.model import OpenAIChatModel
from agentscope.tool import Toolkit
from kimi_config import (
    get_api_key,
    get_active_model,
    get_base_url,
    get_backup_api_key,
    get_backup_base_url,
    get_backup_model,
    is_backup_configured,
)

logger = logging.getLogger(__name__)


class CompatibleOpenAIChatModel(OpenAIChatModel):
    """对上游网关返回非标准格式（字符串 / dict / bytes）做容错的 OpenAIChatModel 子类。

    稳定期（response 为标准 ChatCompletion 对象）行为与原生完全一致；
    波动期（response 为 str / dict / bytes）做反序列化后复用原生解析，避免识别失败掉兜底。
    """

    def _parse_completion_response(self, start_datetime, response, audio_format="wav"):
        if isinstance(response, (str, bytes, dict)):
            logger.warning(
                "[CompatibleOpenAIChatModel] 上游返回非标准格式(%s)，已做容错解析"
                "（gpt 稳定后设 TAG_AGENT_MODEL_COMPAT=0 切回原生）",
                type(response).__name__,
            )
            coerced = self._coerce_response(response)
            return super()._parse_completion_response(start_datetime, coerced, audio_format)
        return super()._parse_completion_response(start_datetime, response, audio_format)

    @staticmethod
    def _coerce_response(raw):
        """把 str / dict / bytes 响应规整成带 .choices / .usage / .id 属性的对象。

        复用原生 _parse_completion_response，从而完全共享其对 reasoning_content /
        tool_calls / audio / usage 的处理逻辑，与稳定期行为零差异。
        """
        data = raw
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        if isinstance(raw, str):
            s = raw.strip()
            try:
                data = json.loads(s)
            except json.JSONDecodeError:
                # 纯文本补全：包成单 choice
                data = {"choices": [{"message": {"content": raw}}]}
        if isinstance(data, dict):
            choices = data.get("choices")
            norm_choices = []
            if isinstance(choices, list):
                for ch in choices:
                    if isinstance(ch, dict):
                        msg = ch.get("message") or {}
                        msg = msg if isinstance(msg, dict) else {"content": str(msg)}
                        norm_choices.append(
                            SimpleNamespace(
                                message=SimpleNamespace(
                                    content=msg.get("content"),
                                    reasoning_content=msg.get("reasoning_content")
                                    or msg.get("reasoning"),
                                    tool_calls=msg.get("tool_calls"),
                                    audio=msg.get("audio"),
                                )
                            )
                        )
                    else:
                        norm_choices.append(
                            SimpleNamespace(
                                message=SimpleNamespace(
                                    content=str(ch),
                                    reasoning_content=None,
                                    tool_calls=None,
                                    audio=None,
                                )
                            )
                        )
            usage = data.get("usage")
            if isinstance(usage, dict):
                details = usage.get("prompt_tokens_details")
                usage = SimpleNamespace(
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                    prompt_tokens_details=details,
                )
            else:
                usage = None
            return SimpleNamespace(choices=norm_choices, usage=usage, id=data.get("id"))
        # 兜底：data 既非 dict 也非 str（理论上不会到这）
        text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=text,
                        reasoning_content=None,
                        tool_calls=None,
                        audio=None,
                    )
                )
            ],
            usage=None,
            id=None,
        )


@lru_cache(maxsize=1)
def build_chat_model() -> OpenAIChatModel:
    """构建 AgentScope OpenAI 兼容聊天模型（进程级缓存）.

    与项目统一模型出口同步：KIMI_MODEL @ KIMI_BASE_URL（kimi_config），
    与 agent-platform 平台默认模型一致，不再单独配置。

    Raises:
        RuntimeError: 缺少 API Key
    """
    api_key = get_api_key()
    if not api_key:
        raise RuntimeError(
            "缺少 KIMI_API_KEY，请在 .env 中配置（项目统一主模型出口）"
        )

    # 兼容适配开关：默认开启（修复波动期 'str' object has no attribute 'choices'）；
    # 网关稳定后设 TAG_AGENT_MODEL_COMPAT=0 切回原生 OpenAIChatModel。
    compat_on = os.getenv("TAG_AGENT_MODEL_COMPAT", "1") not in (
        "0",
        "false",
        "False",
        "",
    )
    model_cls = CompatibleOpenAIChatModel if compat_on else OpenAIChatModel

    credential = OpenAICredential(
        api_key=api_key,
        base_url=get_base_url(),
    )
    model = model_cls(
        credential=credential,
        model=get_active_model(),
        stream=False,
        max_retries=2,
        parameters=OpenAIChatModel.Parameters(temperature=0),
    )
    logger.info(
        "标签识别智能体模型就绪: %s (%s) [compat=%s]",
        get_active_model(),
        get_base_url(),
        compat_on,
    )
    return model


@lru_cache(maxsize=1)
def build_backup_chat_model() -> OpenAIChatModel:
    """构建备用模型 AgentScope 聊天模型（默认模型超时/网络异常时切换，进程级缓存）.

    Raises:
        RuntimeError: 备用模型未配置（BACKUP_MODEL_API_KEY / BASE_URL / NAME）
    """
    if not is_backup_configured():
        raise RuntimeError("备用模型未配置（BACKUP_MODEL_API_KEY / BACKUP_MODEL_BASE_URL / BACKUP_MODEL_NAME）")
    api_key = get_backup_api_key()

    # 同样走容错解析：备用模型也可能处于波动期
    model_cls = CompatibleOpenAIChatModel

    credential = OpenAICredential(
        api_key=api_key,
        base_url=get_backup_base_url(),
    )
    model = model_cls(
        credential=credential,
        model=get_backup_model(),
        stream=False,
        max_retries=1,
        parameters=OpenAIChatModel.Parameters(temperature=0),
    )
    logger.info(
        "标签识别智能体备用模型就绪: %s (%s)",
        get_backup_model(),
        get_backup_base_url(),
    )
    return model


def create_agent(name: str, system_prompt: str, toolkit: Toolkit | None = None) -> Agent:
    """创建 AgentScope 智能体（共用同一模型实例）.

    toolkit 非空时，智能体在 reply 内部具备工具循环能力（可多轮查证后再作答）。
    """
    return Agent(
        name=name,
        system_prompt=system_prompt,
        model=build_chat_model(),
        toolkit=toolkit,
    )

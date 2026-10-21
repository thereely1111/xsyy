# -*- coding: utf-8 -*-
"""智能体基础封装：统一调用、JSON 解析与字段提取."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Optional

from agentscope.agent import Agent
from agentscope.message import UserMsg

from kimi_config import is_backup_configured, is_timeout_error

logger = logging.getLogger(__name__)

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.S)


def _loads_candidate(s: str) -> Optional[dict]:
    """尝试解析单段候选文本：先按原样解析，失败后再做常见脏字符修复."""
    try:
        data = json.loads(s)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    # 修复模型常见的 LaTeX 反斜杠转义问题（如 \frac、\( 等）
    s2 = re.sub(r"(?<!\\)\\([a-zA-Z])", r"\\\\\1", s)
    # 兼容尾逗号 {"a":1,} / [1,2,]
    s2 = re.sub(r",\s*([}\]])", r"\1", s2)
    # 兼容模型用全角引号 / 全角逗号当 JSON 标点的情况（仅在原样解析失败后触发）
    s2 = s2.replace("“", '"').replace("”", '"').replace("‘", '"').replace("’", '"')
    s2 = s2.replace("，", ",")
    try:
        data = json.loads(s2)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    return None


def _extract_json_objects(text: str) -> list[str]:
    """按括号配平从文本中提取所有顶层 JSON 对象片段（贪婪正则失败时的兜底）.

    可正确跳过字符串内部的 { }（含转义），也能把「说明文字 + JSON + 说明文字」
    中的 JSON 逐段切出来，避免贪婪 \\{.*\\} 把中间正文一起吞掉。
    """
    out: list[str] = []
    depth = 0
    start = -1
    in_str = False
    esc = False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start >= 0:
                    out.append(text[start : i + 1])
                    start = -1
    return out


def parse_json(text: str) -> Optional[dict]:
    """从模型输出中稳健解析 JSON 对象.

    依次尝试：```json 代码块 → 贪婪 {.*} → 括号配平逐段提取。
    每段先按原样解析，失败后再做反斜杠/尾逗号/全角引号修复后重试。
    """
    if not text:
        return None
    # 先试 ```json 代码块与贪婪 {.*}（单对象场景的主流路径，保持原行为）
    m = _JSON_BLOCK_RE.search(text)
    if m:
        result = _loads_candidate(m.group(1))
        if result is not None:
            return result
    m = _JSON_OBJECT_RE.search(text)
    if m:
        result = _loads_candidate(m.group(0))
        if result is not None:
            return result
    # 兜底：括号配平逐段提取（处理「说明文字 + 示例对象 + 答案对象」等多对象场景）。
    # 多段都可解析时，取字段最多的一段（并列取靠后的，通常是最终答案而非前文示例）。
    best: Optional[dict] = None
    for cand in _extract_json_objects(text):
        result = _loads_candidate(cand)
        if result is not None and (best is None or len(result) >= len(best)):
            best = result
    return best


def as_str(data: Optional[dict], key: str, default: str = "") -> str:
    if not data:
        return default
    v = data.get(key, default)
    return str(v).strip() if v is not None else default


def as_float(data: Optional[dict], key: str, default: float = 0.0) -> float:
    if not data:
        return default
    v = data.get(key)
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def as_bool(data: Optional[dict], key: str, default: bool = False) -> bool:
    if not data:
        return default
    v = data.get(key)
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "是", "yes", "1")


def as_list(data: Optional[dict], key: str) -> list:
    if not data:
        return []
    v = data.get(key)
    if isinstance(v, list):
        return v
    if isinstance(v, str) and v.strip():
        return [x.strip() for x in re.split(r"[、,，;；]", v) if x.strip()]
    return []


class BaseTagAgent:
    """AgentScope 智能体基础封装."""

    def __init__(self, agent: Agent, timeout: float = 180.0):
        self._agent = agent
        self._timeout = timeout

    @property
    def name(self) -> str:
        return self._agent.name

    async def ask(self, prompt: str) -> Optional[dict]:
        """调用智能体并解析 JSON 结果.

        默认模型超时/网络异常时，优先切换备用模型重试一次，而非直接失败/降级。
        """
        agent = self._agent
        switched = False
        blank_retried = False
        while True:
            try:
                reply = await asyncio.wait_for(
                    agent.reply(UserMsg(name="user", content=prompt)),
                    timeout=self._timeout,
                )
            except asyncio.TimeoutError:
                logger.warning("[%s] 调用超时（%ss）", self.name, self._timeout)
                if not switched:
                    backup_agent = self._build_backup_agent()
                    if backup_agent is not None:
                        agent, switched = backup_agent, True
                        logger.warning("[%s] 切换到备用模型重试", self.name)
                        continue
                return None
            except Exception as e:  # noqa: BLE001
                logger.warning("[%s] 调用失败: %s", self.name, e)
                if not switched and is_timeout_error(e):
                    backup_agent = self._build_backup_agent()
                    if backup_agent is not None:
                        agent, switched = backup_agent, True
                        logger.warning("[%s] 切换到备用模型重试", self.name)
                        continue
                return None

            text = reply.get_text_content() if hasattr(reply, "get_text_content") else str(reply)
            if (text or "").strip():
                break  # 有实质内容，进入 JSON 解析
            # 空返回（content 为空串/纯空白）：网关波动或思考型模型偶发空内容。
            # 按调用失败处理：优先切备用模型，否则同模型重试一次。
            logger.warning("[%s] 模型空返回（content 仅空白），按调用失败处理", self.name)
            if not switched:
                backup_agent = self._build_backup_agent()
                if backup_agent is not None:
                    agent, switched = backup_agent, True
                    logger.warning("[%s] 空返回，切换备用模型重试", self.name)
                    continue
            if not blank_retried:
                blank_retried = True
                logger.warning("[%s] 空返回，同模型重试一次", self.name)
                continue
            break  # 重试后仍空 → 交给 parse_json 返回 None（保留原诊断日志）

        result = parse_json(text)
        if result is None:
            # 用 repr 输出前 500 字符：空输出 / 前后缀文字 / 空白字符都能一眼看清
            logger.warning(
                "[%s] 输出无法解析为 JSON（前500字符 repr）: %r",
                self.name,
                (text or "")[:500],
            )
        return result

    def _build_backup_agent(self) -> Optional[Agent]:
        """构建使用备用模型的同系统提示词 Agent（未配置备用模型时返回 None）。"""
        if not is_backup_configured():
            return None
        try:
            from tag_agent.llm import build_backup_chat_model

            sys_prompt = getattr(self._agent, "_system_prompt", None) or ""
            # 备用模型沿用同一套工具箱，切换后仍保持查证能力
            return Agent(
                name=self.name,
                system_prompt=sys_prompt,
                model=build_backup_chat_model(),
                toolkit=getattr(self._agent, "toolkit", None),
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("[%s] 备用模型初始化失败: %s", self.name, e)
            return None

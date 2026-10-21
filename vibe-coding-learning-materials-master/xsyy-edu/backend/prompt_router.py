# -*- coding: utf-8 -*-
"""分层提示词路由器 PromptRouter（方案 2026-09-03 §4.2/§4.3）.

职责：把教学画像 ContentProfile（学段 × 知识域 × 题型）映射为动画生成的
System Prompt —— 按 router_config.json 拼装：

    System = 00_base_scene_rules.txt（通用纪律层）
           + stage_{stage}/10_style_{stage}.txt（学段风格层）
           + domain_{display_class}/30_domain_{display_class}.txt（知识域表达层）

规则：
- 画像缺失 / 层文件缺失 / 读取失败 → 返回 None，调用方回退 legacy 单文件提示词，
  保证分层库灰度期间任何异常都不改变既有生成行为；
- 案例层（40_cases_*.md）在 P1 按 question_type 命中才注入（预留，文件缺失自动跳过）；
- SolutionAgent / PlanningAgent 的纪律层（01/02_*.txt）由 P2 独立拼装，本模块只读。
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# backend/prompt 目录（同 pipeline.py 的 prompt_dir）
_BACKEND_DIR = Path(__file__).resolve().parent
_PROMPT_DIR = _BACKEND_DIR / "prompt"
_CONFIG_PATH = _PROMPT_DIR / "animation" / "router_config.json"

# 学段 → ContentProfile.stage；知识域 → ContentProfile.display_class
_STAGE_KEY_MAP = {
    "primary_school": "primary_school",
    "junior_high": "junior_high",
}
_DISPLAY_KEY_MAP = {
    "numbers": "numbers",
    "equation": "equation",
    "function": "function",
    "geometry": "geometry",
    "statistics": "statistics",
    "calculation": "calculation",   # 兜底：未知/空域回退，路由到 domain_numbers
}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning("提示词层文件读取失败 %s: %s", path, exc)
        return ""


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("router_config 解析失败 %s: %s", path, exc)
        return {}


def load_config() -> dict:
    """加载 router_config.json；失败返回空 dict（调用方据此回退 legacy）."""
    return _read_json(_CONFIG_PATH)


def build_animation_system_prompt(profile: Optional[dict]) -> Optional[str]:
    """按画像拼装动画生成 System Prompt.

    Args:
        profile: ContentProfile.to_dict() 结果（含 stage/display_class/
                 visual_requirements.style_key/question_type）或 None。

    Returns:
        拼装后的完整 System Prompt；任何环节缺失返回 None（调用方回退 legacy）。
    """
    if not profile:
        return None

    config = load_config()
    if not config:
        logger.warning("router_config 为空，动画提示词回退 legacy")
        return None

    prompt_dir = _PROMPT_DIR / (config.get("prompt_dir") or "animation")

    # 1) 通用纪律层
    base_cfg = config.get("base") or {}
    base_file = prompt_dir / (base_cfg.get("file") or "00_base_scene_rules.txt")
    base_text = _read_text(base_file)
    if not base_text:
        logger.warning("00_base_scene_rules.txt 缺失/为空，动画提示词回退 legacy")
        return None

    # 2) 学段风格层
    stage = profile.get("stage", "")
    stage_layer = ""
    stage_cfg = ((config.get("layers") or {}).get("stage") or {}).get(_STAGE_KEY_MAP.get(stage, ""), {})
    if stage_cfg:
        stage_file = prompt_dir / (stage_cfg.get("dir") or "") / (stage_cfg.get("style_file") or "")
        stage_layer = _read_text(stage_file)

    # 3) 知识域表达层（支持复合多域注入：复合题按 parts 的展示大类逐个叠加）
    display_classes: list[str] = []
    if profile.get("is_composite") and profile.get("domains"):
        display_classes = list(profile["domains"])
    else:
        dc = profile.get("display_class", "")
        if dc:
            display_classes = [dc]
    domain_layers: list[str] = []
    for dc in display_classes:
        domain_cfg = ((config.get("layers") or {}).get("domain") or {}).get(_DISPLAY_KEY_MAP.get(dc, ""), {})
        if domain_cfg:
            domain_file = prompt_dir / (domain_cfg.get("dir") or "") / (domain_cfg.get("style_file") or "")
            text = _read_text(domain_file)
            if text:
                domain_layers.append(text)
    domain_layer = "\n\n---\n\n".join(domain_layers)

    sections = [base_text]
    if stage_layer:
        sections.append(stage_layer)
    if domain_layer:
        sections.append(domain_layer)

    # 3.5) 题型画法模板层（scene_pattern，2026-09-05）：在知识域之后、解法纪律之前，
    #      按画像 question_type（含复合题各小题）命中 pattern_key 整段注入；
    #      未命中 / 目录缺失 / 文件缺失 → 静默跳过，不影响既有拼装。
    pattern_text = _build_pattern_section(prompt_dir, config, profile)
    if pattern_text:
        sections.append(pattern_text)

    # 4) 完整解答纪律层（01_solution_rules.txt）：右侧"完整解法"卷轴由各步
    #    steps.title + steps.description 连读而成；本层约束 steps 文本的书面完整度。
    #    动画/解答不分产物（2026-09-03 用户拍板取消分离），故随动画 System 一并注入。
    sol_rules = _read_text(prompt_dir / "01_solution_rules.txt")
    if sol_rules:
        sections.append(sol_rules)

    # 4.1) 案例层：按 question_type 命中才注入（P1 预留，文件缺失自动跳过）
    qtype = profile.get("question_type", "")
    _primary_display_class = profile.get("display_class", "") or (profile.get("domains") or [""])[0]
    case_text = _build_case_section(prompt_dir, config, stage, _primary_display_class, qtype)
    if case_text:
        sections.append(case_text)

    # 4.5) 复合多小题通用案例（凡复合题都注入，提供多问结构示范）
    if profile.get("is_composite"):
        comp_case = prompt_dir / "cases" / "composite_multi_part.md"
        if comp_case.exists():
            ctext = _read_text(comp_case)
            if ctext:
                sections.append("## 参考案例（复合多小题通用结构）\n" + ctext)

    # 5) 画像信息注入（让模型知晓本题的学段/知识域/题型上下文）
    context_lines = [
        "## 本题教学画像（识别结果，必须服从）",
        f"- 学段：{stage}",
        f"- 知识域：{profile.get('domain', '') or '未标注'}",
        f"- 展示大类：{profile.get('display_class', '') or '未标注'}",
        f"- 年级：{profile.get('grade', '') or '未标注'}",
        f"- 题型：{qtype or '未标注'}",
    ]
    if (profile.get("visual_requirements") or {}).get("must_show"):
        context_lines.append(
            "- 本类必画要素：" + "、".join(profile["visual_requirements"]["must_show"])
        )
    sections.append("\n".join(context_lines))

    return "\n\n---\n\n".join(s for s in sections if s and s.strip())


def _build_case_section(
    prompt_dir: Path,
    config: dict,
    stage: str,
    display_class: str,
    question_type: str,
) -> str:
    """案例层：按 question_type 命中配置的案例文件则整段注入；否则跳过.

    P1 阶段案例文件尚未编写时静默跳过；P1 后期/生产可按题型补充 40_cases_*.md。
    """
    if not question_type:
        return ""
    layers = config.get("layers") or {}
    case_paths: list[Path] = []

    # 知识域案例（最常见：题目命中域级案例）
    domain_cfg = (layers.get("domain") or {}).get(_DISPLAY_KEY_MAP.get(display_class, ""), {})
    if domain_cfg:
        case_paths.append(prompt_dir / (domain_cfg.get("dir") or "") / (domain_cfg.get("case_file") or ""))
    # 学段案例
    stage_cfg = (layers.get("stage") or {}).get(_STAGE_KEY_MAP.get(stage, ""), {})
    if stage_cfg:
        case_paths.append(prompt_dir / (stage_cfg.get("dir") or "") / (stage_cfg.get("case_file") or ""))

    # 通用案例目录（按题型文件名匹配）
    case_dir = prompt_dir / "cases"
    if case_dir.is_dir():
        target = case_dir / f"{question_type}.md"
        if target.exists():
            case_paths.append(target)

    collected: list[str] = []
    for path in case_paths:
        if path and path.exists():
            text = _read_text(path)
            if text:
                collected.append(text)

    if not collected:
        return ""
    header = (
        "## 参考案例（与本题题型相同，只借鉴分镜/讲解结构，禁止照抄数据与图形）\n"
    )
    return header + "\n\n".join(collected)


def _build_pattern_section(prompt_dir: Path, config: dict, profile: dict) -> str:
    """题型画法模板层：按画像命中的 pattern_key 整段注入；未命中/缺失静默跳过.

    pattern ≠ case：case 是"参考讲解"（借结构禁抄数据）；pattern 是**画法硬规范**
    （该题型场景必须长成什么样 + 运动序列约定），约束级别更高。
    命中键解析复用 content_profile.pattern_keys_for_profile（与 pipeline Lint 同口径）。
    """
    pattern_cfg = ((config.get("layers") or {}).get("scene_pattern") or {})
    pattern_dir = pattern_cfg.get("dir") or "scene_patterns"
    file_map = pattern_cfg.get("files") or {}
    if not pattern_dir or not file_map:
        return ""
    try:
        from tag_agent.content_profile import pattern_keys_for_profile
    except Exception as exc:  # noqa: BLE001
        logger.warning("pattern_keys_for_profile 导入失败，跳过画法模板注入: %s", exc)
        return ""
    collected: list[str] = []
    for key in pattern_keys_for_profile(profile):
        rel_file = file_map.get(key)
        if not rel_file:
            continue
        path = prompt_dir / pattern_dir / rel_file
        if not path.exists():
            logger.warning("题型画法模板缺失（跳过）: %s", path)
            continue
        text = _read_text(path)
        if text:
            collected.append(text)
    if not collected:
        return ""
    return "## 题型画法模板（命中即必须遵守，约束级别高于案例层）\n" + "\n\n---\n\n".join(collected)


def build_solution_rules_prompt() -> str:
    """完整解答纪律层（P2 SolutionAgent 拼装用，缺文件返回空字符串）. """
    config = load_config()
    if not config:
        return ""
    prompt_dir = _PROMPT_DIR / (config.get("prompt_dir") or "animation")
    return _read_text(prompt_dir / (config.get("solution_rules") or "01_solution_rules.txt"))


def build_teaching_plan_rules_prompt() -> str:
    """教学节拍表纪律层（P2 PlanningAgent 拼装用，缺文件返回空字符串）. """
    config = load_config()
    if not config:
        return ""
    prompt_dir = _PROMPT_DIR / (config.get("prompt_dir") or "animation")
    return _read_text(prompt_dir / (config.get("teaching_plan_rules") or "02_teaching_plan.txt"))

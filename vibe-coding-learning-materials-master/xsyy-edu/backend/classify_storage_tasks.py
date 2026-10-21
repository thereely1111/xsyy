from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from kimi_config import (
    get_active_model,
    get_api_key,
    get_base_url,
    get_active_params,
    get_backup_api_key,
    get_backup_base_url,
    get_backup_model,
    get_params_for_model,
    is_backup_configured,
    is_timeout_error,
    record_success,
    record_failure,
)

# 加载 .env 文件
backend_dir = Path(__file__).resolve().parent
env_path = backend_dir / ".env"
load_dotenv(dotenv_path=env_path)

# Storage 目录路径
storage_dir = backend_dir.parent / "storage"

# 说明：知识点标签（知识域/年级/章/单元/知识点）已由独立的标签识别模型
# （knowledge_tag_injector.py，两步分层大模型）负责，本模块只负责
# 判断是否为数学题、提取题目、生成标题，不再输出/校验任何标签字段。


def log(message: str, level: str = "INFO"):
    """实时日志输出函数，带时间戳"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_message = f"[{timestamp}] [{level}] {message}"
    print(log_message, flush=True)
    sys.stdout.flush()


def load_prompt_template(file_path: Path) -> str:
    """从文件加载 prompt 模板。"""
    try:
        if file_path.exists():
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read().strip()
        else:
            log(f"Prompt 文件不存在: {file_path}", "WARN")
            return ""
    except Exception as e:
        log(f"读取 Prompt 文件失败 {file_path}: {e}", "ERROR")
        return ""


# ── W1 标题概括优化（方案 §14 / xsyy-9 SKILL.md）─────────────────────────────
# 基线缺陷（201 份 metadata 实测）：50.7% 标题以「题/问题」结尾（题面词冒充考点）、
# 归类错误（牛吃草→鸡兔同笼）、超长未拦截。根因＝规则层命中即 return 短路 LLM。

TITLE_MAX_LEN = 10
_TITLE_GENERIC_WORDS = ("数学题", "题目", "应用题", "问题", "练习题", "试题", "考题")


def validate_title(title: str) -> tuple[bool, str]:
    """P0-3 代码级标题约束校验：≤10 字 ∧ 非泛称 ∧ 不以「题/问题」结尾.

    Returns:
        (是否合格, 不合格原因)；合格时原因为 ""。
    """
    t = re.sub(r"\s+", "", str(title or ""))
    if not t:
        return False, "标题为空"
    if len(t) > TITLE_MAX_LEN:
        return False, f"超长（{len(t)} 字 > {TITLE_MAX_LEN} 字）"
    if t.endswith("题"):
        return False, "以「题/问题/应用题」结尾（题面词冒充考点）"
    if t in _TITLE_GENERIC_WORDS:
        return False, "泛称标题（未指向具体考点）"
    return True, ""


def _normalize_rule_title(title: str) -> str:
    """规则库候选标题归一：剥掉尾部「问题/应用题/题」等题面化后缀（P0-1 配套）.

    规则库 title 本多以「问题」结尾（如"工程问题"），直接用作展示标题正是
    50.7% 基线缺陷的来源之一；剥后缀后即指向考点（"工程""几何面积周长"）。
    """
    t = re.sub(r"\s+", "", str(title or ""))
    for suffix in ("应用题", "问题", "题"):
        if t.endswith(suffix) and len(t) > len(suffix):
            t = t[: -len(suffix)]
            break
    return t


def _rule_fallback_result(rule_candidate: Optional[dict], reason: str) -> Optional[dict]:
    """W1 降级链（P0-1）：LLM 最终失败时保留规则层候选，不阻断主流程.

    降级链：规则层 title（候选）→ LLM 复核/自拟 → question[:30] 截断（调用方）。
    候选标题先归一（剥题面化后缀）并校验，不合格打标 title_quality=low。
    """
    if not rule_candidate:
        return None
    fallback = dict(rule_candidate)
    normalized = _normalize_rule_title(fallback.get("title") or "")
    ok, _ = validate_title(normalized)
    fallback["title"] = normalized
    fallback["title_quality"] = "ok" if ok else "low"
    fallback["reasoning"] = f"{fallback.get('reasoning', '')}（规则候选兜底：{reason}）".strip()
    log(f"LLM 不可用，降级使用规则层候选标题: {normalized}（{reason}）", "WARN")
    return fallback


MATH_PROBLEM_FEATURE_LIBRARY = [
    {
        "type": "余数与同余问题",
        "title": "余数与同余问题",
        "reasoning": "命中除法余数条件或同余结构",
        "priority": 98,
        "direct_keywords": ("余数", "同余", "余数分别是", "除后余数"),
        "structure_keywords": ("分别除以", "去除以", "被除数", "除数", "商", "自然数", "最小公倍数"),
        "quantity_keywords": ("最小是多少", "最小值", "求"),
        "threshold": 5,
    },
    {
        "type": "鸡兔同笼问题",
        "title": "鸡兔同笼",
        "reasoning": "命中双对象总量分配结构",
        "priority": 100,
        "direct_keywords": ("鸡兔同笼",),
        "structure_keywords": ("晴天", "雨天", "鸡", "兔", "头", "脚", "腿", "只", "辆", "船", "运", "次"),
        "quantity_keywords": ("一共", "共", "总共", "总数", "合计", "平均", "平均每天", "每天", "几天", "有几天", "多少只", "多少辆"),
        "threshold": 8,
    },
    {
        "type": "列车过桥过隧道问题",
        "title": "列车过桥过隧道问题",
        "reasoning": "命中列车通过长度结构",
        "priority": 95,
        "direct_keywords": ("过桥", "过隧道", "通过隧道", "通过大桥", "错车而过"),
        "structure_keywords": ("列车", "火车", "车长", "桥长", "隧道", "速度", "每秒", "米/秒", "千米/时"),
        "quantity_keywords": ("需要多少秒", "多少秒", "几秒", "用时", "时间"),
        "threshold": 6,
    },
    {
        "type": "行程相遇追及问题",
        "title": "相遇与追及问题",
        "reasoning": "命中行程双向运动结构",
        "priority": 90,
        "direct_keywords": ("相遇", "追及", "相向而行", "同向而行", "追上", "同时出发"),
        "structure_keywords": ("速度", "路程", "距离", "相距", "千米", "米", "分钟", "小时", "每小时", "每分钟"),
        "quantity_keywords": ("经过", "几小时", "几分钟", "多少时间", "多久"),
        "threshold": 6,
    },
    {
        "type": "工程问题",
        "title": "工程问题",
        "reasoning": "命中工作效率与总工程量结构",
        "priority": 85,
        "direct_keywords": ("工程", "工作效率", "合作完成", "单独完成"),
        "structure_keywords": ("甲", "乙", "修", "做", "完成", "加工", "水池", "注满", "排空"),
        "quantity_keywords": ("几天", "多少天", "每天", "一共", "合作", "单独", "还需"),
        "threshold": 6,
    },
    {
        "type": "利润折扣问题",
        "title": "利润折扣问题",
        "reasoning": "命中售价成本利润结构",
        "priority": 82,
        "direct_keywords": ("利润", "利润率", "打折", "折扣", "售价", "进价", "成本"),
        "structure_keywords": ("商品", "商店", "原价", "现价", "降价", "提价", "盈利", "亏损"),
        "quantity_keywords": ("百分之", "%", "多少元", "赚", "亏"),
        "threshold": 5,
    },
    {
        "type": "概率问题",
        "title": "概率问题",
        "reasoning": "命中随机事件概率结构",
        "priority": 80,
        "direct_keywords": ("概率", "可能性", "随机", "摸出", "抽到", "取出"),
        "structure_keywords": ("红球", "黄球", "白球", "袋", "转盘", "骰子", "扑克牌", "事件"),
        "quantity_keywords": ("求", "多少", "共有", "共", "个", "张", "次"),
        "threshold": 5,
    },
    {
        "type": "统计图表问题",
        "title": "统计图表问题",
        "reasoning": "命中数据统计图表结构",
        "priority": 78,
        "direct_keywords": ("统计图", "扇形统计图", "条形统计图", "折线统计图", "频数", "频率"),
        "structure_keywords": ("样本", "总体", "调查", "数据", "人数", "百分比", "圆心角"),
        "quantity_keywords": ("平均数", "中位数", "众数", "方差", "占比"),
        "threshold": 5,
    },
    {
        "type": "圆与扇形问题",
        "title": "圆与扇形问题",
        "reasoning": "命中圆相关长度面积结构",
        "priority": 75,
        "direct_keywords": ("圆", "扇形", "圆心角", "弧长", "圆周率"),
        "structure_keywords": ("半径", "直径", "周长", "面积", "圆心", "圆弧"),
        "quantity_keywords": ("求", "计算", "多少", "厘米", "平方米"),
        "threshold": 5,
    },
    {
        "type": "几何面积周长问题",
        "title": "几何面积周长问题",
        "reasoning": "命中平面图形面积周长结构",
        "priority": 72,
        "direct_keywords": ("面积", "周长", "体积", "表面积"),
        "structure_keywords": ("长方形", "正方形", "三角形", "平行四边形", "梯形", "圆柱", "圆锥", "长", "宽", "高", "底"),
        "quantity_keywords": ("求", "计算", "多少", "厘米", "平方", "立方"),
        "threshold": 5,
    },
    {
        "type": "函数图象问题",
        "title": "函数图象问题",
        "reasoning": "命中函数解析式图象结构",
        "priority": 70,
        "direct_keywords": ("一次函数", "二次函数", "反比例函数", "函数图象", "抛物线", "双曲线"),
        "structure_keywords": ("解析式", "图象", "图像", "坐标", "交点", "顶点", "对称轴", "k值", "y="),
        "quantity_keywords": ("求", "经过", "面积", "最值", "最大值", "最小值"),
        "threshold": 5,
    },
    {
        "type": "二元一次方程组问题",
        "title": "二元一次方程组",
        "reasoning": "命中二元关系与方程组结构",
        "priority": 68,
        "direct_keywords": ("二元一次方程组", "方程组", "设x", "设y"),
        "structure_keywords": ("两个未知数", "消元", "代入法", "加减法", "x", "y"),
        "quantity_keywords": ("解", "求", "分别", "各"),
        "threshold": 5,
    },
    {
        "type": "不等式问题",
        "title": "不等式问题",
        "reasoning": "命中不等关系结构",
        "priority": 66,
        "direct_keywords": ("不等式", "不等式组", "解集", "大于", "小于", "不超过", "至少", "至多"),
        "structure_keywords": (">", "<", "≥", "≤", "范围", "取值"),
        "quantity_keywords": ("求", "解", "满足", "最多", "最少"),
        "threshold": 4,
    },
    {
        "type": "比例问题",
        "title": "比和比例问题",
        "reasoning": "命中比与比例关系结构",
        "priority": 64,
        "direct_keywords": ("正比例", "反比例", "比例尺", "按比例", "成比例", "比值"),
        "structure_keywords": ("比", "比例", "份", "甲乙", "扩大", "缩小"),
        "quantity_keywords": ("求", "多少", "几", "分配"),
        "threshold": 5,
    },
    {
        "type": "百分数问题",
        "title": "百分数问题",
        "reasoning": "命中百分数应用结构",
        "priority": 62,
        "direct_keywords": ("百分数", "百分之", "%", "折", "成", "税率", "利率"),
        "structure_keywords": ("增加", "减少", "降低", "提高", "原来", "现在", "本金", "利息"),
        "quantity_keywords": ("求", "多少", "几成", "几折"),
        "threshold": 4,
    },
    {
        "type": "分数应用题",
        "title": "分数应用题",
        "reasoning": "命中分数运算应用结构",
        "priority": 60,
        "direct_keywords": ("几分之", "分数", "1/", "2/", "3/"),
        "structure_keywords": ("占", "还剩", "用去", "增加", "减少", "全长", "总数"),
        "quantity_keywords": ("求", "多少", "一共", "剩下"),
        "threshold": 4,
    },
    {
        "type": "平均数问题",
        "title": "平均数问题",
        "reasoning": "命中平均量结构",
        "priority": 58,
        "direct_keywords": ("平均数", "加权平均", "平均每天", "平均每", "平均"),
        "structure_keywords": ("总数", "总量", "分成", "份", "次数", "数量", "合计"),
        "quantity_keywords": ("求平均", "一共", "总共"),
        "threshold": 5,
    },
    {
        "type": "一元一次方程应用题",
        "title": "一元一次方程应用题",
        "reasoning": "命中方程建模结构",
        "priority": 45,
        "direct_keywords": ("解方程", "列方程", "设未知数", "方程"),
        "structure_keywords": ("相等", "未知数", "设x", "设y"),
        "quantity_keywords": ("求", "多少", "几", "余下", "还剩"),
        "threshold": 5,
    },
]


def _count_keyword_hits(text: str, keywords: tuple[str, ...]) -> int:
    return sum(1 for keyword in keywords if keyword and keyword in text)


def _score_structured_rule(question: str, rule: dict) -> int:
    score = 0
    score += _count_keyword_hits(question, rule["direct_keywords"]) * 4
    score += _count_keyword_hits(question, rule["structure_keywords"]) * 2
    score += _count_keyword_hits(question, rule["quantity_keywords"])

    if rule["type"] == "整数周期与分配" and any(
        word in question for word in ("余数", "同余", "分别除以", "除后余数")
    ):
        score -= 8

    if rule["type"] == "统计图表问题":
        statistic_markers = _count_keyword_hits(question, ("平均数", "中位数", "众数", "方差", "样本", "总体", "频数", "频率"))
        if statistic_markers >= 2:
            score += 8

    if rule["type"] == "利润折扣问题":
        if "折" in question and any(word in question for word in ("原价", "现价", "售价", "衣服", "商品", "出售")):
            score += 8

    if rule["type"] == "百分数问题":
        if "折" in question and any(word in question for word in ("原价", "现价", "售价", "衣服", "商品", "出售")):
            score -= 4

    if rule["type"] == "平均数问题":
        statistic_markers = _count_keyword_hits(question, ("中位数", "众数", "方差", "样本", "总体", "频数", "频率"))
        if statistic_markers >= 1:
            score -= 6

    if rule["type"] == "鸡兔同笼问题":
        dual_markers = _count_keyword_hits(question, ("晴天", "雨天", "鸡", "兔", "头", "脚", "腿", "船", "辆", "只"))
        total_markers = _count_keyword_hits(question, ("一共", "共", "总共", "总数", "平均", "平均每天", "每天", "几天"))
        if dual_markers >= 2 and total_markers >= 2:
            score += 6
        if "平均每天" in question and ("一共" in question or "总共" in question):
            score += 3
        if "晴天" in question and "雨天" in question:
            score += 4
        if "鸡" in question and "兔" in question and any(word in question for word in ("头", "脚", "腿")):
            score += 4

    if rule["type"] == "概率问题" and any(word in question for word in ("摸到", "抽到", "取到")):
        score += 3
    if rule["type"] == "函数图象问题" and any(word in question for word in ("y=", "解析式", "图象", "图像")):
        score += 3
    if rule["type"] == "不等式问题":
        if any(word in question for word in ("证明", "三角形两边之和", "大于第三边")):
            score -= 8
        if not any(word in question for word in ("解", "解集", "取值", "范围", "满足", "最多", "最少", "不超过", "至少", "至多")):
            score -= 4

    if rule["type"] == "一元一次方程应用题" and not any(word in question for word in ("方程", "列方程", "解方程", "设未知数")):
        score -= 4

    return score


def _detect_structured_math_type(question: str) -> Optional[dict]:
    """基于题型特征库优先识别常见数学题型，减少大模型泛化误判。"""
    normalized = re.sub(r"\s+", "", question or "")
    if not normalized:
        return None

    candidates = []
    for rule in MATH_PROBLEM_FEATURE_LIBRARY:
        score = _score_structured_rule(normalized, rule)
        if score >= rule["threshold"]:
            candidates.append((score, rule.get("priority", 0), rule))

    if not candidates:
        return None

    score, _, best_rule = max(candidates, key=lambda item: (item[0], item[1]))
    return {
        "is_math_problem": True,
        "question": question.strip() or None,
        "title": best_rule["title"],
        "reasoning": best_rule["reasoning"],
    }


def get_llm_classifier() -> ChatOpenAI:
    """获取或初始化分类器 LLM 实例（Kimi，延迟初始化）。"""
    api_key = get_api_key()
    if not api_key:
        raise RuntimeError(
            "缺少环境变量 KIMI_API_KEY。"
            "请配置后再使用：setx KIMI_API_KEY \"你的密钥\""
        )

    # Kimi 提供 OpenAI 兼容接口
    params = get_active_params()
    extra = params.pop("extra_body", None)
    llm = ChatOpenAI(
        model=get_active_model(),
        api_key=api_key,
        base_url=get_base_url(),
        temperature=0.3,
        max_retries=2,
        timeout=180,
        extra_body=extra,
        model_kwargs=params if params else {},
    )
    return llm


def get_llm_classifier_backup() -> ChatOpenAI:
    """获取备用模型分类器 LLM 实例（默认模型超时/网络异常时切换，延迟初始化）。"""
    api_key = get_backup_api_key()
    if not api_key:
        raise RuntimeError("备用模型未配置 BACKUP_MODEL_API_KEY，请在 .env 中配置")

    # 备用模型提供 OpenAI 兼容接口
    params = get_params_for_model(get_backup_model())
    extra = params.pop("extra_body", None)
    llm = ChatOpenAI(
        model=get_backup_model(),
        api_key=api_key,
        base_url=get_backup_base_url(),
        temperature=0.3,
        max_retries=1,
        timeout=180,
        extra_body=extra,
        model_kwargs=params if params else {},
    )
    return llm


async def analyze_question(question: str, llm: ChatOpenAI, max_validation_retries: int = 3) -> dict | None:
    """一次性调用大模型：判断是否为数学题，如果是则提取题目并生成标题。

    返回格式（与 classification_system_prompt.txt 一致）：
    {
        "is_math_problem": true/false,
        "question": "提取的完整题目" (仅当is_math_problem为true时，非数学题为null),
        "title": "标题" (仅当is_math_problem为true时，非数学题为null),
        "reasoning": "简短判定理由" (仅当is_math_problem为true时)
    }

    注意：知识点标签由 knowledge_tag_injector.py 的两步标签识别模型负责，本函数不输出标签。

    如果失败返回 None。
    """
    structured_result = _detect_structured_math_type(question)
    # W1 P0-1（方案 §14 / xsyy-9）：规则层命中不得直接 return 短路 LLM——
    # 短路正是"归类错误"（牛吃草→鸡兔同笼）的根因。候选降级为参考信息
    # 交模型复核，不一致时以题意为准自拟标题；LLM 最终失败再走规则兜底。
    rule_candidate = structured_result
    if rule_candidate:
        log(
            f"结构题特征命中（候选，交由模型复核）: {rule_candidate['title']}",
            "INFO",
        )
        candidate_hint = (
            f"\n\n[规则候选参考] 规则库命中题型：{rule_candidate['title']}"
            f"（命中理由：{rule_candidate['reasoning']}）。"
            "该候选仅作参考：若与题目实际考点不符（例如把牛吃草问题误判为鸡兔同笼），"
            "必须忽略候选，按题目实际考点自拟标题。"
        )
    else:
        candidate_hint = ""

    # 加载 prompt 模板
    backend_dir = Path(__file__).resolve().parent
    system_prompt_path = backend_dir / "prompt" / "classification_system_prompt.txt"
    user_prompt_path = backend_dir / "prompt" / "classification_user_prompt.txt"

    system_prompt_template = load_prompt_template(system_prompt_path)
    user_prompt_template = load_prompt_template(user_prompt_path)

    # 使用 prompt 文件中的格式，如果文件不存在则使用默认格式
    if not system_prompt_template:
        system_prompt = (
            "你是一名资深的初中数学题目分析专家。\n\n"
            "你需要对用户输入的文本进行分析，严格按照以下流程处理，并输出标准的JSON格式：\n"
            "1. 判断：输入是否为数学题目。\n"
            "2. 提取：从用户输入文本中提取完整题目。\n"
            "3. 概括：如果是数学题，提炼核心考点作为标题。\n\n"
            "知识点标签由独立的标签识别模型负责，不需要输出任何标签字段。\n\n"
            "输出格式必须为标准JSON（不包含markdown标记）：\n"
            "{\n"
            '  "is_math_problem": true/false,\n'
            '  "question": "提取的完整题目",\n'
            '  "title": "核心考点标题" (10字以内，非数学题为null),\n'
            '  "reasoning": "简短判定理由" (15字以内，非数学题为null)\n'
            "}"
        )
    else:
        # 直接使用 prompt 文件中的内容
        system_prompt = system_prompt_template

    # 构建用户提示词
    if not user_prompt_template:
        user_prompt_base = question
    else:
        user_prompt_base = user_prompt_template.replace("__USER_INPUT__", question)

    log(f"调用 Kimi API 分析题目（判断+提取+标题）: {question[:80]}..." if len(question) > 80 else f"调用 Kimi API 分析题目（判断+提取+标题）: {question}")
    
    # 设置 API 调用超时（120秒）
    timeout_seconds = 120
    max_api_retries = 2

    # 备用模型（默认模型超时/网络异常时优先切换重试，而非直接降级）
    backup_llm = None
    used_backup = False
    if is_backup_configured():
        try:
            backup_llm = get_llm_classifier_backup()
        except Exception as e:  # noqa: BLE001
            log(f"备用模型初始化失败，跳过备用模型: {e}", "WARN")
            backup_llm = None

    user_prompt = user_prompt_base + candidate_hint
    api_start = datetime.now()

    # W1 P0-3：标题约束校验失败后的"带原因重试"只允许一次
    title_retry_used = False

    # API 调用重试循环（处理网络错误、超时、解析失败等）
    for api_attempt in range(max_api_retries + 1):
        try:
            log(f"Kimi API 调用尝试 {api_attempt + 1}/{max_api_retries + 1}...")

            resp = await asyncio.wait_for(
                llm.ainvoke(
                    [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ]
                ),
                timeout=timeout_seconds
            )

            api_elapsed = (datetime.now() - api_start).total_seconds()
            record_success()
            output = resp.content if hasattr(resp, "content") else str(resp)
            log(f"Kimi API 调用成功，耗时: {api_elapsed:.2f} 秒，输出长度: {len(output)} 字符")

            # 解析 JSON 结果
            result = parse_analysis_result(output)
            if not result:
                log(f"结果解析失败，原始输出: {output[:200]}...", "WARN")
                if api_attempt < max_api_retries:
                    log("正在重试 API 调用...", "WARN")
                    await asyncio.sleep(2)
                    api_start = datetime.now()
                    continue
                else:
                    break

            # 检查是否为数学题（使用 is_math_problem 字段）
            if not result.get("is_math_problem", True):
                log("判断结果：不是数学题")
                return {
                    "is_math_problem": False,
                    "question": None,
                    "title": None,
                    "reasoning": None,
                }

            log(f"分析结果验证通过: 标题={result.get('title', 'N/A')}")
            # W1 P0-3：标题代码级约束校验（≤10 字 ∧ 非泛称 ∧ 不以「题/问题」结尾）；
            # 不合格带原因重试 1 次，仍不过才落库并打标 title_quality=low。
            title_ok, title_reason = validate_title(result.get("title"))
            if not title_ok and not title_retry_used and api_attempt < max_api_retries:
                title_retry_used = True
                log(f"标题约束校验未通过（{title_reason}），带原因重试 1 次: {result.get('title')}", "WARN")
                user_prompt = (
                    user_prompt_base + candidate_hint
                    + f"\n\n[标题修正] 上一次给出的标题「{result.get('title')}」不合格（原因：{title_reason}）。"
                    "请重新给出标题：≤10 字、指向本题真实考点、不得以「题/问题/应用题」结尾。"
                )
                api_start = datetime.now()
                continue

            result["title_quality"] = "ok" if title_ok else "low"
            if not title_ok:
                log(f"标题约束校验仍未通过，落库打标 title_quality=low: {result.get('title')}（{title_reason}）", "WARN")
            return result

        except asyncio.TimeoutError:
            api_elapsed = (datetime.now() - api_start).total_seconds()
            record_failure()
            # 默认模型超时 → 先切备用模型重试一次，而非直接重试/降级
            if not used_backup and backup_llm is not None:
                used_backup = True
                llm = backup_llm
                log(
                    f"Kimi API 调用超时（{timeout_seconds}秒，已耗时 {api_elapsed:.2f}s），"
                    f"切换到备用模型 {get_backup_model()} 重试",
                    "WARN",
                )
                api_start = datetime.now()
                continue
            if api_attempt < max_api_retries:
                log(f"Kimi API 调用超时（{timeout_seconds}秒），已耗时: {api_elapsed:.2f} 秒，正在重试...", "WARN")
                await asyncio.sleep(2)
                api_start = datetime.now()
            else:
                log(f"Kimi API 调用超时（{timeout_seconds}秒），已重试 {max_api_retries} 次，最终失败", "ERROR")
                return _rule_fallback_result(rule_candidate, "LLM 调用超时")

        except Exception as e:
            api_elapsed = (datetime.now() - api_start).total_seconds()
            record_failure()
            # 默认模型网络/连接异常 → 先切备用模型重试一次，而非直接重试/降级
            if not used_backup and backup_llm is not None and is_timeout_error(e):
                used_backup = True
                llm = backup_llm
                log(
                    f"Kimi API 调用网络异常（已耗时 {api_elapsed:.2f}s）: {str(e)}，"
                    f"切换到备用模型 {get_backup_model()} 重试",
                    "WARN",
                )
                api_start = datetime.now()
                continue
            if api_attempt < max_api_retries:
                log(f"Kimi API 调用出错（已耗时: {api_elapsed:.2f} 秒）: {str(e)}，正在重试...", "WARN")
                await asyncio.sleep(2)
                api_start = datetime.now()
            else:
                log(f"Kimi API 调用失败，已重试 {max_api_retries} 次，最终错误: {str(e)}", "ERROR")
                return _rule_fallback_result(rule_candidate, f"LLM 调用失败: {type(e).__name__}")

    # 所有重试都失败
    log("分析失败，已重试全部次数，最终失败", "ERROR")
    return _rule_fallback_result(rule_candidate, "LLM 重试全部失败")


def parse_analysis_result(output: str) -> dict | None:
    """解析分析结果 JSON（与 classification_system_prompt.txt 格式一致）。

    返回格式：
    {
        "is_math_problem": true/false,
        "question": "提取的完整题目" (非数学题为null),
        "title": "标题" (非数学题为null),
        "reasoning": "简短判定理由" (非数学题为null),
        "version": "版本" (非数学题为null),
        "grade": "年级" (非数学题为null),
        "main_tag": "主标签" (非数学题为null),
        "sub_tags": ["子标签1", "子标签2"] (非数学题为[])
    }
    """
    # 尝试提取 JSON 部分（prompt 要求不包含 markdown 标记，但可能模型仍会添加）
    json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', output, re.DOTALL)
    if json_match:
        json_str = json_match.group(1)
    else:
        # 用栈匹配括号找完整 JSON（避免 LaTeX {x} 中的 } 截断）
        start = output.find('{')
        if start >= 0:
            depth = 0
            in_string = False
            escape_next = False
            for i in range(start, len(output)):
                ch = output[i]
                if escape_next:
                    escape_next = False
                    continue
                if ch == '\\':
                    escape_next = True
                    continue
                if ch == '"':
                    in_string = not in_string
                    continue
                if not in_string:
                    if ch == '{':
                        depth += 1
                    elif ch == '}':
                        depth -= 1
                        if depth == 0:
                            json_str = output[start:i+1]
                            break
            else:
                json_str = output.strip()
        else:
            json_str = output.strip()
    
    # 修复 Kimi 返回的 JSON 中 LaTeX 反斜杠未转义的问题
    # \frac, \sqrt, \times 等 LaTeX 命令中的 \ 在 JSON 中必须写成 \\
    # 转义所有 \ + 字母 的组合（跳过 \\\\ \\\" 等已转义的）
    # \n（JSON 换行）与 \u（JSON Unicode）需原样保留
    json_str = re.sub(r'(?<!\\)\\(?![nu])([a-zA-Z])', r'\\\\\1', json_str)

    try:
        result = json.loads(json_str)
        
        # 检查是否为数学题（支持 is_math_problem 和 is_math_question 两种格式）
        is_math = result.get("is_math_problem", result.get("is_math_question", True))
        
        if not is_math:
            return {
                "is_math_problem": False,
                "question": None,
                "title": None,
                "reasoning": None,
            }
        
        # 确保兼容新旧解析格式
        # 新的题目分析 prompt 只返回题目判定、提取和标题，不再返回标签字段
        sub_tags = result.get("sub_tags", [])
        if not isinstance(sub_tags, list):
            sub_tags = []
        main_tag = result.get("main_tag")
        if main_tag is not None and not isinstance(main_tag, str):
            main_tag = str(main_tag)
        
        return {
            "is_math_problem": True,
            "question": result.get("question", "").strip() if result.get("question") else None,
            "title": result.get("title", "").strip() if result.get("title") else None,
            "reasoning": result.get("reasoning", "").strip() if result.get("reasoning") else "",
            "version": result.get("version", "").strip() if result.get("version") else None,
            "grade": result.get("grade", "").strip() if result.get("grade") else None,
            "main_tag": main_tag,
            "sub_tags": sub_tags
        }
    except json.JSONDecodeError as e:
        log(f"解析分析结果 JSON 失败: {e}，原始输出: {output[:200]}...", "ERROR")
        return None


async def process_task(task_dir: Path, llm: ChatOpenAI, force_update: bool = False) -> bool:
    """处理单个任务：读取 metadata.json，分类题目，更新标签。
    
    返回：是否成功处理
    """
    task_id = task_dir.name
    metadata_path = task_dir / "metadata.json"
    
    if not metadata_path.exists():
        log(f"任务 {task_id}: metadata.json 不存在，跳过", "WARN")
        return False
    
    try:
        # 读取 metadata.json
        with open(metadata_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)
        
        # 检查是否已有新标签和标题且不需要强制更新
        has_knowledge_tags = bool(metadata.get("knowledge_tags"))
        has_title = "title" in metadata and metadata.get("title", "").strip()
        
        if not force_update and has_knowledge_tags and has_title:
            log(f"任务 {task_id}: 已有知识标签和标题，跳过（使用 --force 强制更新）")
            return True
        
        # 提取题目
        question = metadata.get("question", "")
        if not question:
            log(f"任务 {task_id}: metadata.json 中没有 question 字段，跳过", "WARN")
            return False
        
        # 题目分析只负责判断是否为数学题和生成标题，知识标签由独立标签链路处理
        if (not has_knowledge_tags or not has_title) or force_update:
            log(f"任务 {task_id}: 开始分析题目（判断+标题）...")
            analysis_result = await analyze_question(question, llm)
            
            if analysis_result:
                if not analysis_result.get("is_math_problem", True):
                    log(f"任务 {task_id}: 判断结果 - 不是数学题，标记为 __NOT_MATH_QUESTION__", "WARN")
                    metadata["is_math_question"] = False
                    metadata["error"] = "__NOT_MATH_QUESTION__"
                else:
                    if analysis_result.get("title"):
                        metadata["title"] = analysis_result["title"]
                        # W1 P0-3：标题质量打标（约束校验重试后仍不通过 → low）
                        if analysis_result.get("title_quality"):
                            metadata["title_quality"] = analysis_result["title_quality"]
                        log(f"任务 {task_id}: 标题已生成: {analysis_result['title']}")
                    
                    try:
                        from knowledge_tag_injector import inject_knowledge_tags
                        knowledge_tags = await inject_knowledge_tags(question)
                        if knowledge_tags:
                            metadata["knowledge_tags"] = knowledge_tags
                            metadata["needs_tag_selection"] = False
                            log(f"任务 {task_id}: 知识标签已更新，知识域={knowledge_tags.get('version')}, 年级={knowledge_tags.get('grade')}, 章/单元={knowledge_tags.get('main_tag')}")
                        else:
                            metadata["needs_tag_selection"] = True
                            log(f"任务 {task_id}: 知识标签未识别，需手动选择", "WARN")
                    except Exception as tag_err:
                        metadata["needs_tag_selection"] = True
                        log(f"任务 {task_id}: 知识标签识别失败: {tag_err}", "WARN")
                    
                    metadata["is_math_question"] = True
            else:
                log(f"任务 {task_id}: 分析失败", "WARN")
                if not has_title:
                    metadata["title"] = question[:30] + ("..." if len(question) > 30 else "")
                    log(f"任务 {task_id}: 使用默认标题: {metadata['title']}")
        else:
            log(f"任务 {task_id}: 已有标签和标题，跳过分析")
        
        # 保存更新后的 metadata.json
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        
        log(f"任务 {task_id}: metadata.json 已更新")
        return True
        
    except Exception as e:
        log(f"任务 {task_id}: 处理失败: {str(e)}", "ERROR")
        import traceback
        traceback.print_exc()
        return False


async def main(force_update: bool = False):
    """主函数：遍历 storage 目录，为每个任务添加分类标签。"""
    log("=" * 60)
    log("开始为 storage 中的任务添加分类标签")
    log("=" * 60)
    
    if not storage_dir.exists():
        log(f"Storage 目录不存在: {storage_dir}", "ERROR")
        return
    
    # 初始化 LLM
    try:
        llm = get_llm_classifier()
        log("DeepSeek LLM 初始化成功")
    except Exception as e:
        log(f"初始化 LLM 失败: {str(e)}", "ERROR")
        return
    
    # 获取所有任务目录
    task_dirs = [d for d in storage_dir.iterdir() if d.is_dir()]
    total_tasks = len(task_dirs)
    
    log(f"找到 {total_tasks} 个任务目录")
    
    if total_tasks == 0:
        log("没有找到任何任务目录", "WARN")
        return
    
    # 处理每个任务
    success_count = 0
    skip_count = 0
    fail_count = 0
    
    for i, task_dir in enumerate(task_dirs, 1):
        log(f"\n[{i}/{total_tasks}] 处理任务: {task_dir.name}")
        
        result = await process_task(task_dir, llm, force_update)
        
        if result:
            success_count += 1
        else:
            # 检查是否是因为已有标签和标题而跳过
            metadata_path = task_dir / "metadata.json"
            if metadata_path.exists():
                try:
                    with open(metadata_path, "r", encoding="utf-8") as f:
                        metadata = json.load(f)
                    has_knowledge_tags = bool(metadata.get("knowledge_tags"))
                    has_title = "title" in metadata and metadata.get("title", "").strip()
                    if has_knowledge_tags and has_title and not force_update:
                        skip_count += 1
                        continue
                except:
                    pass
            fail_count += 1
        
        # 添加短暂延迟，避免 API 调用过于频繁
        if i < total_tasks:
            await asyncio.sleep(1)
    
    # 输出统计信息
    log("\n" + "=" * 60)
    log("处理完成！")
    log(f"总计: {total_tasks} 个任务")
    log(f"成功: {success_count} 个")
    log(f"跳过: {skip_count} 个（已有标签）")
    log(f"失败: {fail_count} 个")
    log("=" * 60)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="为 storage 中的任务添加分类标签")
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制更新已有标签的任务"
    )
    
    args = parser.parse_args()
    
    asyncio.run(main(force_update=args.force))

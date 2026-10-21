# -*- coding: utf-8 -*-
"""教学画像 ContentProfile（方案 2026-09-03 §3.3 核心中间产物）.

ContentProfile 是所有下游（动画 / 完整解答 / 封面 / 复用判定 / AI 助教）的
**唯一画像消费源**，由识别编排器在 recognize 结果之上构建：

    recognize（域/年级/章/标签）→ 教学画像 ContentProfile
        → PromptRouter 按 stage × domain 拼装分层提示词
        → [AnimationAgent ∥ SolutionAgent ∥ CoverAgent]（P2 起并行）

设计约定：
- 纯数据层：本模块不发起 LLM 调用、不依赖 AgentScope / 数据库，可离线单测；
- 「画像先行」：所有字段对下游透明，下游一律不回头重新解析题面；
- 字段结构对齐方案 §3.3（version/stage/domain/display_class/grade/tags/
  question_type/figure_info/visual_requirements/method_lock/confidence/engine）；
- method_lock（§5.5.0）与 figure_info（§6）在 P0 保留默认空值/占位，
  由 P2/P4 阶段填充，但 schema 与 to_dict/from_dict 一次性定型，避免下游反复改契约。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# ── 学段常量 ─────────────────────────────────────────────────────────────────
STAGE_PRIMARY = "primary_school"
STAGE_JUNIOR = "junior_high"

# 展示大类：决定走哪套知识域表达层提示词（提示词库目录名 domain_*）
DISPLAY_NUMBERS = "numbers"          # 数与式
DISPLAY_EQUATION = "equation"        # 方程与不等式
DISPLAY_FUNCTION = "function"        # 函数（独立层：坐标系/图/交点/面积/图象不等式）
DISPLAY_GEOMETRY = "geometry"        # 图形与几何
DISPLAY_STATISTICS = "statistics"    # 统计与概率
DISPLAY_CALCULATION = "calculation"  # 计算类兜底（未知/空域回退，路由到 domain_numbers）

# 知识域（标签体系 5 域，官方文案） → 展示大类
# 2026-09-03 拆分：原合并的「calculation」拆为 numbers / equation / function 三套独立提示词，
# 单独的「函数」题现在直接走 function 层（此前只有复合题小问才命中，是路由缺口）。
_DOMAIN_TO_DISPLAY_CLASS = {
    "数与式": DISPLAY_NUMBERS,
    "方程与不等式": DISPLAY_EQUATION,
    "函数": DISPLAY_FUNCTION,
    "图形与几何": DISPLAY_GEOMETRY,
    "统计与概率": DISPLAY_STATISTICS,
}

# 年级 → 学段映射（远程权威库 955 行 = 一上~九下 18 年级全学段）。
# 规则：一年级~五年级 → 小学；六年级~九年级 → 初中。
_GRADE_CHAR_TO_NUM = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}

# 题库常规年级别名
_GRADE_ALIAS = {
    "一年级上": "一上", "一年级下": "一下", "二年级上": "二上", "二年级下": "二下",
    "三年级上": "三上", "三年级下": "三下", "四年级上": "四上", "四年级下": "四下",
    "五年级上": "五上", "五年级下": "五下", "六年级上": "六上", "六年级下": "六下",
    "七年级上": "七上", "七年级下": "七下", "八年级上": "八上", "八年级下": "八下",
    "九年级上": "九上", "九年级下": "九下",
}

# 题型粗判规则（question_type 不命中时留空，由案例层按需不注入）。
# 注意：仅为「分层提示词路由」提供粗粒度信号，最终准确题型由识别结果驱动。
# 优先级经验：先放"结构性强、不易误伤"的规则（三角形/圆/全等…），
# 再放"关键词宽泛"的规则（如"角"类，避免"三角形"中的"角"字误命中）。
# 复合函数交点规则须置于"一次函数/反比例函数"通用规则之前（先匹配更具体的复合题型）。
_QUESTION_TYPE_RULES: list[tuple[str, list[str]]] = [
    ("反比例函数与一次函数交点", ["反比例函数", "一次函数", "交于", "交点"]),
    ("鸡兔同笼问题", ["鸡兔同笼"]),
    ("行程问题", ["相遇", "追及", "相向", "同向", "速度", "每小时", "千米/时", "米/分"]),
    ("工程问题", ["工程", "合作", "单独完成", "效率", "工作量"]),
    ("盈亏问题", ["盈亏", "恰好分完", "不够分"]),
    ("年龄问题", ["年龄"]),
    ("植树问题", ["植树", "间隔", "棵数"]),
    ("浓度问题", ["浓度", "盐水", "糖水", "百分"]),
    ("折扣利润问题", ["折扣", "原价", "售价", "利润", "成本价", "八折", "九折"]),
    ("全等三角形", ["全等", "≌", "对应边", "对应角"]),
    ("相似三角形", ["相似", "∽"]),
    ("三角形", ["三角形", "等腰", "等边", "底边", "腰"]),
    ("圆", ["圆", "半径", "直径", "圆周", "弧", "扇形", "π", "圆心"]),
    ("坐标系", ["坐标", "象限", "横坐标", "纵坐标", "有序数对"]),
    ("一次函数", ["一次函数", "y=kx", "斜率", "截距"]),
    ("二次函数", ["二次函数", "抛物线", "顶点", "开口方向"]),
    ("反比例函数", ["反比例函数", "y=k/x", "双曲线"]),
    ("图形面积", ["面积", "平方厘米", "平方分米", "平方米", "公顷"]),
    ("图形周长", ["周长", "围成"]),
    ("体积容积", ["体积", "容积", "立方厘米", "立方分米", "立方米"]),
    ("角的度量", ["角的度数", "量角器", "直角", "锐角", "钝角", "平角", "周角"]),
    ("平均数", ["平均数", "平均分", "均值"]),
    ("统计图表", ["条形", "折线图", "扇形图", "统计图", "频率", "组距"]),
    ("概率", ["概率", "可能性", "随机", "摸出", "掷"]),
    ("找规律", ["规律", "第n个", "数列", "递增", "递推"]),
    ("方程应用", ["列方程", "设未知数", "设x"]),
]


# 题型细分（画法模板 scene_pattern 命中用，2026-09-05 扩展）
# 说明：这些子类必须在 guess_question_type 的粗分关键词循环**之前**判定，
# 且彼此互斥（先船洞/再隧道/后桥类），命中即返回细分类，不再落入笼统"行程问题"。
# 判定用「主体词 + 通道词 + 移动词」成对/成群出现，且主体与通道之间允许
# 夹"一座长 1000 米"这类修饰语；无移动语义（仅提"火车""桥"）不误判。
_TUNNEL_WORDS = ("隧道", "山洞", "过隧道", "穿隧道", "进洞", "出洞")
_BRIDGE_WORDS = ("桥", "闸", "净空")
_MOVER_WORDS = ("通过", "穿过", "驶过", "驶入", "驶上", "驶出", "经过", "钻过",
                "完全通过", "全部通过", "过隧道", "过桥", "过桥洞", "进洞", "穿洞")

# 题型 → 画法模板 pattern_key（scene_patterns/50_pattern_{key}.md）
_QUESTION_TYPE_PATTERN_MAP: dict[str, str] = {
    "火车过隧道": "tunnel_pass",
    "火车过桥": "tunnel_pass",
    "汽车过桥": "tunnel_pass",
    "船过桥洞": "tunnel_pass",
    # 函数曲线族（2026-09 新增）：命中即注入 50_pattern_function_curve.md 画法硬规范
    "一次函数": "function_curve",
    "二次函数": "function_curve",
    "反比例函数": "function_curve",
    "反比例函数与一次函数交点": "function_curve",
    # 利润折扣题本质为二次函数最值，需曲线硬规范（其 question_type 命中"折扣利润问题"规则）
    "折扣利润问题": "function_curve",
}


def _has_any(text: str, words: tuple) -> bool:
    return any(w in text for w in words)


def _match_travel_subtype(text: str) -> str:
    """按细分规则判定通道/行程子题型；未命中返回 ''."""
    t = text or ""
    if len(t) < 4:
        return ""
    train = _has_any(t, ("火车", "列车", "货车"))
    car = _has_any(t, ("汽车", "卡车", "轿车", "大巴"))
    boat = _has_any(t, ("轮船", "货船", "小船", "船只"))
    tunnel = _has_any(t, _TUNNEL_WORDS)
    bridge = _has_any(t, _BRIDGE_WORDS)
    mover = _has_any(t, _MOVER_WORDS)
    if not mover:
        return ""
    # 优先级：船(桥洞/闸) → 火车过隧道 → 火车过桥 → 汽车过桥
    if boat and bridge:
        return "船过桥洞"
    if train and tunnel:
        return "火车过隧道"
    if train and bridge:
        return "火车过桥"
    if car and bridge:
        return "汽车过桥"
    return ""


def pattern_key_for_question_type(question_type: str) -> str:
    """题型 → 画法模板 key；无映射返回 ''. """
    return _QUESTION_TYPE_PATTERN_MAP.get(question_type or "", "")


def pattern_keys_for_profile(profile: Optional[dict]) -> list[str]:
    """从画像 dict 收集应注入的画法模板 key（主题型 + 复合题各小题题型，去重保序）.

    供 prompt_router（组装 System 注入）与 pipeline（Lint 专项检查）共用，
    避免两处各自解析画像字段造成口径漂移。
    """
    keys: list[str] = []
    if not profile:
        return keys

    def _append(qtype: str) -> None:
        key = pattern_key_for_question_type(qtype)
        if key and key not in keys:
            keys.append(key)

    _append(profile.get("question_type", ""))
    for part in profile.get("parts") or []:
        if isinstance(part, dict):
            _append(part.get("question_type", ""))
    return keys


def grade_to_stage(grade: str) -> str:
    """年级 → 学段（一上~五下 → 小学；六上~九下 → 初中）.

    归一化兼容：'七年级上'/'初一上' 等别名在进入前应尽量转 '七上' 形态；
    无法解析的年级返回 junior_high 兜底（存量识别结果以初中为主），并记 WARN。
    """
    if not grade:
        return STAGE_JUNIOR
    g = str(grade).strip()
    g = _GRADE_ALIAS.get(g, g)
    m = re.match(r"^([一二三四五六七八九])[上下]$", g)
    if not m:
        logger.warning("年级无法解析学段（按初中兜底）: %s", grade)
        return STAGE_JUNIOR
    num = _GRADE_CHAR_TO_NUM.get(m.group(1), 6)
    return STAGE_PRIMARY if num <= 5 else STAGE_JUNIOR


# 题面显式学段线索（方案 §13.8.1 守卫）：年级缺失/不可解析时先用题面精判，
# 避免小学题在标签为空时被 junior_high 兜底静默换成初中风格（style_key/motion_policy 全变）。
# 只认显式证据（"五年级""小学"等），不做模糊猜测；无证据返回 '' 由调用方保持原兜底。
_STAGE_HINT_PRIMARY_RE = re.compile(r"[一二三四五]\s*年级|小学")
_STAGE_HINT_JUNIOR_RE = re.compile(r"[六七八九]\s*年级|初一|初二|初三|初中")


def guess_stage_from_text(text: str) -> str:
    """从题面提取显式学段线索；无证据返回 ''."""
    t = text or ""
    if _STAGE_HINT_PRIMARY_RE.search(t):
        return STAGE_PRIMARY
    if _STAGE_HINT_JUNIOR_RE.search(t):
        return STAGE_JUNIOR
    return ""


def domain_to_display_class(domain: str) -> str:
    """知识域 → 展示大类（用于提示词库路由，未知域记 WARN 并回退计算类）. """
    if not domain:
        return DISPLAY_CALCULATION
    cls = _DOMAIN_TO_DISPLAY_CLASS.get(str(domain).strip())
    if not cls:
        logger.warning("未知知识域，提示词按计算类兜底: %s", domain)
        return DISPLAY_CALCULATION
    return cls


def guess_question_type(question: str, tag: str = "") -> str:
    """题型粗判：优先通道/行程细分子类，其次标签名命中，再次题干关键词命中；都不中返回 ''."""
    text = f"{question or ''} {tag or ''}"
    # ① 通道/行程细分子类（火车过隧道/过桥/船过桥洞）——必须在粗分关键词前判定
    subtype = _match_travel_subtype(text)
    if subtype:
        return subtype
    # ② 粗分关键词（原逻辑不变）
    for qtype, keywords in _QUESTION_TYPE_RULES:
        for kw in keywords:
            if kw in text:
                return qtype
    return ""


# ── 复合多小题识别（2026-09-03 扩展） ────────────────────────────────────────
# 支持的小题标记：① （1）/（2）  ② (1)/(2)  ③ 1. / 1、 / 1．  ④ 第1问 / 第(1)问
# 设计约束：纯数字（如"有12颗糖"）、坐标"(2, 4)"均不得误命中——必须带括号/
# 标点/「第..问」锚点才识别为小题起点。
_PART_MARKER_RE = re.compile(
    r"(?m)"
    r"（\s*(\d{1,2})\s*）"            # ① 全角括号 （1）
    r"|\(\s*(\d{1,2})\s*\)"           # ② 半角括号 (1)
    r"|(\d{1,2})[.、．]"              # ③ 数字+标点 1. / 1、 / 1．
    r"|第\s*(\d{1,2})\s*问"           # ④ 第1问
)


def _part_number(m: "re.Match") -> str:
    return (m.group(1) or m.group(2) or m.group(3) or m.group(4) or "").strip()


def _guess_part_domain(text: str, fallback_domain: str = "") -> str:
    """对单个小题粗判知识域（5 域官方文案），命中不到回退主域。"""
    if re.search(r"函数|解析式|图象|双曲线|交点|坐标轴|象限", text):
        return "函数"
    if re.search(r"面积|三角形|边长|周长|角度|圆|辅助线|图形|坐标", text):
        return "图形与几何"
    if re.search(r"概率|统计|频率|平均数|方差|数据", text):
        return "统计与概率"
    if re.search(r"方程|不等式|因式|代数式|整式", text):
        return "方程与不等式"
    return fallback_domain or "数与式"


def _part_display_class(domain: str) -> str:
    """小题展示大类：函数域单独走 function 层，其余复用既有映射（向后兼容）。"""
    if domain == "函数":
        return DISPLAY_FUNCTION
    return domain_to_display_class(domain)


def detect_composite_parts(question: str, fallback_domain: str = "") -> list[dict]:
    """把复合多小题题面切成结构化 parts（每问含 domain/display_class/question_type）。

    仅当能切出 >=2 个有意义小题时返回非空列表；否则返回 []（视为非复合）。
    parts 字段：{label, text, domain, display_class, question_type}。
    """
    if not question or not question.strip():
        return []
    matches = list(_PART_MARKER_RE.finditer(question))
    if len(matches) < 2:
        return []
    parts: list[dict] = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(question)
        label = f"（{_part_number(m)}）"
        text = question[start:end].strip()
        if len(text) < 4:  # 过短（仅标号）视为噪声，跳过
            continue
        domain = _guess_part_domain(text, fallback_domain)
        parts.append({
            "label": label,
            "text": text,
            "domain": domain,
            "display_class": _part_display_class(domain),
            "question_type": guess_question_type(text, domain),
        })
    return parts


def _distinct_display_classes(parts: list[dict]) -> list[str]:
    """parts 去重后的展示大类列表（保序），驱动多域提示词注入。"""
    seen: list[str] = []
    for p in parts:
        dc = p.get("display_class") or ""
        if dc and dc not in seen:
            seen.append(dc)
    return seen


def _default_visual_requirements(stage: str, display_class: str) -> dict:
    """按学段×展示大类产出默认表现要求（§3.3 visual_requirements）.

    P1 起由提示词库 router_config.json 的 style_key 细化覆盖；
    此处提供与分层提示词一致的缺省口径，保证没有画像时前端仍能稳定渲染。
    """
    style_key = f"{'primary' if stage == STAGE_PRIMARY else 'junior'}_{display_class}"
    if stage == STAGE_PRIMARY:
        return {
            "style_key": style_key,
            "steps_min": 3,
            "steps_max": 5,
            "motion_policy": "playful",
            "must_show": [],
        }
    if display_class == DISPLAY_GEOMETRY:
        return {
            "style_key": style_key,
            "steps_min": 5,
            "steps_max": 8,
            "motion_policy": "answer_first",
            "must_show": ["几何标注规范", "辅助线分层"],
        }
    if display_class == DISPLAY_STATISTICS:
        return {
            "style_key": style_key,
            "steps_min": 5,
            "steps_max": 7,
            "motion_policy": "answer_first",
            "must_show": ["数据忠于题干"],
        }
    return {
        "style_key": style_key,
        "steps_min": 5,
        "steps_max": 7,
        "motion_policy": "answer_first",
        "must_show": [],
    }


def _to_jsonable(value):
    """深拷贝为可 JSON 序列化结构（dict/list 原样，其余转基础类型）。"""
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


@dataclass
class ContentProfile:
    """教学画像：题目识别信息 → 下游各产物共享的单一事实源. """

    version: int = 1
    stage: str = STAGE_JUNIOR                     # primary_school | junior_high
    domain: str = ""                              # 知识域（5 域官方文案）
    display_class: str = DISPLAY_CALCULATION      # 计算类/几何类/统计概率类（路由键）
    grade: str = ""                               # 年级（七上…）
    tags: dict = field(default_factory=lambda: {
        "main_tag": "", "sub_tags": [], "second_tag": None,
    })
    question_type: str = ""                       # 识别出的题型（决定提示词案例层）
    figure_info: dict = field(default_factory=lambda: {
        "has_figure": False, "figures": [],
    })
    visual_requirements: dict = field(default_factory=dict)
    # §5.5.0 解法方法锁定：P0 阶段默认空（未锁定），P2 由方法库/LLM 填充；
    # 空表示"未做方法决策"，下游生成仍可自由选法（向后兼容存量流程）。
    method_lock: Optional[dict] = None
    is_math_problem: bool = True
    confidence: float = 0.0
    engine: str = ""                              # agent | legacy（识别引擎来源）
    # 复合多小题（2026-09-03 扩展）；非复合题保持默认空值，向下兼容存量流程
    is_composite: bool = False                   # 是否复合多小题
    parts: list = field(default_factory=list)    # [{label,text,domain,display_class,question_type}]
    domains: list = field(default_factory=list)  # parts 去重后的展示大类（驱动多域提示词注入）

    def __post_init__(self) -> None:
        if not self.display_class and self.domain:
            self.display_class = domain_to_display_class(self.domain)
        if not self.stage and self.grade:
            self.stage = grade_to_stage(self.grade)
        if not self.visual_requirements:
            self.visual_requirements = _default_visual_requirements(self.stage, self.display_class)

    @property
    def style_key(self) -> str:
        return (self.visual_requirements or {}).get("style_key", "")

    def to_dict(self) -> dict:
        return _to_jsonable({
            "version": self.version,
            "stage": self.stage,
            "domain": self.domain,
            "display_class": self.display_class,
            "grade": self.grade,
            "tags": self.tags,
            "question_type": self.question_type,
            "figure_info": self.figure_info,
            "visual_requirements": self.visual_requirements,
            "method_lock": self.method_lock,
            "is_math_problem": self.is_math_problem,
            "confidence": round(float(self.confidence or 0), 4),
            "engine": self.engine,
            "is_composite": self.is_composite,
            "parts": self.parts,
            "domains": self.domains,
        })

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "ContentProfile":
        data = data or {}
        try:
            return cls(
                version=int(data.get("version", 1)),
                stage=data.get("stage") or STAGE_JUNIOR,
                domain=data.get("domain", "") or "",
                display_class=data.get("display_class", "") or "",
                grade=data.get("grade", "") or "",
                tags=data.get("tags") or {},
                question_type=data.get("question_type", "") or "",
                figure_info=data.get("figure_info") or {"has_figure": False, "figures": []},
                visual_requirements=data.get("visual_requirements") or {},
                method_lock=data.get("method_lock"),
                is_math_problem=bool(data.get("is_math_problem", True)),
                confidence=float(data.get("confidence", 0) or 0),
                engine=data.get("engine", "") or "",
                is_composite=bool(data.get("is_composite", False)),
                parts=data.get("parts") or [],
                domains=data.get("domains") or [],
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("ContentProfile.from_dict 解析失败，返回空画像: %s", exc)
            return cls()


# T1 figure_info 数据化（xsyy-3 阶段一，2026-09-14）：确定性插图判定，零 LLM 成本。
# 判定口径：仅当题目确实带图（has_image=True）且存在几何/图形证据时才视为"含插图"——
# 纯文字题提到三角形不等于有配图。视觉精判（bbox 裁剪）属阶段三（T3）。
_FIGURE_CHART_WORDS = ("统计图", "条形统计", "折线统计", "扇形统计", "条形图", "折线图")
_FIGURE_2D_WORDS = (
    "三角形", "正方形", "长方形", "平行四边形", "梯形", "菱形",
    "圆形", "扇形", "多边形", "半圆",
)
_FIGURE_3D_WORDS = ("正方体", "长方体", "圆柱", "圆锥",)
_FIGURE_HINT_WORDS = (
    "如图", "下图", "上图", "图中", "右图", "左图",
    "阴影", "涂色", "线段图", "示意图", "方格", "格子", "剪拼", "折叠",
)


def detect_figure_info(
    question: str,
    *,
    has_image: bool = False,
    display_class: str = "",
) -> dict:
    """按题面线索 + 是否带图，确定性判定题目插图信息（figure_info 真实产出）.

    Args:
        question: 干净题面
        has_image: 该题是否随附图片（上传/裁剪后）
        display_class: 画像展示大类（"geometry" 为强信号）

    Returns:
        无图/无证据：{"has_figure": False, "figures": []}（与既有结构完全一致，向后兼容）；
        命中：{"has_figure": True, "figure_kind": "geometry_2d"|"geometry_3d"|"chart"|"diagram",
        "figures": []} — figures 留空，阶段三（T3 裁剪）填充文件路径。
    """
    text = str(question or "")
    no_figure = {"has_figure": False, "figures": []}
    if not has_image:
        return no_figure

    if display_class == "geometry" or _has_any(text, _FIGURE_2D_WORDS):
        kind = "geometry_2d"
    elif _has_any(text, _FIGURE_3D_WORDS):
        kind = "geometry_3d"
    elif _has_any(text, _FIGURE_CHART_WORDS):
        kind = "chart"
    elif _has_any(text, _FIGURE_HINT_WORDS):
        kind = "diagram"
    else:
        return no_figure
    return {"has_figure": True, "figure_kind": kind, "figures": []}


def build_content_profile(
    question: str,
    primary: Optional[dict],
    *,
    second: Optional[dict] = None,
    meta: Optional[dict] = None,
    title: str = "",
    has_image: bool = False,
) -> ContentProfile:
    """从识别结果构建 ContentProfile（P0 统一入口）.

    Args:
        question: 干净题面（识别链路已剥离纠错要求后的文本）
        primary: 主标签组。两种兼容形态：
            - legacy / agent mapped：{"version": 知识域, "grade": 年级,
              "main_tag": 章/单元, "sub_tags": [知识点标签...]}
            - agent outcome.knowledge_tags：{"domain": 知识域, "grade": 年级,
              "main_tag": 章, "sub_tags": [...], ...}
            两者均按 version|domain / main_tag / grade 归一。
        second: 第二标签组（结构同 primary，可为 None）
        meta: 识别元信息（engine/action/confidence 等，可选）
        title: 题目标题（可选，参与题型粗判）
        has_image: 题目是否随附图片（T1 起参与 figure_info 判定，默认 False 保持旧行为）
    """
    del title  # 预留：后续可参与题型判定
    primary = primary or {}
    meta = meta or {}

    domain = primary.get("version") or primary.get("domain") or ""
    grade = primary.get("grade") or ""
    main_tag = primary.get("main_tag") or ""
    sub_tags = primary.get("sub_tags") or []
    if isinstance(sub_tags, str):
        sub_tags = [sub_tags]

    stage = grade_to_stage(grade)
    # §13.8.1 守卫：年级缺失或不可解析时，不得静默用 junior_high 兜底驱动画法——
    # 先按题面显式学段线索精判（如"五年级""小学"），仍无证据才保持原兜底。
    _g_norm = _GRADE_ALIAS.get(str(grade or "").strip(), str(grade or "").strip())
    if not re.match(r"^[一二三四五六七八九][上下]$", _g_norm):
        _guessed = guess_stage_from_text(question)
        if _guessed:
            if _guessed != stage:
                logger.info(
                    "年级缺失/不可解析（%r），按题面线索判定学段: %s（原兜底 %s）",
                    grade, _guessed, stage,
                )
            stage = _guessed
    display_class = domain_to_display_class(domain)
    main_tag_text = main_tag or ""
    tag_text = " ".join(str(s) for s in sub_tags) or main_tag_text

    profile = ContentProfile(
        stage=stage,
        domain=domain,
        display_class=display_class,
        grade=grade,
        tags={
            "main_tag": main_tag_text,
            "sub_tags": list(sub_tags),
            "second_tag": _to_jsonable(second) if second else None,
        },
        question_type=guess_question_type(question, tag_text),
        figure_info=detect_figure_info(question, has_image=has_image, display_class=display_class),
        visual_requirements=_default_visual_requirements(stage, display_class),
        method_lock=None,  # 动画/解答分离已取消（2026-09-03 用户拍板），恒占位不填充
        is_math_problem=True,
        confidence=float(meta.get("confidence", 0) or 0),
        engine=meta.get("engine") or meta.get("source") or "",
    )

    # 复合多小题识别（2026-09-03）：能切出 >=2 个有意义小题则标记 composite，
    # 并记录每问 domain 与去重后的展示大类（domains）供 PromptRouter 多域注入。
    parts = detect_composite_parts(question, domain)
    if parts:
        profile.is_composite = True
        profile.parts = parts
        profile.domains = _distinct_display_classes(parts)

    return profile

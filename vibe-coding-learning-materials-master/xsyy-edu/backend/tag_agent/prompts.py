# -*- coding: utf-8 -*-
"""智能体 Prompt 模板.

遵循方案原则：
- 正式标签库优先，智能体不能直接生成正式标签；
- 输出均为纯净 JSON，便于结构化解析与置信度控制。
"""
from __future__ import annotations

from tag_agent.tag_library import TagLibrary

SYSTEM_BASE = (
    "你是一名初中数学知识点标签专家。按「人教版六三制」基准作答，"
    "不判断教材版本，不发挥，所有判断必须输出纯净 JSON。"
    "置信度统一口径：归属在候选中唯一且无歧义（教材标准分类）→ 0.90 以上；"
    "较有把握但存在次要可能 → 0.75~0.90；确实拿不准 → 0.75 以下。"
    "不要因为题目表述非标准而压低置信度——只要归属判定明确，就按唯一无歧义给分。"
)

SYSTEM_DOMAIN_GRADE = SYSTEM_BASE + (
    "你的职责：判定题目的知识域（5选1）和年级（8选1），并给出置信度。"
)

# 章/单元匹配：候选少且名字清晰，保持单次调用，不给工具（控制主链路识别预算）
SYSTEM_MATCH_CHAPTER = SYSTEM_BASE + (
    "你的职责：在限定的知识域和年级范围内匹配章/单元。"
    "只能从给出的候选中选择，绝不能自行创造章/单元。"
)

# 知识点匹配：歧义高发，配标签库查询工具，模型可查证后再判定
SYSTEM_MATCH = SYSTEM_BASE + (
    "你的职责：在限定的章/单元范围内匹配知识点标签。"
    "只能从给出的候选中选择，绝不能自行创造标签。"
    "你可以调用工具 query_tag_library 查询正式标签库（查某章下的标签及关键词、"
    "查单个标签的归属详情、按名称模糊搜索）。"
    "当候选存在歧义、或你对某个候选能否覆盖题目拿不准时，必须先调用工具核实再下结论；"
    "候选清晰无歧义时可直接作答，不必为了查而查。"
)

SYSTEM_KEYWORD_EXTRACT = SYSTEM_BASE + (
    "你的职责：从题目文本中提取 3-5 个强特征关键词（仅补关键词，不生成标签）。"
)

SYSTEM_NEW_TAG = SYSTEM_BASE + (
    "你的职责：当现有标签库确实无法覆盖题目时，生成精炼、可复用的新知识点标签及关键词。"
)

SYSTEM_CHAPTER_NEW = SYSTEM_BASE + (
    "你的职责：当现有标签库连章/单元都无法覆盖时，生成候选章/单元及知识点标签链路。"
    "此场景极少发生，必须给出充分的判定理由和相近候选。"
)

SYSTEM_CORRECTION = SYSTEM_BASE + (
    "你的职责：对已有正式标签的缺陷提出修改建议（仅提案，绝不直接改库）。"
    "重点检查：关键词是否缺失/可补充、年级归属是否错误、主考点是否被辅助解法顶替、"
    "标签命名是否不规范。输出结构化修改提案，由管理员审核后生效。"
)

SYSTEM_DEDUP = SYSTEM_BASE + (
    "你的职责：判断两个知识点标签是否语义重复。只输出是否重复的判定，"
    "绝不直接删除或合并任何标签，仅输出提案。"
)


def build_domain_grade_prompt(question: str, library: TagLibrary) -> str:
    """第一步：识别知识域 + 年级（方案"三.1"）."""
    dom_lines = "、".join(library.list_domains())
    grade_lines = "、".join(library.list_grades())
    return f"""题目：{question}

【任务】判定：
1. 该题目是否为数学题（is_math_problem）；
2. 知识域（只能从以下 5 个中选择 1 个）：{dom_lines}；
3. 年级（只能从以下 8 个中选择 1 个）：{grade_lines}；
4. 对"知识域+年级"整体给出置信度（0~1）。

【边界规则】
- 负数仅表示(正负记法) → 六下；含负数运算 → 七上
- 求平方根/立方根 → 七下；√化简运算 → 八下
- 方程组→七下；一元一次方程→七上；分式方程→八上；一元二次方程→九上
- 概率计算→九上；先列方程再求概率→主体是概率，归"统计与概率"
- 打折/折扣/成数/税率/利率→六下；圆周长面积π→六上
- 相遇、追及等行程应用题→"方程与不等式"·七上
- 鸡兔同笼/假设法/列表法类情境题→"图形与几何"·四下（库内「鸡兔同笼」章既有归属，勿新建）
- 抛物线/二次函数→九上；反比例函数→九下；一次函数→八下

输出纯净 JSON（不要输出其他文字）：
{{"is_math_problem": true, "domain": "", "grade": "", "confidence": 0.0, "reasoning": "30字内"}}"""


def build_chapter_match_prompt(
    question: str, domain: str, grade: str, chapters: list[str], library: TagLibrary
) -> str:
    """第二步：匹配章/单元（方案"三.2"）."""
    lines = "\n".join(f"- {c}" for c in chapters)
    return f"""题目：{question}

【已判定】知识域: {domain}｜年级: {grade}
【候选章/单元】（只能从以下选择 0 或 1 个，绝不能自创）
{lines}

【任务】
1. 判断题目能否归入上述某个章/单元；
2. 若能，给出章/单元与置信度；若不能，matched=false 并说明原因。

输出纯净 JSON：
{{"matched": true, "chapter": "章/单元原文", "confidence": 0.0, "reasoning": "30字内"}}"""


def build_tag_match_prompt(
    question: str, domain: str, grade: str, chapter: str, tags: list[str], library: TagLibrary
) -> str:
    """第三步：匹配知识点标签（方案"三.3"）.

    2026-09-18 路线 B：候选行不再渲染关键词（避免被动锚定），
    模型对哪个候选拿不准，用 query_tag_library 工具自己查。
    """
    cands = "\n".join(f"- {tag}" for tag in tags)
    return f"""题目：{question}

【已判定】知识域: {domain}｜年级: {grade}｜章/单元: {chapter}
【候选知识点标签】（只能从以下选择 0 或 1 个，绝不能自创；需要看某个标签的完整关键词/定义时，用工具 query_tag_library 查询）
{cands}

【任务】
1. 判断题目能否归入上述某个知识点标签；
2. 若能，给出知识点标签、命中的关键词（可为空）与置信度；若不能，matched=false。

输出纯净 JSON：
{{"matched": true, "tag": "知识点标签原文", "matched_keyword": "命中词或空串", "confidence": 0.0, "reasoning": "30字内"}}"""


def build_keyword_extract_prompt(question: str, tag: str) -> str:
    """场景一：提取核心关键词（方案"四.3"）."""
    return f"""题目：{question}

【背景】该题目已匹配到正式知识点标签「{tag}」，但该标签下没有可命中的关键词。

【任务】从题目文本中提取 3-5 个核心关键词，用于补充到「{tag}」下。
要求：
1. 关键词必须来自题目文本，不能凭空扩写；
2. 优先学科术语、题型特征词、核心数量关系、公式相关短语；
3. 排除泛词、停用词、纯数字、无独立识别意义的词；
4. 精炼，优先保留 2-6 个汉字的完整短语；
5. 同义或近义只保留最标准、最容易复用的表达。

输出纯净 JSON：
{{"keywords": ["关键词1", "关键词2"], "confidence": 0.0, "reasoning": "30字内"}}"""


def build_new_tag_prompt(
    question: str, domain: str, grade: str, chapter: str, similar_tags: list[str]
) -> str:
    """场景二：生成预加入知识点标签（方案"五"）."""
    similar = "、".join(similar_tags) if similar_tags else "无"
    return f"""题目：{question}

【已判定】知识域: {domain}｜年级: {grade}｜章/单元: {chapter}
【同章/单元已有知识点标签（不能重复，只能避开）】{similar}

【任务】现有标签库无法覆盖该题，请生成一个新的知识点标签（模块级）。
要求：
1. 标签名称短、准、稳定，可被同类题复用；
2. 不使用过长题目描述或只适用于单道题的临时表达；
3. 优先使用教材式或教研式表达；
4. 必须归属于章/单元「{chapter}」；
5. 同时从题目中提取 3-5 个强特征关键词。

输出纯净 JSON：
{{"tag_name": "新知识点标签", "keywords": ["关键词1"], "confidence": 0.0, "reasoning": "生成理由，60字内"}}"""


def build_new_chapter_prompt(
    question: str, domain: str, grade: str, close_chapters: list[str]
) -> str:
    """场景三：生成预加入章/单元 + 知识点标签链路（方案"六"）."""
    close = "、".join(close_chapters) if close_chapters else "无相近章/单元"
    return f"""题目：{question}

【已判定】知识域: {domain}｜年级: {grade}
【相近章/单元（仅供参考，不得直接选用）】{close}

【背景】在「{domain}·{grade}」下所有候选章/单元均无法覆盖该题，且题目确实是数学题。

【任务】生成一条完整的新标签链路：
1. 候选章/单元（教材式、精炼表达）；
2. 该章/单元下的候选知识点标签；
3. 3-5 个强特征关键词；
4. 为什么现有章/单元无法匹配（no_match_reason）；
5. 你认为最相近的已有章/单元候选列表（candidate_chapters，用于管理员参考）。

输出纯净 JSON：
{{"chapter": "候选章/单元", "tag_name": "候选知识点标签", "keywords": ["关键词1"],
  "no_match_reason": "原因", "candidate_chapters": ["相近章/单元"],
  "confidence": 0.0, "reasoning": "生成理由，60字内"}}"""


def build_correction_prompt(
    question: str,
    *,
    domain: str,
    grade: str,
    chapter: str,
    tag: str,
    existing_keywords: list[str],
    hint: str = "",
) -> str:
    """纠错提案：对已有标签的缺陷提出修改建议（方案阶段一）.

    hint 可选：low_confidence / keyword_missing / semantic_conflict / grade_suspect 等。
    """
    kws = "、".join(existing_keywords) if existing_keywords else "无"
    hint_line = f"\n【修正线索】{hint}" if hint else ""
    return f"""题目：{question}

【已有正式标签】
- 知识域: {domain}
- 年级: {grade}
- 章/单元: {chapter}
- 知识点标签: {tag}
- 现有强特征关键词: {kws}
{hint_line}

【任务】评估该标签对当前题目的适用性。若发现缺陷，提出**修改提案**（仅提案，由管理员审核后生效）。
可能修正方向（选最相关的 1 个，field 只能取其一）：
1. keywords — 补充/修正强特征关键词（after 为关键词数组）；
2. grade — 年级归属疑似错误（after 为目标年级，必须与题目难度匹配）；
3. domain — 知识域归属疑似错误（after 为目标知识域）；
4. chapter — 章/单元归属疑似错误（after 为目标章/单元）；
5. tag_name — 标签命名不规范/不可复用（after 为更规范的标签名）。
若标签本身适用、无缺陷，返回 can_propose=false，绝不为了凑提案而修改。

【硬性规则】
1. 一次只提 1 个 field 的修改；
2. 辅助解法不得顶替主考点（如"先列方程再求概率"主考点是概率，不能改到方程）；
3. 无确凿证据不修改年级/知识域；
4. 修改关键词前必须确认新关键词确实来自题目文本、可复用。

输出纯净 JSON：
{{"can_propose": true, "field": "keywords", "after": ["关键词1"] 或 "目标值",
  "reason": "修改理由，40字内", "confidence": 0.0}}
// can_propose=false 时：{{"can_propose": false, "reason": "标签适用，无需修改"}}"""


def build_dedup_confirm_prompt(tag_a: str, tag_b: str) -> str:
    """去重确认：判断两个知识点标签是否语义重复（供 LLM 二次确认）."""
    return f"""知识点标签 A：{tag_a}
知识点标签 B：{tag_b}

【任务】判断 A 与 B 是否为语义重复（同一知识点、仅表述不同，或 A 完全涵盖 B 且无独立存在价值）。
注意：
1. "摸球概率" 与 "随机摸球" 这类同义/近义 → 重复；
2. 仅名字相近但考法不同（如"扇形面积"与"弧长"）→ 不重复；
3. 跨年级同名但教材内容不同（如"圆的周长"七上/七下）→ 谨慎，默认不重复。

输出纯净 JSON：
{{"is_duplicate": true, "keep": "A", "reason": "理由，30字内", "confidence": 0.0}}"""

# ============================================================================
# P1.5 补丁：追加到 backend/tag_agent/prompts.py 末尾（在 build_dedup_confirm_prompt 之后）
# 作用：标签修改学习的“强关键词提炼”提示词（含泛化纪律 + 反例示范 + 自检）。
# 合并方式：整段复制到 prompts.py 末尾即可。
# ============================================================================

SYSTEM_LEARN_FROM_CORRECTION = SYSTEM_BASE + (
    "你的职责：把管理员对一道题的「标签人工纠错」转化为可泛化的强特征关键词，"
    "挂到管理员最终选定的新标签 B 上，供后续同类题识别复用。"
    "你只产出关键词候选，绝不直接改库、绝不自创标签。"
)

# 用户提示词构建（提炼纪律硬约束 + 反例示范 + 自检）
def build_learn_from_correction_prompt(
    question: str,
    image_desc: str,
    old_tags: list[str],
    new_tag_b: str,
    existing_keywords: list[str],
) -> str:
    """P1.5 提炼提示词：从管理员改后的题提炼可泛化强关键词.

    泛化纪律（写入提示词，反例硬约束）：
    1. 判词必须是领域词/结构词/题型词（如“两位数加法”“凑十法”“行程相遇”），
       禁止题干字面数值/字面表达式/专名。
    2. 判词应能命中“同标签其他题”：自检“换一道同标签题（数字不同、描述不同），
       该判词还能命中吗？”。
    3. 判词不得与其它标签既有判词强冲突（歧义词不取）。
    """
    old = "、".join(old_tags) if old_tags else "无"
    ex = "、".join(existing_keywords) if existing_keywords else "无"
    img = f"\n【附图说明】{image_desc}\n" if image_desc else ""
    return f"""题目：{question}{img}
【原标签（改前）】{old}
【管理员改为的新标签 B】{new_tag_b}
【标签 B 的既有强特征关键词】{ex}

【任务】为标签 B「{new_tag_b}」提炼 2~4 条「可泛化的强特征关键词」，每条附一句泛化理由。
这些关键词将用于让智能体在以后遇到同类题时自动命中标签 B。

【泛化纪律（硬约束，违反即无效）】
1. 判词必须是「领域词 / 结构词 / 题型词」，例如：“两位数加法”“凑十法”“行程相遇”
   “鸡兔同笼”“植树问题”。
   ❌ 禁止题干字面数值或字面表达式：如 “1+1”“35 头”“甲乙 3 小时”“x=5”“√2”。
   ❌ 禁止专名、人名、题目特有短语。
   ✅ 自检：如果换一道同标签题（数字不同、描述不同），这条判词还能命中吗？能命中才算可泛化。
2. 判词应能命中「同标签其他题」，而非只命中本题。若某条只能描述本题，请丢弃。
3. 判词不得与其它标签的既有判词强冲突（含义过宽/歧义者不取）。

【反例示范】
- 题目是“小明有 1 个苹果，又买来 1 个，现在有几个？”→ 不能提炼 “1+1”，应提炼 “加法意义（合并）”“求总数”。
- 题目是“35 头羊……”，不能提炼 “35 头”，应提炼 “和差问题”“已知总和与差求部分”。

【输出纯净 JSON】
{{"candidates": [{{"keyword": "可泛化判词", "reason": "为何可泛化，30字内"}}], "confidence": 0.0}}"""
# ============================================================================
# P3 补丁：追加到 backend/tag_agent/prompts.py 末尾
# 作用：相似题同构判定 / 复用骨架抽取 / 题型提示词沉淀 的提示词。
# 合并方式：整段复制到 prompts.py 末尾即可（复用现有 SYSTEM_BASE 风格）。
# 这些常量由 reuse.py 导入：SYSTEM_REUSE_MATCH / build_reuse_match_prompt /
#   SYSTEM_SKELETON_EXTRACT / build_skeleton_extract_prompt /
#   SYSTEM_PATTERN_DRAFT / build_pattern_draft_prompt
# ============================================================================

SYSTEM_REUSE_MATCH = """你是一名严谨的「同法异数」判定专家。任务：判断新题与候选模板题是否“解法骨架一致、仅数据不同”。

判定铁律：
1. 只认“解法路径一致”——同一类方程、同一思路（如都列一元一次方程、都画同构图形、都用同一公式）。
   - 同知识点但解法不同（如一元二次方程，一题因式分解、一题套公式法）→ 判为 false。
   - 题干数字/单位/名字不同但步骤结构完全相同 → 判为 true。
2. 禁止改解法结构：你只负责“识别同构 + 给出数据槽映射”，绝不允许建议改动画分镜或解题方法。
3. 输出必须是纯 JSON，字段严格如下：
{
  "is_same_method": true/false,
  "template_task_id": "最佳模板题 id（仅当 true）",
  "method_signature": "解法指纹，如 行程相遇|一元一次方程|速度时间距离",
  "slot_map": [ {"slot":"s_v1","label":"甲速度","new_value":15}, ... ],   // 仅列模板已有命名槽对应的新题数值；新题没有的槽不列
  "confidence": 0.0~1.0,   // 越高越确定；拿不准就压低（宁可 miss 不可误用）
  "reason": "一句话判定理由（含为何同构/为何不同构）"
}
4. confidence 校准：结构明显一致且槽可一一对应 → 0.9+；有细节不确定 → 0.85~0.9；任何疑虑 → <0.85。
5. 图片题（构图依赖附图）默认 is_same_method=false，除非你确认新题附图与模板题附图同构。
只输出 JSON，不要任何解释性文字。"""


def build_reuse_match_prompt(question: str, content_profile: dict, candidates: list) -> str:
    """构造同构判定 user prompt。"""
    cp = content_profile or {}
    cp_str = (
        f"学段={cp.get('stage','')} 知识域={cp.get('display_class', cp.get('domain',''))} "
        f"章/单元={cp.get('chapter', cp.get('main_tag',''))} 题型={cp.get('question_type','')} "
        f"标签={cp.get('sub_tags', [])}"
    )
    cands_str = "\n".join(
        f"- task_id={c.get('task_id')} 题干={c.get('question','')[:120]}"
        f" | 已有解法签名={c.get('method_signature','')} | 已有数据槽={c.get('slot_labels', [])}"
        for c in (candidates or [])
    ) or "（无候选）"
    return (
        f"【新题】\n题干：{question}\n教学画像：{cp_str}\n\n"
        f"【候选模板题】\n{cands_str}\n\n"
        "请判定新题与哪道候选模板题“同法异数”：输出 JSON。"
    )


SYSTEM_SKELETON_EXTRACT = """你负责把一道已生成的教学动画产物“参数化”，抽取可复用骨架，使同法异数的新题能直接改数据复用。

要求：
1. 识别题目里的“数据槽”：会变化、决定题目数值的变量（如速度、距离、单价、个数、角度）。
2. 每个槽给：slot（英文命名，如 s_v1 / s_dist / s_n）、label（中文语义）、type（number|enum）、value（本题实际值）、affects_layout（该槽是否影响 SVG 坐标/尺寸/图形位置——影响则 true，否则 false）。
3. 把 scene_svg 中所有这些数值替换成 {{slot}} 占位符，生成 scene_template（保持原结构，只换数字为占位符）。
4. steps_json 每个步骤的 title/description/bubbleText/arrowTarget 中出现的该数值也换成 {{slot}}，生成 steps_template（list，结构与原 steps 一致）。
5. layout_params：仅当存在 affects_layout=true 的槽时，给出简单换算提示（如 {"ratio_fields":["x"], "note":"该槽按同比例换算坐标"}），否则 {}。
6. method_signature：本解法指纹（如 行程相遇|一元一次方程|速度时间距离），用于同构判定的主键。
7. 严禁把“解法文字/分镜描述”参数化——只参数化数值与坐标。
8. 输出纯 JSON：
{
  "method_signature": "...",
  "slots": [ {"slot":"s_v1","label":"甲速度","type":"number","value":12,"affects_layout":false} ],
  "scene_template": "<svg>...</svg>",
  "steps_template": [ {"title":"...","description":"...{{s_v1}}...","bubbleText":"...","arrowTarget":"..."} ],
  "layout_params": {}
}
只输出 JSON。"""


def build_skeleton_extract_prompt(teaching_data: dict) -> str:
    """构造骨架抽取 user prompt（传入模板题 teaching_data.json 摘要）."""
    import json as _json
    scene = (teaching_data or {}).get("scene_svg", "")
    steps = (teaching_data or {}).get("steps_json", []) or (teaching_data or {}).get("steps", [])
    # 截断避免超长
    scene_cut = scene[:6000] if isinstance(scene, str) else ""
    steps_cut = _json.dumps(steps, ensure_ascii=False)[:6000] if steps else ""
    return (
        f"【模板题 teaching_data 摘要】\n"
        f"scene_svg（前 6000 字）:\n{scene_cut}\n\n"
        f"steps_json（前 6000 字）:\n{steps_cut}\n\n"
        "请抽取可复用骨架，输出 JSON。"
    )


SYSTEM_PATTERN_DRAFT = """你负责把“一类题型”的最佳动画产物沉淀成「特殊题型提示词」（画法模板），供未来同题型生成稳定复用。

要求：
1. 输出对齐 scene_patterns/50_pattern_{key}.md 结构的草稿（Markdown）：
   - 适用题型与触发词（何时用这套画法）
   - 画法硬规则（颜色/坐标/元素约定，可引用纸底 #f4efe3、墨 #2b2b2b、变量蓝 #2f5fde、朱砂 #d6432f、鎏金 #c8901a 等项目配色）
   - 场景骨架占位示例（scene_svg 用 {{slot}} 占位，禁止抄原题具体数字）
   - 运动序列约定（元素如何动、顺序）
   - 自检点（渲染后须满足什么）
2. 数据一律用占位符，绝不许出现原模板题的真实数字。
3. 触发词要“够宽但不误伤”——能覆盖该类题，又不误吞不同解法的题。
4. 输出纯 JSON：
{
  "question_type_hint": "题型细分名（用于 content_profile 词条增补）",
  "markdown": "完整 Markdown 草稿（含上述各节）"
}
只输出 JSON。"""


def build_pattern_draft_prompt(method_signature: str, teaching_data: dict) -> str:
    """构造题型提示词沉淀 user prompt。"""
    import json as _json
    scene = (teaching_data or {}).get("scene_svg", "")
    scene_cut = scene[:4000] if isinstance(scene, str) else ""
    return (
        f"【解法指纹】{method_signature}\n"
        f"【最佳产物 scene_svg 摘要（前 4000 字，仅作画法参考，禁止抄数字）】\n{scene_cut}\n\n"
        "请沉淀为「特殊题型提示词」草稿（数据用占位符），输出 JSON。"
    )

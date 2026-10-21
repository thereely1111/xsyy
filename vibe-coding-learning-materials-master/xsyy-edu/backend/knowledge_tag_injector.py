"""知识点标签注入模块（知识域 → 年级 → 章/单元 → 知识点标签）。

识别采用两步分层大模型，候选全部来自远程数据库 knowledge_tag_framework 表：
    1. 判定知识域与年级（候选为「域×年级→章/单元」骨架）；
    2. 在确定的 域×年级 内，结合强特征关键词选择 1 个知识点标签。

对外入口：
    - inject_knowledge_tags: 单标签组（兼容旧接口，llm 参数仅为兼容保留）
    - inject_knowledge_tags_full: 主标签组 + 可选第二标签组（多知识点题）
    - match_knowledge_tags_by_keyword: 强特征关键词匹配兜底（无需 API）
    - build_knowledge_tags_from_existing: 由旧字段反查补全标签
    - load_framework / reload_framework: 加载 / 刷新标签框架

标签结构（写入 metadata.json 的 knowledge_tags 字段，单标签组）：
{
    "version": "数与式",            # 知识域
    "grade": "五下",                # 年级
    "main_tag": "分数的意义和性质",  # 章/单元
    "sub_tags": ["分数的基本性质"]   # 知识点标签（模块级，隐性属性不显示）
}
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from dotenv import load_dotenv

from knowledge_tag_rag import (  # noqa: E402
    RAG_DIRECT_MIN,
    TagIndex,
    prescreen,
    rerank_candidates,
    search_combined,
)

_backend_dir = Path(__file__).resolve().parent
load_dotenv(dotenv_path=_backend_dir / ".env")

# 模型配置统一从 kimi_config 读取（.env 唯一出口）
from kimi_config import (  # noqa: E402
    get_backup_api_key,
    get_backup_base_url,
    get_backup_model,
    get_image_api_key,
    get_image_base_url,
    is_backup_configured,
    is_timeout_error,
)

# 框架缓存（进程级，仅缓存远程数据库查询结果）
_framework_cache: Optional[dict] = None
_framework_cache_time = 0.0
_FRAMEWORK_CACHE_TTL = 60.0

# RAG 轻档索引缓存（进程级，与框架同生命周期）
_tag_index: Optional[TagIndex] = None

GRADE_ORDER = [
    "一上", "一下", "二上", "二下", "三上", "三下", "四上", "四下", "五上", "五下",
    "六上", "六下", "七上", "七下", "八上", "八下", "九上", "九下",
]
DOMAIN_ORDER = ["数与式", "方程与不等式", "函数", "图形与几何", "统计与概率"]

# 知识域别名归一化
DOMAIN_ALIAS = {
    "A": "数与式", "B": "方程与不等式", "C": "函数", "D": "图形与几何", "E": "统计与概率",
    "数與式": "数与式", "圖形與几何": "图形与几何", "統計與概率": "统计与概率",
    "数与代数": "数与式", "图形与几何 ": "图形与几何",
}

# 仅保留学段特征明确的强特征词；其余跨学段题型交由数据库候选的两步识别判断
FUNCTION_WORDS = ("一次函数", "二次函数", "反比例函数", "函数图象", "函数图像", "解析式", "抛物线", "双曲线", "y=")


def _normalize_label(value: object) -> str:
    """统一标签字段，移除 Excel 或数据库中混入的空白字符。"""
    return re.sub(r"[\s\u200b\ufeff]+", "", str(value or ""))


def _fuzzy_match(value: str, candidates: list) -> Optional[str]:
    """子串模糊匹配：候选与目标互相包含即命中，否则返回 None。

    用于校正 LLM 输出值（知识域/年级）与标准列表的轻微差异。
    """
    for cand in candidates:
        if cand in value or value in cand:
            return cand
    return None


def _keyword_hit_score(keyword: str, question: str, weight: float = 1.0) -> float:
    """计算强特征关键词对题面的命中得分（按命中词长度加权）。

    keyword 可能含多个词（以、，,/ 分隔），仅统计长度 ≥2 的完整命中词；
    weight 用于区分不同匹配场景的权重（如全局关键词兜底加倍计分）。
    """
    if not keyword or keyword in ("nan", "-"):
        return 0.0
    score = 0.0
    for part in re.split(r"[、，,/]", keyword):
        part = part.strip()
        if len(part) >= 2 and part in question:
            score += len(part) * weight
    return score


# 低年级段（一上~二下）：数字/符号反信号拦截的候选年级范围
_LOW_GRADE_BLOCK_GRADES = frozenset(GRADE_ORDER[:4])


def _low_grade_block_reasons(question: str) -> tuple:
    """检测题面中的高年级特征（三位数/小数分数/百分数/方程函数词）。

    兜底关键词匹配时，若题面命中这些特征而候选标签落在低年级段（一上~二下），
    视为反信号直接拦截，避免"10辆/30个"等数字把方程/应用题误吸到一年级标签。
    返回命中原因元组（空元组表示无反信号）。
    """
    reasons = []
    if re.search(r"\d{3,}", question):
        reasons.append("出现三位及以上数字")
    if re.search(r"\d+\.\d+", question) or re.search(r"\d+\s*/\s*\d+", question) or "几分之几" in question:
        reasons.append("出现小数或分数")
    if "%" in question or "百分" in question:
        reasons.append("出现百分数")
    if any(w in question for w in ("设", "未知数", "方程", "方程组", "抛物线", "函数", "一次函数", "二次函数")):
        reasons.append("出现方程或函数特征词")
    return tuple(reasons)


def _entry_to_result(entry: dict) -> Dict:
    """将标签归属条目（_lookup_tag_entry 的结果）转换为标准标签组结果。"""
    return {
        "version": _normalize_label(entry["version"]),
        "grade": _normalize_label(entry["grade"]),
        "main_tag": _normalize_label(entry["main_tag"]),
        "sub_tags": [_normalize_label(entry["tag"])],
    }


def _build_direct_tag_result(framework: dict, tag: str) -> Optional[Dict]:
    """按知识点标签直接反查归属，用于强特征题型的确定性优先路由。"""
    entry = _lookup_tag_entry(tag, framework)
    return _entry_to_result(entry) if entry else None


def _build_path_tag_result(
    framework: dict, version: str, grade: str, main_tag: str, tag: str
) -> Optional[Dict]:
    """仅在标签库存在指定完整路径时构造确定性路由结果。

    先校验 域×年级×章/单元 下确实存在该知识点标签，再反查唯一归属，
    避免同名标签跨学段串标。
    """
    path_tags = framework.get("hierarchy", {}).get(version, {}).get(grade, {}).get(main_tag, [])
    if not any(_normalize_label(path_tag) == _normalize_label(tag) for path_tag in path_tags):
        return None
    entry = _lookup_tag_entry(
        tag, framework, version=version, grade=grade, main_tag=main_tag
    )
    return _entry_to_result(entry) if entry else None


def _is_remainder_congruence_problem(question: str) -> bool:
    """识别给出除法余数条件的余数与同余问题（含"商是X余Y""除以X余Y"表述）。"""
    has_remainder = (
        "余数" in question or "同余" in question
        or bool(re.search(r"商[^。；;!?]{0,8}余\s*\d+", question))  # 商是5余2 / 商5余2
        or bool(re.search(r"(除以|去除以)\s*\d+[^。；;!?]{0,10}余\s*\d+", question))  # 除以7余2
        or bool(re.search(r"余\s*\d+", question))  # 余2、余3（仅在除法语境下生效）
    )
    has_division_context = any(
        word in question for word in ("除以", "去除以", "被除数", "除数", "商")
    )
    return has_remainder and has_division_context


def _is_complex_meeting_problem(question: str) -> bool:
    """识别两次相遇、到端点折返的复合行程问题。"""
    has_meeting = any(
        word in question for word in ("相遇", "相向而行", "追及", "追上")
    )
    has_turnaround = any(
        word in question for word in ("掉头", "折返", "返回", "往返")
    )
    has_repeat_meeting = any(
        word in question for word in ("第一次相遇", "第二次相遇", "再次相遇")
    )
    return has_meeting and has_turnaround and has_repeat_meeting


def _is_basic_meeting_problem(question: str) -> bool:
    """识别普通两人/两车行程相遇或追及题。"""
    has_motion = any(word in question for word in ("相遇", "相向而行", "追及", "追上", "同向而行"))
    has_subject = any(word in question for word in ("两人", "两车", "甲乙", "甲、乙", "小明", "小华"))
    has_distance_or_time = any(word in question for word in ("速度", "路程", "距离", "相距", "千米", "米", "小时", "分钟"))
    return has_motion and has_subject and has_distance_or_time


def _has_equation_evidence(question: str) -> bool:
    """题面是否明确出现列方程、解方程、设未知数等方程建模证据。"""
    return any(word in question for word in ("方程", "设未知数", "建立方程"))


def _is_double_equilateral_triangle_problem(question: str) -> bool:
    """识别由两个等边三角形组成的全等三角形几何证明结构。"""
    has_equilateral = "等边三角形" in question or "等边" in question
    has_two_triangles = (
        question.count("△") >= 2
        or question.count("三角形") >= 2
        or ("ABC" in question and "CDE" in question)
    )
    has_structure = any(word in question for word in ("相交", "交于", "共线", "同一直线"))
    return has_equilateral and has_two_triangles and has_structure


def _is_ball_volume_problem(question: str) -> bool:
    """识别球(体)的体积/表面积计算题（表内无独立'球'章节，按用户标注归入圆柱与圆锥）。"""
    has_ball = any(word in question for word in ("球", "球体"))
    has_volume = any(word in question for word in ("体积", "容积", "表面积", "立方", "半径", "直径"))
    return has_ball and has_volume


def _is_cylinder_cone_problem(question: str) -> bool:
    """识别圆柱/圆锥的体积或表面积计算题（六下 圆柱与圆锥）。"""
    has_shape = any(word in question for word in ("圆柱", "圆锥"))
    has_metric = any(word in question for word in (
        "体积", "容积", "表面积", "侧面积", "底面积", "底面半径", "底面直径", "高", "半径", "直径",
    ))
    return has_shape and has_metric


def _is_concentration_solution_problem(question: str) -> bool:
    """识别浓度、盐水、配比守恒题。"""
    has_solution = any(word in question for word in ("盐水", "浓度", "溶液", "纯水", "加水", "配制"))
    has_percent = "%" in question or "百分" in question
    has_mass = any(word in question for word in ("克", "千克", "吨", "升", "毫升"))
    return has_solution and (has_percent or has_mass)


def _is_two_capacity_vehicle_seat_problem(question: str) -> bool:
    """识别两种容量车辆的座位/载人总量题（含"每辆坐60人/载60人"表述）。"""
    has_vehicle = any(word in question for word in ("客车", "汽车", "车辆", "巴士", "校车", "大车", "小车"))
    capacities = {int(value) for value in re.findall(r"(\d+)\s*座", question)}
    has_two_capacities = len(capacities) >= 2 or (
        ("大客车" in question and "小客车" in question)
        or ("大车" in question and "小车" in question)
        or "两种" in question
    )
    # 容量表述放宽：除"座位/载客/N座"外，两种车辆各带"坐/载/乘/容纳 N 人"也算
    has_two_people_caps = len({int(v) for v in re.findall(r"(?:坐|载|乘|容纳)\s*(\d+)\s*人", question)}) >= 2
    has_seat_capacity = "座位" in question or "载客" in question or bool(capacities) or has_two_people_caps
    # 总量/差值表述放宽：补充"共用 N 辆"与"比…多/少 N"
    has_total = any(word in question for word in ("一共", "总共", "共有", "共用", "合计", "总数", "多少名", "人数"))
    has_diff = bool(re.search(r"比[^。；;!?]{0,10}(多|少|大|小)\s*\d+", question))
    return has_vehicle and has_two_capacities and has_seat_capacity and (has_total or has_diff)


def _is_chicken_rabbit_head_foot_problem(question: str) -> bool:
    """识别鸡与兔或三脚猫的总头数、总脚数题。"""
    has_pair = "鸡" in question and ("兔" in question or "三脚猫" in question)
    has_head_count = any(word in question for word in ("头", "只"))
    has_foot_count = any(word in question for word in ("脚", "腿"))
    has_total = any(word in question for word in ("一共", "总共", "共有", "合计", "总数"))
    return "鸡兔同笼" in question or (has_pair and has_head_count and has_foot_count and has_total)


def _is_two_kind_quantity_cost_problem(question: str) -> bool:
    """识别两类物品已知总数量与总成本、需先建立二元方程组的应用题。"""
    has_two_kinds = (
        ("甲" in question and "乙" in question)
        or "两种" in question
        or "两款" in question
        or "两类" in question
    )
    has_quantity_total = any(word in question for word in ("共", "总共", "一共", "合计", "共有")) and any(
        word in question for word in ("件", "个", "套", "台", "只", "本")
    )
    has_total_cost = any(word in question for word in ("购进", "进货", "成本", "进价")) and any(
        word in question for word in ("元", "金额", "钱")
    )
    has_unit_cost = question.count("每件") >= 2 or question.count("每个") >= 2 or question.count("进价") >= 2
    return has_two_kinds and has_quantity_total and has_total_cost and has_unit_cost


def _is_grass_grazing_system_problem(question: str) -> bool:
    """识别牧草匀速生长、牛数和天数组成的二元一次方程组应用题。"""
    has_grass = any(word in question for word in ("牧草", "草地", "青草", "草"))
    has_growth = any(word in question for word in ("匀速生长", "每天生长", "不断生长", "生长"))
    has_cattle = any(word in question for word in ("牛", "放牧", "吃"))
    has_multi_conditions = (
        question.count("头") >= 2
        and question.count("天") >= 2
        and any(word in question for word in ("永远吃不完", "吃不完", "最多只能放牧", "可供"))
    )
    return has_grass and has_growth and has_cattle and has_multi_conditions


def _is_right_triangle_compose_problem(question: str) -> bool:
    """识别'以三边长度判断能否组成直角三角形'（勾股定理逆定理应用）。"""
    has_rt = "直角三角形" in question
    has_compose = any(word in question for word in (
        "能组成", "为边", "三条线段", "线段为边", "边长分别", "以下列", "下列", "可否构成"
    ))
    return has_rt and has_compose


def _is_right_triangle_side_problem(question: str) -> bool:
    """识别直角三角形已知两边求第三边（勾股定理直接应用，八上 勾股定理）。"""
    if "面积" in question:
        return False
    has_side = "斜边" in question or "直角边" in question
    has_query = any(w in question for w in ("求", "长", "多少"))
    return has_side and has_query


def _is_complementary_supplementary_angle(question: str) -> bool:
    """识别余角/补角题（锁定七上几何图形初步）。"""
    return "余角" in question or "补角" in question


def _is_explicit_probability(question: str) -> bool:
    """识别显式概率计算题（求概率/摸到…的概率/P=），锁定七下概率初步。

    仅当概率是题面主话题时路由；若概率只是混合题里的附带小问（如题面同时含
    分式方程、平均数、统计图等），交给 LLM 按主计算对象判定，避免误路由。
    """
    has_prob = "概率" in question
    has_query = any(word in question for word in (
        "求", "摸到", "随机", "P=", "取出", "抽出",
        "掷", "抛", "骰子", "硬币", "选中", "抽到", "抽中", "下雨", "降雨", "是多少",
    ))
    competing = any(w in question for w in (
        "分式方程", "平均数", "平均身高", "求平均数", "列方程", "解方程",
        "统计图", "条形", "折线", "扇形图", "中位数", "众数", "方差",
    ))
    return has_prob and has_query and not competing


def _is_angle_bisector_problem(question: str) -> bool:
    """识别角平分线题（平分∠ 或 角平分线）。"""
    return "角平分线" in question or ("平分" in question and "∠" in question)


def _angle_bisector_is_triangle_context(question: str) -> bool:
    """角平分线题是否落在三角形章节（问线段/边长/高/中线）。"""
    return any(word in question for word in ("线段", "边长", "高", "中线", "MN", "长", "周长"))


def _try_path_tag_results(framework: dict, candidates: list) -> tuple:
    """依次尝试多组 (version, grade, main_tag, sub_tag) 确定性路由，返回首个命中的结果。

    用于兼容标签表结构随版本演进：同一题型在新表中可能换了路径/标签名，
    只要其中任意一组路径真实存在即命中；全部缺失则返回 (None, None)，
    由上层退回 LLM 兜底，绝不因路径变更而崩溃。
    """
    for version, grade, main_tag, sub_tag in candidates:
        result = _build_path_tag_result(framework, version, grade, main_tag, sub_tag)
        if result:
            return result, (version, grade, main_tag, sub_tag)
    return None, None


def _route_path(framework: dict, candidates: list, message: str) -> Optional[Dict]:
    """尝试一组确定性路由候选，命中即记录日志并返回标签组结果。"""
    result, _ = _try_path_tag_results(framework, candidates)
    if result:
        _log(message)
    return result


def _is_sum_difference_problem(question: str) -> bool:
    """识别和倍/差倍/和差问题（两类对象 + 倍数关系 + 求各自数量，七上 一元一次方程 和倍差问题）。"""
    if "倍" not in question:
        return False
    has_relation = "比" in question or "和" in question
    has_ask = ("各" in question or "两数" in question or "之和" in question
               or ("共" in question and "多少" in question))
    return has_relation and has_ask


def _is_system_of_equations_problem(question: str) -> bool:
    """识别含'方程组'字样的方程组建模/求解题（七下 二元一次方程组）。"""
    return "方程组" in question


def _is_rotation_construction_problem(question: str) -> bool:
    """识别等边三角形内部一点到三顶点距离题（旋转变换构造，九上 旋转）。

    典型：'等边三角形ABC内部有一点P，PA=3，PB=4，PC=5，求边长'。
    """
    if "等边三角形" not in question:
        return False
    has_inner = "内部" in question or "内一点" in question
    has_dist = ("PA" in question and "PB" in question and "PC" in question) \
        or bool(re.search(r"[Pp][A-D]?[=＝]?\s*\d+", question))
    return has_inner and has_dist


def _is_new_definition_problem(question: str) -> bool:
    """识别新定义/阅读理解型压轴题（给出如下定义/定义新运算，九上 综合与实践）。"""
    return ("给出如下定义" in question or "定义新运算" in question
            or ("新定义" in question and ("问题" in question or "压轴" in question)))


def _is_dynamic_point_problem(question: str) -> bool:
    """识别动点/动态几何问题（点沿边/射线运动，求最值/关系式）。"""
    if "动点" in question:
        return "求" in question or "最大" in question or "最短" in question or "关系式" in question
    return ("以每秒" in question or "设运动时间为" in question or "运动过程中" in question) and "求" in question


def _is_existence_problem(question: str) -> bool:
    """识别存在性问题（是否存在...使得...）。"""
    return "是否存在" in question or ("若存在" in question and "求出" in question)


def _is_geometric_extremum_problem(question: str) -> bool:
    """识别几何最值问题（最短路径/最大面积/将军饮马等）。"""
    if "最大" in question or "最短" in question or "最小" in question:
        if ("PA" in question or "PB" in question or "PC" in question) or "将军饮马" in question:
            return True
        if ("河" in question or "村庄" in question or "取水" in question or "建在" in question) and "最" in question:
            return True
        if "面积" in question and "最大" in question and ("矩形" in question or "三角形" in question or "正方形" in question):
            return True
    return False


def _is_classification_discussion_problem(question: str) -> bool:
    """识别分类讨论问题（条件未指明需分情况讨论）。"""
    return ("分类讨论" in question or "分两种情况" in question or "分情况" in question
            or ("等腰三角形" in question and "求∠" in question and "没有指明" in question))


def _is_hand_hand_model_problem(question: str) -> bool:
    """识别手拉手模型（两个等腰/等边三角形共顶点，连接端点求证线段相等）。"""
    has_triangle_pair = question.count("△") >= 2 or question.count("三角形") >= 2
    has_isosceles = "等腰" in question or "等边" in question
    has_proof = "连接" in question and "求证" in question
    return "手拉手" in question or (has_triangle_pair and has_isosceles and has_proof)


def _is_plan_design_problem(question: str) -> bool:
    """识别方案设计问题（购买方案/费用约束/共有几种方案）。"""
    return (("方案" in question or "共有几种" in question) and "购买" in question) \
        or ("购买" in question and "不超过" in question) \
        or ("方案" in question and "总费用" in question)


def _is_profit_extremum_problem(question: str) -> bool:
    """识别销售利润最值问题（售价/销量/利润，求最大利润）。"""
    return ("利润" in question or "售价" in question) \
        and ("最大" in question or "最多" in question or "最少" in question) \
        and "元" in question


def _is_shopping_money_problem(question: str) -> bool:
    """识别整数购物付钱/找零应用题（单价×数量，二上 表内乘法 乘法应用题）。

    典型：'每支2元，买3支'、'给了售货员10元，应找回多少钱'。
    含小数、或初中特征（方案/不超过/利润/售价/最大等）时交 LLM（避免误吸小数乘法、
    方案设计、利润最值等初中综合题）。
    """
    if re.search(r"\d+\.\d+", question):
        return False
    if any(w in question for w in ("方案", "不超过", "总费用", "利润", "售价", "最大", "最少", "共有几种", "不等式")):
        return False
    has_unit_price = bool(re.search(r"每[^，。；;!?]{0,6}\d+\s*元", question))  # 每支2元/每千克8元
    has_buy = any(w in question for w in ("买", "购", "付", "给", "找回", "应找", "售货员", "营业员"))
    has_money = "元" in question
    return has_unit_price and has_buy and has_money


def _is_division_apportion_problem(question: str) -> bool:
    """识别整数等分/包含除应用题（总量 ÷ 每份 = 份数 或 总量 ÷ 份数 = 每份）。

    典型：'30个苹果，每6个装一袋，可以装几袋？'、'120本平均分给6个班，每班几本？'。
    含小数时交 LLM（避免误吸小数除法）；大数（三位数以上）倾向多位数除法，路由候选含三年级标签。
    """
    if re.search(r"\d+\.\d+", question):
        return False
    has_quantity = bool(re.search(r"\d+\s*[个本支袋盒棵朵块名只辆段]", question))
    has_partition = any(w in question for w in ("平均分", "装一袋", "装几袋", "分成", "分给", "每组", "每份", "每班"))
    has_ask = any(w in question for w in ("几袋", "几盒", "几个", "多少", "几本", "每"))
    return has_quantity and has_partition and has_ask


def _match_strong_special_case(question: str, framework: dict) -> Optional[Dict]:
    """确定性优先路由：题型结构明确且标签库存在目标完整路径时直接命中。

    仅命中完整路径（域×年级×章/单元×知识点标签）才返回结果；否则返回 None，
    由调用方继续走两步 LLM 或关键词兜底，保证标签表结构演进不致崩溃。
    """
    if _is_remainder_congruence_problem(question):
        result = _route_path(framework, [
            ("数与式", "二下", "有余数的除法", "余数应用"),
            ("数与式", "三下", "有余数的除法", "余数应用"),
        ], "命中除法余数条件结构，优先使用余数应用")
        if result:
            return result

    is_meeting = _is_complex_meeting_problem(question) or _is_basic_meeting_problem(question)
    has_equation = _has_equation_evidence(question)
    if is_meeting and has_equation:
        result = _route_path(framework, [
            ("方程与不等式", "七上", "一元一次方程", "一元一次方程应用题"),
        ], "命中行程结构且题面出现方程证据，优先使用一元一次方程应用题")
        if result:
            return result

    if is_meeting and not has_equation:
        result = _route_path(framework, [
            ("方程与不等式", "七上", "一元一次方程", "行程问题"),
            ("方程与不等式", "七下", "一元一次方程", "行程问题"),
        ], "命中小学行程结构（无方程证据），优先使用行程问题")
        if result:
            return result

    if _is_ball_volume_problem(question):
        result = _route_path(framework, [
            ("图形与几何", "六下", "圆柱与圆锥", "圆柱与圆锥的体积"),
        ], "命中球体积/表面积计算结构，按用户标注归入圆柱与圆锥的体积")
        if result:
            return result

    if _is_cylinder_cone_problem(question):
        if "表面积" in question or "侧面积" in question:
            result = _route_path(framework, [
                ("图形与几何", "六下", "圆柱与圆锥", "圆柱的认识与表面积"),
            ], "命中圆柱/圆锥表面积结构，优先使用圆柱的认识与表面积")
        else:
            result = _route_path(framework, [
                ("图形与几何", "六下", "圆柱与圆锥", "圆柱与圆锥的体积"),
            ], "命中圆柱/圆锥体积结构，优先使用圆柱与圆锥的体积")
        if result:
            return result

    if _is_concentration_solution_problem(question):
        result = _route_path(framework, [
            ("数与式", "六下", "比例", "比例的意义与基本性质"),
        ], "命中浓度盐水配制结构，优先使用比例的意义与基本性质")
        if result:
            return result

    if _is_grass_grazing_system_problem(question):
        result = _route_path(framework, [
            ("方程与不等式", "七下", "二元一次方程组", "二元一次方程组应用题"),
        ], "命中牧草匀速生长与多条件牛数天数结构，优先使用二元一次方程组应用题")
        if result:
            return result

    if _is_two_kind_quantity_cost_problem(question):
        result = _route_path(framework, [
            ("方程与不等式", "七下", "二元一次方程组", "二元一次方程组应用题"),
        ], "命中两类物品总数量与总成本结构，优先使用二元一次方程组应用题")
        if result:
            return result

    if _is_new_definition_problem(question):
        # 新定义题按题面主对象（等腰三角形）归知识领域
        result = _route_path(framework, [
            ("图形与几何", "九上", "三角形", "等腰三角形综合应用"),
        ], "命中新定义/阅读理解结构（主对象等腰三角形），优先使用等腰三角形综合应用")
        if result:
            return result

    if _is_rotation_construction_problem(question):
        # 等边三角形内点题按题面主对象归等边三角形（旋转为关键词线索）
        result = _route_path(framework, [
            ("图形与几何", "八上", "轴对称", "等边三角形的性质与判定"),
        ], "命中等边三角形内点结构，优先使用等边三角形的性质与判定")
        if result:
            return result

    if _is_hand_hand_model_problem(question):
        # 手拉手模型（两等腰三角形共顶点求证全等）按题面主对象归全等三角形
        result = _route_path(framework, [
            ("图形与几何", "八上", "全等三角形", "全等三角形判定"),
        ], "命中手拉手模型结构，优先使用全等三角形判定")
        if result:
            return result

    if _is_dynamic_point_problem(question):
        result = _route_path(framework, [
            ("图形与几何", "九上", "图形与几何·综合与实践", "动点问题"),
        ], "命中动点/动态几何结构，优先使用动点问题")
        if result:
            return result

    if _is_existence_problem(question):
        result = _route_path(framework, [
            ("图形与几何", "九上", "图形与几何·综合与实践", "存在性问题"),
        ], "命中存在性问题结构，优先使用存在性问题")
        if result:
            return result

    if _is_geometric_extremum_problem(question):
        result = _route_path(framework, [
            ("图形与几何", "九上", "图形与几何·综合与实践", "几何最值问题"),
        ], "命中几何最值结构，优先使用几何最值问题")
        if result:
            return result

    if _is_classification_discussion_problem(question):
        result = _route_path(framework, [
            ("图形与几何", "九上", "图形与几何·综合与实践", "分类讨论问题"),
        ], "命中分类讨论结构，优先使用分类讨论问题")
        if result:
            return result

    if _is_plan_design_problem(question):
        result = _route_path(framework, [
            ("方程与不等式", "九上", "方程与不等式·综合应用", "方案设计问题"),
        ], "命中方案设计结构，优先使用方案设计问题")
        if result:
            return result

    if _is_profit_extremum_problem(question):
        result = _route_path(framework, [
            ("函数", "九上", "二次函数", "最大利润问题"),
            ("函数", "九上", "二次函数", "利润最值"),
        ], "命中销售利润最值结构，优先使用最大利润问题")
        if result:
            return result

    if _is_shopping_money_problem(question):
        result = _route_path(framework, [
            ("数与式", "二上", "表内乘法", "乘法应用题"),
        ], "命中购物单价×数量结构，优先使用乘法应用题")
        if result:
            return result

    if _is_division_apportion_problem(question):
        is_fraction = bool(re.search(r"\d+\s*/\s*\d+", question)) or "几分之几" in question
        if is_fraction:
            result = _route_path(framework, [
                ("数与式", "五下", "分数乘除", "分数除法应用"),
                ("数与式", "六上", "分数乘除", "分数乘法与除法"),
            ], "命中分数等分结构，优先使用分数除法应用")
        else:
            nums = [int(m) for m in re.findall(r"\d+", question)]
            if nums and max(nums) > 81:
                result = _route_path(framework, [
                    ("数与式", "三上", "除数是一位数的除法", "除法应用"),
                    ("数与式", "二下", "表内除法", "除法应用"),
                ], "命中等分结构且涉及大数，优先使用除数是一位数的除法")
            else:
                result = _route_path(framework, [
                    ("数与式", "二下", "表内除法", "除法应用"),
                    ("数与式", "三上", "除数是一位数的除法", "除法应用"),
                ], "命中等分结构（表内量级），优先使用表内除法")
        if result:
            return result

    if _is_two_capacity_vehicle_seat_problem(question):
        result = _route_path(framework, [
            ("方程与不等式", "七上", "一元一次方程", "一元一次方程应用题"),
        ], "命中两种容量车辆座位结构，优先使用一元一次方程应用题")
        if result:
            return result

    if _is_system_of_equations_problem(question):
        result = _route_path(framework, [
            ("方程与不等式", "七下", "二元一次方程组", "二元一次方程组解法"),
            ("方程与不等式", "七下", "二元一次方程组", "代入法"),
        ], "命中'方程组'特征，优先使用二元一次方程组解法")
        if result:
            return result

    if _is_sum_difference_problem(question):
        result = _route_path(framework, [
            ("方程与不等式", "七上", "一元一次方程", "和倍差问题"),
        ], "命中两类对象+倍数关系结构，优先使用和倍差问题")
        if result:
            return result

    if _is_double_equilateral_triangle_problem(question):
        result = _route_path(framework, [
            ("图形与几何", "八上", "全等三角形", "全等三角形判定"),
        ], "命中双等边三角形共线交点结构，优先使用全等三角形判定")
        if result:
            return result

    if _is_chicken_rabbit_head_foot_problem(question):
        result = _route_path(framework, [
            ("图形与几何", "四下", "鸡兔同笼", "假设法解决"),
            ("图形与几何", "四下", "数学广角-鸡兔同笼", "假设法解决"),
            ("综合与实践", "四下", "数学广角-鸡兔同笼", "假设法解决"),
        ], "命中鸡兔同笼总头数总脚数结构，优先使用假设法解决")
        if result:
            return result

    if _is_right_triangle_side_problem(question):
        result = _route_path(framework, [
            ("图形与几何", "八上", "勾股定理", "勾股定理在几何中的应用"),
        ], "命中直角三角形已知两边求第三边结构，优先使用勾股定理在几何中的应用")
        if result:
            return result

    if _is_right_triangle_compose_problem(question):
        result = _route_path(framework, [
            ("图形与几何", "八上", "勾股定理", "勾股定理在几何中的应用"),
        ], "命中'三边长度判断能否组成直角三角形'结构，优先使用勾股定理在几何中的应用")
        if result:
            return result

    if _is_complementary_supplementary_angle(question):
        result = _route_path(framework, [
            ("图形与几何", "七上", "几何图形初步", "余角、补角与方位角"),
        ], "命中余角/补角结构，优先使用余角、补角与方位角（七上 几何图形初步）")
        if result:
            return result

    if _is_explicit_probability(question):
        result = _route_path(framework, [
            ("统计与概率", "七下", "概率初步", "概率"),
        ], "命中显式概率计算结构，优先使用概率（七下 概率初步）")
        if result:
            return result

    if _is_angle_bisector_problem(question):
        if _angle_bisector_is_triangle_context(question):
            result = _route_path(framework, [
                ("图形与几何", "八上", "三角形", "三角形的高、中线与角平分线"),
            ], "命中角平分线结构，按上下文优先使用三角形的高/中线/角平分线")
        else:
            result = _route_path(framework, [
                ("图形与几何", "七上", "几何图形初步", "角的度量与角平分线"),
            ], "命中角平分线结构，按上下文优先使用角的度量与角平分线")
        if result:
            return result

    function_hit = any(word in question for word in FUNCTION_WORDS)
    if not function_hit:
        return None
    # 显式匹配：仅题面含对应函数名词时路由，避免"y=/x="等符号把非函数题误吸
    function_routes = (
        ("二次函数最值问题", lambda q: ("二次函数" in q or "抛物线" in q) and ("最大" in q or "最小" in q or "最值" in q)),
        ("一次函数与方程/不等式及实际应用", lambda q: "一次函数" in q),
        ("反比例函数的图象、性质与应用", lambda q: "反比例函数" in q or "双曲线" in q),
    )
    for tag_name, matcher in function_routes:
        result = _build_direct_tag_result(framework, tag_name)
        if result and matcher(question):
            _log(f"命中函数强特征，优先使用{tag_name}")
            return result
    return None


def _log(message: str, level: str = "INFO") -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [KT-{level}] {message}", flush=True)


def _load_framework_from_db() -> dict:
    """从数据库读取完整标签框架；数据库不可用时由调用方处理异常。"""
    from database import SessionLocal
    from database.models import KnowledgeTagFramework

    db = SessionLocal()
    try:
        rows = db.query(KnowledgeTagFramework).order_by(KnowledgeTagFramework.id).all()
    finally:
        db.close()

    if not rows:
        return {}

    versions = []
    grades = []
    main_tags = []
    hierarchy = {}
    main_tag_info = {}
    sub_tag_index = {}
    keyword_index = {}
    for row in rows:
        version = _normalize_label(row.version)
        grade = _normalize_label(row.grade)
        main_tag = str(row.main_tag or "").strip()
        sub_tag = _normalize_label(row.sub_tag)
        for values, value in ((versions, version), (grades, grade), (main_tags, main_tag)):
            if value and value not in values:
                values.append(value)
        hierarchy.setdefault(version, {}).setdefault(grade, {}).setdefault(main_tag, [])
        if sub_tag and sub_tag not in hierarchy[version][grade][main_tag]:
            hierarchy[version][grade][main_tag].append(sub_tag)
        info = main_tag_info.setdefault(main_tag, {"grades": [], "sub_tags": []})
        if grade not in info["grades"]:
            info["grades"].append(grade)
        if sub_tag and sub_tag not in info["sub_tags"]:
            info["sub_tags"].append(sub_tag)
        if sub_tag:
            entry = {
                "main_tag": main_tag,
                "grade": grade,
                "version": version,
                "keyword": row.keyword or "",
            }
            if entry not in sub_tag_index.setdefault(sub_tag, []):
                sub_tag_index[sub_tag].append(entry)
            keyword_index.setdefault(sub_tag, row.keyword or "")

    return {
        "versions": versions,
        "grades": grades,
        "main_tags": main_tags,
        "main_tag_info": main_tag_info,
        "hierarchy": hierarchy,
        "sub_tag_index": sub_tag_index,
        "keyword_index": keyword_index,
    }


def load_framework() -> dict:
    """加载并缓存数据库中的知识点标签框架。"""
    global _framework_cache, _framework_cache_time
    now = datetime.now().timestamp()
    if _framework_cache is not None and now - _framework_cache_time < _FRAMEWORK_CACHE_TTL:
        return _framework_cache
    try:
        framework = _load_framework_from_db()
    except Exception as e:
        _log(f"标签框架加载失败: {type(e).__name__}: {str(e)[:150]}", "ERROR")
        framework = {}
    _framework_cache = framework
    _framework_cache_time = now
    return framework


def reload_framework() -> dict:
    """强制重新从数据库加载框架。"""
    global _framework_cache, _framework_cache_time
    _framework_cache = None
    _framework_cache_time = 0.0
    return load_framework()


def load_tag_index() -> Optional[TagIndex]:
    """加载并缓存 RAG 标签索引（进程级，随框架构建）。

    - kill-switch：环境变量 RAG_ENABLED=0/false/no 时禁用整个 RAG 路径；
    - 后端切换：EMBEDDING_BACKEND=lexical|semantic（默认 lexical）；
      semantic 构建/加载失败自动降级 lexical，保证 RAG 链路不中断。
    """
    global _tag_index
    if os.getenv("RAG_ENABLED", "1").strip().lower() in ("0", "false", "no"):
        return None
    if _tag_index is not None:
        return _tag_index
    framework = load_framework()
    if not framework or not framework.get("hierarchy"):
        return None
    backend = os.getenv("EMBEDDING_BACKEND", "lexical").strip().lower()
    try:
        if backend == "semantic":
            _tag_index = TagIndex.from_framework(framework, backend="semantic")
            _log(f"RAG 语义索引已构建: {len(_tag_index)} 条标签")
        else:
            _tag_index = TagIndex.from_framework(framework, backend="lexical")
            _log(f"RAG 轻档索引已构建: {len(_tag_index)} 条标签")
    except Exception as e:
        if backend == "semantic":
            _log(f"语义索引构建失败({str(e)[:120]})，降级轻档索引", "WARN")
            try:
                _tag_index = TagIndex.from_framework(framework, backend="lexical")
            except Exception:
                _tag_index = None
        else:
            _log(f"RAG 轻档索引构建失败: {type(e).__name__}: {str(e)[:150]}", "ERROR")
            _tag_index = None
    return _tag_index


def reload_tag_index() -> Optional[TagIndex]:
    """强制重建 RAG 轻档索引（框架更新后调用）。"""
    global _tag_index
    _tag_index = None
    return load_tag_index()


# ---------------------------------------------------------------------------
# 标签库索引构建
# ---------------------------------------------------------------------------

def _build_tag_lib(framework: dict) -> Dict[str, Dict[str, list]]:
    """从框架构建 {知识域: {年级: [(知识点标签, 关键词, 章/单元)]}}。"""
    hierarchy = framework.get("hierarchy", {})
    keyword_index = framework.get("keyword_index", {})
    lib: Dict[str, Dict[str, list]] = {}
    for dom, grades in hierarchy.items():
        for grade, chapters in grades.items():
            for chapter, tags in chapters.items():
                for tag in tags:
                    kw = keyword_index.get(tag, "")
                    lib.setdefault(dom, {}).setdefault(grade, []).append((tag, kw, chapter))
    return lib


def _lookup_tag_entry(
    tag: str,
    framework: dict,
    *,
    version: Optional[str] = None,
    grade: Optional[str] = None,
    main_tag: Optional[str] = None,
) -> Optional[Dict]:
    """按标签及已确定的域/年级反查归属，避免同名标签跨学段串标。

    索引键与域/年级比较均做空白规范化，兼容数据库中标签名混入异常空白的情况。
    """
    normalized_tag = _normalize_label(tag)
    entries = []
    for indexed_tag, indexed_entries in framework.get("sub_tag_index", {}).items():
        if _normalize_label(indexed_tag) == normalized_tag:
            entries.extend(indexed_entries)
    matched = [
        entry for entry in entries
        if (version is None or _normalize_label(entry.get("version")) == _normalize_label(version))
        and (grade is None or _normalize_label(entry.get("grade")) == _normalize_label(grade))
        and (main_tag is None or entry.get("main_tag") == main_tag)
    ]
    if len(matched) != 1:
        return None
    return {
        "version": matched[0].get("version", ""),
        "grade": matched[0].get("grade", ""),
        "main_tag": matched[0].get("main_tag", ""),
        "tag": normalized_tag,
    }


# ---------------------------------------------------------------------------
# GPT 客户端（kuaipao 中转，配置来自 .env 的 GPTsAPI_*）
# ---------------------------------------------------------------------------

_gpt_client = None


def _get_gpt_client():
    """获取 OpenAI 兼容客户端（GPTsAPI 中转）。"""
    global _gpt_client
    if _gpt_client is not None:
        return _gpt_client
    from openai import OpenAI
    api_key = get_image_api_key()
    base_url = get_image_base_url()
    if not api_key or not base_url:
        _log("缺少 GPTsAPI_KEY / GPTsAPI_BASE 环境变量，无法使用 LLM 识别", "WARN")
        return None
    _gpt_client = OpenAI(api_key=api_key, base_url=base_url, timeout=120)
    return _gpt_client


_backup_gpt_client = None


def _get_backup_gpt_client():
    """获取备用模型客户端（BACKUP_MODEL_*，默认模型超时/网络异常时切换）。"""
    global _backup_gpt_client
    if _backup_gpt_client is not None:
        return _backup_gpt_client
    from openai import OpenAI
    api_key = get_backup_api_key()
    base_url = get_backup_base_url()
    if not api_key or not base_url:
        _log("缺少 BACKUP_MODEL_API_KEY / BACKUP_MODEL_BASE_URL 环境变量，备用模型不可用", "WARN")
        return None
    _backup_gpt_client = OpenAI(api_key=api_key, base_url=base_url, timeout=120)
    return _backup_gpt_client


def _get_model() -> str:
    """返回 LLM 识别使用的模型名（默认 gpt-5.5）。"""
    return os.getenv("GPTsAPI_CHAT_MODEL", "gpt-5.5")


SYSTEM_PROMPT = (
    "你是一名小学和初中数学知识点分类专家。只能依据用户提示中列出的远程数据库标签进行判断，"
    "不判断教材版本，不补造标签。必须先识别题型结构，再判断核心数学概念；题型结构优先于可选解法。"
    "只有题面明确要求或给出列方程、解方程、设未知数等证据时，才能将应用题归入方程标签。"
    "若一道题确由多个不同知识域（如“方程与不等式”+“统计与概率”）的核心概念组合而成，"
    "且主标签无法覆盖全部考查点，才判定为多知识点组合并给出第二知识域；"
    "单知识点题、或仅是同一知识域内部的延伸，不得判为多知识点组合。"
    "判定把握不足时，在 JSON 中如实给出较低的 confidence（0~1），不要为填满字段强行输出低置信标签。"
)


def _chat_once(client, model_name: str, content: str) -> Optional[str]:
    """单次调用指定模型（temperature=0 不被接受时降级为默认参数重试）。"""
    kwargs = dict(
        model=model_name,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
    )
    try:
        resp = client.chat.completions.create(temperature=0, **kwargs)
    except Exception:
        resp = client.chat.completions.create(**kwargs)
    if not hasattr(resp, "choices") or not resp.choices:
        # 上游返回了非标准对象（如字符串错误/代理纯文本），记录形态便于排查，不盲取
        _log(f"GPT 返回异常形态: {type(resp).__name__} {str(resp)[:120]}", "WARN")
        return None
    return resp.choices[0].message.content


def _chat_sync(content: str) -> Optional[str]:
    """同步调用 GPT（在线程池中执行）。默认模型超时/网络异常时切备用模型完整重跑一次。"""
    client = _get_gpt_client()
    if client is None:
        return None
    try:
        return _chat_once(client, _get_model(), content)
    except Exception as e:
        # 仅"确定超时"（Timeout / ConnectionError / HTTP 524）才切备用，4xx 内容类错误不切
        if is_backup_configured() and is_timeout_error(e):
            backup_client = _get_backup_gpt_client()
            if backup_client is not None:
                _log(
                    f"默认模型调用超时/网络异常，切换到备用模型 {get_backup_model()} 重试: "
                    f"{type(e).__name__}: {str(e)[:150]}",
                    "WARN",
                )
                try:
                    return _chat_once(backup_client, get_backup_model(), content)
                except Exception as e2:
                    _log(f"备用模型调用失败: {type(e2).__name__}: {str(e2)[:150]}", "WARN")
                    return None
        _log(f"GPT 调用失败: {type(e).__name__}: {str(e)[:150]}", "WARN")
        return None


async def _chat(content: str) -> Optional[str]:
    """异步执行同步 GPT 调用。"""
    return await asyncio.to_thread(_chat_sync, content)


def _parse_json(text: str) -> Optional[dict]:
    """从 LLM 输出文本中解析第一个 JSON 对象；解析失败返回 None。"""
    if not text:
        return None
    text = re.sub(r"```(json)?", "", str(text)).strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def _safe_conf(obj) -> float:
    """从 LLM 输出的 JSON 中安全解析 confidence（0~1），缺省 0.7 以保证行为不回归。"""
    try:
        c = float((obj or {}).get("confidence", 0.7))
    except (TypeError, ValueError):
        c = 0.7
    return max(0.0, min(1.0, c))


# ---------------------------------------------------------------------------
# 两步识别提示词构建
# ---------------------------------------------------------------------------

def _build_domain_grade_skeleton(framework: dict) -> Dict[str, Dict[str, list]]:
    """构建「知识域 → 年级 → 章/单元」骨架，仅含结构层级不含知识点子标签。

    用于第一步（判域 + 年级）候选概览的瘦身：step1 只需选 域 与 年级，
    无需浏览每个章下的全部知识点子标签。给出章/单元层级既能削减大量 token 噪声，
    又能保留跨域同名章（如 小数乘法 / 三角形）的歧义提示，配合规则 10 纠偏。
    输出按固定 DOMAIN_ORDER / GRADE_ORDER，保证跨缓存命中时 prompt 稳定一致。
    """
    hierarchy = framework.get("hierarchy", {})
    skeleton: Dict[str, Dict[str, list]] = {}
    for dom in DOMAIN_ORDER:
        grades = hierarchy.get(dom, {}) or {}
        if not grades:
            continue
        for grade in GRADE_ORDER:
            chapters = grades.get(grade, {}) or {}
            if not chapters:
                continue
            skeleton.setdefault(dom, {})[grade] = list(chapters.keys())
    return skeleton


def _grade_hint_from_numbers(question: str) -> str:
    """根据题面数字量级给出确定的年级提示（代码计算，不依赖 LLM 推断）。"""
    nums = [int(n) for n in re.findall(r"-?\d+(?:\.\d+)?", question) if n.lstrip("-").isdigit()]
    if not nums:
        return "（题面无显著数字量级信号）"
    max_n = max(nums)
    if max_n >= 100 or any(w in question for w in ("百", "千", "万")):
        return (
            f"【数字量级】题中出现不小于100的数（最大为{max_n}）或含百/千/万，"
            "必为万以内/多位数运算，年级不低于三上；不得因题型简单下拉到一下/二下/二上。"
        )
    if max_n <= 20:
        has_arith = any(w in question for w in (
            "一共", "共有", "求和", "比", "多", "少", "还剩", "剩下", "差", "加", "减", "颗", "个", "只", "元", "米", "厘米"
        ))
        if has_arith:
            return (
                "【数字量级】题中所有数均≤20，属20以内加减范围：出现“一共有/共有/求和/比…多”等加法语义"
                "→ 一上 20以内的进位加法；出现“还剩/剩下/比…少/差”等减法语义 → 一下 20以内的退位减法。"
            )
        return "（数字较小但题面为代数/几何内容，按核心概念判年级，不受小数字影响）"
    return f"（数字量级中等，最大数{max_n}，按概念判断年级）"


def _build_domain_grade_prompt(question: str, framework: dict) -> str:
    """第一步：知识域 + 年级概览（瘦身版：仅章/单元骨架，不含知识点子标签）。"""
    skeleton = _build_domain_grade_skeleton(framework)
    grade_options = "、".join(framework.get("grades", []))
    lines = []
    for dom, grades in skeleton.items():
        for g, chapters in grades.items():
            lines.append(f"{dom}·{g}: {'、'.join(chapters)}")
    return f"""题目：{question}

【知识域×年级 → 章/单元概览】（仅含远程数据库中的候选结构，不含具体知识点标签）
{chr(10).join(lines)}

【任务】判定题目的 知识域（从上方列表选1个完整中文名）和 年级（从以下可选学段选1个）：{grade_options}。

{_grade_hint_from_numbers(question)}

【关键边界规则】
1. 只能从上方数据库候选中选择知识域和年级，不能使用固定年级映射或历史标签补缺规则。
2. 先抽取题型结构，再判断核心数学概念和解法证据；不要因为题目可以用某种方法求解，就把题型标签替换成该方法标签。
3. 小学与初中出现相同题型（分数、折扣、行程、鸡兔同笼、统计、概率等）时，依据题目使用的数学概念、表示方法和候选标签区分；仅凭“相遇、速度、路程、时间”等词不能判定为方程与不等式或七上。
4. 只有题面明确出现“方程、列方程、解方程、设未知数”等方程证据，或核心任务明确要求建立方程模型时，才选择方程候选；小学算术、线段图、份数关系、比或比例可解决的行程题优先选择小学行程候选。
5. 出现“第一次相遇、第二次相遇、到达端点后掉头、折返、往返”等组合时，优先识别为复合相遇/往返行程结构。
6. 出现“余数、同余、分别除以、除后余数、余数分别是”等除法条件时，优先选择“有余数的除法 / 余数应用”；只有周期、次数或分配语义且没有余数语义时，才选择周期标签（如“周期问题”）。
7. 只有题目明确出现函数、方程组、不等式、平方根、因式分解等初中概念时，才选择相应初中候选。
8. 综合题按题目实际考查的对象和数据库候选确定，不自行推断教材版本或年级。
9. 多知识点组合判定：仅当题目确实由【不同知识域】的核心概念组合（例如同时考查“方程与不等式”与“统计与概率”），且单一主标签无法覆盖全部考查点时，才置 is_multi_point=true 并给出 second_domain（必须是与 domain 不同的另一知识域完整中文名）；单知识点题、或同一知识域内部的延伸（如“函数”内的两种函数）不得判为多知识点组合，is_multi_point 必须为 false。
10. 部分章/单元名称会在多个知识域下同时出现（如“1~5认识与加减、20以内的进位加法、小数乘法、分数运算、四则运算、年月日、三角形、比例、认识图形”等），绝不可仅凭章名判域；必须按题目考查的“核心运算/核心对象”判定：涉及加减乘除、小数、分数、百分数、比和比例运算的归“数与式”；涉及图形、位置、度量、变换、证明的归“图形与几何”；涉及收集整理数据、概率的归“统计与概率”。同一章名在候选中跨域出现时，必须选与题目实质最吻合的域。
11. 年级须与题目使用的数学概念一致，不得因题型简单就下拉到更低年级：一元二次方程（含x²、配方法、公式法、因式分解法解一元二次方程）→ 九上；二元一次方程组 → 七下；一次函数/反比例函数 → 八下/九上；勾股定理（直角三角形边长关系）→ 八上；相似/全等三角形 → 八上/九上；概率（P=m/n公式、摸到…的概率、随机）→ 七下；可能性/确定与不确定 → 五上；三角形内角和（求内角和、内角和180°）→ 八上，仅在“三角形认识/分类/三边关系”时才选四下。
12. 20以内加减按运算语义判年级：“一共有/共有/求和/比…多”等加法语义 → 一上 20以内的进位加法；“还剩/剩下/比…少/差”等减法语义 → 一下 20以内的退位减法。若题中含≥100的数（百/千/万），以上小数字规则让位于“万以内/多位数运算，年级≥三上”。
13. 余角、补角 → 七上 几何图形初步（不归命题·证明与推理，也不归四下三角形）；角平分线（平分∠）按上下文：在三角形内问线段/边长/高/中线 → 八上 三角形/三角形的高、中线与角平分线，否则 → 七上 几何图形初步/角的度量与角平分线。

输出纯净 JSON：{{"is_math_problem": true, "domain": "", "grade": "", "grade_range": "", "is_multi_point": false, "second_domain": null, "confidence": 0.0, "reasoning": "30字内"}}"""


def _build_tag_prompt(
    question: str,
    domain: str,
    grade: str,
    framework: dict,
    candidate_tags: Optional[list] = None,
) -> str:
    """第二步：在确定知识域+年级内选知识点标签（带强特征关键词，候选极少）。

    candidate_tags 非空时（RAG 锁定模式）：候选列表被替换为 Top-K 召回结果，
    并在 prompt 中强制「只能从候选中选择，禁止输出候选外标签」，实现候选锁定。
    """
    lib = _build_tag_lib(framework)
    if candidate_tags:
        kw_index = framework.get("keyword_index", {}) or {}
        cand = [(tag, kw_index.get(tag, "") or "", "") for tag in candidate_tags]
    else:
        cand = lib.get(domain, {}).get(grade, [])
    cands = "\n".join(f"- {t}〔{k}〕" for t, k, _ in cand)
    lock_line = (
        f"\n【锁定范围】以下 {len(candidate_tags)} 个候选为系统已召回结果，【必须且只能】从中选择 1 个，"
        "禁止输出候选之外的标签名，禁止新增或编造标签。"
        if candidate_tags
        else ""
    )
    return f"""题目：{question}

【已判定】知识域: {domain}｜年级: {grade}
【候选标签】（只能从以下选择 1 个）{lock_line}
{cands}

【选择规则】
1. 先按题型结构选择标签，再参考〔强特征关键词〕，不能仅按生活词或可选解法选择。
2. 出现“余数、同余、分别除以、除后余数、余数分别是”等条件 → 选择“余数应用”（位于 数与式/二下·三下 有余数的除法），不选周期类标签。
3. 出现“第一次相遇+第二次相遇+掉头/折返/往返”等组合，或普通相遇、追及题 → 选择“行程问题”（位于 方程与不等式/七上·七下 一元一次方程）。
4. 只有明确出现“方程、列方程、解方程、设未知数”或要求建立方程模型时，才选择一元一次方程应用题。
5. 出现"因式分解/分解因式"指令 → 因式分解（不选乘法公式）。
6. 混合四则运算 → 有理数四则运算；仅乘方/科学记数法 → 乘方与科学记数法。
7. 求交点/求最值的一次函数题 → 一次函数与方程/不等式及实际应用；仅问图象性质(k/b/增减/象限/平移) → 一次函数的图象与性质。
8. 二次函数标签选择：
   - 求顶点坐标/对称轴/开口方向/平移 → 二次函数的图象、性质与平移（注意：顶点坐标只是求一个点，不是最值问题）
   - 求面积/求交点坐标 → 二次函数的图象、性质与平移
   - 求最大利润/最大面积/最大值 → 二次函数最值问题
   - 仅问交点与方程根的关系 → 二次函数与一元二次方程
6. 已知三角函数值或一边一角解直角三角形求边/角 → 解直角三角形；仅求 sin/cos/tan 的值 → 锐角三角函数。
7. 综合题（动点/存在性/与几何结合）：主体是抛物线性质应用 → 二次函数的图象、性质与平移，不选"概念"和"与一元二次方程"。
8. "用比例方法解"或"解比例" → 必须选"比例的意义与基本性质"，绝对不选"正比例与反比例"（正比例与反比例仅用于判断是否成正/反比例关系，不解题）
9. 求平均数 → 选"平均数与加权平均数"或"求平均数"；求中位数/众数 → 选"中位数与众数"（"平均数"标签已不存在，不得输出）。
10. 四边形证明题（菱形/矩形/正方形）→ 选"矩形、菱形与正方形"。
11. 中点连线 → 选"三角形中位线"（不选"三角形的高、中线与角平分线"）。
12. 等腰三角形+中线（三线合一证明）→ 选"等腰三角形的性质与判定"（不选"三角形的高、中线与角平分线"）。
13. 求平方根且附带判断无理数 → 选"平方根与算术平方根"（不选"无理数与实数"）。
14. 求概率（直接用P=m/n公式计算）→ 选"列举法求概率"（不选"随机事件"）。
15. 平行四边形证明（含中点条件）→ 选"平行四边形的性质与判定"（不选"三角形中位线"）。
16. 求扇形面积（圆心角+半径，小学公式S=nπr²/360）→ 选"扇形的认识"（不选"弧长与扇形面积"）。

【易错参考示例】（仅作判据参考，不要求复现这些题干）
- 题：“甲、乙从相距100米两地相向而行，第一次相遇后到端点折返再次相遇” → 选“行程问题”（方程与不等式/七上·七下 一元一次方程）
- 题：“一个数除以7余2，除以8余3” → 选“余数应用”（数与式/二下·三下 有余数的除法）
- 题：“圆心角为60°、半径r，求扇形面积” → 选“扇形的认识”（图形与几何）
- 题：“求这组数据的平均数” → 选“平均数与加权平均数”（不选“中位数与众数”）
- 题：“抛物线 y=ax²+bx+c，求最大利润” → 选“二次函数最值问题”
- 题：“用比例方法解 3:x=2:5” → 选“比例的意义与基本性质”（不选“正比例与反比例”）

17. 仅问“对称轴/对称轴方程/开口方向/顶点横坐标”→ 选“二次函数的图象、性质与平移”；严禁选“顶点与对称轴”子标签（它仅用于明确求顶点坐标的题）。
18. 题面仅给出形如 x²-3x+2=0 的一元二次方程且未指定解法 → 选“一元二次方程的概念”（不选具体解法如因式分解法/公式法/配方法）。
19. 题面为“解方程组”类且未强调某特定解法（代入/加减）→ 选“二元一次方程组解法”（不选“代入消元法/加减消元法”等具体方法标签）。
20. 题面出现“角平分线”或“平分∠”：若同时问线段/边长/高/中线（如求MN长度）→ 选“三角形的高、中线与角平分线”（八上 三角形）；若仅为角的度量与角平分线本身 → 选“角的度量与角平分线”（七上 几何图形初步）。
21. “用…证明相似三角形/相似判定”→ 相似判定相关标签（如“相似判定注意”），不选“三大判定”（三大判定多指全等三角形）。
22. 求平均数（平均身高/平均年龄/求这组数据的平均数）→ 选“求平均数”或“平均数与加权平均数”；题同时含概率时，以主计算对象为准，平均类优先归“求平均数”。
23. “能组成直角三角形/以…为边组成直角三角形/三条线段能否组成直角三角形”→ 选“勾股定理在几何中的应用”（八上 勾股定理），不选“命题·证明与推理/逆定理”。

输出纯净 JSON：{{"tag": "标签原文(不带〔〕)", "matched_keyword": "命中词", "confidence": 0.0, "reasoning": "30字内"}}"""


def _build_grade_prompt(question: str, domain: str, framework: dict) -> str:
    """在已确定知识域下，判定年级（用于第二标签组的定域识别）。"""
    lib = _build_tag_lib(framework)
    grade_options = "、".join(framework.get("grades", []))
    lines = []
    for g in framework.get("grades", []):
        if g in lib.get(domain, {}):
            tags = "、".join(t for t, _, _ in lib[domain][g])
            lines.append(f"{domain}·{g}: {tags}")
    return f"""题目：{question}

【{domain} 知识域候选年级 → 标签】
{chr(10).join(lines)}

【任务】判定题目在「{domain}」知识域下的 年级（从以下可选学段选1个）：{grade_options}。

【规则】
1. 仅依据题目使用的数学概念与候选标签判断，不推断教材版本。
2. 小学与初中同名题型（分数、行程、鸡兔同笼、统计、概率等）按题目实际数学概念与候选标签区分年级。

输出纯净 JSON：{{"grade": "", "reasoning": "30字内"}}"""


# ---------------------------------------------------------------------------
# 两步识别主流程
# ---------------------------------------------------------------------------

async def _recognize_with_llm(
    question: str, framework: dict, title: str = "", rag_index=None
) -> Optional[Dict]:
    """两步识别：知识域+年级 → 知识点标签 → 反查章/单元。

    集成 RAG 轻档检索（三档策略）：
    1. 预检直出（0 次 LLM）：向量高分 + 关键词命中 + 标题字符命中 三重确认；
    2. step1 后域内重排：高置信直出（省 step2）/ 中置信锁定 Top-K 候选给 step2；
    3. 低置信：按原两步 LLM 逻辑，失败退关键词兜底。

    返回 {"group": 单标签组, "is_multi_point": bool, "second_domain": str|None}；
    失败（含非数学题）返回 None。
    """
    index = rag_index if rag_index is not None else load_tag_index()

    # RAG 预检：三重确认直出（不调 step1/step2，省 2 次 LLM）
    if index:
        direct = prescreen(index, question, title)
        if direct:
            _log(
                f"RAG 预检直出: 知识域={direct['version']}, 年级={direct['grade']}, "
                f"章/单元={direct['main_tag']}, 知识点标签={direct['sub_tags'][0]}"
            )
            return {
                "group": direct,
                "is_multi_point": False,
                "second_domain": None,
                "source": "prescreen",
                "confidence": 1.0,
            }

    # 第一步: 域 + 年级（含多知识点判定）
    r1 = _parse_json(await _chat(_build_domain_grade_prompt(question, framework)) or "")
    if not r1:
        _log("第一步（知识域+年级）识别失败：无法解析输出", "WARN")
        return None
    if r1.get("is_math_problem") is False:
        _log("判定不是数学题，转入关键词兜底", "INFO")
        return None

    domain = str(r1.get("domain", "")).strip()
    grade = str(r1.get("grade", "")).strip()
    domain = DOMAIN_ALIAS.get(domain, domain)

    domains = framework.get("versions", [])
    grades = framework.get("grades", [])
    if domain not in domains:
        _log(f"知识域不在标准列表中: {domain}", "WARN")
        fixed = _fuzzy_match(domain, domains)
        if not fixed:
            return None
        domain = fixed
    if grade not in grades:
        _log(f"年级不在标准列表中: {grade}", "WARN")
        fixed = _fuzzy_match(grade, grades)
        if not fixed:
            return None
        grade = fixed

    # 第二步: 域内选知识点标签
    lib = _build_tag_lib(framework)
    if not lib.get(domain, {}).get(grade):
        _log(f"标签库中无 {domain}·{grade} 候选", "WARN")
        return None

    # RAG 域内重排（域先验：候选限定在 step1 判定的知识域内；题面+标题两路合并检索）
    locked_tags: Optional[list] = None
    if index:
        cands = search_combined(index, question, title, top_k=15, domain=domain)
        reranked = rerank_candidates(cands, question, title=title, prefer_grade=grade)
        if reranked:
            top = reranked[0]
            if top["score"] >= RAG_DIRECT_MIN and (top["kw_hit"] or top["title_hit"]):
                if top["grade"] != grade:
                    # 候选年级与 step1 判定不一致：不直出，降级走锁定模式（最终年级以 step1 为准）
                    _log(
                        f"RAG 候选年级({top['grade']})与 step1 判定({grade})不一致，"
                        f"不直出，降级锁定候选给 step2"
                    )
                else:
                    # 高置信直出（省 step2）：候选年级与 step1 判定一致才直出
                    entry = _lookup_tag_entry(
                        top["sub_tag"], framework, version=domain, grade=grade
                    )
                    if entry:
                        result = {
                            "version": entry["version"],
                            "grade": entry["grade"],
                            "main_tag": entry["main_tag"],
                            "sub_tags": [entry["tag"]],
                        }
                        _log(
                            f"RAG 域内重排直出: 知识域={result['version']}, 年级={result['grade']}, "
                            f"章/单元={result['main_tag']}, 知识点标签={entry['tag']} "
                            f"(score={top['score']:.2f})"
                        )
                        return {
                            "group": result,
                            "is_multi_point": bool(r1.get("is_multi_point")),
                            "second_domain": (r1.get("second_domain") or None),
                            "source": "rag_direct",
                            "confidence": float(top["score"]),
                        }
            # 锁定候选：仅当 Top-3 内存在字符证据候选（关键词/标题命中），
            # 避免正确标签大概率在候选外时把 LLM 锁死
            if any(c["title_hit"] or c["kw_hit"] for c in reranked[:3]):
                locked_tags = [c["sub_tag"] for c in reranked[:10]]
                _log(
                    f"RAG 域内重排命中证据候选（score={reranked[0]['score']:.2f}），"
                    f"锁定 {len(locked_tags)} 个候选给 LLM"
                )

    r2 = _parse_json(
        await _chat(_build_tag_prompt(question, domain, grade, framework, candidate_tags=locked_tags)) or ""
    )
    tag = str(r2.get("tag", "")).strip() if r2 else ""
    if locked_tags:
        # 锁定模式：校验必须落在锁定候选内；越界尝试模糊修正，失败转兜底（绝不新增标签）
        if tag not in locked_tags:
            if tag:
                _log(f"LLM 输出不在锁定候选内: {tag}（锁定模式，不采信）", "WARN")
            kw_index = framework.get("keyword_index", {}) or {}
            cand_locked = [(t, kw_index.get(t, "") or "", "") for t in locked_tags]
            tag = _resolve_tag_in_group(question, cand_locked, tag) or ""
        if not tag:
            _log("锁定候选内无法解析合法标签，转限定域关键词兜底", "WARN")
            return match_knowledge_tags_by_keyword(
                question, prefer_domain=domain, prefer_grade=grade
            )
        valid_tags = set(locked_tags)
    else:
        valid_tags = {t for t, _, _ in lib[domain][grade]}
        if tag not in valid_tags:
            if tag:
                _log(f"知识点标签不在 {domain}·{grade} 候选中: {tag}", "WARN")
            tag = _resolve_tag_in_group(question, lib[domain][grade], tag) or ""
            if not tag:
                return None

    # 置信度阈值保护：两步置信度偏低时，不盲接受 LLM 结果，转限定域关键词兜底
    conf = _safe_conf(r1)
    if r2:
        conf = min(conf, _safe_conf(r2))
    if conf < 0.6:
        _log(f"两步识别置信度偏低({conf:.2f})，转限定域关键词兜底", "WARN")
        kw = match_knowledge_tags_by_keyword(question, prefer_domain=domain, prefer_grade=grade)
        if kw:
            return kw
        return None

    entry = _lookup_tag_entry(
        tag,
        framework,
        version=domain,
        grade=grade,
    )
    if not entry:
        return None
    result = {
        "version": entry["version"],
        "grade": entry["grade"],
        "main_tag": entry["main_tag"],
        "sub_tags": [entry["tag"]],
    }
    _log(
        f"两步识别成功: 知识域={result['version']}, 年级={result['grade']}, "
        f"章/单元={result['main_tag']}, 知识点标签={tag}"
    )
    return {
        "group": result,
        "is_multi_point": bool(r1.get("is_multi_point")),
        "second_domain": (r1.get("second_domain") or None),
        "source": "rag_locked_llm" if locked_tags else "llm",
        "confidence": float(conf),
    }


def _resolve_tag_in_group(question: str, candidates: list, llm_tag: str) -> Optional[str]:
    """将 LLM 返回的标签校正为候选组内合法标签。

    依次尝试：精确匹配 → 子串模糊匹配 → 强特征关键词命中；全部失败返回 None。
    """
    valid = {t for t, _, _ in candidates}
    if llm_tag in valid:
        return llm_tag
    for t in valid:
        if llm_tag and (t in llm_tag or llm_tag in t):
            return t
    return _match_tag_by_keyword_in_group(question, candidates)


def _match_tag_by_keyword_in_group(question: str, candidates: list) -> Optional[str]:
    """在候选组内用强特征关键词匹配题面，返回命中得分最高的知识点标签。"""
    best = None
    best_score = 0.0
    for tag, kw, _ in candidates:
        score = _keyword_hit_score(kw, question)
        if score > best_score:
            best_score = score
            best = tag
    return best


# ---------------------------------------------------------------------------
# 关键词匹配兜底（无需 API）
# ---------------------------------------------------------------------------

def match_knowledge_tags_by_keyword(
    question: str,
    prefer_domain: Optional[str] = None,
    prefer_grade: Optional[str] = None,
) -> Optional[Dict]:
    """通过强特征关键词/知识点标签匹配识别（兜底方案，无需 API）。

    匹配策略：
    1. 遍历所有知识点标签的强特征关键词，检查是否命中题目文本（按词长加权）
    2. 知识点标签本身出现在题目中也计分
    3. 取总分最高的知识点标签，反查其唯一归属（知识域/年级/章/单元）

    prefer_domain / prefer_grade：若提供，优先在指定 域×年级 内取最高分，
    仅当该域内无命中时才回退到全局，避免跨域同名 sub_tag 被随机归域。
    """
    framework = load_framework()
    if not framework:
        return None
    lib = _build_tag_lib(framework)
    if not lib:
        return None

    scores: Dict[str, float] = {}
    block_reasons = _low_grade_block_reasons(question)
    for dom, grades in lib.items():
        for grade, cands in grades.items():
            if grade in _LOW_GRADE_BLOCK_GRADES and block_reasons:
                continue  # 低年级标签命中高年级特征（反信号），拦截
            for tag, kw, main_tag in cands:
                # 强特征关键词命中（长词权重高，全局兜底加倍计分）
                score = _keyword_hit_score(kw, question, weight=2.0)
                # 知识点标签本身出现在题面也计分
                if len(tag) >= 3 and tag in question:
                    score += len(tag)
                if score > 0:
                    key = (dom, grade, main_tag, tag)
                    scores[key] = scores.get(key, 0) + score

    # 限定域/年级优先（避免跨域同名 sub_tag 被随机归域）
    if prefer_domain:
        pd = _normalize_label(prefer_domain)
        pg = _normalize_label(prefer_grade) if prefer_grade else None
        scoped = {
            k: s for k, s in scores.items()
            if _normalize_label(k[0]) == pd and (pg is None or _normalize_label(k[1]) == pg)
        }
        if scoped:
            scores = scoped

    if not scores:
        # 向量融合兜底：纯字符零命中时，用 RAG 轻档向量检索补一手（仅采信高分，绝不降级）
        index = load_tag_index()
        if index:
            cands = index.search(
                question,
                top_k=3,
                domain=_normalize_label(prefer_domain) if prefer_domain else None,
                grade=_normalize_label(prefer_grade) if prefer_grade else None,
            )
            if cands and cands[0]["score"] >= 0.62:
                # 低年级标签同样受反信号拦截（防向量兜底绕回一上/一下）
                if cands[0]["grade"] in _LOW_GRADE_BLOCK_GRADES and block_reasons:
                    return None
                top = cands[0]
                entry = _lookup_tag_entry(
                    top["sub_tag"],
                    framework,
                    version=top["version"],
                    grade=top["grade"],
                    main_tag=top["main_tag"],
                )
                if entry:
                    result = {
                        "version": entry["version"],
                        "grade": entry["grade"],
                        "main_tag": entry["main_tag"],
                        "sub_tags": [top["sub_tag"]],
                    }
                    _log(
                        f"向量融合兜底: 知识域={result['version']}, 年级={result['grade']}, "
                        f"章/单元={result['main_tag']}, 知识点标签={top['sub_tag']} "
                        f"(score={cands[0]['score']:.2f})"
                    )
                    return result
        return None

    best_dom, best_grade, best_main_tag, best_tag = max(
        scores, key=lambda key: scores[key]
    )
    entry = _lookup_tag_entry(
        best_tag,
        framework,
        version=best_dom,
        grade=best_grade,
        main_tag=best_main_tag,
    )
    if not entry:
        return None
    result = {
        "version": entry["version"],
        "grade": entry["grade"],
        "main_tag": entry["main_tag"],
        "sub_tags": [best_tag],
    }
    _log(
        f"关键词匹配结果: 知识域={result['version']}, 年级={result['grade']}, "
        f"章/单元={result['main_tag']}, 知识点标签={best_tag}"
    )
    return result


# ---------------------------------------------------------------------------
# 对外主入口
# ---------------------------------------------------------------------------

async def _recognize_group_for_domain(
    question: str, framework: dict, domain: str
) -> Optional[Dict]:
    """在已确定知识域下，识别一个标签组（先判年级，再选知识点标签）。

    用于多知识点题目的【第二标签组】识别。返回单标签组，或 None。
    """
    lib = _build_tag_lib(framework)
    if domain not in lib:
        return None

    # 第一步（域内定年级）
    rg = _parse_json(await _chat(_build_grade_prompt(question, domain, framework)) or "")
    grade = ""
    if rg:
        grade = str(rg.get("grade", "")).strip()
    grades = framework.get("grades", [])
    if grade not in grades:
        grade = _fuzzy_match(grade, grades) or ""
    if not grade or not lib.get(domain, {}).get(grade):
        # 年级无法确定：改用强特征关键词直接在该域各年级候选内命中
        best_grade = None
        best_tag = None
        best_score = 0
        for g, cands in lib[domain].items():
            hit = _match_tag_by_keyword_in_group(question, cands)
            if hit:
                score = len(hit)
                if score > best_score:
                    best_score = score
                    best_grade = g
                    best_tag = hit
        if not best_tag:
            return None
        grade = best_grade
        tag = best_tag
    else:
        # 第二步（域内选知识点标签）
        r2 = _parse_json(
            await _chat(_build_tag_prompt(question, domain, grade, framework)) or ""
        )
        tag = str(r2.get("tag", "")).strip() if r2 else ""
        tag = _resolve_tag_in_group(question, lib[domain][grade], tag) or ""
        if not tag:
            return None

    entry = _lookup_tag_entry(tag, framework, version=domain, grade=grade)
    if not entry:
        return None
    result = {
        "version": entry["version"],
        "grade": entry["grade"],
        "main_tag": entry["main_tag"],
        "sub_tags": [entry["tag"]],
    }
    _log(
        f"定域识别成功(第二标签): 知识域={result['version']}, 年级={result['grade']}, "
        f"章/单元={result['main_tag']}, 知识点标签={tag}"
    )
    return result


async def _recognize_primary_with_decision(
    question: str, framework: dict, title: str = "", rag_index=None
) -> tuple:
    """识别主标签组并附带两步识别的决策信息（供第二标签判断与识别日志）。

    Args:
        question: 题目文本
        framework: 标签框架
        title: 教学内容标题（RAG 标题交叉验证信号，可空）

    Returns:
        (primary_group, decision, source)
        - primary_group: 主标签组结果，或 None
        - decision: 两步 LLM 的原始结果（含 is_multi_point / second_domain / source / confidence），
          确定性路由或关键词兜底命中时为 None
        - source: 识别来源（route / prescreen / rag_direct / rag_locked_llm / llm / keyword / none）
    """
    primary = _match_strong_special_case(question, framework)
    if primary:
        return primary, None, "route"

    decision = None
    source = "none"
    try:
        res = await asyncio.wait_for(
            _recognize_with_llm(question, framework, title=title, rag_index=rag_index), timeout=180
        )
    except asyncio.TimeoutError:
        _log("LLM 识别超时（180秒）", "WARN")
        res = None
    except Exception as e:
        _log(f"LLM 识别失败: {e}", "WARN")
        res = None

    if res:
        primary = res.get("group")
        decision = res
        source = res.get("source", "llm")
    if primary is None:
        primary = match_knowledge_tags_by_keyword(question)
        source = "keyword" if primary else "none"
    return primary, decision, source


async def _recognize_primary(
    question: str, framework: dict, title: str = "", rag_index=None
) -> Optional[Dict]:
    """识别主标签组（单组）：确定性路由 → RAG 检索/两步 LLM → 关键词兜底。"""
    primary, _, _ = await _recognize_primary_with_decision(
        question, framework, title=title, rag_index=rag_index
    )
    return primary


async def inject_knowledge_tags(
    question: str, llm=None, title: str = None, rag_index=None
) -> Optional[Dict]:
    """为题目注入知识点标签（主标签组，向后兼容单组返回）。

    优先使用 RAG 轻档检索与两步 LLM 识别；失败时使用远程数据库候选中的关键词匹配。

    Args:
        question: 题目文本
        llm: 兼容参数，忽略（识别使用 GPTsAPI 配置）
        title: 教学内容标题（可选，用于 RAG 标题交叉验证，可显著提升高置信直出率）
        rag_index: 指定 TagIndex 覆盖全局索引（评测时切换后端用），None 用默认索引

    Returns:
        {"version": 知识域, "grade": 年级, "main_tag": 章/单元, "sub_tags": [知识点标签]}
    """
    if not question or not question.strip():
        return None

    question = question.strip()
    framework = load_framework()
    if not framework:
        _log("标签框架未加载，跳过知识点标签注入", "WARN")
        return None

    return await _recognize_primary(question, framework, title=title or "", rag_index=rag_index)


async def inject_knowledge_tags_full(
    question: str, llm=None, title: str = None, return_meta: bool = False, rag_index=None
) -> Optional[Dict]:
    """为题目注入知识点标签（双标签组：主标签 + 可选第二标签）。

    规则（模型层强制）：
    - 第二标签仅在模型确认题目为多知识点组合（is_multi_point）且第二知识域
      与主标签知识域不同时才生成；
    - 每种知识域最多一个标签；标签总数不超过两种。

    Args:
        question: 题目文本
        llm: 兼容参数，忽略（识别使用 GPTsAPI 配置）
        title: 教学内容标题（可选，用于 RAG 标题交叉验证）
        return_meta: 为 True 时在返回中附加 "_meta"（识别来源/置信度/多知识点/耗时），
            供准确率评测与识别日志使用，不影响主调用方。
        rag_index: 指定 TagIndex 覆盖全局索引（用于评测时切换 lexical/semantic 后端 A/B），
            None 时使用进程级默认索引。

    Returns:
        {"primary": 主标签组, "second": 第二标签组|None}
        return_meta=True 时额外包含 "_meta": {source, confidence, is_multi_point, elapsed_ms}
    """
    if not question or not question.strip():
        return None

    question = question.strip()
    framework = load_framework()
    if not framework:
        _log("标签框架未加载，跳过知识点标签注入", "WARN")
        return None

    # 1) 主标签组（确定性路由 / RAG 检索+两步 LLM / 关键词兜底）
    import time as _time
    _t0 = _time.time()
    primary, decision, source = await _recognize_primary_with_decision(
        question, framework, title=title or "", rag_index=rag_index
    )
    if not primary:
        result = {"primary": None, "second": None}
        if return_meta:
            result["_meta"] = {
                "source": source, "confidence": None,
                "is_multi_point": False, "elapsed_ms": int((_time.time() - _t0) * 1000),
            }
        return result

    # 2) 第二标签组（仅模型确认的多知识点组合，且知识域不同）
    second = None
    if decision and decision.get("is_multi_point") and decision.get("second_domain"):
        sd = DOMAIN_ALIAS.get(decision["second_domain"], decision["second_domain"])
        sd = _normalize_label(sd)
        domains = [_normalize_label(d) for d in framework.get("versions", [])]
        primary_version = _normalize_label(primary.get("version", ""))
        if sd in domains and sd != primary_version:
            try:
                second = await asyncio.wait_for(
                    _recognize_group_for_domain(question, framework, sd), timeout=180
                )
            except Exception as e:
                _log(f"第二标签识别失败: {e}", "WARN")
                second = None
            if second and _normalize_label(second.get("version", "")) == primary_version:
                second = None  # 安全兜底：绝不允许两标签同域

    result = {"primary": primary, "second": second}
    if return_meta:
        result["_meta"] = {
            "source": source,
            "confidence": (decision or {}).get("confidence"),
            "is_multi_point": bool((decision or {}).get("is_multi_point")),
            "elapsed_ms": int((_time.time() - _t0) * 1000),
        }
    return result


def build_knowledge_tags_from_existing(main_tag: str, sub_tags: Optional[list]) -> Optional[Dict]:
    """从已有的 章/单元 + 知识点标签 反查知识域/年级，构造 knowledge_tags（不调 LLM）。

    用于补全 knowledge_tags 为空但已有旧字段的题目。
    """
    if not main_tag or not sub_tags:
        return None
    framework = load_framework()
    for st in sub_tags:
        entry = _lookup_tag_entry(st, framework, main_tag=main_tag)
        if entry:
            result = {
                "version": entry["version"],
                "grade": entry["grade"],
                "main_tag": entry["main_tag"],
                "sub_tags": sub_tags,
            }
            _log(
                f"从已有标签反查: 知识域={result['version']}, 年级={result['grade']}, "
                f"章/单元={result['main_tag']}"
            )
            return result
    return None


def enrich_all_matches(result: dict, framework: Optional[dict] = None) -> dict:
    """兼容保留：新标签体系为单标签组，不再生成 all_matches，直接原样返回。"""
    if isinstance(result, dict):
        result.pop("all_matches", None)
        result.pop("main_tags", None)
    return result


# ---------------------------------------------------------------------------
# 批量注入工具（用于补打历史数据）
# ---------------------------------------------------------------------------

async def inject_for_metadata_file(metadata_path: Path, llm=None) -> bool:
    """为单个 metadata.json 文件注入知识点标签。

    Returns: True 表示已更新（或已有标签），False 表示跳过/失败。
    """
    try:
        with open(metadata_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)
    except Exception as e:
        _log(f"读取 metadata 失败: {metadata_path}: {e}", "WARN")
        return False

    # 已有 knowledge_tags 则跳过
    if metadata.get("knowledge_tags"):
        return True

    # 非数学题跳过
    if metadata.get("is_math_problem") is False:
        return True

    question = metadata.get("question") or metadata.get("prompt") or ""
    if not question.strip():
        return False

    tags = await inject_knowledge_tags(question)
    if not tags:
        _log(f"未能识别知识点标签: {metadata_path.parent.name}", "WARN")
        return False

    metadata["knowledge_tags"] = tags
    metadata["knowledge_tags_updated_at"] = datetime.utcnow().isoformat() + "Z"

    try:
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        _log(f"已注入知识点标签: {metadata_path.parent.name} -> {tags['main_tag']}")
        return True
    except Exception as e:
        _log(f"写入 metadata 失败: {metadata_path}: {e}", "WARN")
        return False

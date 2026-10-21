import sys
from pathlib import Path

import pytest

backend_dir = Path(__file__).resolve().parents[2]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import knowledge_tag_injector as injector


def make_framework():
    return {
        "versions": ["数与式"],
        "grades": ["五下", "六上"],
        "hierarchy": {
            "数与式": {
                "五下": {"分数": ["公共标签"]},
                "六上": {"整数": ["公共标签", "分数运算"]},
            }
        },
        "keyword_index": {
            "公共标签": "公共标签",
            "分数运算": "分数运算",
        },
        "sub_tag_index": {
            "公共标签": [
                {"version": "数与式", "grade": "五下", "main_tag": "分数"},
                {"version": "数与式", "grade": "六上", "main_tag": "整数"},
            ],
            "分数运算": [
                {"version": "数与式", "grade": "六上", "main_tag": "整数"},
            ],
        },
    }


def test_domain_grade_prompt_uses_framework_grades():
    prompt = injector._build_domain_grade_prompt("计算题", make_framework())

    assert "五下、六上" in prompt
    assert "六上/六下/七上/七下/八上/八下/九上/九下 选1" not in prompt


@pytest.mark.asyncio
async def test_llm_tag_lookup_stays_in_selected_grade(monkeypatch):
    responses = iter(
        [
            '{"is_math_problem": true, "domain": "数与式", "grade": "六上"}',
            '{"tag": "公共标签"}',
        ]
    )

    async def fake_chat(_prompt):
        return next(responses)

    monkeypatch.setattr(injector, "_chat", fake_chat)

    result = await injector._recognize_with_llm("计算公共标签", make_framework())

    assert result == {
        "version": "数与式",
        "grade": "六上",
        "main_tag": "整数",
        "sub_tags": ["公共标签"],
    }


def test_keyword_fallback_scores_full_tag_path(monkeypatch):
    framework = make_framework()
    monkeypatch.setattr(injector, "load_framework", lambda: framework)

    result = injector.match_knowledge_tags_by_keyword("请计算分数运算")

    assert result == {
        "version": "数与式",
        "grade": "六上",
        "main_tag": "整数",
        "sub_tags": ["分数运算"],
    }


def test_direct_tag_result_rejects_cross_grade_duplicate():
    result = injector._build_direct_tag_result(make_framework(), "公共标签")

    assert result is None


def make_special_framework():
    return {
        "versions": ["数与式", "方程与不等式", "图形与几何", "综合与实践"],
        "grades": ["四下", "六上", "七上", "七下", "八上"],
        "hierarchy": {
            "数与式": {
                "六上": {
                    "数的运算基础": ["余数与同余问题"],
                    "行程问题": ["相遇与追及问题"],
                },
            },
            "方程与不等式": {
                "七上": {"一元一次方程": ["一元一次方程应用题", "相遇与追及问题"]},
                "七下": {"二元一次方程组": ["二元一次方程组应用题"]},
            },
            "图形与几何": {
                "八上": {"全等三角形": ["全等三角形判定"]},
            },
            "综合与实践": {
                "四下": {"数学广角——鸡兔同笼": ["假设法解决"]},
            },
        },
        "keyword_index": {},
        "sub_tag_index": {
            "余数与同余问题": [
                {"version": "数与式", "grade": "六上", "main_tag": "数的运算基础"},
            ],
            "相遇与追及问题": [
                {"version": "数与式", "grade": "六上", "main_tag": "行程问题"},
                {"version": "方程与不等式", "grade": "七上", "main_tag": "一元一次方程"},
            ],
            "一元一次方程应用题": [
                {"version": "方程与不等式", "grade": "七上", "main_tag": "一元一次方程"},
            ],
            "二元一次方程组应用题": [
                {"version": "方程与不等式", "grade": "七下", "main_tag": "二元一次方程组"},
            ],
            "全等三角形判定": [
                {"version": "图形与几何", "grade": "八上", "main_tag": "全等三角形"},
            ],
            "假设法解决": [
                {"version": "综合与实践", "grade": "四下", "main_tag": "数学广角——鸡兔同笼"},
            ],
        },
    }


@pytest.mark.asyncio
async def test_remainder_problem_uses_remainder_tag_without_llm(monkeypatch):
    framework = make_special_framework()
    monkeypatch.setattr(injector, "load_framework", lambda: framework)

    async def fail_chat(_prompt):
        raise AssertionError("deterministic route must not call LLM")

    monkeypatch.setattr(injector, "_chat", fail_chat)
    result = await injector.inject_knowledge_tags(
        "有一个自然数，用它分别去除以5、7、9，得到的余数分别是3、4、5，求这个自然数最小是多少。"
    )

    assert result == {
        "version": "数与式",
        "grade": "六上",
        "main_tag": "数的运算基础",
        "sub_tags": ["余数与同余问题"],
    }


@pytest.mark.asyncio
async def test_double_equilateral_triangle_problem_uses_congruence_route_without_llm(monkeypatch):
    framework = make_special_framework()
    monkeypatch.setattr(injector, "load_framework", lambda: framework)

    async def fail_chat(_prompt):
        raise AssertionError("deterministic route must not call LLM")

    monkeypatch.setattr(injector, "_chat", fail_chat)
    result = await injector.inject_knowledge_tags(
        "已知△ABC和△CDE都是等边三角形，且点B、C、D在同一直线上，"
        "点A和点E在BD的同侧。连接AD和BE，相交于点O。"
    )

    assert result == {
        "version": "图形与几何",
        "grade": "八上",
        "main_tag": "全等三角形",
        "sub_tags": ["全等三角形判定"],
    }


@pytest.mark.asyncio
async def test_double_equilateral_triangle_problem_without_triangle_symbol_uses_congruence_route(monkeypatch):
    framework = make_special_framework()
    monkeypatch.setattr(injector, "load_framework", lambda: framework)

    async def fail_chat(_prompt):
        raise AssertionError("deterministic route must not call LLM")

    monkeypatch.setattr(injector, "_chat", fail_chat)
    result = await injector.inject_knowledge_tags(
        "已知ABC和CDE都是等边三角形，且点B、C、D在同一直线上，"
        "点A和点E在BD的同侧。连接AD和BE，相交于点O。"
    )

    assert result == {
        "version": "图形与几何",
        "grade": "八上",
        "main_tag": "全等三角形",
        "sub_tags": ["全等三角形判定"],
    }


@pytest.mark.asyncio
async def test_complex_meeting_problem_uses_primary_route_without_llm(monkeypatch):
    framework = make_special_framework()
    monkeypatch.setattr(injector, "load_framework", lambda: framework)

    async def fail_chat(_prompt):
        raise AssertionError("deterministic route must not call LLM")

    monkeypatch.setattr(injector, "_chat", fail_chat)
    result = await injector.inject_knowledge_tags(
        "甲、乙两人分别从A、B两地同时出发，相向而行。第一次相遇时，相遇点距离A地800米。"
        "两人相遇后继续前进，分别到达B、A两地后立即掉头返回，第二次相遇时，"
        "相遇点距离B地300米。请问：A、B两地之间的路程是多少米？"
    )

    assert result == {
        "version": "数与式",
        "grade": "六上",
        "main_tag": "行程问题",
        "sub_tags": ["相遇与追及问题"],
    }


@pytest.mark.asyncio
async def test_basic_meeting_problem_prefers_primary_route_without_llm(monkeypatch):
    framework = make_special_framework()
    monkeypatch.setattr(injector, "load_framework", lambda: framework)

    async def fail_chat(_prompt):
        raise AssertionError("deterministic route must not call LLM")

    monkeypatch.setattr(injector, "_chat", fail_chat)
    result = await injector.inject_knowledge_tags(
        "甲乙两车相向而行，甲车每小时行60千米，乙车每小时行40千米，"
        "两车相距200千米，几小时后相遇？"
    )

    assert result == {
        "version": "数与式",
        "grade": "六上",
        "main_tag": "行程问题",
        "sub_tags": ["相遇与追及问题"],
    }


@pytest.mark.asyncio
async def test_grass_grazing_problem_uses_two_variable_route_without_llm(monkeypatch):
    framework = make_special_framework()
    monkeypatch.setattr(injector, "load_framework", lambda: framework)

    async def fail_chat(_prompt):
        raise AssertionError("deterministic route must not call LLM")

    monkeypatch.setattr(injector, "_chat", fail_chat)
    result = await injector.inject_knowledge_tags(
        "一片牧草，每天匀速生长。这片牧草可供10头牛吃20天，或者供15头牛吃10天。"
        "问：可供25头牛吃几天？若想使这片牧草永远吃不完，最多只能放牧多少头牛？"
    )

    assert result == {
        "version": "方程与不等式",
        "grade": "七下",
        "main_tag": "二元一次方程组",
        "sub_tags": ["二元一次方程组应用题"],
    }


@pytest.mark.asyncio
async def test_meeting_problem_normalizes_indexed_tag_with_whitespace(monkeypatch):
    """真实数据库中同名标签名混入异常空白时，结果仍返回规范标签名。"""
    framework = make_special_framework()
    framework["sub_tag_index"] = {
        "相 遇与追及问题": [
            {"version": "数与式", "grade": "六上", "main_tag": "行程问题"},
        ],
        "相遇与追及问题": [
            {"version": "方程与不等式", "grade": "七上", "main_tag": "一元一次方程"},
        ],
    }
    monkeypatch.setattr(injector, "load_framework", lambda: framework)

    async def fail_chat(_prompt):
        raise AssertionError("deterministic route must not call LLM")

    monkeypatch.setattr(injector, "_chat", fail_chat)
    result = await injector.inject_knowledge_tags(
        "甲乙两车相向而行，甲车每小时行60千米，乙车每小时行40千米，"
        "两车相距200千米，几小时后相遇？"
    )

    assert result == {
        "version": "数与式",
        "grade": "六上",
        "main_tag": "行程问题",
        "sub_tags": ["相遇与追及问题"],
    }


@pytest.mark.asyncio
async def test_meeting_problem_with_equation_evidence_uses_equation_route(monkeypatch):
    """行程结构 + 明确方程证据时，优先归入七上一元一次方程应用题。"""
    framework = make_special_framework()
    monkeypatch.setattr(injector, "load_framework", lambda: framework)

    async def fail_chat(_prompt):
        raise AssertionError("deterministic route must not call LLM")

    monkeypatch.setattr(injector, "_chat", fail_chat)
    result = await injector.inject_knowledge_tags(
        "甲乙两车从相距200千米的两地同时相向而行，甲车每小时行60千米，"
        "乙车每小时行40千米，设未知数列方程求解几小时后相遇。"
    )

    assert result == {
        "version": "方程与不等式",
        "grade": "七上",
        "main_tag": "一元一次方程",
        "sub_tags": ["一元一次方程应用题"],
    }


def test_duplicate_meeting_tag_resolves_to_middle_school_path():
    """同名“相遇与追及问题”标签按完整路径解析到七上一元一次方程。"""
    framework = make_special_framework()
    result = injector._build_path_tag_result(
        framework, "方程与不等式", "七上", "一元一次方程", "相遇与追及问题"
    )

    assert result == {
        "version": "方程与不等式",
        "grade": "七上",
        "main_tag": "一元一次方程",
        "sub_tags": ["相遇与追及问题"],
    }


@pytest.mark.asyncio
async def test_vehicle_seat_problem_uses_remote_path_without_llm(monkeypatch):
    framework = make_special_framework()
    monkeypatch.setattr(injector, "load_framework", lambda: framework)

    async def fail_chat(_prompt):
        raise AssertionError("deterministic route must not call LLM")

    monkeypatch.setattr(injector, "_chat", fail_chat)
    result = await injector.inject_knowledge_tags(
        "学校组织七年级师生参观。如果租用45座的客车，会有15人没有座位；如果租用60座的客车，会空出30个座位，且车辆数少2辆。求师生人数和原计划车辆数。"
    )

    assert result == {
        "version": "方程与不等式",
        "grade": "七上",
        "main_tag": "一元一次方程",
        "sub_tags": ["一元一次方程应用题"],
    }


@pytest.mark.asyncio
async def test_chicken_three_legged_cat_problem_uses_remote_path(monkeypatch):
    framework = make_special_framework()
    monkeypatch.setattr(injector, "load_framework", lambda: framework)

    async def fail_chat(_prompt):
        raise AssertionError("deterministic route must not call LLM")

    monkeypatch.setattr(injector, "_chat", fail_chat)
    result = await injector.inject_knowledge_tags(
        "鸡和三脚猫共有20个头，一共有52只脚，求鸡和三脚猫各有多少只。"
    )

    assert result == {
        "version": "综合与实践",
        "grade": "四下",
        "main_tag": "数学广角——鸡兔同笼",
        "sub_tags": ["假设法解决"],
    }


@pytest.mark.asyncio
async def test_two_kind_sales_problem_prefers_equation_system(monkeypatch):
    framework = make_special_framework()
    framework["hierarchy"]["方程与不等式"]["七下"] = {
        "二元一次方程组": ["二元一次方程组应用题"]
    }
    framework["grades"].append("七下")
    framework["sub_tag_index"]["二元一次方程组应用题"] = [
        {
            "version": "方程与不等式",
            "grade": "七下",
            "main_tag": "二元一次方程组",
        }
    ]
    monkeypatch.setattr(injector, "load_framework", lambda: framework)

    async def fail_chat(_prompt):
        raise AssertionError("deterministic route must not call LLM")

    monkeypatch.setattr(injector, "_chat", fail_chat)
    result = await injector.inject_knowledge_tags(
        "某服装店用4000元购进甲、乙两种新款夏装共80件。甲种进价每件40元，乙种进价每件80元；甲按售价出售，乙在售价基础上加价10%。全部售完后求获利。"
    )

    assert result == {
        "version": "方程与不等式",
        "grade": "七下",
        "main_tag": "二元一次方程组",
        "sub_tags": ["二元一次方程组应用题"],
    }


def test_special_route_requires_remote_path():
    framework = make_special_framework()
    framework["sub_tag_index"].pop("假设法解决")

    result = injector._match_strong_special_case(
        "鸡和兔共有35只头，数脚共有94只，求鸡和兔各有多少只。", framework
    )

    assert result is None


@pytest.mark.asyncio
async def test_primary_question_is_not_routed_by_legacy_fraction_rule(monkeypatch):
    framework = {
        "versions": ["数与式"],
        "grades": ["五下", "六上"],
        "hierarchy": {
            "数与式": {
                "五下": {"分数": ["小学分数应用"]},
                "六上": {"分数": ["分数乘法与除法"]},
            }
        },
        "keyword_index": {},
        "sub_tag_index": {
            "小学分数应用": [
                {"version": "数与式", "grade": "五下", "main_tag": "分数"},
            ],
            "分数乘法与除法": [
                {"version": "数与式", "grade": "六上", "main_tag": "分数"},
            ],
        },
    }
    responses = iter(
        [
            '{"is_math_problem": true, "domain": "数与式", "grade": "五下"}',
            '{"tag": "小学分数应用"}',
        ]
    )

    async def fake_chat(_prompt):
        return next(responses)

    monkeypatch.setattr(injector, "load_framework", lambda: framework)
    monkeypatch.setattr(injector, "_chat", fake_chat)

    result = await injector.inject_knowledge_tags("一根绳子用去全长的三分之一，还剩12米")

    assert result == {
        "version": "数与式",
        "grade": "五下",
        "main_tag": "分数",
        "sub_tags": ["小学分数应用"],
    }

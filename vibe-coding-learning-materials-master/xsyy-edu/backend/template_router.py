# -*- coding: utf-8 -*-
"""画法模板路由（P0 实验，2026-09-20）。

把「改造/模板库」的冻结画法模板接入动画生成链路：

    题面(+画像) → LLM 选画法 → LLM 按该画法的填空 schema 写填空 JSON
    → node 装配器.js 装配 → node 验收器.js 八道闸门 → 成品页直接作为 teaching.html
    （八道闸门没过时，把验收器原文回喂给模型重写一次再验；仍不过才回退自由生成）

设计纪律（与项目约定一致）：
- 任何一步失败都返回 None（或由调用方捕获异常后回退），**绝不阻塞主流程**；
  未命中/失败一律回退现有「LLM 自由生成 scene_svg」链路。
- 装配与验收复用模板库自己的脚本，信任模型与模板库一致（八道闸门过 = 放行）。
- 落库形态：teaching_data=None → pipeline 存整页 teaching.html →
  /api/teachings/{id}/html 走既有兜底路径原样返回，老页面完全不受影响。

环境变量：
- ANIM_TEMPLATE_ROUTE_ENABLED   置 "0" 关闭整条路由（默认开）
- ANIM_TEMPLATE_LIB_DIR         模板库目录（默认取「代码旁边」的 backend/anim_template_lib，
  随 git 一起部署、服务器零配置；本地想改用源库 改造\\模板库 时才覆盖此变量）
- ANIM_TEMPLATE_NODE_BIN        node 可执行文件（默认 "node"）
- ANIM_TEMPLATE_DOMAINS         参与路由的域目录名，逗号分隔（默认即模板库全部 24 族，
  与 同步_生产卡片.js 的 FAMS 一致；想缩小范围再覆盖此变量）
- ANIM_TEMPLATE_ROUTE_TIMEOUT   选画法 LLM 超时秒数（默认 90）
- ANIM_TEMPLATE_FILL_TIMEOUT    写填空 LLM 超时秒数（默认 900，对齐 pipeline 自由生成链路的
  timeout=900；思考模型偶尔会思考 5 分钟以上，2026-09-20 实测 300 秒会掐断）
- ANIM_TEMPLATE_ROUTE_MAX_TOKENS   选画法 completion 上限（默认 4096；
  思考模型如 qwen3.8-flash 的 reasoning 计入 completion 额度，过小会导致
  思考吃光额度、正文 0 字符——2026-09-20 实测踩坑）
- ANIM_TEMPLATE_FILL_MAX_TOKENS    写填空 completion 上限（默认 32768，对齐 pipeline 主链路）
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

_TEMPLATE_ID_RE = re.compile(r"id:\s*'([^']+)'")
_SLOTS_RE = re.compile(r"slots:\s*\[([^\]]*)\]")
_MUSTSHOW_RE = re.compile(r"mustShow:\s*\[([^\]]*)\]")


def _lib_dir() -> Path:
    """模板库目录：默认取「代码旁边」的 anim_template_lib（随 git 部署，服务器零配置）。

    需要指向别处（例如本地源库 改造\\模板库）时用 ANIM_TEMPLATE_LIB_DIR 覆盖。
    """
    env = os.getenv("ANIM_TEMPLATE_LIB_DIR", "").strip()
    return Path(env) if env else (Path(__file__).resolve().parent / "anim_template_lib")


def _node_bin() -> str:
    return os.getenv("ANIM_TEMPLATE_NODE_BIN", "node")


def _domains() -> List[str]:
    default = ("数与式,几何,函数,行程,静态兜底,替换假设,线段图,几何最值,面积割补,"
               "图形变换,全等相似,统计图表,树状图,离散点阵,分支展开,天平,时间轴,"
               "集合,割线,单位圆,四边形,数轴,圆,立体")
    return [d.strip() for d in os.getenv("ANIM_TEMPLATE_DOMAINS", default).split(",") if d.strip()]


def _route_enabled() -> bool:
    return os.getenv("ANIM_TEMPLATE_ROUTE_ENABLED", "1") != "0"


def _log(message: str, level: str = "INFO") -> None:
    try:
        from pipeline import log as _plog

        _plog(f"[画法路由] {message}", level)
    except Exception:  # noqa: BLE001
        print(f"[画法路由][{level}] {message}")


# ---------------------------------------------------------------- 注册表

def scan_registry(lib_dir: Optional[Path] = None) -> List[Dict]:
    """扫描模板库：域目录/*.html 且配了 填空示例/<名>.json 的才算可路由画法。

    每个条目：{id, html, fill_example, tag, question, title, slots, must_show}
    slots / must_show 从模板 HTML 的 TEMPLATE 自述块抽取（解析失败不致命，置空）。
    """
    root = Path(lib_dir) if lib_dir else _lib_dir()
    entries: List[Dict] = []
    if not root.exists():
        return entries
    for domain in _domains():
        domain_dir = root / domain
        if not domain_dir.is_dir():
            continue
        for tpl_path in sorted(domain_dir.glob("*.html")):
            fill_path = root / "填空示例" / (tpl_path.stem + ".json")
            if not fill_path.exists():
                continue
            try:
                fill_example = json.loads(fill_path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                _log(f"跳过 {tpl_path.name}：填空示例解析失败 {exc}", "WARN")
                continue
            meta = fill_example.get("meta") or {}
            try:
                tpl_src = tpl_path.read_text(encoding="utf-8")
            except Exception:  # noqa: BLE001
                tpl_src = ""
            slots_m = _SLOTS_RE.search(tpl_src)
            must_m = _MUSTSHOW_RE.search(tpl_src)
            entries.append(
                {
                    "id": f"{domain}/{tpl_path.stem}",
                    "html": str(tpl_path),
                    "fill_example": fill_example,
                    "tag": str(meta.get("tag", "")),
                    "question": str(meta.get("question", "")),
                    "title": str(meta.get("title", "")),
                    "slots": [s.strip().strip("'\"") for s in slots_m.group(1).split(",") if s.strip()] if slots_m else [],
                    "must_show": [s.strip().strip("'\"") for s in must_m.group(1).split(",") if s.strip()] if must_m else [],
                }
            )
    return entries


# ---------------------------------------------------------------- LLM 调用

async def _chat(client, model_name: str, system: str, user: str,
                params_fn, max_tokens: int, timeout: float) -> tuple[str, str]:
    """流式累积一小段输出（与 pipeline 同款流式，规避网关 120s 代理超时）。

    返回 (text, finish_reason)；finish_reason 用于诊断「思考模型把额度吃光」类截断。
    """
    def _call():
        stream = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_completion_tokens=max_tokens,
            stream=True,
            timeout=timeout,
            **params_fn(model_name),
        )
        text = ""
        finish = ""
        for ev in stream:
            if not ev.choices:
                continue
            choice = ev.choices[0]
            if choice.finish_reason:
                finish = choice.finish_reason
            delta = choice.delta.content or ""
            if delta:
                text += delta
        return text, finish

    return await asyncio.wait_for(asyncio.to_thread(_call), timeout=timeout + 30)


def _extract_json(text: str) -> Optional[dict]:
    """剥掉 ```json 围栏 / 前后噪声，取第一个完整 JSON 对象。"""
    if not text:
        return None
    text = re.sub(r"```(?:json)?", "", text).strip()
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
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
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except Exception:  # noqa: BLE001
                    return None
    return None


# ---------------------------------------------------------------- 提示词

_ROUTE_SYSTEM = """你是数学教学动画的「画法调度员」。给你一道题和候选画法清单，
你要判断这道题是否恰好是某个画法覆盖的题型。

判断纪律（宁缺勿滥）：
- 题型结构与画法的「示例题面」本质相同（同一画法、只换数字/文字）才命中；
- 结构相似但画法讲不出的（比如画法没有的元素、多问超范围），一律返回 null；
- 拿不准就返回 null——落空回退自由生成，比硬套错画法好。

只输出 JSON，不要任何多余文字：
{"template_id": "域/模板名", "reason": "一句话理由"}
或
{"template_id": null, "reason": "一句话理由"}"""

_FILL_SYSTEM = """你是数学教学动画的「填空员」。冻结画法模板已经把画面画法定死，
你只做一道填空题：按「填空规范」和「参考示例」的形态，把用户题目的数字、算式、
讲解文字填进同结构的 JSON。

硬性规范：
1. 只输出一个完整 JSON（与参考示例同构），不要 markdown 围栏，不要解释。
2. expr 顺序求值，后面的能用前面的；e 里只允许：数字、+ - * / %、括号、
   比较与逻辑运算、Math.sqrt/abs/pow/max/min/round/floor/ceil/hypot/log、
   已定义的变量名与参数 id。禁止：引号、分号、箭头函数、window/document 等。
3. 严禁算出 Infinity/NaN：所有除法的分母在整个滑块扫描范围内都不得为 0。
4. steps 恰好按参考示例的步数写；show/hi 只能用「可用元素 id」清单里的名字；
   凡会被滑块改变位置的元素，第 1 步的 show 必须包含它。
5. p/d 里可用 {{expr名}} 占位（图变了字一定跟着变）；{{}} 内只许写变量名或纯算式，
   不许写字符串；条件与结论用自然语言写在文案里。
6. 所有数字必须与题面一致，输出前自己代值验算一遍再交卷。
7. JSON 字符串里不许出现 "</script"。
8. meta.question 必须是题面原文（可轻度整理，不改数字不改问法）。
9. meta 三项（title / tag / question）都必须写，且都不得为空字符串：
   - title：中文题名（≤12 字），例如「平行四边形面积公式」「勾股定理」；
   - tag：该画法的标签（与参考示例保持一致，例如「面积割补」）；
   - question：题面原文。
   ⚠ G01 系模板（几何、面积割补等）的 title 为空会直接导致场景编译失败、整题回退，务必填。
10. labels 的 t（标签文字，例如「底 = 6」）必须是字面量，**严禁**在 label 文字里写 {{}} 占位符；
   需要随图变化的数字，请放进 steps 的 p / d 文案或 expr，不要塞进 label。
   占位符 {{}} 只允许出现在 p / d / t / tip / readout 这些文案字段，禁止出现在 labels、texts 等其他字段。
11. **文字长度是硬闸**：模板对每个字符串字段都有长度上限，超长会直接「验收未过」→ 整题回退。
   上限因族而异且对你看不见（最紧的只有 20~50 字：割线 / 单位圆的 method ≤ 26、deri ≤ 42；
   几何一系的 texts.deri ≤ 80；分支展开的 labels 每项只有 3 字）。
   唯一可靠的标尺就是参考示例：**每一个字符串字段的字数，都不要超过参考示例中同名
   字段的字数**（示例本身就是照着闸门写的），示例里没有的字段一律不要自己新增。
   写完逐字段数一遍字数再交卷，宁可短一点。
12. **「画面规模」不等于题面数字**：像 scene（画面上画几只动物）、items / 分支条数
   这类字段只决定「图上画多少个」，照参考示例的小规模写（示例 4 只鸡 3 只兔就写 4 和 3），
   **绝不要把题面里的答案级数字填进去**（题面是 35 个头、94 条腿，scene 仍是几只这种小数目）。
   题面的答案数字只放在 expr 与 steps 的文案里。"""


def _candidate_block(entries: List[Dict]) -> str:
    lines = []
    for i, e in enumerate(entries, 1):
        lines.append(f"{i}. id={e['id']}\n   标签：{e['tag']}\n   示例题面：{e['question'][:160]}")
    return "\n".join(lines)


def _profile_hint(content_profile: Optional[dict]) -> str:
    if not isinstance(content_profile, dict):
        return ""
    keys = ["domain", "grade_band", "grade", "knowledge_tags", "tags", "question_type"]
    parts = []
    for k in keys:
        v = content_profile.get(k)
        if v:
            parts.append(f"{k}={v}")
    return ("；教学画像：" + "；".join(map(str, parts))) if parts else ""


def _repair_user(fill_user: str, fill: dict, err: str) -> str:
    """「验收未过 → 回喂验收器原文重写」的提示词（拼在原来的写填空提示词之后）。"""
    return (
        f"{fill_user}\n\n"
        f"────\n"
        f"⚠ 你上一版填空被模板的硬闸打回了。验收器原文（截尾）：\n{err[-1200:]}\n\n"
        f"上一版填空：\n{json.dumps(fill, ensure_ascii=False, indent=2)}\n\n"
        f"请**只针对报错点**改（例如把超长字段压到上限以内、把「画面规模」类字段改回"
        f"参考示例的小量级），其余字段与结构一律保持原样，重新输出一份完整填空 JSON。"
    )


async def _assemble_and_verify(entry: Dict, fill: dict) -> tuple[bool, str, str]:
    """装配 + 验收（模板库自己的脚本）；返回 (是否通过, 失败原文, 成品 html)。"""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="xsyy-frozen-") as td:
        fill_path = Path(td) / "fill.json"
        out_path = str(Path(td) / "out.html")
        fill_path.write_text(json.dumps(fill, ensure_ascii=False, indent=2), encoding="utf-8")

        asm_ok, asm_out = await _run_node(["装配器.js", entry["html"], str(fill_path), out_path])
        if not asm_ok:
            return False, f"【装配失败】{asm_out.strip()}", ""
        val_ok, val_out = await _run_node(["验收器.js", entry["html"], str(fill_path), out_path])
        if not val_ok or "✅ 全部通过" not in val_out:
            return False, val_out.strip(), ""
        return True, "", Path(out_path).read_text(encoding="utf-8")


# ---------------------------------------------------------------- node 装配 / 验收

async def _run_node(args: List[str], timeout: float = 120.0) -> tuple[bool, str]:
    def _call():
        import subprocess

        p = subprocess.run(
            [_node_bin()] + args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=str(_lib_dir()),
        )
        return p.returncode == 0, (p.stdout or "") + (p.stderr or "")

    try:
        return await asyncio.wait_for(asyncio.to_thread(_call), timeout=timeout + 30)
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------- 主入口

async def try_frozen_template(
    *,
    client,
    model_name: str,
    params_fn,
    question: str,
    title: str = "",
    content_profile: Optional[dict] = None,
    task_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Optional[Dict]:
    """命中冻结画法 → 装配成品页；返回 {"html", "teaching_data": None, ...}，未命中/失败返回 None。"""
    if not _route_enabled():
        return None
    try:
        from website_log import record_website_log
    except Exception:  # noqa: BLE001
        record_website_log = None  # type: ignore[assignment]

    def _site_log(level: str, message: str, context: Optional[dict] = None):
        if record_website_log is None:
            return
        try:
            record_website_log(
                level=level,
                category="animation_generation",
                message=message,
                user_id=user_id,
                task_id=task_id,
                context=context,
            )
        except Exception:  # noqa: BLE001
            pass

    entries = scan_registry()
    if not entries:
        _log(f"注册表为空（{_lib_dir()}），跳过路由", "WARN")
        return None

    route_timeout = float(os.getenv("ANIM_TEMPLATE_ROUTE_TIMEOUT", "90"))
    fill_timeout = float(os.getenv("ANIM_TEMPLATE_FILL_TIMEOUT", "900"))
    route_max_tokens = int(os.getenv("ANIM_TEMPLATE_ROUTE_MAX_TOKENS", "4096"))
    fill_max_tokens = int(os.getenv("ANIM_TEMPLATE_FILL_MAX_TOKENS", "32768"))

    # ① 选画法
    route_user = (
        f"题目：{question}\n（标题：{title or '无'}{_profile_hint(content_profile)}）\n\n"
        f"候选画法清单：\n{_candidate_block(entries)}\n\n这道题命中哪个画法？"
    )
    route_text, route_finish = "", ""
    try:
        route_text, route_finish = await _chat(client, model_name, _ROUTE_SYSTEM, route_user,
                                               params_fn, max_tokens=route_max_tokens, timeout=route_timeout)
    except Exception as exc:  # noqa: BLE001
        # 超时/网关异常一律视为"未命中"，但必须落日志（否则只剩管线外层的笼统一条）
        _log(f"选画法调用失败（{type(exc).__name__}: {exc or '超时'}），回退自由生成", "WARN")
        return None
    route = _extract_json(route_text) or {}
    tpl_id = route.get("template_id")
    if not tpl_id:
        _log(f"未命中画法（{route.get('reason', '无理由')}），回退自由生成")
        if not route and route_text.strip():
            _log(f"选画法输出无法解析（finish={route_finish}，{len(route_text)} 字符），"
                 f"头 200：{route_text.strip()[:200]}", "WARN")
        return None
    entry = next((e for e in entries if e["id"] == tpl_id), None)
    if entry is None:
        _log(f"选了不存在的画法 {tpl_id}，回退自由生成", "WARN")
        return None
    _log(f"命中 {tpl_id}：{route.get('reason', '')}")

    # ② 写填空 → ③ 装配 + 验收；「装配/验收未过」把验收器原文回喂给模型重写一次
    slots_line = "、".join(entry["slots"]) if entry["slots"] else "（以参考示例为准）"
    must_line = "、".join(entry["must_show"]) if entry["must_show"] else "（以参考示例为准）"
    fill_user = (
        f"用户题目：{question}\n（标题：{title or '无'}）\n\n"
        f"选用画法：{entry['id']}\n"
        f"可用元素 id（show/hi 只能从这里选）：{slots_line}\n"
        f"必须出现在某一步 show 里的答案类元素：{must_line}\n\n"
        f"参考示例（该画法的标准填空，严格按这个形态写）：\n"
        f"{json.dumps(entry['fill_example'], ensure_ascii=False, indent=2)}\n\n"
        f"现在为用户题目写填空 JSON。"
    )

    html, fail_out = "", ""
    for attempt in (1, 2):
        prompt = fill_user if attempt == 1 else _repair_user(fill_user, fill, fail_out)
        try:
            fill_text, fill_finish = await _chat(client, model_name, _FILL_SYSTEM, prompt,
                                                 params_fn, max_tokens=fill_max_tokens, timeout=fill_timeout)
        except Exception as exc:  # noqa: BLE001
            _log(f"写填空调用失败（{type(exc).__name__}: {exc or '超时'}），回退自由生成", "WARN")
            _site_log("WARN", f"画法路由 {tpl_id} 写填空调用失败，回退自由生成",
                      {"error": f"{type(exc).__name__}: {exc}"[:300]})
            return None
        fill = _extract_json(fill_text)
        if not fill or not isinstance(fill.get("meta"), dict) or not fill.get("steps"):
            _log(
                f"填空 JSON 解析失败或缺关键字段，回退自由生成"
                f"（finish={fill_finish or '未知'}，输出 {len(fill_text)} 字符）",
                "WARN",
            )
            if not fill and fill_text.strip():
                _log(f"填空原始输出头 200：{fill_text.strip()[:200]}；尾 300：{fill_text.strip()[-300:]}", "WARN")
            _site_log("WARN", f"画法路由 {tpl_id} 填空解析失败，回退自由生成",
                      {"output_chars": len(fill_text), "finish_reason": fill_finish})
            return None
        if "</script" in json.dumps(fill, ensure_ascii=False).lower():
            _log("填空里出现 </script，回退自由生成", "WARN")
            return None

        ok, fail_out, html = await _assemble_and_verify(entry, fill)
        if ok:
            break
        if attempt == 2:
            # 保留原分类口径：装配不过报「装配失败」，验收不过报「验收未过」
            label = "装配失败" if fail_out.startswith("【装配失败】") else "验收未过"
            _log(f"{label}（已回喂重写一次仍不过），回退自由生成：{fail_out[-300:]}", "WARN")
            _site_log("WARN", f"画法路由 {tpl_id} {label}（重试一次仍不过），回退自由生成",
                      {"error": fail_out[-400:]})
            return None
        _log(f"首次没过（装配或验收），回喂验收器原文重写一次：{fail_out[-300:]}", "WARN")

    if not html or len(html) < 50000 or "xsyy-fill" not in html:
        _log("装配产物异常（过短或缺填空块），回退自由生成", "WARN")
        return None

    _log(f"装配+验收通过：{entry['id']}（{len(html)} 字符）")
    _site_log(
        "INFO",
        f"动画生成命中冻结画法 {entry['id']}，装配验收通过（{len(html)} 字符），"
        "跳过自由生成",
        {"template_id": entry["id"]},
    )
    return {
        "html": html,
        "teaching_data": None,  # 整页已成品 → 走 teaching.html 兜底路径，勿写 teaching_data.json
        "frozen_template": {"id": entry["id"], "reason": route.get("reason", "")},
    }

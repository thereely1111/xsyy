r"""scene_svg 纪律 Lint（方案 2026-09-03 §4.5）.

从产物源头拦截"乱动/叠加/杂乱"类违规，不依赖模型自觉。全部为纯函数，
仅依赖标准库 re，可离线单测。

硬性规则（hard，任一命中 → 拒收重试，随 Lint 反馈重生成一次）：
  1. temporary_layer_only_exact_step —— 临时层元素（dashed-line/轨迹/高亮/
     辅助线/笔迹等语义 class）禁止使用 sceneStep >= N，必须 === N；
  2. persistent_min_range —— 持久层（sceneStep >= N）元素至少 3 个；
  3. motion_animation_limit —— 循环 @keyframes 动画 ≤1（初中）/ ≤2（小学）；
  4. no_full_canvas_background —— 全幅浅色背景层（rect/foreignObject/path）；
  5. no_latex_in_svg —— scene_svg 内出现 $…$ / \frac / \sqrt 等 LaTeX 原文；
  6. text_text_overlap —— 同屏两段独立文字 bbox 深交叠（文字压字，100% 缺陷）。

告警规则（warning，仅记录供人工抽查，不阻断）：
  7. coordinate_in_bounds —— bubblePos/arrowTarget 明显越出 820×620；
  8. x_show_min_count —— x-show 条件块过少（<6，原要求 8，宽限到 6 防误伤）；
  9. text_box_ratio —— 文字矩形宽度与文本量比例明显不合理（简化抽样）；
 10. text_on_shape_warn —— 文字与图形交叠且未完全落入任一图形内（含越界标签）；
 11. shape_coincident_warn —— 非 line 图形近乎重合（IoU≥0.45，疑似重复/贴死）。

模式（环境变量 SCENE_LINT_MODE，与 legacy 逻辑互斥）：
  strict（默认）：hard 违规 → 返回 errors，调用方拒收重试；
  warn       ：hard 违规降为 warnings，仅记录；
  off        ：完全跳过。

v2 规则（2026-09-05，方案《质量门与特殊题型提示词拆分》§3.1）：
  bbox_in_bounds / motion_ref_exists / motion_no_self_transform /
  motion_step_delta_min / occlusion_order / palette_blacklist / pattern_contract。
  灰度策略：v2 默认按 warning 记录（SCENE_LINT_V2_MODE 默认 warn），
  误报清零后设 SCENE_LINT_V2_MODE=strict 才升级 hard 拒收；
  命中 scene_pattern 的题（pattern_key 非空）时 palette/contract 立即按其级别判定。
"""
from __future__ import annotations

import html
import os
import re
from dataclasses import dataclass, field
from typing import Optional

SVG_WIDTH = 820
SVG_HEIGHT = 620

# 临时层语义 class 标记（命中即视为"本步临时元素"）
_TEMP_CLASS_HINTS = (
    "dashed-line", "trace", "trail", "highlight", "aux", "guide",
    "pen", "stroke-path", "temp-", "arrow-line", "motion-", "hl-",
)

# 明确声明为持久层的 class（豁免临时层判定）
_PERSISTENT_CLASS_HINTS = ("persistent", "persist-", "core-", "base-")

_LATEX_PATTERNS = (
    re.compile(r"\$[^$\n]*\$"),
    re.compile(r"\\frac\b|\\sqrt\b|\\times\b|\\cdot\b|\\left\b|\\right\b|\\sum\b|\\int\b"),
    re.compile(r"\\(?:le|ge|ne|pm|pi|alpha|beta|theta)\b"),
)


def lint_mode() -> str:
    mode = os.getenv("SCENE_LINT_MODE", "strict").strip().lower()
    return mode if mode in ("strict", "warn", "off") else "strict"


@dataclass
class LintIssue:
    rule: str
    message: str
    level: str = "hard"  # hard | warning


@dataclass
class LintResult:
    passed: bool = True
    issues: list = field(default_factory=list)  # list[LintIssue]

    @property
    def hard_issues(self) -> list:
        return [i for i in self.issues if i.level == "hard"]

    @property
    def warnings(self) -> list:
        return [i for i in self.issues if i.level == "warning"]

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "hard": [{"rule": i.rule, "message": i.message} for i in self.hard_issues],
            "warnings": [{"rule": i.rule, "message": i.message} for i in self.warnings],
        }


# SVG 标签级扫描辅助
# 注意：x-show="sceneStep >= 1" 的值内含有 '>'，简单 [^>]* 会提前截断标签，
# 因此标签体用「引号内容整体消费 + 其余非 > 字符」的方式匹配，保证属性值内的 > 不算标签结束。
_TAG_OPEN = re.compile(r"<([A-Za-z][A-Za-z0-9]*)((?:\"[^\"]*\"|'[^']*'|[^>\"'])*?)(/?)>")


def _attr(tag_attrs: str, name: str) -> str:
    """从标签属性串里取属性值（忽略大小写），未命中返回 ''. """
    m = re.search(rf"\b{name}\s*=\s*(['\"])(.*?)\1", tag_attrs, re.IGNORECASE | re.DOTALL)
    return m.group(2) if m else ""


def _split_attr_values(value: str) -> list[str]:
    return re.split(r"[\s,]+", (value or "").strip())


def _has_attr(tag_attrs: str, name: str) -> bool:
    return bool(re.search(rf"\b{name}\b", tag_attrs, re.IGNORECASE))


def _is_svg_content_tag(tag_name: str) -> bool:
    """scene_svg 内容元素白名单（跳过 defs/style/marker/filter 等容器内部误伤）. """
    skip = {"style", "defs", "marker", "filter", "clippath", "mask", "pattern",
            "lineargradient", "radialgradient", "stop", "metadata", "title", "desc"}
    return tag_name.lower() not in skip


def _collect_elements(scene_svg: str) -> list[dict]:
    """把 scene_svg 拆成元素级 {tag, attrs, x_show, classes, inline_style} 列表. """
    elements: list[dict] = []
    for m in _TAG_OPEN.finditer(scene_svg or ""):
        tag_name = m.group(1)
        attrs = m.group(2)
        if not _is_svg_content_tag(tag_name):
            continue
        x_show = _attr(attrs, "x-show")
        elements.append({
            "tag": tag_name,
            "attrs": attrs,
            "x_show": x_show,
            "classes": _split_attr_values(_attr(attrs, "class")),
            "style": _attr(attrs, "style"),
        })
    return elements


def _is_temporary_element(el: dict) -> bool:
    classes = " ".join(el.get("classes") or []).lower()
    return any(h in classes for h in _TEMP_CLASS_HINTS)


def _is_persistent_declared(el: dict) -> bool:
    classes = " ".join(el.get("classes") or []).lower()
    return any(h in classes for h in _PERSISTENT_CLASS_HINTS)


def _x_show_uses_range(x_show: str) -> bool:
    """x-show 表达式中是否存在 sceneStep >= N / sceneStep > N 范围判断.

    模型合法 SVG 输出会把 ``>`` 写成 XML 实体 ``&gt;``，这里先 unescape 再匹配，
    避免实体写法被漏数（曾导致 persistent_min_range 误判「持久层 0 个」而拒收）。
    """
    return bool(re.search(r"sceneStep\s*(>=|>)\s*\d+", html.unescape(x_show or "")))


def _count_range_elements(elements: list[dict]) -> int:
    return sum(1 for el in elements if _x_show_uses_range(el.get("x_show", "")))


def _extract_style_block(scene_svg: str) -> str:
    """合并全部 <style> 块（模型可能输出多个 style 块）. """
    blocks = re.findall(r"<style[^>]*>(.*?)</style>", scene_svg or "", re.IGNORECASE | re.DOTALL)
    return "\n".join(blocks)


# ── 几何重叠检测（bbox 解析 + 同屏可见分组）──────────────────────────────────

_TEXT_ANCHOR_KEYS = {"middle", "end"}


def _inherited_x_shows(scene_svg: str) -> dict:
    """把 <g x-show="...">…</g> 的可见性映射到其内部的起始位置区间。

    返回 {start_pos: end_pos} → 该 g 的 x_show（仅一层：区间不含内层更深的 g，
    内层 g 会覆盖同名 key 位置区间，取最内层即可，故用「最内层含盖」查询）。
    为简单可靠，这里返回 {pos: x_show} 其中 pos 为每个 g 的开启位置，
    查询时取“覆盖元素且起点最大的 g”（最内层）。
    """
    mapping: dict[int, tuple[int, str]] = {}  # start -> (end, x_show)
    stack: list[tuple[int, str]] = []  # (start, x_show)
    for m in re.finditer(r"<g\b[^>]*?>|</g>", scene_svg or ""):
        tok = m.group(0)
        if tok.startswith("</g>"):
            if stack:
                start, xs = stack.pop()
                mapping[start] = (m.start(), xs)
        else:
            stack.append((m.start(), _attr(tok[2:], "x-show")))
    return {k: v for k, v in mapping.items() if v[1]}  # 仅保留带 x-show 的 g


def _text_lines_from_inner(inner: str, base_x: float, base_y: float,
                           font_size: float, anchor: str) -> list[tuple[float, float, str]]:
    """把 <text> 内容拆成 (x, y, 文本行) 列表：支持 tspan 分行近似.

    模型常用两种写法：直接文本、<tspan>…</tspan> 分行。此处把 tspan 视为独立行，
    未显式给 dy/y 时按行高 font_size*1.3 向下排列（与浏览器渲染近似）。
    """
    lines: list[tuple[float, float, str]] = []
    x, y = base_x, base_y
    if not re.search(r"<tspan", inner, re.I):
        txt = re.sub(r"<[^>]+>", "", inner)
        if txt.strip():
            lines.append((x, y, txt.strip()))
        return lines
    # 含 tspan：tspan 自带 x/y/dy
    for seg in re.findall(r"<tspan\b([^>]*)>(.*?)</tspan>|<tspan\b([^>]*)/>", inner, re.S):
        attrs, content = (seg[0], seg[1]) if seg[0] else (seg[2], "")
        if seg[0]:
            attrs, content = seg[0], seg[1]
        else:
            continue
        sx = _num_attr(attrs, "x", x)
        sy = _num_attr(attrs, "y", y)
        dy = _num_attr(attrs, "dy", 0)
        if sy != y or dy:
            sy = y + dy if sy == y else sy
        content = re.sub(r"<[^>]+>", "", content).strip()
        if content:
            lines.append((sx, sy, content))
            y = sy + font_size * 1.3
    # 直接落在 <text> 内但也在 tspan 之外的文本（罕见），追加一行
    tail = re.sub(r"<[^>]+>", "", inner).strip()
    if tail and not lines:
        lines.append((x, y, tail))
    return lines


def _num_attr(attrs: str, name: str, default: float) -> float:
    m = re.search(rf"\b{name}\s*=\s*['\"]\s*([-+]?\d*\.?\d+)", attrs, re.IGNORECASE)
    return float(m.group(1)) if m else default


def _collect_geometry(scene_svg: str) -> list[dict]:
    """解析 scene_svg 为几何元素 {tag, x_show, bbox, kind} 列表.

    bbox=(x0,y0,x1,y1)。kind: text|shape(line 归 shape 但参与度低)。
    可见性：元素自身 x-show > 外层 <g> 继承 > 常显 always。
    仅解析 rect/circle/ellipse/line/text（path/复杂变换不估，避免误报）。
    """
    svg = scene_svg or ""
    g_map = _inherited_x_shows(svg)

    def _nearest_g_x_show(pos: int) -> str:
        best = None
        for g_start, (g_end, xs) in g_map.items():
            if g_start < pos < g_end and (best is None or g_start > best[0]):
                best = (g_start, xs)
        return best[1] if best else ""

    out: list[dict] = []
    for m in _TAG_OPEN.finditer(svg):
        tag = m.group(1).lower()
        if tag not in ("rect", "circle", "ellipse", "line", "text"):
            continue
        attrs = m.group(2)
        if _has_attr(attrs, "x-show") is False and not re.search(r"x-show\s*=", attrs):
            pass
        x_show = _attr(attrs, "x-show") or _nearest_g_x_show(m.start())
        bb = None
        try:
            if tag == "rect":
                x = _num_attr(attrs, "x", 0); y = _num_attr(attrs, "y", 0)
                w = _num_attr(attrs, "width", 0); h = _num_attr(attrs, "height", 0)
                bb = (x, y, x + w, y + h)
            elif tag == "circle":
                cx = _num_attr(attrs, "cx", 0); cy = _num_attr(attrs, "cy", 0)
                r = _num_attr(attrs, "r", 0)
                bb = (cx - r, cy - r, cx + r, cy + r)
            elif tag == "ellipse":
                cx = _num_attr(attrs, "cx", 0); cy = _num_attr(attrs, "cy", 0)
                rx = _num_attr(attrs, "rx", 0); ry = _num_attr(attrs, "ry", 0)
                bb = (cx - rx, cy - ry, cx + rx, cy + ry)
            elif tag == "line":
                x1 = _num_attr(attrs, "x1", 0); y1 = _num_attr(attrs, "y1", 0)
                x2 = _num_attr(attrs, "x2", 0); y2 = _num_attr(attrs, "y2", 0)
                bb = (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
            elif tag == "text":
                x = _num_attr(attrs, "x", 0); y = _num_attr(attrs, "y", 0)
                fs = _num_attr(attrs, "font-size", 15)
                anchor = _attr(attrs, "text-anchor").strip().lower()
                if fs < 8 or fs > 60:
                    fs = 15
                # _TAG_OPEN 只消费开标签；内容从匹配结束位置向后找 </text>
                inner_m = re.search(r"^>?([\s\S]*?)</text\s*>", svg[m.end() - 1:], re.S)
                inner = inner_m.group(1) if inner_m else ""
                lines = _text_lines_from_inner(inner, x, y, fs, anchor)
                if not lines:
                    continue
                xs_all = [lx for lx, _, _ in lines]
                ys_all = [ly for _, ly, _ in lines]
                widths = []
                for lx, ly, txt in lines:
                    w = sum((1.02 if ord(c) > 127 else 0.55) * fs for c in txt)
                    if anchor == "middle":
                        widths.append((lx - w / 2, lx + w / 2))
                    elif anchor == "end":
                        widths.append((lx - w, lx))
                    else:
                        widths.append((lx, lx + w))
                x0 = min(w[0] for w in widths); x1 = max(w[1] for w in widths)
                y0 = min(ys_all) - fs * 0.25
                y1 = max(ys_all) + fs * 0.95
                bb = (x0, y0, x1, y1)
        except Exception:
            continue
        if bb is None:
            continue
        kind = "text" if tag == "text" else "shape"
        out.append({"tag": tag, "x_show": x_show, "bb": bb, "kind": kind})
    return out


def _visibility_group(x_show: str) -> str:
    """归一化可见组：persist:N / step:N / always. """
    m = re.search(r"sceneStep\s*>\s*(\d+)", x_show or "")
    if m:
        return f"persist:{int(m.group(1)) + 1}"
    m = re.search(r"sceneStep\s*>=\s*(\d+)", x_show or "")
    if m:
        return f"persist:{int(m.group(1))}"
    m = re.search(r"sceneStep\s*(?:===|==)\s*(\d+)", x_show or "")
    if m:
        return f"step:{int(m.group(1))}"
    m = re.search(r"sceneStep\s*<=\s*(\d+)", x_show or "")
    if m:
        return f"step:1-{int(m.group(1))}"
    return "always"


def _intersect(a: tuple, b: tuple) -> tuple | None:
    ax0, ay0, ax1, ay1 = a; bx0, by0, bx1, by1 = b
    x0 = max(ax0, bx0); x1 = min(ax1, bx1)
    y0 = max(ay0, by0); y1 = min(ay1, by1)
    if x1 - x0 <= 0 or y1 - y0 <= 0:
        return None
    return (x0, y0, x1, y1)


def _check_text_text_overlap(geoms: list[dict]) -> list[LintIssue]:
    """同屏两段独立文字 bbox 深交叠 → 拒收（文字压字是 100% 视觉缺陷）。

    深交叠判据：交叠高度 ≥ 较小行高 30%（且 ≥6px）且交叠宽度 ≥4px，
    避免行距略紧的正常排布被误伤。单字符几何点标（O/A/B/1/2）若仅轻微相切不触发。
    """
    issues: list[LintIssue] = []
    texts = [g for g in geoms if g["kind"] == "text"]
    for i in range(len(texts)):
        for k in range(i + 1, len(texts)):
            A, B = texts[i], texts[k]
            if _visibility_group(A["x_show"]) != _visibility_group(B["x_show"]):
                continue
            ov = _intersect(A["bb"], B["bb"])
            if not ov:
                continue
            ox, oy, ox1, oy1 = ov
            dw, dh = ox1 - ox, oy1 - oy
            ha = A["bb"][3] - A["bb"][1]; hb = B["bb"][3] - B["bb"][1]
            if dh >= max(6.0, min(ha, hb) * 0.3) and dw >= 4.0:
                issues.append(LintIssue(
                    rule="text_text_overlap",
                    message=(f"同屏两段文字互相压叠：<text>@{int(A['bb'][0])},{int(A['bb'][1])} 与 "
                             f"<text>@{int(B['bb'][0])},{int(B['bb'][1])}（交叠 {dw:.0f}×{dh:.0f}px）。"
                             "请错开 y 坐标/分行/加行距（≥字号 1.3 倍），禁止文字压字"),
                ))
    return issues


def _check_text_on_shape(geoms: list[dict]) -> list[LintIssue]:
    """text 与图形部分交叠但未完全落在任一图形内 → 告警（可能压住图形关键部位）.

    完全内含于图形的文字（点标/数值标/图内标签）是数学教学合法表达，不告警。
    """
    issues: list[LintIssue] = []
    texts = [g for g in geoms if g["kind"] == "text"]
    shapes = [g for g in geoms if g["kind"] == "shape"]
    for t in texts:
        tg = _visibility_group(t["x_show"])
        inside_any = False
        for s in shapes:
            if _visibility_group(s["x_show"]) != tg:
                continue
            sb = s["bb"]
            if (t["bb"][0] >= sb[0] - 1 and t["bb"][1] >= sb[1] - 1
                    and t["bb"][2] <= sb[2] + 1 and t["bb"][3] <= sb[3] + 1):
                inside_any = True
                break
        if inside_any:
            continue
        for s in shapes:
            if _visibility_group(s["x_show"]) != tg:
                continue
            if s["tag"] == "line":
                continue
            ov = _intersect(t["bb"], s["bb"])
            if not ov:
                continue
            ox, oy, ox1, oy1 = ov
            ow, oh = ox1 - ox, oy1 - oy
            if max(ow, oh) < 6 or ow * oh < 90:
                continue  # 轻微擦边不告警（小圆点/贴线常见，视觉无碍）
            issues.append(LintIssue(
                rule="text_on_shape_warn",
                level="warning",
                message=(f"文字 @{int(t['bb'][0])},{int(t['bb'][1])} 与 <{s['tag']}> "
                         f"@{int(s['bb'][0])},{int(s['bb'][1])} 交叠 {ox1 - ox:.0f}×{oy1 - oy:.0f}px 且"
                         "未完全落入图形内；若文字是图形内标签请整体移入，否则请移到图形外侧避让"),
            ))
            break
    return issues


def _check_shape_coincident(geoms: list[dict]) -> list[LintIssue]:
    """非 line 图形之间近乎重合（IoU 高 / 同心同尺寸）→ 告警（疑似重复或贴死）."""
    issues: list[LintIssue] = []
    shapes = [g for g in geoms if g["kind"] == "shape" and g["tag"] != "line"]
    for i in range(len(shapes)):
        for k in range(i + 1, len(shapes)):
            A, B = shapes[i], shapes[k]
            if _visibility_group(A["x_show"]) != _visibility_group(B["x_show"]):
                continue
            ov = _intersect(A["bb"], B["bb"])
            if not ov:
                continue
            ox, oy, ox1, oy1 = ov
            ia = (ox1 - ox) * (oy1 - oy)
            area_a = (A["bb"][2] - A["bb"][0]) * (A["bb"][3] - A["bb"][1])
            area_b = (B["bb"][2] - B["bb"][0]) * (B["bb"][3] - B["bb"][1])
            if min(area_a, area_b) < 200:
                continue
            iou = ia / (area_a + area_b - ia + 1e-6)
            if iou >= 0.45:
                issues.append(LintIssue(
                    rule="shape_coincident_warn",
                    level="warning",
                    message=(f"图形 <{A['tag']}>@{int(A['bb'][0])},{int(A['bb'][1])} 与 "
                             f"<{B['tag']}>@{int(B['bb'][0])},{int(B['bb'][1])} 交叠 IoU={iou:.2f}，"
                             "疑似重复/贴死，请确认是否为同一图形画了两遍"),
                ))
    return issues


# ── 规则实现 ─────────────────────────────────────────────────────────────────


def _check_temporary_exact(elements: list[dict]) -> list[LintIssue]:
    """临时层语义元素禁止 sceneStep >= N. """
    issues: list[LintIssue] = []
    for i, el in enumerate(elements):
        if not _is_temporary_element(el):
            continue
        if _is_persistent_declared(el):
            continue  # 显式声明持久，豁免
        x_show = el.get("x_show", "")
        if x_show and _x_show_uses_range(x_show):
            issues.append(LintIssue(
                rule="temporary_layer_only_exact_step",
                message=(
                    f"元素#{i} <{el['tag']}> class='{el.get('classes')}' 属临时层语义，"
                    f"却使用范围判断 x-show=\"{x_show[:80]}\"；临时层必须 sceneStep === N"
                ),
            ))
    return issues


def _check_persistent_min(elements: list[dict]) -> list[LintIssue]:
    """持久层元素（sceneStep >= N）至少 3 个，防止全临时化导致画面闪没."""
    cnt = _count_range_elements(elements)
    if cnt < 3:
        return [LintIssue(
            rule="persistent_min_range",
            message=f"持久层元素（sceneStep >= N）仅 {cnt} 个，要求至少 3 个；"
                    "题目主体/基础图形/轴/固定标签应跨步保留",
        )]
    return []


def _check_motion_limit(scene_svg: str, stage: str) -> list[LintIssue]:
    """循环动画数量上限：初中 ≤1，小学 ≤2（按 style 内 'infinite' 循环计数）. """
    style_block = _extract_style_block(scene_svg)
    if not style_block:
        return []
    limit = 2 if stage == "primary_school" else 1
    loop_count = len(re.findall(r"infinite", style_block, re.IGNORECASE))
    if loop_count > limit:
        return [LintIssue(
            rule="motion_animation_limit",
            message=f"检测到 {loop_count} 处 infinite 循环动画（{'小学' if stage == 'primary_school' else '初中'}上限 {limit}）；"
                    "默认不做循环浮动，动效只服务关键数学动作，请删减无意义循环",
        )]
    return []


def _check_full_canvas_background(scene_svg: str) -> list[LintIssue]:
    """全幅浅色背景（rect/foreignObject 铺满）. """
    issues: list[LintIssue] = []

    def _full_rect(match: re.Match) -> str:
        attrs = match.group(0)

        def _num(key: str, default: float) -> float:
            m = re.search(rf"\b{key}\s*=\s*['\"]\s*([-+]?\d*\.?\d+)", attrs, re.IGNORECASE)
            return float(m.group(1)) if m else default

        x, y = _num("x", 0), _num("y", 0)
        w, h = _num("width", 0), _num("height", 0)
        if x <= 30 and y <= 30 and w >= SVG_WIDTH - 40 and h >= SVG_HEIGHT - 40:
            issues.append(LintIssue(
                rule="no_full_canvas_background",
                message=f"检测到疑似全画布背景层 <rect {attrs[:120]}>，请移除整幅背景",
            ))
        return attrs

    for tag in ("rect", "foreignObject", "path"):
        re.sub(rf"<{tag}\b[^>]*>", _full_rect, scene_svg or "", flags=re.IGNORECASE)
    return issues


def _check_latex(scene_svg: str) -> list[LintIssue]:
    for pat in _LATEX_PATTERNS:
        m = pat.search(scene_svg or "")
        if m:
            return [LintIssue(
                rule="no_latex_in_svg",
                message=f"scene_svg 内出现未渲染 LaTeX 原文片段: {m.group(0)[:40]}；"
                        "请用 Unicode（× ÷ √ π ² ³ ≤ ≥ ≈ ≠）或预计算结果",
            )]
    return []


def _check_coordinate_bounds(steps: list) -> list[LintIssue]:
    """bubblePos/arrowTarget 明显越出画布（容差 24px）→ 告警. """
    issues: list[LintIssue] = []

    def _out_of_bounds(pt: dict) -> bool:
        x = pt.get("x")
        y = pt.get("y")
        if x is None or y is None:
            return False
        try:
            x, y = float(x), float(y)
        except (TypeError, ValueError):
            return False
        return x < -24 or y < -24 or x > SVG_WIDTH + 24 or y > SVG_HEIGHT + 24

    for idx, step in enumerate(steps or []):
        if not isinstance(step, dict):
            continue
        for key in ("bubblePos", "arrowTarget"):
            pt = step.get(key)
            if isinstance(pt, dict) and _out_of_bounds(pt):
                issues.append(LintIssue(
                    rule="coordinate_in_bounds",
                    level="warning",
                    message=f"step[{idx}].{key}={pt} 明显越出 820×620 画布，请修正",
                ))
    return issues


def _check_x_show_min(scene_svg: str) -> list[LintIssue]:
    cnt = len(re.findall(r"x-show\s*=", scene_svg or "", re.IGNORECASE))
    if cnt < 6:
        return [LintIssue(
            rule="x_show_min_count",
            level="warning",
            message=f"x-show 条件块仅 {cnt} 个（建议 ≥8），可能步骤显隐设计不足",
        )]
    return []


def _check_text_box_ratio(scene_svg: str) -> list[LintIssue]:
    """文字矩形宽高与文本长度抽样告警（简化启发式，不阻断）."""
    issues: list[LintIssue] = []
    # 仅抽查 <text> 直接文本过长且无 tspan 换行
    for m in re.finditer(r"<text\b[^>]*>([^<]{12,})</text>", scene_svg or ""):
        content = m.group(1).strip()
        if len(content) > 20 and re.search(r"[\u4e00-\u9fff0-9]", content):
            issues.append(LintIssue(
                rule="text_box_ratio_warn",
                level="warning",
                message=f"检测到较长 <text> 未分行: “{content[:30]}…”（{len(content)} 字），"
                        "建议 tspan 换行或扩矩形避免溢出",
            ))
            break
    return issues


# ── v2 规则（2026-09-05 新增，方案《质量门与特殊题型提示词拆分》§3.1）─────────
# 灰度策略：v1 规则沿用 SCENE_LINT_MODE（默认 strict）；v2 新增规则默认只按
# warning 记录，直到 SCENE_LINT_V2_MODE=strict 才升级为 hard 拒收（决策点 3：
# 先 warn 灰度一周、误报清零后再切 strict）。运动类规则仅在有 motions 时触发；
# bbox 越界/遮挡/配色/contract 均带容差，避免误伤既有正常产物。

_BAD_PALETTE = {"#8a1c1c", "#78716c", "#44403c", "#a8a29e"}
_BBOX_TOL = 24  # 元素 bbox 越界容差（px），±24 内不算越界（收窄以根治"压到边线外/半截出界"）

_MOTION_TRANSLATE_RE = re.compile(r"translate\(\s*([-+]?\d*\.?\d+)\s*(?:px)?\s*,?\s*([-+]?\d*\.?\d+)?\s*(?:px)?\s*\)")
_MOTION_ROTATE_RE = re.compile(r"rotate\(\s*([-+]?\d*\.?\d+)")
_ID_ATTR_RE = re.compile(r'\bid\s*=\s*(["\'])(.*?)\1')
_ID_TAG_RE_TMPL = r'<[A-Za-z][\w-]*[^>]*?\bid\s*=\s*(["\']){mid}\1[^>]*>'


def _v2_hard() -> bool:
    """v2 规则是否以 hard 级别生效（SCENE_LINT_V2_MODE=strict）。默认 warn。"""
    mode = os.getenv("SCENE_LINT_V2_MODE", "warn").strip().lower()
    return mode == "strict"


def _v2_level(*, pattern_key: str = "") -> str:
    """v2 规则级别：命中 pattern 的专项检查（contract）与整体 v2 strict 才 hard。"""
    if pattern_key or _v2_hard():
        return "hard"
    return "warning"


def _scene_ids_with_pos(scene_svg: str) -> dict:
    """提取 scene_svg 中所有 id → (元素开标签起始位置, 标签名). """
    out: dict[str, tuple[int, str]] = {}
    for m in re.finditer(r"<([A-Za-z][\w-]*)((?:\"[^\"]*\"|'[^']*'|[^>\"'])*?)(/?)>", scene_svg or ""):
        tag = m.group(1)
        if not _is_svg_content_tag(tag):
            continue
        idm = _ID_ATTR_RE.search(m.group(2))
        if idm:
            out[idm.group(2)] = (m.start(), tag)
    return out


def _motion_position(transform: str) -> Optional[tuple[float, float, float]]:
    """解析 transform 文本 → (dx, dy, deg)；无法解析返回 None.

    translate 与 rotate 可同串并存；未出现 translate 时 dx/dy 视为 0，
    以 rotate 度数参与位移量判定。
    """
    text = transform or ""
    tm = _MOTION_TRANSLATE_RE.search(text)
    dx, dy = 0.0, 0.0
    if tm:
        dx = float(tm.group(1))
        dy = float(tm.group(2)) if tm.group(2) else 0.0
    rm = _MOTION_ROTATE_RE.search(text)
    deg = float(rm.group(1)) if rm else 0.0
    if not tm and not rm:
        return None
    return (dx, dy, deg)


def _collect_motion_tracks(steps: list) -> dict:
    """把 steps 里的 motions 归一为 {id: [(step_idx, dx, dy, deg), ...]}（按步序）.

    兼容对象式 {"train": "translate(..)"} 与数组式 [{"id","transform"}]。
    """
    tracks: dict[str, list] = {}
    for idx, step in enumerate(steps or []):
        if not isinstance(step, dict):
            continue
        motions = step.get("motions")
        entries: list = []
        if isinstance(motions, dict):
            entries = [(mid, str(val)) for mid, val in motions.items()]
        elif isinstance(motions, list):
            entries = [
                (str(it.get("id", "")), str(it.get("transform", "")))
                for it in motions if isinstance(it, dict) and it.get("id")
            ]
        for mid, val in entries:
            pos = _motion_position(val)
            if pos is None or not mid:
                continue
            tracks.setdefault(mid, []).append((idx,) + pos)
    return tracks


def _check_bbox_in_bounds(geoms: list[dict]) -> list[LintIssue]:
    """元素 bbox 越出 820×620（±24px 容差）→ 硬性拒收（始终 hard，不随 v2 灰度降级）.

    越界元素会被画布裁切、直接看不到，属 100% 视觉缺陷；因此该规则独立于
    SCENE_LINT_V2_MODE 的灰度，默认即以 hard 生效，由 pipeline 带坐标反馈重试一次。
    """
    issues: list[LintIssue] = []
    for g in geoms:
        x0, y0, x1, y1 = g["bb"]
        if x0 < -_BBOX_TOL or y0 < -_BBOX_TOL or x1 > SVG_WIDTH + _BBOX_TOL or y1 > SVG_HEIGHT + _BBOX_TOL:
            issues.append(LintIssue(
                rule="bbox_in_bounds",
                level="hard",
                message=(f"元素 <{g['tag']}> bbox=({int(x0)},{int(y0)})-({int(x1)},{int(y1)}) "
                         f"越出 820×620 画布（容差 ±{_BBOX_TOL}px），请把图形/文字移入画布或整体缩小；"
                         "若含 motions 运动主体，须保证「初始位置 + 各步 translate 最大位移」仍落在画布内"),
            ))
            break  # 一条足够，避免同图刷屏
    return issues


def _check_motion_ref_exists(tracks: dict, ids: dict) -> list[LintIssue]:
    """motions 引用的 id 必须存在于 scene_svg → 否则静默失效。"""
    issues: list[LintIssue] = []
    for mid in tracks:
        if mid not in ids:
            issues.append(LintIssue(
                rule="motion_ref_exists",
                level=_v2_level(),
                message=(f"motions 引用了不存在的元素 id=\"{mid}\"（在 scene_svg 里找不到），"
                         "motions 会静默失效；请给运动主体加唯一 id 或修正引用"),
            ))
    return issues


def _check_motion_no_self_transform(tracks: dict, scene_svg: str, ids: dict) -> list[LintIssue]:
    """被 motions 驱动的元素自身禁带 transform 属性（会被 style.transform 覆盖错位）。"""
    issues: list[LintIssue] = []
    for mid in tracks:
        if mid not in ids:
            continue
        pat = re.compile(_ID_TAG_RE_TMPL.format(mid=re.escape(mid)))
        m = pat.search(scene_svg or "")
        if m and re.search(r"\btransform\s*=", m.group(0)):
            issues.append(LintIssue(
                rule="motion_no_self_transform",
                level=_v2_level(),
                message=(f"运动主体 id=\"{mid}\" 自身携带 transform 属性 "
                         f"(<{m.group(0)[:120]}>…)；模板会用 style.transform 覆盖它导致错位，"
                         "请把静态定位移到外层包裹 <g> 上、主体自身去掉 transform"),
            ))
    return issues


def _check_motion_step_delta(tracks: dict) -> list[LintIssue]:
    """相邻步位移校验：每步推进可见（平移≥40px / 旋转≥15°）；全程同值=没动。"""
    issues: list[LintIssue] = []
    for mid, seq in tracks.items():
        if len(seq) < 2:
            continue
        seq = sorted(seq)
        total_move = _motion_delta(seq[0], seq[-1])
        if total_move is not None and total_move < 1e-6:
            issues.append(LintIssue(
                rule="motion_step_delta_min",
                level=_v2_level(),
                message=(f"运动主体 id=\"{mid}\" 全程 motions 位移相同（{seq[0][1:]} → {seq[-1][1:]}），"
                         "等于没动；请按题意逐步推进（平移每步 ≥40px 或旋转 ≥15°）"),
            ))
            continue
        for prev, cur in zip(seq, seq[1:]):
            delta = _motion_delta(prev, cur)
            if delta is None:
                continue
            threshold = _motion_threshold(prev, cur)
            if 1e-6 < delta < threshold:
                issues.append(LintIssue(
                    rule="motion_step_delta_min",
                    level=_v2_level(),
                    message=(f"运动主体 id=\"{mid}\" step{prev[0] + 1}→step{cur[0] + 1} "
                             f"位移 {delta:.0f} 小于可见阈值（平移 {threshold:.0f}px），"
                             "肉眼难辨；请加大位移或改为旋转/缩放表达"),
                ))
    return issues


def _motion_delta(a: tuple, b: tuple) -> Optional[float]:
    """两 (step, dx, dy, deg) 间的位移量（平移距离与旋转角的较大语义）。"""
    if a is None or b is None:
        return None
    dx = b[1] - a[1]
    dy = b[2] - a[2]
    dist = (dx * dx + dy * dy) ** 0.5
    deg = abs(b[3] - a[3])
    return max(dist, deg)


def _motion_threshold(a: tuple, b: tuple) -> float:
    """位移可见阈值：以平移为主按 40px，纯旋转为主按 15°。"""
    dx = b[1] - a[1]
    dy = b[2] - a[2]
    dist = (dx * dx + dy * dy) ** 0.5
    deg = abs(b[3] - a[3])
    return 40.0 if dist >= deg else 15.0


def _check_occlusion_order(tracks: dict, ids: dict) -> list[LintIssue]:
    """存在 *-front 前景层时，绘制顺序必须在运动主体之后（穿越/钻入感正确）。"""
    issues: list[LintIssue] = []
    front_ids = {i for i in ids if "front" in i.lower()}
    motion_ids = [i for i in tracks if i in ids]
    if not front_ids or not motion_ids:
        return []
    motion_max = max(ids[i][0] for i in motion_ids)
    for fid in front_ids:
        if ids[fid][0] <= motion_max:
            issues.append(LintIssue(
                rule="occlusion_order",
                level=_v2_level(),
                message=(f"前景遮罩 id=\"{fid}\" 的绘制顺序在运动主体之前（{ids[fid][1]}@{ids[fid][0]} "
                         f"≤ {motion_max}），主体会盖在遮罩上、失去钻入感；"
                         "请把前景（洞口/桥身/容器前壁）画在主体**之后**"),
            ))
    return issues


def _check_palette_blacklist(scene_svg: str, pattern_key: str = "") -> list[LintIssue]:
    """配色黑名单：禁旧朱砂 #8a1c1c 铺底与灰系 #78716c/#44403c/#a8a29e 作大块遮罩. """
    hits: dict[str, int] = {}
    big_rect = False
    for m in re.finditer(r"<([A-Za-z][\w-]*)((?:\"[^\"]*\"|'[^']*'|[^>\"'])*?)(/?)>", scene_svg or ""):
        tag = m.group(1)
        if not _is_svg_content_tag(tag):
            continue
        attrs = m.group(2)
        low = attrs.lower()
        colors = [c for c in _BAD_PALETTE if c in low]
        if not colors:
            continue
        # 仅当颜色用于填充/描边类属性时才算（style="fill:#…" 或 fill="#…"）
        if not re.search(r"fill\s*[:=]|stroke\s*[:=]", low):
            continue
        for c in colors:
            hits[c] = hits.get(c, 0) + 1
        if tag in ("rect", "rect") and re.search(r"\bfill\s*[:=]", low):
            try:
                w = float(re.search(r"\bwidth\s*=\s*[\"']\s*([-+]?\d*\.?\d+)", attrs).group(1))
                h = float(re.search(r"\bheight\s*=\s*[\"']\s*([-+]?\d*\.?\d+)", attrs).group(1))
                if w * h >= 6000:
                    big_rect = True
            except Exception:  # noqa: BLE001
                pass
    total = sum(hits.values())
    if total < 3 and not big_rect:
        return []
    desc = "、".join(f"{c}×{n}" for c, n in sorted(hits.items()))
    return [LintIssue(
        rule="palette_blacklist",
        level=_v2_level(pattern_key=pattern_key),
        message=(f"检测到禁用配色 {desc}（{('大块铺底' if big_rect else '多处出现')}）；"
                 "请使用模板三色体系：蓝 #2f5fde / 朱砂 #d6432f / 鎏金 #c8901a / 墨 #2b2b2b / 米带 #e9e2d2"),
    )]


_TRIGRAM_RE = re.compile(r"[\u2630-\u2637]")  # 八卦卦象字符：字体缺失会渲染成乱码，禁止出现在 scene_svg 文字


def _check_no_trigram(scene_svg: str) -> list[LintIssue]:
    """scene_svg 文字中严禁八卦卦象字符：常用字体缺字形→乱码/豆腐块，命中即硬拒收。"""
    issues: list[LintIssue] = []
    for m in re.finditer(r"<text\b[^>]*>([\s\S]*?)</text>", scene_svg or "", re.IGNORECASE):
        content = re.sub(r"<[^>]+>", "", m.group(1))
        if _TRIGRAM_RE.search(content):
            issues.append(LintIssue(
                rule="no_trigram_glyph",
                level="hard",
                message=("scene_svg 文字中出现八卦卦象字符（U+2630–U+2637 一类），在常用字体下"
                         "会渲染成乱码/豆腐块，一律拒收；请改用汉字卦名（乾/兑/离/震/巽/坎/艮/坤），"
                         "禁止八卦符号字符"),
            ))
            break
    return issues


_PATTERN_CONTRACT_TOKENS = {
    # pattern_key: (方向标注集, 长度标注集)
    "tunnel_pass": (
        ("入口", "出口", "桥左", "桥右", "桥洞左", "桥洞右", "左端", "右端"),
        ("隧道长", "桥长", "车长", "洞长", "全长", "主体长", "通道长"),
    ),
}


def _check_pattern_contract(scene_svg: str, pattern_key: str = "") -> list[LintIssue]:
    """命中 pattern 的题必须出现该 pattern 要求的关键标注（画法模板落地检查）。"""
    if not pattern_key or pattern_key not in _PATTERN_CONTRACT_TOKENS:
        return []
    dir_tokens, len_tokens = _PATTERN_CONTRACT_TOKENS[pattern_key]
    svg = scene_svg or ""
    dir_hits = sum(1 for t in dir_tokens if t in svg)
    len_hit = any(t in svg for t in len_tokens)
    if dir_hits >= 2 and len_hit:
        return []
    return [LintIssue(
        rule="pattern_contract",
        level=_v2_level(pattern_key=pattern_key),
        message=(f"命中题型画法模板 {pattern_key} 但场景缺少必备标注："
                 f"方向标注命中 {dir_hits}/2（入口/出口 或 桥左/右 等），长度标注"
                 f"{'有' if len_hit else '无'}（隧道长/桥长/车长/全长 等）；"
                 "请按 50_pattern_tunnel_pass.md 补齐通道长/主体长/两端标注"),
    )]


def lint_scene_svg(
    scene_svg: str,
    steps: Optional[list] = None,
    *,
    stage: str = "junior_high",
    display_class: str = "",
    pattern_key: str = "",
) -> LintResult:
    """执行全部纪律规则，返回 LintResult.

    Args:
        scene_svg: LLM 产出的 scene_svg（未做背景清理前的原始片段）
        steps: steps 数组（用于坐标越界检查 / motions 合法性）
        stage: primary_school | junior_high（决定动效上限）
        display_class: 展示大类（预留：几何类可加更严几何精度检查）
        pattern_key: 命中题型画法模板的 pattern_key（如 tunnel_pass）；
            开启 pattern_contract / palette_blacklist 专项并按其级别判定（v2 灰度）。
    """
    del display_class  # 预留
    result = LintResult(passed=True)
    scene_svg = scene_svg or ""
    steps = steps or []

    elements = _collect_elements(scene_svg)
    geoms = _collect_geometry(scene_svg)
    ids = _scene_ids_with_pos(scene_svg)
    tracks = _collect_motion_tracks(steps)

    checks: list[tuple] = [
        (_check_temporary_exact, (elements,)),
        (_check_persistent_min, (elements,)),
        (_check_motion_limit, (scene_svg, stage)),
        (_check_full_canvas_background, (scene_svg,)),
        (_check_latex, (scene_svg,)),
        (_check_no_trigram, (scene_svg,)),
        (_check_coordinate_bounds, (steps,)),
        (_check_x_show_min, (scene_svg,)),
        (_check_text_box_ratio, (scene_svg,)),
        (_check_text_text_overlap, (geoms,)),
        (_check_text_on_shape, (geoms,)),
        (_check_shape_coincident, (geoms,)),
    ]
    for fn, args in checks:
        result.issues.extend(fn(*args))

    # ── v2 规则（2026-09-05，灰度见 _v2_hard 说明）──────────────────────────
    # 运动类规则仅在有 motions（tracks 非空）时才可能触发；无运动题自然跳过。
    v2_checks: list[tuple] = [
        (_check_bbox_in_bounds, (geoms,)),
        (_check_motion_ref_exists, (tracks, ids)),
        (_check_motion_no_self_transform, (tracks, scene_svg, ids)),
        (_check_motion_step_delta, (tracks,)),
        (_check_occlusion_order, (tracks, ids)),
        (_check_palette_blacklist, (scene_svg, pattern_key)),
        (_check_pattern_contract, (scene_svg, pattern_key)),
    ]
    for fn, args in v2_checks:
        result.issues.extend(fn(*args))

    hard = result.hard_issues
    result.passed = not hard
    return result

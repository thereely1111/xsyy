#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""通用 2.0 风格预览图生成器。"""

import asyncio
import base64
import io
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv
from PIL import Image

# 模型配置统一从 kimi_config 读取（.env 唯一出口）
from kimi_config import (
    get_image_api_key,
    get_image_base_url,
    get_image_model,
    get_backup_api_key,
    get_backup_base_url,
    get_backup_model,
    get_backup_image_api_key,
    get_backup_image_base_url,
    get_backup_image_model,
    is_backup_configured,
    is_backup_image_configured,
)

backend_dir = Path(__file__).resolve().parent
project_dir = backend_dir.parent
load_dotenv(backend_dir / ".env")
storage_dir = project_dir / "storage"
# 生图网关地址统一从 .env 的 GPTsAPI_BASE 读取（2026-09-11 收口，原硬编码 https://kuaipao.pro/v1 作为兜底默认值）
IMAGE_API_BASE = get_image_base_url().rstrip("/")

XUAN_PAPER_STYLE = """Use the approved 2.0 educational cover style: restrained minimalist textbook illustration with a unified traditional xuan paper base.
The full square canvas must be covered by warm ivory rice paper with subtle natural fibers, soft handmade grain, and gentle uneven texture. The xuan paper is the continuous background base, not a card, border, frame, object, or scenery.
Use one clear central mathematical visual that directly matches this problem. Use flat 2D shapes, clean thin ink-blue lines, one muted jade accent, and one restrained cinnabar-red accent. Keep the composition sparse, balanced, elegant, child-friendly, and recognizable at thumbnail size.
Do not use a plain digital white background, dark borders, frames, decorative patterns, gradients, 3D rendering, photorealism, dense worksheet layout, unrelated objects, readable text, random Chinese characters, watermark, or logo."""


def log(message: str, level: str = "INFO") -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level}] {message}", flush=True)


def _text_from_metadata(metadata: dict) -> str:
    parts = [
        metadata.get("title", ""),
        metadata.get("question", ""),
        metadata.get("prompt", ""),
        metadata.get("knowledge_tags", {}).get("version", "") if isinstance(metadata.get("knowledge_tags"), dict) else "",
        metadata.get("knowledge_tags", {}).get("main_tag", "") if isinstance(metadata.get("knowledge_tags"), dict) else "",
    ]
    return " ".join(str(part) for part in parts if part)


def _visual_direction(metadata: dict) -> str:
    text = _text_from_metadata(metadata)
    if any(word in text for word in ("相遇", "追及", "追赶", "路程", "速度", "同时出发", "同时到达")):
        return (
            "Show a clear two-actor motion diagram: two simple figures, two vehicles, or one person and one bus on the same route, "
            "with different start points, arrows, and distance marks to express meeting or chasing. Keep the scene minimal, flat, and readable."
        )
    if any(word in text for word in ("二元", "两元", "两种", "和差", "差不", "鸡兔", "甲乙", "姐姐", "妹妹")):
        return (
            "Show a two-part comparison or combination diagram: two distinct simple figures or object groups, side by side or stacked, "
            "with a visible sum-and-difference relationship. Keep the symbols abstract and avoid readable labels."
        )
    if any(word in text for word in ("春游", "校车", "旅游", "乘车", "出发", "到站")):
        return (
            "Show a small school-bus or trip-related scene: a simple bus icon, a few student dots, and a route arrow. "
            "Keep it symbolic, neat, and secondary to the math structure."
        )
    if any(word in text for word in ("三角形", "等腰", "内角", "角度")):
        return "Show one central triangle with clearly marked sides, vertices, and angle relationship."
    if any(word in text for word in ("方程", "函数", "坐标", "一次函数", "直线")):
        return "Show one central coordinate plane with only the necessary axes and one or two clean mathematical lines or an intersection."
    if any(word in text for word in ("除", "平均", "分给", "分成", "倍", "每人")):
        return "Show one central equal-sharing diagram using neatly separated groups of simple tokens or objects."
    if any(word in text for word in ("面积", "周长", "长方形", "正方形")):
        return "Show one central outlined geometric shape with restrained measurement marks and area or perimeter structure."
    if any(word in text for word in ("圆", "半径", "直径", "弧")):
        return "Show one central circle with only the necessary radius, diameter, or arc construction."
    if any(word in text for word in ("排列", "组合", "概率", "选择")):
        return "Show one central branching or counting diagram made from clean dots and connected lines."
    if any(word in text for word in ("钱", "元", "价格", "找零", "购买")):
        return "Show one central arrangement of simple coin-like circles and a clean arithmetic relationship, without currency text."
    return "Show one central abstract mathematical diagram made only from the lines, dots, shapes, and relationships required by the problem."


def build_image_prompt(metadata: dict) -> str:
    title = metadata.get("title", "数学问题讲解")
    question = metadata.get("question", "") or metadata.get("prompt", "")
    return (
        f"Create one premium educational math cover illustration.\n\n"
        f"Topic: {title}\n"
        f"Problem context: {str(question)[:240]}\n\n"
        f"{XUAN_PAPER_STYLE}\n"
        f"Visual direction: {_visual_direction(metadata)}\n"
        "For every word problem with a clear real-world context, infer and depict one to three essential people, objects, animals, vehicles, or actions from the problem context. "
        "Make the story relationship visible through simple symbolic props and the mathematical diagram, not readable labels. "
        "Do not default to a coordinate graph merely because the problem also contains algebra, equations, or functions; use a coordinate graph only when graph interpretation is the main task. "
        "The visual must communicate the problem type without copying the full question or adding unrelated visual elements."
    )


def build_safe_image_prompt(metadata: dict) -> str:
    """更保守的兜底 prompt，用于第三方网关拦截或超时时降级重试。"""
    title = metadata.get("title", "数学问题讲解")
    question = metadata.get("question", "") or metadata.get("prompt", "")
    return (
        "Create a premium Chinese-inspired educational illustration for a math lesson cover.\n\n"
        f"Topic: {title}\n"
        f"Context: {str(question)[:100]}\n\n"
        "Square composition, warm ivory xuan paper texture background, one clear central abstract math diagram, "
        "thin ink-blue lines, muted jade accents, cinnabar highlights, elegant and child-friendly, "
        "no text, no numbers, no grid paper, no watermark, no logo."
    )


def env_int(name: str, default: int) -> int:
    """读取整数型环境变量，缺失或非法时回退默认值。"""
    raw = os.getenv(name, "")
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        log(f"环境变量 {name}={raw!r} 非法，回退默认值 {default}", "WARN")
        return default


def preview_backup_extra_seconds() -> int:
    """封面备用模型独立预算引入的额外外层等待时间（秒）。

    备用模型切换后 deadline 会整体重置为 PREVIEW_BACKUP_TOTAL_TIMEOUT_SECONDS，
    不再与默认模型共享预算；调用方的外层 asyncio.wait_for 兜底必须把这些
    独立预算计入，否则备用模型刚开跑就会被外层掐断（历史封面丢失根因的镜像问题）。
    每配置一级备用模型（专用封面备用 / 动画共用备用）就累加一份独立预算。
    """
    extra = 0
    backup_total = env_int("PREVIEW_BACKUP_TOTAL_TIMEOUT_SECONDS", 270)

    def _configured(prefix: str) -> bool:
        return all(
            os.getenv(f"{prefix}_{suffix}", "").strip()
            for suffix in ("API_KEY", "BASE_URL", "NAME")
        )

    if _configured("BACKUP_IMAGE_MODEL"):   # 第一级：专用封面备用生图模型
        extra += backup_total
    if _configured("BACKUP_MODEL"):         # 第二级：动画共用备用模型
        extra += backup_total
    return extra


def _sleep_within(deadline: float, seconds: int) -> None:
    """退避睡眠，但绝不越过 deadline。"""
    remaining = deadline - time.monotonic()
    if remaining > 0:
        time.sleep(min(seconds, remaining))


def _extract_image_bytes(response, deadline: float) -> bytes:
    """从生成接口响应中取出图片字节，每条失败路径都给出可读错误。"""
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(f"生成接口返回非 JSON: {response.text[:200]}") from exc

    items = payload.get("data") or []
    if not items:
        raise RuntimeError(f"生成接口返回空 data: {str(payload)[:200]}")

    item = items[0]
    b64 = item.get("b64_json")
    if b64:
        try:
            return base64.b64decode(b64)
        except Exception as exc:
            raise RuntimeError(f"b64_json 解码失败: {exc}") from exc

    url = item.get("url")
    if not url:
        raise RuntimeError(f"响应既无 b64_json 也无 url，实际字段: {list(item.keys())}")

    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise RuntimeError("预算耗尽，来不及下载图片")
    download = requests.get(
        url, timeout=min(env_int("PREVIEW_DOWNLOAD_TIMEOUT_SECONDS", 60), remaining)
    )
    if download.status_code != 200:
        # 必须拦在这里：403/404 的错误页正文若喂给 Image.open 会炸成 UnidentifiedImageError
        raise RuntimeError(f"下载图片失败 HTTP {download.status_code}: {download.text[:200]}")
    return download.content


def _request_image(prompt: str, deadline: float, fallback_prompt: str | None = None) -> bytes:
    """在 deadline 之前尽力取回图片字节。

    重试预算由 deadline 统一约束，每次请求的超时都收缩到剩余预算之内。
    调用方通过 asyncio.to_thread 执行本函数，而线程无法被取消，所以预算
    必须在函数内部自我约束，不能指望外层 asyncio.wait_for 把它掐掉。
    """
    api_key = get_image_api_key()
    if not api_key:
        raise RuntimeError("未配置 GPTsAPI_KEY")
    base = IMAGE_API_BASE.rstrip("/")
    model = get_image_model()

    # 备用封面生图模型配置（封面生图专用，默认封面模型超时/网络异常时优先切换）
    backup_image_key = get_backup_image_api_key()
    backup_image_base = get_backup_image_base_url().rstrip("/")
    backup_image_model = get_backup_image_model()
    backup_image_configured = is_backup_image_configured()

    # 动画共用的备用模型（封面生图第二级兜底：专用封面备用生图模型失败后使用）
    backup_key = get_backup_api_key()
    backup_base = get_backup_base_url().rstrip("/")
    backup_model = get_backup_model()
    backup_configured = is_backup_configured()
    used_backup = False          # 是否已切换到专用封面备用生图模型
    used_backup_common = False   # 是否已切换到动画共用备用模型

    request_timeout = env_int("PREVIEW_REQUEST_TIMEOUT_SECONDS", 180)
    max_attempts = env_int("PREVIEW_MAX_ATTEMPTS", 3)
    backoff = env_int("PREVIEW_RETRY_BACKOFF_SECONDS", 5)
    min_attempt = env_int("PREVIEW_MIN_ATTEMPT_SECONDS", 10)
    # 备用模型独立预算（秒）：切换到任一备用模型时 deadline 整体重置为该值，
    # 不再与默认模型共享同一条 deadline（旧方案靠 reserve 从默认模型头上抠时间，
    # 默认模型被压缩、备用也只能用残余预算；现在两者互不挤占）。
    backup_total_budget = env_int("PREVIEW_BACKUP_TOTAL_TIMEOUT_SECONDS", 270)

    def _pick_backup():
        """按优先级挑选下一个备用模型，返回 (key, base, model, kind, label) 或 None。"""
        if not used_backup and backup_image_configured:
            return (
                backup_image_key,
                backup_image_base,
                backup_image_model,
                "image",
                f"备用封面生图模型 {backup_image_model}",
            )
        if not used_backup_common and backup_configured:
            return (
                backup_key,
                backup_base,
                backup_model,
                "common",
                f"动画共用备用模型 {backup_model}",
            )
        return None

    def _switch_to_backup(chosen, reason: str) -> None:
        nonlocal api_key, base, model, headers, used_backup, used_backup_common
        nonlocal deadline, attempt
        key, base_url, model_name, kind, backup_label = chosen
        api_key, base, model = key, base_url, model_name
        if kind == "image":
            used_backup = True
        else:
            used_backup_common = True
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        # 备用模型预算独立：deadline 整体重置，尝试次数也重新计数，
        # 备用模型获得与默认模型同等规模的完整重试预算，互不挤占。
        deadline = time.monotonic() + backup_total_budget
        attempt = 0
        log(
            f"默认图片模型{reason}，切换到{backup_label}重试"
            f"（独立预算 {backup_total_budget}s，重试计数已重置）: {last_error}",
            "WARN",
        )

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    attempt = 0
    last_error = "未发起任何请求"

    while True:
        remaining = deadline - time.monotonic()
        remaining_seconds = max(0.0, remaining)
        if remaining < min_attempt:
            reason = "预览图生成超时" if "Timeout" in str(last_error) or "Read timed out" in str(last_error) else "预览图重试预算耗尽"
            raise RuntimeError(f"{reason}（剩余 {remaining_seconds:.1f}s），最后错误: {last_error}")
        if attempt >= max_attempts:
            raise RuntimeError(f"预览图重试已达上限 {max_attempts} 次，最后错误: {last_error}")

        attempt += 1
        # 备用模型预算已独立（切换时 deadline 整体重置），默认模型不再被 reserve 压缩，
        # 单次超时只收缩到当前模型的剩余预算之内即可。
        timeout = min(request_timeout, remaining)
        log(f"生成请求第 {attempt}/{max_attempts} 次（剩余预算 {remaining_seconds:.1f}s，本次超时 {timeout:.1f}s）")
        try:
            response = requests.post(
                f"{base}/images/generations",
                headers=headers,
                json={"model": model, "prompt": prompt, "n": 1, "size": "1024x1024"},
                timeout=timeout,
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            # 默认模型超时/网络异常 → 切下一级备用模型重试（专用封面备用 → 动画共用备用）
            chosen = _pick_backup()
            if chosen is not None:
                remaining = deadline - time.monotonic()
                if remaining >= min_attempt:
                    _switch_to_backup(chosen, "调用超时/网络异常")
                    continue
            log(f"生成请求网络异常: {last_error}", "WARN")
            _sleep_within(deadline, backoff)
            continue

        if response.status_code >= 500:
            last_error = f"HTTP {response.status_code}"
            # 网关超时 524（kuaipao.pro 约 120s 无响应即返回）视同超时，切下一级备用模型重试
            if response.status_code == 524:
                chosen = _pick_backup()
                if chosen is not None:
                    remaining = deadline - time.monotonic()
                    if remaining >= min_attempt:
                        _switch_to_backup(chosen, "返回 HTTP 524（网关超时）")
                        continue
            log(f"生成接口 {response.status_code}，准备重试", "WARN")
            _sleep_within(deadline, backoff)
            continue

        if response.status_code in (400, 524) and fallback_prompt and prompt != fallback_prompt:
            fallback_remaining = deadline - time.monotonic()
            if fallback_remaining >= min_attempt:
                log(
                    f"标准封面请求返回 HTTP {response.status_code}，切换保守 prompt 重试",
                    "WARN",
                )
                prompt = fallback_prompt
                continue

        if response.status_code != 200:
            # 4xx 通常是请求参数或内容策略问题，保留真实响应便于排查。
            raise RuntimeError(f"生成接口 HTTP {response.status_code}: {response.text[:200]}")

        return _extract_image_bytes(response, deadline)


def _save_webp(image_bytes: bytes, output_path: Path) -> None:
    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception as exc:
        raise RuntimeError(f"图片解码失败（{len(image_bytes)} 字节）: {exc}") from exc
    image.thumbnail((512, 512), Image.Resampling.LANCZOS)
    image.save(output_path, format="WebP", quality=85, method=6)


def update_metadata(task_dir: Path, updates: dict) -> None:
    """读-改-写合并更新 metadata.json。

    历史上预览图生成与 _save_teaching_content 各自全量覆写此文件，后写方
    会把先写方的字段（preview_image / knowledge_tags）整段丢掉。合并写入
    加原子替换可同时消除"丢字段"和"读到半截 JSON"两个问题。

    带重试：并发场景（管理员保存标签等同时写 metadata.json）会触发
    Windows 文件锁（WinError 5 / Errno 13 Permission denied），瞬时锁重试即可恢复。
    """
    path = task_dir / "metadata.json"
    meta: dict = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                meta = loaded
        except Exception as exc:
            log(f"metadata.json 解析失败，将以新字段重建: {exc}", "WARN")
    meta.update(updates)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    for _attempt in range(5):
        try:
            tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, path)
            return
        except OSError:
            if _attempt == 4:
                raise
            time.sleep(0.5)


async def generate_image_for_task(
    task_dir: Path,
    metadata: dict,
    force: bool = False,
    timeout_seconds: int | None = None,
) -> bool:
    """为一个案例生成 2.0 风格 Preview.webp。

    timeout_seconds 为整个生成过程（请求重试 + 下载）的总预算，缺省读
    PREVIEW_TOTAL_TIMEOUT_SECONDS。它必须小于调用方 asyncio.wait_for 的超时，
    否则重试还没跑完就会被外层掐断（这正是历史上封面丢失的根因）。
    """
    output_path = task_dir / "Preview.webp"
    if output_path.exists() and not force:
        log(f"已有新版封面，跳过: {task_dir.name}", "SKIP")
        return False

    total_budget = timeout_seconds or env_int("PREVIEW_TOTAL_TIMEOUT_SECONDS", 270)
    deadline = time.monotonic() + total_budget

    prompt = build_image_prompt(metadata)
    fallback_prompt = build_safe_image_prompt(metadata)
    log(f"生成 2.0 封面: {task_dir.name}（总预算 {total_budget}s）")
    image_bytes = await asyncio.to_thread(_request_image, prompt, deadline, fallback_prompt)
    await asyncio.to_thread(_save_webp, image_bytes, output_path)
    metadata["preview_image"] = "Preview.webp"
    update_metadata(task_dir, {"preview_image": "Preview.webp"})
    log(f"已保存: {output_path}")

    # 同步数据库，避免 DB 里残留旧的 preview_image 值导致接口返回 null
    try:
        sys.path.insert(0, str(backend_dir))
        from database import SessionLocal
        from database.models import Teaching

        db = SessionLocal()
        teaching = db.query(Teaching).filter(Teaching.task_id == task_dir.name).first()
        if teaching:
            teaching.preview_image = "Preview.webp"
            db.commit()
            log(f"已同步数据库: {task_dir.name}", "DB")
        db.close()
    except Exception as exc:
        log(f"数据库同步失败（不影响封面文件）: {exc}", "WARN")

    return True


async def main() -> None:
    if not storage_dir.exists():
        log(f"Storage 目录不存在: {storage_dir}", "ERROR")
        return
    task_dirs = sorted(path for path in storage_dir.iterdir() if path.is_dir())
    log(f"找到 {len(task_dirs)} 个案例")
    for task_dir in task_dirs:
        metadata_path = task_dir / "metadata.json"
        if not metadata_path.exists():
            continue
        if not ((task_dir / "teaching.html").exists() or (task_dir / "teaching_data.json").exists()):
            continue
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            await generate_image_for_task(task_dir, metadata)
        except Exception as exc:
            log(f"案例 {task_dir.name} 生成失败: {exc}", "ERROR")


if __name__ == "__main__":
    asyncio.run(main())

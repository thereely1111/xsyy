#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
遍历 storage 目录，使用 GPTsAPI (gemini-3.1-flash-lite-image) 生成预览图片
"""

import asyncio
import io
import json
import os
import time
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
import requests
from PIL import Image

# 加载 .env 文件
utils_dir = Path(__file__).resolve().parent
backend_dir = utils_dir.parent
project_dir = backend_dir.parent
env_path = backend_dir / ".env"
load_dotenv(dotenv_path=env_path)

# Storage 目录
storage_dir = project_dir / "storage"


def log(message: str, level: str = "INFO"):
    """实时日志输出函数，带时间戳"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_message = f"[{timestamp}] [{level}] {message}"
    print(log_message, flush=True)


def build_image_prompt(metadata: dict) -> str:
    """根据 metadata 构建图片生成的 prompt（标准版）"""
    question = metadata.get("question", "") or metadata.get("prompt", "")
    title = metadata.get("title", "数学问题讲解")

    question_lower = f"{title} {question}".lower()
    visual_elements = []

    if any(kw in question_lower for kw in ['相遇', '追及', '追赶', '路程', '速度', '同时出发', '同时到达']):
        visual_elements.append("two simple figures or vehicles on one route, with different start points, arrows, and distance marks to show meeting/chasing")
    if any(kw in question_lower for kw in ['二元', '两元', '两种', '和差', '差不', '甲乙', '姐姐', '妹妹']):
        visual_elements.append("two distinct groups or figures arranged as a clean sum-and-difference comparison")
    if any(kw in question_lower for kw in ['春游', '校车', '旅游', '乘车', '出发', '到站']):
        visual_elements.append("a small symbolic school-bus or trip scene with a route arrow and a few student dots")
    if any(kw in question_lower for kw in ['三角形', '等腰', '周长', '内角']):
        visual_elements.append("a clean central triangle diagram with colored sides and vertex points")
    if any(kw in question_lower for kw in ['方程', '坐标', '函数']):
        visual_elements.append("a simple central coordinate axis with two crossing colored straight lines, no background grid")
    if any(kw in question_lower for kw in ['平均', '除法', '分', '苹果', '糖果']):
        visual_elements.append("balanced grouped circles or tokens showing equal sharing")
    if any(kw in question_lower for kw in ['长方形', '正方形', '图形', '面积']):
        visual_elements.append("simple geometric shapes with clean ink outlines, no graph paper")
    if any(kw in question_lower for kw in ['比赛', '组合', '排列', '选择', '选手']):
        visual_elements.append("connected dots and elegant branching lines representing combinations")
    if any(kw in question_lower for kw in ['买', '钱', '元', '找零']):
        visual_elements.append("subtle coin-like circular tokens without currency text")
    if any(kw in question_lower for kw in ['圆', '半径', '直径']):
        visual_elements.append("a central circle with radius or diameter construction lines")

    if not visual_elements:
        visual_elements.append("a clear central mathematical diagram made from lines, dots, and geometric forms")

    prompt = "Create a premium neo Chinese style educational math cover illustration.\n\n"
    prompt += f"Topic: {title}\n"
    prompt += f"Problem context: {question[:140]}\n\n"
    prompt += "Use the first approved cover style from the prompt tests, with only one added requirement: a unified xuan paper base.\n"
    prompt += "Visual template:\n"
    prompt += "- square cover, full-canvas composition\n"
    prompt += "- background master: warm ivory xuan paper (宣纸) texture covering the entire canvas, visible fine fibers, soft cream-white handmade grain, subtle natural mottling; this paper is the base layer, not a separate card, border, frame, or scenery\n"
    prompt += "- a large imperfect ink-blue circular ring framing the central math diagram\n"
    prompt += "- central visual: " + ", ".join(visual_elements) + "\n"
    prompt += "- linework colors: ink blue, muted jade green, cinnabar red; dots and highlights in the same restrained palette\n"
    prompt += "- surrounding Chinese painting elements: bamboo leaves, plum blossoms, auspicious cloud motifs, distant mountains, pavilion or arched bridge, lotus leaves, brush, inkstone, scroll or stacked books\n"
    prompt += "- scholarly, elegant, child-friendly, polished teaching-card cover, soft natural light\n"
    prompt += "- for every word problem with a clear real-world context, infer and depict one to three essential people, objects, animals, vehicles, or actions from the problem context\n"
    prompt += "- make the story relationship visible through simple symbolic props and the mathematical diagram, not readable labels\n"
    prompt += "- do not default to a coordinate graph merely because the problem also contains algebra, equations, or functions; use a coordinate graph only when graph interpretation is the main task\n"
    prompt += "- no readable text, no random Chinese characters, no numbers unless they are essential abstract tick marks, no watermark, no logo\n"
    prompt += "- avoid grid paper, graph paper, worksheet grids, coordinate grids, notebook lines, dense ruler marks, textbook exercise layout, empty beige space; keep the illustration rich but balanced, matching the first approved existing cover style\n"
    return prompt


def build_safe_image_prompt(metadata: dict) -> str:
    """根据 metadata 构建更保守的图片生成 prompt（用于 400 降级重试）"""
    title = metadata.get("title", "数学问题讲解")
    question = metadata.get("question", "") or metadata.get("prompt", "")
    prompt = "Create a premium Chinese-inspired educational illustration for a math lesson cover.\n\n"
    prompt += f"Topic: {title}\n"
    prompt += f"Context: {question[:100]}\n\n"
    prompt += "Square composition, warm ivory xuan paper texture background, one clear central abstract math diagram, thin ink-blue lines, muted jade accents, cinnabar highlights, elegant and child-friendly, no text, no numbers, no grid paper, no watermark, no logo."
    return prompt


async def generate_image_for_task(task_dir: Path, metadata: dict):
    """为单个任务生成预览图片 (通过 OpenAI 兼容接口 /v1/images/generations 调用 gpt-image-2)"""
    task_id = task_dir.name
    log(f"处理任务: {task_id}")

    preview_webp_path = task_dir / "Preview.webp"
    force = os.getenv("PREVIEW_FORCE_REGENERATE", "").lower() in ("1", "true", "yes")
    if preview_webp_path.exists() and not force:
        log(f"任务 {task_id} 已有预览图（WebP），跳过", "SKIP")
        return

    try:
        api_key = os.getenv("GPTsAPI_KEY")
        if not api_key:
            log("[ERROR] 未配置 GPTsAPI_KEY", "ERROR")
            return
        base = os.getenv("GPTsAPI_BASE", "https://kuaipao.pro/v1").rstrip("/")
        model = os.getenv("GPTsAPI_IMAGE_MODEL", "gpt-image-2")
        url = f"{base}/images/generations"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        def do_request(prompt: str):
            payload = {
                "model": model,
                "prompt": prompt,
                "n": 1,
                "size": "1024x1024",
            }

            def call():
                return requests.post(url, headers=headers, json=payload, timeout=180)

            return asyncio.to_thread(call)

        image_prompt = build_image_prompt(metadata)
        log(f"图片生成 prompt: {image_prompt[:100]}...")
        resp = await do_request(image_prompt)
        if resp.status_code in (400, 524):
            safe_prompt = build_safe_image_prompt(metadata)
            if resp.status_code == 400:
                log("标准 prompt 被拦截，改用安全简化版重试", "WARN")
            else:
                log("标准 prompt 请求超时，改用安全简化版重试", "WARN")
            log(f"安全 prompt: {safe_prompt[:100]}...")
            resp = await do_request(safe_prompt)

        if resp.status_code != 200:
            log(f"生成失败 HTTP {resp.status_code}: {resp.text[:300]}", "ERROR")
            return

        data = resp.json()
        items = data.get("data") or []
        if not items:
            log(f"响应无 data: {data}", "ERROR")
            return

        item = items[0]
        b64 = item.get("b64_json")
        img_url = item.get("url")

        image_bytes = None
        if b64:
            import base64
            image_bytes = base64.b64decode(b64)
        elif img_url:
            try:
                img_resp = requests.get(img_url, timeout=60)
                if img_resp.status_code == 200:
                    image_bytes = img_resp.content
            except Exception as e:
                log(f"下载图片 URL 失败: {e}", "ERROR")

        if not image_bytes:
            log(f"响应无 b64_json/url: keys={list(item.keys())}", "ERROR")
            return

        image = Image.open(io.BytesIO(image_bytes))
        if image.mode in ('RGBA', 'LA', 'P'):
            rgb_img = Image.new('RGB', image.size, (255, 255, 255))
            if image.mode == 'P':
                image = image.convert('RGBA')
            rgb_img.paste(image, mask=image.split()[-1] if image.mode in ('RGBA', 'LA') else None)
            image = rgb_img
        elif image.mode != 'RGB':
            image = image.convert('RGB')

        target_size = 512
        if image.width > target_size or image.height > target_size:
            ratio = min(target_size / image.width, target_size / image.height)
            image = image.resize(
                (int(image.width * ratio), int(image.height * ratio)),
                Image.Resampling.LANCZOS,
            )

        image.save(preview_webp_path, format='WebP', quality=85, method=6)
        log(f"[OK] WebP 已保存: {preview_webp_path} ({os.path.getsize(preview_webp_path)/1024:.1f} KB)")

        metadata["preview_image"] = "Preview.webp"
        (task_dir / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    except Exception as e:
        log(f"任务 {task_id} 生成图片时出错: {str(e)}", "ERROR")
        import traceback
        traceback.print_exc()


async def main():
    """主函数：遍历 storage 并生成预览图"""
    log("=" * 80)
    log("开始为 storage 中的任务生成预览图片")
    log("=" * 80)
    log("")
    
    # 检查 API Key
    api_key = os.getenv("GPTsAPI_KEY")
    if not api_key:
        log("[ERROR] 错误：未找到 GPTsAPI_KEY 环境变量", "ERROR")
        log("请在 .env 文件中配置 GPTsAPI_KEY")
        return

    log("[OK] GPTsAPI_KEY 已配置")
    log(f"[OK] 图片模型: {os.getenv('GPTsAPI_IMAGE_MODEL', 'gpt-image-2')} @ {os.getenv('GPTsAPI_BASE', 'https://kuaipao.pro/v1')}")
    
    log("")
    
    # 遍历 storage 目录
    if not storage_dir.exists():
        log(f"[ERROR] Storage 目录不存在: {storage_dir}", "ERROR")
        return

    task_dirs = [d for d in storage_dir.iterdir() if d.is_dir()]
    target_task_ids = {
        task_id.strip()
        for task_id in os.getenv("PREVIEW_TASK_IDS", "").split(",")
        if task_id.strip()
    }
    if target_task_ids:
        task_dirs = [d for d in task_dirs if d.name in target_task_ids]
        log(f"指定生成 {len(task_dirs)} 个任务文件夹")
    else:
        log(f"找到 {len(task_dirs)} 个任务文件夹")
    log("")
    
    # 处理每个任务
    for i, task_dir in enumerate(task_dirs, 1):
        log("-" * 80)
        log(f"[{i}/{len(task_dirs)}] 处理任务: {task_dir.name}")
        log("-" * 80)
        
        metadata_path = task_dir / "metadata.json"
        if not metadata_path.exists():
            log(f"任务 {task_dir.name} 没有 metadata.json，跳过", "SKIP")
            continue
        
        try:
            # 读取 metadata.json
            with open(metadata_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)
            
            if not (task_dir / "teaching.html").exists() and not (task_dir / "teaching_data.json").exists():
                log(f"任务 {task_dir.name} 没有教学内容文件，跳过", "SKIP")
                continue

            # 生成图片
            await generate_image_for_task(task_dir, metadata)
            
        except Exception as e:
            log(f"处理任务 {task_dir.name} 时出错: {str(e)}", "ERROR")
            import traceback
            traceback.print_exc()
        
        log("")
    
    log("=" * 80)
    log("所有任务处理完成！")
    log("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())


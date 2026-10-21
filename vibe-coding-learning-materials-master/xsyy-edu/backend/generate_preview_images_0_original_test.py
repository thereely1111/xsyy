#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成当前正式宣纸背景提示词的额外样张。"""

import base64
import io
import json
import os
from pathlib import Path

import requests
from dotenv import load_dotenv
from PIL import Image

from generate_preview_images import build_image_prompt

backend_dir = Path(__file__).resolve().parent
load_dotenv(backend_dir / ".env")
output_dir = backend_dir / "preview_prompt_tests_20260817" / "prompt_set_0_original"

QUESTIONS = [
    ("sample_1", "division", "小明有18个玩具，他想平均分给6个小朋友，每个小朋友能分到几个？"),
    ("sample_2", "geometry_area", "一个长方形长12厘米，宽8厘米，它的面积是多少平方厘米？"),
    ("sample_3", "circle_radius", "一个圆的半径是5厘米，求这个圆的直径是多少厘米。"),
    ("sample_4", "money", "小红买一本书花了18元，付给售货员20元，应找回多少钱？"),
    ("sample_5", "combination", "4名同学参加象棋比赛，每两人比赛一场，一共要比赛多少场？"),
    ("sample_6", "generic_math", "学校图书角原来有36本书，又买来24本，现在一共有多少本书？"),
]


def generate_image(prompt: str, output_path: Path) -> None:
    api_key = os.getenv("GPTsAPI_KEY")
    if not api_key:
        raise RuntimeError("未配置 GPTsAPI_KEY")
    base = os.getenv("GPTsAPI_BASE", "https://kuaipao.pro/v1").rstrip("/")
    model = os.getenv("GPTsAPI_IMAGE_MODEL", "gpt-image-2")
    response = None
    for attempt in range(3):
        response = requests.post(
            f"{base}/images/generations",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "prompt": prompt, "n": 1, "size": "1024x1024"},
            timeout=180,
        )
        if response.status_code < 500:
            break
        print(f"生成接口 {response.status_code}，重试 {attempt + 1}/3", flush=True)
    response.raise_for_status()
    item = (response.json().get("data") or [])[0]
    image_bytes = base64.b64decode(item["b64_json"]) if item.get("b64_json") else requests.get(item["url"], timeout=60).content
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    image.thumbnail((512, 512), Image.Resampling.LANCZOS)
    image.save(output_path, format="WebP", quality=85, method=6)


def main() -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"prompt_set": "prompt_set_0_original", "style": "当前正式提示词：第一版简洁图解 + 宣纸背景母版", "items": []}
    for sample_no, problem_type, question in QUESTIONS:
        filename = f"xuan_paper_{sample_no}_{problem_type}.webp"
        output_path = output_dir / filename
        if output_path.exists():
            print(f"已存在，跳过: {output_path}", flush=True)
        else:
            generate_image(build_image_prompt({"question": question}), output_path)
            print(f"已生成: {output_path}", flush=True)
        manifest["items"].append({"file": filename, "sample_no": sample_no, "problem_type": problem_type, "question": question})
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""图片压缩工具：将图片统一为视觉模型可用的格式，控制 base64 请求体大小

背景：图片识别改用 base64 内联传给中转站（kuaipao.pro），前端可能直接上传数 MB 原图，
base64 后体积 +33%，需在服务端先压缩/归一化。
"""
import io

from PIL import Image

MAX_SIDE = 2048                 # 长边超过该值则降采样（题目截图文字识别够用）
MAX_BYTES = 3 * 1024 * 1024     # 重编码目标：base64 前字节数上限
DIRECT_MIME = {"image/jpeg", "image/png"}  # 无需重编码即可直传的格式


def compress_image_for_vision(image_data: bytes, mime_type: str) -> tuple[bytes, str]:
    """压缩图片用于视觉模型输入，返回 (字节, MIME 类型)。

    - 小尺寸 JPEG/PNG 原样返回，避免无谓重编码损失文字清晰度；
    - 超大图降采样，gif/bmp/webp 等统一转 JPEG（动图取第一帧，透明底贴白）。
    解码失败（非图片字节）时抛出异常，由调用方处理。
    """
    # 已是 JPEG/PNG 且体积、尺寸均未超阈值：原样直传
    # （尺寸也要查：大分辨率小体积的图不降采样会浪费视觉 token）
    if mime_type in DIRECT_MIME and len(image_data) <= MAX_BYTES:
        with Image.open(io.BytesIO(image_data)) as probe:
            if max(probe.size) <= MAX_SIDE:
                return image_data, mime_type

    img = Image.open(io.BytesIO(image_data))
    if getattr(img, "is_animated", False):
        img.seek(0)  # gif 动图只取第一帧
    if img.mode in ("RGBA", "LA", "P"):
        # 透明/调色板图先贴白底再转 RGB，避免 JPEG 透明区变黑
        rgba = img.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        bg.alpha_composite(rgba)
        img = bg.convert("RGB")
    else:
        img = img.convert("RGB")

    if max(img.size) > MAX_SIDE:
        img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)

    # quality 递降重编码，直到满足体积上限
    buf = io.BytesIO()
    for quality in (85, 70, 50):
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        if len(buf.getvalue()) <= MAX_BYTES:
            break
    return buf.getvalue(), "image/jpeg"

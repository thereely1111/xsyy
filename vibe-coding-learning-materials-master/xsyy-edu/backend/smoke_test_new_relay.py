#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""新中转站(kuaipao.pro)冒烟自检
- 验证 claude-opus-4-8 chat.completions
- 验证 gpt-image-2 images/generations (base64 路径)
"""
import os, requests, base64, time
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parent / ".env")

KEY       = os.getenv("KIMI_API_KEY")
BASE      = os.getenv("KIMI_BASE_URL")
TXT_MODEL = os.getenv("KIMI_MODEL")
IMG_BASE  = os.getenv("GPTsAPI_BASE")
IMG_MODEL = os.getenv("GPTsAPI_IMAGE_MODEL", "gpt-image-2")
IMG_KEY   = os.getenv("GPTsAPI_KEY")

print(f"TXT : {TXT_MODEL} @ {BASE}")
print(f"IMG : {IMG_MODEL} @ {IMG_BASE}")
print(f"KEY same: {KEY == IMG_KEY}")
print()

H = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}

# 1) 文本
print("[1/2] POST", f"{BASE}/chat/completions")
t0 = time.time()
r = requests.post(f"{BASE}/chat/completions", headers=H, json={
    "model": TXT_MODEL,
    "messages": [{"role": "user", "content": "用一句话回复：1+1=？"}],
    "max_tokens": 64,
}, timeout=60)
print(f"  HTTP {r.status_code}  ({time.time()-t0:.1f}s)")
if r.status_code == 200:
    j = r.json()
    msg = (j.get("choices") or [{}])[0].get("message", {}).get("content", "")
    print(f"  reply: {msg[:160]!r}")
    print(f"  usage: {j.get('usage')}")
else:
    print(f"  body: {r.text[:400]}")

print()

# 2) 图片
print("[2/2] POST", f"{IMG_BASE}/images/generations")
t0 = time.time()
r2 = requests.post(f"{IMG_BASE}/images/generations", headers=H, json={
    "model": IMG_MODEL,
    "prompt": "a tiny red dot on white paper",
    "n": 1,
    "size": "1024x1024",
}, timeout=180)
print(f"  HTTP {r2.status_code}  ({time.time()-t0:.1f}s)")
if r2.status_code == 200:
    j2 = r2.json()
    items = j2.get("data") or []
    if items:
        it = items[0]
        b64 = it.get("b64_json")
        url = it.get("url")
        if b64:
            b = base64.b64decode(b64)
            print(f"  b64_json decoded: {len(b)} bytes, head={b[:4]}")
        elif url:
            print(f"  url: {url[:120]}")
        else:
            print(f"  no b64_json/url. keys={list(it.keys())}")
    else:
        print(f"  no data. body: {r2.text[:400]}")
else:
    print(f"  body: {r2.text[:400]}")

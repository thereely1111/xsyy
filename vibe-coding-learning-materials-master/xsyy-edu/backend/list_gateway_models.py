#!/usr/bin/env python3
"""
列出网关可用的模型
"""

import asyncio
import aiohttp
import json
import os
from dotenv import load_dotenv

load_dotenv()

async def list_models():
    """列出网关可用的模型"""
    api_key = os.getenv("ZENMUX_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("请先在 .env 中配置 ZENMUX_API_KEY")
    
    # 尝试不同的路径来列出模型
    paths_to_try = [
        "/v1/models",
        "/models",
        "/api/v1/models",
        "/v1beta/models",
    ]
    
    base_url = "https://ai-gateway.eo-edgefunctions7.com"
    
    headers = {
        "X-Goog-Api-Key": api_key,
        "OE-Gateway-Version": "2",
        "OE-Key": "2c8f1178d7e74a83a6e0ab5fe83c812a",
        "OE-Gateway-Name": "test",
        "OE-AI-Provider": "gemini",
        "Content-Type": "application/json"
    }
    
    for path in paths_to_try:
        url = f"{base_url}{path}"
        print(f"\n尝试路径: {url}")
        
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=headers) as response:
                    print(f"  状态码: {response.status}")
                    response_text = await response.text()
                    
                    if response.status == 200:
                        try:
                            result = json.loads(response_text)
                            print(f"  ✓ 成功！可用模型:")
                            print(json.dumps(result, indent=2, ensure_ascii=False))
                            return
                        except:
                            print(f"  响应: {response_text[:500]}")
                    else:
                        print(f"  响应: {response_text[:200]}")
        except Exception as e:
            print(f"  ✗ 失败: {e}")

if __name__ == "__main__":
    asyncio.run(list_models())


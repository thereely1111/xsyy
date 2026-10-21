#!/usr/bin/env python3
"""
调试网关 API，查看实际的请求和响应格式
"""

import asyncio
import aiohttp
import json
import os
from dotenv import load_dotenv

load_dotenv()

async def debug_gateway_api():
    """调试网关 API"""
    url = "https://ai-gateway.eo-edgefunctions7.com"
    
    api_key = os.getenv("ZENMUX_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("请先在 .env 中配置 ZENMUX_API_KEY")
    
    headers = {
        "X-Goog-Api-Key": api_key,
        "OE-Gateway-Version": "2",
        "OE-Key": "2c8f1178d7e74a83a6e0ab5fe83c812a",
        "OE-Gateway-Name": "test",
        "OE-AI-Provider": "gemini",
        "Content-Type": "application/json"
    }
    
    # 测试不同的模型名称
    models_to_test = [
        os.getenv("ZENMUX_HTML_MODEL", "google/gemini-3.1-pro-preview"),
        "gemini-1.5-pro",
        "gemini-1.5-flash",
        "gemini-pro",
    ]
    
    for model in models_to_test:
        print(f"\n{'='*60}")
        print(f"测试模型: {model}")
        print(f"{'='*60}")
        
        body = {
            "model": model,
            "messages": [{"content": "Hello"}],
            "stream": False
        }
        
        print(f"\n请求 URL: {url}")
        print(f"请求 Headers:")
        for k, v in headers.items():
            if k == "X-Goog-Api-Key":
                print(f"  {k}: {v[:20]}...")
            else:
                print(f"  {k}: {v}")
        print(f"\n请求 Body:")
        print(json.dumps(body, indent=2, ensure_ascii=False))
        
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, headers=headers, json=body) as response:
                    print(f"\n响应状态码: {response.status}")
                    print(f"响应 Headers:")
                    for k, v in response.headers.items():
                        print(f"  {k}: {v}")
                    
                    response_text = await response.text()
                    print(f"\n响应内容:")
                    try:
                        response_json = json.loads(response_text)
                        print(json.dumps(response_json, indent=2, ensure_ascii=False))
                    except:
                        print(response_text)
                    
                    if response.status == 200:
                        print(f"\n✓ 模型 {model} 可用！")
                        break
                    else:
                        print(f"\n✗ 模型 {model} 不可用")
        except Exception as e:
            print(f"\n✗ 请求失败: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(debug_gateway_api())


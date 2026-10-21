#!/usr/bin/env python3
"""
测试网关 LLM 是否能正常工作
使用方法: python test_gateway_llm.py
"""

import asyncio
import sys
from pathlib import Path

# 添加当前目录到路径
backend_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(backend_dir))

from gateway_llm import GatewayChatModel
from langchain_core.messages import HumanMessage, SystemMessage


async def test_gateway_llm():
    """测试网关 LLM"""
    print("=" * 60)
    print("测试网关 LLM")
    print("=" * 60)
    
    try:
        # 创建网关 LLM 实例
        print("\n1. 创建网关 LLM 实例...")
        llm = GatewayChatModel(
            model="google/gemini-3.1-pro-preview",
            gateway_key="2c8f1178d7e74a83a6e0ab5fe83c812a",
            gateway_name="test",
            timeout=180
        )
        print("✓ LLM 实例创建成功")
        
        # 测试 1: 简单消息
        # 测试 0: 先测试 API 连接（不通过 LLM）
        print("\n2. 测试 API 连接...")
        import aiohttp
        test_url = "https://ai-gateway.eo-edgefunctions7.com"
        test_headers = {
            "X-Goog-Api-Key": llm.api_key,
            "OE-Gateway-Version": "2",
            "OE-Key": "2c8f1178d7e74a83a6e0ab5fe83c812a",
            "OE-Gateway-Name": "test",
            "OE-AI-Provider": "gemini",
            "Content-Type": "application/json"
        }
        test_body = {
            "model": "google/gemini-3.1-pro-preview",
            "messages": [{"content": "Hello"}],
            "stream": False
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(test_url, headers=test_headers, json=test_body) as resp:
                    print(f"   状态码: {resp.status}")
                    resp_text = await resp.text()
                    print(f"   响应: {resp_text[:500]}...")
                    if resp.status != 200:
                        print(f"   ⚠️  API 返回错误，请检查网关配置")
        except Exception as e:
            print(f"   ✗ 连接失败: {e}")
        
        print("\n3. 测试简单消息...")
        messages = [
            HumanMessage(content="什么是 Gemini AI？")
        ]
        
        print("   发送消息: 什么是 Gemini AI？")
        response = await llm.ainvoke(messages)
        print(f"✓ 收到响应:")
        print(f"   {response.content[:200]}..." if len(response.content) > 200 else f"   {response.content}")
        
        # 测试 2: 带系统提示的消息
        print("\n4. 测试带系统提示的消息...")
        messages_with_system = [
            SystemMessage(content="你是一个专业的数学老师。"),
            HumanMessage(content="请解释什么是勾股定理？")
        ]
        
        print("   发送消息: 请解释什么是勾股定理？")
        response2 = await llm.ainvoke(messages_with_system)
        print(f"✓ 收到响应:")
        print(f"   {response2.content[:200]}..." if len(response2.content) > 200 else f"   {response2.content}")
        
        # 测试 3: 使用字典格式（兼容 pipeline.py 的调用方式）
        print("\n5. 测试字典格式消息（兼容 pipeline.py）...")
        messages_dict = [
            {"role": "system", "content": "你是一个专业的数学老师。"},
            {"role": "user", "content": "请用简单的话解释什么是分数？"}
        ]
        
        # 转换为 LangChain 消息格式
        langchain_messages = []
        for msg in messages_dict:
            if msg["role"] == "system":
                langchain_messages.append(SystemMessage(content=msg["content"]))
            elif msg["role"] == "user":
                langchain_messages.append(HumanMessage(content=msg["content"]))
        
        print("   发送消息: 请用简单的话解释什么是分数？")
        response3 = await llm.ainvoke(langchain_messages)
        print(f"✓ 收到响应:")
        print(f"   {response3.content[:200]}..." if len(response3.content) > 200 else f"   {response3.content}")
        
        print("\n" + "=" * 60)
        print("✓ 所有测试通过！")
        print("=" * 60)
        
    except ValueError as e:
        print(f"\n✗ 配置错误: {e}")
        print("\n请确保:")
        print("  1. 已设置 ZENMUX_API_KEY 环境变量")
        print("  2. 或在 .env 文件中配置了 ZENMUX_API_KEY")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(test_gateway_llm())

#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
快速测试 Gemini API 连接和模型可用性

这个脚本使用 google-genai 库的 genai.Client 方式调用 Gemini API（异步方式）。
"""

import asyncio
import os
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types

# 加载 .env 文件
backend_dir = Path(__file__).resolve().parent
env_path = backend_dir / ".env"
load_dotenv(dotenv_path=env_path)
system_prompt = """# Role
You are an expert EdTech Full-Stack Developer and UI/UX Designer. You specialize in creating "Single-File HTML Interactive Teaching Apps" for children. You combine technical expertise (HTML5, Tailwind CSS, JS) with child psychology to make complex math concepts simple and engaging.

# Goal
Your task is to generate a standalone, responsive web application that visually explains a specific math problem.

# Tech Stack & Output Format
1. **Single File**: Output ONLY a single HTML file containing logic, styling, and structure.
2. **Styling**: Use Tailwind CSS via CDN.
3. **Logic**: Use Native JavaScript (ES6+) or Alpine.js for state management.
4. **No External Assets**: Use Emojis, CSS shapes, or SVG for visuals. Do not use `<img>` tags linking to external files.

# UI/UX Design Specifications (STRICTLY FOLLOW)
1. **Global Style**:
   - Background: `bg-gray-100`.
   - Aesthetics: Rounded UI (`rounded-xl` or `rounded-2xl`), Soft Shadows, Clean Typography.
   - Layout: Dashboard style. Responsive (Vertical stack on mobile, Split view on desktop).

2. **Header (Control Bar)**:
   - Left: App Title & Icon.
   - Middle: The Problem Text.
   - Right: Input fields for variables (Underlined or Minimalist) & a "Reset" button.

3. **Left Column (Visual Canvas)**:
   - Container: White card (`bg-white`), shadow, rounded.
   - Top: Status bar (showing current counts/stats).
   - Content: A visual stage using Grid or Flexbox to show elements (people, objects, geometric shapes) with CSS transitions for movement/appearance.

4. **Right Column (Sidebar/Teaching Area)**:
   - **Module A (Stepper)**: Progress indicator (e.g., "Step 2/5") with dots/lines.
   - **Module B (The Blackboard - CORE)**: 
     - Style: Dark card (e.g., `bg-slate-700` or `bg-blue-900`), White text.
     - Content: "Teacher's" explanation. Simple, conversational Chinese.
     - Bottom: A distinct section for Math Formulas/Derivations using monospaced font.
   - **Module C (Action Button)**:
     - Style: Full-width, Prominent (e.g., `bg-blue-600`), Large text.
     - Behavior: "Next Step", "Start", or "Finish" based on state.

# Interaction Logic
1. **State Management**: The app must have a `currentStep` state.
2. **Step-by-Step Guide**: Clicking the Action Button advances the logic.
   - **Visuals**: Update animation/elements on the Left.
   - **Blackboard**: Update explanation and formulas on the Right.
3. **Reactivity**: Changing inputs in the Header must immediately reset the visualization to the initial state.

# Language
All text must be in **Simplified Chinese (简体中文)**.
"""
mock_output = """---
**题目内容：**
一个长方形的长是 8 厘米，宽是 5 厘米，求这个长方形的周长和面积。

**具体要求：**
1. **默认参数**：
   - 变量 长 = 8（允许范围 1 - 20，单位：厘米）。
   - 变量 宽 = 5（允许范围 1 - 20，单位：厘米）。

2. **解题方法选择**：
   - 采用"图形演示法"。
   - 核心逻辑：通过绘制长方形，标注边长，逐步计算周长和面积。

3. **分步演示逻辑（傻瓜式教学）**：
   - **初始状态**：左侧画布显示一个长方形，标注长和宽，黑板显示题目。
   - **步骤 1**：计算周长，动画展示四条边，黑板显示"周长 = 长 + 宽 + 长 + 宽 = 8 + 5 + 8 + 5 = 26 厘米"。
   - **步骤 2**：引入周长公式，黑板显示"周长 = (长 + 宽) × 2 = (8 + 5) × 2 = 26 厘米"。
   - **步骤 3**：计算面积，动画展示长方形被分成小方格，黑板显示"面积 = 长 × 宽 = 8 × 5 = 40 平方厘米"。
   - **最终总结**：显示答案"周长 26 厘米，面积 40 平方厘米"。
---
"""
user_prompt = """请为一个数学问题制作交互式教学应用。

__PRE_OUT__

请直接输出符合 System Prompt 规范的 HTML 代码。不要输出无关内容。
"""
user_prompt = user_prompt.replace("__PRE_OUT__", mock_output)
async def test_gemini_connection():
    """测试 Gemini API 连接（使用 google-genai 的 genai.Client 方式）"""
    
    print("=" * 80)
    print("测试 Gemini API 连接（使用 google-genai Client 方式）")
    print("=" * 80)
    print()
    
    # 检查 API Key
    api_key = os.getenv("ZENMUX_API_KEY") or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("❌ 错误：未找到 ZENMUX_API_KEY / GEMINI_API_KEY / GOOGLE_API_KEY 环境变量")
        print("请在 .env 文件中优先配置 ZENMUX_API_KEY")
        return
    
    print(f"✓ ZENMUX/Gemini API Key 已配置（长度: {len(api_key)} 字符）")
    
    # 检查模型名称
    model_name = os.getenv("ZENMUX_HTML_MODEL") or os.getenv("GEMINI_MODEL_NAME", "google/gemini-3.1-pro-preview")
    print(f"✓ 使用模型: {model_name}")
    print()
    
    # 步骤 1: 初始化 Client
    print("-" * 80)
    print("步骤 1: 初始化 genai.Client")
    print("-" * 80)
    try:
        base_url = os.getenv("ZENMUX_BASE_URL", "https://zenmux.ai/api/vertex-ai")
        client = genai.Client(api_key=api_key, http_options={'api_version': 'v1alpha', 'base_url': base_url})
        print("✓ Client 初始化成功")
    except Exception as e:
        print(f"❌ Client 初始化失败: {e}")
        print()
        print("可能的原因：")
        print("1. API Key 无效")
        print("2. google-genai 库未安装（运行: pip install google-genai）")
        print("3. 网络连接问题")
        import traceback
        traceback.print_exc()
        return
    
    print()
    
    # 步骤 2: 测试简单调用（不使用工具）
    print("-" * 80)
    print("步骤 2: 测试简单 API 调用（不使用工具）")
    print("-" * 80)
    print("发送测试消息: '你好，请回复一个数字 42'")
    print()
    
    try:
        import time
        start_time = time.time()
        
        contents = [
            types.Content(
                role="user",
                parts=[
                    types.Part.from_text(text="你好，请回复一个数字 42"),
                ],
            ),
        ]
        
        # 使用异步调用（非流式）
        print("正在调用 Gemini API（异步方式）...")
        
        # 使用 asyncio.to_thread 将同步调用包装成异步
        def generate_content_sync():
            """同步生成内容的辅助函数"""
            response = client.models.generate_content(
                model=model_name,
                contents=contents,
            )
            return response
        
        response = await asyncio.to_thread(generate_content_sync)
        
        # 提取响应文本
        response_text = ""
        if hasattr(response, 'text'):
            response_text = response.text
        elif hasattr(response, 'candidates') and response.candidates:
            candidate = response.candidates[0]
            if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                for part in candidate.content.parts:
                    if hasattr(part, 'text'):
                        response_text += part.text
        
        elapsed = time.time() - start_time
        print()
        print("响应内容:")
        print("-" * 80)
        print(response_text)
        print("-" * 80)
        print()
        print(f"✓ API 调用成功！耗时: {elapsed:.2f} 秒")
        print(f"响应总长度: {len(response_text)} 字符")
        print()
        print("=" * 80)
        print("✓ Gemini API 连接测试通过！")
        print("=" * 80)
        
    except Exception as e:
        elapsed = time.time() - start_time if 'start_time' in locals() else 0
        print()
        print(f"❌ API 调用失败，已等待 {elapsed:.2f} 秒")
        print(f"错误信息: {e}")
        print()
        print("可能的原因：")
        print("1. 网络连接慢或不稳定")
        print("2. API 服务响应慢")
        print("3. 模型名称不正确")
        print("4. API Key 权限问题")
        print()
        import traceback
        traceback.print_exc()
        return
    
    print()
    
    # 步骤 3: 测试带工具的调用（可选）
    print("-" * 80)
    print("步骤 3: 测试带生成网页（可选）")
    print("-" * 80)
    print(f"发送测试消息: {user_prompt[:100]}..." if len(user_prompt) > 100 else f"发送测试消息: {user_prompt}")
    print()
    

    try:
        import time
        start_time = time.time()
        
        contents = [
            types.Content(
                role="user",
                parts=[
                    types.Part.from_text(text=user_prompt),
                ],
            ),
        ]
        
        generate_content_config = types.GenerateContentConfig(
            thinkingConfig={
                "thinkingLevel": "HIGH",
            },
            system_instruction=system_prompt,
            max_output_tokens=16384,  # 限制输出长度
            http_options=types.HttpOptions(
                timeout=180000,  # 3分钟超时（180000毫秒）
            ),
        )
        
        # 使用异步流式调用
        print("正在调用 Gemini API（异步流式方式）...")
        print("响应内容（流式输出）:")
        print("-" * 80)
        
        # 使用 asyncio.to_thread 将同步流式调用包装成异步
        def generate_content_stream_sync():
            """同步流式生成内容的辅助函数"""
            response_text = ""
            for chunk in client.models.generate_content_stream(
                model=model_name,
                contents=contents,
                config=generate_content_config,
            ):
                if hasattr(chunk, 'text') and chunk.text:
                    print(chunk.text, end="", flush=True)  # 实时输出
                    response_text += chunk.text
            return response_text
        
        # 异步调用流式生成
        response_text = await asyncio.to_thread(generate_content_stream_sync)
        
        elapsed = time.time() - start_time
        print()
        print("-" * 80)
        print()
        print(f"✓ 流式 API 调用成功！耗时: {elapsed:.2f} 秒")
        print(f"响应总长度: {len(response_text)} 字符")
        print()
        
        # 保存生成的 HTML 到文件
        teaching_html_path = backend_dir.parent / "teaching_test.html"
        with open(teaching_html_path, "w", encoding="utf-8") as f:
            f.write(response_text)
        print(f"✓ 生成的 HTML 已保存到: {teaching_html_path}")
        print()
        
        # 显示响应内容预览（前 1000 字符）
        print("响应内容预览（前 1000 字符）:")
        print("-" * 80)
        print(response_text[:1000])
        if len(response_text) > 1000:
            print("...")
            print(f"（共 {len(response_text)} 字符，完整内容已保存到文件）")
        print("-" * 80)
        print()
        print("=" * 80)
        print("✓ 流式调用测试通过！")
        print("=" * 80)
        
    except Exception as e:
        elapsed = time.time() - start_time if 'start_time' in locals() else 0
        print()
        print(f"⚠ 流式调用测试失败（不影响主测试）: {e}")
        print(f"已等待 {elapsed:.2f} 秒")
        print("（这可能是正常的，取决于模型是否支持流式输出或网络连接）")
        print()
        import traceback
        traceback.print_exc()
        



if __name__ == "__main__":
    asyncio.run(test_gemini_connection())


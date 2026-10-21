#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试 Gemini 程序员大模型（使用与 pipeline.py 相同的调用方式）

这个脚本会：
1. 伪造教学设计师（DeepSeek）的输出内容
2. 使用与 pipeline.py 完全相同的方式调用 Gemini 程序员大模型生成 HTML
3. 显示生成的 HTML 内容
"""

import asyncio
import os
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types

# 加载 .env 文件
backend_dir = Path(__file__).resolve().parent.parent
print(backend_dir)
env_path = backend_dir / ".env"
load_dotenv(dotenv_path=env_path)
ZENMUX_BASE_URL = os.getenv("ZENMUX_BASE_URL", "https://zenmux.ai/api/vertex-ai")

def create_mock_designer_output(question_type: str = "default") -> str:
    """创建伪造的教学设计师输出内容（模拟 DeepSeek 的输出格式）
    
    这个函数返回一个符合 extract_system_prompt.txt 中定义格式的 Markdown 文档。
    可以根据需要修改题目内容来测试不同的场景。
    
    Args:
        question_type: 题目类型，可选值：
            - "default": 乒乓球比赛组合问题（默认）
            - "simple": 简单的加减法问题
            - "complex": 复杂的应用题
    """
    
    if question_type == "simple":
        # 简单的加减法问题
        mock_output = """---
**题目内容：**
小明有 5 个苹果，吃了 2 个，还剩几个？

**具体要求：**
1. **默认参数**：
   - 变量 初始苹果数 = 5（允许范围 1 - 10）。
   - 变量 吃掉数量 = 2（允许范围 1 - 初始苹果数）。

2. **解题方法选择**：
   - 采用"实物演示法"。
   - 核心逻辑：通过动画展示苹果的减少过程，让小学生直观理解减法。

3. **分步演示逻辑（傻瓜式教学）**：
   - **初始状态**：左侧画布显示 5 个红色圆形（代表苹果），黑板显示题目："小明有 5 个苹果，吃了 2 个，还剩几个？"
   - **步骤 1**：高亮显示 5 个苹果，黑板显示"原来有 5 个苹果"。
   - **步骤 2**：动画展示吃掉 2 个苹果（苹果逐渐消失或变灰），黑板显示"吃掉了 2 个"。
   - **步骤 3**：剩余 3 个苹果高亮显示，黑板显示"还剩 5 - 2 = 3 个苹果"。
   - **最终总结**：显示答案"还剩 3 个苹果"，并总结："减法就是从一个数中拿走一些，剩下的就是答案。"
---
"""
    elif question_type == "complex":
        # 复杂的应用题
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
    else:
        # 默认：乒乓球比赛组合问题
        mock_output = """---
**题目内容：**
学校进行乒乓球选拔赛，每个参赛选手都要和其他所有选手各赛一场，一共有10位参赛选手，问一共要进行多少场比赛？

**具体要求：**
1. **默认参数**：
   - 变量 N（参赛选手数）= 10（允许范围 2 - 20）。

2. **解题方法选择**：
   - 采用"组合计数法"。
   - 核心逻辑：利用组合数学中的 C(n,2) 公式，即从 n 个选手中选择 2 个进行比赛，计算组合数。

3. **分步演示逻辑（傻瓜式教学）**：
   - **初始状态**：左侧画布显示 10 个圆形代表 10 位选手，每个选手都有编号（1-10）。黑板显示题目："10 位选手，每两人比赛一场，共多少场？"
   - **步骤 1**：高亮选手 1，然后依次连接选手 2、3、4...10，每连接一次，右侧黑板显示"选手1 vs 选手2"、"选手1 vs 选手3"等，并累计显示已进行的比赛场数（1场、2场、3场...9场）。解释："选手1需要和其他9位选手各赛一场，共9场比赛。"
   - **步骤 2**：高亮选手 2，然后依次连接选手 3、4、5...10（跳过选手1，因为已经比赛过了），每连接一次，黑板累计显示比赛场数（10场、11场...17场）。解释："选手2需要和剩余的8位选手各赛一场，共8场比赛。"
   - **步骤 3**：继续同样的逻辑，选手3连接选手4-10（7场），选手4连接选手5-10（6场），以此类推。每完成一个选手，黑板显示累计场数和当前选手的比赛场数。
   - **步骤 4**：当所有选手都完成连接后，显示最终结果。黑板显示公式：9+8+7+6+5+4+3+2+1 = 45，并解释："这是等差数列求和，首项9，末项1，项数9，和 = (9+1)×9÷2 = 45。"
   - **步骤 5**：引入组合公式 C(10,2) = 10×9÷2 = 45，解释："从10个选手中选2个进行比赛，就是组合数 C(10,2)。"
   - **最终总结**：显示答案"共需要进行 45 场比赛"，并总结："n 位选手的比赛场数 = C(n,2) = n×(n-1)÷2。"
---
"""
    
    return mock_output


def load_prompt_template(file_path: Path) -> str:
    """从文件加载 prompt 模板（与 pipeline.py 中的方法相同）。"""
    try:
        if file_path.exists():
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read().strip()
        else:
            print(f"⚠ Prompt 文件不存在: {file_path}")
            return ""
    except Exception as e:
        print(f"❌ 读取 Prompt 文件失败 {file_path}: {e}")
        return ""


async def test_gemini_programmer(question_type: str = "default"):
    """测试 Gemini 程序员大模型（使用与 pipeline.py 完全相同的方式）
    
    Args:
        question_type: 题目类型，可选值：
            - "default": 乒乓球比赛组合问题（默认）
            - "simple": 简单的加减法问题
            - "complex": 复杂的应用题
    """
    
    print("=" * 80)
    print("测试 Gemini 程序员大模型（使用 pipeline.py 相同的调用方式）")
    print("=" * 80)
    print()
    
    # 检查 API Key
    api_key = os.getenv("ZENMUX_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("❌ 错误：未找到 ZENMUX_API_KEY 环境变量")
        print("请在 .env 文件中配置 ZENMUX_API_KEY")
        return
    
    print(f"✓ ZENMUX_API_KEY 已配置（长度: {len(api_key)} 字符）")
    
    # 检查模型名称
    model_name = os.getenv("ZENMUX_HTML_MODEL") or os.getenv("GEMINI_MODEL_NAME", "google/gemini-3.1-pro-preview")
    print(f"✓ 使用模型: {model_name}")
    print()
    
    # 步骤 1: 初始化 Client（与 pipeline.py 相同）
    print("-" * 80)
    print("步骤 1: 初始化 genai.Client")
    print("-" * 80)
    try:
        client = genai.Client(api_key=api_key, http_options={'api_version': 'v1alpha', 'base_url': ZENMUX_BASE_URL})
        
        print("✓ Client 初始化成功")
    except Exception as e:
        print(f"❌ Client 初始化失败: {e}")
        import traceback
        traceback.print_exc()
        return
    
    print()
    
    # 步骤 2: 准备题目和标题（与 pipeline.py 相同，不再使用设计文档）
    print("-" * 80)
    print("步骤 2: 准备题目和标题")
    print("-" * 80)
    print(f"题目类型: {question_type}")
    
    # # 根据题目类型设置题目和标题
    # if question_type == "simple":
    #     question = "小明有 5 个苹果，吃了 2 个，还剩几个？"
    #     title = "简单减法"
    # elif question_type == "complex":
    #     question = "一个长方形的长是 8 厘米，宽是 5 厘米，求这个长方形的周长和面积。"
    #     title = "长方形周长面积"
    # else:
    #     question = "学校进行乒乓球选拔赛，每个参赛选手都要和其他所有选手各赛一场，一共有10位参赛选手，问一共要进行多少场比赛？"
    #     title = "组合计数问题"
    
    question = "姐姐和妹妹共有书39本，如果姐姐给妹妹7本后就比妹妹少3本，那么姐姐和妹妹原来各有书多少本?"
    title = "和差问题"
    print(f"题目: {question}")
    print(f"标题: {title}")
    print()
    
    # 步骤 3: 加载 prompt 模板（与 pipeline.py 相同）
    print("-" * 80)
    print("步骤 3: 加载 prompt 模板")
    print("-" * 80)
    prompt_dir = backend_dir / "prompt"
    teaching_system_prompt_path = prompt_dir / "teaching_system_prompt.txt"
    teaching_user_prompt_path = prompt_dir / "teaching_user_prompt.txt"
    
    system_prompt = load_prompt_template(teaching_system_prompt_path)
    user_prompt_template = load_prompt_template(teaching_user_prompt_path)
    
    # 如果模板文件不存在，使用默认 prompt（与 pipeline.py 相同）
    if not system_prompt:
        system_prompt = (
            "You are an expert EdTech Full-Stack Developer and UI/UX Designer. "
            "You specialize in creating Single-File HTML Interactive Teaching Apps for children."
        )
        print("⚠ 使用默认系统提示词")
    else:
        print(f"✓ 系统提示词已加载（长度: {len(system_prompt)} 字符）")
    
    # 构建题目和标题的输入内容（与 pipeline.py 相同）
    # 从 mock_design_output 中提取题目，如果没有则使用默认
    # question = "学校进行乒乓球选拔赛，每个参赛选手都要和其他所有选手各赛一场，一共有10位参赛选手，问一共要进行多少场比赛？"
    # title = "组合计数问题"
    
    question_content = f"题目：{question}\n标题：{title}"
    
    if not user_prompt_template:
        user_prompt = f"请为一个数学问题制作交互式教学应用。\n\n{question_content}"
        print("⚠ 使用默认用户提示词")
    else:
        # 替换模板中的占位符，传入题目和标题（与 pipeline.py 相同）
        user_prompt = user_prompt_template.replace("__PRE_OUT__", question_content)
        print(f"✓ 用户提示词已加载（长度: {len(user_prompt)} 字符）")
    
    print()


    # 步骤 4: 调用 Gemini 程序员大模型（与 pipeline.py 完全相同的方式）
    print("-" * 80)
    # print("步骤 3.9: 跑通Gemini API")


    client = genai.Client(api_key=api_key, http_options={'api_version': 'v1alpha', 'base_url': ZENMUX_BASE_URL})


    if question_type == "normal":
        print("-" * 80)
        print("步骤 3.5: 图片输入测试（带图片生成 HTML）")
        print("-" * 80)
        try:


            contents = [
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_text(text=user_prompt)
                    ],
                ),
            ]

            generate_content_config = types.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=16384,
                http_options=types.HttpOptions(timeout=180000),
            )

            resp = client.models.generate_content(
                model=model_name,
                contents=contents,
                config=generate_content_config,
            )
            print("✓ 图片输入调用成功，返回文本预览（前 500 字符）：")
            print(resp.text[:500])
        except Exception as e:
            print(f"❌ 图片输入测试失败: {e}")
        print("-" * 80)
        print()
        return

        # response = client.models.generate_content(
        #     model='gemini-2.5-flash',
        #     contents="Explain how AI works",
        # )

        # print(response.text)
        # print("-" * 80)
        # print("跑通Gemini API成功")
        # print()

        # return
    elif question_type == "image":
        # 步骤 4: 调用 Gemini 程序员大模型（与 pipeline.py 完全相同的方式）
        print("-" * 80)
        print("步骤 4: 调用 Gemini 程序员大模型生成 HTML（带图片输入）")
        print("-" * 80)
        print("正在生成 HTML，请耐心等待...")
        print()
        
        try:
            import time
            from datetime import datetime
            
            start_time = time.time()
            timeout_seconds = int(os.getenv("GEMINI_API_TIMEOUT", "180"))
            max_retries = 2
            image_path = backend_dir / "utils" / "test_pic" / "test_image2.png"
            mime_type = "image/png"
            with open(image_path, "rb") as f:
                image_bytes = f.read()  
            # 构建用户 prompt（和 pipeline 一致）
            question = "设P是平行四边形 ABCD 内部的一点，且∠PBA=∠PDA求证:∠PAB=∠PCB"
            title = "平行四边形"
            question_content = f"题目：{question}\n标题：{title}"
            user_prompt = user_prompt_template.replace("__PRE_OUT__", question_content)
            # 构建消息内容（与 pipeline.py 相同：只传入 user_prompt，system_prompt 通过 config 传入）
            contents = [
                types.Content(
                    role="user",
                    parts=[
                        {"inline_data": {"mime_type": "image/jpeg", "data": image_bytes}},
                        # {"text": user_prompt}
                        # types.Part.from_text(text=user_prompt),
                        # types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                    ],
                ),
            ]
            
            # 创建配置（与 pipeline.py 相同）
            generate_content_config = types.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=16384,  # 限制输出长度
                http_options=types.HttpOptions(
                    timeout=180000,  # 3分钟超时（180000毫秒）
                ),
            )
            
            # 使用流式调用（与 pipeline.py 相同）
            print("正在调用 Gemini API（流式方式）...")
            
            for attempt in range(max_retries + 1):
                try:
                    print(f"Gemini API 调用尝试 {attempt + 1}/{max_retries + 1}...")
                    
                    # 使用 asyncio.to_thread 将同步流式调用包装成异步（与 pipeline.py 相同）
                    def generate_content_stream_sync():
                        """同步流式生成内容的辅助函数"""
                        html = ""
                        for chunk in client.models.generate_content_stream(
                            model=model_name,
                            contents=contents,
                            config=generate_content_config,
                        ):
                            if hasattr(chunk, 'text') and chunk.text:
                                html += chunk.text
                        return html
                    
                    # 使用 asyncio.wait_for 设置超时，并用 to_thread 包装同步流式调用
                    teaching_html = await asyncio.wait_for(
                        asyncio.to_thread(generate_content_stream_sync),
                        timeout=timeout_seconds
                    )
                    
                    elapsed = time.time() - start_time
                    print()
                    print(f"✓ Gemini API 调用成功！耗时: {elapsed:.2f} 秒")
                    print(f"生成的 HTML 长度: {len(teaching_html)} 字符")
                    print()
                    break  # 成功则跳出重试循环
                    
                except asyncio.TimeoutError:
                    elapsed = time.time() - start_time
                    if attempt < max_retries:
                        print(f"⚠ Gemini API 调用超时（{timeout_seconds}秒），已耗时: {elapsed:.2f} 秒，正在重试...")
                        await asyncio.sleep(2)  # 等待2秒后重试
                        start_time = time.time()  # 重置开始时间
                    else:
                        print(f"❌ Gemini API 调用超时（{timeout_seconds}秒），已重试 {max_retries} 次，最终失败")
                        raise TimeoutError(f"Gemini API 调用超时，超过 {timeout_seconds} 秒无响应")
                        
                except Exception as e:
                    elapsed = time.time() - start_time
                    if attempt < max_retries:
                        print(f"⚠ Gemini API 调用出错（已耗时: {elapsed:.2f} 秒）: {str(e)}，正在重试...")
                        await asyncio.sleep(2)  # 等待2秒后重试
                        start_time = time.time()  # 重置开始时间
                    else:
                        print(f"❌ Gemini API 调用失败，已重试 {max_retries} 次，最终错误: {str(e)}")
                        raise
            
            # 清理生成的 HTML（与 pipeline.py 相同）
            def clean_generated_html(html: str) -> str:
                """去除生成的 HTML 前后的 ```/```html 包裹"""
                if html is not None:
                    html = html.lstrip()
                    if html.startswith("```html"):
                        html = html[7:].lstrip()
                    elif html.startswith("```"):
                        html = html[3:].lstrip()
                    html = html.rstrip()
                    if html.endswith("```"):
                        html = html[:-3].rstrip()
                return html
            
            teaching_html = clean_generated_html(teaching_html)
            
            # 保存生成的 HTML 到文件
            output_file = backend_dir / "test_gemini_output.html"
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(teaching_html)
            print(f"✓ 生成的 HTML 已保存到: {output_file}")
            print()
            
            # 显示 HTML 内容预览（前 1000 字符）
            print("-" * 80)
            print("生成的 HTML 内容预览（前 1000 字符）:")
            print("-" * 80)
            print(teaching_html[:1000])
            if len(teaching_html) > 1000:
                print("...")
                print(f"（共 {len(teaching_html)} 字符，完整内容已保存到文件）")
            print()
            
            print("=" * 80)
            print("测试完成！")
            print("=" * 80)
            print()
            print(f"提示：可以在浏览器中打开 {output_file} 查看生成的 HTML 效果")
            
        except Exception as e:
            elapsed = time.time() - start_time if 'start_time' in locals() else 0
            print()
            print("=" * 80)
            print("❌ 测试失败")
            print("=" * 80)
            print(f"错误信息: {e}")
            print(f"已等待 {elapsed:.2f} 秒")
            print()
            print("可能的原因：")
            print("1. 网络连接慢或不稳定")
            print("2. API 服务响应慢")
            print("3. 模型名称不正确")
            print("4. API Key 权限问题")
            print()
            import traceback
            traceback.print_exc()
    
    elif question_type == "image-stream":
        # 同步流式输出测试（不需要异步，直接实时输出）
        print("-" * 80)
        print("步骤 4: 同步流式输出测试（带图片输入，实时输出）")
        print("-" * 80)
        print("正在调用 Gemini API（同步流式方式，实时输出）...")
        print()
        
        try:
            import time
            import sys
            
            # 初始化 Client（与 image 分支相同）
            client = genai.Client(api_key=api_key, http_options={'api_version': 'v1alpha', 'base_url': ZENMUX_BASE_URL})
            
            start_time = time.time()
            image_path = backend_dir / "utils" / "test_pic" / "test_image.png"
            mime_type = "image/png"
            
            if not image_path.exists():
                print(f"❌ 图片文件不存在: {image_path}")
                return
            
            with open(image_path, "rb") as f:
                image_bytes = f.read()
            
            print(f"✓ 图片已加载: {image_path.name} ({mime_type}, {len(image_bytes)} 字节)")
            
            # 构建用户 prompt
            question = "设P是平行四边形 ABCD 内部的一点，且∠PBA=∠PDA求证:∠PAB=∠PCB"
            title = "平行四边形"
            question_content = f"题目：{question}\n标题：{title}"
            user_prompt = user_prompt_template.replace("__PRE_OUT__", question_content)
            
            # 构建消息内容
            contents = [
                types.Content(
                    role="user",
                    parts=[
                        {"inline_data": {"mime_type": "image/jpeg", "data": image_bytes}},
                        {"text": user_prompt}
                        # types.Part.from_text(text=user_prompt),
                        # types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                    ],
                ),
            ]
            
            # 创建配置
            generate_content_config = types.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=16384,
                http_options=types.HttpOptions(timeout=180000),
            )
            
            print("开始流式输出（实时显示）:")
            print("-" * 80)
            
            # 同步流式调用，实时输出
            html = ""
            chunk_count = 0
            for chunk in client.models.generate_content_stream(
                model=model_name,
                contents=contents,
                config=generate_content_config,
            ):
                if hasattr(chunk, 'text') and chunk.text:
                    chunk_text = chunk.text
                    html += chunk_text
                    chunk_count += 1
                    # 实时输出到控制台
                    print(chunk_text, end='', flush=True)
            
            print()
            print("-" * 80)
            elapsed = time.time() - start_time
            print(f"\n✓ 流式输出完成！")
            print(f"  总耗时: {elapsed:.2f} 秒")
            print(f"  接收块数: {chunk_count}")
            print(f"  生成的 HTML 长度: {len(html)} 字符")
            print()
            
            # 清理生成的 HTML
            def clean_generated_html(html: str) -> str:
                """去除生成的 HTML 前后的 ```/```html 包裹"""
                if html is not None:
                    html = html.lstrip()
                    if html.startswith("```html"):
                        html = html[7:].lstrip()
                    elif html.startswith("```"):
                        html = html[3:].lstrip()
                    html = html.rstrip()
                    if html.endswith("```"):
                        html = html[:-3].rstrip()
                return html
            
            teaching_html = clean_generated_html(html)
            
            # 保存生成的 HTML 到文件
            output_file = backend_dir / "test_gemini_output_stream.html"
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(teaching_html)
            print(f"✓ 生成的 HTML 已保存到: {output_file}")
            print()
            
            print("=" * 80)
            print("同步流式输出测试完成！")
            print("=" * 80)
            print()
            print(f"提示：可以在浏览器中打开 {output_file} 查看生成的 HTML 效果")
            
        except Exception as e:
            elapsed = time.time() - start_time if 'start_time' in locals() else 0
            print()
            print("=" * 80)
            print("❌ 同步流式输出测试失败")
            print("=" * 80)
            print(f"错误信息: {e}")
            print(f"已等待 {elapsed:.2f} 秒")
            print()
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    import sys
    
    # 支持命令行参数选择题目类型
    question_type = "default"
    if len(sys.argv) > 1:
        question_type = sys.argv[1]
        if question_type not in ["default", "simple", "complex", "image", "image-stream"]:
            print(f"⚠ 警告：未知的题目类型 '{question_type}'，使用默认类型 'default'")
            question_type = "default"
    
    print(f"使用题目类型: {question_type}")
    print("可选类型: default（乒乓球比赛）, simple（简单加减法）, complex（复杂应用题）, image（图片输入异步测试）, image-stream（图片输入同步流式测试）")
    print()
    
    # 运行异步测试
    asyncio.run(test_gemini_programmer(question_type))


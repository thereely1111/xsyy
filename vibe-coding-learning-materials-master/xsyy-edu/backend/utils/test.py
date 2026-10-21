# To run this code you need to install the following dependencies:
# pip install google-genai

import base64
import os
from pathlib import Path
from google import genai
from google.genai import types
from dotenv import load_dotenv


# 加载 .env 文件
backend_dir = Path(__file__).resolve().parent
env_path = backend_dir / ".env"
load_dotenv(dotenv_path=env_path)
ZENMUX_API_KEY = os.getenv("ZENMUX_API_KEY") or os.getenv("GEMINI_API_KEY")
ZENMUX_BASE_URL = os.getenv("ZENMUX_BASE_URL", "https://zenmux.ai/api/vertex-ai")
ZENMUX_HTML_MODEL = os.getenv("ZENMUX_HTML_MODEL", "google/gemini-3.1-pro-preview")

text = """


**角色定义：**
你是一位精通前端开发（HTML5, Tailwind CSS, JavaScript）、用户体验设计和儿童心理学的教育类App工程师。

**任务目标：**
创建一个**单文件 HTML 响应式交互式教学应用**，详细讲述这一类问题的解题原理：**[学校进行乒乓球选拔赛，每个参赛选手都要和其他所有选手各赛一场，一共有10位参赛选手，问一共要进行多少场比赛?]**。
要求：
    *   如果有多个解题方法，选择最容易展示的那种 。
    *   每个步骤都要展示得非常详细，当用户是个什么都不懂的白痴。


**UI 布局与设计规范（必须严格遵守）：**

1.  **整体风格：**
    *   使用 Tailwind CSS 进行样式设计。
    *   背景色为淡灰色（如 `bg-gray-100`），整体界面圆角化（Rounded UI），阴影柔和（Soft Shadows）。
    *   布局采用 **Dashboard 风格**：顶部为控制栏，下方分为左右两栏（移动端垂直堆叠，桌面端左7右3或左2右1比例）。

2.  **顶部控制栏 (Header & Inputs)：**
    *   左侧显示 App 标题和图标。
    *   中间显示题目原文
    *   右侧放置**输入框组**：允许用户自定义参数（例如：头数量、腿数量），并包含一个“重新开始”按钮。
    *   输入框风格：下划线式或简约边框，带有清晰的 Label。

3.  **左侧：可视化演示区 (Visual Canvas)：**
    *   **容器：** 一个大的白色卡片 (`bg-white`, `shadow`, `rounded-xl`)。
    *   **状态栏：** 顶部显示当前统计数据（如：当前画面多少头，已分配多少腿）。
    *   **展示网格：** 使用 Grid 布局展示元素（如使用 Emoji 或 SVG 图标代表动物/物体）。
    *   **动态效果：** 元素出现或变化时需要有简单的 CSS 过渡动画。

4.  **右侧：教学与控制区 (Sidebar)：**
    *   **模块 A：步骤进度条 (Stepper)：** 顶部显示当前步骤（例如 2/4），使用圆点和连接线表示进度。
    *   **模块 B：黑板/老师讲课区 (The Blackboard)：**
        *   这是核心区域。必须设计成**深色背景卡片**（如 `bg-slate-700` 或深蓝灰）。
        *   包含一个“老师讲课”的标题或图标（黄色高亮）。
        *   内容区：用白色文字解释当前步骤的逻辑。
        *   底部：专门的区域显示算式或数据推导过程（等宽字体，类似代码块）。
    *   **模块 C：操作按钮 (Action Button)：**
        *   底部放置一个全宽的大按钮（如蓝色 `bg-blue-600`）。
        *   按钮文字根据状态变化（如：“下一步：计算差额”、“开始演示”）。

**交互逻辑要求：**
1.  使用 **Alpine.js** 或 **原生 JavaScript** 管理状态。
2.  必须包含“分步演示”逻辑：用户点击“下一步”按钮，UI 更新，黑板区的文字和左侧的动画同步变化。
3.  输入参数改变时，自动重置演示。

**输出要求：**
请直接输出包含所有 CSS、JS 的完整 HTML 代码，不要依赖外部图片链接（使用 Emoji 或 base64/SVG）。只输出html代码，不用作其它解释
"""
def generate():
    client = genai.Client(
        api_key=ZENMUX_API_KEY,
        http_options={'api_version': 'v1alpha', 'base_url': ZENMUX_BASE_URL},
    )

    model = ZENMUX_HTML_MODEL
    contents = [
        types.Content(
            role="user",
            parts=[
                types.Part.from_text(text=text),
            ],
        ),
    ]
    tools = [
        types.Tool(googleSearch=types.GoogleSearch(
        )),
    ]
    generate_content_config = types.GenerateContentConfig(
        thinkingConfig={
            "thinkingLevel": "HIGH",
        },
        tools=tools,
    )

    for chunk in client.models.generate_content_stream(
        model=model,
        contents=contents,
        config=generate_content_config,
    ):
        print(chunk.text, end="")

if __name__ == "__main__":
    generate()

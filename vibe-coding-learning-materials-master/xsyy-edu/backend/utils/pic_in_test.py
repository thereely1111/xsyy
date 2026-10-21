from google import genai
from google.genai import types
import os
from pathlib import Path
from dotenv import load_dotenv

# 加载环境变量
backend_dir = Path(__file__).resolve().parent.parent
env_path = backend_dir / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)

# prompt_dir = Path(__file__).resolve().parent
prompt_dir = backend_dir / "prompt"
teaching_system_prompt_path = prompt_dir / "teaching_system_prompt.txt"
with open(teaching_system_prompt_path, "r", encoding="utf-8") as f:
    system_prompt = f.read()

question = "设P是平行四边形 ABCD 内部的一点，且∠PBA=∠PDA求证:∠PAB=∠PCB"
title = "平行四边形"
user_prompt = f"题目：{question}\n标题：{title}"

ZENMUX_API_KEY = os.getenv("ZENMUX_API_KEY") or os.getenv("GEMINI_API_KEY")
ZENMUX_BASE_URL = os.getenv("ZENMUX_BASE_URL", "https://zenmux.ai/api/vertex-ai")
ZENMUX_HTML_MODEL = os.getenv("ZENMUX_HTML_MODEL", "google/gemini-3.1-pro-preview")

print(f"now path: {os.getcwd()}")
client = genai.Client(api_key=ZENMUX_API_KEY, http_options={'api_version': 'v1alpha', 'base_url': ZENMUX_BASE_URL})

# 测试图片输入
image_path = Path("backend/utils/test_pic/test_image.png")  # 替换为你的测试图片路径

# 读取图片文件
with open(image_path, "rb") as f:
    image_data = f.read()

system_prompt = '''判断该数学题中是否包含图片
输出格式：
```json
{
  "has_pic": // Boolean: 是否包含图片
}
```'''
generate_content_config = types.GenerateContentConfig(
    system_instruction = system_prompt
    )
# 构建包含图片的内容
response = client.models.generate_content(
    # model="gemini-flash-latest",
    model=ZENMUX_HTML_MODEL,
    config=generate_content_config,
    contents=[
        {
            "role": "user",
            "parts": [
                {"inline_data": {"mime_type": "image/jpeg", "data": image_data}},
                {"text": user_prompt}
            ]
        }
    ]
)
print(response.text)
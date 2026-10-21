import requests
import json
import os
from dotenv import load_dotenv
from pathlib import Path
# 加载 .env 文件
backend_dir = Path(__file__).resolve().parent.parent
env_path = backend_dir / ".env"
load_dotenv(dotenv_path=env_path)
# 设置你的API密钥
API_KEY = os.getenv("ZENMUX_API_KEY") or os.getenv("GEMINI_API_KEY")
BASE_URL = os.getenv("ZENMUX_BASE_URL", "https://zenmux.ai/api/vertex-ai")
# API端点
# url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={API_KEY}"
url = f"{BASE_URL}/v1beta/models/google/gemini-2.5-flash-image:generateContent?key={API_KEY}"

# 请求头
headers = {
    "Content-Type": "application/json"
}

# 请求数据
data = {
    "contents": [
        {
            "parts": [
                {
                    "text": "Explain how AI works in a few words"
                }
            ]
        }
    ]
}

try:
    # 发送POST请求
    response = requests.post(url, headers=headers, json=data)
    
    # 检查响应状态
    if response.status_code == 200:
        result = response.json()
        # 提取生成的文本
        if "candidates" in result and len(result["candidates"]) > 0:
            text_response = result["candidates"][0]["content"]["parts"][0]["text"]
            print("Gemini回复:")
            print(text_response)
        else:
            print("API响应格式异常:", result)
    else:
        print(f"请求失败，状态码: {response.status_code}")
        print("错误信息:", response.text)
        
except Exception as e:
    print(f"发生错误: {e}")
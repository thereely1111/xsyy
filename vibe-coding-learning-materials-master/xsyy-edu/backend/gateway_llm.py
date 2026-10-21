"""网关 LLM 包装器，兼容 LangChain ChatModel 接口"""
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk
from langchain_core.callbacks import CallbackManagerForLLMRun
from typing import List, Optional, Any, Iterator, AsyncIterator
import aiohttp
import json
import os
from dotenv import load_dotenv

load_dotenv()


class GatewayChatModel(BaseChatModel):
    """网关 ChatModel，支持 llm.ainvoke 调用方式"""
    
    model: str = "google/gemini-3.1-pro-preview"
    api_key: str = ""
    gateway_url: str = "https://ai-gateway.eo-edgefunctions7.com"
    gateway_version: str = "2"
    gateway_key: str = "2c8f1178d7e74a83a6e0ab5fe83c812a"
    gateway_name: str = "test"
    gateway_provider: str = "gemini"
    temperature: float = 0.3
    timeout: int = 180
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.model:
            self.model = os.getenv("ZENMUX_HTML_MODEL") or os.getenv("GEMINI_MODEL_NAME", "google/gemini-3.1-pro-preview")
        if not self.api_key:
            self.api_key = os.getenv("ZENMUX_API_KEY") or os.getenv("GEMINI_API_KEY", "")
        self.gateway_url = os.getenv("ZENMUX_BASE_URL", self.gateway_url)
        if not self.api_key:
            raise ValueError("需要设置 api_key，或在 .env 中配置 ZENMUX_API_KEY / GEMINI_API_KEY")
    
    @property
    def _llm_type(self) -> str:
        return "gateway"
    
    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatGeneration:
        """同步生成（内部调用异步）"""
        import asyncio
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(
            self._agenerate(messages, stop, run_manager, **kwargs)
        )
    
    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatGeneration:
        """异步生成响应"""
        # 转换消息格式
        formatted_messages = []
        system_content = None
        
        for msg in messages:
            if isinstance(msg, SystemMessage):
                system_content = msg.content
            elif isinstance(msg, HumanMessage):
                formatted_messages.append({"content": msg.content})
            elif hasattr(msg, 'content'):
                # 处理其他类型的消息
                formatted_messages.append({"content": msg.content})
        
        # 构建请求体
        body = {
            "model": self.model,
            "messages": formatted_messages,
            "stream": False
        }
        
        if system_content:
            body["system_instruction"] = system_content
        
        # 构建 headers
        headers = {
            "X-Goog-Api-Key": self.api_key,
            "OE-Gateway-Version": self.gateway_version,
            "OE-Key": self.gateway_key,
            "OE-Gateway-Name": self.gateway_name,
            "OE-AI-Provider": self.gateway_provider,
            "Content-Type": "application/json"
        }
        
        # 发送请求
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(self.gateway_url, headers=headers, json=body) as response:
                    response_text = await response.text()
                    
                    if response.status != 200:
                        # 尝试解析错误响应
                        try:
                            error_json = json.loads(response_text)
                            error_msg = error_json.get("msg", error_json.get("message", response_text))
                        except:
                            error_msg = response_text
                        raise Exception(f"网关 API 返回错误 {response.status}: {error_msg}")
                    
                    # 解析成功响应
                    try:
                        result = json.loads(response_text)
                    except json.JSONDecodeError:
                        # 如果不是 JSON，直接返回文本
                        return ChatGeneration(
                            message=AIMessage(content=response_text)
                        )
                    
                    # 解析响应（根据实际 API 响应格式调整）
                    content = ""
                    if "data" in result:
                        if "choices" in result["data"] and len(result["data"]["choices"]) > 0:
                            content = result["data"]["choices"][0].get("message", {}).get("content", "")
                        elif "content" in result["data"]:
                            content = result["data"]["content"]
                    elif "choices" in result and len(result["choices"]) > 0:
                        content = result["choices"][0].get("message", {}).get("content", "")
                    elif "content" in result:
                        content = result["content"]
                    elif "message" in result:
                        content = result["message"]
                    elif "text" in result:
                        content = result["text"]
                    else:
                        # 如果格式不匹配，返回整个响应用于调试
                        print(f"警告: 无法解析响应格式，返回完整响应:")
                        print(json.dumps(result, ensure_ascii=False, indent=2))
                        content = json.dumps(result, ensure_ascii=False, indent=2)
                    
                    if not content:
                        # 如果内容为空，返回完整响应用于调试
                        content = json.dumps(result, ensure_ascii=False, indent=2)
                    
                    return ChatGeneration(
                        message=AIMessage(content=content)
                    )
        except Exception as e:
            raise Exception(f"网关 API 调用失败: {str(e)}")


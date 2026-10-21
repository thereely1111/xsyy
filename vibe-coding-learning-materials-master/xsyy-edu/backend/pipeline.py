from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Callable, List

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from openai import OpenAI

from kimi_config import (
    get_active_model,
    get_api_key,
    get_base_url,
    get_active_params,
    get_backup_api_key,
    get_backup_base_url,
    get_backup_model,
    is_backup_configured,
    get_params_for_model,
    is_timeout_error,
    get_image_api_key,
    get_image_base_url,
    record_success,
    record_failure,
)

# 导入预览图生成相关函数
from generate_preview_images import (
    build_image_prompt,
    env_int,
    generate_image_for_task,
    preview_backup_extra_seconds,
    update_metadata,
)

# 图片压缩（视觉模型输入前控制体积）
from utils.image_compress import compress_image_for_vision

# 导入题目分析相关函数和常量
from classify_storage_tasks import (
    parse_analysis_result,
    analyze_question,
)

# 知识点标签注入（两步分层标签识别模型：知识域+年级 → 知识点标签）
from knowledge_tag_injector import inject_knowledge_tags, inject_knowledge_tags_full

# 导入数据库相关模块
from database import SessionLocal, Teaching

# 网站日志：记录动画生成过程中的轻微异常 / 小问题（best-effort）
from website_log import record_website_log
from website_log import EVENT_PREVIEW_GENERATION_FAILED, STAGE_PREVIEW_GENERATION

# 加载 .env 文件
backend_dir = Path(__file__).resolve().parent
env_path = backend_dir / ".env"
load_dotenv(dotenv_path=env_path)


class TemplateDynamicPartsError(RuntimeError):
    """模板动态片段生成失败时携带诊断信息。"""

    def __init__(self, message: str, debug_info: Optional[Dict] = None):
        super().__init__(message)
        self.debug_info = debug_info or {}


def log(message: str, level: str = "INFO"):
    """实时日志输出函数，带时间戳"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_message = f"[{timestamp}] [{level}] {message}"
    try:
        print(log_message, flush=True)
    except UnicodeEncodeError:
        buffer = getattr(sys.stdout, "buffer", None)
        if buffer is not None:
            try:
                buffer.write((log_message + "\n").encode("utf-8", errors="replace"))
                buffer.flush()
                return
            except Exception:
                pass
        safe_message = log_message.encode("ascii", errors="replace").decode("ascii")
        try:
            print(safe_message, flush=True)
        except Exception:
            pass
    sys.stdout.flush()


def log_detail(title: str, data: dict, max_length: int = 500):
    """输出详细的日志信息，包括输入、输出、prompt 等
    
    Args:
        title: 日志标题
        data: 包含各种信息的字典，如 {"input": "...", "prompt": "...", "output": "..."}
        max_length: 每个字段的最大显示长度
    """
    log("=" * 80, "DETAIL")
    log(f"📋 {title}", "DETAIL")
    log("-" * 80, "DETAIL")
    
    for key, value in data.items():
        if value is None:
            continue
        
        # 格式化值
        if isinstance(value, str):
            if len(value) > max_length:
                display_value = value[:max_length] + f"... (共 {len(value)} 字符)"
            else:
                display_value = value
        elif isinstance(value, (dict, list)):
            display_value = json.dumps(value, ensure_ascii=False, indent=2)
            if len(display_value) > max_length:
                display_value = display_value[:max_length] + f"... (共 {len(display_value)} 字符)"
        else:
            display_value = str(value)
        
        # 输出格式：key: value（多行时适当缩进）
        lines = display_value.split('\n')
        if len(lines) == 1:
            log(f"  {key}: {display_value}", "DETAIL")
        else:
            log(f"  {key}:", "DETAIL")
            for line in lines:
                log(f"    {line}", "DETAIL")
    
    log("=" * 80, "DETAIL")


@dataclass
class PipelineResult:
    """流水线执行结果

    当前仍保留 video_url / preview_image 字段，方便未来接入真实渲染服务。
    实际的「HTML 教学应用」内容会放在 metadata["teaching_html"] 里。
    如果执行失败（例如输入不是数学题），metadata["error"] 会包含错误消息。
    """

    video_url: str
    preview_image: str
    metadata: Dict


# ---------------------------------------------------------------------------
# 解题预检（识题阶段轻量校验）：确认是数学题后、进入标签识别/动画生成前，
# 让模型对题目做一次「能否得到正确解答」的快速判断，题目矛盾/无解/无正确答案
# 时提前 failed，避免浪费算力生成一份错误动画。
# 开关：环境变量 ENABLE_SOLVABILITY_CHECK（默认 "true"；置 0/false/off/no 关闭）。
# 调用失败一律 fail-open：放行继续生成，不把基础设施故障当成题目错误。
# ---------------------------------------------------------------------------
SOLVABILITY_SYSTEM_PROMPT = """你是一名严谨的初中数学审题员。用户会给你一道数学题（纯文字，或一张题目图片）。
请做【轻量】解题预检：
1. 通读题目，判断已知条件是否自洽、是否存在正确（唯一或明确）答案；
2. 快速推导关键结论（无需完整解题过程）；
3. 重点排查常见硬伤：
   - 条件矛盾：如给出的多个点不共同一曲线/同一直线（例：A(2,4) 与 B(-1,-2) 代入 y=k/x 得 k=8 与 k=2，两交点不共同一反比例函数）；
   - 无解：方程/不等式在实数范围内无解，或几何作图不可能；
   - 无正确唯一答案：题干缺失关键量、多解且各解都成立导致「没有标准答案」、单位/数据明显不合理。
只输出一个 JSON 对象（不要任何解释性文字、不要 Markdown 代码块）：
{
  "solvable": true,
  "reason": "",
  "brief": ""
}
字段说明：
- solvable：bool。仅当确有硬伤（矛盾/无解/无正确唯一答案）才置 false；普通难题、多解但每解都成立、或只是较开放，都置 true。
- reason：若 solvable=false，用一句中文说明题目问题（说清矛盾点，例如「A(2,4)与B(-1,-2)代入 y=k/x 分别得 k=8 与 k=2，两交点不共同一反比例函数，条件矛盾」）；solvable=true 时填空字符串。
- brief：若 solvable=true，用一句中文给出本题关键结论/答案要点（用于日志与回执）；solvable=false 时填空字符串。"""


def _parse_solvability_verdict(text: str) -> dict:
    """从模型输出中解析 {solvable, reason, brief}。

    解析失败（空输出/无 JSON/JSON 损坏）一律返回 solvable=True，避免把正常题误杀。
    """
    if not text:
        return {"solvable": True, "reason": "", "brief": ""}
    s = text.strip()
    m = re.search(r"\{.*\}", s, re.DOTALL)
    if not m:
        return {"solvable": True, "reason": "", "brief": ""}
    try:
        obj = json.loads(m.group(0))
    except Exception:
        return {"solvable": True, "reason": "", "brief": ""}
    solvable = obj.get("solvable", True)
    if isinstance(solvable, str):
        solvable = solvable.strip().lower() not in ("false", "0", "否", "no")
    reason = str(obj.get("reason", "") or "").strip()
    brief = str(obj.get("brief", "") or "").strip()
    if not solvable and not reason:
        reason = "题目存在矛盾或无法得到正确解答，请检查题干条件。"
    return {"solvable": bool(solvable), "reason": reason, "brief": brief}


class LangChainPipeline:
    """负责 orchestrate 教学流水线，调用 Kimi 生成教学 HTML。"""

    def __init__(self) -> None:
        """延迟初始化：不在启动时检查环境变量，而是在实际调用时才初始化 LLM。"""
        self._kimi_client = None  # Kimi Client (OpenAI SDK)
        self._kimi_model = get_active_model()
        self._gptsapi_client = None  # GPTsAPI (预览图)
        self._backup_client = None  # 备用模型 Client（默认模型超时/网络异常时切换）
        # 测试模式
        self.test_mode = os.getenv("TEST_MODE", "").lower() in ("1", "true", "yes") or \
                        os.getenv("USE_MOCK", "").lower() in ("1", "true", "yes")
        # 低内存模式：如果设置了 LOW_MEMORY=1，则使用更轻量的模型和配置
        self.low_memory_mode = os.getenv("LOW_MEMORY", "").lower() in ("1", "true", "yes")
        
        # 加载 prompt 模板文件
        backend_dir = Path(__file__).resolve().parent
        prompt_dir = backend_dir / "prompt"
        self.classification_system_prompt_path = prompt_dir / "classification_system_prompt.txt"
        self.classification_user_prompt_path = prompt_dir / "classification_user_prompt.txt"
        self.classi_pic_system_prompt_path = prompt_dir / "classi_pic_system_prompt.txt"
        self.teaching_html_template_path = prompt_dir / "teaching_template.html"
        self.teaching_dynamic_system_prompt_path = prompt_dir / "teaching_dynamic_system_prompt.txt"
        self.teaching_dynamic_user_prompt_path = prompt_dir / "teaching_dynamic_user_prompt.txt"


    def _get_kimi_client(self) -> OpenAI:
        """获取 Kimi Client (OpenAI 兼容接口, 延迟初始化)。"""
        if self._kimi_client is None:
            api_key = get_api_key()
            if not api_key:
                raise RuntimeError("缺少 KIMI_API_KEY, 请在 .env 中配置")
            self._kimi_client = OpenAI(
                api_key=api_key,
                base_url=get_base_url(),
                timeout=600.0,
            )
            log(f"Kimi Client 初始化完成, 模型: {self._kimi_model}, base_url: {get_base_url()}")
        return self._kimi_client

    def _get_backup_client(self) -> OpenAI:
        """获取备用模型 Client（默认模型超时/网络异常时切换，延迟初始化）。"""
        if self._backup_client is None:
            api_key = get_backup_api_key()
            if not api_key:
                raise RuntimeError("备用模型未配置 BACKUP_MODEL_API_KEY，请在 .env 中配置")
            self._backup_client = OpenAI(
                api_key=api_key,
                base_url=get_backup_base_url(),
                timeout=600.0,
            )
            log(f"备用模型 Client 初始化完成, 模型: {get_backup_model()}, base_url: {get_backup_base_url()}")
        return self._backup_client

    def _get_gptsapi_client(self) -> OpenAI:
        """获取 GPTsAPI Client (仅预览图, 延迟初始化)。"""
        if self._gptsapi_client is None:
            self._gptsapi_client = OpenAI(
                api_key=get_image_api_key() or "placeholder",
                base_url=get_image_base_url(),
                timeout=120.0,
            )
        return self._gptsapi_client

    def _get_llm_analyzer(self) -> ChatOpenAI:
        """获取题目分析 LLM 实例 (兼容旧接口, 底层已切换为 Kimi)。"""
        if self._kimi_client is None:
            self._get_kimi_client()
        # 返回 ChatOpenAI 包装以保持调用方兼容
        params = get_active_params()
        extra = params.pop("extra_body", None)
        return ChatOpenAI(
            model=self._kimi_model,
            api_key=get_api_key(),
            base_url=get_base_url(),
            temperature=0.3,
            max_retries=1,
            timeout=120,
            extra_body=extra,
            model_kwargs=params if params else {},
        )

    def _is_image_file(self, file_path: str) -> bool:
        """检测文件是否为图片格式。"""
        if not file_path:
            return False
        image_extensions = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
        return Path(file_path).suffix.lower() in image_extensions

    def _get_image_mime_type(self, file_path: Path) -> str | None:
        """根据扩展名返回图片 MIME 类型。"""
        suffix = file_path.suffix.lower()
        if suffix in (".jpg", ".jpeg"):
            return "image/jpeg"
        if suffix == ".png":
            return "image/png"
        if suffix == ".gif":
            return "image/gif"
        if suffix == ".bmp":
            return "image/bmp"
        if suffix == ".webp":
            return "image/webp"
        return None

    async def _analyze_image_question(self, image_path: str) -> dict | None:
        """使用 Kimi Vision 对图片题目进行分类，返回与文本分析兼容的结果。"""
        if not image_path:
            return None
        img_path = Path(image_path)
        if not img_path.exists():
            log(f"图片文件不存在: {img_path}", "WARN")
            return None

        mime_type = self._get_image_mime_type(img_path)
        if not mime_type:
            log(f"不支持的图片类型: {img_path.suffix}", "WARN")
            return None

        try:
            with open(img_path, "rb") as f:
                image_data = f.read()
        except Exception as e:
            log(f"读取图片失败: {e}", "WARN")
            return None

        system_prompt = self._load_prompt_template(self.classi_pic_system_prompt_path)
        if not system_prompt:
            raise RuntimeError("缺少图片分类 system prompt（classi_pic_system_prompt.txt），请检查文件是否存在")

        # 输出详细的输入信息
        log_detail(
            "图片分类 - 输入信息",
            {
                "图片路径": str(img_path),
                "图片大小": f"{len(image_data)} 字节",
                "MIME 类型": mime_type,
                "System Prompt": system_prompt,
                "模型": self._kimi_model,
            }
        )

        client = self._get_kimi_client()

        try:
            log("检测到图片输入，使用视觉模型进行分类...", "INFO")

            # 压缩并转 base64 内联传给视觉模型
            # （中转站不支持 files 上传接口，base64 data URL 是网关官方识图示例格式）
            image_data, mime_type = compress_image_for_vision(image_data, mime_type)
            image_b64 = base64.b64encode(image_data).decode("ascii")
            log_detail(
                "图片预处理",
                {
                    "压缩后大小": f"{len(image_data)} 字节",
                    "base64 长度": f"{len(image_b64)} 字符",
                    "最终 MIME": mime_type,
                }
            )

            def _request_classification(cur_client, cur_model: str) -> str:
                output_text = ""
                for _attempt in range(2):
                    resp = cur_client.chat.completions.create(
                        model=cur_model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": [
                                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_b64}"}},
                                {"type": "text", "text": "请分析这张题目截图，输出 JSON。"},
                            ]},
                        ],
                        max_tokens=4096,
                        **get_params_for_model(cur_model),
                    )
                    output_text = resp.choices[0].message.content or ""
                    if output_text.strip():
                        break
                    # gpt-5.5 等 reasoning 模型偶发"只思考不输出"（finish_reason=stop 但 content 为空），自动重试一次
                    log("图片分类模型返回空内容，自动重试一次", "WARN")
                return output_text

            try:
                output_text = _request_classification(client, get_active_model())
            except Exception as exc:
                # 仅"确定超时"（Timeout / ConnectionError / HTTP 524）才切备用，4xx 内容类错误不切
                if not is_backup_configured() or not is_timeout_error(exc):
                    raise
                backup_client = self._get_backup_client()
                log(
                    f"图片分类默认模型超时/网络异常，切换到备用模型 {get_backup_model()} 重试: {exc}",
                    "WARN",
                )
                output_text = _request_classification(backup_client, get_backup_model())
            record_success()
            
            # 输出原始响应
            log_detail(
                "图片分类 - API 原始响应",
                {
                    "原始输出": output_text,
                }
            )
            
            # 尝试解析 JSON（使用更健壮的方法）
            def extract_json_from_text(text: str) -> str | None:
                """从文本中提取完整的 JSON 对象，使用栈匹配括号确保完整性"""
                # 方法1：先尝试提取 markdown 代码块中的 JSON
                # 找到代码块开始位置
                code_block_start = text.find('```')
                if code_block_start != -1:
                    # 找到代码块结束位置
                    code_block_end = text.find('```', code_block_start + 3)
                    if code_block_end != -1:
                        # 提取代码块内容
                        code_content = text[code_block_start + 3:code_block_end].strip()
                        # 移除可能的 "json" 标记
                        if code_content.startswith('json'):
                            code_content = code_content[4:].strip()
                        # 在代码块内容中查找 JSON 对象
                        json_start = code_content.find('{')
                        if json_start != -1:
                            # 使用栈匹配括号找到完整的 JSON
                            brace_count = 0
                            in_string = False
                            escape_next = False
                            
                            for i in range(json_start, len(code_content)):
                                char = code_content[i]
                                
                                if escape_next:
                                    escape_next = False
                                    continue
                                
                                if char == '\\':
                                    escape_next = True
                                    continue
                                
                                if char == '"' and not escape_next:
                                    in_string = not in_string
                                    continue
                                
                                if not in_string:
                                    if char == '{':
                                        brace_count += 1
                                    elif char == '}':
                                        brace_count -= 1
                                        if brace_count == 0:
                                            return code_content[json_start:i + 1]
                
                # 方法2：从第一个 { 开始，使用栈匹配括号找到完整的 JSON
                start_idx = text.find('{')
                if start_idx != -1:
                    brace_count = 0
                    in_string = False
                    escape_next = False
                    end_idx = start_idx
                    
                    for i in range(start_idx, len(text)):
                        char = text[i]
                        
                        if escape_next:
                            escape_next = False
                            continue
                        
                        if char == '\\':
                            escape_next = True
                            continue
                        
                        if char == '"' and not escape_next:
                            in_string = not in_string
                            continue
                        
                        if not in_string:
                            if char == '{':
                                brace_count += 1
                            elif char == '}':
                                brace_count -= 1
                                if brace_count == 0:
                                    end_idx = i
                                    return text[start_idx:end_idx + 1]
                
                # 方法3：如果都失败，尝试使用整个输出
                return text.strip()
            
            json_str = extract_json_from_text(output_text)
            if not json_str:
                raise ValueError("无法从输出中提取 JSON")
            
            try:
                # 修复 LaTeX 反斜杠未转义（\frac, \sqrt 等）
                # \n（JSON 换行）与 \u（JSON Unicode）需原样保留
                json_str = re.sub(r'(?<!\\)\\(?![nu])([a-zA-Z])', r'\\\\\1', json_str)
                result = json.loads(json_str)
            except json.JSONDecodeError as e:
                # 如果直接解析失败，尝试使用 classify_storage_tasks 中的解析函数作为备选
                log(f"直接 JSON 解析失败: {e}，尝试使用备选解析方法...", "WARN")
                parsed_result = parse_analysis_result(output_text)
                if parsed_result:
                    # 转换为图片分类需要的格式
                    result = {
                        "is_math_problem": parsed_result.get("is_math_problem", True),
                        "question": parsed_result.get("question", ""),
                        "title": parsed_result.get("title", ""),
                        "reasoning": parsed_result.get("reasoning", ""),
                        "has_pic": False,  # 图片输入，所以 has_pic 为 False
                    }
                else:
                    raise e

            # 标准化返回结构，兼容后续流程
            is_math = result.get("is_math_problem", result.get("is_math_question", True))

            analysis_result = {
                "is_math_problem": bool(is_math),
                "title": result.get("title") if is_math else None,
                "reasoning": result.get("reasoning", "") if is_math else None,
                "question": result.get("question", ""),
                "has_pic": result.get("has_pic"),
            }
            
            # 输出解析后的结果
            log_detail(
                "图片分类 - 解析结果",
                {
                    "是否为数学题": str(is_math),
                    "题目": analysis_result.get("question", ""),
                    "标题": analysis_result.get("title", ""),
                    "推理过程": analysis_result.get("reasoning", ""),
                    "包含图片": str(analysis_result.get("has_pic", False)),
                }
            )
            
            return analysis_result
        except Exception as e:
            log(f"图片分类失败: {e}", "ERROR")
            record_failure()
            return None

    async def execute(self, input_path: str, prompt: str, task_dir: Path, user_id: Optional[str] = None, progress_callback: Optional[Callable[[int], None]] = None) -> PipelineResult:
        """执行完整流水线：

        1. 从上传内容 / 文本 prompt 中抽取题目表述；
        2. **第一步（教学设计师）**：使用 Kimi 分析用户输入，提取核心数学题，策划教学步骤；
        3. **第二步（程序员）**：使用 Kimi 根据教学设计师的输出生成 HTML 教学应用；
        4. 返回 metadata，前端可直接渲染该 HTML。
        """

        user_input = await self._build_question_text(input_path, prompt)
        has_pic = False  # 默认无图片，用于后续教学 HTML 生成是否附带图片输入
        title = ""
        tags = None
        preview_image = ""
        
        log("=" * 80, "PIPELINE")
        log("🚀 开始执行流水线", "PIPELINE")
        log("=" * 80, "PIPELINE")
        
        # 输出流水线启动信息
        log_detail(
            "流水线启动 - 初始参数",
            {
                "任务目录": str(task_dir),
                "任务ID": task_dir.name,
                "用户输入": user_input,
                "输入文件": input_path if input_path else "无",
                "用户ID": user_id if user_id else "匿名用户",
                "测试模式": "是" if self.test_mode else "否",
            }
        )
        
        # 测试模式：直接返回预设数据，不调用真实 API，也不保存到 storage
        if self.test_mode:
            log("使用测试模式：使用预设回复，跳过 API 调用，不保存到 storage", "TEST")
            # 为了兼容，仍然使用 question_text 作为题目
            plan_json = self._get_mock_plan(user_input)
            teaching_html = self._get_mock_teaching_html(user_input, plan_json)
            question_text = user_input
            title = "测试模式教学"
            tags = None
            preview_image = ""
            log("测试模式：预设数据已生成", "TEST")
        else:
            # 非测试模式：链式调用大模型 API
            log("=" * 60)
            log("开始链式调用：题目分析专家 -> 程序员", "PIPELINE")
            
            # 第一步：题目分析专家（分图片/文本两种路径）分析用户输入，判断是否为数学题、生成标题和分类
            log("-" * 60)
            if progress_callback:
                progress_callback(10)  # 开始分析
            
            if input_path and self._is_image_file(input_path):
                log("[步骤 1/2] 检测到图片输入，使用 Kimi Vision 进行图片分类...", "STEP")
                start_time = datetime.now()
                analysis_result = await self._analyze_image_question(input_path)
                elapsed = (datetime.now() - start_time).total_seconds()
                log(f"[步骤 1/2] 图片分类完成，耗时: {elapsed:.2f} 秒", "STEP")
            else:
                log("[步骤 1/2] 题目分析专家（gpt-5.5）分析文本输入...", "STEP")
                start_time = datetime.now()
                
                # 加载 prompt 模板用于日志输出
                classification_system_prompt = self._load_prompt_template(self.classification_system_prompt_path)
                classification_user_prompt_template = self._load_prompt_template(self.classification_user_prompt_path)
                
                # 构建用户 prompt（用于日志显示）
                user_prompt_for_log = ""
                if classification_user_prompt_template:
                    user_prompt_for_log = classification_user_prompt_template.replace("__USER_INPUT__", user_input)
                else:
                    user_prompt_for_log = user_input
                
                # 输出详细的输入信息
                log_detail(
                    "文本分类 - 输入信息",
                    {
                        "用户输入": user_input,
                        "System Prompt": classification_system_prompt if classification_system_prompt else "使用默认",
                        "User Prompt": user_prompt_for_log,
                        "模型": self._kimi_model,
                    }
                )
                
                llm_analyzer = self._get_llm_analyzer()
                analysis_result = await analyze_question(user_input, llm_analyzer)
                
                # 输出分析结果
                if analysis_result:
                    log_detail(
                        "文本分类 - 分析结果",
                        {
                            "是否为数学题": str(analysis_result.get("is_math_problem", True)),
                            "题目": analysis_result.get("question", ""),
                            "标题": analysis_result.get("title", ""),
                            "推理过程": analysis_result.get("reasoning", ""),
                        }
                    )
                
                elapsed = (datetime.now() - start_time).total_seconds()
                log(f"[步骤 1/2] 文本分析完成，耗时: {elapsed:.2f} 秒", "STEP")
            
            elapsed = (datetime.now() - start_time).total_seconds()
            log(f"[步骤 1/2] 完成，耗时: {elapsed:.2f} 秒", "STEP")
            
            if progress_callback:
                progress_callback(20)  # 分析完成
            
            # 判断是否为数学题
            if not analysis_result:
                # 分类模型输出异常时保留原题面，避免有效数学题因格式问题被直接拒绝。
                log("题目分析结果无法解析，回退使用原始输入继续处理", "WARN")
                # 兜底标题：从题面提取连续中文片段（去数字/符号），优于无信息量的泛称"数学题"
                _hint = re.sub(r"[0-9A-Za-z=+\-*/<>()（）.。,，;；:：'\"%√°_【】\s]", "", user_input)
                analysis_result = {
                    "is_math_problem": True,
                    "question": user_input,
                    "title": _hint.strip()[:10] if _hint.strip() else "数学题",
                    "reasoning": "分类结果不可解析，按原题面继续处理",
                }
            
            is_math_problem = analysis_result.get("is_math_problem", True)
            if not is_math_problem:
                error_msg = "抱歉，您输入的内容不是初中数学题，请提供一道初中数学题。"
                log(f"检测到输入不是数学题", "WARN")
                # 返回错误结果，不继续后续步骤
                metadata: Dict = {
                    "question": user_input,
                    "plan": {},
                    "teaching_html": "",
                    "error": error_msg,
                    "is_math_problem": False,
                }
                return PipelineResult(
                    video_url="",
                    preview_image="",
                    metadata=metadata,
                )
            
            # 提取分析结果
            # 优先使用分类模型提取的题目，如果不存在或为空则回退到用户输入
            _err_marker = "【纠错要求】"
            extracted_question = analysis_result.get("question", "").strip()
            if extracted_question:
                question_text = extracted_question
                log(f"使用分类模型提取的题目: {extracted_question[:100]}..." if len(extracted_question) > 100 else f"使用分类模型提取的题目: {extracted_question}")
            else:
                question_text = user_input
                log(f"分类模型未提取到题目，使用原始用户输入: {user_input[:100]}..." if len(user_input) > 100 else f"分类模型未提取到题目，使用原始用户输入: {user_input}")

            # 实测：分类模型可能把【纠错要求】整段也提取进 question 字段（视为题面的一部分）。
            # 必须主动剥离，确保 question_text 是干净题面（用于知识点标签/向量/metadata/页面题目区）。
            if _err_marker in question_text:
                question_text = question_text.split(_err_marker, 1)[0].strip()
                log("分类模型提取的题目包含纠错要求段，已剥离为干净题面", "INFO")

            # 管理员"重新生成动画"链路：从输入中提取纠错要求（【纠错要求】标记段），
            # 绕过分类模型的题目提取，仅注入动画/步骤生成（error_feedback 参数），
            # question_text 保持干净题面，用于知识点标签/向量/metadata/页面题目区。
            error_feedback = ""
            if _err_marker in user_input:
                _fb_parts = user_input.split(_err_marker, 1)
                if len(_fb_parts) == 2 and _fb_parts[1].strip():
                    error_feedback = _fb_parts[1].strip()
                    log(f"检测到纠错要求，将仅注入动画动态片段生成（{len(error_feedback)} 字符）: {error_feedback[:80]}...", "INFO")

            # 解题预检（识题阶段轻量校验）：确认是数学题后、进入标签识别/动画生成前，
            # 简单分析题目是否可解；矛盾/无解/无正确答案则提前 failed，避免浪费生成资源。
            if not error_feedback:  # 纠错重生成模式：题目已验证过，跳过预检
                if progress_callback:
                    progress_callback(25)
                _solvable_img = input_path if (input_path and self._is_image_file(input_path)) else ""
                _solv = await self._check_problem_solvable(question_text, _solvable_img)
                if not _solv.get("solvable"):
                    _reason = _solv.get("reason") or "题目存在问题，无法得到正确解答。"
                    log(f"解题预检未通过：{_reason}", "WARN")
                    metadata: Dict = {
                        "question": question_text,
                        "plan": {},
                        "teaching_html": "",
                        "error": _reason,
                        "error_stage": "solvability",
                        "is_math_problem": True,
                    }
                    return PipelineResult(
                        video_url="",
                        preview_image="",
                        metadata=metadata,
                    )

            title = analysis_result.get("title", "")
            reasoning = analysis_result.get("reasoning", "")
            has_pic = bool(analysis_result.get("has_pic")) and input_path and self._is_image_file(input_path)

            log(f"分析结果: 题目={question_text[:50]}..., 标题={title}")

            # 知识点标签：主链路按 TAG_RECOGNITION_ENGINE 分发识别（P0，方案 2026-09-03）：
            #   agent | dual → tag_agent 智能体优先（识别预算内），primary 未命中/异常 → 降级 legacy
            #   legacy       → 既有两步分层标签识别（知识域+年级 → 知识点标签 → 反查章/单元）
            # 结构：knowledge_tags = 主标签组 {version, grade, main_tag, sub_tags}；
            #       second_tag    = 第二标签组（多知识点组合，结构同主组，可空）；
            #       同时产出教学画像 content_profile（P0 起落 metadata/content_profile.json）。
            knowledge_tags = None
            second_tag = None
            content_profile = None
            recognition_meta = {}
            needs_tag_selection = False
            try:
                knowledge_tags, second_tag, recognition_meta, content_profile = \
                    await self._recognize_knowledge_tags_with_engine(
                        question_text, title=title, task_id=task_dir.name, user_id=user_id,
                        has_image=bool(
                            (has_pic and input_path and self._is_image_file(input_path))
                            or bool(_find_task_dir_image(task_dir))
                        ),
                    )
            except Exception as kt_err:
                log(f"知识点标签识别失败，需手动选择: {kt_err}", "WARN")
                record_website_log(
                    level="WARN",
                    category="animation_generation",
                    message=f"知识点标签识别失败: {kt_err}",
                    user_id=user_id,
                    task_id=task_dir.name,
                )
                knowledge_tags = None
                second_tag = None
                content_profile = None

            # DB 正式框架对账：拦截框架外标签（智能体种子库漂移 / 引擎异常产出）
            knowledge_tags, second_tag, _tags_dropped = self._drop_tags_not_in_db_framework(
                knowledge_tags, second_tag,
            )

            if knowledge_tags and knowledge_tags.get("main_tag"):
                if not knowledge_tags.get("version") or not knowledge_tags.get("grade"):
                    needs_tag_selection = True
                    log(f"知识点标签不完整（知识域或年级缺失），需手动选择: 知识域={knowledge_tags.get('version')}, 年级={knowledge_tags.get('grade')}", "WARN")
                else:
                    log(
                        f"知识点标签: 知识域={knowledge_tags['version']}, 年级={knowledge_tags['grade']}, "
                        f"章/单元={knowledge_tags['main_tag']}, 知识点标签={knowledge_tags.get('sub_tags', [])}"
                        + (f" | 第二标签: 知识域={second_tag['version']}, 章/单元={second_tag['main_tag']}" if second_tag else "")
                    )
            else:
                needs_tag_selection = True
                log("知识点标签未能识别，需手动选择", "WARN")

            # 提前创建 task_dir 和构建基础 metadata（用于并行任务）
            try:
                task_dir.mkdir(parents=True, exist_ok=True)
                log(f"提前创建任务目录: {task_dir}")
            except Exception as e:
                log(f"创建任务目录失败: {e}", "WARN")
            
            # 构建基础 metadata（用于预览图生成）
            base_metadata = {
                "question": question_text,
                "title": title,
                "plan": {"steps": []},  # 预览图生成只需要 question，plan 可以为空
                "is_math_problem": True,
                "has_pic": has_pic,
            }
            if knowledge_tags:
                base_metadata["knowledge_tags"] = knowledge_tags
                base_metadata["second_tag"] = second_tag
                base_metadata["needs_tag_selection"] = needs_tag_selection
            
            # 第二步：先生成预览图，再生成 HTML
            log("-" * 60)
            log("[步骤 2/2] 执行：先生成预览图，再生成 HTML...", "STEP")
            start_time = datetime.now()
            if progress_callback:
                progress_callback(30)  # 开始阶段二

            # T2（xsyy-3 阶段二，2026-09-14）：几何/图形题的 ③-B 直接以原题图为依据。
            # 画像判定含插图（figure_info.has_figure 或 display_class=geometry）时，
            # 参考图不再用重绘的 Preview.webp（预览图退居纯封面），避免"看图编题"幻觉。
            # 图片定位：has_pic 不可信（xsyy-3 教训，会漏 70%+ 图片题），
            # 优先上传原图 input_path，否则扫任务目录实际图片文件（排除 Preview*）。
            _cp_fig_e = locals().get("content_profile")
            _fig_img = ""
            if has_pic and input_path and self._is_image_file(input_path):
                _fig_img = input_path
            else:
                _fig_img = _find_task_dir_image(task_dir)
            _use_orig_fig = bool(
                _fig_img
                and _cp_fig_e is not None
                and (
                    (getattr(_cp_fig_e, "figure_info", None) or {}).get("has_figure")
                    or getattr(_cp_fig_e, "display_class", "") == "geometry"
                )
            )

            # 先生成预览图。预览图失败不阻断后续教学动画生成。
            async def generate_preview_task():
                try:
                    await self._generate_preview_image(task_dir, base_metadata)
                    log("预览图生成完成")
                    return True
                except Exception as e:
                    log(f"生成预览图失败: {e}", "WARN")
                    record_website_log(
                        level="WARN",
                        category="animation_generation",
                        message=f"预览图生成失败: {e}",
                        user_id=user_id,
                        task_id=task_dir.name,
                        event=EVENT_PREVIEW_GENERATION_FAILED,
                        stage=STAGE_PREVIEW_GENERATION,
                    )
                    return False

            preview_result = await generate_preview_task()

            # 阶段 2.1：预览图完成后执行 HTML 生成
            preview_reference_path = task_dir / "Preview.webp"
            if _use_orig_fig:
                # T2：几何/图形题——原题图为唯一结构依据，Preview.webp 仅作封面展示
                image_for_generation = input_path or _fig_img
                log("几何/图形题：动画生成改用原题图作为视觉参考（Preview.webp 仅作封面）", "INFO")
            elif preview_result and preview_reference_path.exists():
                image_for_generation = str(preview_reference_path)
                log(f"动画生成优先使用预览图作为视觉参考: {preview_reference_path}")
            else:
                image_for_generation = input_path if has_pic else None
            # P1：画像 dict（ContentProfile.to_dict()），供分层提示词路由与 Lint
            _cp_obj = locals().get("content_profile")
            _cp_dict = _cp_obj.to_dict() if _cp_obj is not None else None

            # P3 复用闸门（方案 §10）：画像产出后、动画生成前判定「同法异数」复用。
            # 开关默认关；开启后仅写「复用建议队列」人工确认（不跳过生成，异常 fail-open）。
            if _cp_dict is not None:
                try:
                    from tag_agent.config import get_reuse_enabled as _reuse_enabled
                    from tag_agent.reuse import match_reuse_before_generation as _match_reuse
                    if _reuse_enabled():
                        _reuse_decision = await _match_reuse(
                            question_text, title, _cp_dict, task_dir.name, user_id,
                        )
                        if _reuse_decision and _reuse_decision.get("mode") == "L1":
                            log(
                                f"[复用] 命中相似题模板 {_reuse_decision.get('template_task_id')} "
                                f"(置信 {float(_reuse_decision.get('confidence') or 0):.2f})，已写入复用建议队列",
                                "INFO",
                            )
                except Exception as _re_err:  # noqa: BLE001
                    log(f"[复用] 闸门异常（已跳过，不影响生成）: {_re_err}", "WARN")
            # P1 修复（2026-09-11）：HTML 打包阶段失败自动重试 1 次。
            # 此前该阶段一次失败即整单 failed（app.py 标 error="教学 HTML 生成失败"），
            # 而此时动画(scene_svg/steps)与封面已生成成功，造成「明明生成成功却弹
            # 生成失败弹窗」。现对【异常/空输出/验证失败】自动重试一次；
            # 命中「截断特征」仍立即终止不重试（沿用既定口径，见下方 _is_truncated_html_failure）。
            async def _html_task_with_retry():
                last_error = ""
                for attempt in (1, 2):
                    try:
                        html_result = await self._generate_teaching_html_from_question(
                            question_text,
                            title,
                            has_pic=has_pic,
                            image_path=image_for_generation,
                            task_dir=task_dir,
                            task_id=task_dir.name,
                            progress_callback=progress_callback,
                            content_profile=_cp_dict,
                        )
                        _html = html_result["html"] if isinstance(html_result, dict) else html_result
                        if _html and _html.strip():
                            _valid, _reason = self._is_valid_teaching_html(_html)
                            if _valid:
                                return html_result
                            # 截断即失败：不重试，立即中断（与主流程口径一致）
                            if self._is_truncated_html_failure(_reason, _html):
                                raise RuntimeError(f"教学 HTML 输出被截断，任务终止：{_reason}")
                            last_error = f"教学 HTML 验证失败: {_reason}"
                            log(f"第 {attempt} 次 HTML 生成验证失败：{last_error}", "WARN")
                        else:
                            last_error = "教学 HTML 为空"
                            log(f"第 {attempt} 次 HTML 生成结果为空", "WARN")
                    except RuntimeError:
                        # 截断终止等主动 RuntimeError：原样抛出，不重试
                        raise
                    except Exception as _e:
                        # 内部抛出的截断类错误同样不重试
                        if "截断" in (str(_e) or ""):
                            raise
                        last_error = f"教学 HTML 生成失败: {_e}"
                        log(f"第 {attempt} 次 HTML 生成异常：{_e}", "ERROR")
                    if attempt == 1:
                        log("HTML 打包阶段失败，自动重试 1 次...", "WARN")
                raise RuntimeError(last_error or "教学 HTML 生成失败")

            html_task = _html_task_with_retry()

            # 任务3：生成预览图（必须在 HTML 之后执行）
            async def generate_preview_task():
                try:
                    await self._generate_preview_image(task_dir, base_metadata)
                    log("预览图生成完成")
                    return True
                except Exception as e:
                    log(f"生成预览图失败: {e}", "WARN")
                    return False

            html_failure_reason = None

            # 低内存模式下串行执行任务，避免内存峰值
            if self.low_memory_mode:
                log("低内存模式：串行执行 HTML 生成...")
                try:
                    html_result = await html_task
                    results = [html_result]
                except Exception as e:
                    log(f"生成 HTML 失败: {e}", "ERROR")
                    results = [e]
            else:
                log("预览图完成，开始执行 HTML 生成...")
                results = await asyncio.gather(
                    html_task,
                    return_exceptions=True
                )
            
            # 处理结果
            teaching_html = ""
            teaching_data = None

            if isinstance(results[0], Exception):
                log(f"生成 HTML 失败: {results[0]}", "ERROR")
                teaching_html = ""
                html_failure_reason = f"教学 HTML 生成失败: {results[0]}"
            elif isinstance(results[0], dict):
                teaching_html = results[0]["html"]
                teaching_data = results[0].get("teaching_data")
            else:
                teaching_html = results[0]

            # 在生成预览图前先校验 HTML 完整性
            is_valid, validation_reason = self._is_valid_teaching_html(teaching_html)

            # 你要求"截断即失败并中断任务"：命中截断特征时直接抛错，不再自动补救重试
            if not is_valid and self._is_truncated_html_failure(validation_reason, teaching_html):
                error_msg = f"教学 HTML 输出被截断，任务终止：{validation_reason}"
                log(error_msg, "ERROR")
                raise RuntimeError(error_msg)

            # 阶段 2.2：预览图已在 HTML 之前生成，这里只复用结果，不再重复执行
            if not preview_result:
                log("预览图生成失败，已继续完成 HTML 生成流程", "WARN")

            if progress_callback:
                progress_callback(85)  # 阶段二完成

            elapsed = (datetime.now() - start_time).total_seconds()
            log(f"[步骤 2/2] 任务完成（预览图已前置生成），总耗时: {elapsed:.2f} 秒", "STEP")
            
            # 仅保留题目分析兼容字段，知识标签单独保存为 knowledge_tags
            tags = {"reasoning": reasoning} if reasoning else None
            
            # 为了兼容，仍然生成 plan_json（空结构，因为不再需要教学步骤）
            plan_json = {"steps": []}

            # 仅在真正调用大模型生成且内容有效时，才保存到 storage
            # 如果 teaching_html 为空或无效，不保存任何内容到 storage

            if is_valid:
                log("教学 HTML 验证通过，开始保存到 storage", "SAVE")
                
                # 输出保存前的详细信息
                log_detail(
                    "保存教学内容 - 准备保存",
                    {
                        "任务目录": str(task_dir),
                        "任务ID": task_dir.name,
                        "题目": question_text,
                        "标题": title,
                        "知识域": knowledge_tags.get("version", "") if knowledge_tags else "",
                        "年级": knowledge_tags.get("grade", "") if knowledge_tags else "",
                        "章/单元": knowledge_tags.get("main_tag", "") if knowledge_tags else "",
                        "知识点标签": json.dumps(knowledge_tags.get("sub_tags", []), ensure_ascii=False) if knowledge_tags else "[]",
                        "HTML 长度": f"{len(teaching_html)} 字符",
                        "输入文件": input_path if input_path else "无",
                        "用户ID": user_id if user_id else "匿名用户",
                        "包含图片": str(has_pic),
                    }
                )
                
                if progress_callback:
                    progress_callback(90)  # 开始保存
                
                await self._save_teaching_content(
                    task_dir=task_dir,
                    question=question_text,
                    prompt=prompt,
                    plan=plan_json,
                    teaching_html=teaching_html,
                    input_file=input_path,
                    analysis_result=analysis_result,
                    tags=tags,
                    knowledge_tags=knowledge_tags,
                    second_tag=second_tag,
                    needs_tag_selection=needs_tag_selection,
                    user_id=user_id,
                    progress_callback=progress_callback,
                    teaching_data=teaching_data,
                )
                log("教学内容已成功保存", "SAVE")

                # 将知识点标签写入 metadata.json
                if knowledge_tags:
                    try:
                        update_metadata(task_dir, {
                            "knowledge_tags": knowledge_tags,
                            "second_tag": second_tag,
                            "needs_tag_selection": needs_tag_selection,
                            "knowledge_tags_updated_at": datetime.utcnow().isoformat() + "Z",
                        })
                        log("知识点标签已写入 metadata.json", "SAVE")
                    except Exception as kt_save_err:
                        log(f"知识点标签写入 metadata.json 失败: {kt_save_err}", "WARN")

                # 教学画像 content_profile 落盘（P0，方案 2026-09-03）：
                # 独立 content_profile.json + 合并进 metadata.json。
                # 下游（P1 提示词路由 / P2 动画解答同源 / P6 封面助教）统一读此文件。
                _cp = locals().get("content_profile")
                if _cp is not None:
                    try:
                        _cp_dict = _cp.to_dict()
                        _cp_path = task_dir / "content_profile.json"
                        _tmp_cp = _cp_path.with_name(_cp_path.name + ".tmp")
                        with open(_tmp_cp, "w", encoding="utf-8") as _f:
                            json.dump(_cp_dict, _f, ensure_ascii=False, indent=2)
                        os.replace(_tmp_cp, _cp_path)
                        update_metadata(task_dir, {
                            "content_profile": _cp_dict,
                            "recognition_meta": (locals().get("recognition_meta") or {}),
                        })
                        log(f"教学画像已落盘: {_cp_path} (stage={_cp_dict.get('stage')}, "
                            f"domain={_cp_dict.get('domain')}, style_key={_cp_dict.get('visual_requirements', {}).get('style_key')})", "SAVE")
                    except Exception as cp_err:
                        log(f"教学画像落盘失败（不影响主流程）: {cp_err}", "WARN")

                if progress_callback:
                    progress_callback(100)  # 全部完成
                
                # 检查预览图是否已生成，优先使用当前标准文件名 Preview.webp。
                if (task_dir / "Preview.webp").exists():
                    preview_image = "Preview.webp"
                elif (task_dir / "preview.webp").exists():
                    preview_image = "preview.webp"
                else:
                    preview_image = ""
            else:
                log("❌ 教学 HTML 验证失败，不保存到 storage（包括文件夹和文件）", "WARN")
                html_failure_reason = f"教学 HTML 验证失败: {validation_reason}"
                
                # 输出详细的验证失败原因
                log_detail(
                    "HTML 验证失败 - 失败原因",
                    {
                        "失败原因": validation_reason,
                        "HTML 长度": f"{len(teaching_html)} 字符",
                        "HTML 预览（前 500 字符）": teaching_html[:500] if len(teaching_html) > 500 else teaching_html,
                    }
                )
                
                # embedding 已移除：无向量入库，HTML 失败时无需清理向量数据库

                preview_image = ""

        # 目前没有真实视频渲染，这里保留占位路径，方便以后接入。
        video_url = ""
        if not preview_image:
            preview_image = ""

        metadata: Dict = {
            "question": question_text,
            "plan": plan_json,
            "teaching_html": teaching_html,
            "title": title,
            "tags": tags,
            "is_math_problem": True,
            "has_pic": has_pic,
            "knowledge_tags": locals().get("knowledge_tags"),
            "needs_tag_selection": locals().get("needs_tag_selection", False),
        }
        # 教学画像（P0 起随产物落库，P1/P2 供提示词路由与解答/动画同源消费）
        _cp = locals().get("content_profile")
        if _cp is not None:
            try:
                metadata["content_profile"] = _cp.to_dict()
            except Exception:  # noqa: BLE001
                pass
        _rm = locals().get("recognition_meta")
        if _rm:
            metadata["recognition_meta"] = _rm
        # 将 HTML 生成失败的【具体原因】带出流水线，供 run_pipeline 写入网站日志（生成失败原因可查）。
        # error_stage="html" 用于区分「输入非数学题」（同字段 error 由 run_pipeline 分支1 使用）。
        if html_failure_reason:
            metadata["error"] = html_failure_reason
            metadata["error_stage"] = "html"
        
        # 输出流水线完成总结
        log("=" * 80, "PIPELINE")
        log("✅ 流水线执行完成", "PIPELINE")
        log("=" * 80, "PIPELINE")
        
        # 验证 HTML 并获取失败原因
        is_valid_final, validation_reason_final = self._is_valid_teaching_html(teaching_html)
        save_status = "是" if is_valid_final else f"否（HTML 无效：{validation_reason_final}）"
        
        log_detail(
            "流水线完成 - 最终结果",
            {
                "任务ID": task_dir.name,
                "题目": question_text,
                "标题": title if 'title' in locals() else "无",
                "知识域": knowledge_tags.get("version", "") if knowledge_tags else "",
                "年级": knowledge_tags.get("grade", "") if knowledge_tags else "",
                "章/单元": knowledge_tags.get("main_tag", "") if knowledge_tags else "",
                "HTML 长度": f"{len(teaching_html)} 字符",
                "预览图": preview_image if preview_image else "未生成",
                "包含图片": str(has_pic),
                "是否保存": save_status,
            }
        )

        return PipelineResult(
            video_url=video_url,
            preview_image=preview_image,
            metadata=metadata,
        )

    async def _recognize_knowledge_tags_with_engine(
        self,
        question_text: str,
        *,
        title: str = "",
        task_id: str = "",
        user_id: str = "",
        has_image: bool = False,
    ) -> tuple[Optional[dict], Optional[dict], dict, object]:
        """主链路标签识别：按 TAG_RECOGNITION_ENGINE 灰度分发（P0，方案 2026-09-03 §3.2-4）.

        - legacy：既有两步分层识别（inject_knowledge_tags_full），行为不变；
        - agent / dual：先走 tag_agent 进程内智能体（含识别预算超时护栏），
          识别命中主标签则采用；否则（不可用/失败/低置信/超时/未配置 Key）
          自动降级 legacy，保证主创建链路不因智能体灰度而劣化。

        Returns:
            (knowledge_tags, second_tag, meta, content_profile)
            - knowledge_tags/second_tag 为 xsyy 既有结构（version/grade/main_tag/sub_tags）
            - meta = {"engine": "agent"|"legacy", "action", "confidence", "fallback_from"}
            - content_profile: tag_agent.content_profile.ContentProfile | None
        """
        from tag_agent.config import get_recognition_engine

        engine = get_recognition_engine()

        async def _legacy_full() -> tuple[Optional[dict], Optional[dict]]:
            kt_full = await inject_knowledge_tags_full(question_text, title=title)
            if not kt_full:
                return None, None
            return kt_full.get("primary"), kt_full.get("second")

        knowledge_tags: Optional[dict] = None
        second_tag: Optional[dict] = None
        meta: dict = {"engine": engine}

        if engine in ("agent", "dual"):
            try:
                from tag_agent.client import recognize_question

                budget = float(os.getenv("TAG_RECOGNIZE_PIPELINE_BUDGET_SECONDS", "120"))
                # persist=True：识别结果落库（识别日志 + 提案入审核队列），
                # 与 run_tag_completion / 管理后台「重新识别」同口径。
                mapped = await asyncio.wait_for(
                    recognize_question(question_text, title=title, question_id=task_id,
                                       creator_id=user_id or "system", persist=True),
                    timeout=budget,
                )
                mapped = mapped or {}
                primary = mapped.get("primary") or {}
                _m = mapped.get("_meta") or {}
                # 只采纳官方命中：提案类结果（新建标签/补关键词/链路提案）与低置信
                # 一律降级 legacy（框架锁定，保底官方标签），绝不把提案标签直接写题。
                # （2026-09-11 修复：此前不分 action 一律采纳，导致"新建标签提案"
                #  绕过审核直接上题、审核队列无记录。）
                if primary.get("main_tag") and _m.get("action") == "inject_official" \
                        and not mapped.get("pending_tag_id"):
                    knowledge_tags = primary
                    second_tag = mapped.get("second")
                    meta = {
                        "engine": "agent",
                        "action": _m.get("action", ""),
                        "confidence": _m.get("confidence"),
                    }
                    log(
                        f"[智能体识别] 引擎=agent 官方命中主标签: "
                        f"知识域={knowledge_tags.get('version')} 年级={knowledge_tags.get('grade')} "
                        f"章={knowledge_tags.get('main_tag')} 标签={knowledge_tags.get('sub_tags')}",
                        "INFO",
                    )
                else:
                    log(
                        "智能体识别非官方命中（action="
                        f"{_m.get('action') or '无'}，提案已入审核队列），降级 legacy 找官方标签",
                        "WARN",
                    )
            except Exception as e:  # noqa: BLE001
                # 注意：asyncio.TimeoutError 的 str(e) 为空字符串，必须拼上异常类型名，
                # 否则日志只剩"降级 legacy:"，看不出根因是识别预算超时还是其他异常
                _err_txt = str(e).strip() or "（无错误信息）"
                log(f"智能体识别不可用或超时，降级 legacy: {type(e).__name__}: {_err_txt}", "WARN")
                meta["fallback_reason"] = f"{type(e).__name__}: {_err_txt}"[:200]

        if knowledge_tags is None:
            # legacy 引擎 / agent 降级：回到既有两步分层识别
            try:
                knowledge_tags, second_tag = await _legacy_full()
                if meta.get("engine") == "agent" or engine == "dual":
                    meta = {"engine": "legacy", "fallback_from": "agent" if engine != "legacy" else ""}
            except Exception as e:  # noqa: BLE001
                log(f"legacy 标签识别失败: {e}", "WARN")
                knowledge_tags = None
                second_tag = None

        content_profile = None
        try:
            from tag_agent.content_profile import build_content_profile

            content_profile = build_content_profile(
                question_text,
                knowledge_tags,
                second=second_tag,
                meta=meta,
                title=title,
                has_image=bool(has_image),
            )
        except Exception as e:  # noqa: BLE001
            log(f"构建教学画像失败（不影响标签）: {e}", "WARN")
        return knowledge_tags, second_tag, meta, content_profile

    @staticmethod
    def _drop_tags_not_in_db_framework(
        knowledge_tags: Optional[dict], second_tag: Optional[dict]
    ) -> tuple[Optional[dict], Optional[dict], bool]:
        """标签组与数据库正式标签框架（knowledge_tag_framework）对账.

        背景（2026-09-11 排查）：智能体的"正式库"是本地种子 JSON
        （tag_agent/seed_data），与后台管理/legacy 引擎使用的 DB 框架可能
        漂移；legacy 引擎虽按框架构造，此处对两条引擎的最终产出统一兜底
        校验。不在 DB 框架内的标签组一律不落 metadata，防止野生标签绕过
        审核直接展示到题目上（被拦下的组由调用方置 needs_tag_selection）。

        Returns:
            (knowledge_tags, second_tag, dropped) — dropped=是否有组被拦截。
        框架加载失败时 fail-open 保留原结果（不因基础设施故障丢标签）。
        """
        try:
            from knowledge_tag_injector import load_framework

            hierarchy = (load_framework() or {}).get("hierarchy", {})

            def _in_framework(group: dict) -> bool:
                subs = (hierarchy.get(group.get("version") or "", {})
                        .get(group.get("grade") or "", {})
                        .get(group.get("main_tag") or ""))
                if not subs:
                    return False
                return all(t in subs for t in (group.get("sub_tags") or []))

            dropped = False
            if knowledge_tags and knowledge_tags.get("main_tag") and not _in_framework(knowledge_tags):
                log(
                    "主标签组不在 DB 正式框架内，已拦截（需审核/手动选择）: "
                    f"知识域={knowledge_tags.get('version')} 年级={knowledge_tags.get('grade')} "
                    f"章/单元={knowledge_tags.get('main_tag')} 标签={knowledge_tags.get('sub_tags')}",
                    "WARN",
                )
                knowledge_tags = None
                dropped = True
            if second_tag and second_tag.get("main_tag") and not _in_framework(second_tag):
                log(
                    "第二标签组不在 DB 正式框架内，已拦截: "
                    f"知识域={second_tag.get('version')} 章/单元={second_tag.get('main_tag')} "
                    f"标签={second_tag.get('sub_tags')}",
                    "WARN",
                )
                second_tag = None
                dropped = True
            return knowledge_tags, second_tag, dropped
        except Exception as e:  # noqa: BLE001
            log(f"标签框架对账失败（fail-open 保留原结果）: {type(e).__name__}: {str(e)[:150]}", "WARN")
            return knowledge_tags, second_tag, False

    async def _build_question_text(self, input_path: str, prompt: str) -> str:
        """构造题目文本。

        - 当前 demo 阶段：优先使用前端传来的 prompt 作为题面；
        - 如果没有 prompt，则用文件名占位，方便后续 OCR/ASR 接入。
        """

        if prompt and prompt.strip():
            return prompt.strip()

        base = Path(input_path).name
        return f"请根据文件「{base}」中的题目，面向小学生讲解解题思路。"

    async def _check_problem_solvable(self, question_text: str, image_path: str = "") -> dict:
        """识题阶段轻量解题预检。

        文字题走文本模型，图片题把原图（base64）一并传给视觉模型直接判读（避免 OCR 丢坐标）。
        返回 {solvable, reason, brief}。
        开关 ENABLE_SOLVABILITY_CHECK 关闭、或 LLM 调用失败时一律 fail-open（solvable=True），
        不把基础设施故障当成题目错误、也不阻断正常生成。
        """
        if os.getenv("ENABLE_SOLVABILITY_CHECK", "true").strip().lower() in ("0", "false", "off", "no"):
            log("解题预检已通过开关关闭，跳过", "INFO")
            return {"solvable": True, "reason": "", "brief": ""}

        user_text = (
            "请对下面这道题目做解题预检，仅输出判定 JSON：\n\n" + (question_text or "")
        )

        # 图片输入：把原图内联传给视觉模型（与 _analyze_image_question 同格式）
        human_content: any = user_text
        if image_path and self._is_image_file(image_path):
            try:
                with open(image_path, "rb") as f:
                    raw = f.read()
                mime = self._get_image_mime_type(Path(image_path)) or "image/png"
                data, mime = compress_image_for_vision(raw, mime)
                b64 = base64.b64encode(data).decode("ascii")
                human_content = [
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                    {"type": "text", "text": user_text},
                ]
            except Exception as e:
                log(f"解题预检图片读取/压缩失败，降级为纯文本预检：{e}", "WARN")
                human_content = user_text

        messages = [
            SystemMessage(content=SOLVABILITY_SYSTEM_PROMPT),
            HumanMessage(content=human_content),
        ]
        try:
            llm = self._get_llm_analyzer()

            async def _ask_precheck_once() -> dict:
                resp = await llm.ainvoke(messages)
                content = resp.content
                if isinstance(content, list):
                    # 部分 provider 返回 content 块列表，拼接文本
                    content = "".join(getattr(b, "text", "") for b in content if getattr(b, "text", ""))
                text = content if isinstance(content, str) else str(content)
                return _parse_solvability_verdict(text)

            verdict = await _ask_precheck_once()

            # 复核采样：单次判定可能因题面歧义选错建模而误杀
            # （实例：追及题"乙先跑2秒，甲跑4秒追上"被建成 4a=2b 解出负速度判无解，
            #   同题换建模 a-b=2、4(a-b)=2b 则甲6乙4 完全可解）。
            # 两次独立判定均为 false 才拦截；复核翻案则 fail-open 放行。
            if not verdict.get("solvable"):
                _first_reason = verdict.get("reason") or ""
                verdict = await _ask_precheck_once()
                if verdict.get("solvable"):
                    log(
                        f"解题预检复核翻案（首次判无解: {_first_reason[:80]}），按可解继续生成",
                        "WARN",
                    )
                    return {"solvable": True, "reason": "", "brief": verdict.get("brief", "")}
                log(f"解题预检两次独立判定均未通过，确认拦截", "WARN")

            log(
                f"解题预检结果：solvable={verdict['solvable']}"
                + (f"，brief={verdict['brief'][:80]}" if verdict["brief"] else "")
                + (f"，reason={verdict['reason'][:120]}" if verdict["reason"] else ""),
                "INFO",
            )
        except Exception as e:
            log(f"解题预检 LLM 调用失败，fail-open 放行继续生成：{e}", "WARN")
            return {"solvable": True, "reason": "", "brief": ""}
        return verdict

    def _load_prompt_template(self, file_path: Path) -> str:
        """从文件加载 prompt 模板。"""
        try:
            if file_path.exists():
                with open(file_path, "r", encoding="utf-8") as f:
                    return f.read().strip()
            else:
                log(f"Prompt 文件不存在: {file_path}", "WARN")
                return ""
        except Exception as e:
            log(f"读取 Prompt 文件失败 {file_path}: {e}", "ERROR")
            return ""

    def _is_math_question(self, design_output: str) -> tuple[bool, str]:
        """判断设计输出是否为数学题。
        
        返回：(是否为数学题, 错误消息)
        如果不是数学题，返回 (False, 错误消息)
        如果是数学题，返回 (True, "")
        """
        # 检查是否包含特殊标记
        if "__NOT_MATH_QUESTION__" in design_output:
            # 提取错误消息（标记后的内容）
            lines = design_output.split("\n")
            error_msg = ""
            found_marker = False
            for line in lines:
                if "__NOT_MATH_QUESTION__" in line:
                    found_marker = True
                    # 提取标记后的内容
                    if "__NOT_MATH_QUESTION__" in line:
                        part = line.split("__NOT_MATH_QUESTION__", 1)[-1].strip()
                        if part:
                            error_msg = part
                    continue
                if found_marker and line.strip():
                    if not error_msg:
                        error_msg = line.strip()
                    else:
                        error_msg += " " + line.strip()
            
            # 如果没有提取到消息，使用默认消息
            if not error_msg:
                error_msg = "抱歉，您输入的内容不是初中数学题，请提供一道初中数学题。"
            
            return False, error_msg
        
        return True, ""
    
    def _clean_generated_html(self, html: str) -> str:
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

    def _escape_js_single_quote(self, text: str) -> str:
        """转义单引号 JS 字符串。"""
        return text.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")

    def _write_template_failure_sample(
        self,
        task_dir: Path | None,
        failure_stage: str,
        error_message: str,
        debug_info: Dict,
    ) -> Optional[Path]:
        """将模板动态片段失败样本落盘，便于后续回放定位。"""
        try:
            base_dir = task_dir if task_dir else (Path(__file__).resolve().parent.parent / "storage" / "_template_failure_samples")
            sample_dir = base_dir / "template_failure_samples"
            sample_dir.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            sample_path = sample_dir / f"{timestamp}_{failure_stage}.json"
            sample_payload = {
                "failure_stage": failure_stage,
                "error_message": error_message,
                "generated_at": datetime.utcnow().isoformat() + "Z",
                "task_id": task_dir.name if task_dir else None,
                "debug_info": debug_info,
            }

            with open(sample_path, "w", encoding="utf-8") as f:
                json.dump(sample_payload, f, ensure_ascii=False, indent=2)

            log(f"模板失败样本已落盘: {sample_path}", "WARN")
            return sample_path
        except Exception as exc:
            log(f"模板失败样本落盘失败: {exc}", "WARN")
            return None

    def _build_question_summary(self, question: str, title: str = "", max_len: int = 56) -> str:
        """本地兜底：生成顶部展示的概括语句。"""
        if title and title.strip():
            clean_title = re.sub(r"\s+", " ", title).strip()
            if len(clean_title) > max_len:
                clean_title = clean_title[:max_len].rstrip() + "..."
            return f"{clean_title}"

        return "从已知条件出发，分步推导关键数量关系。"

    async def _generate_question_summary(self, question: str, title: str = "") -> str:
        """调用 gpt-5.5 生成"题意概括"，失败时回退到本地规则。"""
        fallback_summary = self._build_question_summary(question, title=title)
        clean_question = re.sub(r"\s+", " ", (question or "")).strip()
        if not clean_question:
            return fallback_summary

        question_compact = re.sub(r"\s+", "", clean_question)

        def summary_looks_too_similar(candidate: str) -> bool:
            compact_candidate = re.sub(r"\s+", "", candidate or "")
            if not compact_candidate or len(compact_candidate) < 4:
                return True
            prefix = question_compact[:8]
            if prefix and prefix in compact_candidate:
                return True
            if question_compact and compact_candidate in question_compact[: max(12, len(compact_candidate))]:
                return True
            return False

        try:
            llm = self._get_llm_analyzer()
            # gpt-5.5 为 reasoning 模型，响应偏慢，默认超时放宽到 90s
            timeout_seconds = int(os.getenv("SUMMARY_TIMEOUT", "90"))
            system_prompt = (
                "你是小学数学教学文案助手。"
                "请根据题目提炼一句题意概括，必须概括核心任务，不得照搬题目原文。"
                "只输出一句中文短句，不要解释，不要编号，不要引号，不要 markdown。"
            )
            prompts = [
                (
                    f"题目：{clean_question}\n"
                    f"标题：{title or '无'}\n"
                    "要求：12-22字，表达核心任务与关键关系，禁止复述题目中的连续原文。"
                ),
                (
                    f"题目：{clean_question}\n"
                    f"标题：{title or '无'}\n"
                    "要求：重新改写成一句概括，不能使用题目前8个字或任何明显原文片段。"
                ),
            ]

            for attempt, user_prompt in enumerate(prompts, start=1):
                resp = await asyncio.wait_for(
                    llm.ainvoke(
                        [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ]
                    ),
                    timeout=timeout_seconds,
                )
                raw_summary = resp.content if hasattr(resp, "content") else str(resp)
                if not str(raw_summary or "").strip():
                    # gpt-5.5 等 reasoning 模型偶发"只思考不输出"（finish_reason=stop 但 content 为空），重试
                    log("题意概括模型返回空内容，自动重试一次", "WARN")
                    continue
                summary = re.sub(r"\s+", " ", str(raw_summary)).strip()
                summary = summary.replace("题意概括：", "").replace("概括：", "").strip(" \n\r\t。；;，,")
                if "\n" in summary:
                    summary = summary.split("\n", 1)[0].strip()
                if len(summary) > 22:
                    summary = summary[:22].rstrip() + "..."

                if not summary_looks_too_similar(summary):
                    return summary

                log(f"题意概括与原题相似度过高，第 {attempt} 次重试", "WARN")

            return fallback_summary
        except Exception as exc:
            log(f"调用 gpt-5.5 生成题意概括失败，已回退本地概括: {type(exc).__name__}: {exc}", "WARN")
            return fallback_summary

    def _extract_first_json_object(self, text: str) -> str:
        """从文本中提取第一个完整 JSON 对象字符串。"""
        if not text:
            return ""

        # 优先处理 ```json 代码块
        code_block_pattern = r"```(?:json)?\s*(.*?)\s*```"
        matches = re.findall(code_block_pattern, text, re.DOTALL | re.IGNORECASE)
        for code_content in matches:
            start_idx = code_content.find('{')
            if start_idx != -1:
                brace_count = 0
                in_string = False
                escape_next = False
                for i in range(start_idx, len(code_content)):
                    ch = code_content[i]
                    if escape_next:
                        escape_next = False
                        continue
                    if ch == '\\':
                        escape_next = True
                        continue
                    if ch == '"':
                        in_string = not in_string
                        continue
                    if not in_string:
                        if ch == '{':
                            brace_count += 1
                        elif ch == '}':
                            brace_count -= 1
                            if brace_count == 0:
                                return code_content[start_idx:i + 1]

        # 通用扫描
        start_idx = text.find('{')
        if start_idx == -1:
            return ""

        brace_count = 0
        in_string = False
        escape_next = False
        for i in range(start_idx, len(text)):
            ch = text[i]
            if escape_next:
                escape_next = False
                continue
            if ch == '\\':
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if not in_string:
                if ch == '{':
                    brace_count += 1
                elif ch == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        return text[start_idx:i + 1]
        return ""
    def _escape_json_control_chars_in_strings(self, text: str) -> str:
        """修复 JSON 字符串中未转义的控制字符。"""
        if not text:
            return text

        out: list[str] = []
        in_string = False
        escape_next = False

        for ch in text:
            if in_string:
                if escape_next:
                    out.append(ch)
                    escape_next = False
                    continue

                if ch == "\\":
                    out.append(ch)
                    escape_next = True
                    continue

                if ch == '"':
                    out.append(ch)
                    in_string = False
                    continue

                # JSON 字符串内必须转义控制字符
                if ch == "\n":
                    out.append("\\n")
                    continue
                if ch == "\r":
                    out.append("\\r")
                    continue
                if ch == "\t":
                    out.append("\\t")
                    continue
                if ord(ch) < 0x20:
                    out.append(f"\\u{ord(ch):04x}")
                    continue

                out.append(ch)
                continue

            out.append(ch)
            if ch == '"':
                in_string = True

        return "".join(out)

    def _remove_scene_background_overlays(self, scene_svg: str) -> str:
        """移除模型偶发生成的全画布背景层（尤其是米黄色底板）。"""
        if not scene_svg:
            return scene_svg

        beige_tokens = (
            "#fdfbf7",
            "#f5f5dc",
            "#faf3e0",
            "#f8f4e8",
            "#fff8e7",
            "#f3ead7",
            "beige",
            "ivory",
            "wheat",
            "rgb(253,251,247)",
            "rgb(245,245,220)",
        )

        removed_rect = 0
        removed_fo = 0
        removed_path = 0

        def _parse_num(attrs: str, key: str, default: float) -> float:
            match = re.search(rf"\b{key}\s*=\s*['\"]\s*([-+]?[0-9]*\.?[0-9]+)", attrs, re.IGNORECASE)
            if not match:
                return default
            try:
                return float(match.group(1))
            except Exception:
                return default

        def _is_light_fill(attrs: str) -> bool:
            fill_match = re.search(r"\bfill\s*=\s*['\"]([^'\"]+)['\"]", attrs, re.IGNORECASE)
            if not fill_match:
                return False
            fill_value = fill_match.group(1).strip().lower().replace(" ", "")
            return any(token in fill_value for token in beige_tokens)

        def _is_full_canvas_rect(attrs: str) -> bool:
            x = _parse_num(attrs, "x", 0.0)
            y = _parse_num(attrs, "y", 0.0)
            w = _parse_num(attrs, "width", 0.0)
            h = _parse_num(attrs, "height", 0.0)
            return x <= 20 and y <= 20 and w >= 780 and h >= 560

        def _rect_replacer(match: re.Match) -> str:
            nonlocal removed_rect
            tag = match.group(0)
            if _is_full_canvas_rect(tag):
                removed_rect += 1
                return ""
            return tag

        def _fo_replacer(match: re.Match) -> str:
            nonlocal removed_fo
            tag = match.group(0)
            if _is_full_canvas_rect(tag):
                removed_fo += 1
                return ""
            return tag

        def _path_replacer(match: re.Match) -> str:
            nonlocal removed_path
            tag = match.group(0)
            if not _is_light_fill(tag):
                return tag
            d_match = re.search(r"\bd\s*=\s*['\"]([^'\"]+)['\"]", tag, re.IGNORECASE)
            if not d_match:
                return tag
            d_compact = re.sub(r"\s+", "", d_match.group(1)).lower()
            full_canvas_pattern = (
                "m0,0" in d_compact
                and (
                    (("h800" in d_compact and "v600" in d_compact)
                     or ("h820" in d_compact and "v620" in d_compact))
                    or (("l800,0" in d_compact and "l800,600" in d_compact and "l0,600" in d_compact)
                        or ("l820,0" in d_compact and "l820,620" in d_compact and "l0,620" in d_compact))
                )
                and "z" in d_compact
            )
            if full_canvas_pattern:
                removed_path += 1
                return ""
            return tag

        cleaned = re.sub(r"<rect\b[^>]*>", _rect_replacer, scene_svg, flags=re.IGNORECASE)
        cleaned = re.sub(r"<foreignObject\b[^>]*>", _fo_replacer, cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"<path\b[^>]*>", _path_replacer, cleaned, flags=re.IGNORECASE)

        removed_total = removed_rect + removed_fo + removed_path
        if removed_total > 0:
            log(
                f"已移除动态场景全画布背景层: rect={removed_rect}, foreignObject={removed_fo}, path={removed_path}",
                "INFO",
            )

        return cleaned

    def _normalize_scene_step_indexing(self, scene_svg: str) -> str:
        """将 1 基 currentStep 条件归一化为 0 基，避免首步动画空白。"""
        if not scene_svg or "currentStep" not in scene_svg:
            return scene_svg

        pattern_rhs = re.compile(r"(currentStep\s*(?:===|==|>=|<=|>|<)\s*)(\d+)")
        pattern_lhs = re.compile(r"(\d+)(\s*(?:===|==|>=|<=|>|<)\s*currentStep)")

        referenced_indices: list[int] = []
        for m in pattern_rhs.finditer(scene_svg):
            referenced_indices.append(int(m.group(2)))
        for m in pattern_lhs.finditer(scene_svg):
            referenced_indices.append(int(m.group(1)))

        if not referenced_indices:
            return scene_svg

        min_idx = min(referenced_indices)
        if min_idx <= 0:
            return scene_svg

        def _rhs_replacer(match: re.Match) -> str:
            prefix = match.group(1)
            idx = int(match.group(2))
            return f"{prefix}{max(0, idx - 1)}"

        def _lhs_replacer(match: re.Match) -> str:
            idx = int(match.group(1))
            suffix = match.group(2)
            return f"{max(0, idx - 1)}{suffix}"

        normalized = pattern_rhs.sub(_rhs_replacer, scene_svg)
        normalized = pattern_lhs.sub(_lhs_replacer, normalized)
        log(
            f"检测到动态场景使用 1 基步骤索引，已自动归一化到 0 基（最小索引: {min_idx}）",
            "INFO",
        )
        return normalized

    @staticmethod
    def _normalize_point_field(
        value: Any,
        *,
        fallback: Dict[str, float],
        field_name: str,
        step_index: int,
        debug_info: Dict,
    ) -> Dict[str, float]:
        """将模型输出的点坐标字段规整为 {x: 数值, y: 数值}，避免单步字段形态异常拖垮整个动画任务。

        支持形态：dict{x,y}（数值或可转数值）、两元素 list/tuple、逗号/空格分隔字符串。
        无法规整或缺失时回退默认坐标（fallback）并记 WARN + debug_info.recovered_fields，
        保证后续校验与渲染始终拿到结构正确的坐标对象。
        """
        try:
            if isinstance(value, dict):
                x, y = value.get("x"), value.get("y")
                if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                    return {"x": float(x), "y": float(y)}
                try:
                    fx, fy = float(x), float(y)
                    log(f"动态片段 step[{step_index}] {field_name} 坐标类型异常，已规整为数值: {value}", "WARN")
                    debug_info.setdefault("recovered_fields", []).append(
                        {"step_index": step_index, "field": field_name, "original": value, "reason": "coordinate_non_numeric"}
                    )
                    return {"x": fx, "y": fy}
                except (TypeError, ValueError):
                    pass
            elif isinstance(value, (list, tuple)) and len(value) == 2:
                try:
                    fx, fy = float(value[0]), float(value[1])
                    log(f"动态片段 step[{step_index}] {field_name} 为数组形态，已规整: {value}", "WARN")
                    debug_info.setdefault("recovered_fields", []).append(
                        {"step_index": step_index, "field": field_name, "original": value, "reason": "array_form"}
                    )
                    return {"x": fx, "y": fy}
                except (TypeError, ValueError):
                    pass
            elif isinstance(value, str):
                parts = re.split(r"[,\s，、]+", value.strip())
                if len(parts) == 2:
                    try:
                        fx, fy = float(parts[0]), float(parts[1])
                        log(f"动态片段 step[{step_index}] {field_name} 为字符串形态，已规整: {value}", "WARN")
                        debug_info.setdefault("recovered_fields", []).append(
                            {"step_index": step_index, "field": field_name, "original": value, "reason": "string_form"}
                        )
                        return {"x": fx, "y": fy}
                    except (TypeError, ValueError):
                        pass
            # 无法规整（缺失 / null / 其他类型）→ 回退默认坐标，并记录恢复痕迹以便溯源
            log(f"动态片段 step[{step_index}] {field_name} 形态异常（{'缺失' if value is None else type(value).__name__}），已回退默认坐标 {fallback}", "WARN")
            debug_info.setdefault("recovered_fields", []).append(
                {
                    "step_index": step_index,
                    "field": field_name,
                    "original": value,
                    "reason": "missing" if value is None else f"unsupported_type_{type(value).__name__}",
                }
            )
            return {"x": float(fallback["x"]), "y": float(fallback["y"])}
        except Exception as exc:
            log(f"动态片段 {field_name} 规整过程异常，回退默认坐标: {exc}", "WARN")
            return {"x": float(fallback["x"]), "y": float(fallback["y"])}

    async def _generate_template_dynamic_parts(
        self,
        client,
        model_name: str,
        question: str,
        title: str,
        has_pic: bool = False,
        reference_image_path: str | None = None,
        max_output_tokens: int = 65535,
        content_profile: Optional[dict] = None,
        lint_feedback: str = "",
    ) -> tuple[str, list[dict], Dict]:
        """仅生成模板中的动态片段（SVG 动画演示 + 解题步骤）。

        content_profile: ContentProfile.to_dict()（P0 起主链路带画像）；存在时
            用分层提示词库（prompt_router）拼装 System Prompt，并启用 SVG 纪律
            Lint（_lint_scene_svg）。无画像/分层失败 → 回退 legacy 单文件提示词。
        lint_feedback: 上一次 Lint 拒绝时产生的纪律反馈，追加进 user prompt，
            实现"带 Lint 反馈重试 1 次"（方案 §4.5）。
        """
        end_marker = "<!--PARTS_END-->"
        debug_info: Dict = {
            "question": question,
            "title": title,
            "model_name": model_name,
            "end_marker": end_marker,
            "attempts": [],
        }

        has_pic_text = "是" if has_pic else "否"

        # ── 提示词选择：分层提示词库优先（有画像），legacy 兜底 ──────────────
        layered_system_prompt: Optional[str] = None
        layered_user_template: str = ""
        if content_profile:
            try:
                from prompt_router import build_animation_system_prompt

                layered_system_prompt = build_animation_system_prompt(content_profile)
                layered_user_file = Path(__file__).resolve().parent / "prompt" / "animation" / "90_user_prompt.txt"
                if layered_system_prompt and layered_user_file.exists():
                    layered_user_template = self._load_prompt_template(layered_user_file)
                    log(
                        f"使用分层提示词库生成模板动态部分: "
                        f"stage={content_profile.get('stage')}, "
                        f"domain={content_profile.get('display_class')}, "
                        f"type={content_profile.get('question_type') or '无'}",
                        "INFO",
                    )
                else:
                    layered_system_prompt = None
            except Exception as exc:  # noqa: BLE001
                layered_system_prompt = None
                log(f"分层提示词加载失败，回退 legacy: {exc}", "WARN")

        file_system_prompt = self._load_prompt_template(self.teaching_dynamic_system_prompt_path)
        file_user_prompt_template = self._load_prompt_template(self.teaching_dynamic_user_prompt_path)

        if layered_system_prompt and layered_user_template:
            system_prompt = layered_system_prompt.strip()
            user_prompt = (
                layered_user_template
                .replace("__QUESTION__", question)
                .replace("__TITLE__", title)
                .replace("__HAS_PIC__", has_pic_text)
            )
            log("使用分层提示词（分层纪律 + 学段/知识域表达）", "INFO")
        elif file_system_prompt and file_user_prompt_template:
            system_prompt = file_system_prompt.strip()
            user_prompt = (
                file_user_prompt_template
                .replace("__QUESTION__", question)
                .replace("__TITLE__", title)
                .replace("__HAS_PIC__", has_pic_text)
            )
            log("使用统一提示词文件生成模板动态部分（legacy）", "INFO")
        else:
            system_prompt = (
                "你是前端教学动画代码生成器。"
                "只输出 JSON，不要输出任何额外解释。"
                "JSON 必须且只能包含两个顶级字段：scene_svg 与 steps。"
                "输出必须可被 Python json.loads 直接解析。"
            )
            user_prompt = (
                "请根据题目生成模板动态部分：\n"
                f"题目：{question}\n"
                f"标题：{title}\n"
                f"是否包含几何图形：{has_pic_text}\n"
                "输出 JSON 结构："
                "{\"title\":\"...\",\"summary\":\"...\",\"scene_svg\":\"...\",\"steps\":[{\"title\":\"\",\"description\":\"\",\"bubbleText\":\"\",\"bubblePos\":{\"x\":24,\"y\":24},\"arrowTarget\":{\"x\":560,\"y\":360}}]}。\n"
                "硬约束（必须全部满足，否则视为失败）：\n"
                "1) 只输出 JSON 本体 + 最后一行结束标记，严禁 markdown 代码块、严禁注释、严禁额外字段；\n"
                "2) scene_svg 只允许 SVG 内部片段，严禁包含 <svg>、<script>、<html>、<body>（可以且推荐使用 <defs> 和 <style>）；\n"
                "3) steps 数量必须为 6 - 15，且每步 title/description/bubbleText 均为非空字符串；\n"
                "4) 每步必须有 bubblePos，且 bubblePos.x / bubblePos.y 必须是数值；\n"
                "5) 每步必须有 arrowTarget，且 arrowTarget.x / arrowTarget.y 必须是数值，表示当前讲解对象中心；不得所有步骤都使用同一个默认点或画布中心；\n"
                "6) bubblePos 和 arrowTarget 都使用同一 SVG 画布坐标系（820×620）；\n"
                "6.1) arrowTarget 必须落在当前 bubbleText 实际解释的公式、关键数字、图形标记或文字块中心；若目标是矩形内文字，指向文字块中心而非矩形边缘；\n"
                "6.2) 所有带文字矩形必须按文字实际尺寸自适应，至少保留 16px 内边距；长文本主动换行或扩大矩形，禁止文字超出、遮挡或被裁切；文字与背景矩形使用相同 x-show；\n"
                "7) scene_svg 必须包含至少 8 个 x-show 条件块，并明确分为 persistent-layer 与 temporary-layer-step-N；\n"
                "8) 核心持久元素可以使用 sceneStep >= N，但临时元素严禁使用 sceneStep >= N，必须严格使用 sceneStep === N；\n"
                "9) 轨迹、虚线箭头、运动路径、笔迹、高亮、辅助线和阶段性标注一律属于临时层，进入下一步必须消失，不得叠加；\n"
                "10) scene_svg 必须包含至少 3 处 x-transition 高级平滑切换；\n"
                "11) scene_svg 必须包含至少 2 条带 dashed-line 类的流动轨迹，且这些轨迹必须位于对应步骤临时层；\n"
                "12) 数学公式必须放在 <foreignObject> 内；\n"
                "13) 视觉风格为新中式：水墨灰+朱砂红+米白；\n"
                "14) 解题步骤最后必须包含答案验证；\n"
                "15) 严禁全画布背景层和未渲染的 LaTeX 原文。\n"
                "最后一行必须追加结束标记 " + end_marker + "。"
            )

        # 复合多小题：把 parts 清单渲染进用户模板（__PARTS__ 占位；非复合则清空）
        _cp_parts = (content_profile or {}).get("parts") if content_profile else None
        _parts_block = _render_parts_block(_cp_parts) if _cp_parts else ""
        if "__PARTS__" in user_prompt:
            user_prompt = user_prompt.replace("__PARTS__", _parts_block)

        # Lint 反馈注入：上一次被 SVG 纪律 Lint 拒绝时，把具体违规点带给模型，
        # 实现"带 Lint 反馈重试 1 次"（方案 §4.5，违规处理）。
        if lint_feedback and lint_feedback.strip():
            user_prompt += (
                "\n\n【上一轮 SVG 纪律检查未通过，请修正后重新输出】\n"
                + lint_feedback.strip()
            )

        reference_image_content = None
        if reference_image_path:
            reference_path = Path(reference_image_path)
            reference_mime = self._get_image_mime_type(reference_path)
            if reference_path.exists() and reference_mime:
                try:
                    reference_data = reference_path.read_bytes()
                    reference_data, reference_mime = compress_image_for_vision(reference_data, reference_mime)
                    reference_b64 = base64.b64encode(reference_data).decode("ascii")
                    reference_image_content = {
                        "type": "image_url",
                        "image_url": {"url": f"data:{reference_mime};base64,{reference_b64}"},
                    }
                    user_prompt += _ref_prompt_note(content_profile)
                except Exception as exc:
                    log(f"读取教学动画预览图失败，将仅使用文字题面: {exc}", "WARN")

        def _generate_parts_sync() -> tuple[str, list[dict]]:
            max_rounds = int(os.getenv("HTML_PARTS_CONTINUE_MAX_ROUNDS", "2"))
            continue_tokens = int(os.getenv("HTML_PARTS_CONTINUE_MAX_TOKENS", "32768"))

            combined = ""
            current_prompt = user_prompt
            finish_reasons: list[str] = []
            last_response_text = ""

            for round_idx in range(max_rounds + 1):
                round_max_tokens = max_output_tokens if round_idx == 0 else max(1024, min(max_output_tokens, continue_tokens))
                user_message_content = current_prompt
                if round_idx == 0 and reference_image_content:
                    user_message_content = [reference_image_content, {"type": "text", "text": current_prompt}]
                # 关键修复：改用流式（stream）调用。
                # kuaipao.pro 网关存在 120s Proxy Read Timeout，非流式在大体量提示词 /
                # 长输出下整段无完整响应即被网关掐断（APITimeoutError / 524 / SDK 重试），
                # 表现为"动画生成每次都要重试好多次"。流式让字节持续下发，网关保持连接，
                # 彻底规避该超时。已实测：同一提示词流式 81s 正常返回，非流式 60s 即超时。
                stream = client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message_content},
                    ],
                    max_completion_tokens=round_max_tokens,
                    stream=True,
                    timeout=900.0,
                    **get_params_for_model(model_name),
                )
                text = ""
                finish_reason = "stop"
                for _ev in stream:
                    if not _ev.choices:
                        continue
                    _delta = _ev.choices[0].delta.content or ""
                    if _delta:
                        text += _delta
                    _fr = getattr(_ev.choices[0], "finish_reason", None)
                    if _fr:
                        finish_reason = _fr
                last_response_text = text
                finish_reasons.append(finish_reason)
                debug_info["attempts"].append(
                    {
                        "round_idx": round_idx,
                        "round_max_tokens": round_max_tokens,
                        "finish_reason": finish_reason,
                        "streaming": True,
                        "response_text_preview": text[:1200],
                        "combined_preview": combined[-1200:],
                    }
                )

                if text:
                    if combined and not combined.endswith("\n"):
                        combined += "\n"
                    combined += text

                if end_marker in combined:
                    break

                if round_idx < max_rounds:
                    tail = combined[-800:] if combined else ""
                    current_prompt = (
                        "继续输出剩余 JSON，仅输出新增内容，不要重复。"
                        "继续时仍必须严格满足全部硬约束。"
                        "最后一行必须追加结束标记 " + end_marker + "。\n\n"
                        "末尾片段（仅定位用，禁止复述）：\n" + tail
                    )

            if end_marker not in combined:
                debug_info["error_stage"] = "missing_end_marker"
                debug_info["combined_preview"] = combined[-2000:]
                debug_info["last_response_text_preview"] = last_response_text[:2000]
                raise TemplateDynamicPartsError(
                    f"模板动态片段生成失败：未检测到结束标记 {end_marker}（finish_reasons: {finish_reasons}）",
                    debug_info,
                )

            cleaned = combined.replace(end_marker, "").strip()
            json_text = self._extract_first_json_object(cleaned)
            if not json_text:
                debug_info["error_stage"] = "extract_json"
                debug_info["combined_preview"] = combined[-2000:]
                debug_info["last_response_text_preview"] = last_response_text[:2000]
                raise TemplateDynamicPartsError("模板动态片段生成失败：未提取到有效 JSON", debug_info)

            # 修复：在 JSON 解析前，将 LaTeX 反斜杠命令（\frac, \sqrt, \times 等）
            # 中的 \ 转义为 \\，防止 json.loads 将 \f/\t/\r/\b
            # 错误解释为 JSON 控制字符（换页、制表、回车、退格）。
            # 注意：\n（JSON 换行转义）和 \u（JSON Unicode 转义）必须原样保留，
            # 否则 scene_svg 内 <style> 的换行会变成字面 "\n"，导致 CSS 失效、元素变黑框。
            json_text = re.sub(r'(?<!\\)\\(?![nu])([a-zA-Z])', r'\\\\\1', json_text)

            try:
                payload = json.loads(json_text)
            except json.JSONDecodeError as exc:
                repaired_json = self._escape_json_control_chars_in_strings(json_text)
                if repaired_json == json_text:
                    debug_info["error_stage"] = "json_decode"
                    debug_info["json_text_preview"] = json_text[:4000]
                    debug_info["combined_preview"] = combined[-2000:]
                    raise TemplateDynamicPartsError(f"模板动态片段生成失败：JSON 解析失败: {exc}", debug_info) from exc
                try:
                    payload = json.loads(repaired_json)
                    log(f"模板动态片段 JSON 首次解析失败，已自动修复控制字符并重试成功: {exc}", "WARN")
                except json.JSONDecodeError:
                    debug_info["error_stage"] = "json_decode_repaired_failed"
                    debug_info["json_text_preview"] = json_text[:4000]
                    debug_info["repaired_json_preview"] = repaired_json[:4000]
                    debug_info["combined_preview"] = combined[-2000:]
                    raise TemplateDynamicPartsError(f"模板动态片段生成失败：修复后 JSON 仍无法解析: {exc}", debug_info) from exc
            scene_svg = payload.get("scene_svg", "")
            steps = payload.get("steps", [])
            if not isinstance(scene_svg, str) or not scene_svg.strip():
                debug_info["error_stage"] = "empty_scene_svg"
                debug_info["payload_preview"] = json.dumps(payload, ensure_ascii=False)[:4000]
                raise TemplateDynamicPartsError("模板动态片段生成失败：scene_svg 为空", debug_info)

            # 兜底校验：<style> 内的 CSS 不应出现字面反斜杠字母（如 \n、\t、\r），
            # 否则 CSS 规则解析失败、元素回退为默认黑色填充（黑框），动画也全部失效。
            for style_block in re.findall(r"<style[^>]*>(.*?)</style>", scene_svg, re.DOTALL | re.IGNORECASE):
                if re.search(r"\\(?![uU])[a-zA-Z]", style_block):
                    debug_info["error_stage"] = "literal_escape_in_style"
                    debug_info["scene_svg_preview"] = scene_svg[:4000]
                    raise TemplateDynamicPartsError(
                        "模板动态片段生成失败：scene_svg 的 <style> 内出现字面反斜杠字母序列（如 \\n、\\t），会导致 CSS 失效出现黑框，请改用真实换行/空格",
                        debug_info,
                    )

            # 兜底校验：确保数学文本渲染路径正确，避免 <text> 中直接写 $$...$$。
            if re.search(r"<text[^>]*>[^<]*\$\$[\s\S]*?\$\$[^<]*</text>", scene_svg, re.IGNORECASE):
                debug_info["error_stage"] = "invalid_formula_text_rendering"
                debug_info["scene_svg_preview"] = scene_svg[:4000]
                raise TemplateDynamicPartsError(
                    "模板动态片段生成失败：检测到 <text> 内直接包含 $$...$$，请改为 foreignObject 文本渲染",
                    debug_info,
                )

            # 兜底校验：阻止未渲染 LaTeX 原文进入最终场景。
            if re.search(r"\$[^$\n]+\$|\$\$[\s\S]*?\$\$", scene_svg):
                debug_info["error_stage"] = "raw_latex_delimiter_detected"
                debug_info["scene_svg_preview"] = scene_svg[:4000]
                raise TemplateDynamicPartsError(
                    "模板动态片段生成失败：检测到未渲染的 $...$ / $$...$$ 公式原文",
                    debug_info,
                )
            if re.search(r"\\(?:le|ge|frac|sqrt|times|cdot|left|right|sum|int|alpha|beta|theta|pi|neq|approx|pm|cdots)\b", scene_svg, re.IGNORECASE):
                debug_info["error_stage"] = "raw_latex_command_detected"
                debug_info["scene_svg_preview"] = scene_svg[:4000]
                raise TemplateDynamicPartsError(
                    "模板动态片段生成失败：检测到未渲染的 LaTeX 控制符原文",
                    debug_info,
                )

            # 兜底校验：抑制大量无语义线条（常见退化模式）。
            raw_line_count = len(re.findall(r"<(?:line|path|polyline)\b", scene_svg, re.IGNORECASE))
            semantic_line_count = len(
                re.findall(
                    r"<(?:line|path|polyline)\b[^>]*(?:class=\"[^\"]*(?:dashed-line|svg-elem)[^\"]*\"|marker-|x-show=|id=|data-purpose=)",
                    scene_svg,
                    re.IGNORECASE,
                )
            )
            if raw_line_count >= 16 and semantic_line_count <= max(2, raw_line_count // 5):
                debug_info["error_stage"] = "too_many_non_semantic_lines"
                debug_info["raw_line_count"] = raw_line_count
                debug_info["semantic_line_count"] = semantic_line_count
                debug_info["scene_svg_preview"] = scene_svg[:4000]
                raise TemplateDynamicPartsError(
                    "模板动态片段生成失败：检测到大量疑似无语义线条，请保留具备教学语义的线条元素",
                    debug_info,
                )

            if not isinstance(steps, list) or len(steps) == 0:
                debug_info["error_stage"] = "empty_steps"
                debug_info["payload_preview"] = json.dumps(payload, ensure_ascii=False)[:4000]
                raise TemplateDynamicPartsError("模板动态片段生成失败：steps 为空", debug_info)

            for idx, step in enumerate(steps):
                if not isinstance(step, dict):
                    debug_info["error_stage"] = "invalid_step_type"
                    debug_info["step_index"] = idx
                    debug_info["payload_preview"] = json.dumps(payload, ensure_ascii=False)[:4000]
                    raise TemplateDynamicPartsError("模板动态片段生成失败：step 必须是对象", debug_info)

                # 容错修复（2026-08-27）：模型偶发将 bubblePos / arrowTarget 输出为非对象、
                # 坐标缺失或类型异常，自动规整为 {x, y} 数值对象；无法规整时回退默认坐标
                # 并记 WARN + debug_info，避免整个动画任务因单步字段形态异常而失败。
                bubble_pos = self._normalize_point_field(
                    step.get("bubblePos"),
                    fallback={"x": 24, "y": 24},
                    field_name="bubblePos",
                    step_index=idx,
                    debug_info=debug_info,
                )
                step["bubblePos"] = bubble_pos

                arrow_target = self._normalize_point_field(
                    step.get("arrowTarget"),
                    fallback={"x": 400, "y": 300},
                    field_name="arrowTarget",
                    step_index=idx,
                    debug_info=debug_info,
                )
                step["arrowTarget"] = arrow_target

            targets = {(step.get("arrowTarget", {}).get("x"), step.get("arrowTarget", {}).get("y")) for step in steps}
            if len(steps) > 1 and len(targets) == 1 and targets != {(400, 300)}:
                log("动态场景所有步骤箭头目标相同，请确认模型是否正确标注了当前讲解对象", level="WARNING")

            # ── P1：SVG 纪律 Lint（方案 §4.5）+ v2 题型画法模板专项（2026-09-05）──
            # 有画像时按学段/知识域执行分层纪律规则；无画像（legacy 链路）也执行
            # 通用规则（stage 用初中默认，避免旧链路漏检最严重的"乱动/叠加"）。
            # 命中 scene_pattern（如隧道/过桥族）时传 pattern_key 给 Lint，
            # 开启 pattern_contract / palette_blacklist 专项检查。
            pattern_key = ""
            if content_profile is not None:
                try:
                    from tag_agent.content_profile import pattern_keys_for_profile

                    _keys = pattern_keys_for_profile(content_profile)
                    pattern_key = _keys[0] if _keys else ""
                except Exception:  # noqa: BLE001
                    pattern_key = ""
            if content_profile is not None or lint_feedback:
                lint_outcome = self._lint_scene_svg(
                    scene_svg,
                    steps,
                    stage=(content_profile or {}).get("stage") or "junior_high",
                    pattern_key=pattern_key,
                )
                if not lint_outcome.get("passed"):
                    feedback = lint_outcome.get("feedback", "")
                    debug_info["error_stage"] = "scene_svg_lint"
                    debug_info["scene_svg_preview"] = scene_svg[:4000]
                    debug_info["lint_report"] = lint_outcome.get("report", [])
                    raise TemplateDynamicPartsError(
                        "模板动态片段生成失败：SVG 纪律 Lint 未通过\n"
                        + feedback,
                        debug_info,
                    )

            debug_info["payload_preview"] = json.dumps(payload, ensure_ascii=False)[:4000]
            return scene_svg, steps, debug_info

        return await asyncio.to_thread(_generate_parts_sync)

    def _lint_scene_svg(
        self,
        scene_svg: str,
        steps: list[dict],
        *,
        stage: str = "junior_high",
        display_class: str = "",
        pattern_key: str = "",
    ) -> dict:
        """SVG 纪律 Lint（方案 2026-09-03 §4.5）——从源头拦截"乱动/叠加/杂乱".

        基于 scene_lint 纯函数模块执行硬性规则；支持 SCENE_LINT_MODE 开关：
          strict（默认）→ 硬性违规 passed=False（调用方拒收，带反馈重试 1 次）；
          warn        → 硬性违规降级为警告，passed=True（仅记日志/供人工抽查）；
          off         → 完全跳过（风险开关，可一键关闭）。
        pattern_key: 命中题型画法模板（scene_patterns）时传入，开启 v2 专项检查
            （pattern_contract / palette_blacklist 按 pattern 命中级别判定）。

        Returns:
            {"passed": bool, "feedback": str, "report": [{"rule","message"}], "mode": str}
        """
        try:
            from scene_lint import lint_mode, lint_scene_svg

            mode = lint_mode()
            if mode == "off":
                return {"passed": True, "feedback": "", "report": [], "mode": mode}

            result = lint_scene_svg(
                scene_svg or "",
                steps or [],
                stage=stage or "junior_high",
                display_class=display_class,
                pattern_key=pattern_key,
            )
            if mode == "warn":
                # 告警模式：仅记录，不拒收
                if result.issues:
                    lines = [
                        f"- [{i.rule}] {i.message}" for i in result.issues if i.level == "hard"
                    ]
                    if lines:
                        log(f"SVG 纪律 Lint（warn 模式）发现 {len(lines)} 处违规，已放行: " + "; ".join(lines), "WARN")
                return {"passed": True, "feedback": "", "report": result.to_dict(), "mode": mode}

            if result.passed:
                return {"passed": True, "feedback": "", "report": result.to_dict(), "mode": mode}

            # strict：硬性违规 → 组装反馈
            hard = result.hard_issues
            feedback_lines = ["请检查并修正以下纪律违规，然后重新输出完整 JSON："]
            for issue in hard:
                feedback_lines.append(f"- [{issue.rule}] {issue.message}")
            warn_lines = [f"- [{i.rule}] {i.message}" for i in result.warnings]
            if warn_lines:
                feedback_lines.append("（另有告警，建议一并优化：")
                feedback_lines.extend("  " + w for w in warn_lines)
                feedback_lines.append("）")
            return {
                "passed": False,
                "feedback": "\n".join(feedback_lines),
                "report": result.to_dict(),
                "mode": mode,
            }
        except Exception as exc:  # noqa: BLE001
            # Lint 自身异常不应阻断生成：降级放行并记日志（与"可一键关闭"同级兜底）
            log(f"SVG 纪律 Lint 执行异常，本次放行: {exc}", "WARN")
            return {"passed": True, "feedback": "", "report": [], "mode": "error_fallback"}

    async def _generate_teaching_html_from_question(
        self,
        question: str,
        title: str,
        has_pic: bool = False,
        image_path: str | None = None,
        task_dir: Path | None = None,
        task_id: str | None = None,
        progress_callback: Optional[Callable[[int], None]] = None,
        max_output_tokens: int = 32768,
        simplify_prompt: bool = False,
        error_feedback: str = "",
        user_id: str | None = None,
        content_profile: Optional[dict] = None,
    ) -> str:
        """第二步：程序员（Kimi）根据题目和标题生成 HTML 教学应用。

        error_feedback 为管理员纠错要求：仅注入动画动态片段（SVG 演示 + 解题步骤）生成，
        不进入页面题目区 / 题意概括 / 教学数据，避免纠错内容出现在题面中。
        content_profile: ContentProfile.to_dict()（P0 起主链路带画像），驱动
            分层提示词路由 + SVG 纪律 Lint；无画像时回退 legacy 单文件提示词。
        """
        content_profile_dict = content_profile if isinstance(content_profile, dict) else None

        # 模板驱动：保留 UI/UX 骨架，仅替换动画与步骤
        template_html = self._load_prompt_template(self.teaching_html_template_path)
        if not template_html:
            raise RuntimeError("模板模式生成失败：缺少 teaching_template.html，已终止生成")

        log("使用 teaching_template.html 模板生成：仅替换动画演示与解题步骤", "INFO")

        client = self._get_kimi_client()
        model_name = get_active_model()

        # 页面展示用的干净题面（不含纠错要求）
        display_question = (question or "").strip()
        # 动画/步骤生成输入：干净题面 + 纠错要求（若有）
        generation_question = display_question
        if error_feedback and error_feedback.strip():
            generation_question = display_question + "\n\n【纠错要求】\n" + error_feedback.strip()
            log("纠错要求将仅注入动画动态片段生成（不写入题目区）", "INFO")

        # ── 画法模板路由（P0，2026-09-20）：命中冻结画法 → LLM 只写填空 JSON →
        #    装配器出整页 → teaching_data=None 走 teaching.html 兜底路径。
        #    未命中/任何异常都回退下方自由生成链路；ANIM_TEMPLATE_ROUTE_ENABLED=0 整条关闭。
        try:
            from template_router import try_frozen_template as _try_frozen
            _frozen = await _try_frozen(
                client=client,
                model_name=model_name,
                params_fn=get_params_for_model,
                question=display_question,
                title=title,
                content_profile=content_profile_dict,
                task_id=task_id,
                user_id=user_id,
            )
            if _frozen:
                log(f"画法路由命中 {_frozen.get('frozen_template', {}).get('id')}，使用冻结模板整页", "INFO")
                if progress_callback:
                    progress_callback(82)
                return _frozen
        except Exception as _route_err:  # noqa: BLE001
            log(f"画法模板路由异常（回退自由生成）: {_route_err}", "WARN")

        dynamic_retry_max = int(os.getenv("HTML_TEMPLATE_DYNAMIC_RETRY_MAX", "2"))
        dynamic_retry_delay = float(os.getenv("HTML_TEMPLATE_DYNAMIC_RETRY_DELAY_SECONDS", "1.5"))

        async def generate_template_parts_with_retry() -> tuple[str, list[dict], Dict]:
            last_error: Optional[Exception] = None
            last_debug_info: Dict = {}
            accumulated_lint_feedback = ""  # 累积 Lint 反馈，重试时注入提示词

            # 备用模型：默认模型超时/网络异常时优先切换尝试，而非直接降级
            backup_client = None
            backup_model_name = ""
            if is_backup_configured():
                try:
                    backup_client = self._get_backup_client()
                    backup_model_name = get_backup_model()
                except Exception as exc:  # noqa: BLE001
                    log(f"备用模型初始化失败，跳过备用模型: {exc}", "WARN")
                    backup_client = None
            used_backup = False  # 是否已切换到备用模型

            # 尝试次数预算独立：默认模型与备用模型各自拥有完整的
            # dynamic_retry_max + 1 次尝试，互不挤占；仅当默认模型确定超时
            # （is_timeout_error：超时/网络异常/网关 524）才切备用模型重跑。
            attempt = 0  # 当前模型的已用尝试次数（切换到备用时重置为 0）
            while attempt <= dynamic_retry_max:
                try:
                    if attempt > 0:
                        log(
                            f"模板动态片段重试中（{'备用模型' if used_backup else '默认模型'}）："
                            f"第 {attempt + 1}/{dynamic_retry_max + 1} 次",
                            "WARN",
                        )

                    cur_client = backup_client if used_backup else client
                    cur_model = backup_model_name if used_backup else model_name
                    scene_svg, steps, debug_info = await self._generate_template_dynamic_parts(
                        client=cur_client,
                        model_name=cur_model,
                        question=generation_question,
                        title=title,
                        has_pic=has_pic,
                        reference_image_path=(
                            str(task_dir / "Preview.webp")
                            if task_dir and (task_dir / "Preview.webp").exists()
                            else image_path
                        ),
                        max_output_tokens=max_output_tokens,
                        content_profile=content_profile_dict,
                        lint_feedback=accumulated_lint_feedback,
                    )
                    return scene_svg, steps, debug_info
                except TemplateDynamicPartsError as exc:
                    last_error = exc
                    last_debug_info = getattr(exc, "debug_info", {}) or {}
                    last_debug_info.setdefault("retry_attempt", attempt)
                    last_debug_info.setdefault("retry_limit", dynamic_retry_max)
                    log(f"模板动态片段生成失败（第 {attempt + 1} 次）: {exc}", "WARN")
                    # 若是 SVG 纪律 Lint 拒收：累积反馈供下一次注入（§4.5 带反馈重试 1 次）
                    if last_debug_info.get("error_stage") == "scene_svg_lint":
                        _report = last_debug_info.get("lint_report") or {}
                        _hard = (_report.get("hard") if isinstance(_report, dict) else None) or []
                        if _hard:
                            accumulated_lint_feedback = "\n".join(
                                f"- [{item.get('rule')}] {item.get('message')}" for item in _hard
                            )
                    if attempt < dynamic_retry_max:
                        attempt += 1
                        await asyncio.sleep(dynamic_retry_delay)
                        continue
                    break
                except Exception as exc:
                    # 默认模型确定超时/网络异常 → 切备用模型重跑，且备用模型
                    # 获得独立完整的重试预算（尝试计数重置），不挤占也不被挤占
                    if not used_backup and backup_client is not None and is_timeout_error(exc):
                        used_backup = True
                        attempt = 0
                        log(
                            f"默认模型调用超时/网络异常，切换到备用模型 {backup_model_name} "
                            f"重跑（备用重试预算独立：{dynamic_retry_max + 1} 次重新计数）: {exc}",
                            "WARN",
                        )
                        await asyncio.sleep(dynamic_retry_delay)
                        continue
                    last_error = exc
                    last_debug_info = {
                        "error_stage": "unexpected_exception",
                        "exception_type": type(exc).__name__,
                        "exception_message": str(exc),
                        "retry_attempt": attempt,
                        "retry_limit": dynamic_retry_max,
                    }
                    log(f"模板动态片段生成发生未知异常（第 {attempt + 1} 次）: {exc}", "WARN")
                    if attempt < dynamic_retry_max:
                        attempt += 1
                        await asyncio.sleep(dynamic_retry_delay)
                        continue
                    break

            # 将失败阶段映射到具体步骤（动画 / 完整解题 / 两者），便于在网站日志中清晰归因
            _stage = last_debug_info.get("error_stage") or "template_dynamic_parts_failed"
            _ANIM_STAGES = {
                "empty_scene_svg", "literal_escape_in_style", "invalid_formula_text_rendering",
                "raw_latex_delimiter_detected", "raw_latex_command_detected", "too_many_non_semantic_lines",
            }
            _SOL_STAGES = {
                "empty_steps", "invalid_step_type", "invalid_bubble_pos", "invalid_bubble_pos_type",
            }
            if _stage in _ANIM_STAGES:
                _step_label = "动画（场景 SVG）"
            elif _stage in _SOL_STAGES:
                _step_label = "完整解题（步骤）"
            else:
                _step_label = "动画与完整解题（动态片段）"

            failure_message = (
                f"【{_step_label}生成失败】模板动态片段生成失败，已重试 {dynamic_retry_max} 次，"
                f"最终错误: {last_error}（stage={_stage}）"
            )
            # 在网站日志中记录明确归因到「动画 / 完整解题」的失败条目
            try:
                record_website_log(
                    level="ERROR",
                    category="animation_generation",
                    message=f"{_step_label}生成失败: {last_error}（stage={_stage}）",
                    user_id=user_id,
                    task_id=task_id,
                )
            except Exception:
                pass
            self._write_template_failure_sample(
                task_dir=task_dir,
                failure_stage=_stage,
                error_message=failure_message,
                debug_info={
                    **last_debug_info,
                    "question": display_question,
                    "title": title,
                    "task_id": task_id,
                    "max_output_tokens": max_output_tokens,
                },
            )
            raise RuntimeError(failure_message)

        try:
            # 题意概括与动态片段生成并行（两者都只依赖题面与标题，互不依赖）
            parts_task = generate_template_parts_with_retry()
            summary_task = self._generate_question_summary(display_question, title)
            parts_result, summary_result = await asyncio.gather(parts_task, summary_task, return_exceptions=True)

            if isinstance(parts_result, Exception):
                raise parts_result
            scene_svg, steps, dynamic_debug_info = parts_result

            # 记录容错修复痕迹：模型字段形态异常被自动规整时，在日志与网站日志中留痕（2026-08-27）
            recovered_fields = (dynamic_debug_info or {}).get("recovered_fields") or []
            if recovered_fields:
                recovery_summary = "; ".join(
                    f"step[{r.get('step_index')}] {r.get('field')}({r.get('reason')})" for r in recovered_fields
                )
                log(f"动态片段生成完成，检测到 {len(recovered_fields)} 处字段形态异常已自动修复: {recovery_summary}", "WARN")
                try:
                    record_website_log(
                        level="WARN",
                        category="animation_generation",
                        message=f"动画生成成功，但 {len(recovered_fields)} 处字段形态异常已自动修复: {recovery_summary}",
                        user_id=user_id,
                        task_id=task_id,
                        context={"recovered_fields": recovered_fields[:20]},
                    )
                except Exception:
                    pass

            if isinstance(summary_result, Exception):
                log(f"题意概括失败（并行）: {summary_result}", "WARN")
                summary_text = ""
            else:
                summary_text = summary_result or ""

            scene_svg = self._remove_scene_background_overlays(scene_svg)
            scene_svg = self._normalize_scene_step_indexing(scene_svg)

            # 映射 currentStep -> sceneStep，匹配模板的步骤偏移逻辑
            scene_svg_for_template = re.sub(r"\bcurrentStep\b", "sceneStep", scene_svg)

            title_text = title if title else "数学互动教学"
            steps_json = json.dumps(steps, ensure_ascii=False, indent=4)
            summary_text_js = self._escape_js_single_quote(summary_text)
            summary_text_js = summary_text_js.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
            steps_json_for_script = (
                steps_json
                .replace("</", "<\\/")
                .replace("\u2028", "\\u2028")
                .replace("\u2029", "\\u2029")
            )

            final_html = template_html
            final_html = final_html.replace("__TITLE__", title_text)
            # 题目注入 HTML 文本区，需做 HTML 转义（存库保留原始文本，组合时统一转义）
            # 仅注入干净题面，纠错要求绝不进入题目区
            question_html = (
                (display_question or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            )
            final_html = final_html.replace("__QUESTION__", question_html)
            final_html = final_html.replace("__SUMMARY_TEXT__", summary_text_js)
            final_html = final_html.replace("__DYNAMIC_SCENE_SVG__", scene_svg_for_template)
            final_html = final_html.replace("__STEPS_JSON__", steps_json_for_script)

            log(f"模板填充完成，动态 SVG: {len(scene_svg_for_template)} 字符，步骤: {len(steps)}，HTML: {len(final_html)} 字符")

            if progress_callback:
                progress_callback(82)

            cleaned_html = self._clean_generated_html(final_html)

            teaching_data = {
                "title": title_text,
                "question": display_question,
                "summary": summary_text_js,
                "scene_svg": scene_svg_for_template,
                "steps_json": steps_json_for_script,
            }

            return {"html": cleaned_html, "teaching_data": teaching_data}
        except Exception:
            raise

    def _get_mock_plan(self, question: str) -> Dict:
        """测试模式：返回预设的解题步骤计划。"""
        return {
            "steps": [
                {
                    "title": "理解题意",
                    "detail": f"首先，我们要仔细读题，理解题目在问什么。题目是：{question[:50]}..."
                },
                {
                    "title": "找出已知条件",
                    "detail": "把题目中给出的数字和条件都找出来，写在草稿纸上。"
                },
                {
                    "title": "确定解题方法",
                    "detail": "根据题目的类型，选择合适的计算方法，比如加法、减法、乘法或除法。"
                },
                {
                    "title": "逐步计算",
                    "detail": "按照步骤一步步计算，不要着急，每一步都要算对。"
                },
                {
                    "title": "检查答案",
                    "detail": "算完后，检查一下答案是否合理，是否符合题目的要求。"
                }
            ]
        }

    def _get_mock_teaching_html(self, question: str, plan: Dict) -> str:
        """测试模式：从 web/sample_teaching.html 读取完整内容，不做任何删减。"""
        # 获取项目根目录（backend 的父目录）
        backend_dir = Path(__file__).resolve().parent
        project_root = backend_dir.parent
        sample_file = project_root / "web" / "sample_teaching.html"
        
        try:
            # 读取完整文件内容，不做任何处理
            with open(sample_file, "r", encoding="utf-8") as f:
                html_content = f.read()
            
            # 直接返回完整内容
            return html_content
                    
        except FileNotFoundError:
            # 如果文件不存在，返回一个错误提示
            return f"""
<section style="padding: 30px; text-align: center; color: #B83B43;">
    <p>测试文件未找到：{sample_file}</p>
    <p style="font-size: 14px; color: #5A6A76;">请确保 web/sample_teaching.html 文件存在</p>
</section>
"""
        except Exception as e:
            # 其他错误
            return f"""
<section style="padding: 30px; text-align: center; color: #B83B43;">
    <p>读取测试文件时出错：{str(e)}</p>
</section>
"""

    def _is_valid_teaching_html(self, teaching_html: str) -> tuple[bool, str]:
        """检查教学 HTML 是否有效（成功生成）。
        
        判断标准：
        1. 不为空
        2. 不是错误信息
        3. 包含基本的 HTML 结构
        4. 长度足够
        
        Returns:
            tuple[bool, str]: (是否有效, 失败原因) 如果有效，失败原因为空字符串
        """
        if not teaching_html or not teaching_html.strip():
            return False, "HTML 内容为空或只包含空白字符"
        
        html_lower = teaching_html.lower()
        html_length = len(teaching_html.strip())
        
        # 检查是否是错误信息（需同时满足：命中关键词且长度过短）
        # 避免正常教学 HTML 中偶然出现"错误/failed"等词被误判
        error_keywords = [
            ("错误", "包含错误关键词：'错误'"),
            ("失败", "包含错误关键词：'失败'"),
            ("未找到", "包含错误关键词：'未找到'"),
            ("读取测试文件时出错", "包含错误关键词：'读取测试文件时出错'"),
            ("测试文件未找到", "包含错误关键词：'测试文件未找到'"),
            ("error", "包含错误关键词：'error'"),
            ("failed", "包含错误关键词：'failed'"),
            ("not found", "包含错误关键词：'not found'"),
        ]
        # 当内容很短且包含上述关键词时，判定为错误信息
        error_length_threshold = 400
        for keyword, reason in error_keywords:
            if keyword in html_lower and html_length < error_length_threshold:
                return False, f"{reason}，且内容过短（{html_length} 字符）"
        
        # 检查是否包含基本的 HTML 结构
        # 可能是完整的 HTML 文档（包含 <html> 或 <!DOCTYPE>）
        # 或者是 HTML 片段（包含 <section>、<div>、<body> 等）
        has_doctype = "<!doctype" in html_lower
        has_html_tag = "<html" in html_lower
        has_body_tag = "<body" in html_lower
        has_section_tag = "<section" in html_lower
        has_div_tags = "<div" in html_lower and "</div>" in html_lower
        
        has_html_structure = (
            has_doctype or has_html_tag or has_body_tag or 
            has_section_tag or has_div_tags
        )
        
        if not has_html_structure:
            structure_details = []
            if not has_doctype:
                structure_details.append("缺少 <!DOCTYPE>")
            if not has_html_tag:
                structure_details.append("缺少 <html> 标签")
            if not has_body_tag:
                structure_details.append("缺少 <body> 标签")
            if not has_section_tag:
                structure_details.append("缺少 <section> 标签")
            if not has_div_tags:
                structure_details.append("缺少 <div> 标签对")
            
            return False, f"缺少基本的 HTML 结构（{', '.join(structure_details)}）"

        # 对完整页面增加完整性校验，避免流式输出被截断后误判为有效
        # 生成的教学页面应为完整 HTML 文档，并包含 Alpine 应用初始化逻辑
        if "<html" in html_lower:
            if "</body>" not in html_lower or "</html>" not in html_lower:
                return False, "HTML 文档不完整（缺少 </body> 或 </html> 结束标签，疑似输出被截断）"
            if "x-data=\"mathapp()\"" in html_lower:
                # K2.7 风格: function mathApp()
                # K3 风格:  window.mathApp = function ()
                has_mathapp = (
                    "function mathapp" in html_lower
                    or "window.mathapp" in html_lower
                    or "mathapp = function" in html_lower
                )
                if not has_mathapp:
                    return False, "检测到 x-data=\"mathApp()\" 但缺少 mathApp 初始化脚本，疑似输出被截断"
        
        # 基本长度检查（太短可能是错误信息）
        if html_length < 100:
            return False, f"HTML 内容太短（仅 {html_length} 字符，要求至少 100 字符）"
        
        return True, ""

    def _is_truncated_html_failure(self, validation_reason: str, teaching_html: str) -> bool:
        """判断 HTML 校验失败是否属于"输出截断"场景。"""
        if not validation_reason:
            return False

        reason = validation_reason.lower()
        truncation_markers = [
            "疑似输出被截断",
            "缺少 </body>",
            "缺少 </html>",
            "缺少 mathapp 初始化脚本",
            "html 文档不完整",
        ]
        if any(marker.lower() in reason for marker in truncation_markers):
            return True

        # 防御性兜底：内容不空且出现明显未闭合文档特征
        html_lower = (teaching_html or "").lower()
        if html_lower and "<html" in html_lower and ("</body>" not in html_lower or "</html>" not in html_lower):
            return True

        return False

    async def _save_teaching_content(
        self,
        task_dir: Path,
        question: str,
        prompt: str,
        plan: Dict,
        teaching_html: str,
        input_file: str,
        analysis_result: Dict = None,
        tags: Dict = None,
        knowledge_tags: Dict = None,
        second_tag: Optional[Dict] = None,
        needs_tag_selection: bool = False,
        user_id: Optional[str] = None,
        progress_callback: Optional[Callable[[int], None]] = None,
        teaching_data: Optional[Dict] = None,  # 模板动态数据（title, summary, scene_svg, steps_json）
    ) -> None:
        """保存生成的教学内容到本地文件。
        
        保存内容：
        - teaching_data.json: 模板动态数据（标题、摘要、SVG动画、解题步骤）
        - metadata.json: 包含题目、步骤、prompt、生成时间、分析结果等元数据
        - 如果用户上传了文件，将文件从临时目录移动到最终目录
        """
        import shutil
        
        try:
            # 创建最终的任务目录（只有在成功生成 HTML 后才创建）
            task_dir.mkdir(parents=True, exist_ok=True)
            log(f"创建任务目录: {task_dir}")
            
            # 如果用户上传了文件，且文件在临时目录中，移动到最终目录
            if input_file:
                input_path = Path(input_file)
                if input_path.exists():
                    # 检查是否在临时目录中（路径包含 "temp_"）
                    if "temp_" in str(input_path.parent):
                        # 移动到最终目录
                        final_file_path = task_dir / input_path.name
                        shutil.move(str(input_path), str(final_file_path))
                        log(f"文件已从临时目录移动到最终目录: {final_file_path}")
                        # 更新 input_file 路径
                        input_file = str(final_file_path)
                        
                        # 删除临时目录（如果为空）
                        try:
                            temp_dir = input_path.parent
                            if temp_dir.exists() and not any(temp_dir.iterdir()):
                                temp_dir.rmdir()
                                log(f"已删除空的临时目录: {temp_dir}")
                        except Exception as e:
                            log(f"删除临时目录失败（可忽略）: {e}", "WARN")
            
            # 1. 保存模板动态数据（优先）或完整 HTML（兜底）
            if teaching_data:
                data_path = task_dir / "teaching_data.json"
                # 原子写入 + 重试：并发场景（管理员保存标签等同时写文件）触发
                # Windows 文件锁（WinError 5 / Errno 13）时，瞬时锁重试即可恢复
                tmp_data_path = data_path.with_name(data_path.name + ".tmp")
                for _attempt in range(5):
                    try:
                        with open(tmp_data_path, "w", encoding="utf-8") as f:
                            json.dump(teaching_data, f, ensure_ascii=False, indent=2)
                        os.replace(tmp_data_path, data_path)
                        break
                    except OSError:
                        if _attempt == 4:
                            raise
                        time.sleep(0.5)
                log(f"教学动态数据已保存到: {data_path}")
            else:
                teaching_html_path = task_dir / "teaching.html"
                tmp_html_path = teaching_html_path.with_name(teaching_html_path.name + ".tmp")
                for _attempt in range(5):
                    try:
                        with open(tmp_html_path, "w", encoding="utf-8") as f:
                            f.write(teaching_html)
                        os.replace(tmp_html_path, teaching_html_path)
                        break
                    except OSError:
                        if _attempt == 4:
                            raise
                        time.sleep(0.5)
                log(f"教学 HTML 已保存到: {teaching_html_path}，文件大小: {len(teaching_html)} 字符")
            
            # 2. 保存元数据 JSON 文件
            metadata = {
                "question": question,
                "prompt": prompt,
                "plan": plan,
                "input_file": input_file,
                "task_id": task_dir.name,
                "generated_at": datetime.utcnow().isoformat() + "Z",
                "teaching_html_file": "teaching_data.json" if teaching_data else "teaching.html",
            }
            
            # 计算 has_pic
            has_pic_flag = False
            if analysis_result:
                has_pic_flag = bool(analysis_result.get("has_pic", False)) and input_file and self._is_image_file(input_file)
            
            # 添加题目分析结果（确保 title / tags 写入 metadata.json）
            if analysis_result:
                metadata["is_math_problem"] = analysis_result.get("is_math_problem", True)
                metadata["title"] = analysis_result.get("title")
                # W1 P0-3：标题质量打标随落库（约束校验重试后仍不通过 → low）
                if analysis_result.get("title_quality"):
                    metadata["title_quality"] = analysis_result.get("title_quality")
                metadata["has_pic"] = has_pic_flag
                if tags:
                    metadata["tags"] = tags
                    metadata["tags_updated_at"] = datetime.utcnow().isoformat() + "Z"
                if knowledge_tags:
                    metadata["knowledge_tags"] = knowledge_tags
                    metadata["second_tag"] = second_tag
                    metadata["needs_tag_selection"] = needs_tag_selection
                    metadata["knowledge_tags_updated_at"] = datetime.utcnow().isoformat() + "Z"
            else:
                metadata["has_pic"] = False
            
            metadata_path = task_dir / "metadata.json"
            # 合并写入而非全量覆写：预览图生成可能已先写入 preview_image，
            # 全量覆写会把它连同其他先写方的字段一起丢掉
            update_metadata(task_dir, metadata)
            log(f"元数据已保存到: {metadata_path}")
            
            # 输出保存的元数据详情
            log_detail(
                "保存教学内容 - 元数据详情",
                {
                    "元数据文件": str(metadata_path),
                    "元数据内容": json.dumps(metadata, ensure_ascii=False, indent=2),
                }
            )
            
            # 2.5. 保存到数据库
            task_id = task_dir.name
            try:
                db = SessionLocal()
                try:
                    # 检查是否已存在该 task_id 的记录
                    existing_teaching = db.query(Teaching).filter(Teaching.task_id == task_id).first()
                    
                    # 旧数据库列仅用于历史兼容，新业务标签以 knowledge_tags 为准
                    main_tag = knowledge_tags.get("main_tag") if knowledge_tags else None
                    sub_tags = knowledge_tags.get("sub_tags", []) if knowledge_tags else None
                    second_tag_value = second_tag if second_tag else None
                    # 解析生成时间
                    generated_at = datetime.now()
                    if metadata.get("generated_at"):
                        try:
                            generated_at = datetime.fromisoformat(metadata["generated_at"])
                        except:
                            pass
                    
                    # 优先使用 2.0 风格的新封面，兼容旧封面。
                    if (task_dir / "Preview.webp").exists():
                        preview_image = "Preview.webp"
                    elif (task_dir / "preview.webp").exists():
                        preview_image = "preview.webp"
                    else:
                        preview_image = None
                    
                    has_pic_flag = False
                    if analysis_result:
                        has_pic_flag = bool(analysis_result.get("has_pic", False))
                        if has_pic_flag and input_file and self._is_image_file(input_file):
                            has_pic_flag = True
                        else:
                            has_pic_flag = False
                    
                    if existing_teaching:
                        # 更新现有记录
                        existing_teaching.question = question
                        existing_teaching.prompt = prompt
                        existing_teaching.title = metadata.get("title")
                        existing_teaching.is_math_problem = metadata.get("is_math_problem", True)
                        existing_teaching.has_pic = has_pic_flag
                        existing_teaching.main_tag = main_tag
                        existing_teaching.sub_tags = sub_tags
                        existing_teaching.knowledge_tags = knowledge_tags
                        existing_teaching.second_tag = second_tag_value
                        existing_teaching.reasoning = tags.get("reasoning") if tags else None
                        existing_teaching.input_file = input_file
                        existing_teaching.teaching_html_file = "teaching_data.json" if teaching_data else "teaching.html"
                        existing_teaching.preview_image = preview_image
                        existing_teaching.generated_at = generated_at
                        if user_id and not existing_teaching.user_id:
                            existing_teaching.user_id = user_id
                        db.commit()
                        log(f"数据库记录已更新: task_id={task_id}")
                        
                        # 输出更新的数据库记录详情
                        log_detail(
                            "数据库保存 - 更新记录",
                            {
                                "任务ID": task_id,
                                "题目": question,
                                "标题": metadata.get("title"),
                                "知识域": knowledge_tags.get("version", "") if knowledge_tags else "",
                                "年级": knowledge_tags.get("grade", "") if knowledge_tags else "",
                                "章/单元": knowledge_tags.get("main_tag", "") if knowledge_tags else "",
                                "预览图": preview_image if preview_image else "未生成",
                                "用户ID": user_id if user_id else "匿名",
                                "包含图片": str(has_pic_flag),
                            }
                        )
                    else:
                        # 创建新记录
                        new_teaching = Teaching(
                            task_id=task_id,
                            user_id=user_id,
                            question=question,
                            prompt=prompt,
                            title=metadata.get("title"),
                            is_math_problem=metadata.get("is_math_problem", True),
                            has_pic=has_pic_flag,
                            main_tag=main_tag,
                            sub_tags=sub_tags,
                            knowledge_tags=knowledge_tags,
                            second_tag=second_tag_value,
                            reasoning=tags.get("reasoning") if tags else None,
                            generated_at=generated_at,
                            input_file=input_file,
                            teaching_html_file="teaching_data.json" if teaching_data else "teaching.html",
                            preview_image=preview_image
                        )
                        db.add(new_teaching)
                        db.commit()
                        log(f"数据库记录已创建: task_id={task_id}")
                        
                        # 输出创建的数据库记录详情
                        log_detail(
                            "数据库保存 - 创建记录",
                            {
                                "任务ID": task_id,
                                "题目": question,
                                "标题": metadata.get("title"),
                                "知识域": knowledge_tags.get("version", "") if knowledge_tags else "",
                                "年级": knowledge_tags.get("grade", "") if knowledge_tags else "",
                                "章/单元": knowledge_tags.get("main_tag", "") if knowledge_tags else "",
                                "预览图": preview_image if preview_image else "未生成",
                                "用户ID": user_id if user_id else "匿名",
                                "包含图片": str(has_pic_flag),
                            }
                        )
                except Exception as db_error:
                    db.rollback()
                    # 数据库保存失败不影响文件保存流程，只记录警告
                    log(f"保存到数据库失败（不影响文件保存）: {db_error}", "WARN")
                finally:
                    db.close()
            except Exception as db_init_error:
                # 数据库初始化失败（如连接失败），只记录警告
                log(f"数据库连接失败（不影响文件保存）: {db_init_error}", "WARN")
            
            # 3. 向量数据库同步已随 embedding 功能移除（2026-09-11）

            # 4. 预览图已在并行任务中生成，这里不需要再生成
            # 检查预览图是否已生成（只检查 WebP）
            preview_webp_path = task_dir / "Preview.webp"
            if preview_webp_path.exists():
                log(f"预览图已生成: {preview_webp_path}")
            else:
                log("预览图未生成（可能在并行任务中失败）", "WARN")
            
        except Exception as e:
            # 保存失败不影响主流程，只打印错误
            log(f"保存教学内容失败: {e}", "ERROR")

    async def _generate_preview_image(self, task_dir: Path, metadata: dict) -> None:
        """为任务生成预览图片。

        重试与退避已下沉到 generate_image_for_task 内部，由 deadline 统一约束，
        因此这里不再叠加一层重试循环。外层 wait_for 仅作兜底，其超时必须大于内层
        总预算——否则内层重试还没跑完就会被掐断，这正是历史上封面丢失的根因。
        """
        task_id = task_dir.name
        log(f"开始为任务 {task_id} 生成预览图片...")

        inner_budget = env_int("PREVIEW_TOTAL_TIMEOUT_SECONDS", 270)
        timeout_seconds = env_int("PREVIEW_TASK_TIMEOUT_SECONDS", 300)
        if timeout_seconds <= inner_budget:
            log(
                f"PREVIEW_TASK_TIMEOUT_SECONDS({timeout_seconds}) 未大于内层预算({inner_budget})，"
                f"自动调整为 {inner_budget + 30} 以免重试被掐断",
                "WARN",
            )
            timeout_seconds = inner_budget + 30

        # 备用模型预算已独立（切换时 deadline 重置），外层兜底必须把已配置备用模型
        # 的独立预算计入，否则备用模型刚开跑就会被这里掐断。
        backup_extra = preview_backup_extra_seconds()
        if backup_extra:
            timeout_seconds += backup_extra
            log(f"计入备用模型独立预算 {backup_extra} 秒，外层兜底调整为 {timeout_seconds} 秒")

        api_start = datetime.now()
        try:
            log(f"正在调用 GPTsAPI 生成预览图片（内层预算 {inner_budget} 秒，外层兜底 {timeout_seconds} 秒）...")

            await asyncio.wait_for(
                generate_image_for_task(task_dir, metadata, timeout_seconds=inner_budget),
                timeout=timeout_seconds,
            )

            api_elapsed = (datetime.now() - api_start).total_seconds()
            if not (task_dir / "Preview.webp").exists():
                raise RuntimeError("预览图片接口调用结束，但未生成 Preview.webp")
            log(f"预览图片生成完成（WebP格式），耗时: {api_elapsed:.2f} 秒")

            # 生成成功后写入数据库 preview_image 字段
            try:
                db = SessionLocal()
                teaching = db.query(Teaching).filter(Teaching.task_id == task_id).first()
                if teaching:
                    teaching.preview_image = "Preview.webp"
                    db.commit()
                    log(f"预览图记录已写入数据库: {task_id}/Preview.webp")
                db.close()
            except Exception as db_err:
                log(f"更新预览图到数据库失败: {db_err}", "WARN")

        except asyncio.TimeoutError:
            # 内层预算本应先于此处生效，走到这里说明配置异常。不影响主流程。
            api_elapsed = (datetime.now() - api_start).total_seconds()
            log(f"生成预览图片被外层兜底超时掐断（{timeout_seconds}秒），已耗时: {api_elapsed:.2f} 秒", "WARN")

        except Exception as e:
            api_elapsed = (datetime.now() - api_start).total_seconds()
            log(f"生成预览图片失败（已耗时: {api_elapsed:.2f} 秒）: {e}", "WARN")
            import traceback
            traceback.print_exc()
            # 错误不影响主流程，只记录警告


def _find_task_dir_image(task_dir: Path) -> str:
    """在任务目录内定位实际图片文件（xsyy-3 教训：has_pic 不可信，会漏 70%+ 图片题）.

    返回图片路径字符串；找不到返回 ""。排除 Preview*（封面，非原题图）。
    """
    try:
        for _pat in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
            _hits = [
                _p for _p in sorted(task_dir.glob(_pat))
                if not _p.name.startswith("Preview")
            ]
            if _hits:
                return str(_hits[0])
    except Exception:  # noqa: BLE001 —— 扫描失败按无图处理
        pass
    return ""


def _ref_prompt_note(content_profile: Optional[dict]) -> str:
    """T2（xsyy-3 阶段二）：参考图提示词按题型分流.

    几何/图形题（figure_info.has_figure 或 display_class=geometry）附的是
    原题插图——要求 scene_svg 精确复刻原图结构；场景题维持原话术
    （预览图仅作氛围参考、不得当装饰素材）。
    """
    fig = (content_profile or {}).get("figure_info") or {}
    is_figure = bool(fig.get("has_figure")) or (content_profile or {}).get("display_class") == "geometry"
    if is_figure:
        return (
            "\n\n已附上本题原题图片，图中是题目原始插图（几何图形/统计图/示意图）。"
            "scene_svg 必须忠实复刻原图的图形结构——点的位置、线段连接与交点、字母标注、"
            "边的比例关系、阴影/涂色区域都要与原图一致；不得改动画形、不得增删图形元素；"
            "图中数据以题面文字为准，画面保持简洁、突出图形关系。"
        )
    return (
        "\n\n已附上一张题目预览图。仅当图中确实存在与题意相关的火车、桥、圆、道路或其他物体时，"
        "才在 scene_svg 角落用简洁 SVG 复刻；不得把预览图当作装饰素材，也不得添加题意之外的图案。"
    )


def _render_parts_block(parts: list) -> str:
    """把复合多小题清单渲染为可读文本块（注入用户提示词的 __PARTS__ 占位）。

    非复合（parts 为空）返回 ""，调用方据此把 __PARTS__ 占位清空，避免残留令牌。
    """
    import re
    if not parts:
        return ""
    _lead = re.compile(r"^\s*[（(]?\s*\d{1,2}\s*[)）]?\s*[.、．]?\s*")
    lines = [
        f"【复合多小题】本题包含 {len(parts)} 个小题，请严格按下列顺序逐问作答；"
        f"steps 中每一步用「【第N问】」标注所属小题，每问独立给出完整解答：",
    ]
    for p in parts:
        label = p.get("label") or ""
        text = _lead.sub("", (p.get("text") or "").replace("\n", " ").strip())
        lines.append(f"{label} {text}")
    return "\n".join(lines)

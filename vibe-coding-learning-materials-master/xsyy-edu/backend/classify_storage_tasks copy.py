from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

# 加载 .env 文件
backend_dir = Path(__file__).resolve().parent
env_path = backend_dir / ".env"
load_dotenv(dotenv_path=env_path)

# Storage 目录路径
storage_dir = backend_dir.parent / "storage"

# 九个标准分类标签（必须严格匹配）
STANDARD_TAGS = {
    "模型意识",
    "数据意识",
    "空间观念",
    "几何直观",
    "符号意识",
    "量感",
    "数感",
    "推理意识",
    "运算能力"
}

# 九个标准分类标签（必须严格匹配）
STANDARD_TAGS = {
    "模型意识",
    "数据意识",
    "空间观念",
    "几何直观",
    "符号意识",
    "量感",
    "数感",
    "推理意识",
    "运算能力"
}


def log(message: str, level: str = "INFO"):
    """实时日志输出函数，带时间戳"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_message = f"[{timestamp}] [{level}] {message}"
    print(log_message, flush=True)
    sys.stdout.flush()


def load_prompt_template(file_path: Path) -> str:
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


def validate_tags(classification: dict) -> tuple[bool, str]:
    """验证分类结果中的标签是否在标准列表中。
    
    同时处理：如果"运算能力"出现在副标签中，则自动移除。
    
    返回：(是否有效, 错误信息)
    """
    if not classification:
        return False, "分类结果为空"
    
    main_tag = classification.get("main_tag", "")
    sub_tags = classification.get("sub_tags", [])
    
    # 验证主标签
    if not main_tag or main_tag not in STANDARD_TAGS:
        invalid_tags = [main_tag] if main_tag else ["空"]
        return False, f"主标签不在标准列表中: {invalid_tags}，标准列表: {sorted(STANDARD_TAGS)}"
    
    # 如果"运算能力"在副标签中，移除它（运算能力只能作为主标签）
    if "运算能力" in sub_tags:
        sub_tags = [tag for tag in sub_tags if tag != "运算能力"]
        classification["sub_tags"] = sub_tags
        log("已从副标签中移除'运算能力'（运算能力只能作为主标签）", "WARN")
    
    # 验证副标签
    invalid_sub_tags = [tag for tag in sub_tags if tag not in STANDARD_TAGS]
    if invalid_sub_tags:
        return False, f"副标签不在标准列表中: {invalid_sub_tags}，标准列表: {sorted(STANDARD_TAGS)}"
    
    return True, ""


def get_llm_classifier() -> ChatOpenAI:
    """获取或初始化分类器 LLM 实例（DeepSeek，延迟初始化）。"""
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError(
            "缺少环境变量 DEEPSEEK_API_KEY。"
            "请配置后再使用：setx DEEPSEEK_API_KEY \"你的密钥\""
        )

    # DeepSeek 提供 OpenAI 兼容接口
    llm = ChatOpenAI(
        model=os.getenv("DEEPSEEK_MODEL_NAME", "deepseek-chat"),
        api_key=api_key,
        base_url=os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com/v1"),
        temperature=0.3,
        max_retries=2,  # 最大重试次数
        timeout=180,  # 超时时间（秒）
    )
    return llm


def parse_classification_result(output: str) -> dict:
    """解析分类结果 JSON。
    
    返回格式：
    {
        "reasoning": "简短判定理由",
        "main_tag": "分类名",
        "sub_tags": ["分类名1", "分类名2"]
    }
    """
    # 尝试提取 JSON 部分
    # 可能包含 markdown 代码块包裹
    json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', output, re.DOTALL)
    if json_match:
        json_str = json_match.group(1)
    else:
        # 尝试直接查找 JSON 对象
        json_match = re.search(r'\{.*?"main_tag".*?"sub_tags".*?\}', output, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
        else:
            # 如果找不到，尝试使用整个输出
            json_str = output.strip()
    
    try:
        result = json.loads(json_str)
        # 验证必要字段
        if "main_tag" not in result:
            log(f"分类结果缺少 main_tag 字段: {result}", "WARN")
            return None
        
        # 确保格式正确
        classification = {
            "reasoning": result.get("reasoning", ""),
            "main_tag": result["main_tag"],
            "sub_tags": result.get("sub_tags", [])
        }
        
        # 验证 sub_tags 是列表
        if not isinstance(classification["sub_tags"], list):
            classification["sub_tags"] = []
        
        return classification
    except json.JSONDecodeError as e:
        log(f"解析分类结果 JSON 失败: {e}，原始输出: {output[:200]}...", "ERROR")
        return None


async def generate_title(question: str, llm: ChatOpenAI) -> str | None:
    """调用 DeepSeek API 为题目生成简短的标题。
    
    返回标题字符串，如果失败返回 None。
    """
    system_prompt = (
        "你是一位擅长为数学题起标题的专家。"
        "请根据给定的数学题目，生成一个简短、准确、易懂、专业的标题。"
        "标题要求："
        "1. 长度控制在10个汉字以内"
        "2. 用专业的术语准确概括题目的核心内容"
        "3. 直接输出标题，不要添加任何解释、引号或其他格式"
    )
    
    user_prompt = f"请为以下数学题生成一个简短的标题：\n\n{question}"
    
    log(f"调用 DeepSeek API 生成标题: {question[:80]}..." if len(question) > 80 else f"调用 DeepSeek API 生成标题: {question}")
    
    # 设置 API 调用超时（60秒，标题生成应该更快）
    timeout_seconds = int(os.getenv("DEEPSEEK_API_TIMEOUT", "60"))
    max_retries = 2
    
    api_start = datetime.now()
    
    for attempt in range(max_retries + 1):
        try:
            log(f"DeepSeek API 调用尝试 {attempt + 1}/{max_retries + 1}...")
            
            # 使用 asyncio.wait_for 设置超时
            resp = await asyncio.wait_for(
                llm.ainvoke(
                    [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ]
                ),
                timeout=timeout_seconds
            )
            
            api_elapsed = (datetime.now() - api_start).total_seconds()
            output = resp.content if hasattr(resp, "content") else str(resp)
            
            # 清理输出：移除可能的引号、换行等
            title = output.strip()
            # 移除首尾的引号
            if title.startswith('"') and title.endswith('"'):
                title = title[1:-1]
            if title.startswith("'") and title.endswith("'"):
                title = title[1:-1]
            # 移除可能的"标题："前缀
            title = re.sub(r'^标题[：:]\s*', '', title)
            # 只取第一行（如果有换行）
            title = title.split('\n')[0].strip()
            
            if title and len(title) > 0:
                log(f"DeepSeek API 调用成功，耗时: {api_elapsed:.2f} 秒，生成标题: {title}")
                return title
            else:
                log(f"生成的标题为空，原始输出: {output[:200]}...", "WARN")
                if attempt < max_retries:
                    log("正在重试...", "WARN")
                    await asyncio.sleep(2)
                    api_start = datetime.now()
                    continue
                else:
                    return None
                
        except asyncio.TimeoutError:
            api_elapsed = (datetime.now() - api_start).total_seconds()
            if attempt < max_retries:
                log(f"DeepSeek API 调用超时（{timeout_seconds}秒），已耗时: {api_elapsed:.2f} 秒，正在重试...", "WARN")
                await asyncio.sleep(2)
                api_start = datetime.now()
            else:
                log(f"DeepSeek API 调用超时（{timeout_seconds}秒），已重试 {max_retries} 次，最终失败", "ERROR")
                return None
                
        except Exception as e:
            api_elapsed = (datetime.now() - api_start).total_seconds()
            if attempt < max_retries:
                log(f"DeepSeek API 调用出错（已耗时: {api_elapsed:.2f} 秒）: {str(e)}，正在重试...", "WARN")
                await asyncio.sleep(2)
                api_start = datetime.now()
            else:
                log(f"DeepSeek API 调用失败，已重试 {max_retries} 次，最终错误: {str(e)}", "ERROR")
                return None
    
    return None


async def classify_question(question: str, llm: ChatOpenAI, max_validation_retries: int = 3) -> dict | None:
    """调用 DeepSeek API 对题目进行分类。
    
    包含后处理兜底策略：如果输出的标签不在标准列表中，则重新调用模型。
    
    Args:
        question: 题目内容
        llm: LLM 实例
        max_validation_retries: 最大验证重试次数（默认3次）
    
    返回分类结果字典，如果失败返回 None。
    """
    # 加载 prompt 模板
    backend_dir = Path(__file__).resolve().parent
    system_prompt_path = backend_dir / "classification_system_prompt.txt"
    user_prompt_path = backend_dir / "classification_user_prompt.txt"
    
    system_prompt = load_prompt_template(system_prompt_path)
    user_prompt_template = load_prompt_template(user_prompt_path)
    
    # 如果模板文件不存在，使用默认 prompt
    if not system_prompt:
        system_prompt = (
            "你是一名资深的小学/初中数学题目分类专家。"
            "你的任务是根据给定的数学题，依据分类标准打上唯一的主标签和0-3个副标签。"
            "输出格式必须为标准JSON，不包含任何多余解释。"
            f"标签必须严格从以下九个标准分类中选择：{', '.join(sorted(STANDARD_TAGS))}。"
            "不允许使用任何其他标签名称。"
        )
    
    if not user_prompt_template:
        user_prompt_base = question
    else:
        # 替换模板中的占位符
        user_prompt_base = user_prompt_template.replace("__USER_INPUT__", question)
    
    log(f"调用 DeepSeek API 分类题目: {question[:80]}..." if len(question) > 80 else f"调用 DeepSeek API 分类题目: {question}")
    
    # 设置 API 调用超时（120秒）
    timeout_seconds = int(os.getenv("DEEPSEEK_API_TIMEOUT", "120"))
    max_api_retries = 2
    
    # 验证重试循环（处理标签不在标准列表中的情况）
    for validation_attempt in range(max_validation_retries):
        if validation_attempt > 0:
            log(f"标签验证失败，重新调用模型（验证重试 {validation_attempt}/{max_validation_retries - 1}）...", "WARN")
            # 在重试时，在用户提示词中强调标准标签
            user_prompt = f"{user_prompt_base}\n\n请确保主标签和副标签都严格从以下标准列表中选择：{', '.join(sorted(STANDARD_TAGS))}。"
        else:
            user_prompt = user_prompt_base
        
        api_start = datetime.now()
        
        # API 调用重试循环（处理网络错误、超时等）
        for api_attempt in range(max_api_retries + 1):
            try:
                log(f"DeepSeek API 调用尝试 {api_attempt + 1}/{max_api_retries + 1}...")
                
                # 使用 asyncio.wait_for 设置超时
                resp = await asyncio.wait_for(
                    llm.ainvoke(
                        [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ]
                    ),
                    timeout=timeout_seconds
                )
                
                api_elapsed = (datetime.now() - api_start).total_seconds()
                output = resp.content if hasattr(resp, "content") else str(resp)
                log(f"DeepSeek API 调用成功，耗时: {api_elapsed:.2f} 秒，输出长度: {len(output)} 字符")
                
                # 解析分类结果
                classification = parse_classification_result(output)
                if not classification:
                    log(f"分类结果解析失败，原始输出: {output[:200]}...", "WARN")
                    if api_attempt < max_api_retries:
                        log("正在重试 API 调用...", "WARN")
                        await asyncio.sleep(2)
                        api_start = datetime.now()
                        continue
                    else:
                        # API 调用失败，进入验证重试
                        break
                
                # 验证标签是否在标准列表中
                is_valid, error_msg = validate_tags(classification)
                if is_valid:
                    log(f"分类结果验证通过: 主标签={classification['main_tag']}, 副标签={classification['sub_tags']}")
                    return classification
                else:
                    log(f"分类结果验证失败: {error_msg}", "WARN")
                    log(f"当前分类结果: 主标签={classification.get('main_tag')}, 副标签={classification.get('sub_tags')}", "WARN")
                    # 标签不在标准列表中，进入验证重试
                    break
                    
            except asyncio.TimeoutError:
                api_elapsed = (datetime.now() - api_start).total_seconds()
                if api_attempt < max_api_retries:
                    log(f"DeepSeek API 调用超时（{timeout_seconds}秒），已耗时: {api_elapsed:.2f} 秒，正在重试...", "WARN")
                    await asyncio.sleep(2)
                    api_start = datetime.now()
                else:
                    log(f"DeepSeek API 调用超时（{timeout_seconds}秒），已重试 {max_api_retries} 次，最终失败", "ERROR")
                    return None
                    
            except Exception as e:
                api_elapsed = (datetime.now() - api_start).total_seconds()
                if api_attempt < max_api_retries:
                    log(f"DeepSeek API 调用出错（已耗时: {api_elapsed:.2f} 秒）: {str(e)}，正在重试...", "WARN")
                    await asyncio.sleep(2)
                    api_start = datetime.now()
                else:
                    log(f"DeepSeek API 调用失败，已重试 {max_api_retries} 次，最终错误: {str(e)}", "ERROR")
                    return None
        
        # 如果验证重试次数未用完，等待后继续
        if validation_attempt < max_validation_retries - 1:
            await asyncio.sleep(2)
    
    # 所有验证重试都失败
    log(f"标签验证失败，已重试 {max_validation_retries} 次，最终失败", "ERROR")
    return None


async def process_task(task_dir: Path, llm: ChatOpenAI, force_update: bool = False) -> bool:
    """处理单个任务：读取 metadata.json，分类题目，更新标签。
    
    返回：是否成功处理
    """
    task_id = task_dir.name
    metadata_path = task_dir / "metadata.json"
    
    if not metadata_path.exists():
        log(f"任务 {task_id}: metadata.json 不存在，跳过", "WARN")
        return False
    
    try:
        # 读取 metadata.json
        with open(metadata_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)
        
        # 检查是否已有标签和标题且不需要强制更新
        has_tags = "tags" in metadata and metadata["tags"]
        has_title = "title" in metadata and metadata.get("title", "").strip()
        
        if not force_update and has_tags and has_title:
            log(f"任务 {task_id}: 已有标签和标题，跳过（使用 --force 强制更新）")
            return True
        
        # 提取题目
        question = metadata.get("question", "")
        if not question:
            log(f"任务 {task_id}: metadata.json 中没有 question 字段，跳过", "WARN")
            return False
        
        # 生成标题（如果还没有或需要强制更新）
        if not has_title or force_update:
            log(f"任务 {task_id}: 开始生成标题...")
            title = await generate_title(question, llm)
            if title:
                metadata["title"] = title
                log(f"任务 {task_id}: 标题已生成: {title}")
            else:
                log(f"任务 {task_id}: 标题生成失败", "WARN")
                # 标题生成失败不影响继续处理，使用题目前30字作为默认标题
                if not has_title:
                    metadata["title"] = question[:30] + ("..." if len(question) > 30 else "")
                    log(f"任务 {task_id}: 使用默认标题: {metadata['title']}")
        else:
            log(f"任务 {task_id}: 已有标题，跳过生成")
        
        # 分类题目（如果还没有标签或需要强制更新）
        if not has_tags or force_update:
            log(f"任务 {task_id}: 开始分类题目...")
            classification = await classify_question(question, llm)
            
            if classification:
                metadata["tags"] = classification
                log(f"任务 {task_id}: 标签已更新，主标签={classification['main_tag']}, 副标签={classification['sub_tags']}")
            else:
                log(f"任务 {task_id}: 分类失败", "WARN")
                # 分类失败不影响保存标题
        else:
            log(f"任务 {task_id}: 已有标签，跳过分类")
        
        # 保存更新后的 metadata.json
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        
        log(f"任务 {task_id}: metadata.json 已更新")
        return True
        
    except Exception as e:
        log(f"任务 {task_id}: 处理失败: {str(e)}", "ERROR")
        import traceback
        traceback.print_exc()
        return False


async def main(force_update: bool = False):
    """主函数：遍历 storage 目录，为每个任务添加分类标签。"""
    log("=" * 60)
    log("开始为 storage 中的任务添加分类标签")
    log("=" * 60)
    
    if not storage_dir.exists():
        log(f"Storage 目录不存在: {storage_dir}", "ERROR")
        return
    
    # 初始化 LLM
    try:
        llm = get_llm_classifier()
        log("DeepSeek LLM 初始化成功")
    except Exception as e:
        log(f"初始化 LLM 失败: {str(e)}", "ERROR")
        return
    
    # 获取所有任务目录
    task_dirs = [d for d in storage_dir.iterdir() if d.is_dir()]
    total_tasks = len(task_dirs)
    
    log(f"找到 {total_tasks} 个任务目录")
    
    if total_tasks == 0:
        log("没有找到任何任务目录", "WARN")
        return
    
    # 处理每个任务
    success_count = 0
    skip_count = 0
    fail_count = 0
    
    for i, task_dir in enumerate(task_dirs, 1):
        log(f"\n[{i}/{total_tasks}] 处理任务: {task_dir.name}")
        
        result = await process_task(task_dir, llm, force_update)
        
        if result:
            success_count += 1
        else:
            # 检查是否是因为已有标签和标题而跳过
            metadata_path = task_dir / "metadata.json"
            if metadata_path.exists():
                try:
                    with open(metadata_path, "r", encoding="utf-8") as f:
                        metadata = json.load(f)
                    has_tags = "tags" in metadata and metadata.get("tags")
                    has_title = "title" in metadata and metadata.get("title", "").strip()
                    if has_tags and has_title and not force_update:
                        skip_count += 1
                        continue
                except:
                    pass
            fail_count += 1
        
        # 添加短暂延迟，避免 API 调用过于频繁
        if i < total_tasks:
            await asyncio.sleep(1)
    
    # 输出统计信息
    log("\n" + "=" * 60)
    log("处理完成！")
    log(f"总计: {total_tasks} 个任务")
    log(f"成功: {success_count} 个")
    log(f"跳过: {skip_count} 个（已有标签）")
    log(f"失败: {fail_count} 个")
    log("=" * 60)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="为 storage 中的任务添加分类标签")
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制更新已有标签的任务"
    )
    
    args = parser.parse_args()
    
    asyncio.run(main(force_update=args.force))


"""规范 storage 下所有 metadata.json 的标签格式（批量脚本）。

主要工作：
1. 移除旧字段 is_math_question，统一为 is_math_problem
2. 将 knowledge_tags 规范为单标签组对象
3. 清理旧 tags 字段中残留的标签键，仅保留 reasoning

用法：cd backend && python utils/update_metadata_format.py
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

backend_dir = Path(__file__).resolve().parent
storage_dir = backend_dir.parent / "storage"


def log(message: str, level: str = "INFO") -> None:
    """带时间戳的日志输出。"""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [{level}] {message}", flush=True)


def update_metadata_format(metadata: dict) -> bool:
    """规范化单条 metadata 的标签相关字段。

    处理内容：
    1. 移除旧字段 is_math_question
    2. 设置 is_math_problem = True（存量数据假设均为数学题）
    3. 将 knowledge_tags 规范为单标签组对象，避免旧 tags 覆盖新标签对象

    返回：是否有更新
    """
    updated = False
    
    # 1. 移除旧的 is_math_question 字段（如果存在）
    if "is_math_question" in metadata:
        metadata.pop("is_math_question")
        updated = True
        log("  更新: 移除 is_math_question 字段")
    
    # 2. 添加或更新 is_math_problem 字段为 True
    if "is_math_problem" not in metadata or metadata["is_math_problem"] is not True:
        metadata["is_math_problem"] = True
        updated = True
        log("  更新: 设置 is_math_problem = True")
    
    # 3. 规范 knowledge_tags 单标签组结构
    knowledge_tags = metadata.get("knowledge_tags")
    if isinstance(knowledge_tags, list):
        knowledge_tags = knowledge_tags[0] if knowledge_tags else None
        metadata["knowledge_tags"] = knowledge_tags
        updated = True
        log("  更新: 将 knowledge_tags 统一为单标签组对象")

    if isinstance(knowledge_tags, dict):
        normalized = {
            "version": knowledge_tags.get("version", ""),
            "grade": knowledge_tags.get("grade", ""),
            "main_tag": knowledge_tags.get("main_tag", ""),
            "sub_tags": knowledge_tags.get("sub_tags", []) if isinstance(knowledge_tags.get("sub_tags", []), list) else [],
        }
        if normalized != knowledge_tags:
            metadata["knowledge_tags"] = normalized
            updated = True
            log("  更新: 规范 knowledge_tags 字段")

    # 旧 tags 只保留题目分析理由，不再补写 main_tag/sub_tags
    tags = metadata.get("tags")
    if isinstance(tags, dict) and ("main_tag" in tags or "sub_tags" in tags):
        cleaned_tags = {"reasoning": tags.get("reasoning", "")}
        if cleaned_tags != tags:
            metadata["tags"] = cleaned_tags
            updated = True
            log("  更新: 清理旧 tags 中的标签字段")
    elif tags is not None and not isinstance(tags, dict):
        metadata["tags"] = {"reasoning": ""}
        updated = True
        log("  更新: 修正 tags 为兼容对象")

    return updated


def process_metadata_file(metadata_path: Path) -> bool:
    """处理单个 metadata.json 文件。
    
    返回：是否成功更新
    """
    task_id = metadata_path.parent.name
    
    try:
        # 读取 metadata.json
        with open(metadata_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)
        
        # 更新格式
        updated = update_metadata_format(metadata)
        
        if updated:
            # 保存更新后的 metadata.json
            with open(metadata_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
            log(f"任务 {task_id}: metadata.json 已更新")
            return True
        else:
            log(f"任务 {task_id}: 格式已是最新，无需更新")
            return False
        
    except json.JSONDecodeError as e:
        log(f"任务 {task_id}: JSON 解析失败: {e}", "ERROR")
        return False
    except Exception as e:
        log(f"任务 {task_id}: 处理失败: {str(e)}", "ERROR")
        import traceback
        traceback.print_exc()
        return False


def main():
    """主函数：遍历 storage 目录，更新所有 metadata.json 文件。"""
    log("=" * 60)
    log("开始更新 storage 中的 metadata.json 格式")
    log("=" * 60)
    
    if not storage_dir.exists():
        log(f"Storage 目录不存在: {storage_dir}", "ERROR")
        return
    
    # 获取所有任务目录
    task_dirs = [d for d in storage_dir.iterdir() if d.is_dir()]
    total_tasks = len(task_dirs)
    
    log(f"找到 {total_tasks} 个任务目录")
    
    if total_tasks == 0:
        log("没有找到任何任务目录", "WARN")
        return
    
    # 处理每个任务
    updated_count = 0
    skipped_count = 0
    error_count = 0
    
    for i, task_dir in enumerate(task_dirs, 1):
        task_id = task_dir.name
        metadata_path = task_dir / "metadata.json"
        
        log(f"\n[{i}/{total_tasks}] 处理任务: {task_id}")
        
        if not metadata_path.exists():
            log(f"任务 {task_id}: metadata.json 不存在，跳过", "WARN")
            skipped_count += 1
            continue
        
        result = process_metadata_file(metadata_path)
        
        if result:
            updated_count += 1
        else:
            skipped_count += 1
    
    # 输出统计信息
    log("\n" + "=" * 60)
    log("更新完成！")
    log(f"总计: {total_tasks} 个任务")
    log(f"已更新: {updated_count} 个")
    log(f"无需更新: {skipped_count} 个")
    log(f"错误: {error_count} 个")
    log("=" * 60)


if __name__ == "__main__":
    main()


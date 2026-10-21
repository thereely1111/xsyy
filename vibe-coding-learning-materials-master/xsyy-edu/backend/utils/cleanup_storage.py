from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

# Storage 目录路径
backend_dir = Path(__file__).resolve().parent
storage_dir = backend_dir.parent / "storage"


def log(message: str, level: str = "INFO"):
    """实时日志输出函数，带时间戳"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_message = f"[{timestamp}] [{level}] {message}"
    print(log_message, flush=True)
    sys.stdout.flush()


def is_valid_teaching_folder(task_dir: Path) -> tuple[bool, str]:
    """检查任务文件夹是否完整。
    
    返回：(是否有效, 原因)
    
    有效文件夹必须包含：
    - teaching.html: 教学 HTML 文件
    - metadata.json: 元数据文件
    
    可选文件：
    - preview.png: 预览图片
    - text-input.txt 或其他输入文件
    
    如果文件夹只有输入文件（如 text-input.txt）而没有 teaching.html 和 metadata.json，
    则认为是脏数据。
    """
    if not task_dir.is_dir():
        return False, "不是目录"
    
    files = list(task_dir.iterdir())
    file_names = [f.name for f in files if f.is_file()]
    
    # 检查必需文件
    has_teaching_html = "teaching.html" in file_names
    has_metadata = "metadata.json" in file_names
    
    # 检查是否有输入文件（如 text-input.txt）
    input_files = [f for f in file_names if f.endswith(('.txt', '.jpg', '.jpeg', '.png', '.pdf')) 
                   and f not in ('teaching.html', 'preview.png')]
    
    # 如果只有输入文件，没有 teaching.html 和 metadata.json，则是脏数据
    if not has_teaching_html and not has_metadata:
        if input_files:
            return False, f"只有输入文件 {input_files}，缺少 teaching.html 和 metadata.json"
        else:
            return False, "文件夹为空或只包含非标准文件"
    
    # 如果只有 metadata.json 但没有 teaching.html，也是不完整的
    if has_metadata and not has_teaching_html:
        return False, "有 metadata.json 但缺少 teaching.html"
    
    # 如果只有 teaching.html 但没有 metadata.json，也是不完整的
    if has_teaching_html and not has_metadata:
        return False, "有 teaching.html 但缺少 metadata.json"
    
    # 两个必需文件都存在，认为是有效的
    return True, "结构完整"


def cleanup_storage(dry_run: bool = False) -> None:
    """清理 storage 目录中的脏数据。
    
    Args:
        dry_run: 如果为 True，只显示将要删除的文件夹，不实际删除
    """
    log("=" * 60)
    log(f"开始清理 storage 目录{'（模拟模式，不会实际删除）' if dry_run else ''}")
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
    
    # 检查每个任务目录
    valid_count = 0
    invalid_count = 0
    deleted_count = 0
    text_input_deleted_count = 0
    
    for i, task_dir in enumerate(task_dirs, 1):
        task_id = task_dir.name
        log(f"\n[{i}/{total_tasks}] 检查任务: {task_id}")
        
        # 先删除 text-input.txt 文件（如果存在）
        text_input_path = task_dir / "text-input.txt"
        if text_input_path.exists():
            if dry_run:
                log(f"  [模拟] 将删除: {text_input_path}", "DRY_RUN")
            else:
                try:
                    text_input_path.unlink()
                    text_input_deleted_count += 1
                    log(f"  ✓ 已删除 text-input.txt", "DELETE")
                except Exception as e:
                    log(f"  ✗ 删除 text-input.txt 失败: {str(e)}", "ERROR")
        
        is_valid, reason = is_valid_teaching_folder(task_dir)
        
        if is_valid:
            valid_count += 1
            log(f"  ✓ 有效: {reason}")
        else:
            invalid_count += 1
            log(f"  ✗ 无效: {reason}", "WARN")
            
            if dry_run:
                log(f"  [模拟] 将删除: {task_dir}", "DRY_RUN")
            else:
                try:
                    shutil.rmtree(task_dir)
                    deleted_count += 1
                    log(f"  ✓ 已删除: {task_dir}", "DELETE")
                except Exception as e:
                    log(f"  ✗ 删除失败: {str(e)}", "ERROR")
    
    # 输出统计信息
    log("\n" + "=" * 60)
    log("清理完成！")
    log(f"总计: {total_tasks} 个任务目录")
    log(f"有效: {valid_count} 个")
    log(f"无效: {invalid_count} 个")
    if dry_run:
        log(f"[模拟] 将删除文件夹: {invalid_count} 个")
    else:
        log(f"已删除文件夹: {deleted_count} 个")
    log(f"已删除 text-input.txt 文件: {text_input_deleted_count} 个")
    log("=" * 60)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="清理 storage 目录中的脏数据")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="模拟模式：只显示将要删除的文件夹，不实际删除"
    )
    
    args = parser.parse_args()
    
    cleanup_storage(dry_run=args.dry_run)


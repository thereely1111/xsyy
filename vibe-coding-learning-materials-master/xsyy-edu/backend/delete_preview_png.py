#!/usr/bin/env python3
"""
删除 storage 目录下所有的 preview.png 文件
只保留 preview.webp 文件
"""

import sys
from pathlib import Path
from datetime import datetime

# 添加 backend 目录到路径
backend_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(backend_dir))

# Storage 目录
storage_dir = backend_dir.parent / "storage"


def log(message: str, level: str = "INFO"):
    """实时日志输出函数，带时间戳"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_message = f"[{timestamp}] [{level}] {message}"
    print(log_message, flush=True)


def delete_all_preview_png():
    """删除 storage 目录下所有的 preview.png 文件"""
    if not storage_dir.exists():
        log(f"Storage 目录不存在: {storage_dir}", "ERROR")
        return False
    
    # 查找所有 preview.png 文件
    preview_png_files = list(storage_dir.rglob("preview.png"))
    
    if not preview_png_files:
        log("未找到任何 preview.png 文件", "INFO")
        return True
    
    log(f"找到 {len(preview_png_files)} 个 preview.png 文件")
    log("=" * 60)
    
    deleted_count = 0
    failed_count = 0
    
    for i, png_path in enumerate(preview_png_files, 1):
        task_id = png_path.parent.name
        try:
            # 检查对应的 WebP 文件是否存在
            webp_path = png_path.parent / "preview.webp"
            if webp_path.exists():
                # 如果 WebP 存在，删除 PNG
                png_path.unlink()
                deleted_count += 1
                log(f"[{i}/{len(preview_png_files)}] {task_id}: 已删除 preview.png（存在 preview.webp）", "INFO")
            else:
                # 如果 WebP 不存在，警告但不删除（可能需要先转换）
                log(f"[{i}/{len(preview_png_files)}] {task_id}: 跳过（不存在 preview.webp，请先转换）", "WARN")
        except Exception as e:
            failed_count += 1
            log(f"[{i}/{len(preview_png_files)}] {task_id}: 删除失败 - {e}", "ERROR")
    
    log("=" * 60)
    log(f"删除完成！")
    log(f"  已删除: {deleted_count} 个文件")
    log(f"  跳过: {len(preview_png_files) - deleted_count - failed_count} 个文件（无对应 WebP）")
    log(f"  失败: {failed_count} 个文件")
    log("=" * 60)
    
    return failed_count == 0


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="删除 storage 目录下所有的 preview.png 文件")
    parser.add_argument("-y", "--yes", action="store_true", help="跳过确认提示，直接执行删除")
    args = parser.parse_args()
    
    log("=" * 60)
    log("删除 preview.png 文件工具")
    log("将删除 storage 目录下所有 preview.png 文件（仅当存在对应 preview.webp 时）")
    log("=" * 60)
    print()
    
    if not args.yes:
        confirm = input("此操作将删除所有 preview.png 文件，是否继续？(y/N): ").strip().lower()
        if confirm != 'y':
            log("操作已取消。", "INFO")
            sys.exit(0)
    
    success = delete_all_preview_png()
    sys.exit(0 if success else 1)


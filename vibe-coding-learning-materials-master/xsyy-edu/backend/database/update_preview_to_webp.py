#!/usr/bin/env python3
"""
将数据库中所有 preview_image 字段从 preview.png 更新为 preview.webp
前提是对应的 preview.webp 文件存在
"""

import sys
from pathlib import Path

# 添加 backend 目录到路径
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from database import SessionLocal, Teaching
from sqlalchemy import update

# Storage 目录
storage_dir = backend_dir.parent / "storage"

def update_preview_image_to_webp():
    """更新数据库中所有 preview_image 字段为 preview.webp（如果文件存在）"""
    db = SessionLocal()
    
    try:
        # 获取所有有 preview_image 的记录
        teachings = db.query(Teaching).filter(Teaching.preview_image.isnot(None)).all()
        
        print(f"找到 {len(teachings)} 条有预览图的记录")
        print("=" * 60)
        
        updated_count = 0
        skipped_count = 0
        not_found_count = 0
        
        for i, teaching in enumerate(teachings, 1):
            task_id = teaching.task_id
            current_preview = teaching.preview_image
            
            # 检查对应的任务目录
            task_dir = storage_dir / task_id
            if not task_dir.exists():
                print(f"[{i}/{len(teachings)}] {task_id}: 任务目录不存在，跳过")
                not_found_count += 1
                continue
            
            # 检查 preview.webp 是否存在
            preview_webp_path = task_dir / "preview.webp"
            preview_png_path = task_dir / "preview.png"
            
            if preview_webp_path.exists():
                # WebP 文件存在，更新数据库
                if current_preview != "preview.webp":
                    teaching.preview_image = "preview.webp"
                    updated_count += 1
                    print(f"[{i}/{len(teachings)}] {task_id}: {current_preview} → preview.webp ✓")
                else:
                    skipped_count += 1
                    print(f"[{i}/{len(teachings)}] {task_id}: 已经是 preview.webp，跳过")
            elif preview_png_path.exists():
                # 只有 PNG 文件，也更新为 preview.webp（文件后续会转换）
                if current_preview != "preview.webp":
                    teaching.preview_image = "preview.webp"
                    updated_count += 1
                    print(f"[{i}/{len(teachings)}] {task_id}: {current_preview} → preview.webp (有PNG文件，待转换)")
                else:
                    skipped_count += 1
                    print(f"[{i}/{len(teachings)}] {task_id}: 已经是 preview.webp（有PNG文件，待转换）")
            else:
                # 两个文件都不存在
                not_found_count += 1
                print(f"[{i}/{len(teachings)}] {task_id}: 预览图文件不存在，跳过")
        
        # 提交更改
        if updated_count > 0:
            db.commit()
            print()
            print("=" * 60)
            print("更新完成！")
            print(f"  已更新: {updated_count} 条记录")
            print(f"  已跳过: {skipped_count} 条记录")
            print(f"  文件不存在: {not_found_count} 条记录")
            print("=" * 60)
        else:
            print()
            print("=" * 60)
            print("无需更新，所有记录都已是最新状态")
            print("=" * 60)
            
    except Exception as e:
        db.rollback()
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()

if __name__ == "__main__":
    print("=" * 60)
    print("预览图字段迁移工具")
    print("将 preview_image 字段更新为 preview.webp（如果文件存在）")
    print("=" * 60)
    print()
    
    update_preview_image_to_webp()


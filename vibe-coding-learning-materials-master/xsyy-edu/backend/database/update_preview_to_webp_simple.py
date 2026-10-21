#!/usr/bin/env python3
"""
直接将数据库中所有 preview_image 字段更新为 preview.webp
不检查文件是否存在（适用于先更新数据库，后转换文件的场景）
"""

import sys
from pathlib import Path

# 添加 backend 目录到路径
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from database import SessionLocal, Teaching

def update_all_preview_to_webp():
    """直接将所有 preview_image 字段更新为 preview.webp"""
    db = SessionLocal()
    
    try:
        # 获取所有有 preview_image 的记录
        teachings = db.query(Teaching).filter(Teaching.preview_image.isnot(None)).all()
        
        print(f"找到 {len(teachings)} 条有预览图的记录")
        print("=" * 60)
        
        updated_count = 0
        skipped_count = 0
        
        for i, teaching in enumerate(teachings, 1):
            task_id = teaching.task_id
            current_preview = teaching.preview_image
            
            if current_preview != "preview.webp":
                teaching.preview_image = "preview.webp"
                updated_count += 1
                print(f"[{i}/{len(teachings)}] {task_id}: {current_preview} → preview.webp ✓")
            else:
                skipped_count += 1
                print(f"[{i}/{len(teachings)}] {task_id}: 已经是 preview.webp，跳过")
        
        # 提交更改
        if updated_count > 0:
            db.commit()
            print()
            print("=" * 60)
            print("更新完成！")
            print(f"  已更新: {updated_count} 条记录")
            print(f"  已跳过: {skipped_count} 条记录")
            print("=" * 60)
            print()
            print("注意：请确保后续将 preview.png 文件转换为 preview.webp")
        else:
            print()
            print("=" * 60)
            print("无需更新，所有记录都已经是 preview.webp")
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
    import argparse
    
    parser = argparse.ArgumentParser(description="批量更新 preview_image 字段为 preview.webp")
    parser.add_argument("-y", "--yes", action="store_true", help="跳过确认，直接执行")
    args = parser.parse_args()
    
    print("=" * 60)
    print("预览图字段批量更新工具（简化版）")
    print("直接将所有 preview_image 字段更新为 preview.webp")
    print("=" * 60)
    print()
    
    # 确认操作（除非使用 -y 参数）
    if not args.yes:
        response = input("确定要将所有 preview_image 字段更新为 preview.webp 吗？(y/n): ")
        if response.lower() != 'y':
            print("操作已取消")
            sys.exit(0)
        print()
    
    update_all_preview_to_webp()


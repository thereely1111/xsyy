"""
数据迁移脚本：将现有题目的 embedding 同步到 Chroma 向量数据库

使用方法：
    python migrate_to_chroma.py

功能：
    1. 从 MySQL 数据库读取所有题目
    2. 为每个题目计算 embedding（如果还没有）
    3. 将 embedding 添加到 Chroma 向量数据库
    4. 显示进度和统计信息
"""

import os
import sys
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple
from dotenv import load_dotenv

# 加载环境变量
backend_dir = Path(__file__).resolve().parent
env_path = backend_dir / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)

# 导入数据库相关模块
from database import SessionLocal, Teaching
from sqlalchemy.orm import Session

# 导入 embedding 和向量数据库模块
from utils.embedding_utils import get_question_embedding
from utils.vector_db import (
    add_teaching_embedding,
    get_teaching_embedding,
    count_teachings
)


def get_all_teachings(db: Session) -> List[Teaching]:
    """获取所有有题目的教学内容"""
    teachings = db.query(Teaching).filter(
        Teaching.question.isnot(None),
        Teaching.question != ""
    ).all()
    return teachings


def migrate_teaching_to_chroma(
    teaching: Teaching,
    force_update: bool = False
) -> Tuple[bool, Optional[str]]:
    """
    将单个题目的 embedding 迁移到 Chroma
    
    Args:
        teaching: 教学内容对象
        force_update: 是否强制更新（即使已存在）
        
    Returns:
        (是否成功, 错误信息)
    """
    try:
        # 检查是否已存在
        existing_embedding = get_teaching_embedding(teaching.task_id)
        if existing_embedding is not None and len(existing_embedding) > 0 and not force_update:
            return (True, None)  # 已存在，跳过
        
        # 计算 embedding
        embedding = get_question_embedding(teaching.question)
        if embedding is None or len(embedding) == 0:
            return (False, "计算 embedding 失败")
        
        # 准备元数据
        metadata = {}
        if teaching.title:
            metadata["title"] = teaching.title
        if teaching.main_tag:
            metadata["main_tag"] = teaching.main_tag
        if teaching.sub_tags:
            metadata["sub_tags"] = teaching.sub_tags
        
        # 添加到向量数据库
        success = add_teaching_embedding(
            task_id=teaching.task_id,
            question=teaching.question,
            embedding=embedding,
            metadata=metadata if metadata else None
        )
        
        if success:
            return (True, None)
        else:
            return (False, "添加到向量数据库失败")
            
    except Exception as e:
        return (False, str(e))


def main():
    """主函数"""
    print("=" * 60)
    print("开始迁移数据到 Chroma 向量数据库")
    print("=" * 60)
    
    # 检查向量数据库中的现有数据
    existing_count = count_teachings()
    print(f"\n向量数据库中现有题目数量: {existing_count}")
    
    # 从 MySQL 获取所有题目
    print("\n正在从 MySQL 数据库读取题目...")
    db = SessionLocal()
    try:
        teachings = get_all_teachings(db)
        total_count = len(teachings)
        print(f"MySQL 数据库中共有 {total_count} 个题目")
        
        if total_count == 0:
            print("没有需要迁移的题目")
            return
        
        # 询问是否强制更新
        force_update = False
        if existing_count > 0:
            response = input(f"\n向量数据库中已有 {existing_count} 个题目，是否强制更新所有题目？(y/N): ")
            force_update = response.lower() == 'y'
        
        # 开始迁移
        print("\n开始迁移...")
        success_count = 0
        skip_count = 0
        error_count = 0
        errors = []
        
        for i, teaching in enumerate(teachings, 1):
            # 显示进度
            progress = (i / total_count) * 100
            print(f"\r进度: {i}/{total_count} ({progress:.1f}%) - {teaching.task_id[:8]}...", end="", flush=True)
            
            # 迁移单个题目
            success, error_msg = migrate_teaching_to_chroma(teaching, force_update)
            
            if success:
                if error_msg is None and not force_update:
                    skip_count += 1  # 已存在，跳过
                else:
                    success_count += 1  # 成功添加/更新
            else:
                error_count += 1
                errors.append({
                    "task_id": teaching.task_id,
                    "question": teaching.question[:50] if teaching.question else "",
                    "error": error_msg or "未知错误"
                })
        
        print("\n" + "=" * 60)
        print("迁移完成！")
        print("=" * 60)
        print(f"总计: {total_count} 个题目")
        print(f"成功: {success_count} 个")
        print(f"跳过: {skip_count} 个（已存在）")
        print(f"失败: {error_count} 个")
        
        # 显示错误详情
        if errors:
            print("\n失败的题目:")
            for error in errors[:10]:  # 只显示前10个错误
                print(f"  - {error['task_id']}: {error['error']}")
            if len(errors) > 10:
                print(f"  ... 还有 {len(errors) - 10} 个错误")
        
        # 验证最终数量
        final_count = count_teachings()
        print(f"\n向量数据库中最终题目数量: {final_count}")
        
    except Exception as e:
        print(f"\n迁移过程中发生错误: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()


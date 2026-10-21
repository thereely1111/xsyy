#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
数据库迁移脚本：为用户表添加每日调用次数相关字段
"""

import sys
from pathlib import Path

# 添加 backend 目录到路径
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from database.database import engine
from sqlalchemy import text

def migrate():
    """执行数据库迁移"""
    print("=" * 60)
    print("开始迁移：添加每日调用次数相关字段")
    print("=" * 60)
    
    # SQL 语句
    sql_statements = [
        # 添加 daily_max_calls 字段（默认值 10）
        """
        ALTER TABLE users 
        ADD COLUMN daily_max_calls INT NOT NULL DEFAULT 10 
        COMMENT '每日最大调用次数（可修改）'
        """,
        # 添加 daily_calls_count 字段（默认值 0）
        """
        ALTER TABLE users 
        ADD COLUMN daily_calls_count INT NOT NULL DEFAULT 0 
        COMMENT '当天已调用次数'
        """,
        # 添加 last_call_date 字段（可为空）
        """
        ALTER TABLE users 
        ADD COLUMN last_call_date DATETIME NULL 
        COMMENT '最后调用日期（用于重置计数）'
        """,
    ]
    
    try:
        with engine.connect() as conn:
            for i, sql in enumerate(sql_statements, 1):
                try:
                    print(f"\n[{i}/{len(sql_statements)}] 执行 SQL...")
                    conn.execute(text(sql))
                    conn.commit()
                    print(f"✓ 成功执行 SQL {i}")
                except Exception as e:
                    # 如果字段已存在，跳过
                    if "Duplicate column name" in str(e) or "already exists" in str(e).lower():
                        print(f"⚠ 字段已存在，跳过: {e}")
                    else:
                        print(f"❌ 执行 SQL {i} 失败: {e}")
                        raise
        
        print("\n" + "=" * 60)
        print("✓ 迁移完成！")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ 迁移失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    migrate()


#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
为用户表添加基础信息字段（grade、signature、email）的迁移脚本
"""

import sys
from pathlib import Path

# 添加 backend 目录到路径
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy import text
from database.database import engine, SessionLocal

def add_user_profile_fields():
    """添加用户基础信息字段"""
    print("=" * 60)
    print("开始迁移：添加用户基础信息字段")
    print("=" * 60)
    
    db = SessionLocal()
    try:
        # 检查字段是否已存在
        with engine.connect() as conn:
            result = conn.execute(text("SHOW COLUMNS FROM users LIKE 'email'"))
            email_exists = result.fetchone() is not None
            
            result = conn.execute(text("SHOW COLUMNS FROM users LIKE 'grade'"))
            grade_exists = result.fetchone() is not None
            
            result = conn.execute(text("SHOW COLUMNS FROM users LIKE 'signature'"))
            signature_exists = result.fetchone() is not None
        
        # 添加邮箱字段
        if not email_exists:
            print("添加 email 字段...")
            db.execute(text("ALTER TABLE users ADD COLUMN email VARCHAR(100) NULL AFTER phone"))
            db.execute(text("CREATE INDEX idx_users_email ON users(email)"))
            print("✓ email 字段已添加")
        else:
            print("⚠ email 字段已存在，跳过")
        
        # 添加年级字段
        if not grade_exists:
            print("添加 grade 字段...")
            db.execute(text("ALTER TABLE users ADD COLUMN grade VARCHAR(10) NULL AFTER password_hash"))
            print("✓ grade 字段已添加")
        else:
            print("⚠ grade 字段已存在，跳过")
        
        # 添加个性签名字段
        if not signature_exists:
            print("添加 signature 字段...")
            db.execute(text("ALTER TABLE users ADD COLUMN signature TEXT NULL AFTER grade"))
            print("✓ signature 字段已添加")
        else:
            print("⚠ signature 字段已存在，跳过")
        
        db.commit()
        print("=" * 60)
        print("✓ 迁移完成！")
        print("=" * 60)
        
    except Exception as e:
        db.rollback()
        print(f"❌ 迁移失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()
    
    return True

if __name__ == "__main__":
    success = add_user_profile_fields()
    sys.exit(0 if success else 1)


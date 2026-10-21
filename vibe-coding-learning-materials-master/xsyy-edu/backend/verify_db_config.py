#!/usr/bin/env python3
"""
验证数据库配置脚本
检查数据库连接和数据迁移结果
"""

import sys
from pathlib import Path
from sqlalchemy import text

# 确保可以导入 backend 模块
backend_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(backend_dir))

from database import engine, SessionLocal
from database.models import User, Teaching, Comment, TeachingLike, Favorite

def verify_connection():
    """验证数据库连接"""
    print("=" * 60)
    print("数据库配置验证")
    print("=" * 60)
    
    print("\n1. 测试数据库连接...")
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT DATABASE(), VERSION()"))
            db_name, version = result.fetchone()
            print(f"   ✓ 数据库连接成功")
            print(f"   - 当前数据库: {db_name}")
            print(f"   - MySQL 版本: {version}")
    except Exception as e:
        print(f"   ✗ 数据库连接失败: {e}")
        return False
    
    print("\n2. 检查数据库表...")
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SHOW TABLES"))
            tables = [row[0] for row in result.fetchall()]
            expected_tables = [
                'users', 'verification_codes', 'teachings', 
                'comments', 'comment_likes', 'teaching_likes', 'favorites'
            ]
            
            print(f"   - 找到 {len(tables)} 个表")
            for table in expected_tables:
                if table in tables:
                    print(f"   ✓ {table}")
                else:
                    print(f"   ✗ {table} (缺失)")
            
            if len(tables) < len(expected_tables):
                print("\n   ⚠️  警告: 部分表缺失，请运行 python init_database.py 初始化")
                return False
    except Exception as e:
        print(f"   ✗ 检查表失败: {e}")
        return False
    
    print("\n3. 检查数据迁移结果...")
    db = SessionLocal()
    try:
        user_count = db.query(User).count()
        teaching_count = db.query(Teaching).count()
        comment_count = db.query(Comment).count()
        like_count = db.query(TeachingLike).count()
        favorite_count = db.query(Favorite).count()
        
        print(f"   - 用户数量: {user_count}")
        print(f"   - 教学内容数量: {teaching_count}")
        print(f"   - 评论数量: {comment_count}")
        print(f"   - 点赞数量: {like_count}")
        print(f"   - 收藏数量: {favorite_count}")
        
        if user_count == 0 and teaching_count == 0:
            print("\n   ⚠️  提示: 数据库为空，可以运行 python database/migrate.py 迁移数据")
        else:
            print("\n   ✓ 数据迁移完成")
    except Exception as e:
        print(f"   ✗ 检查数据失败: {e}")
        return False
    finally:
        db.close()
    
    print("\n" + "=" * 60)
    print("✓ 数据库配置验证完成！")
    print("=" * 60)
    return True

if __name__ == "__main__":
    success = verify_connection()
    sys.exit(0 if success else 1)


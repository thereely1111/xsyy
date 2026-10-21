"""
添加专题分享字段的迁移脚本
"""
import sys
from pathlib import Path

# 添加父目录到路径
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from database import SessionLocal, engine
from sqlalchemy import text

def add_topic_share_fields():
    """添加专题分享相关字段"""
    print("=" * 60)
    print("开始添加专题分享字段...")
    print("=" * 60)
    
    try:
        with engine.connect() as conn:
            # 检查 share_token 字段是否已存在
            result = conn.execute(text("""
                SELECT COUNT(*) as count 
                FROM information_schema.COLUMNS 
                WHERE TABLE_SCHEMA = DATABASE() 
                AND TABLE_NAME = 'topics' 
                AND COLUMN_NAME = 'share_token'
            """))
            share_token_exists = result.fetchone()[0] > 0
            
            if share_token_exists:
                print("✓ share_token 字段已存在，跳过添加")
            else:
                print("正在添加 share_token 字段...")
                conn.execute(text("""
                    ALTER TABLE topics
                    ADD COLUMN share_token VARCHAR(64) NULL AFTER is_default
                """))
                conn.commit()
                print("✓ share_token 字段添加成功")
                
                # 添加唯一索引
                print("正在添加 share_token 唯一索引...")
                conn.execute(text("""
                    ALTER TABLE topics
                    ADD UNIQUE INDEX idx_topics_share_token (share_token)
                """))
                conn.commit()
                print("✓ share_token 唯一索引添加成功")
            
            # 检查 is_shared 字段是否已存在
            result = conn.execute(text("""
                SELECT COUNT(*) as count 
                FROM information_schema.COLUMNS 
                WHERE TABLE_SCHEMA = DATABASE() 
                AND TABLE_NAME = 'topics' 
                AND COLUMN_NAME = 'is_shared'
            """))
            is_shared_exists = result.fetchone()[0] > 0
            
            if is_shared_exists:
                print("✓ is_shared 字段已存在，跳过添加")
            else:
                print("正在添加 is_shared 字段...")
                conn.execute(text("""
                    ALTER TABLE topics
                    ADD COLUMN is_shared BOOLEAN DEFAULT FALSE NOT NULL AFTER share_token
                """))
                conn.commit()
                print("✓ is_shared 字段添加成功")
            
            # 检查 share_expires_at 字段是否已存在
            result = conn.execute(text("""
                SELECT COUNT(*) as count 
                FROM information_schema.COLUMNS 
                WHERE TABLE_SCHEMA = DATABASE() 
                AND TABLE_NAME = 'topics' 
                AND COLUMN_NAME = 'share_expires_at'
            """))
            share_expires_at_exists = result.fetchone()[0] > 0
            
            if share_expires_at_exists:
                print("✓ share_expires_at 字段已存在，跳过添加")
            else:
                print("正在添加 share_expires_at 字段...")
                conn.execute(text("""
                    ALTER TABLE topics
                    ADD COLUMN share_expires_at DATETIME NULL AFTER is_shared
                """))
                conn.commit()
                print("✓ share_expires_at 字段添加成功")
            
            # 验证
            print("\n" + "=" * 60)
            print("验证结果：")
            print("=" * 60)
            
            result = conn.execute(text("DESCRIBE topics"))
            columns = {row[0]: row[1] for row in result}
            
            if 'share_token' in columns:
                print("✓ share_token 字段存在")
            else:
                print("✗ share_token 字段不存在")
                return False
            
            if 'is_shared' in columns:
                print("✓ is_shared 字段存在")
            else:
                print("✗ is_shared 字段不存在")
                return False
            
            if 'share_expires_at' in columns:
                print("✓ share_expires_at 字段存在")
            else:
                print("✗ share_expires_at 字段不存在")
                return False
            
            # 检查索引
            result = conn.execute(text("SHOW INDEX FROM topics WHERE Column_name = 'share_token'"))
            indexes = list(result)
            if indexes:
                print(f"\n✓ share_token 索引存在（共 {len(indexes)} 个）")
            else:
                print("\n⚠ share_token 索引不存在")
            
            print("\n" + "=" * 60)
            print("✓ 迁移完成！")
            print("=" * 60)
            return True
                
    except Exception as e:
        print(f"\n✗ 迁移失败: {e}")
        import traceback
        traceback.print_exc()
        print("\n" + "=" * 60)
        print("提示：")
        print("  1. 请确认 MySQL 服务正在运行")
        print("  2. 请确认 .env 文件中的 DATABASE_URL 配置正确")
        print("  3. 请确认数据库用户有 ALTER TABLE 权限")
        print("=" * 60)
        return False

if __name__ == "__main__":
    success = add_topic_share_fields()
    sys.exit(0 if success else 1)

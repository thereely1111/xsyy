"""
添加 topics 表和 topic_id 字段的迁移脚本
"""
import sys
from pathlib import Path

# 添加父目录到路径
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from database import SessionLocal, engine
from sqlalchemy import text

def add_topics_table():
    """添加 topics 表和 topic_id 字段"""
    print("=" * 60)
    print("开始添加 topics 表和 topic_id 字段...")
    print("=" * 60)
    
    try:
        with engine.connect() as conn:
            # 检查 topics 表是否已存在
            result = conn.execute(text("""
                SELECT COUNT(*) as count 
                FROM information_schema.TABLES 
                WHERE TABLE_SCHEMA = DATABASE() 
                AND TABLE_NAME = 'topics'
            """))
            topics_exists = result.fetchone()[0] > 0
            
            if topics_exists:
                print("✓ topics 表已存在")
            else:
                print("正在创建 topics 表...")
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS topics (
                        topic_id VARCHAR(36) PRIMARY KEY,
                        user_id VARCHAR(36) NOT NULL,
                        name VARCHAR(100) NOT NULL,
                        description TEXT NULL,
                        is_default BOOLEAN DEFAULT FALSE NOT NULL,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        INDEX idx_user_id (user_id),
                        INDEX idx_is_default (is_default),
                        CONSTRAINT fk_topics_user
                            FOREIGN KEY (user_id) REFERENCES users(user_id)
                            ON DELETE CASCADE
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """))
                conn.commit()
                print("✓ topics 表创建成功！")
            
            # 检查 topic_id 字段是否已存在
            result = conn.execute(text("""
                SELECT COUNT(*) as count 
                FROM information_schema.COLUMNS 
                WHERE TABLE_SCHEMA = DATABASE() 
                AND TABLE_NAME = 'teachings' 
                AND COLUMN_NAME = 'topic_id'
            """))
            topic_id_exists = result.fetchone()[0] > 0
            
            if topic_id_exists:
                print("✓ topic_id 字段已存在，跳过添加")
            else:
                print("正在添加 topic_id 字段到 teachings 表...")
                try:
                    conn.execute(text("""
                        ALTER TABLE teachings
                        ADD COLUMN topic_id VARCHAR(36) NULL AFTER user_id
                    """))
                    conn.commit()
                    print("✓ topic_id 字段添加成功")
                    
                    # 添加索引
                    print("正在添加索引...")
                    conn.execute(text("""
                        ALTER TABLE teachings
                        ADD INDEX idx_teachings_topic_id (topic_id)
                    """))
                    conn.commit()
                    print("✓ 索引添加成功")
                    
                    # 添加外键约束
                    print("正在添加外键约束...")
                    conn.execute(text("""
                        ALTER TABLE teachings
                        ADD CONSTRAINT fk_teachings_topic
                            FOREIGN KEY (topic_id) REFERENCES topics(topic_id)
                            ON DELETE SET NULL
                    """))
                    conn.commit()
                    print("✓ 外键约束添加成功")
                except Exception as e:
                    # 如果添加字段失败，可能是字段已存在或其他原因
                    print(f"⚠ 添加 topic_id 字段时出现警告: {e}")
                    print("   尝试继续验证...")
            
            # 验证
            print("\n" + "=" * 60)
            print("验证结果：")
            print("=" * 60)
            
            # 验证 topics 表
            result = conn.execute(text("SHOW TABLES LIKE 'topics'"))
            if result.fetchone():
                print("✓ topics 表存在")
                
                # 显示 topics 表结构
                result = conn.execute(text("DESCRIBE topics"))
                print("\ntopics 表结构：")
                for row in result:
                    print(f"  - {row[0]}: {row[1]}")
            else:
                print("✗ topics 表不存在")
                return False
            
            # 验证 topic_id 字段
            result = conn.execute(text("DESCRIBE teachings"))
            columns = [row[0] for row in result]
            if 'topic_id' in columns:
                print("\n✓ topic_id 字段已存在于 teachings 表中")
                
                # 显示 topic_id 字段的详细信息
                result = conn.execute(text("DESCRIBE teachings"))
                print("\ntopic_id 字段信息：")
                for row in result:
                    if row[0] == 'topic_id':
                        print(f"  - 字段名: {row[0]}")
                        print(f"  - 类型: {row[1]}")
                        print(f"  - 允许NULL: {row[2]}")
                        print(f"  - 默认值: {row[4]}")
                        break
                
                # 检查索引
                result = conn.execute(text("SHOW INDEX FROM teachings WHERE Column_name = 'topic_id'"))
                indexes = list(result)
                if indexes:
                    print(f"\n✓ topic_id 索引存在（共 {len(indexes)} 个）")
                else:
                    print("\n⚠ topic_id 索引不存在（可能需要手动添加）")
                
                # 检查外键约束
                result = conn.execute(text("""
                    SELECT CONSTRAINT_NAME 
                    FROM information_schema.KEY_COLUMN_USAGE 
                    WHERE TABLE_SCHEMA = DATABASE() 
                    AND TABLE_NAME = 'teachings' 
                    AND COLUMN_NAME = 'topic_id'
                    AND REFERENCED_TABLE_NAME IS NOT NULL
                """))
                fk = result.fetchone()
                if fk:
                    print(f"✓ 外键约束存在: {fk[0]}")
                else:
                    print("⚠ 外键约束不存在（可能需要手动添加）")
                
                print("\n" + "=" * 60)
                print("✓ 迁移完成！")
                print("=" * 60)
                return True
            else:
                print("\n✗ topic_id 字段未找到")
                return False
                
    except Exception as e:
        print(f"\n✗ 迁移失败: {e}")
        import traceback
        traceback.print_exc()
        print("\n" + "=" * 60)
        print("提示：")
        print("  1. 请确认 MySQL 服务正在运行")
        print("  2. 请确认 .env 文件中的 DATABASE_URL 配置正确")
        print("  3. 请确认数据库用户有 CREATE TABLE 和 ALTER TABLE 权限")
        print("  4. 请确认 users 表已存在（topics 表依赖 users 表）")
        print("=" * 60)
        return False

if __name__ == "__main__":
    success = add_topics_table()
    sys.exit(0 if success else 1)

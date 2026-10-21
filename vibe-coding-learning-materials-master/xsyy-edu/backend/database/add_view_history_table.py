"""
创建 user_view_history 表的迁移脚本
"""
import sys
from pathlib import Path

# 添加父目录到路径
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from database.database import SessionLocal, engine
from sqlalchemy import text

def create_view_history_table():
    """创建 user_view_history 表"""
    print("=" * 60)
    print("开始创建 user_view_history 表...")
    print("=" * 60)
    
    try:
        with engine.connect() as conn:
            # 检查表是否已存在
            result = conn.execute(text("""
                SELECT COUNT(*) as count 
                FROM information_schema.TABLES 
                WHERE TABLE_SCHEMA = DATABASE() 
                AND TABLE_NAME = 'user_view_history'
            """))
            exists = result.fetchone()[0] > 0
            
            if exists:
                print("✓ user_view_history 表已存在，跳过创建")
                return True
            
            # 创建表
            print("正在创建 user_view_history 表...")
            conn.execute(text("""
                CREATE TABLE user_view_history (
                    view_id VARCHAR(36) PRIMARY KEY,
                    user_id VARCHAR(36) NOT NULL,
                    task_id VARCHAR(36) NOT NULL,
                    viewed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    view_count INT NOT NULL DEFAULT 1,
                    INDEX idx_user_id (user_id),
                    INDEX idx_task_id (task_id),
                    INDEX idx_viewed_at (viewed_at),
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                    FOREIGN KEY (task_id) REFERENCES teachings(task_id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """))
            conn.commit()
            print("✓ user_view_history 表创建成功！")
            
            # 验证
            result = conn.execute(text("SHOW TABLES LIKE 'user_view_history'"))
            if result.fetchone():
                print("✓ 验证成功：user_view_history 表已创建")
                return True
            else:
                print("✗ 验证失败：user_view_history 表未找到")
                return False
                
    except Exception as e:
        print(f"✗ 创建表失败: {e}")
        print("\n提示：")
        print("  1. 请确认 MySQL 服务正在运行")
        print("  2. 请确认 .env 文件中的 DATABASE_URL 配置正确")
        print("  3. 请确认数据库用户有 CREATE TABLE 权限")
        print("  4. 请确认 users 和 teachings 表已存在")
        return False

if __name__ == "__main__":
    success = create_view_history_table()
    sys.exit(0 if success else 1)


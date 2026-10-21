"""
创建 knowledge_tag_framework 表的迁移脚本

用法：
    cd backend
    python database/add_knowledge_tag_framework_table.py
"""
import sys
from pathlib import Path

# 添加父目录到路径
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from database import engine
from sqlalchemy import text


def create_table():
    """创建 knowledge_tag_framework 表"""
    print("=" * 60)
    print("开始创建 knowledge_tag_framework 表...")
    print("=" * 60)

    try:
        with engine.connect() as conn:
            # 检查表是否已存在
            result = conn.execute(text("""
                SELECT COUNT(*) as count
                FROM information_schema.TABLES
                WHERE TABLE_SCHEMA = DATABASE()
                AND TABLE_NAME = 'knowledge_tag_framework'
            """))
            table_exists = result.fetchone()[0] > 0

            if table_exists:
                print("✓ knowledge_tag_framework 表已存在")
            else:
                print("正在创建 knowledge_tag_framework 表...")
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS knowledge_tag_framework (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        version VARCHAR(50) NOT NULL,
                        grade VARCHAR(10) NOT NULL,
                        main_tag VARCHAR(100) NOT NULL,
                        sub_tag VARCHAR(100) NOT NULL,
                        keyword VARCHAR(500) NULL,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        INDEX idx_version (version),
                        INDEX idx_grade (grade),
                        INDEX idx_main_tag (main_tag),
                        INDEX idx_sub_tag (sub_tag),
                        INDEX idx_version_grade (version, grade),
                        INDEX idx_main_tag_sub_tag (main_tag, sub_tag)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """))
                conn.commit()
                print("✓ knowledge_tag_framework 表创建成功")

    except Exception as e:
        print(f"✗ 创建表失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    create_table()
    print("\n完成。接下来请运行导入脚本：")
    print("  python scripts/import_tag_framework_to_db.py")

"""
添加 second_tag 字段到 teachings 表的迁移脚本（支持多知识点双标签）。

标签体系（双标签组）：
    knowledge_tags = 主标签组 {version(知识域), grade(年级), main_tag(章/单元), sub_tags:[知识点标签]}
    second_tag     = 第二标签组（结构同 knowledge_tags，可空；与主标签组知识域不同，最多 2 个标签）

用法：
    cd backend
    python database/add_second_tag_column.py
"""
import sys
from pathlib import Path

# 添加父目录到路径
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from database import engine
from sqlalchemy import text


def add_second_tag_column():
    """添加 second_tag 字段到 teachings 表。"""
    print("=" * 60)
    print("开始添加 second_tag 字段...")
    print("=" * 60)

    try:
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT COUNT(*) as count
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                AND TABLE_NAME = 'teachings'
                AND COLUMN_NAME = 'second_tag'
            """))
            exists = result.fetchone()[0] > 0

            if exists:
                print("✓ second_tag 字段已存在，跳过添加")
                return True

            print("正在添加 second_tag 字段...")
            conn.execute(text("""
                ALTER TABLE teachings
                ADD COLUMN second_tag JSON NULL
                AFTER knowledge_tags
            """))
            conn.commit()
            print("✓ second_tag 字段添加成功！")

            result = conn.execute(text("DESCRIBE teachings"))
            columns = [row[0] for row in result]
            if "second_tag" in columns:
                print("✓ 验证成功：second_tag 字段已存在于 teachings 表中")
                return True
            else:
                print("✗ 验证失败：second_tag 字段未找到")
                return False

    except Exception as e:
        print(f"✗ 添加字段失败: {e}")
        print("\n提示：")
        print("  1. 请确认 MySQL 服务正在运行")
        print("  2. 请确认 .env 文件中的 DATABASE_URL 配置正确")
        print("  3. 请确认数据库用户有 ALTER TABLE 权限")
        return False


if __name__ == "__main__":
    success = add_second_tag_column()
    sys.exit(0 if success else 1)

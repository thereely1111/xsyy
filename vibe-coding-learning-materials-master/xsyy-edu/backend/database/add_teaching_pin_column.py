from database import engine
from sqlalchemy import text


def add_teaching_pin_column():
    """添加 is_pinned 字段到 teachings 表。"""
    try:
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT COUNT(*) as count
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                AND TABLE_NAME = 'teachings'
                AND COLUMN_NAME = 'is_pinned'
            """))
            exists = result.fetchone()[0] > 0

            if exists:
                print("✓ is_pinned 字段已存在，跳过添加")
                return True

            conn.execute(text("""
                ALTER TABLE teachings
                ADD COLUMN is_pinned BOOLEAN NOT NULL DEFAULT FALSE
                AFTER view_count
            """))
            conn.commit()
            print("✓ is_pinned 字段添加成功")
            return True
    except Exception as e:
        print(f"✗ 添加 is_pinned 字段失败: {e}")
        return False


if __name__ == "__main__":
    add_teaching_pin_column()

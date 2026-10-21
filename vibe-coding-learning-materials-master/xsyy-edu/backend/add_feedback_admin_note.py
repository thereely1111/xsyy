"""为 user_feedbacks 表补充 admin_note（管理员留言）列。

用法：在 backend 目录下执行
    python add_feedback_admin_note.py

脚本是幂等的：列已存在时会跳过，不会重复添加。
"""
from sqlalchemy import text

from database.database import engine


def main():
    with engine.begin() as conn:
        exists = conn.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() "
                "AND TABLE_NAME = 'user_feedbacks' "
                "AND COLUMN_NAME = 'admin_note'"
            )
        ).scalar()
        if exists:
            print("admin_note 列已存在，无需迁移")
            return
        conn.execute(text("ALTER TABLE user_feedbacks ADD COLUMN admin_note TEXT NULL"))
        print("已为 user_feedbacks 添加 admin_note 列")


if __name__ == "__main__":
    main()

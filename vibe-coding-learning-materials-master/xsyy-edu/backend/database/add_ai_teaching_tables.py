"""
添加 AI 助教会话与问答缓存表
"""
import sys
from pathlib import Path

from sqlalchemy import text

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from database import engine


def add_ai_teaching_tables() -> bool:
    print("=" * 60)
    print("开始添加 AI 助教数据表...")
    print("=" * 60)

    try:
        with engine.connect() as conn:
            conn.execute(text(
                """
                CREATE TABLE IF NOT EXISTS ai_teaching_session (
                    session_hash VARCHAR(64) PRIMARY KEY,
                    page_id VARCHAR(128) NOT NULL,
                    content_full_hash VARCHAR(64) NOT NULL,
                    summary TEXT NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_ai_teaching_session_page_id (page_id),
                    INDEX idx_ai_teaching_session_content_full_hash (content_full_hash),
                    INDEX idx_ai_teaching_session_created_at (created_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            ))
            conn.commit()
            print("✓ ai_teaching_session 表已就绪")

            conn.execute(text(
                """
                CREATE TABLE IF NOT EXISTS ai_teaching_qa (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    session_hash VARCHAR(64) NOT NULL,
                    user_id VARCHAR(36) NOT NULL,
                    question_hash VARCHAR(64) NOT NULL,
                    question_text TEXT NOT NULL,
                    answer_summary TEXT NOT NULL,
                    full_qa_data JSON NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_ai_teaching_qa_session_hash (session_hash),
                    INDEX idx_ai_teaching_qa_user_id (user_id),
                    INDEX idx_ai_teaching_qa_question_hash (question_hash),
                    INDEX idx_ai_teaching_qa_created_at (created_at),
                    CONSTRAINT fk_ai_teaching_qa_session_hash FOREIGN KEY (session_hash)
                        REFERENCES ai_teaching_session(session_hash) ON DELETE CASCADE,
                    CONSTRAINT fk_ai_teaching_qa_user_id FOREIGN KEY (user_id)
                        REFERENCES users(user_id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            ))
            conn.commit()
            print("✓ ai_teaching_qa 表已就绪")

            print("=" * 60)
            print("✓ AI 助教数据表迁移完成")
            print("=" * 60)
            return True

    except Exception as exc:
        print(f"✗ 迁移失败: {exc}")
        return False


if __name__ == "__main__":
    success = add_ai_teaching_tables()
    sys.exit(0 if success else 1)

-- AI 助教会话与问答缓存表

CREATE TABLE IF NOT EXISTS ai_teaching_session (
    session_hash VARCHAR(64) PRIMARY KEY,
    page_id VARCHAR(128) NOT NULL,
    content_full_hash VARCHAR(64) NOT NULL,
    summary TEXT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_ai_teaching_session_page_id (page_id),
    INDEX idx_ai_teaching_session_content_full_hash (content_full_hash),
    INDEX idx_ai_teaching_session_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

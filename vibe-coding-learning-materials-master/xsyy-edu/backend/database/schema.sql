-- XSYY 数据库表结构
-- MySQL 5.7+ / MySQL 8.0+

CREATE DATABASE IF NOT EXISTS xsyy CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE xsyy;

-- 用户表
CREATE TABLE IF NOT EXISTS users (
    user_id VARCHAR(36) PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    phone VARCHAR(11) UNIQUE NULL,
    password_hash VARCHAR(64) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reset_token VARCHAR(255) NULL,
    reset_token_expiry DATETIME NULL,
    INDEX idx_username (username),
    INDEX idx_phone (phone)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 验证码表（临时数据）
CREATE TABLE IF NOT EXISTS verification_codes (
    phone VARCHAR(11) PRIMARY KEY,
    code VARCHAR(6) NOT NULL,
    expiry DATETIME NOT NULL,
    INDEX idx_expiry (expiry)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 教学内容表
CREATE TABLE IF NOT EXISTS teachings (
    task_id VARCHAR(36) PRIMARY KEY,
    question TEXT NOT NULL,
    prompt TEXT,
    title VARCHAR(100) NULL,
    is_math_problem BOOLEAN DEFAULT TRUE,
    main_tag VARCHAR(50) NULL,
    sub_tags JSON NULL,
    reasoning VARCHAR(200) NULL,
    generated_at DATETIME NOT NULL,
    input_file VARCHAR(500) NULL,
    teaching_html_file VARCHAR(100) NOT NULL DEFAULT 'teaching.html',
    preview_image VARCHAR(100) NULL,
    INDEX idx_generated_at (generated_at),
    INDEX idx_main_tag (main_tag),
    INDEX idx_is_math_problem (is_math_problem)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 评论表
CREATE TABLE IF NOT EXISTS comments (
    comment_id VARCHAR(36) PRIMARY KEY,
    task_id VARCHAR(36) NOT NULL,
    user_id VARCHAR(36) NOT NULL,
    username VARCHAR(50) NOT NULL,
    content TEXT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    likes INT DEFAULT 0,
    parent_id VARCHAR(36) NULL,
    INDEX idx_task_id (task_id),
    INDEX idx_parent_id (parent_id),
    INDEX idx_created_at (created_at),
    INDEX idx_user_id (user_id),
    FOREIGN KEY (task_id) REFERENCES teachings(task_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (parent_id) REFERENCES comments(comment_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 评论点赞关系表
CREATE TABLE IF NOT EXISTS comment_likes (
    comment_id VARCHAR(36) NOT NULL,
    user_id VARCHAR(36) NOT NULL,
    PRIMARY KEY (comment_id, user_id),
    INDEX idx_user_id (user_id),
    FOREIGN KEY (comment_id) REFERENCES comments(comment_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 教学内容点赞关系表
CREATE TABLE IF NOT EXISTS teaching_likes (
    task_id VARCHAR(36) NOT NULL,
    user_id VARCHAR(36) NOT NULL,
    PRIMARY KEY (task_id, user_id),
    INDEX idx_user_id (user_id),
    FOREIGN KEY (task_id) REFERENCES teachings(task_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 用户收藏表
CREATE TABLE IF NOT EXISTS favorites (
    user_id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, task_id),
    INDEX idx_user_id (user_id),
    INDEX idx_created_at (created_at),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (task_id) REFERENCES teachings(task_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- AI 助教会话摘要缓存表
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

-- AI 助教问答缓存表
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
    FOREIGN KEY (session_hash) REFERENCES ai_teaching_session(session_hash) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


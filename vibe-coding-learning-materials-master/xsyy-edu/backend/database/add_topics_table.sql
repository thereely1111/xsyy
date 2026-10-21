-- 创建 topics 表
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 为 teachings 表添加 topic_id 字段
-- 如果字段已存在，执行会报错，可忽略
ALTER TABLE teachings
ADD COLUMN topic_id VARCHAR(36) NULL AFTER user_id,
ADD INDEX idx_teachings_topic_id (topic_id),
ADD CONSTRAINT fk_teachings_topic
    FOREIGN KEY (topic_id) REFERENCES topics(topic_id)
    ON DELETE SET NULL;

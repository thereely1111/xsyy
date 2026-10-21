-- 创建用户浏览记录表
-- 如果表已存在，此语句会报错，可以忽略

CREATE TABLE IF NOT EXISTS user_view_history (
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


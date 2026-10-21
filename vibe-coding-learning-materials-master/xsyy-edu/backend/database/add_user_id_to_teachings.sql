-- 为 teachings 表添加 user_id 字段并建立外键与索引
-- 如果字段已存在，执行会报错，可忽略

ALTER TABLE teachings
ADD COLUMN user_id VARCHAR(36) NULL AFTER task_id,
ADD INDEX idx_teachings_user_id (user_id),
ADD CONSTRAINT fk_teachings_user
    FOREIGN KEY (user_id) REFERENCES users(user_id)
    ON DELETE SET NULL;


-- 添加专题分享相关字段

-- 添加 share_token 字段（唯一，用于生成分享链接）
ALTER TABLE topics
ADD COLUMN share_token VARCHAR(64) NULL AFTER is_default,
ADD UNIQUE INDEX idx_topics_share_token (share_token);

-- 添加 is_shared 字段（是否已分享）
ALTER TABLE topics
ADD COLUMN is_shared BOOLEAN DEFAULT FALSE NOT NULL AFTER share_token;

-- 添加 share_expires_at 字段（分享过期时间，可选）
ALTER TABLE topics
ADD COLUMN share_expires_at DATETIME NULL AFTER is_shared;

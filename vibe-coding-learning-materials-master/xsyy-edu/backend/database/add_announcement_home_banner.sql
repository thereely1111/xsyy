-- 首页顶部公告条：每条公告是否在首页展示。
-- 业务层确保同一时刻仅有一条已发布的系统公告开启该开关。
ALTER TABLE announcements
    ADD COLUMN IF NOT EXISTS is_home_banner BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS ix_announcements_is_home_banner
    ON announcements (is_home_banner);

-- 公告表新增 is_pinned 字段（置顶），供"管理公告"模块使用
ALTER TABLE announcements
    ADD COLUMN IF NOT EXISTS is_pinned BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS ix_announcements_is_pinned ON announcements (is_pinned);

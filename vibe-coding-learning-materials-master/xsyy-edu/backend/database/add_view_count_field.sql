-- 为 teachings 表添加 view_count 字段
-- 如果字段已存在，此语句会报错，可以忽略

ALTER TABLE teachings 
ADD COLUMN view_count INT NOT NULL DEFAULT 0 
AFTER preview_image;

-- 如果字段已存在，可以使用以下语句更新现有记录的默认值（可选）
-- UPDATE teachings SET view_count = 0 WHERE view_count IS NULL;


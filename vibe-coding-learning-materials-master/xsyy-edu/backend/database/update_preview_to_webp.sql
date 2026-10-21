-- 将数据库中所有 preview_image 字段更新为 preview.webp
-- 使用方法：在 MySQL 客户端中执行此脚本
-- mysql -u root -p xsyy < update_preview_to_webp.sql

-- 更新所有 preview_image 字段为 preview.webp
UPDATE teachings 
SET preview_image = 'preview.webp' 
WHERE preview_image IS NOT NULL 
  AND preview_image != 'preview.webp';

-- 查看更新结果
SELECT 
    COUNT(*) as total_records,
    SUM(CASE WHEN preview_image = 'preview.webp' THEN 1 ELSE 0 END) as webp_count,
    SUM(CASE WHEN preview_image = 'preview.png' THEN 1 ELSE 0 END) as png_count,
    SUM(CASE WHEN preview_image IS NULL OR preview_image = '' THEN 1 ELSE 0 END) as null_count
FROM teachings;


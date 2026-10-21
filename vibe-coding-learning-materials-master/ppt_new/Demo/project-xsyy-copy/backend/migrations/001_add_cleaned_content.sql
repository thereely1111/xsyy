-- XSYY 数据库变更脚本
-- 文件: migrations/001_add_cleaned_content.sql
-- 描述: 为 problems 表添加 cleaned_content 字段用于存储清洗后的核心题干

-- ============================================
-- 变更 1: 添加 cleaned_content 字段
-- ============================================
ALTER TABLE problems
ADD COLUMN cleaned_content TEXT COMMENT '清洗后的核心题干（去除题号、废话、冗余格式）' AFTER content;

-- ============================================
-- 变更 2: 添加索引（可选，便于按清洗内容搜索审计）
-- ============================================
-- ALTER TABLE problems ADD INDEX idx_cleaned_content (cleaned_content(100));

-- ============================================
-- 回滚脚本（如需回滚）
-- ============================================
-- ALTER TABLE problems DROP COLUMN cleaned_content;

-- ============================================
-- 数据迁移示例（将现有 content 复制到 cleaned_content）
-- ============================================
-- UPDATE problems SET cleaned_content = content WHERE cleaned_content IS NULL;

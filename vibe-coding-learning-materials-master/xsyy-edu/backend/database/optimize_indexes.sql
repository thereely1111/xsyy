-- 数据库索引优化脚本
-- 执行此脚本可以提升数据库查询性能
-- 使用方法：mysql -u root -p xsyy < optimize_indexes.sql

-- ==================== 用户表索引 ====================
-- 用户名索引（登录查询）
CREATE INDEX IF NOT EXISTS idx_user_username ON users(username);
-- 手机号索引（登录查询）
CREATE INDEX IF NOT EXISTS idx_user_phone ON users(phone);
-- 邮箱索引（登录查询）
CREATE INDEX IF NOT EXISTS idx_user_email ON users(email);
-- 用户ID索引（主键已有，但确保存在）
-- ALTER TABLE users ADD PRIMARY KEY IF NOT EXISTS (user_id);

-- ==================== 教学内容表索引 ====================
-- 用户ID索引（查询用户的教学内容）
CREATE INDEX IF NOT EXISTS idx_teaching_user_id ON teachings(user_id);
-- 生成时间索引（按时间排序）
CREATE INDEX IF NOT EXISTS idx_teaching_generated_at ON teachings(generated_at DESC);
-- 主标签索引（按标签筛选）
CREATE INDEX IF NOT EXISTS idx_teaching_main_tag ON teachings(main_tag);
-- 任务ID索引（主键已有，但确保存在）
-- ALTER TABLE teachings ADD PRIMARY KEY IF NOT EXISTS (task_id);

-- ==================== 评论表索引 ====================
-- 任务ID索引（查询某个教学内容的评论）
CREATE INDEX IF NOT EXISTS idx_comment_task_id ON comments(task_id);
-- 创建时间索引（按时间排序）
CREATE INDEX IF NOT EXISTS idx_comment_created_at ON comments(created_at DESC);
-- 用户ID索引（查询用户的评论）
CREATE INDEX IF NOT EXISTS idx_comment_user_id ON comments(user_id);

-- ==================== 评论点赞表索引 ====================
-- 评论ID索引（查询评论的点赞数）
CREATE INDEX IF NOT EXISTS idx_comment_like_comment_id ON comment_likes(comment_id);
-- 用户ID索引（查询用户点赞的评论）
CREATE INDEX IF NOT EXISTS idx_comment_like_user_id ON comment_likes(user_id);
-- 复合索引（查询用户是否点赞某条评论）
CREATE INDEX IF NOT EXISTS idx_comment_like_user_comment ON comment_likes(user_id, comment_id);

-- ==================== 教学内容点赞表索引 ====================
-- 任务ID索引（查询教学内容的点赞数）
CREATE INDEX IF NOT EXISTS idx_teaching_like_task_id ON teaching_likes(task_id);
-- 用户ID索引（查询用户点赞的教学内容）
CREATE INDEX IF NOT EXISTS idx_teaching_like_user_id ON teaching_likes(user_id);
-- 复合索引（查询用户是否点赞某个教学内容）
CREATE INDEX IF NOT EXISTS idx_teaching_like_user_task ON teaching_likes(user_id, task_id);

-- ==================== 收藏表索引 ====================
-- 用户ID索引（查询用户的收藏）
CREATE INDEX IF NOT EXISTS idx_favorite_user_id ON favorites(user_id);
-- 任务ID索引（查询某个教学内容的收藏数）
CREATE INDEX IF NOT EXISTS idx_favorite_task_id ON favorites(task_id);
-- 复合索引（查询用户是否收藏某个教学内容）
CREATE INDEX IF NOT EXISTS idx_favorite_user_task ON favorites(user_id, task_id);

-- ==================== 用户浏览历史表索引 ====================
-- 用户ID索引（查询用户的浏览历史）
CREATE INDEX IF NOT EXISTS idx_view_history_user_id ON user_view_history(user_id);
-- 浏览时间索引（按时间排序）
CREATE INDEX IF NOT EXISTS idx_view_history_viewed_at ON user_view_history(viewed_at DESC);
-- 任务ID索引（查询某个教学内容的浏览数）
CREATE INDEX IF NOT EXISTS idx_view_history_task_id ON user_view_history(task_id);
-- 复合索引（查询用户浏览某个教学内容的历史）
CREATE INDEX IF NOT EXISTS idx_view_history_user_task ON user_view_history(user_id, task_id);

-- ==================== 验证码表索引 ====================
-- 手机号索引（查询验证码）
CREATE INDEX IF NOT EXISTS idx_verification_code_phone ON verification_codes(phone);
-- 过期时间索引（清理过期验证码）
CREATE INDEX IF NOT EXISTS idx_verification_code_expires_at ON verification_codes(expires_at);

-- ==================== 查看索引创建结果 ====================
-- 查看所有索引
-- SHOW INDEX FROM teachings;
-- SHOW INDEX FROM comments;
-- SHOW INDEX FROM teaching_likes;
-- SHOW INDEX FROM comment_likes;
-- SHOW INDEX FROM favorites;
-- SHOW INDEX FROM user_view_history;


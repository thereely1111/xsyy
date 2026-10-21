-- 为用户表添加基础信息字段
-- 执行方式：mysql -u root -p your_database < add_user_profile_fields.sql

-- 添加邮箱字段
ALTER TABLE users ADD COLUMN email VARCHAR(100) NULL AFTER phone;
CREATE INDEX idx_users_email ON users(email);

-- 添加年级字段
ALTER TABLE users ADD COLUMN grade VARCHAR(10) NULL AFTER password_hash;

-- 添加个性签名字段
ALTER TABLE users ADD COLUMN signature TEXT NULL AFTER grade;


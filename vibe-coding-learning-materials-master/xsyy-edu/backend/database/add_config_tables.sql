-- 为系统配置与配置修改日志添加表
-- 执行方式（在 MySQL 中执行本文件）：
--   mysql -u root -p < add_config_tables.sql
-- 重复执行安全（IF NOT EXISTS）

CREATE TABLE IF NOT EXISTS system_configs (
    config_key VARCHAR(64) PRIMARY KEY,
    config_value TEXT NOT NULL,
    description VARCHAR(255) NULL,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS config_change_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    config_key VARCHAR(64) NOT NULL,
    old_value TEXT NULL,
    new_value TEXT NOT NULL,
    operator VARCHAR(50) NOT NULL DEFAULT '',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_config_change_logs_config_key (config_key),
    INDEX idx_config_change_logs_created_at (created_at)
);

-- 初始化默认配置（键值：键名 / 默认值 / 说明）
INSERT IGNORE INTO system_configs (config_key, config_value, description) VALUES
    ('commission_total_shares', '15', '返利总分份数：充值金额按此份数切分'),
    ('commission_level1_shares', '5', '一级返利份数：直接邀请人所得（如总分15份中占5份）'),
    ('commission_level2_shares', '3', '二级返利份数：上级邀请人所得（如总分15份中占3份）'),
    ('new_user_gift_quota', '5', '新用户注册赠送的使用额度（次）'),
    ('invite_reward_quota', '3', '每成功邀请1位新用户，邀请人获得的固定奖励额度（次）');

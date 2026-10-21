-- 为多级返利体系添加表（返利账户 / 返利分配记录 / 提现申请）
-- 执行方式（在 MySQL 中执行本文件，或）：
--   mysql -u root -p < add_commission_tables.sql
-- 重复执行安全（IF NOT EXISTS）

CREATE TABLE IF NOT EXISTS commission_accounts (
    user_id VARCHAR(36) PRIMARY KEY,
    total_reward INT NOT NULL DEFAULT 0,
    withdrawn_amount INT NOT NULL DEFAULT 0,
    pending_amount INT NOT NULL DEFAULT 0,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_commission_accounts_user_id FOREIGN KEY (user_id)
        REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS commission_records (
    id INT AUTO_INCREMENT PRIMARY KEY,
    source_user_id VARCHAR(36) NOT NULL,
    recipient_user_id VARCHAR(36) NOT NULL,
    inviter_user_id VARCHAR(36) NOT NULL,
    level INT NOT NULL DEFAULT 1,
    amount INT NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'available',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_commission_records_recipient_user_id (recipient_user_id),
    INDEX idx_commission_records_source_user_id (source_user_id),
    INDEX idx_commission_records_inviter_user_id (inviter_user_id),
    INDEX idx_commission_records_created_at (created_at),
    CONSTRAINT fk_commission_records_source_user_id FOREIGN KEY (source_user_id)
        REFERENCES users(user_id) ON DELETE CASCADE,
    CONSTRAINT fk_commission_records_recipient_user_id FOREIGN KEY (recipient_user_id)
        REFERENCES users(user_id) ON DELETE CASCADE,
    CONSTRAINT fk_commission_records_inviter_user_id FOREIGN KEY (inviter_user_id)
        REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS withdrawal_requests (
    request_id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL,
    amount INT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    note TEXT NULL,
    admin_note TEXT NULL,
    processed_by VARCHAR(50) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    processed_at DATETIME NULL,
    INDEX idx_withdrawal_requests_user_id (user_id),
    INDEX idx_withdrawal_requests_status (status),
    CONSTRAINT fk_withdrawal_requests_user_id FOREIGN KEY (user_id)
        REFERENCES users(user_id) ON DELETE CASCADE
);

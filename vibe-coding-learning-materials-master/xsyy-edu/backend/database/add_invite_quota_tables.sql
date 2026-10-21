ALTER TABLE users ADD COLUMN invite_code VARCHAR(8) NULL UNIQUE;
ALTER TABLE users ADD COLUMN first_login_reward_granted BOOLEAN NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS device_bindings (
    device_id VARCHAR(128) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL UNIQUE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_device_bindings_user_id (user_id),
    CONSTRAINT fk_device_bindings_user_id FOREIGN KEY (user_id)
        REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS user_quotas (
    user_id VARCHAR(36) PRIMARY KEY,
    daily_free_used INT NOT NULL DEFAULT 0,
    extra_balance INT NOT NULL DEFAULT 0,
    last_reset_date VARCHAR(10) NOT NULL,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_user_quotas_user_id FOREIGN KEY (user_id)
        REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS device_quotas (
    device_id VARCHAR(128) PRIMARY KEY,
    daily_free_used INT NOT NULL DEFAULT 0,
    last_reset_date VARCHAR(10) NOT NULL,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS invite_progress (
    user_id VARCHAR(36) PRIMARY KEY,
    invited_count INT NOT NULL DEFAULT 0,
    claimed_targets JSON NOT NULL,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_invite_progress_user_id FOREIGN KEY (user_id)
        REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS invite_relations (
    id INT AUTO_INCREMENT PRIMARY KEY,
    inviter_user_id VARCHAR(36) NOT NULL,
    invited_user_id VARCHAR(36) NOT NULL UNIQUE,
    invited_device_id VARCHAR(128) NOT NULL UNIQUE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_invite_relations_inviter_user_id (inviter_user_id),
    INDEX idx_invite_relations_invited_user_id (invited_user_id),
    INDEX idx_invite_relations_invited_device_id (invited_device_id),
    CONSTRAINT fk_invite_relations_inviter_user_id FOREIGN KEY (inviter_user_id)
        REFERENCES users(user_id) ON DELETE CASCADE,
    CONSTRAINT fk_invite_relations_invited_user_id FOREIGN KEY (invited_user_id)
        REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS recharge_requests (
    request_id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL,
    amount INT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    note TEXT NULL,
    admin_note TEXT NULL,
    processed_by VARCHAR(50) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    processed_at DATETIME NULL,
    INDEX idx_recharge_requests_user_id (user_id),
    INDEX idx_recharge_requests_status (status),
    CONSTRAINT fk_recharge_requests_user_id FOREIGN KEY (user_id)
        REFERENCES users(user_id) ON DELETE CASCADE
);

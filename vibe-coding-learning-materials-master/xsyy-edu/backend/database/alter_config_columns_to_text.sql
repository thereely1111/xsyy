-- 修复：管理后台「系统配置」保存 500 的根因
-- system_configs.config_value 与 config_change_logs.old_value/new_value 原为 VARCHAR(255)，
-- 但首页公告(home_announcement_states)、订阅价格、返佣规则、邀请里程碑等配置值序列化后
-- 经常超过 255 字，写入时触发 MySQL "Data too long" -> 整个事务回滚 -> HTTP 500。
-- 模型层(database/models.py)已将对应列声明为 Text，此处把线上库列同步放宽到 TEXT。
--
-- 执行方式（在 MySQL 中执行本文件）：
--   mysql -u root -p test_xsyy < alter_config_columns_to_text.sql
-- 重复执行安全：MODIFY COLUMN 幂等。

ALTER TABLE system_configs
    MODIFY COLUMN config_value TEXT NOT NULL;

ALTER TABLE config_change_logs
    MODIFY COLUMN old_value TEXT NULL,
    MODIFY COLUMN new_value TEXT NOT NULL;

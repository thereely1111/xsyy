# 用户基础信息字段迁移说明

## 概述
本次迁移为用户表（`users`）添加以下字段：
- `email`: 邮箱地址（VARCHAR(100)，可为空，有索引）
- `grade`: 所在年级（VARCHAR(10)，可为空）
- `signature`: 个性签名（TEXT，可为空）

## 迁移方式

### 方式一：使用 Python 脚本（推荐）

```bash
cd backend
python database/add_user_profile_fields.py
```

### 方式二：使用 SQL 脚本

```bash
# Windows PowerShell
Get-Content backend/database/add_user_profile_fields.sql | mysql -u root -p your_database

# 或者直接执行
mysql -u root -p your_database < backend/database/add_user_profile_fields.sql
```

## 验证迁移

迁移完成后，可以执行以下 SQL 查询验证：

```sql
DESCRIBE users;
```

应该能看到新增的三个字段：
- `email` (在 `phone` 字段之后)
- `grade` (在 `password_hash` 字段之后)
- `signature` (在 `grade` 字段之后)

## 回滚（如果需要）

如果需要回滚，可以执行：

```sql
ALTER TABLE users DROP COLUMN signature;
ALTER TABLE users DROP COLUMN grade;
ALTER TABLE users DROP INDEX idx_users_email;
ALTER TABLE users DROP COLUMN email;
```

## 注意事项

1. 这些字段都是可选的（NULL），不会影响现有用户数据
2. 迁移脚本会自动检查字段是否已存在，可以安全地重复执行
3. 建议在迁移前备份数据库


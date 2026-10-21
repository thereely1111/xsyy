# 添加 view_count 字段迁移说明

## 概述
为了在 video.html 中显示真实的观看次数，需要在 `teachings` 表中添加 `view_count` 字段。

## 执行迁移

### 方法一：使用 Python 脚本（推荐，最简单）

在项目根目录下执行：

```bash
cd backend
python database/add_view_count_field.py
```

或者在项目根目录下：

```bash
python backend/database/add_view_count_field.py
```

这个脚本会自动：
- 检查字段是否已存在
- 如果不存在则添加字段
- 验证添加结果

### 方法二：使用 MySQL 命令行

**Windows PowerShell:**
```powershell
# 方式 A：使用 Get-Content 和管道
Get-Content backend/database/add_view_count_field.sql | mysql -u your_username -p your_database_name

# 方式 B：直接使用 -e 参数执行 SQL 语句
mysql -u your_username -p your_database_name -e "ALTER TABLE teachings ADD COLUMN view_count INT NOT NULL DEFAULT 0 AFTER preview_image;"
```

**Windows CMD 或 Linux/Mac:**
```bash
mysql -u your_username -p your_database_name < backend/database/add_view_count_field.sql
```

**注意：** 请将 `your_username` 和 `your_database_name` 替换为实际的用户名和数据库名。

### 方法二：使用 MySQL 客户端工具
1. 打开 MySQL 客户端（如 MySQL Workbench、phpMyAdmin 等）
2. 连接到数据库
3. 执行以下 SQL 语句：

```sql
ALTER TABLE teachings 
ADD COLUMN view_count INT NOT NULL DEFAULT 0 
AFTER preview_image;
```

### 方法三：如果字段已存在
如果执行时提示字段已存在，可以忽略该错误，或者先检查字段是否存在：

```sql
-- 检查字段是否存在
SHOW COLUMNS FROM teachings LIKE 'view_count';

-- 如果不存在，则添加
ALTER TABLE teachings 
ADD COLUMN view_count INT NOT NULL DEFAULT 0 
AFTER preview_image;
```

## 验证
执行迁移后，可以验证字段是否添加成功：

```sql
DESCRIBE teachings;
```

应该能看到 `view_count` 字段，类型为 `INT`，默认值为 `0`。

## 注意事项
- 如果数据库中已有数据，所有现有记录的 `view_count` 将被设置为 `0`
- 新创建的教学内容会自动初始化 `view_count` 为 `0`
- 每次访问 video.html 页面时，观看次数会自动增加


# XSYY 项目部署文档

## 一、服务器环境准备

### 1.1 系统要求

- 操作系统: OpenCloudOS 8.x
- Python: 3.9+
- MySQL: 5.7+ 或 8.0+
- Nginx: 1.18+

### 1.2 安装系统依赖

```bash
# 更新系统
sudo yum update -y

# 安装 Python 3.9 和开发工具
sudo yum install -y python39 python39-pip python39-devel gcc

# 安装 MySQL 客户端库
sudo yum install -y mysql-devel

# 安装 Nginx
sudo yum install -y nginx

# 安装其他必要工具
sudo yum install -y git
```

### 1.3 配置 MySQL 数据库

#### 1.3.1 连接腾讯云 TencentDB MySQL

在腾讯云控制台获取数据库连接信息：
- 主机地址
- 端口
- 数据库名
- 用户名
- 密码

#### 1.3.2 创建数据库和用户（如果需要）

```sql
CREATE DATABASE IF NOT EXISTS xsyy CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'xsyy_user'@'%' IDENTIFIED BY 'your_secure_password';
GRANT ALL PRIVILEGES ON xsyy.* TO 'xsyy_user'@'%';
FLUSH PRIVILEGES;
```

#### 1.3.3 执行数据库初始化脚本

```bash
# 连接到 MySQL 并执行 schema.sql
mysql -h your_host -u xsyy_user -p xsyy < /opt/xsyy/backend/database/schema.sql
```

## 二、项目部署

### 2.1 克隆项目代码

```bash
# 创建项目目录
sudo mkdir -p /opt/xsyy
sudo chown $USER:$USER /opt/xsyy

# 克隆代码（或上传代码包）
cd /opt/xsyy
git clone <your-repo-url> .
# 或使用 scp 上传代码包
```

### 2.2 配置 Python 虚拟环境

```bash
cd /opt/xsyy/backend

# 创建虚拟环境
python3.9 -m venv .venv

# 激活虚拟环境
source .venv/bin/activate

# 安装依赖
pip install --upgrade pip
pip install -r requirements.txt
```

### 2.3 配置环境变量

```bash
cd /opt/xsyy/backend

# 复制环境变量模板（如果存在）
cp .env.example .env

# 编辑环境变量文件
nano .env
```

在 `.env` 文件中配置：

```env
# 数据库连接
DATABASE_URL=mysql+pymysql://xsyy_user:your_password@your_host:3306/xsyy?charset=utf8mb4

# JWT 密钥（生产环境必须修改）
JWT_SECRET=your-very-secure-secret-key-change-this

# API 密钥
DEEPSEEK_API_KEY=your_deepseek_api_key
ZENMUX_API_KEY=your_zenmux_api_key

# 可选配置
DEEPSEEK_MODEL_NAME=deepseek-chat
# ZENMUX 图片生成模型（预览图）
ZENMUX_IMAGE_MODEL=google/gemini-3.1-flash-lite-image
# ZENMUX HTML 生成模型（交互式教学页面）
# 推荐低成本快速模型：google/gemini-3.1-flash-lite
ZENMUX_HTML_MODEL=google/gemini-3.1-flash-lite
# ZENMUX AI 助教回答模型
ZENMUX_RESPONSE_MODEL=google/gemini-3.1-flash-lite
```

### 2.4 初始化数据库

```bash
cd /opt/xsyy/backend
source .venv/bin/activate

# 初始化数据库表结构
python -c "from database import init_db; init_db()"

# 迁移现有数据（如果有）
python database/migrate.py
```

### 2.5 配置 systemd 服务

```bash
# 复制服务文件
sudo cp /opt/xsyy/deploy/xsyy-backend.service /etc/systemd/system/

# 修改服务文件中的路径（如果需要）
sudo nano /etc/systemd/system/xsyy-backend.service

# 重新加载 systemd
sudo systemctl daemon-reload

# 启动服务
sudo systemctl start xsyy-backend

# 设置开机自启
sudo systemctl enable xsyy-backend

# 查看服务状态
sudo systemctl status xsyy-backend
```

### 2.6 配置 Nginx

```bash
# 复制 Nginx 配置文件
sudo cp /opt/xsyy/deploy/nginx.conf /etc/nginx/sites-available/xsyy

# 编辑配置文件，修改域名或 IP
sudo nano /etc/nginx/sites-available/xsyy

# 创建软链接
sudo ln -s /etc/nginx/sites-available/xsyy /etc/nginx/sites-enabled/

# 测试 Nginx 配置
sudo nginx -t

# 启动 Nginx
sudo systemctl start nginx
sudo systemctl enable nginx
```

### 2.7 配置防火墙

```bash
# 开放 HTTP 和 HTTPS 端口
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload
```

## 三、服务管理

### 3.1 后端服务管理

```bash
# 启动服务
sudo systemctl start xsyy-backend

# 停止服务
sudo systemctl stop xsyy-backend

# 重启服务
sudo systemctl restart xsyy-backend

# 查看服务状态
sudo systemctl status xsyy-backend

# 查看日志
sudo journalctl -u xsyy-backend -f
```

### 3.2 Nginx 服务管理

```bash
# 启动 Nginx
sudo systemctl start nginx

# 停止 Nginx
sudo systemctl stop nginx

# 重启 Nginx
sudo systemctl restart nginx

# 重新加载配置（不中断服务）
sudo systemctl reload nginx

# 查看日志
sudo tail -f /var/log/nginx/xsyy_access.log
sudo tail -f /var/log/nginx/xsyy_error.log
```

## 四、数据迁移

### 4.1 迁移现有数据

如果项目已有 JSON 文件数据，使用迁移脚本：

```bash
cd /opt/xsyy/backend
source .venv/bin/activate
python database/migrate.py
```

迁移脚本会：
- 迁移 `users.json` 到 users 表
- 迁移 `storage/*/metadata.json` 到 teachings、comments、likes 表
- 保留文件存储（teaching.html、preview.png）在 storage 目录

## 五、故障排查

### 5.1 后端服务无法启动

1. 检查服务状态：
```bash
sudo systemctl status xsyy-backend
```

2. 查看详细日志：
```bash
sudo journalctl -u xsyy-backend -n 100
```

3. 检查环境变量：
```bash
sudo systemctl show xsyy-backend --property=Environment
```

4. 检查数据库连接：
```bash
cd /opt/xsyy/backend
source .venv/bin/activate
python -c "from database import engine; engine.connect()"
```

### 5.2 Nginx 502 错误

1. 检查后端服务是否运行：
```bash
sudo systemctl status xsyy-backend
```

2. 检查后端服务端口：
```bash
sudo netstat -tlnp | grep 8000
```

3. 检查 Nginx 错误日志：
```bash
sudo tail -f /var/log/nginx/xsyy_error.log
```

### 5.3 数据库连接失败

1. 检查数据库连接字符串：
```bash
cat /opt/xsyy/backend/.env | grep DATABASE_URL
```

2. 测试数据库连接：
```bash
mysql -h your_host -u xsyy_user -p xsyy
```

3. 检查防火墙规则（如果数据库在远程服务器）

### 5.4 文件权限问题

```bash
# 确保 storage 目录有写权限
sudo chown -R www-data:www-data /opt/xsyy/storage
sudo chmod -R 755 /opt/xsyy/storage

# 确保 web 目录有读权限
sudo chown -R www-data:www-data /opt/xsyy/web
sudo chmod -R 755 /opt/xsyy/web
```

## 六、性能优化

### 6.1 数据库优化

- 定期清理过期验证码
- 为常用查询字段添加索引
- 定期备份数据库

### 6.2 Nginx 优化

- 启用 gzip 压缩
- 配置静态文件缓存
- 调整 worker 进程数

### 6.3 后端服务优化

- 根据服务器配置调整 uvicorn workers 数量
- 配置数据库连接池大小
- 监控内存和 CPU 使用情况

## 七、备份与恢复

### 7.1 数据库备份

```bash
# 备份数据库
mysqldump -h your_host -u xsyy_user -p xsyy > xsyy_backup_$(date +%Y%m%d).sql

# 恢复数据库
mysql -h your_host -u xsyy_user -p xsyy < xsyy_backup_20231203.sql
```

### 7.2 文件备份

```bash
# 备份 storage 目录
tar -czf storage_backup_$(date +%Y%m%d).tar.gz /opt/xsyy/storage
```

## 八、安全建议

1. **修改默认密钥**：确保 `.env` 文件中的 `JWT_SECRET` 是强随机字符串
2. **数据库安全**：使用强密码，限制数据库用户权限
3. **防火墙配置**：只开放必要的端口
4. **HTTPS 配置**：生产环境建议配置 SSL 证书
5. **定期更新**：保持系统和依赖包的最新版本

## 九、监控与日志

### 9.1 日志位置

- 后端服务日志：`journalctl -u xsyy-backend`
- Nginx 访问日志：`/var/log/nginx/xsyy_access.log`
- Nginx 错误日志：`/var/log/nginx/xsyy_error.log`

### 9.2 监控建议

- 使用 systemd 监控服务状态
- 配置日志轮转
- 监控数据库连接数
- 监控磁盘空间使用


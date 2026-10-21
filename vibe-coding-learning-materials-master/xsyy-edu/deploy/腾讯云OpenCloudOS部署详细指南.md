# 腾讯云 OpenCloudOS 部署详细指南

## 一、部署前准备

### 1.1 服务器准备
- 已购买腾讯云轻量应用服务器（OpenCloudOS 系统）
- 已获取服务器公网 IP 地址
- 已获取 root 密码或 SSH 密钥
- 建议配置：2核2GB以上，带宽5Mbps以上

### 1.2 数据库准备
- 已创建腾讯云 TencentDB MySQL 实例（或使用服务器本地 MySQL）
- 已获取数据库连接信息：
  - 主机地址（如：cdb-xxxxx.sql.tencentcdb.com 或 localhost）
  - 端口（通常为 3306）
  - 数据库名（建议：xsyy）
  - 用户名和密码

### 1.3 API 密钥准备
- DeepSeek API 密钥（https://platform.deepseek.com/）
- Google Gemini API 密钥（https://ai.google.dev/）

### 1.4 域名准备（可选）
- 已购买域名（如：xsyy.example.com）
- 已配置域名解析到服务器 IP

---

## 二、本地准备工作

### 2.1 准备项目文件
在本地电脑上，确保项目代码完整，包括：
- `backend/` 目录（后端代码）
- `web/` 目录（前端代码）
- `deploy/` 目录（部署配置文件）
- `storage/` 目录（可选，已有数据）

### 2.2 准备上传工具
- Windows：使用 WinSCP、FileZilla 或 PowerShell 的 `scp` 命令
- Mac/Linux：使用 `scp` 或 `rsync` 命令

---

## 三、服务器环境配置

### 3.1 连接服务器

**方式一：使用 SSH 客户端（推荐）**
```bash
# Windows 使用 PowerShell 或 CMD
ssh root@你的服务器IP

# 输入密码后回车
```

**方式二：使用腾讯云控制台**
- 登录腾讯云控制台
- 进入轻量应用服务器管理页面
- 点击"登录"按钮，使用 Web Shell

### 3.2 更新系统

```bash
# 更新系统包
sudo yum update -y

# 安装基础工具
sudo yum install -y wget curl vim git
```

### 3.3 安装 Python 3.9

```bash
# 安装 Python 3.9 和 pip
sudo yum install -y python39 python39-pip python39-devel

# 验证安装
python3.9 --version
pip3.9 --version

# 创建 python3 和 pip3 的软链接（如果不存在）
sudo alternatives --install /usr/bin/python3 python3 /usr/bin/python3.9 1
sudo alternatives --install /usr/bin/pip3 pip3 /usr/bin/pip3.9 1
```

### 3.4 安装编译工具

```bash
# 安装 GCC 等编译工具（用于编译 Python 包）
sudo yum groupinstall -y "Development Tools"
sudo yum install -y gcc gcc-c++ make
```

### 3.5 安装 MySQL 客户端库

```bash
# 安装 MySQL 开发库（用于连接数据库）
sudo yum install -y mysql-devel
```

### 3.6 安装 Nginx

```bash
# 安装 Nginx
sudo yum install -y nginx

# 启动 Nginx（先测试，稍后配置）
sudo systemctl start nginx
sudo systemctl enable nginx

# 检查状态
sudo systemctl status nginx
```

### 3.7 安装 Node.js（画法模板库用）

画法模板路由（`backend/template_router.py`）在装配/验收动画模板时调用 `node 装配器.js` /
`node 验收器.js`。这两个脚本只用 Node 内置模块（`fs` / `path` / `vm`），**不需要 npm install**，
但服务器必须装有 Node.js，否则模板路由会静默降级（不影响主流程，只是用不上冻结模板）。

```bash
# OpenCloudOS / CentOS 系：加 NodeSource 源后安装
curl -fsSL https://rpm.nodesource.com/setup_20.x | sudo bash -
sudo yum install -y nodejs

# 验证（应输出版本号，例如 v20.x.x）
node -v

# 若 node 不在 PATH 中，在 backend/.env 里指定绝对路径：
#   ANIM_TEMPLATE_NODE_BIN=/usr/bin/node
```

---

## 四、上传项目文件

### 4.1 创建项目目录

```bash
# 在服务器上创建项目目录
sudo mkdir -p /opt/xsyy
sudo chown $USER:$USER /opt/xsyy
```

### 4.2 上传项目文件

**方式一：使用 SCP（从本地 Windows）**

在本地电脑的 PowerShell 或 CMD 中执行：

```powershell
# 进入项目目录
cd D:\nick\大模型应用工程师\XSYY

# 上传整个项目（排除虚拟环境和缓存）
# 注意：Windows PowerShell 的 scp 可能不支持 --exclude，建议使用 WinSCP
scp -r . root@你的服务器IP:/opt/xsyy/
```

**方式二：使用 WinSCP（图形界面，推荐新手）**

1. 下载并安装 WinSCP：https://winscp.net/
2. 打开 WinSCP，新建连接：
   - 文件协议：SFTP
   - 主机名：你的服务器IP
   - 用户名：root
   - 密码：你的服务器密码
3. 连接后，将本地项目文件夹拖拽到服务器的 `/opt/xsyy/` 目录
4. **注意：** 上传时排除以下目录和文件：
   - `.venv/`（Python 虚拟环境）
   - `__pycache__/`（Python 缓存）
   - `*.pyc`（Python 编译文件）
   - `chroma_db/`（向量数据库，会在服务器上重新生成）

**方式三：使用 Git（如果项目在 Git 仓库）**

```bash
# 在服务器上执行
cd /opt/xsyy
git clone <你的Git仓库地址> .
```

### 4.3 验证文件上传

```bash
# 检查文件是否上传成功
ls -la /opt/xsyy
# 应该看到 backend/, web/, deploy/ 等目录
```

---

## 五、配置 Python 环境

### 5.1 创建虚拟环境

```bash
cd /opt/xsyy/backend

# 创建虚拟环境
python3.9 -m venv .venv

# 激活虚拟环境
source .venv/bin/activate

# 验证（命令提示符前应该显示 (.venv)）
which python
# 应该显示：/opt/xsyy/backend/.venv/bin/python
```

### 5.2 升级 pip

```bash
# 确保在虚拟环境中
pip install --upgrade pip setuptools wheel
```

### 5.3 安装项目依赖

```bash
# 确保在虚拟环境中，且当前目录是 /opt/xsyy/backend
pip install -r requirements.txt

# 这个过程可能需要 5-10 分钟，请耐心等待
# 如果遇到网络问题，可以使用国内镜像：
# pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

**注意：** 如果安装 `torch` 或 `sentence-transformers` 时出错，可能需要：

```bash
# 安装 CPU 版本的 PyTorch（更小更快）
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
```

---

## 六、配置环境变量

### 6.1 创建 .env 文件

```bash
cd /opt/xsyy/backend

# 复制模板文件
cp env.example .env

# 编辑配置文件
nano .env
```

### 6.2 填写配置信息

在编辑器中填入以下内容（按实际情况修改）：

```env
# 数据库连接配置
# 格式：mysql+pymysql://用户名:密码@主机:端口/数据库名?charset=utf8mb4
# 示例（腾讯云 TencentDB）：
DATABASE_URL=mysql+pymysql://root:你的数据库密码@cdb-xxxxx.sql.tencentcdb.com:3306/xsyy?charset=utf8mb4
# 示例（本地 MySQL）：
# DATABASE_URL=mysql+pymysql://root:你的数据库密码@localhost:3306/xsyy?charset=utf8mb4

# JWT 密钥（必须修改为随机字符串）
# 生成随机密钥：openssl rand -hex 32
JWT_SECRET=生成的随机32位十六进制字符串

# DeepSeek API 密钥
DEEPSEEK_API_KEY=你的DeepSeek_API密钥

# Gemini API 密钥
GEMINI_API_KEY=你的Gemini_API密钥

# 可选配置
DEEPSEEK_MODEL_NAME=deepseek-chat
GEMINI_MODEL_NAME=gemini-3-pro-preview

# Embedding 模型本地路径（如果使用 ONNX）
EMBEDDING_MODEL_LOCAL_PATH=/opt/xsyy/backend/models/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
EMBEDDING_MODEL_FORMAT=onnx
```

**重要提示：**
- `DATABASE_URL` 中的密码如果包含特殊字符，需要进行 URL 编码
- `JWT_SECRET` 必须修改，可以使用命令生成：`openssl rand -hex 32`

### 6.3 保存并退出

在 nano 编辑器中：
- 按 `Ctrl + O` 保存
- 按 `Enter` 确认
- 按 `Ctrl + X` 退出

---

## 七、配置数据库

### 7.1 创建数据库

**如果使用腾讯云 TencentDB：**
- 在腾讯云控制台创建数据库实例
- 创建数据库 `xsyy`（字符集：utf8mb4，排序规则：utf8mb4_unicode_ci）

**如果使用本地 MySQL：**

```bash
# 安装 MySQL（如果还没有）
sudo yum install -y mariadb-server mariadb
sudo systemctl start mariadb
sudo systemctl enable mariadb

# 设置 MySQL root 密码
sudo mysql_secure_installation

# 登录 MySQL
mysql -u root -p

# 在 MySQL 中执行
CREATE DATABASE IF NOT EXISTS xsyy CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'xsyy_user'@'localhost' IDENTIFIED BY '你的数据库密码';
GRANT ALL PRIVILEGES ON xsyy.* TO 'xsyy_user'@'localhost';
FLUSH PRIVILEGES;
EXIT;
```

### 7.2 初始化数据库表结构

```bash
cd /opt/xsyy/backend
source .venv/bin/activate

# 使用 Python 脚本初始化（推荐）
python init_database.py

# 如果失败，使用 SQL 脚本
# mysql -h 你的数据库主机 -u 用户名 -p xsyy < database/schema.sql
```

### 7.3 迁移现有数据（如果有）

```bash
cd /opt/xsyy/backend
source .venv/bin/activate

# 迁移数据
python database/migrate.py

# 如果数据在 storage 目录，确保 storage 目录存在
ls -la /opt/xsyy/storage
```

---

## 八、配置 systemd 服务

### 8.1 创建服务用户（如果不存在）

```bash
# 检查 www-data 用户是否存在
id www-data

# 如果不存在，创建用户
sudo groupadd -r www-data
sudo useradd -r -g www-data -s /bin/false www-data
```

### 8.2 复制服务文件

```bash
# 复制服务文件
sudo cp /opt/xsyy/deploy/xsyy-backend.service /etc/systemd/system/

# 编辑服务文件（检查路径是否正确）
sudo nano /etc/systemd/system/xsyy-backend.service
```

### 8.3 修改服务文件

确保以下路径正确：
- `WorkingDirectory=/opt/xsyy/backend`
- `ExecStart=/opt/xsyy/backend/.venv/bin/uvicorn app:app --host 0.0.0.0 --port 8000 --workers 4`
- `EnvironmentFile=/opt/xsyy/backend/.env`

**注意：** 如果服务器内存较小（< 4GB），可以将 `--workers 4` 改为 `--workers 2`

### 8.4 启动服务

```bash
# 重新加载 systemd
sudo systemctl daemon-reload

# 启动服务
sudo systemctl start xsyy-backend

# 设置开机自启
sudo systemctl enable xsyy-backend

# 查看服务状态
sudo systemctl status xsyy-backend
```

### 8.5 查看服务日志

```bash
# 查看实时日志
sudo journalctl -u xsyy-backend -f

# 查看最近 100 条日志
sudo journalctl -u xsyy-backend -n 100

# 如果服务启动失败，查看详细错误
sudo journalctl -u xsyy-backend -n 200 --no-pager
```

### 8.6 测试后端 API

```bash
# 测试健康检查接口
curl http://localhost:8000/api/health

# 应该返回：{"status":"ok"}
```

---

## 九、配置 Nginx

### 9.1 复制配置文件

```bash
# 创建 sites-available 目录（如果不存在）
sudo mkdir -p /etc/nginx/sites-available
sudo mkdir -p /etc/nginx/sites-enabled

# 复制配置文件
sudo cp /opt/xsyy/deploy/nginx.conf /etc/nginx/sites-available/xsyy

# 编辑配置文件
sudo nano /etc/nginx/sites-available/xsyy
```

### 9.2 修改 Nginx 配置

找到这一行并修改：
```nginx
server_name your-domain.com;  # 改为你的域名或服务器IP
```

如果没有域名，改为：
```nginx
server_name 你的服务器IP;
```

### 9.3 创建软链接

```bash
# 创建软链接
sudo ln -s /etc/nginx/sites-available/xsyy /etc/nginx/sites-enabled/

# 检查 Nginx 主配置文件，确保包含 sites-enabled
sudo nano /etc/nginx/nginx.conf
```

在 `http` 块中添加（如果还没有）：
```nginx
include /etc/nginx/sites-enabled/*;
```

### 9.4 测试并启动 Nginx

```bash
# 测试配置
sudo nginx -t

# 如果测试通过，启动 Nginx
sudo systemctl start nginx
sudo systemctl enable nginx

# 查看状态
sudo systemctl status nginx
```

---

## 十、配置防火墙

### 10.1 开放端口

```bash
# 检查防火墙状态
sudo systemctl status firewalld

# 如果防火墙未运行，启动它
sudo systemctl start firewalld
sudo systemctl enable firewalld

# 开放 HTTP 端口（80）
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-port=80/tcp

# 如果使用 HTTPS，开放 HTTPS 端口（443）
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --permanent --add-port=443/tcp

# 重新加载防火墙
sudo firewall-cmd --reload

# 查看开放的端口
sudo firewall-cmd --list-all
```

### 10.2 腾讯云安全组配置

在腾讯云控制台：
1. 进入轻量应用服务器管理页面
2. 点击"防火墙"标签
3. 添加规则：
   - 协议：TCP
   - 端口：80
   - 策略：允许
   - 来源：0.0.0.0/0

---

## 十一、设置文件权限

```bash
# 设置 storage 目录权限（需要写权限）
sudo chown -R www-data:www-data /opt/xsyy/storage
sudo chmod -R 775 /opt/xsyy/storage

# 设置 web 目录权限（只需要读权限）
sudo chown -R www-data:www-data /opt/xsyy/web
sudo chmod -R 755 /opt/xsyy/web

# 设置 backend 目录权限
sudo chown -R www-data:www-data /opt/xsyy/backend
sudo chmod -R 755 /opt/xsyy/backend

# 确保 .env 文件只有所有者可读
sudo chmod 600 /opt/xsyy/backend/.env
```

---

## 十二、验证部署

### 12.1 检查服务状态

```bash
# 检查后端服务
sudo systemctl status xsyy-backend

# 检查 Nginx
sudo systemctl status nginx

# 检查端口监听
sudo netstat -tlnp | grep 8000  # 后端服务
sudo netstat -tlnp | grep 80    # Nginx
```

### 12.2 测试 API

```bash
# 在服务器上测试
curl http://localhost:8000/api/health

# 从外部测试（在本地电脑浏览器中）
http://你的服务器IP/api/health
```

### 12.3 访问网站

在浏览器中访问：
- `http://你的服务器IP` 或
- `http://你的域名`

应该能看到网站首页。

---

## 十三、常见问题排查

### 问题 1：后端服务无法启动

**排查步骤：**
```bash
# 1. 查看服务状态
sudo systemctl status xsyy-backend

# 2. 查看详细日志
sudo journalctl -u xsyy-backend -n 200 --no-pager

# 3. 检查环境变量文件
cat /opt/xsyy/backend/.env

# 4. 手动测试启动
cd /opt/xsyy/backend
source .venv/bin/activate
python -c "from app import app; print('OK')"
```

**常见错误及解决方法：**
- `ModuleNotFoundError`：运行 `pip install -r requirements.txt`
- 数据库连接失败：检查 `.env` 中的 `DATABASE_URL`
- 端口被占用：`sudo lsof -i :8000` 查看占用进程

### 问题 2：Nginx 502 Bad Gateway

**排查步骤：**
```bash
# 1. 确认后端服务运行
sudo systemctl status xsyy-backend

# 2. 测试后端 API
curl http://localhost:8000/api/health

# 3. 查看 Nginx 错误日志
sudo tail -f /var/log/nginx/xsyy_error.log

# 4. 检查 Nginx 配置
sudo nginx -t
```

### 问题 3：数据库连接失败

**排查步骤：**
```bash
# 1. 测试数据库连接
mysql -h 你的数据库主机 -u 用户名 -p xsyy

# 2. 检查防火墙（如果数据库在远程）
# 在腾讯云控制台检查安全组规则

# 3. 检查数据库用户权限
# 在 MySQL 中执行：SHOW GRANTS FOR '用户名'@'%';
```

### 问题 4：文件权限问题

```bash
# 重新设置权限
sudo chown -R www-data:www-data /opt/xsyy
sudo chmod -R 755 /opt/xsyy
sudo chmod -R 775 /opt/xsyy/storage
```

---

## 十四、后续维护

### 14.1 更新代码

```bash
cd /opt/xsyy
# 如果使用 Git
git pull

# 如果使用文件上传，重新上传文件

# 重启服务
sudo systemctl restart xsyy-backend
sudo systemctl reload nginx
```

### 14.2 查看日志

```bash
# 后端服务日志
sudo journalctl -u xsyy-backend -f

# Nginx 访问日志
sudo tail -f /var/log/nginx/xsyy_access.log

# Nginx 错误日志
sudo tail -f /var/log/nginx/xsyy_error.log
```

### 14.3 备份数据

```bash
# 备份数据库
mysqldump -h 你的数据库主机 -u 用户名 -p xsyy > /root/xsyy_backup_$(date +%Y%m%d).sql

# 备份文件
tar -czf /root/storage_backup_$(date +%Y%m%d).tar.gz /opt/xsyy/storage
```

---

## 十五、安全建议

1. **修改 SSH 端口**（可选）
2. **使用 SSH 密钥登录**（推荐）
3. **定期更新系统**：`sudo yum update -y`
4. **配置 HTTPS**（使用 Let's Encrypt 免费证书）
5. **定期备份数据库和文件**
6. **监控服务器资源使用情况**

---

## 完成！

如果所有步骤都成功完成，你的项目应该已经部署到服务器上了！

访问 `http://你的服务器IP` 即可使用。


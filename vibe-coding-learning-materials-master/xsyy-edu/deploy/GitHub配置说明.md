# GitHub Actions 配置说明

## 📋 什么是 GitHub Actions？

**简单理解**：GitHub Actions 是一个自动化工具，当你把代码推送到 GitHub 后，它可以自动帮你执行一些操作，比如：
- 自动测试代码
- 自动部署到服务器
- 自动发送通知

**就像**：你设置了一个机器人，每次你上传代码，机器人就自动帮你把代码部署到服务器。

---

## 🔐 配置 GitHub Secrets（重要！）

### 什么是 Secrets？

**Secrets** 就是"秘密信息"，比如：
- 服务器的密码
- SSH 密钥
- API 密钥

这些信息不能公开，所以 GitHub 提供了 Secrets 功能来安全存储。

### 如何配置？

#### 步骤 1: 打开 GitHub 仓库设置

1. 打开你的 GitHub 仓库页面
2. 点击右上角的 **Settings**（设置）
3. 在左侧菜单找到 **Secrets and variables** → **Actions**

#### 步骤 2: 添加 Secrets

点击 **New repository secret**（新建仓库密钥），添加以下信息：

##### 开发环境 Secrets

| Secret 名称 | 说明 | 示例 |
|------------|------|------|
| `DEV_HOST` | 开发服务器 IP 地址 | `192.168.1.100` |
| `DEV_USER` | 开发服务器用户名 | `ubuntu` 或 `root` |
| `DEV_SSH_KEY` | SSH 私钥（见下方说明） | `-----BEGIN OPENSSH PRIVATE KEY-----...` |

##### 生产环境 Secrets

| Secret 名称 | 说明 | 示例 |
|------------|------|------|
| `PROD_HOST` | 生产服务器 IP 地址 | `123.456.789.0` |
| `PROD_USER` | 生产服务器用户名 | `ubuntu` 或 `root` |
| `PROD_SSH_KEY` | SSH 私钥（见下方说明） | `-----BEGIN OPENSSH PRIVATE KEY-----...` |

---

## 🔑 生成 SSH 密钥（如果还没有）

### 什么是 SSH 密钥？

SSH 密钥是一对文件（公钥和私钥），用于安全地连接服务器：
- **公钥**（`.pub` 文件）：放在服务器上，允许持有对应私钥的人连接
- **私钥**（无扩展名文件）：放在 GitHub Secrets 中，GitHub Actions 使用它来连接服务器

**简单理解**：公钥像门锁，私钥像钥匙。你把门锁（公钥）装在服务器上，GitHub Actions 用钥匙（私钥）来开门。

### 在本地电脑上生成

```bash
# 1. 生成 SSH 密钥对
ssh-keygen -t ed25519 -C "github-actions" -f ~/.ssh/github_actions

# 按 Enter 使用默认路径
# 设置密码（可选，直接 Enter 跳过）

# 2. 查看公钥（需要添加到服务器）
cat ~/.ssh/github_actions.pub
# 复制输出的全部内容，稍后需要添加到服务器

# 3. 查看私钥（需要添加到 GitHub Secrets）
cat ~/.ssh/github_actions
# 复制输出的全部内容，稍后需要添加到 GitHub Secrets
```

### 将公钥添加到服务器

**重要**：根据你的服务器配置，选择以下方案之一：

#### 方案 A：只有一台服务器（开发和生产共用）

如果开发环境和生产环境在同一台服务器上：

```bash
# 1. SSH 连接到你的服务器
ssh user@your_server_ip

# 2. 在服务器上执行
mkdir -p ~/.ssh
chmod 700 ~/.ssh

# 3. 将公钥内容添加到 authorized_keys
#    将之前复制的公钥内容（github_actions.pub）粘贴到这里
echo "你的公钥内容" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

#### 方案 B：有两台服务器（开发和生产分开）

**如果使用同一个密钥对**（推荐，简单）：

```bash
# 1. 在开发服务器上执行
ssh dev_user@dev_server_ip
mkdir -p ~/.ssh
chmod 700 ~/.ssh
echo "你的公钥内容" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys

# 2. 在生产服务器上执行
ssh prod_user@prod_server_ip
mkdir -p ~/.ssh
chmod 700 ~/.ssh
echo "你的公钥内容" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

**如果使用不同的密钥对**（更安全，但需要生成两个密钥对）：

```bash
# 1. 生成开发环境密钥对
ssh-keygen -t ed25519 -C "github-actions-dev" -f ~/.ssh/github_actions_dev

# 2. 生成生产环境密钥对
ssh-keygen -t ed25519 -C "github-actions-prod" -f ~/.ssh/github_actions_prod

# 3. 在开发服务器上添加开发公钥
ssh dev_user@dev_server_ip
echo "开发环境公钥内容" >> ~/.ssh/authorized_keys

# 4. 在生产服务器上添加生产公钥
ssh prod_user@prod_server_ip
echo "生产环境公钥内容" >> ~/.ssh/authorized_keys
```

### 将私钥添加到 GitHub Secrets

1. **复制私钥内容**：
   - 如果使用同一个密钥对：复制 `~/.ssh/github_actions` 文件的全部内容
   - 如果使用不同的密钥对：分别复制 `~/.ssh/github_actions_dev` 和 `~/.ssh/github_actions_prod` 的内容

2. **在 GitHub 仓库的 Secrets 中添加**：
   - 打开 GitHub 仓库 → Settings → Secrets and variables → Actions
   - 点击 "New repository secret"
   - **Secret 名称**：`DEV_SSH_KEY`（开发环境）或 `PROD_SSH_KEY`（生产环境）
   - **Secret 值**：粘贴对应的私钥内容（包括 `-----BEGIN OPENSSH PRIVATE KEY-----` 和 `-----END OPENSSH PRIVATE KEY-----` 之间的所有内容）

3. **注意事项**：
   - 如果使用同一个密钥对，`DEV_SSH_KEY` 和 `PROD_SSH_KEY` 可以使用相同的私钥内容
   - 如果使用不同的密钥对，需要分别使用对应的私钥内容

---

## ✅ 测试配置

### 测试 SSH 连接

在本地电脑上测试：

```bash
# 测试开发服务器连接
ssh -i ~/.ssh/github_actions dev_user@dev_host

# 测试生产服务器连接
ssh -i ~/.ssh/github_actions prod_user@prod_host
```

### 测试 GitHub Actions

1. 修改代码并提交
2. 推送到 `develop` 分支
3. 在 GitHub 仓库页面点击 **Actions** 标签
4. 查看部署是否成功

---

## 🔍 查看部署日志

### 在 GitHub 上查看

1. 打开仓库页面
2. 点击 **Actions** 标签
3. 点击最新的工作流运行
4. 查看详细日志

### 在服务器上查看

```bash
# 查看部署日志
tail -f /opt/xsyy/deploy.log

# 查看服务日志
sudo journalctl -u xsyy-backend -f
```

---

## ⚠️ 安全建议

1. **不要将 Secrets 提交到代码仓库**
   - 永远不要把密码、密钥写在代码里
   - 使用 GitHub Secrets 存储

2. **定期更换 SSH 密钥**
   - 建议每 3-6 个月更换一次

3. **限制 SSH 访问**
   - 只允许特定 IP 访问
   - 使用强密码

4. **使用不同的密钥**
   - 开发环境和生产环境使用不同的 SSH 密钥

---

## 🆘 常见问题

### Q: GitHub Actions 显示连接失败

**A**: 检查：
1. SSH 密钥是否正确配置
2. 服务器 IP 地址是否正确
3. 服务器防火墙是否开放 SSH 端口（22）

### Q: 部署脚本没有执行权限

**A**: 在服务器上执行：
```bash
chmod +x /opt/xsyy/deploy/*.sh
```

### Q: 如何手动触发部署？

**A**: 
1. 在 GitHub 仓库页面点击 **Actions**
2. 选择 **Deploy XSYY** 工作流
3. 点击 **Run workflow**
4. 选择环境（dev 或 prod）
5. 点击 **Run workflow**

---

## 📚 下一步

配置完成后：
1. 查看 `快速开始.md` 了解如何使用
2. 查看 `代码更新完整指南.md` 了解详细流程
3. 尝试推送代码，观察自动部署


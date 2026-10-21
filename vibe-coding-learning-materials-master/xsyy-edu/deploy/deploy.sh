#!/bin/bash
# ============================================
# XSYY 项目自动化部署脚本
# 使用方法: ./deploy.sh [dev|prod] [version]
# 示例: ./deploy.sh dev latest
#       ./deploy.sh prod v1.0.1
# ============================================

set -e  # 遇到错误立即退出，防止继续执行导致更严重的问题

# ============================================
# 配置部分（根据实际情况修改）
# ============================================
ENV=${1:-dev}  # 默认开发环境，可以通过参数指定 dev 或 prod
VERSION=${2:-latest}  # 默认最新版本，可以指定具体的版本号或分支名
PROJECT_DIR="/opt/xsyy"  # 项目在服务器上的目录
BACKEND_DIR="$PROJECT_DIR/backend"
WEB_DIR="$PROJECT_DIR/web"
BACKUP_DIR="$PROJECT_DIR/backups"
LOG_FILE="$PROJECT_DIR/deploy.log"

# 颜色输出（让日志更清晰）
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 日志函数
log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1" | tee -a "$LOG_FILE"
}

log_error() {
    echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')] 错误:${NC} $1" | tee -a "$LOG_FILE"
}

log_warn() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')] 警告:${NC} $1" | tee -a "$LOG_FILE"
}

# ============================================
# 开始部署
# ============================================
log "=========================================="
log "XSYY 项目部署脚本启动"
log "环境: $ENV"
log "版本: $VERSION"
log "项目目录: $PROJECT_DIR"
log "=========================================="

# 检查项目目录是否存在
if [ ! -d "$PROJECT_DIR" ]; then
    log_error "项目目录不存在: $PROJECT_DIR"
    exit 1
fi

cd "$PROJECT_DIR"

# ============================================
# 步骤 1: 备份当前版本（非常重要！）
# ============================================
log "步骤 1: 开始备份当前版本..."

# 创建备份目录
BACKUP_TIMESTAMP=$(date +%Y%m%d_%H%M%S)
CURRENT_BACKUP_DIR="$BACKUP_DIR/$BACKUP_TIMESTAMP"
mkdir -p "$CURRENT_BACKUP_DIR"

# 备份代码（排除不需要的文件）
log "  备份代码文件..."
tar -czf "$CURRENT_BACKUP_DIR/code.tar.gz" \
    -C "$PROJECT_DIR" \
    backend web \
    --exclude='.venv' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.git' \
    --exclude='node_modules' 2>/dev/null || log_warn "代码备份可能不完整"

# 备份数据库（仅生产环境）
if [ "$ENV" = "prod" ]; then
    log "  备份数据库..."
    # 从 .env 文件读取数据库信息（需要根据实际情况调整）
    if [ -f "$BACKEND_DIR/.env" ]; then
        # 尝试备份数据库（如果配置了数据库连接）
        DB_BACKUP_FILE="$CURRENT_BACKUP_DIR/database.sql"
        # 这里需要根据实际的数据库配置来执行备份
        # 示例：mysqldump -h host -u user -p password database > "$DB_BACKUP_FILE"
        log_warn "数据库备份需要手动配置，请参考部署文档"
    fi
fi

log "✓ 备份完成: $CURRENT_BACKUP_DIR"

# ============================================
# 步骤 2: 拉取最新代码
# ============================================
log "步骤 2: 拉取最新代码..."

# 检查是否是 Git 仓库
if [ ! -d "$PROJECT_DIR/.git" ]; then
    log_error "不是 Git 仓库，无法拉取代码"
    exit 1
fi

# 保存当前分支
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
log "  当前分支: $CURRENT_BRANCH"

# 拉取最新代码
git fetch origin

# 切换到指定版本或分支
if [ "$VERSION" != "latest" ]; then
    # 如果指定了版本，尝试切换到该版本
    if git rev-parse --verify "$VERSION" >/dev/null 2>&1; then
        git checkout "$VERSION"
        log "  已切换到版本: $VERSION"
    else
        log_warn "版本 $VERSION 不存在，使用当前分支"
    fi
else
    # 根据环境选择分支
    if [ "$ENV" = "prod" ]; then
        git checkout main || git checkout master
        git pull origin main || git pull origin master
        log "  已切换到 main/master 分支"
    else
        git checkout develop
        git pull origin develop
        log "  已切换到 develop 分支"
    fi
fi

# 获取当前版本信息
CURRENT_VERSION=$(git describe --tags --always 2>/dev/null || git rev-parse --short HEAD)
log "  当前代码版本: $CURRENT_VERSION"

# ============================================
# 步骤 3: 更新 Python 依赖
# ============================================
log "步骤 3: 更新 Python 依赖..."

cd "$BACKEND_DIR"

# 检查虚拟环境
if [ ! -d ".venv" ]; then
    log "  创建虚拟环境..."
    python3 -m venv .venv
fi

# 激活虚拟环境
source .venv/bin/activate

# 升级 pip
log "  升级 pip..."
pip install --upgrade pip --quiet

# 安装依赖
log "  安装 Python 依赖包..."
pip install -r requirements.txt --quiet

log "✓ Python 依赖更新完成"

# ============================================
# 步骤 4: 运行数据库迁移
# ============================================
log "步骤 4: 运行数据库迁移..."

# 初始化数据库（如果表不存在）
log "  检查数据库表结构..."
python -c "from database import init_db; init_db()" 2>/dev/null || log_warn "数据库初始化跳过（可能已存在）"

# 运行迁移脚本（如果存在）
if [ -f "database/migrate.py" ]; then
    log "  运行数据迁移脚本..."
    python database/migrate.py || log_warn "数据迁移跳过"
fi

# 运行其他迁移脚本
for migration in database/*.py; do
    if [ -f "$migration" ] && [[ "$migration" == *"migrate"* ]] || [[ "$migration" == *"update"* ]]; then
        if [ "$migration" != "database/migrate.py" ] && [ "$migration" != "database/__init__.py" ]; then
            log "  运行迁移: $migration"
            python "$migration" || log_warn "迁移 $migration 失败，跳过"
        fi
    fi
done

log "✓ 数据库迁移完成"

# ============================================
# 步骤 5: 重启服务
# ============================================
log "步骤 5: 重启服务..."

if [ "$ENV" = "prod" ]; then
    # 生产环境：使用 systemd 服务
    log "  重启 systemd 服务..."
    sudo systemctl restart xsyy-backend || log_error "服务重启失败"
    
    # 重新加载 Nginx 配置（如果需要）
    if systemctl is-active --quiet nginx; then
        sudo systemctl reload nginx
        log "  Nginx 配置已重新加载"
    fi
else
    # 开发环境：直接重启 uvicorn
    log "  重启 uvicorn 服务..."
    pkill -f "uvicorn app:app" || true
    sleep 2
    nohup uvicorn app:app --host 0.0.0.0 --port 8000 --reload > /tmp/xsyy-backend.log 2>&1 &
    log "  uvicorn 已在后台启动"
fi

log "✓ 服务重启完成"

# ============================================
# 步骤 6: 健康检查
# ============================================
log "步骤 6: 健康检查..."

# 等待服务启动
log "  等待服务启动（5秒）..."
sleep 5

# 检查服务是否正常运行
MAX_RETRIES=5
RETRY_COUNT=0
SERVICE_OK=false

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if curl -f http://localhost:8000/api/health > /dev/null 2>&1; then
        SERVICE_OK=true
        break
    fi
    RETRY_COUNT=$((RETRY_COUNT + 1))
    log "  服务未就绪，重试 $RETRY_COUNT/$MAX_RETRIES..."
    sleep 3
done

if [ "$SERVICE_OK" = true ]; then
    log "✓ 服务启动成功，健康检查通过"
else
    log_error "服务启动失败，健康检查未通过"
    log_error "开始回滚到上一个版本..."
    
    # ============================================
    # 回滚操作
    # ============================================
    log "回滚: 恢复代码..."
    cd "$PROJECT_DIR"
    tar -xzf "$CURRENT_BACKUP_DIR/code.tar.gz" -C "$PROJECT_DIR"
    
    log "回滚: 重启服务..."
    if [ "$ENV" = "prod" ]; then
        sudo systemctl restart xsyy-backend
    else
        pkill -f "uvicorn app:app" || true
        sleep 2
        cd "$BACKEND_DIR"
        source .venv/bin/activate
        nohup uvicorn app:app --host 0.0.0.0 --port 8000 --reload > /tmp/xsyy-backend.log 2>&1 &
    fi
    
    log_error "部署失败，已回滚到备份版本"
    log_error "备份位置: $CURRENT_BACKUP_DIR"
    log_error "请检查日志并修复问题后重试"
    exit 1
fi

# ============================================
# 部署完成
# ============================================
log "=========================================="
log "✓ 部署成功完成！"
log "  环境: $ENV"
log "  版本: $CURRENT_VERSION"
log "  备份位置: $CURRENT_BACKUP_DIR"
log "=========================================="

# 保存部署信息
echo "ENV=$ENV" > "$PROJECT_DIR/.deploy_info"
echo "VERSION=$CURRENT_VERSION" >> "$PROJECT_DIR/.deploy_info"
echo "DATE=$(date +'%Y-%m-%d %H:%M:%S')" >> "$PROJECT_DIR/.deploy_info"
echo "BACKUP=$CURRENT_BACKUP_DIR" >> "$PROJECT_DIR/.deploy_info"

exit 0


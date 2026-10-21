#!/bin/bash
# ============================================
# 回滚脚本 - 恢复到上一个版本
# 使用方法: ./rollback.sh [backup_dir]
# 示例: ./rollback.sh backups/20241219_143022
# ============================================

set -e

PROJECT_DIR="/opt/xsyy"
BACKEND_DIR="$PROJECT_DIR/backend"
BACKUP_DIR="$PROJECT_DIR/backups"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1"
}

log_error() {
    echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')] 错误:${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')] 警告:${NC} $1"
}

log "=========================================="
log "回滚脚本"
log "=========================================="

# 如果没有指定备份目录，使用最新的备份
if [ -z "$1" ]; then
    # 查找最新的备份
    LATEST_BACKUP=$(ls -t "$BACKUP_DIR" | head -1)
    if [ -z "$LATEST_BACKUP" ]; then
        log_error "没有找到备份目录"
        exit 1
    fi
    BACKUP_PATH="$BACKUP_DIR/$LATEST_BACKUP"
    log "使用最新备份: $LATEST_BACKUP"
else
    BACKUP_PATH="$BACKUP_DIR/$1"
fi

# 检查备份是否存在
if [ ! -d "$BACKUP_PATH" ]; then
    log_error "备份目录不存在: $BACKUP_PATH"
    exit 1
fi

# 确认回滚
echo ""
log_warn "⚠️  警告: 即将回滚到备份版本！"
log "   备份位置: $BACKUP_PATH"
echo ""
read -p "确认继续？(yes/no): " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    log "回滚已取消"
    exit 0
fi

# 1. 停止服务
log "步骤 1: 停止服务..."
sudo systemctl stop xsyy-backend || pkill -f "uvicorn app:app" || true
sleep 2

# 2. 恢复代码
log "步骤 2: 恢复代码..."
cd "$PROJECT_DIR"

if [ -f "$BACKUP_PATH/code.tar.gz" ]; then
    # 备份当前版本（以防回滚失败）
    ROLLBACK_BACKUP="$BACKUP_DIR/rollback_$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$ROLLBACK_BACKUP"
    tar -czf "$ROLLBACK_BACKUP/code.tar.gz" -C "$PROJECT_DIR" backend web --exclude='.venv' --exclude='__pycache__' 2>/dev/null || true
    
    # 恢复备份
    tar -xzf "$BACKUP_PATH/code.tar.gz" -C "$PROJECT_DIR"
    log "✓ 代码已恢复"
else
    log_error "备份文件不存在: $BACKUP_PATH/code.tar.gz"
    exit 1
fi

# 3. 恢复数据库（如果有备份）
if [ -f "$BACKUP_PATH/database.sql" ]; then
    log "步骤 3: 恢复数据库..."
    log_warn "数据库恢复需要手动执行，请参考备份文件: $BACKUP_PATH/database.sql"
    log_warn "执行命令: mysql -h host -u user -p database < $BACKUP_PATH/database.sql"
else
    log "步骤 3: 跳过数据库恢复（无备份文件）"
fi

# 4. 重启服务
log "步骤 4: 重启服务..."
if systemctl is-enabled xsyy-backend >/dev/null 2>&1; then
    sudo systemctl start xsyy-backend
    log "✓ 服务已重启（systemd）"
else
    cd "$BACKEND_DIR"
    source .venv/bin/activate
    nohup uvicorn app:app --host 0.0.0.0 --port 8000 > /tmp/xsyy-backend.log 2>&1 &
    log "✓ 服务已重启（uvicorn）"
fi

# 5. 健康检查
log "步骤 5: 健康检查..."
sleep 5

if curl -f http://localhost:8000/api/health > /dev/null 2>&1; then
    log "✓ 回滚成功！服务运行正常"
else
    log_error "回滚后服务启动失败，请检查日志"
    exit 1
fi

log "=========================================="
log "回滚完成！"
log "   备份位置: $BACKUP_PATH"
log "=========================================="


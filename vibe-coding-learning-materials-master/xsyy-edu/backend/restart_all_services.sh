#!/usr/bin/env bash
# 一键重启所有服务脚本
# 功能：重启 Nginx、后端服务，然后运行检查脚本验证所有服务状态

set -euo pipefail

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 脚本目录（现在脚本在项目根目录）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"
BACKEND_DIR="$PROJECT_ROOT/backend"

echo "=========================================="
echo "🚀 一键重启所有服务"
echo "=========================================="
echo ""

# 函数：打印步骤
print_step() {
    echo -e "${BLUE}[步骤] $1${NC}"
}

# 函数：打印成功
print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

# 函数：打印警告
print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

# 函数：打印错误
print_error() {
    echo -e "${RED}✗ $1${NC}"
}

# --- 1. 停止后端服务 ---
print_step "1. 停止后端服务..."
if pgrep -f "uvicorn app:app" > /dev/null; then
    echo "   正在停止 uvicorn 进程..."
    pkill -f "uvicorn app:app" || true
    sleep 2
    
    # 确认是否已停止
    if pgrep -f "uvicorn app:app" > /dev/null; then
        print_warning "   进程仍在运行，强制停止..."
        pkill -9 -f "uvicorn app:app" || true
        sleep 1
    fi
    
    if ! pgrep -f "uvicorn app:app" > /dev/null; then
        print_success "   后端服务已停止"
    else
        print_error "   后端服务停止失败"
        exit 1
    fi
else
    print_warning "   后端服务未运行，跳过停止步骤"
fi
echo ""

# --- 2. 重启 Nginx ---
print_step "2. 重启 Nginx 服务..."
if systemctl is-active nginx > /dev/null 2>&1; then
    echo "   正在重启 Nginx..."
    if sudo systemctl restart nginx; then
        sleep 1
        if systemctl is-active nginx > /dev/null 2>&1; then
            print_success "   Nginx 已重启"
        else
            print_error "   Nginx 重启后未运行"
            echo "   错误信息："
            sudo systemctl status nginx --no-pager -l | head -n 10
            exit 1
        fi
    else
        print_error "   Nginx 重启失败"
        exit 1
    fi
else
    print_warning "   Nginx 未运行，尝试启动..."
    if sudo systemctl start nginx; then
        print_success "   Nginx 已启动"
    else
        print_error "   Nginx 启动失败"
        exit 1
    fi
fi
echo ""

# --- 3. 重启 MySQL（可选，通常不需要）---
# 注释掉，因为数据库通常不需要重启
# print_step "3. 检查 MySQL 服务..."
# if systemctl is-active mysqld > /dev/null 2>&1; then
#     print_success "   MySQL 正在运行，无需重启"
# else
#     print_warning "   MySQL 未运行，尝试启动..."
#     if sudo systemctl start mysqld; then
#         print_success "   MySQL 已启动"
#     else
#         print_error "   MySQL 启动失败"
#     fi
# fi
# echo ""

# --- 4. 启动后端服务 ---
print_step "3. 启动后端服务..."
cd "$BACKEND_DIR"

# 检查虚拟环境
if [[ ! -f "$PROJECT_ROOT/.venv/bin/activate" ]]; then
    print_error "   虚拟环境不存在: $PROJECT_ROOT/.venv"
    exit 1
fi

# 激活虚拟环境
source "$PROJECT_ROOT/.venv/bin/activate"

# 检查 .env 文件
if [[ ! -f .env ]]; then
    print_warning "   .env 文件不存在，可能影响服务启动"
fi

# 启动后端服务（后台运行，不输出日志到终端）
echo "   正在启动 uvicorn..."
nohup uvicorn app:app --host 127.0.0.1 --port 8000 > /tmp/uvicorn.log 2>&1 &

# 等待服务启动（使用重试机制）
echo "   等待服务启动..."
MAX_RETRIES=30
RETRY_COUNT=0
SERVICE_READY=0

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    sleep 2
    RETRY_COUNT=$((RETRY_COUNT + 1))
    
    # 检查进程是否存在
    if ! pgrep -f "uvicorn app:app" > /dev/null; then
        print_error "   后端服务进程已退出"
        echo "   错误日志："
        tail -n 30 /tmp/uvicorn.log 2>/dev/null || echo "   无法读取日志文件"
        exit 1
    fi
    
    # 检查端口是否监听
    if ss -tlnp | grep -q ":8000 "; then
        # 检查 API 是否可以访问
        if curl -s -f http://127.0.0.1:8000/docs > /dev/null 2>&1; then
            SERVICE_READY=1
            break
        fi
    fi
    
    if [ $((RETRY_COUNT % 5)) -eq 0 ]; then
        echo "   等待中... ($RETRY_COUNT/$MAX_RETRIES)"
    fi
done

if [ $SERVICE_READY -eq 1 ]; then
    PID=$(pgrep -f "uvicorn app:app")
    print_success "   后端服务已启动 (PID: $PID)"
    print_success "   端口 8000 正在监听"
    print_success "   API 可访问"
else
    print_error "   后端服务启动超时（等待了 $((MAX_RETRIES * 2)) 秒）"
    echo "   当前状态："
    ps aux | grep uvicorn | grep -v grep || echo "   进程不存在"
    ss -tlnp | grep 8000 || echo "   端口未监听"
    echo "   最近日志："
    tail -n 30 /tmp/uvicorn.log 2>/dev/null || echo "   无法读取日志文件"
    exit 1
fi
echo ""

# --- 5. 最终验证 ---
print_step "4. 最终验证服务状态..."
echo "   验证所有服务..."
sleep 2

# 验证 Nginx
if systemctl is-active nginx > /dev/null 2>&1 && ss -tlnp | grep -q ":80 "; then
    print_success "   Nginx 运行正常"
else
    print_error "   Nginx 状态异常"
fi

# 验证后端服务
if pgrep -f "uvicorn app:app" > /dev/null && curl -s -f http://127.0.0.1:8000/docs > /dev/null 2>&1; then
    print_success "   后端服务运行正常"
else
    print_error "   后端服务状态异常"
fi

echo ""

# --- 6. 运行检查脚本 ---
print_step "5. 运行服务状态检查..."
echo ""

# 运行检查脚本
if [[ -f "$SCRIPT_DIR/check_server_status.sh" ]]; then
    bash "$SCRIPT_DIR/check_server_status.sh"
    CHECK_EXIT_CODE=$?
    
    echo ""
    echo "=========================================="
    if [ $CHECK_EXIT_CODE -eq 0 ]; then
        echo -e "${GREEN}✅ 所有服务重启完成并检查通过！${NC}"
    else
        echo -e "${YELLOW}⚠️  服务已重启，但检查发现一些问题，请查看上述信息。${NC}"
    fi
    echo "=========================================="
else
    print_error "   检查脚本不存在: $SCRIPT_DIR/check_server_status.sh"
    exit 1
fi

echo ""
echo "=========================================="
echo "📋 服务管理命令"
echo "=========================================="
echo ""
echo "查看后端服务日志："
echo "  tail -f /tmp/uvicorn.log"
echo ""
echo "查看 Nginx 日志："
echo "  sudo tail -f /var/log/nginx/error.log"
echo ""
echo "查看后端服务进程："
echo "  ps aux | grep uvicorn | grep -v grep"
echo ""
echo "手动重启后端服务："
echo "  pkill -f 'uvicorn app:app' && cd $BACKEND_DIR && source $PROJECT_ROOT/.venv/bin/activate && nohup uvicorn app:app --host 127.0.0.1 --port 8000 > /tmp/uvicorn.log 2>&1 &"
echo ""
echo "运行服务检查："
echo "  bash $SCRIPT_DIR/check_server_status.sh"
echo ""


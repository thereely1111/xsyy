#!/bin/bash
# ============================================
# 开发环境快速部署脚本
# 使用方法: ./deploy-dev.sh
# ============================================

set -e

PROJECT_DIR="/opt/xsyy"
BACKEND_DIR="$PROJECT_DIR/backend"

echo "=========================================="
echo "开发环境快速部署"
echo "=========================================="

cd "$PROJECT_DIR"

# 1. 拉取最新代码（develop 分支）
echo "1. 拉取最新代码..."
git checkout develop
git pull origin develop

# 2. 更新 Python 依赖
echo "2. 更新 Python 依赖..."
cd "$BACKEND_DIR"
source .venv/bin/activate
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet

# 3. 运行数据库迁移（如果有）
echo "3. 检查数据库迁移..."
python -c "from database import init_db; init_db()" 2>/dev/null || echo "  数据库已是最新"

# 4. 重启服务（开发环境使用 uvicorn --reload）
echo "4. 重启服务..."
pkill -f "uvicorn app:app" || true
sleep 2

# 启动服务（带自动重载，方便开发）
cd "$BACKEND_DIR"
source .venv/bin/activate
nohup uvicorn app:app --host 0.0.0.0 --port 8000 --reload > /tmp/xsyy-backend.log 2>&1 &

echo "5. 等待服务启动..."
sleep 3

# 5. 健康检查
if curl -f http://localhost:8000/api/health > /dev/null 2>&1; then
    echo "✓ 开发环境部署成功！"
    echo "  服务地址: http://localhost:8000"
    echo "  日志文件: /tmp/xsyy-backend.log"
else
    echo "✗ 服务启动失败，请检查日志: /tmp/xsyy-backend.log"
    exit 1
fi


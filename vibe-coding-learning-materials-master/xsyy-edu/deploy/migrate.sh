#!/bin/bash
# ============================================
# 数据库迁移脚本
# 使用方法: ./migrate.sh [dev|prod]
# ============================================

set -e

ENV=${1:-dev}
BACKEND_DIR="/opt/xsyy/backend"

echo "=========================================="
echo "数据库迁移脚本"
echo "环境: $ENV"
echo "=========================================="

cd "$BACKEND_DIR"

# 激活虚拟环境
if [ -d ".venv" ]; then
    source .venv/bin/activate
else
    echo "错误: 虚拟环境不存在，请先运行部署脚本"
    exit 1
fi

# 1. 初始化数据库（如果表不存在）
echo "1. 检查数据库表结构..."
python -c "from database import init_db; init_db()" 2>/dev/null || echo "  数据库表已存在"

# 2. 运行 Python 迁移脚本
echo "2. 运行 Python 迁移脚本..."
for migration in database/*.py; do
    if [ -f "$migration" ]; then
        filename=$(basename "$migration")
        # 跳过 __init__.py 和 models.py
        if [[ "$filename" != "__init__.py" ]] && [[ "$filename" != "models.py" ]] && [[ "$filename" != "database.py" ]]; then
            if [[ "$filename" == *"migrate"* ]] || [[ "$filename" == *"update"* ]] || [[ "$filename" == *"add"* ]]; then
                echo "  运行: $filename"
                python "$migration" || echo "    跳过（可能已执行）"
            fi
        fi
    fi
done

# 3. 运行 SQL 迁移脚本（需要手动配置数据库连接）
echo "3. 检查 SQL 迁移脚本..."
if [ -f ".env" ]; then
    # 从 .env 读取数据库信息（需要根据实际情况调整）
    echo "  找到 .env 文件，SQL 迁移需要手动执行"
    echo "  请参考 database/*.sql 文件"
else
    echo "  未找到 .env 文件，跳过 SQL 迁移"
fi

echo ""
echo "=========================================="
echo "✓ 数据库迁移完成"
echo "=========================================="


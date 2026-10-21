#!/bin/bash
# ============================================
# 生产环境部署脚本（带安全检查）
# 使用方法: ./deploy-prod.sh [version]
# 示例: ./deploy-prod.sh v1.0.1
# ============================================

set -e

PROJECT_DIR="/opt/xsyy"
VERSION=${1:-latest}

echo "=========================================="
echo "生产环境部署（安全检查模式）"
echo "=========================================="

cd "$PROJECT_DIR"

# 1. 检查当前分支（生产环境只能从 main/master 部署）
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$CURRENT_BRANCH" != "main" ] && [ "$CURRENT_BRANCH" != "master" ]; then
    echo "❌ 错误: 生产环境只能从 main/master 分支部署"
    echo "   当前分支: $CURRENT_BRANCH"
    echo "   请先切换到 main 分支: git checkout main"
    exit 1
fi

# 2. 检查是否有未提交的更改
if [ -n "$(git status --porcelain)" ]; then
    echo "❌ 错误: 有未提交的更改"
    echo "   请先提交或暂存所有更改"
    git status
    exit 1
fi

# 3. 确认部署
echo ""
echo "⚠️  警告: 即将部署到生产环境！"
echo "   当前分支: $CURRENT_BRANCH"
echo "   部署版本: $VERSION"
echo ""
read -p "确认继续？(yes/no): " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo "部署已取消"
    exit 0
fi

# 4. 执行主部署脚本
echo ""
echo "开始部署..."
"$PROJECT_DIR/deploy/deploy.sh" prod "$VERSION"

echo ""
echo "=========================================="
echo "✓ 生产环境部署完成！"
echo "=========================================="


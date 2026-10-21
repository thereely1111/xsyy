#!/bin/bash
# ============================================
# 版本管理脚本
# 自动生成版本信息文件
# ============================================

PROJECT_DIR="/opt/xsyy"

cd "$PROJECT_DIR"

# 获取版本信息
VERSION=$(git describe --tags --always 2>/dev/null || echo "unknown")
COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
DATE=$(date +%Y%m%d_%H%M%S)

# 保存版本信息
cat > "$PROJECT_DIR/.version" << EOF
VERSION=$VERSION
COMMIT=$COMMIT
BRANCH=$BRANCH
BUILD_DATE=$DATE
EOF

# 创建 Python 版本文件（供 API 使用）
cat > "$PROJECT_DIR/backend/version.py" << EOF
"""版本信息（自动生成）"""
VERSION = "$VERSION"
COMMIT = "$COMMIT"
BRANCH = "$BRANCH"
BUILD_DATE = "$DATE"
EOF

echo "版本信息已更新:"
echo "  版本: $VERSION"
echo "  提交: $COMMIT"
echo "  分支: $BRANCH"
echo "  日期: $DATE"


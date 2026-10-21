#!/bin/bash
# Bash 脚本：测试后端 API
# 使用方法: bash test_api.sh

echo "测试后端 API 健康检查端点..."

response=$(curl -s -w "\n%{http_code}" http://localhost:8000/api/health)
http_code=$(echo "$response" | tail -n1)
body=$(echo "$response" | sed '$d')

if [ "$http_code" -eq 200 ]; then
    echo "✓ API 响应成功"
    echo "状态码: $http_code"
    echo "响应内容:"
    echo "$body" | python3 -m json.tool 2>/dev/null || echo "$body"
else
    echo "✗ API 请求失败"
    echo "状态码: $http_code"
    echo "响应内容: $body"
    echo ""
    echo "请确保:"
    echo "  1. 后端服务正在运行 (python -m uvicorn app:app --reload)"
    echo "  2. 服务运行在 http://localhost:8000"
fi


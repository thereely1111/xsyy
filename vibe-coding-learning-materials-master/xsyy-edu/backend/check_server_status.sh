#!/bin/bash
# 服务器配置检查脚本
# 用于检查 xsyy.top 网站访问所需的所有服务和配置

set +e  # 不立即退出，允许检查失败

echo "=========================================="
echo "服务器配置检查脚本"
echo "=========================================="
echo ""

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 检查结果统计
PASSED=0
FAILED=0
WARNINGS=0

# 检查函数
check_service() {
    local service_name=$1
    local check_cmd=$2
    
    echo -n "检查 $service_name: "
    if bash -c "$check_cmd" > /dev/null 2>&1; then
        echo -e "${GREEN}✓ 正常${NC}"
        ((PASSED++))
        return 0
    else
        echo -e "${RED}✗ 异常${NC}"
        ((FAILED++))
        return 1
    fi
}

check_warning() {
    local service_name=$1
    local check_cmd=$2
    
    echo -n "检查 $service_name: "
    if bash -c "$check_cmd" > /dev/null 2>&1; then
        echo -e "${GREEN}✓ 正常${NC}"
        ((PASSED++))
        return 0
    else
        echo -e "${YELLOW}⚠ 警告${NC}"
        ((WARNINGS++))
        return 1
    fi
}

# 1. 检查 Nginx 服务
echo "【1. Web 服务器检查】"
check_service "Nginx 进程" "ps aux | grep '[n]ginx'"
check_service "Nginx 端口 80" "ss -tlnp | grep ':80'"
check_service "Nginx 端口 443" "ss -tlnp | grep ':443'"

# 检查 Nginx 配置
echo -n "检查 Nginx 配置: "
if sudo nginx -t > /dev/null 2>&1; then
    echo -e "${GREEN}✓ 配置正确${NC}"
    ((PASSED++))
else
    echo -e "${RED}✗ 配置错误${NC}"
    sudo nginx -t 2>&1 | head -n 5
    ((FAILED++))
fi

echo ""

# 2. 检查后端服务
echo "【2. 后端服务检查】"
check_service "后端服务 (8000端口)" "ss -tlnp | grep ':8000'"

# 测试后端 API
echo -n "检查后端 API: "
if curl -s http://127.0.0.1:8000/docs > /dev/null 2>&1; then
    echo -e "${GREEN}✓ API 可访问${NC}"
    ((PASSED++))
else
    echo -e "${RED}✗ API 不可访问${NC}"
    ((FAILED++))
fi

echo ""

# 3. 检查 SSL 证书
echo "【3. SSL 证书检查】"
if [ -f /etc/letsencrypt/live/xsyy.top/cert.pem ]; then
    echo -e "${GREEN}✓ 证书文件存在${NC}"
    ((PASSED++))
    
    # 检查证书有效期
    CERT_EXPIRY=$(sudo openssl x509 -in /etc/letsencrypt/live/xsyy.top/cert.pem -noout -enddate 2>/dev/null | cut -d= -f2)
    if [ -n "$CERT_EXPIRY" ]; then
        EXPIRY_EPOCH=$(date -d "$CERT_EXPIRY" +%s 2>/dev/null || echo "0")
        CURRENT_EPOCH=$(date +%s)
        DAYS_LEFT=$(( ($EXPIRY_EPOCH - $CURRENT_EPOCH) / 86400 ))
        
        if [ $DAYS_LEFT -gt 30 ]; then
            echo -e "${GREEN}✓ 证书有效期: $CERT_EXPIRY (剩余 $DAYS_LEFT 天)${NC}"
            ((PASSED++))
        elif [ $DAYS_LEFT -gt 0 ]; then
            echo -e "${YELLOW}⚠ 证书即将过期: $CERT_EXPIRY (剩余 $DAYS_LEFT 天)${NC}"
            ((WARNINGS++))
        else
            echo -e "${RED}✗ 证书已过期: $CERT_EXPIRY${NC}"
            ((FAILED++))
        fi
    fi
else
    echo -e "${RED}✗ 证书文件不存在${NC}"
    ((FAILED++))
fi

echo ""

# 4. 检查防火墙
echo "【4. 防火墙检查】"
# 检查 iptables 规则（可能为空，因为使用云服务器安全组）
if sudo iptables -L -n | grep -q "dpt:80\|:80 "; then
    check_service "防火墙规则 (80端口)" "sudo iptables -L -n | grep -E 'dpt:80|:80 '"
else
    # 如果没有显式规则，检查默认策略和端口是否可访问
    echo -n "检查防火墙规则 (80端口): "
    if ss -tlnp | grep -q ":80 "; then
        echo -e "${YELLOW}⚠ 使用默认策略或云服务器安全组（端口正在监听）${NC}"
        ((WARNINGS++))
    else
        echo -e "${RED}✗ 端口未监听${NC}"
        ((FAILED++))
    fi
fi

if sudo iptables -L -n | grep -q "dpt:443\|:443 "; then
    check_service "防火墙规则 (443端口)" "sudo iptables -L -n | grep -E 'dpt:443|:443 '"
else
    echo -n "检查防火墙规则 (443端口): "
    if ss -tlnp | grep -q ":443 "; then
        echo -e "${YELLOW}⚠ 使用默认策略或云服务器安全组（端口正在监听）${NC}"
        ((WARNINGS++))
    else
        echo -e "${RED}✗ 端口未监听${NC}"
        ((FAILED++))
    fi
fi

echo ""

# 5. 检查数据库
echo "【5. 数据库检查】"
check_service "MySQL 服务" "systemctl is-active mysqld"
check_service "MySQL 端口 (3306)" "ss -tlnp | grep ':3306'"

# 检查 MySQL 监听地址
echo -n "检查 MySQL 监听地址: "
MYSQL_BIND=$(ss -tlnp | grep ':3306' | awk '{print $4}')
if echo "$MYSQL_BIND" | grep -q "0.0.0.0"; then
    echo -e "${GREEN}✓ 监听所有接口 (0.0.0.0)${NC}"
    ((PASSED++))
elif echo "$MYSQL_BIND" | grep -q "127.0.0.1"; then
    echo -e "${YELLOW}⚠ 仅监听本地 (127.0.0.1)，外网无法连接${NC}"
    ((WARNINGS++))
else
    echo -e "${YELLOW}⚠ 监听地址: $MYSQL_BIND${NC}"
    ((WARNINGS++))
fi

echo ""

# 6. 检查静态文件
echo "【6. 静态文件检查】"
if [ -f /var/www/xsyy/index.html ]; then
    echo -e "${GREEN}✓ 前端文件存在${NC}"
    ((PASSED++))
else
    echo -e "${RED}✗ 前端文件不存在: /var/www/xsyy/index.html${NC}"
    ((FAILED++))
fi

echo ""

# 7. 检查域名解析（需要网络连接）
echo "【7. 域名解析检查】"
echo -n "检查 xsyy.top DNS: "
XSYY_IP=$(nslookup xsyy.top 2>/dev/null | grep -A 1 "Name:" | grep "Address:" | tail -1 | awk '{print $2}' || echo "")
if [ -n "$XSYY_IP" ]; then
    SERVER_IP=$(curl -s ifconfig.me 2>/dev/null || echo "")
    if [ "$XSYY_IP" = "$SERVER_IP" ]; then
        echo -e "${GREEN}✓ 解析正确 ($XSYY_IP)${NC}"
        ((PASSED++))
    else
        echo -e "${YELLOW}⚠ 解析到 $XSYY_IP，服务器 IP 是 $SERVER_IP${NC}"
        ((WARNINGS++))
    fi
else
    echo -e "${YELLOW}⚠ 无法解析域名${NC}"
    ((WARNINGS++))
fi

echo ""

# 8. 检查本地访问测试
echo "【8. 本地访问测试】"
echo -n "测试 HTTP (80端口): "
if curl -s http://127.0.0.1/ | grep -q "html\|DOCTYPE" 2>/dev/null; then
    echo -e "${GREEN}✓ 可访问${NC}"
    ((PASSED++))
else
    echo -e "${RED}✗ 无法访问${NC}"
    ((FAILED++))
fi

echo -n "测试 HTTPS (443端口): "
if curl -s -k https://127.0.0.1/ | grep -q "html\|DOCTYPE" 2>/dev/null; then
    echo -e "${GREEN}✓ 可访问${NC}"
    ((PASSED++))
else
    echo -e "${RED}✗ 无法访问${NC}"
    ((FAILED++))
fi

echo ""

# 总结
echo "=========================================="
echo "检查结果汇总"
echo "=========================================="
echo -e "${GREEN}✓ 通过: $PASSED${NC}"
echo -e "${YELLOW}⚠ 警告: $WARNINGS${NC}"
echo -e "${RED}✗ 失败: $FAILED${NC}"
echo ""

if [ $FAILED -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo -e "${GREEN}✅ 所有检查通过！服务器配置正常。${NC}"
    exit 0
elif [ $FAILED -eq 0 ]; then
    echo -e "${YELLOW}⚠️  有警告项，请查看上述警告信息。${NC}"
    exit 0
else
    echo -e "${RED}❌ 发现 $FAILED 个问题，请修复后重新检查。${NC}"
    exit 1
fi


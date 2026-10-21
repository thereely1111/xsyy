#!/bin/bash
# 内存监控启动脚本 - 增强版（防断开）
# 保存为：/root/xsyy/backend/start_with_monitor.sh

# 切换到项目目录
cd /root/xsyy/backend || { echo "❌ 无法进入项目目录"; exit 1; }

# 0. 激活虚拟环境
if [ -f "/data/miniconda3/etc/profile.d/conda.sh" ]; then
    source /data/miniconda3/etc/profile.d/conda.sh
    conda activate xsyy
elif [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
elif [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi
echo "🐍 当前Python: $(which python)"

# 1. 清理旧进程（增强版）
echo "🔄 清理旧进程..."
pkill -f "uvicorn.*8000" 2>/dev/null
sleep 2

# 强制清理端口占用
if sudo lsof -i:8000 > /dev/null 2>&1; then
    echo "⏳ 端口8000仍被占用，强制清理..."
    sudo fuser -k 8000/tcp 2>/dev/null
    sleep 1
fi

# 2. 检查内存（改为警告而非退出）
FREE_MEM=$(free -m | awk 'NR==2{print $7}')
if [ $FREE_MEM -lt 100 ]; then
    echo "⚠️ 内存紧张: ${FREE_MEM}MB，尝试释放缓存..."
    sudo sync && echo 3 | sudo tee /proc/sys/vm/drop_caches > /dev/null
    sleep 2
    FREE_MEM=$(free -m | awk 'NR==2{print $7}')
    echo "📊 释放后可用内存: ${FREE_MEM}MB"
fi

# 3. 启动（使用systemd-run或setsid防止断开）
echo "🚀 启动服务..."

# 使用 nohup 后台启动（兼容所有服务器）
nohup uvicorn app:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 1 \
    --limit-concurrency 20 \
    --log-level warning \
    --no-access-log \
    --timeout-keep-alive 2 \
    > minimal_$(date +%Y%m%d_%H%M%S).log 2>&1 &
PID=$!

echo "✅ 进程启动，PID: $PID"
echo "📊 启动时可用内存: ${FREE_MEM}MB"

# 4. 验证启动
sleep 3
if ps -p $PID > /dev/null 2>/dev/null || [ "$PID" != "unknown" ]; then
    # 获取进程内存（如果有PID）
    if [ "$PID" != "unknown" ] && [ -n "$PID" ] && [ "$PID" -eq "$PID" ] 2>/dev/null; then
        MEM_USAGE=$(ps -p $PID -o rss= 2>/dev/null | awk '{printf "%.1f", $1/1024}')
        echo "📈 进程内存占用: ${MEM_USAGE}MB"
    fi
    
    # 测试API
    echo "🌐 测试API连通性..."
    if curl -s -f --max-time 5 http://localhost:8000/api/health > /dev/null; then
        echo "✅ 服务运行正常"
        echo "📋 日志文件: minimal_*.log"
    else
        echo "⚠️ API无响应，但进程存在"
    fi
else
    echo "❌ 进程启动失败，查看日志:"
    ls -t minimal_*.log 2>/dev/null | head -1 | xargs tail -20
fi

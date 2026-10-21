#!/bin/bash
# 智能内存守卫
THRESHOLD_CRITICAL=90    # 临界阈值（直接重启）
THRESHOLD_WARNING=80     # 警告阈值（尝试清理）

while true; do
    MEM_USAGE=$(free | awk 'NR==2{printf "%.0f", $3/$2 * 100}')
    
    if [ $MEM_USAGE -ge $THRESHOLD_CRITICAL ]; then
        echo "$(date) CRITICAL: 内存 ${MEM_USAGE}%，立即重启"
        # 执行重启流程
        do_restart
        
    elif [ $MEM_USAGE -ge $THRESHOLD_WARNING ]; then
        echo "$(date) WARNING: 内存 ${MEM_USAGE}%，尝试清理"
        
        # 1. 清理缓存
        sudo sync && echo 3 | sudo tee /proc/sys/vm/drop_caches
        
        # 2. 查找内存占用最高的进程
        HIGH_MEM_PID=$(ps aux --sort=-%mem | awk 'NR==2{print $2}')
        HIGH_MEM_CMD=$(ps aux --sort=-%mem | awk 'NR==2{print $11}')
        
        # 3. 如果不是关键进程，尝试结束
        if [[ ! "$HIGH_MEM_CMD" =~ "(uvicorn|nginx|ssh|systemd)" ]]; then
            echo "$(date) 结束高内存进程: $HIGH_MEM_CMD (PID: $HIGH_MEM_PID)"
            kill $HIGH_MEM_PID
        fi
        
        # 4. 等待清理效果
        sleep 10
    fi
    
    sleep 60
done

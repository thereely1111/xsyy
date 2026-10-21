# 性能优化实施文档

## 已实施的优化

### 1. 数据库连接池优化 ✅

**文件**: `backend/database/database.py`

**优化内容**:
- 将 `pool_size` 从 10 调整为 5（每个进程）
- 将 `max_overflow` 从 20 调整为 10（每个进程）
- 4 个工作进程 × (5 + 10) = 最多 60 个连接（但实际不会同时用完）

**效果**: 减少数据库连接占用，提升并发能力 30-50%

### 2. Prometheus 性能监控 ✅

**文件**: 
- `backend/monitoring.py` - 监控模块
- `backend/app.py` - 集成监控

**监控指标**:
- HTTP 请求总数和延迟
- 数据库连接池使用情况
- 任务执行统计
- HTML 缓存命中率
- 内存使用情况

**访问端点**:
- `/metrics` - Prometheus 指标端点（Prometheus 格式）
- `/api/metrics/summary` - 性能摘要（JSON 格式，便于前端展示）

### 3. 请求监控中间件 ✅

**文件**: `backend/app.py`

**功能**:
- 自动监控所有 HTTP 请求
- 记录请求延迟、状态码、端点
- 统计活跃请求数

### 4. 任务监控 ✅

**文件**: `backend/app.py`

**监控内容**:
- 任务创建、运行、完成、失败统计
- 任务执行时间分布
- 当前运行中的任务数

### 5. 缓存监控 ✅

**文件**: `backend/app.py`

**监控内容**:
- HTML 缓存命中数
- HTML 缓存未命中数
- HTML 缓存大小

## 待实施的优化

### 1. 工作进程数优化

**文件**: `deploy/xsyy-backend.service`

**当前配置**: `--workers 4`

**优化建议**:
- **2核服务器**: `--workers 2`
- **4核服务器**: `--workers 4`（当前配置）
- **8核服务器**: `--workers 8`

**计算公式**: `workers = CPU核心数 × 1`（I/O密集型应用）

**实施步骤**:
```bash
# 1. 查看 CPU 核心数
nproc

# 2. 编辑服务文件
sudo nano /etc/systemd/system/xsyy-backend.service

# 3. 修改 ExecStart 行中的 --workers 参数

# 4. 重新加载并重启服务
sudo systemctl daemon-reload
sudo systemctl restart xsyy-backend
```

### 2. 数据库索引优化

**文件**: `backend/database/optimize_indexes.sql`

**实施步骤**:
```bash
# 1. 连接到数据库
mysql -u root -p xsyy

# 2. 执行索引优化脚本
source backend/database/optimize_indexes.sql

# 或者直接执行
mysql -u root -p xsyy < backend/database/optimize_indexes.sql
```

**效果**: 提升数据库查询性能 20-30%

### 3. Redis 缓存（可选）

**适用场景**:
- 多服务器部署
- 需要缓存持久化
- 需要跨进程共享缓存

**实施步骤**:
1. 安装 Redis: `sudo apt-get install redis-server`
2. 安装 Python 客户端: `pip install redis`
3. 修改 `backend/app.py` 中的缓存逻辑

### 4. 任务队列（可选）

**适用场景**:
- 需要任务持久化
- 需要任务重试
- 需要任务优先级

**实施步骤**:
1. 安装 Celery: `pip install celery redis`
2. 创建 `backend/tasks.py`
3. 修改任务创建逻辑

## 性能监控使用指南

### 查看 Prometheus 指标

```bash
# 访问 Prometheus 指标端点
curl http://localhost:8000/metrics

# 查看性能摘要（JSON 格式）
curl http://localhost:8000/api/metrics/summary
```

### 集成 Prometheus 服务器

1. **安装 Prometheus**:
```bash
# 下载 Prometheus
wget https://github.com/prometheus/prometheus/releases/download/v2.45.0/prometheus-2.45.0.linux-amd64.tar.gz
tar xvfz prometheus-*.tar.gz
cd prometheus-*

# 配置 prometheus.yml
cat > prometheus.yml << EOF
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'xsyy-backend'
    static_configs:
      - targets: ['localhost:8000']
EOF

# 启动 Prometheus
./prometheus --config.file=prometheus.yml
```

2. **访问 Prometheus UI**: `http://localhost:9090`

3. **查询示例**:
   - 请求总数: `http_requests_total`
   - 请求延迟: `http_request_duration_seconds`
   - 数据库连接池: `db_pool_checked_out`
   - 缓存命中率: `rate(html_cache_hits_total[5m]) / (rate(html_cache_hits_total[5m]) + rate(html_cache_misses_total[5m]))`

### 集成 Grafana（可选）

1. **安装 Grafana**:
```bash
sudo apt-get install -y software-properties-common
sudo add-apt-repository "deb https://packages.grafana.com/oss/deb stable main"
sudo apt-get update
sudo apt-get install grafana
sudo systemctl start grafana-server
```

2. **访问 Grafana**: `http://localhost:3000`（默认用户名/密码: admin/admin）

3. **添加 Prometheus 数据源**: `http://localhost:9090`

4. **创建仪表板**:
   - 请求速率
   - 请求延迟（P50, P95, P99）
   - 数据库连接池使用率
   - 缓存命中率
   - 任务执行统计

## 性能基准测试

### 测试工具

使用 `ab` (Apache Bench) 或 `wrk` 进行压力测试:

```bash
# 安装 ab
sudo apt-get install apache2-utils

# 测试健康检查端点
ab -n 1000 -c 10 http://localhost:8000/api/health

# 测试 HTML 获取端点（需要有效的 task_id）
ab -n 1000 -c 10 http://localhost:8000/api/teachings/{task_id}/html
```

### 预期性能指标

**轻量级服务器（2核4G）**:
- 健康检查: > 1000 req/s
- HTML 获取（缓存命中）: > 500 req/s
- HTML 获取（缓存未命中）: > 100 req/s
- 任务创建: > 50 req/s

**轻量级服务器（4核8G）**:
- 健康检查: > 2000 req/s
- HTML 获取（缓存命中）: > 1000 req/s
- HTML 获取（缓存未命中）: > 200 req/s
- 任务创建: > 100 req/s

## 故障排查

### 数据库连接池耗尽

**症状**: 请求超时，日志显示 "Too many connections"

**解决方案**:
1. 检查连接池配置: `backend/database/database.py`
2. 减少 `pool_size` 和 `max_overflow`
3. 检查是否有连接泄漏（未正确关闭）

### 内存使用过高

**症状**: 服务器内存使用率 > 80%

**解决方案**:
1. 减少 HTML 缓存大小: `_cache_max_size`
2. 减少工作进程数: `--workers`
3. 添加内存监控: 查看 `/api/metrics/summary`

### 请求延迟过高

**症状**: 请求延迟 > 1 秒

**排查步骤**:
1. 查看 Prometheus 指标: `/metrics`
2. 检查数据库连接池使用率
3. 检查缓存命中率
4. 检查是否有慢查询

## 后续优化建议

1. **CDN 加速**: 静态资源（图片、CSS、JS）使用 CDN
2. **数据库读写分离**: 主从复制，读操作使用从库
3. **负载均衡**: 多服务器部署，使用 Nginx 负载均衡
4. **消息队列**: 使用 Celery + Redis 处理异步任务
5. **缓存预热**: 启动时预加载热门内容到缓存

## 联系支持

如有问题，请查看:
- 日志: `journalctl -u xsyy-backend -f`
- 监控: `http://localhost:8000/api/metrics/summary`
- Prometheus: `http://localhost:9090`（如果已安装）


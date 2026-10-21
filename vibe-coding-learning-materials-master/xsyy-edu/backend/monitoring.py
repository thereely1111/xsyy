"""性能监控模块 - 使用 Prometheus 客户端"""

from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from prometheus_client import CollectorRegistry, REGISTRY
import time
from functools import wraps
from typing import Callable
from fastapi import Request, Response
from sqlalchemy import inspect

# 创建自定义注册表（可选，如果不想使用默认的）
registry = CollectorRegistry()

# ==================== 请求监控指标 ====================

# HTTP 请求总数（按方法和路径）
http_requests_total = Counter(
    'http_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status'],
    registry=registry
)

# HTTP 请求延迟（按端点）
http_request_duration_seconds = Histogram(
    'http_request_duration_seconds',
    'HTTP request duration in seconds',
    ['method', 'endpoint'],
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
    registry=registry
)

# 当前活跃请求数
http_requests_active = Gauge(
    'http_requests_active',
    'Number of active HTTP requests',
    registry=registry
)

# ==================== 数据库监控指标 ====================

# 数据库连接池使用情况
db_pool_size = Gauge(
    'db_pool_size',
    'Database connection pool size',
    registry=registry
)

db_pool_checked_in = Gauge(
    'db_pool_checked_in',
    'Database connections checked in',
    registry=registry
)

db_pool_checked_out = Gauge(
    'db_pool_checked_out',
    'Database connections checked out',
    registry=registry
)

db_pool_overflow = Gauge(
    'db_pool_overflow',
    'Database connection pool overflow',
    registry=registry
)

# 数据库查询总数
db_queries_total = Counter(
    'db_queries_total',
    'Total database queries',
    ['operation'],  # operation: select, insert, update, delete
    registry=registry
)

# 数据库查询延迟
db_query_duration_seconds = Histogram(
    'db_query_duration_seconds',
    'Database query duration in seconds',
    ['operation'],
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0],
    registry=registry
)

# ==================== 任务监控指标 ====================

# 任务总数（按状态）
tasks_total = Counter(
    'tasks_total',
    'Total tasks created',
    ['status'],  # status: pending, running, completed, failed
    registry=registry
)

# 当前运行中的任务数
tasks_running = Gauge(
    'tasks_running',
    'Number of tasks currently running',
    registry=registry
)

# 任务执行时间
task_duration_seconds = Histogram(
    'task_duration_seconds',
    'Task execution duration in seconds',
    ['status'],
    buckets=[10, 30, 60, 120, 300, 600, 1200, 1800],
    registry=registry
)

# ==================== 缓存监控指标 ====================

# HTML 缓存命中数
html_cache_hits_total = Counter(
    'html_cache_hits_total',
    'Total HTML cache hits',
    registry=registry
)

# HTML 缓存未命中数
html_cache_misses_total = Counter(
    'html_cache_misses_total',
    'Total HTML cache misses',
    registry=registry
)

# HTML 缓存大小
html_cache_size = Gauge(
    'html_cache_size',
    'Number of items in HTML cache',
    registry=registry
)

# ==================== 系统资源监控指标 ====================

# 内存使用量（MB）
memory_usage_mb = Gauge(
    'memory_usage_mb',
    'Memory usage in MB',
    registry=registry
)


def update_db_pool_metrics(engine):
    """更新数据库连接池指标"""
    try:
        pool = engine.pool
        db_pool_size.set(pool.size())
        db_pool_checked_in.set(pool.checkedin())
        db_pool_checked_out.set(pool.checkedout())
        db_pool_overflow.set(pool.overflow())
    except Exception as e:
        # 如果获取失败，不影响主流程
        pass


def update_memory_usage():
    """更新内存使用量指标"""
    try:
        import psutil
        import os
        process = psutil.Process(os.getpid())
        memory_mb = process.memory_info().rss / 1024 / 1024
        memory_usage_mb.set(memory_mb)
    except ImportError:
        # psutil 未安装，跳过
        pass
    except Exception:
        # 其他错误，跳过
        pass


def monitor_request(func: Callable):
    """装饰器：监控 API 请求"""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        # 从参数中提取 request（FastAPI 会自动注入）
        request = None
        for arg in args:
            if isinstance(arg, Request):
                request = arg
                break
        
        if not request:
            # 如果没有 request，直接执行
            return await func(*args, **kwargs)
        
        # 获取端点路径（简化，去掉参数）
        endpoint = request.url.path
        method = request.method
        
        # 增加活跃请求数
        http_requests_active.inc()
        
        start_time = time.time()
        status_code = 200
        
        try:
            response = await func(*args, **kwargs)
            # 尝试从响应中获取状态码
            if hasattr(response, 'status_code'):
                status_code = response.status_code
            return response
        except Exception as e:
            status_code = 500
            raise
        finally:
            # 减少活跃请求数
            http_requests_active.dec()
            
            # 记录请求延迟
            duration = time.time() - start_time
            http_request_duration_seconds.labels(
                method=method,
                endpoint=endpoint
            ).observe(duration)
            
            # 记录请求总数
            http_requests_total.labels(
                method=method,
                endpoint=endpoint,
                status=str(status_code)
            ).inc()
    
    return wrapper


def get_metrics_response() -> Response:
    """获取 Prometheus 指标响应"""
    update_memory_usage()
    return Response(
        content=generate_latest(registry),
        media_type=CONTENT_TYPE_LATEST
    )


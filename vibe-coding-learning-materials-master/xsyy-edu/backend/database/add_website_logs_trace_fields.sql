-- 为 website_logs 表添加结构化事件追踪字段（统一链路 ID + 事件字典）
-- 如果字段已存在，此语句会报错，可以忽略

ALTER TABLE website_logs
ADD COLUMN trace_id VARCHAR(36) NULL AFTER task_id,
ADD COLUMN event VARCHAR(50) NOT NULL DEFAULT '' AFTER trace_id,
ADD COLUMN stage VARCHAR(50) NOT NULL DEFAULT '' AFTER event,
ADD COLUMN error_type VARCHAR(50) NOT NULL DEFAULT '' AFTER stage;

-- 为历史数据回填 trace_id（1:1 复用 task_id，保证旧日志也能按链路聚合）
-- UPDATE website_logs SET trace_id = task_id WHERE trace_id IS NULL AND task_id IS NOT NULL;

-- 为常用筛选建立索引
-- CREATE INDEX idx_website_logs_trace_id ON website_logs (trace_id);
-- CREATE INDEX idx_website_logs_event ON website_logs (event);

"""网站日志：集中记录网站运行过程中产生的报错与异常信息。

设计目标：
- 与业务解耦，写入为 best-effort（即使记录失败也不影响主流程）。
- 结构化字段，便于后续排查与追溯（原因 / 触发用户 / 页面 / 设备 / 请求参数等）。
- 事件字典：event / stage / error_type 三枚举统一命名，支持按链路聚合与归因筛选。
- trace_id 与 task_id 1:1（一次任务一条链路），前端 / 后端 / 流水线全程透传。
- DB 相关导入均为懒加载，避免模块导入期触碰数据库。

事件字典约定（前端 error-reporter.js 中维护同名常量）：
- event     动作名：task_created / task_started / task_completed / task_failed /
                     task_poll_started / task_poll_failed / preview_generation_failed /
                     frontend_resource_load_failed / frontend_runtime_error / frontend_api_request_failed ...
- stage     阶段名：home_submit / upload_parse / pipeline / preview_generation /
                     video_page_polling / frontend_render
- error_type 错误大类：third_party_http_error / timeout / resource_load_error /
                     db_write_error / local_file_missing / prompt_too_long / unknown
"""
from __future__ import annotations

import traceback
from typing import Any, Dict, Optional

# ---------- 事件字典（后端侧常量，与前端 js/error-reporter.js 保持一致） ----------

# event：任务生命周期
EVENT_TASK_CREATED = "task_created"
EVENT_TASK_STARTED = "task_started"
EVENT_TASK_COMPLETED = "task_completed"
EVENT_TASK_FAILED = "task_failed"
EVENT_TASK_REDIRECT_STARTED = "task_redirect_started"
# event：前端轮询
EVENT_POLL_STARTED = "task_poll_started"
EVENT_POLL_FAILED = "task_poll_failed"
# event：封面 / 预览图
EVENT_PREVIEW_GENERATION_STARTED = "preview_generation_started"
EVENT_PREVIEW_GENERATION_FAILED = "preview_generation_failed"
EVENT_PREVIEW_GENERATION_COMPLETED = "preview_generation_completed"
# event：前端错误
EVENT_FRONTEND_RESOURCE_ERROR = "frontend_resource_load_failed"
EVENT_FRONTEND_RUNTIME_ERROR = "frontend_runtime_error"
EVENT_FRONTEND_API_ERROR = "frontend_api_request_failed"

# stage：阶段名
STAGE_HOME_SUBMIT = "home_submit"
STAGE_UPLOAD_PARSE = "upload_parse"
STAGE_PIPELINE = "pipeline"
STAGE_PREVIEW_GENERATION = "preview_generation"
STAGE_VIDEO_PAGE_POLLING = "video_page_polling"
STAGE_FRONTEND_RENDER = "frontend_render"

# error_type：错误大类
ERROR_TYPE_THIRD_PARTY_HTTP = "third_party_http_error"
ERROR_TYPE_TIMEOUT = "timeout"
ERROR_TYPE_RESOURCE_LOAD = "resource_load_error"
ERROR_TYPE_DB_WRITE = "db_write_error"
ERROR_TYPE_LOCAL_FILE_MISSING = "local_file_missing"
ERROR_TYPE_PROMPT_TOO_LONG = "prompt_too_long"
ERROR_TYPE_UNKNOWN = "unknown"

# 统一截断阈值（脱敏）
_PROMPT_SNAPSHOT_MAX = 200  # prompt 只存前 200 字
_RESPONSE_SNAPSHOT_MAX = 500  # 上游响应摘要最多 500 字
_MSG_MAX = 8000


def _snapshot_prompt(prompt: Optional[str]) -> Optional[Dict]:
    """prompt 脱敏快照：只存前 200 字 + 总长度，不存全文。"""
    if prompt is None:
        return None
    text = str(prompt)
    return {
        "preview": text[:_PROMPT_SNAPSHOT_MAX],
        "length": len(text),
    }


def record_website_log(
    *,
    level: str = "ERROR",
    category: str = "system",
    message: str,
    user_id: Optional[str] = None,
    username: Optional[str] = None,
    task_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    event: Optional[str] = None,
    stage: Optional[str] = None,
    error_type: Optional[str] = None,
    page_url: Optional[str] = None,
    page_title: Optional[str] = None,
    device: Optional[str] = None,
    request_method: Optional[str] = None,
    request_path: Optional[str] = None,
    request_params: Optional[Any] = None,
    error_code: Optional[str] = None,
    stack_trace: Optional[str] = None,
    context: Optional[Any] = None,
) -> Optional[int]:
    """将一条网站日志写入数据库，返回日志 id；任何异常都被吞掉以保证主流程安全。"""
    try:
        from database import SessionLocal
        from database.models import WebsiteLog

        # 若只提供了 user_id 而未提供 username，尝试从数据库反查用户名
        if user_id and not username:
            try:
                db0 = SessionLocal()
                try:
                    from database.models import User
                    user = db0.query(User).filter(User.user_id == user_id).first()
                    if user:
                        username = user.username
                finally:
                    db0.close()
            except Exception:
                pass

        # trace_id 与 task_id 1:1：未显式指定时自动对齐，保证链路可聚合
        trace_id = trace_id or task_id

        db = SessionLocal()
        try:
            row = WebsiteLog(
                level=str(level or "ERROR").upper()[:20],
                category=str(category or "system")[:50],
                message=(message or "")[:_MSG_MAX],
                user_id=user_id,
                username=(username or "")[:50],
                task_id=task_id,
                trace_id=(trace_id or "")[:36],
                event=(event or "")[:50],
                stage=(stage or "")[:50],
                error_type=(error_type or "")[:50],
                page_url=(page_url or "")[:500],
                page_title=(page_title or "")[:255],
                device=(device or "")[:255],
                request_method=(request_method or "")[:10],
                request_path=(request_path or "")[:500],
                request_params=request_params,
                error_code=(error_code or "")[:50],
                stack_trace=stack_trace,
                context=context,
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return row.id
        finally:
            db.close()
    except Exception as exc:  # 记录日志本身失败绝不影响业务
        try:
            print(f"[website_log] 记录网站日志失败: {exc}", flush=True)
        except Exception:
            pass
        return None


def record_exception(
    *,
    category: str = "system",
    message: Optional[str] = None,
    exc: Optional[BaseException] = None,
    user_id: Optional[str] = None,
    username: Optional[str] = None,
    task_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    event: Optional[str] = None,
    stage: Optional[str] = None,
    error_type: Optional[str] = None,
    page_url: Optional[str] = None,
    page_title: Optional[str] = None,
    device: Optional[str] = None,
    request_method: Optional[str] = None,
    request_path: Optional[str] = None,
    request_params: Optional[Any] = None,
    error_code: Optional[str] = None,
    context: Optional[Any] = None,
) -> Optional[int]:
    """从异常对象记录一条 ERROR 级网站日志（自动提取类型、消息与堆栈）。"""
    stack_trace = None
    if exc is not None:
        if message is None:
            message = f"{type(exc).__name__}: {exc}"
        try:
            stack_trace = "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            )
        except Exception:
            stack_trace = None
    if not message:
        message = "未知错误"
    return record_website_log(
        level="ERROR",
        category=category,
        message=message,
        user_id=user_id,
        username=username,
        task_id=task_id,
        trace_id=trace_id,
        event=event,
        stage=stage,
        error_type=error_type,
        page_url=page_url,
        page_title=page_title,
        device=device,
        request_method=request_method,
        request_path=request_path,
        request_params=request_params,
        error_code=error_code,
        stack_trace=stack_trace,
        context=context,
    )

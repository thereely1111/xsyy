from __future__ import annotations

import base64
import asyncio
import gzip
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import uuid4
from collections import deque
import threading

from dotenv import load_dotenv

if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        _reconf = getattr(_stream, "reconfigure", None)
        if callable(_reconf):
            try:
                _reconf(encoding="utf-8", errors="replace")
            except Exception:
                pass

from fastapi import FastAPI, File, UploadFile, Form, BackgroundTasks, HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, HTTPBearer
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
import time

from auth import (
    UserRegisterPassword, UserRegisterPhone, UserLogin, UserLoginPhone, SendVerificationCode,
    ForgotPassword, ResetPassword, BindPhone, BindEmail, UpdateProfile, ChangePassword, FavoriteAction,
    register_user_password, register_user_phone, send_verification_code,
    login_user, login_user_phone, forgot_password_request, reset_password, get_user_by_token,
    bind_phone, bind_email, update_profile, verify_token, change_password, toggle_favorite, get_user_favorites,
    check_and_increment_daily_calls, update_user_daily_max_calls, hash_password
)
from database import get_db, Teaching, Comment, CommentLike, TeachingLike, User, UserQuota, RechargeRequest, SessionLocal, UserViewHistory, engine, Favorite, Topic, UserFeedback, CommissionAccount, CommissionRecord, WithdrawalRequest, SystemConfig, ConfigChangeLog, WebsiteLog, Announcement, OfficialInviteCode, TaskStatus
# 网站日志：集中记录网站运行过程中的报错与异常
from website_log import record_website_log, record_exception
from website_log import (
    EVENT_TASK_CREATED, EVENT_TASK_STARTED, EVENT_TASK_COMPLETED, EVENT_TASK_FAILED,
    STAGE_HOME_SUBMIT, STAGE_PIPELINE,
    ERROR_TYPE_UNKNOWN, _snapshot_prompt,
)
from database.models import TeachingLike as TeachingLikeModel, InviteRelation, InviteProgress, Notification
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy import and_, func, or_, desc, text

# 导入管理后台模块
from admin_auth import require_admin, get_current_user as get_admin_current_user
from config import DEFAULT_BETA_CODE, DEFAULT_DAILY_MAX_CALLS, ANONYMOUS_DAILY_MAX_CALLS
from utils.vector_db import delete_teaching_embedding
# 延迟导入 embedding_utils，避免启动时加载 PyTorch
# from utils.embedding_utils import find_similar_questions

# 封面（预览图）生成模型：与首页流水线同款，供管理员"重新生成封面"使用
from generate_preview_images import generate_image_for_task, env_int, preview_backup_extra_seconds

# 导入监控模块
from monitoring import (
    http_requests_total, http_request_duration_seconds, http_requests_active,
    db_pool_size, db_pool_checked_in, db_pool_checked_out, db_pool_overflow,
    update_db_pool_metrics, update_memory_usage, get_metrics_response,
    html_cache_hits_total, html_cache_misses_total, html_cache_size,
    tasks_total, tasks_running, task_duration_seconds
)

# 安全相关
security = HTTPBearer(auto_error=False)

_log_buffer = deque(maxlen=500)
_log_subscribers = set()
_log_condition = threading.Condition()
_LOG_MAX_SUBSCRIBERS = max(1, int(os.getenv("ADMIN_LOG_MAX_SUBSCRIBERS", "10")))
_LOG_HEARTBEAT_SECONDS = 15
_BEIJING_TZ = ZoneInfo("Asia/Shanghai")


def _format_log_event(message: str, level: str, timestamp: str) -> Dict[str, str]:
    return {
        "timestamp": timestamp,
        "level": str(level or "INFO").upper(),
        "message": str(message)[:4000],
    }


def log(message: str, level: str = "INFO"):
    """输出服务日志，并保留最近事件供管理员实时查看。"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_message = f"[{timestamp}] [{level}] {message}"
    print(log_message, flush=True)
    sys.stdout.flush()

    event = _format_log_event(message, level, timestamp)
    with _log_condition:
        _log_buffer.append(event)
        for subscriber in tuple(_log_subscribers):
            subscriber.append(event)
        _log_condition.notify_all()

# 加载 .env 文件
backend_dir = Path(__file__).resolve().parent
env_path = backend_dir / ".env"
load_dotenv(dotenv_path=env_path)

DATA_DIR = Path(__file__).resolve().parent.parent / "storage"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _atomic_write_json(path: Path, data: dict, max_retries: int = 5) -> None:
    """原子写入 JSON 文件（tmp + os.replace），带重试以容忍 Windows 文件锁瞬时冲突。

    并发场景（如重新生成动画的后台流水线同时写 metadata.json / teaching_data.json）
    会触发 Windows 文件锁（WinError 5 / Errno 13 Permission denied），瞬时锁重试即可恢复。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    for attempt in range(max_retries):
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
            return
        except OSError:
            if attempt == max_retries - 1:
                raise
            time.sleep(0.5)

# HTML 缓存机制（优化加载速度）
# 缓存格式：{task_id: (content, file_mtime, is_compressed)}
# content: bytes（压缩）或 str（未压缩），is_compressed: bool
_html_cache: Dict[str, Tuple[Union[bytes, str], float, bool]] = {}
# 检查是否为低内存模式
_low_memory_mode = os.getenv("LOW_MEMORY", "").lower() in ("1", "true", "yes")
# 低内存模式下减少缓存大小
_cache_max_size = 50 if _low_memory_mode else 100  # 最多缓存 100 个 HTML，低内存模式下 50 个

def get_preview_image_name(task_dir: Path, preferred: Optional[str] = None) -> Optional[str]:
    """返回存储目录中实际存在的封面文件名，优先使用 2.0 新文件名。"""
    candidates = ["Preview.webp", "preview.webp", "preview.png"]
    if preferred in candidates and (task_dir / preferred).exists():
        return preferred
    for filename in candidates:
        if (task_dir / filename).exists():
            return filename
    return None


def check_preview_image_exists(task_dir: Path, preview_image: Optional[str]) -> bool:
    """检查预览图是否存在，并兼容数据库中的旧文件名。"""
    return get_preview_image_name(task_dir, preview_image) is not None


def get_preview_version(task_dir: Path, preview_image: Optional[str] = None) -> Optional[int]:
    """返回封面文件的修改时间戳（秒），供前端 ?v= 缓存失效参数使用。

    封面重生成后文件名不变（Preview.webp），仅 mtime 变化；前端把该值拼进
    封面 URL 的 ?v= 参数，URL 变化即可让浏览器（含已缓存旧图的用户）重新拉取。
    文件不存在或读取失败时返回 None，前端回退旧参数。
    """
    filename = get_preview_image_name(task_dir, preview_image)
    if not filename:
        return None
    try:
        return int((task_dir / filename).stat().st_mtime)
    except OSError:
        return None

# JWT 密钥（生产环境应该使用环境变量）
JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24

# 检查是否是测试模式
def is_test_mode() -> bool:
    """检查是否处于测试模式。"""
    return os.getenv("TEST_MODE", "").lower() in ("1", "true", "yes") or \
           os.getenv("USE_MOCK", "").lower() in ("1", "true", "yes")


class Task(BaseModel):
    task_id: str
    status: str = "pending"
    progress: int = 0  # 进度 0-100
    input_file: Optional[str] = None
    prompt: str = ""
    video_url: Optional[str] = None
    preview_image: Optional[str] = None
    metadata: Dict = {}
    error: Optional[str] = None
    user_id: Optional[str] = None
    topic_id: Optional[str] = None  # 所属专题ID
    preserve_on_failure: bool = False  # 管理员"重新生成"复用已有 task_id：流水线失败时不得删除已有 Teaching 记录


tasks: Dict[str, Task] = {}

# 任务内存字典上限保护（2026-09-01）：tasks 只增不减会导致长跑内存泄漏（OOM）。
# 惰性清理：仅当超过上限时移除【终态（completed/failed）】任务；
# running/pending 永不清理（metadata 等接口依赖内存态判断生成中状态）。
# 已完成任务在 DB（teachings / task_status）有完整兜底，清理不影响任何查询。
_MAX_TASKS_IN_MEMORY = int(os.getenv("MAX_TASKS_IN_MEMORY", "1000"))


def _cleanup_tasks() -> None:
    """惰性清理终态任务，防止 tasks 字典无限增长。仅在超上限时触发，正常 O(1) 短路。"""
    if len(tasks) <= _MAX_TASKS_IN_MEMORY:
        return
    stale = [tid for tid, t in tasks.items() if t.status in ("completed", "failed")]
    for tid in stale:
        if len(tasks) <= _MAX_TASKS_IN_MEMORY:
            break
        tasks.pop(tid, None)


# 任务状态落库判定：running/pending 超过该秒数仍未更新，视为任务已失效（如服务器重启后遗留记录）
TASK_STATUS_STALE_SECONDS = int(os.getenv("TASK_STATUS_STALE_SECONDS", "1800"))


def _persist_task_state(task: Task) -> None:
    """将任务状态持久化到 task_status 表，支持多 worker 部署下跨进程轮询。

    多 worker 场景：任务创建/进度更新发生在某个 worker 进程内（内存 tasks 字典），
    其他 worker 轮询 /api/tasks/{task_id} 时查不到该任务。此处把任务状态落库，
    任意 worker 都可从 task_status 表读取到进行中的任务状态，避免前端误报 not_found。

    写库失败不影响主流程（任务照常运行），仅记录日志。
    """
    # 惰性触发终态任务清理（所有任务创建/更新都会经过这里，O(1) 短路，防内存泄漏）
    _cleanup_tasks()
    if is_test_mode():
        return
    try:
        db = SessionLocal()
        try:
            row = db.query(TaskStatus).filter(TaskStatus.task_id == task.task_id).first()
            if row is None:
                row = TaskStatus(task_id=task.task_id)
                db.add(row)
            row.status = task.status
            row.progress = task.progress
            row.error = task.error
            row.video_url = task.video_url
            row.preview_image = task.preview_image
            row.user_id = task.user_id
            row.topic_id = task.topic_id
            row.prompt = task.prompt
            row.input_file = task.input_file
            # 剔除 teaching_html，避免超大字段写入（HTML 以文件形式落在 storage 目录）
            meta = dict(task.metadata or {})
            meta.pop("teaching_html", None)
            row.metadata_json = meta or None
            db.commit()
        finally:
            db.close()
    except Exception as e:
        log(f"任务状态持久化失败: {task.task_id}, {e}", "WARN")


def _load_task_state(task_id: str) -> Optional[Task]:
    """从 task_status 表读取任务状态（跨 worker 兜底）。"""
    try:
        db = SessionLocal()
        try:
            row = db.query(TaskStatus).filter(TaskStatus.task_id == task_id).first()
        finally:
            db.close()
        if row is None:
            return None
        # 进行中的任务长时间未更新（如服务器重启遗留），视为已失效，避免前端无限等待
        if row.status in ("pending", "running"):
            last_updated = row.updated_at or row.created_at
            if last_updated and (datetime.utcnow() - last_updated).total_seconds() > TASK_STATUS_STALE_SECONDS:
                return None
        return Task(
            task_id=row.task_id,
            status=row.status,
            progress=row.progress,
            error=row.error,
            video_url=row.video_url,
            preview_image=row.preview_image,
            metadata=row.metadata_json or {},
            user_id=row.user_id,
            topic_id=row.topic_id,
            prompt=row.prompt or "",
            input_file=row.input_file,
        )
    except Exception as e:
        log(f"读取任务状态失败: {task_id}, {e}", "WARN")
        return None

def _derive_generating_titles(task) -> tuple[str, str]:
    """为进行中任务推导展示标题与题目文本（用于成果库"正在生成"卡片区分）。

    兜底顺序：metadata.title → metadata.question → prompt → 上传文件名 → "正在生成中..."。
    多任务并发生成时（如专题批量导入的文件任务 prompt 为空），靠文件名兜底区分。
    """
    metadata = getattr(task, "metadata", None) or {}
    prompt = (getattr(task, "prompt", "") or "").strip()
    question = (metadata.get("question") or prompt or "").strip()
    title = (metadata.get("title") or "").strip()
    if not title and question:
        title = question[:30] + ("..." if len(question) > 30 else "")
    if not title:
        file_name = (metadata.get("source_file_name") or "").strip()
        if not file_name:
            input_file = (getattr(task, "input_file", "") or "").strip()
            if input_file:
                file_name = Path(input_file).name
        if file_name:
            title = f"文件识别：{file_name}"
    if not title:
        title = "正在生成中..."
    return title, question


def _find_active_duplicate_task(user_id: str, prompt_text: str) -> Optional[Task]:
    """查找同一用户同一题目的进行中任务（内存优先，task_status 表跨 worker 兜底）。

    用于 /api/tasks 防重：前端跳转异常后用户重试时，避免同题重复生成两份动画。
    """
    normalized = (prompt_text or "").strip()
    if not normalized or not user_id:
        return None

    candidate: Optional[Task] = None
    for task in tasks.values():
        if task.user_id != user_id or task.status not in ("pending", "running"):
            continue
        if (task.prompt or "").strip() != normalized:
            continue
        candidate = task  # 取最后一个匹配（最新创建）
    if candidate is not None:
        return candidate

    # 内存未命中 → 跨 worker 查 task_status 表（多 worker 部署下任务可能在其他进程）
    try:
        db = SessionLocal()
        try:
            row = db.query(TaskStatus).filter(
                TaskStatus.user_id == user_id,
                TaskStatus.status.in_(["pending", "running"]),
                TaskStatus.prompt == normalized,
            ).order_by(TaskStatus.created_at.desc()).first()
        finally:
            db.close()
        if row is not None:
            last_updated = row.updated_at or row.created_at
            if last_updated and (datetime.utcnow() - last_updated).total_seconds() <= TASK_STATUS_STALE_SECONDS:
                candidate = _load_task_state(row.task_id)
    except Exception as e:
        log(f"查询进行中同题任务失败（防重兜底跳过）: {e}", "WARN")
    return candidate


# 任务请求上下文：创建任务时记录触发来源（页面 / 设备 / 请求参数 / IP），
# 供动画生成失败时回溯网站日志使用（后台流水线已脱离原 HTTP 请求）。
_task_request_context: Dict[str, Dict] = {}


def _capture_task_context(
    task_id: str,
    request: Request,
    prompt: Optional[str] = None,
    page_url: Optional[str] = None,
    page_title: Optional[str] = None,
    user_id: Optional[str] = None,
) -> None:
    """记录任务创建时的请求上下文，并作为 task_created 事件落库（链路时间线第 1 条）。

    说明：_task_request_context 仅为同进程快速通道；关键信息已通过 task_created 日志
    持久化到 website_logs，多 worker 部署下其他进程的流水线可通过 trace_id 回溯。
    """
    try:
        ip = _get_client_ip(request)
        ctx = {
            "device": (request.headers.get("user-agent", "") or "")[:255],
            "ip": ip,
            "request_method": request.method,
            "request_path": str(request.url.path),
            "page_url": (page_url or request.headers.get("referer", "") or "")[:500],
            "page_title": (page_title or "")[:255],
            "request_params": _snapshot_prompt(prompt) if prompt else None,
        }
        _task_request_context[task_id] = ctx
        # 持久化链路起点：task_created 事件（trace_id 与 task_id 1:1）
        record_website_log(
            level="INFO",
            category="animation_generation",
            message=f"任务创建成功: {task_id}",
            user_id=user_id,
            task_id=task_id,
            trace_id=task_id,
            event=EVENT_TASK_CREATED,
            stage=STAGE_HOME_SUBMIT,
            page_url=ctx.get("page_url"),
            page_title=ctx.get("page_title"),
            device=ctx.get("device"),
            request_method=ctx.get("request_method"),
            request_path=ctx.get("request_path"),
            request_params=ctx.get("request_params"),
            context={
                "ip": ip,
                "prompt_snapshot": ctx.get("request_params"),
            },
        )
    except Exception:
        pass


def _get_task_context(task_id: str) -> Dict:
    """获取任务创建上下文：优先内存快速通道，未命中则从 task_created 日志回溯（跨 worker）。"""
    ctx = _task_request_context.get(task_id)
    if ctx is not None:
        return ctx
    try:
        db = SessionLocal()
        try:
            row = (
                db.query(WebsiteLog)
                .filter(WebsiteLog.trace_id == task_id, WebsiteLog.event == EVENT_TASK_CREATED)
                .order_by(WebsiteLog.id.asc())
                .first()
            )
            if row:
                ctx = {
                    "device": row.device or "",
                    "ip": (row.context or {}).get("ip") if row.context else None,
                    "request_method": row.request_method or "",
                    "request_path": row.request_path or "",
                    "page_url": row.page_url or "",
                    "page_title": row.page_title or "",
                    "request_params": row.request_params,
                }
                _task_request_context[task_id] = ctx
                return ctx
        except Exception:
            pass
        finally:
            db.close()
    except Exception:
        pass
    return {}


def _record_pipeline_log(
    task_id: str,
    level: str,
    category: str,
    message: str,
    *,
    event: Optional[str] = None,
    stage: Optional[str] = None,
    error_type: Optional[str] = None,
    stack_trace: Optional[str] = None,
    context_extra: Optional[dict] = None,
) -> None:
    """把动画生成相关事件写入网站日志，并附带任务创建时的请求上下文（跨进程可回溯）。"""
    task = tasks.get(task_id)
    user_id = task.user_id if task else None
    ctx = _get_task_context(task_id)
    merged_context = None
    if ctx.get("request_params") or context_extra:
        merged_context = {**(ctx.get("request_params") or {}), **(context_extra or {})}
    record_website_log(
        level=level,
        category=category,
        message=message,
        user_id=user_id,
        task_id=task_id,
        trace_id=task_id,
        event=event,
        stage=stage,
        error_type=error_type,
        device=ctx.get("device"),
        page_url=ctx.get("page_url"),
        page_title=ctx.get("page_title"),
        request_method=ctx.get("request_method"),
        request_path=ctx.get("request_path"),
        request_params=ctx.get("request_params"),
        stack_trace=stack_trace,
        context=merged_context,
    )

_pipeline: Any = None
_optimized_generation_service: Any = None
_task_reuse_cache: Any = None


def get_pipeline():
    """按需创建主流水线，避免应用启动时加载重依赖。"""
    global _pipeline
    if _pipeline is None:
        from pipeline import LangChainPipeline

        _pipeline = LangChainPipeline()
    return _pipeline


def get_optimized_generation_service():
    """按需创建测试/优化服务，避免启动时初始化 Gemini 和缓存依赖。"""
    global _optimized_generation_service
    if _optimized_generation_service is None:
        from cost_optimization_demo.main_service import AnimationGenerationService

        _optimized_generation_service = AnimationGenerationService()
    return _optimized_generation_service


def get_task_reuse_cache():
    """按需创建题目复用缓存，避免启动时连接 Redis。"""
    global _task_reuse_cache
    if _task_reuse_cache is None:
        from cost_optimization_demo.cache_service import TeachingCacheService

        _task_reuse_cache = TeachingCacheService()
    return _task_reuse_cache

_TASK_REUSE_EXTRA_CONTEXT = {
    "route": "/api/tasks",
    "kind": "teaching_reuse",
    "version": "v2-canvas-layer-isolation",
}

_TASK_REUSE_SIMILARITY_THRESHOLD = float(os.getenv("TEACHING_REUSE_SIMILARITY_THRESHOLD", "0.85"))
_TASK_REUSE_TOKEN_OVERLAP_THRESHOLD = float(os.getenv("TEACHING_REUSE_TOKEN_OVERLAP_THRESHOLD", "0.45"))
_TASK_REUSE_CANDIDATE_LIMIT = max(3, int(os.getenv("TEACHING_REUSE_CANDIDATE_LIMIT", "8")))
_TASK_REUSE_TAG_BOOST_TOKEN_OVERLAP = float(os.getenv("TEACHING_REUSE_TAG_BOOST_TOKEN_OVERLAP", "0.35"))
# 语义复用（embedding 向量检索）总开关。默认关闭：embedding 计算不稳定，先停用该功能。
# 置为 true 可重新启用。
_TASK_REUSE_ENABLED = os.getenv("TEACHING_SEMANTIC_REUSE_ENABLED", "false").strip().lower() in (
    "1", "true", "yes", "on",
)


def _build_task_reuse_prompt_hash(prompt: str) -> str:
    """构建 /api/tasks 同题复用哈希。"""
    return get_task_reuse_cache().build_prompt_hash(
        problem=(prompt or "").strip(),
        difficulty="default",
        extra_context=_TASK_REUSE_EXTRA_CONTEXT,
    )


def _set_task_reuse_mapping(prompt: str, task_id: str) -> Optional[str]:
    """写入同题复用映射：prompt_hash -> task_id。"""
    if not (prompt or "").strip():
        return None
    prompt_hash = _build_task_reuse_prompt_hash(prompt)
    get_task_reuse_cache().set(prompt_hash, task_id)
    return prompt_hash


def _try_get_reused_task_id(prompt: str) -> tuple[Optional[str], Optional[str]]:
    """尝试按题目命中缓存映射。

    返回：(prompt_hash, source_task_id)
    """
    prompt_text = (prompt or "").strip()
    if not prompt_text:
        return None, None

    prompt_hash = _build_task_reuse_prompt_hash(prompt_text)
    cached_task_id = get_task_reuse_cache().get(prompt_hash)
    return prompt_hash, cached_task_id


def _tokenize_for_reuse_similarity(text: str) -> set[str]:
    """将题目拆成用于复用判断的 token 集合。"""
    normalized_text = re.sub(r"\s+", "", (text or "").lower())
    normalized_text = re.sub(r"\d+(\.\d+)?", "num", normalized_text)
    tokens: set[str] = set()

    for chunk in re.findall(r"[\u4e00-\u9fff]+|[A-Za-z0-9]+", normalized_text):
        if len(chunk) < 2:
            continue
        if re.fullmatch(r"[A-Za-z0-9]+", chunk):
            tokens.add(chunk)
            continue
        tokens.update(chunk[index:index + 2] for index in range(len(chunk) - 1))

    if tokens:
        return tokens
    return set(ch for ch in normalized_text if ch.strip())


def _calculate_reuse_token_coverage(source_text: str, candidate_text: str) -> float:
    """计算候选题目对源题目的 token 覆盖率。"""
    source_tokens = _tokenize_for_reuse_similarity(source_text)
    if not source_tokens:
        return 0.0
    candidate_tokens = _tokenize_for_reuse_similarity(candidate_text)
    if not candidate_tokens:
        return 0.0
    return len(source_tokens & candidate_tokens) / len(source_tokens)


def _teaching_has_canvas_layer_isolation(task_id: str) -> bool:
    """仅允许复用包含持久层和步骤临时层的新动画数据。"""
    data_path = DATA_DIR / task_id / "teaching_data.json"
    if not data_path.exists():
        return False

    try:
        teaching_data = json.loads(data_path.read_text(encoding="utf-8"))
        scene_svg = str(teaching_data.get("scene_svg", ""))
    except (OSError, json.JSONDecodeError):
        return False

    temporary_layers = re.findall(
        r'<g\s+id=["\']temporary-layer-step-[^"\']+["\'][^>]*>',
        scene_svg,
        flags=re.IGNORECASE,
    )
    return bool(
        re.search(r'<g\s+id=["\']persistent-layer["\']', scene_svg, re.IGNORECASE)
        and temporary_layers
        and all("sceneStep ===" in layer for layer in temporary_layers)
    )


def _materialize_reused_task_response(
    db: Session,
    prompt_hash: str,
    source_task_id: str,
    prompt_text: str,
) -> tuple[Optional[TaskResponse], Optional[str]]:
    """将复用命中的教学内容转换为任务响应。

    返回：(TaskResponse, 命中来源)；命中来源为 memory / database。
    """
    source_task = tasks.get(source_task_id)
    if (
        source_task
        and source_task.status == "completed"
        and str(source_task.metadata.get("teaching_html", "")).strip()
    ):
        return TaskResponse(
            task_id=source_task_id,
            status="completed",
            progress=100,
            preview_image=source_task.preview_image,
            metadata={
                "is_reused": True,
                "source_task_id": source_task_id,
                "prompt_hash": prompt_hash,
            },
        ), "memory"

    reused_teaching = db.query(Teaching).filter(Teaching.task_id == source_task_id).first()
    if reused_teaching:
        task_data_dir = DATA_DIR / source_task_id
        has_content = (task_data_dir / "teaching_data.json").exists() or (task_data_dir / "teaching.html").exists()
        if has_content:
            if source_task_id not in tasks:
                tasks[source_task_id] = Task(
                    task_id=source_task_id,
                    status="completed",
                    progress=100,
                    prompt=reused_teaching.prompt or prompt_text,
                    video_url=None,
                    preview_image=reused_teaching.preview_image,
                    metadata={
                        "question": reused_teaching.question or prompt_text,
                        "title": reused_teaching.title or "",
                        "is_reused": True,
                        "source_task_id": source_task_id,
                        "prompt_hash": prompt_hash,
                    },
                    user_id=reused_teaching.user_id,
                    topic_id=reused_teaching.topic_id,
                )

            return TaskResponse(
                task_id=source_task_id,
                status="completed",
                progress=100,
                preview_image=reused_teaching.preview_image,
                metadata={
                    "is_reused": True,
                    "source_task_id": source_task_id,
                    "prompt_hash": prompt_hash,
                },
            ), "database"

    return None, None


def _infer_query_main_tag(similar_items: list[dict]) -> Optional[str]:
    """从 Chroma 候选结果中推断查询题目最可能的 main_tag。"""
    tag_counts: dict[str, int] = {}
    total_with_tag = 0
    for item in similar_items:
        meta = item.get("metadata") or {}
        tag = meta.get("main_tag")
        if tag and isinstance(tag, str) and tag.strip():
            tag = tag.strip()
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
            total_with_tag += 1
    if not tag_counts or total_with_tag < 2:
        return None
    best_tag = max(tag_counts, key=tag_counts.get)
    if tag_counts[best_tag] >= total_with_tag * 0.5:
        return best_tag
    return None


async def _find_semantic_reused_task_id(db: Session, prompt_text: str) -> tuple[Optional[str], Optional[float]]:
    """通过向量相似度查找可复用的教学内容。"""
    prompt_text = (prompt_text or "").strip()
    if not prompt_text:
        return None, None

    if not _TASK_REUSE_ENABLED:
        # 语义复用功能已停用（embedding 不稳定），不再调用向量检索
        return None, None

    try:
        from utils.embedding_utils import get_question_embedding_async
        from utils.vector_db import query_similar_teachings

        embedding = await get_question_embedding_async(prompt_text)
        if not embedding:
            log("语义复用：embedding 计算失败，跳过", "REUSE")
            return None, None

        similar_items = query_similar_teachings(
            query_embedding=embedding,
            n_results=_TASK_REUSE_CANDIDATE_LIMIT,
        )
        if not similar_items:
            log("语义复用：Chroma 无候选结果", "REUSE")
            return None, None

        inferred_main_tag = _infer_query_main_tag(similar_items)
        log(f"语义复用：共 {len(similar_items)} 个候选，推断 main_tag={inferred_main_tag or '未知'}", "REUSE")

        best_task_id: Optional[str] = None
        best_similarity = 0.0
        gate_fail_counts = {"cosine": 0, "db_missing": 0, "html_missing": 0, "layer_isolation": 0, "token_coverage": 0}

        for item in similar_items:
            task_id = item.get("id")
            if not task_id:
                continue

            similarity = float(item.get("similarity") or 0.0)
            if similarity < _TASK_REUSE_SIMILARITY_THRESHOLD:
                gate_fail_counts["cosine"] += 1
                continue

            teaching = db.query(Teaching).filter(Teaching.task_id == task_id).first()
            if not teaching:
                gate_fail_counts["db_missing"] += 1
                continue

            if not _teaching_has_canvas_layer_isolation(task_id):
                gate_fail_counts["layer_isolation"] = gate_fail_counts.get("layer_isolation", 0) + 1
                log(f"  候选 {task_id}: 不符合画布分层规则 -> 拒绝", "REUSE")
                continue

            teaching_html_path = DATA_DIR / task_id / teaching.teaching_html_file
            if not teaching_html_path.exists():
                gate_fail_counts["html_missing"] += 1
                continue

            candidate_text = teaching.question or item.get("document") or teaching.prompt or ""
            token_coverage = _calculate_reuse_token_coverage(prompt_text, candidate_text)

            effective_threshold = _TASK_REUSE_TOKEN_OVERLAP_THRESHOLD
            if inferred_main_tag:
                candidate_meta = item.get("metadata") or {}
                candidate_tag = (candidate_meta.get("main_tag") or "").strip()
                if candidate_tag == inferred_main_tag:
                    effective_threshold = _TASK_REUSE_TAG_BOOST_TOKEN_OVERLAP

            if token_coverage < effective_threshold:
                gate_fail_counts["token_coverage"] += 1
                log(
                    f"  候选 {task_id}: cosine={similarity:.3f}, "
                    f"coverage={token_coverage:.3f} < {effective_threshold:.2f} -> 拒绝",
                    "REUSE",
                )
                continue

            log(
                f"  候选 {task_id}: cosine={similarity:.3f}, "
                f"coverage={token_coverage:.3f} >= {effective_threshold:.2f} -> 通过",
                "REUSE",
            )
            if similarity > best_similarity:
                best_task_id = task_id
                best_similarity = similarity

        if best_task_id:
            log(f"语义复用命中：task_id={best_task_id}, similarity={best_similarity:.3f}", "REUSE")
        else:
            log(f"语义复用未命中，各门拒绝统计: {gate_fail_counts}", "REUSE")

        return best_task_id, best_similarity if best_task_id else None
    except Exception as exc:
        log(f"语义复用候选查询失败: {exc}", "WARN")
        return None, None

# 匿名用户每日调用计数（按客户端IP，进程内存级）
_anonymous_daily_calls: Dict[str, Tuple[date, int]] = {}
_anonymous_calls_lock = asyncio.Lock()


def _get_client_ip(request: Request) -> str:
    """获取客户端 IP，优先使用反向代理头。"""
    cf_ip = request.headers.get("cf-connecting-ip", "")
    if cf_ip:
        return cf_ip.strip()

    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip", "")
    if real_ip:
        return real_ip.strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _get_request_host(request: Request) -> str:
    """获取请求域名（去掉端口）。"""
    xfh = request.headers.get("x-forwarded-host", "")
    raw_host = xfh or request.headers.get("host", "")
    host = raw_host.split(",")[0].strip().lower()
    if ":" in host:
        host = host.split(":", 1)[0]
    return host


def _get_anonymous_daily_limit(host: str) -> int:
    """按域名读取匿名用户每日调用上限，未命中则回退全局配置。"""
    normalized = (host or "").strip().lower().replace(".", "_").replace("-", "_")
    if normalized:
        per_host_key = f"ANONYMOUS_DAILY_MAX_CALLS_{normalized.upper()}"
        value = os.getenv(per_host_key)
        if value is not None:
            try:
                return max(0, int(value))
            except ValueError:
                log(f"环境变量 {per_host_key} 不是有效整数，回退全局匿名上限", "WARN")

    return ANONYMOUS_DAILY_MAX_CALLS


async def _check_and_increment_anonymous_daily_calls(client_ip: str, host: str) -> tuple[bool, str, int, int]:
    """检查并增加匿名用户当日调用次数。"""
    today = date.today()
    key = f"{host or 'unknown'}|{client_ip or 'unknown'}"
    daily_limit = _get_anonymous_daily_limit(host)

    async with _anonymous_calls_lock:
        last_date, current_count = _anonymous_daily_calls.get(key, (today, 0))
        if last_date != today:
            current_count = 0

        if current_count >= daily_limit:
            return False, f"匿名用户今日调用次数已达上限（{daily_limit}次），请登录后继续使用", current_count, daily_limit

        current_count += 1
        _anonymous_daily_calls[key] = (today, current_count)
        remaining = daily_limit - current_count
        return True, f"调用成功，匿名用户今日剩余 {remaining} 次", current_count, daily_limit


def _reset_user_daily_calls_if_needed(user: User, db: Session) -> None:
    """在需要时重置用户当日调用次数。"""
    today = date.today()
    if user.last_call_date is None or user.last_call_date.date() < today:
        user.daily_calls_count = 0
        user.last_call_date = datetime.utcnow()
        db.commit()


def _get_user_daily_remaining_calls(user_id: str, db: Session) -> tuple[int, int]:
    """读取当前用户的剩余调用次数。"""
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        return 0, 0

    _reset_user_daily_calls_if_needed(user, db)
    remaining = max(0, user.daily_max_calls - user.daily_calls_count)
    return remaining, user.daily_max_calls


async def _get_anonymous_daily_remaining_calls(client_ip: str, host: str) -> tuple[int, int]:
    """读取匿名用户的剩余调用次数。"""
    today = date.today()
    key = f"{host or 'unknown'}|{client_ip or 'unknown'}"
    daily_limit = _get_anonymous_daily_limit(host)

    async with _anonymous_calls_lock:
        last_date, current_count = _anonymous_daily_calls.get(key, (today, 0))
        if last_date != today:
            current_count = 0
            _anonymous_daily_calls[key] = (today, current_count)

        remaining = max(0, daily_limit - current_count)
        return remaining, daily_limit


def _read_text_bytes(content: bytes) -> str:
    """按常见编码顺序解码文本文件。"""
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "gbk", "big5"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="ignore")


def _extract_docx_text_and_images(file_path: Path) -> tuple[str, list[str]]:
    """提取 docx 文本与内嵌图片（base64）。"""
    try:
        from docx import Document
    except ImportError as exc:
        raise RuntimeError("缺少 python-docx 依赖，请先安装 python-docx 后再上传 .docx 文件") from exc

    document = Document(str(file_path))
    text_chunks: list[str] = []

    for paragraph in document.paragraphs:
        paragraph_text = (paragraph.text or "").strip()
        if paragraph_text:
            text_chunks.append(paragraph_text)

    for table in document.tables:
        for row in table.rows:
            row_text = " ".join((cell.text or "").strip() for cell in row.cells).strip()
            if row_text:
                text_chunks.append(row_text)

    images: list[str] = []
    try:
        with zipfile.ZipFile(file_path) as archive:
            for file_name in archive.namelist():
                if not file_name.startswith("word/media/"):
                    continue
                image_bytes = archive.read(file_name)
                if not image_bytes:
                    continue
                encoded = base64.b64encode(image_bytes).decode("utf-8")
                images.append(encoded)
    except Exception as exc:
        log(f"提取 docx 内嵌图片失败: {exc}", "WARN")

    return "\n".join(text_chunks).strip(), images


def _extract_pdf_text(file_path: Path) -> str:
    """提取 PDF 文本。"""
    try:
        from pypdf import PdfReader  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("缺少 pypdf 依赖，请先安装 pypdf 后再上传 PDF 文件") from exc

    reader = PdfReader(str(file_path))
    text_chunks: list[str] = []
    for page in reader.pages:
        try:
            page_text = page.extract_text() or ""
        except Exception:
            page_text = ""
        if page_text.strip():
            text_chunks.append(page_text.strip())

    return "\n".join(text_chunks).strip()


def _extract_doc_text(file_path: Path) -> str:
    """尽力提取旧版 .doc 文本。"""
    try:
        import textract  # type: ignore[import-not-found]
    except ImportError:
        textract = None

    if textract is not None:
        try:
            raw_text = textract.process(str(file_path))
            return _read_text_bytes(raw_text).strip()
        except Exception as exc:
            log(f"textract 解析 .doc 失败: {exc}", "WARN")

    try:
        completed = subprocess.run(
            ["antiword", str(file_path)],
            capture_output=True,
            text=True,
            check=True,
        )
        return (completed.stdout or "").strip()
    except Exception as exc:
        raise RuntimeError("当前环境无法解析 .doc 文件，请安装 textract 或 antiword 后重试") from exc


def _extract_text_from_plain_file(file_path: Path) -> str:
    """提取纯文本文件内容。"""
    with file_path.open("rb") as file_handle:
        return _read_text_bytes(file_handle.read()).strip()


def _extract_json_array_text(raw_text: str) -> str:
    """从模型输出中提取 JSON 数组。"""
    if not raw_text:
        return ""

    code_block_match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", raw_text, re.DOTALL | re.IGNORECASE)
    if code_block_match:
        return code_block_match.group(1).strip()

    start_index = raw_text.find("[")
    if start_index == -1:
        return raw_text.strip()

    bracket_count = 0
    in_string = False
    escape_next = False
    for index in range(start_index, len(raw_text)):
        char = raw_text[index]

        if escape_next:
            escape_next = False
            continue

        if char == "\\":
            escape_next = True
            continue

        if char == '"':
            in_string = not in_string
            continue

        if in_string:
            continue

        if char == "[":
            bracket_count += 1
        elif char == "]":
            bracket_count -= 1
            if bracket_count == 0:
                return raw_text[start_index:index + 1].strip()

    return raw_text.strip()


async def _ocr_image_to_text(file_path: Path) -> str:
    """使用现有图片识别能力提取图片中的题目文本。"""
    pipeline = get_pipeline()
    analysis_result = await pipeline._analyze_image_question(str(file_path))
    if not analysis_result:
        log("图片识别失败，未提取到题目文本", "WARN")
        return ""

    if not analysis_result.get("is_math_problem", True):
        # 区分"非数学题"与"识别失败"，给用户明确提示而非笼统"请重新上传"
        raise RuntimeError("未能识别为数学题，请确认图片清晰完整后重拍，或手动输入题目。")

    return (analysis_result.get("question") or "").strip()


async def _split_questions_from_source_text(source_text: str, source_name: str, source_images: Optional[list[str]] = None) -> list[dict]:
    """调用 gpt-5.5 将输入拆分成题目数组。"""
    text_content = (source_text or "").strip()
    if not text_content:
        return []

    trimmed_text = text_content[:20000]
    system_prompt = (
        "请严格识别此文件中的所有题目。以 JSON 数组格式输出，每道题目为一个对象，包含 ‘title’（题干文本）和 ‘images’（base64 编码的图片数组）字段。如果无图片，images 为 []。"
        "不要输出任何额外文字。"
    )
    user_prompt = (
        f"文件名：{source_name}\n"
        f"识别到的图片数量：{len(source_images or [])}\n\n"
        f"文件内容：\n{trimmed_text}"
    )

    llm = get_pipeline()._get_llm_analyzer()
    response = await llm.ainvoke(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
    )
    raw_output = response.content if hasattr(response, "content") else str(response)
    log(f"题目拆分 - API 原始输出:\n{raw_output}", "DETAIL")
    json_text = _extract_json_array_text(raw_output)

    try:
        parsed = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"题目拆分结果不是有效 JSON 数组: {exc}") from exc

    if isinstance(parsed, dict):
        parsed = parsed.get("questions", [])

    if not isinstance(parsed, list):
        raise RuntimeError("题目拆分结果格式不正确，预期为 JSON 数组")

    normalized_questions: list[dict] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("question") or item.get("content") or "").strip()
        if not title:
            continue

        images = item.get("images") or []
        if not isinstance(images, list):
            images = []
        images = [str(image).strip() for image in images if str(image).strip()]

        normalized_questions.append({
            "title": title,
            "images": images,
        })

    log(f"题目拆分 - 解析得到题目数: {len(normalized_questions)}", "DETAIL")
    return normalized_questions


async def _parse_uploaded_file_to_questions(file_path: Path, source_name: str, source_type: str) -> list[dict]:
    """根据上传文件类型提取题目并拆分。"""
    normalized_type = (source_type or "").strip().lower()
    suffix = file_path.suffix.lower()

    if normalized_type == "image" or suffix in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}:
        source_text = await _ocr_image_to_text(file_path)
        source_images: list[str] = []
        questions = await _split_questions_from_source_text(source_text, source_name, source_images)
        if not questions and source_text:
            # 图片上传通常只有一道题：拆分模型判空时直接回退，用 OCR 提取的题目文本作为题目，
            # 避免"分类成功但二次拆分判空"导致误报"没有识别到题目"。
            log("图片题目拆分为空，回退使用 OCR 提取文本作为题目", "WARN")
            questions = [{"title": source_text, "images": []}]
        return questions
    elif suffix == ".docx":
        source_text, source_images = _extract_docx_text_and_images(file_path)
    elif suffix == ".pdf":
        source_text = _extract_pdf_text(file_path)
        source_images = []
    elif suffix == ".doc":
        source_text = _extract_doc_text(file_path)
        source_images = []
    elif suffix == ".txt":
        source_text = _extract_text_from_plain_file(file_path)
        source_images = []
    else:
        raise RuntimeError("不支持的文件格式，仅支持 .docx、.doc、.pdf、.txt 以及图片文件")

    return await _split_questions_from_source_text(source_text, source_name, source_images)


async def _run_upload_and_parse_pipeline(task_id: str) -> None:
    """后台解析上传文件的第一道题，再复用现有流水线生成教学内容。"""
    task = tasks[task_id]
    input_file = (task.input_file or "").strip()
    if not input_file:
        task.status = "failed"
        task.progress = 0
        task.error = "未找到上传文件"
        task.metadata = {
            **(task.metadata or {}),
            "upload_mode": "upload-and-parse",
        }
        _persist_task_state(task)
        return

    input_path = Path(input_file)
    upload_metadata = task.metadata or {}
    source_file_name = upload_metadata.get("source_file_name") or input_path.name
    source_type = upload_metadata.get("source_type") or "document"
    file_suffix = input_path.suffix.lower()

    try:
        task_question_items = await _parse_uploaded_file_to_questions(input_path, source_file_name, source_type)
        if not task_question_items:
            raise RuntimeError("本次没有识别到题目，请重新上传。")

        question_item = task_question_items[0] or {}
        question_title = str(question_item.get("title") or "").strip()
        if not question_title:
            raise RuntimeError("本次没有识别到题目，请重新上传。")

        question_images = question_item.get("images") or []
        task.prompt = question_title
        task.metadata = {
            **upload_metadata,
            "question_index": 1,
            "questions_total": len(task_question_items),
            "source_images": question_images,
            "source_upload_type": file_suffix,
            "upload_mode": "upload-and-parse",
            "source_question": question_title,
        }
        await run_pipeline(task_id)
    except Exception as exc:
        task.status = "failed"
        task.progress = 0
        task.error = str(exc)
        task.metadata = {
            **upload_metadata,
            "source_upload_type": file_suffix,
            "upload_mode": "upload-and-parse",
        }
        _persist_task_state(task)
        log(f"上传解析任务失败: task_id={task_id}, error={exc}", "ERROR")
        if not is_test_mode() and input_path.exists():
            temp_dir = input_path.parent
            if temp_dir.exists() and "temp_upload_" in temp_dir.name:
                try:
                    shutil.rmtree(temp_dir)
                    log(f"上传解析失败，已清理临时目录: {temp_dir}", "CLEANUP")
                except Exception as cleanup_exc:
                    log(f"清理上传解析临时目录失败: {cleanup_exc}", "WARN")


def _create_pipeline_task(
    background_tasks: BackgroundTasks,
    *,
    prompt: str,
    user_id: Optional[str],
    topic_id: Optional[str],
    metadata: Optional[Dict] = None,
) -> str:
    """创建并注册一个后台教学任务。"""
    task_id = str(uuid4())
    task = Task(
        task_id=task_id,
        status="pending",
        progress=0,
        input_file=None,
        prompt=prompt,
        metadata=metadata or {},
        user_id=user_id,
        topic_id=topic_id,
    )
    tasks[task_id] = task
    _persist_task_state(task)
    tasks_total.labels(status="pending").inc()
    background_tasks.add_task(run_pipeline, task_id)
    return task_id

# --- 应用生命周期（取代已废弃的 @app.on_event）---
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(_app: "FastAPI"):
    # 启动逻辑（原 startup_event）
    try:
        from database import init_db
        init_db()
    except Exception as exc:
        log(f"数据库初始化失败: {exc}", "WARN")

    try:
        from tag_agent.db import create_tables as create_tag_agent_tables
        await create_tag_agent_tables()
        log("标签识别智能体数据表就绪", "STARTUP")
    except Exception as exc:
        log(f"标签识别智能体建表失败: {exc}", "WARN")

    yield

    # 关闭逻辑（原 shutdown_event）
    log("=" * 60)
    log("XSYY LangChain Backend 服务关闭", "SHUTDOWN")
    log("=" * 60)

app = FastAPI(
    lifespan=lifespan,
    title="XSYY LangChain Backend",
    version="0.1.0",
    description="后端服务：上传题目 -> LangChain Agent -> 动画/视频讲解",
)

try:
    from tag_agent.router import router as tag_agent_router
    app.include_router(tag_agent_router)
    print("已成功注册进程内标签智能体路由")
except Exception as exc:
    print(f"注册进程内标签智能体路由失败: {exc}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 配置静态文件服务（用于提供web目录下的HTML文件）
# 获取web目录的绝对路径
WEB_DIR = Path(__file__).parent.parent / "web"
if WEB_DIR.exists():
    # 挂载 /web 路径，提供静态文件服务
    app.mount("/web", StaticFiles(directory=str(WEB_DIR), html=True), name="web")


# 添加请求监控中间件
class MetricsMiddleware(BaseHTTPMiddleware):
    """监控所有 HTTP 请求的中间件"""
    async def dispatch(self, request: Request, call_next):
        # 获取端点路径（简化，去掉参数）
        endpoint = request.url.path
        method = request.method
        
        # 增加活跃请求数
        http_requests_active.inc()
        
        start_time = time.time()
        status_code = 200
        
        try:
            response = await call_next(request)
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


app.add_middleware(MetricsMiddleware)


# 全局 5xx 错误日志中间件：集中记录网站运行过程中产生的服务端未捕获报错。
class WebsiteErrorLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if response.status_code >= 500:
            try:
                auth = request.headers.get("authorization", "")
                token = auth[7:].strip() if auth.startswith("Bearer ") else None
                user_id = verify_token(token) if token else None
                record_website_log(
                    level="ERROR",
                    category="server_error",
                    message=f"HTTP {response.status_code} at {request.method} {request.url.path}",
                    user_id=user_id,
                    page_url=request.headers.get("referer", ""),
                    device=request.headers.get("user-agent", ""),
                    request_method=request.method,
                    request_path=str(request.url.path),
                    context={"query": str(request.url.query)[:500]},
                )
            except Exception:
                pass
        return response


app.add_middleware(WebsiteErrorLoggingMiddleware)

# --- 引入自定义路由 ---
try:
    from ai_teacher_route import router as ai_teacher_router
    app.include_router(ai_teacher_router)
    print("已成功注册 AI 助教路由")
except Exception as e:
    print(f"注册 AI 助教路由失败: {e}")

try:
    from invite_quota_api import router as invite_quota_router
    app.include_router(invite_quota_router)
    print("已成功注册邀请与配额路由(v2)")
except Exception as e:
    print(f"注册邀请与配额路由失败: {e}")

try:
    from admin_invite_api import router as admin_invite_router
    app.include_router(admin_invite_router)
    print("已成功注册后台邀请与额度管理路由(只读)")
except Exception as e:
    print(f"注册后台邀请与额度管理路由失败: {e}")

# 启动/关闭逻辑已迁移至上方 lifespan()（取代已废弃的 @app.on_event）

    try:
        from tag_agent.router import get_orchestrator
        get_orchestrator()
        log("标签识别智能体已预热", "STARTUP")
    except Exception as exc:
        log(f"标签识别智能体预热失败: {exc}", "WARN")

    log("=" * 60)
    log("XSYY LangChain Backend 服务启动", "STARTUP")
    log(f"存储目录: {DATA_DIR}")
    log(f"测试模式: {'是' if is_test_mode() else '否'}")
    log("性能监控已启用（Prometheus）", "STARTUP")


@app.get("/api/admin/logs")
async def admin_get_logs(
    limit: int = 500,
    admin_user: User = Depends(require_admin),
):
    """获取最近服务日志（管理员）。"""
    del admin_user
    with _log_condition:
        events = list(_log_buffer)[-min(max(1, limit), _log_buffer.maxlen):]
    return {"logs": events}


@app.get("/api/admin/logs/stream")
async def admin_stream_logs(
    request: Request,
    admin_user: User = Depends(require_admin),
):
    """通过 SSE 推送历史及实时服务日志（管理员）。"""
    del admin_user
    subscriber = deque()
    with _log_condition:
        if len(_log_subscribers) >= _LOG_MAX_SUBSCRIBERS:
            raise HTTPException(status_code=503, detail="日志订阅人数已达上限")
        subscriber.extend(_log_buffer)
        _log_subscribers.add(subscriber)

    async def event_stream():
        try:
            while True:
                if await request.is_disconnected():
                    break

                def wait_for_event():
                    with _log_condition:
                        if not subscriber:
                            _log_condition.wait(timeout=_LOG_HEARTBEAT_SECONDS)
                        events = list(subscriber)
                        subscriber.clear()
                    return events

                events = await asyncio.to_thread(wait_for_event)
                if events:
                    for event in events:
                        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                else:
                    yield ": heartbeat\n\n"
        finally:
            with _log_condition:
                _log_subscribers.discard(subscriber)
                subscriber.clear()


    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ==================== 网站日志 API ====================
# 用于管理后台"网站日志"模块：集中查看网站运行过程中产生的所有报错与异常。
class ClientErrorReport(BaseModel):
    level: Optional[str] = "ERROR"
    category: Optional[str] = "client_page"
    message: str
    page_url: Optional[str] = ""
    page_title: Optional[str] = ""
    device: Optional[str] = ""
    error_code: Optional[str] = ""
    stack_trace: Optional[str] = ""
    context: Optional[Dict] = None
    # 结构化事件字段（事件字典，与 website_log.py 常量对齐）
    event: Optional[str] = ""
    stage: Optional[str] = ""
    error_type: Optional[str] = ""
    task_id: Optional[str] = ""
    trace_id: Optional[str] = ""


def _website_log_to_dict(row: "WebsiteLog") -> Dict:
    return {
        "id": row.id,
        "createdAt": row.created_at.isoformat() + "Z" if row.created_at else None,
        "level": row.level,
        "category": row.category,
        "message": row.message,
        "userId": row.user_id,
        "username": row.username,
        "taskId": row.task_id,
        "traceId": row.trace_id,
        "event": row.event,
        "stage": row.stage,
        "errorType": row.error_type,
        "pageUrl": row.page_url,
        "pageTitle": row.page_title,
        "device": row.device,
        "requestMethod": row.request_method,
        "requestPath": row.request_path,
        "requestParams": row.request_params,
        "errorCode": row.error_code,
        "stackTrace": row.stack_trace,
        "context": row.context,
    }


@app.get("/api/admin/website-logs")
async def admin_list_website_logs(
    page: int = 1,
    page_size: int = 30,
    level: Optional[str] = None,
    category: Optional[str] = None,
    user_id: Optional[str] = None,
    task_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    event: Optional[str] = None,
    stage: Optional[str] = None,
    error_type: Optional[str] = None,
    search: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """管理员获取网站日志列表（支持分页、级别/类别/用户/链路/事件筛选、关键词搜索、时间范围）。"""
    page = max(1, page)
    page_size = min(max(1, page_size), 200)

    query = db.query(WebsiteLog)
    if level:
        query = query.filter(WebsiteLog.level == level.upper())
    if category:
        query = query.filter(WebsiteLog.category == category)
    if user_id:
        query = query.filter(WebsiteLog.user_id == user_id)
    if task_id:
        query = query.filter(WebsiteLog.task_id == task_id)
    if trace_id:
        query = query.filter(WebsiteLog.trace_id == trace_id)
    if event:
        query = query.filter(WebsiteLog.event == event)
    if stage:
        query = query.filter(WebsiteLog.stage == stage)
    if error_type:
        query = query.filter(WebsiteLog.error_type == error_type)
    if search and search.strip():
        kw = f"%{search.strip()}%"
        query = query.filter(or_(
            WebsiteLog.message.like(kw),
            WebsiteLog.username.like(kw),
            WebsiteLog.user_id.like(kw),
            WebsiteLog.task_id.like(kw),
            WebsiteLog.trace_id.like(kw),
            WebsiteLog.page_url.like(kw),
            WebsiteLog.error_code.like(kw),
        ))
    if start_date:
        start_at = datetime.fromisoformat(start_date).replace(tzinfo=_BEIJING_TZ).astimezone(timezone.utc).replace(tzinfo=None)
        query = query.filter(WebsiteLog.created_at >= start_at)
    if end_date:
        end_at = (datetime.fromisoformat(end_date) + timedelta(days=1)).replace(tzinfo=_BEIJING_TZ).astimezone(timezone.utc).replace(tzinfo=None)
        query = query.filter(WebsiteLog.created_at < end_at)

    total = query.count()
    items = (
        query.order_by(desc(WebsiteLog.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
        "logs": [_website_log_to_dict(r) for r in items],
    }


@app.get("/api/admin/website-logs/timeline")
async def admin_website_log_timeline(
    task_id: str,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """按任务链路聚合日志时间线：返回该 task_id（或 trace_id）的全部日志，按时间正序。

    前端据此渲染"一条任务从创建到完成/失败"的完整事件链，
    一眼可判断是主流程挂了、封面挂了、前端展示挂了还是轮询挂了。
    """
    task_id = (task_id or "").strip()
    if not task_id:
        raise HTTPException(status_code=400, detail="task_id 不能为空")

    items = (
        db.query(WebsiteLog)
        .filter(or_(WebsiteLog.task_id == task_id, WebsiteLog.trace_id == task_id))
        .order_by(WebsiteLog.id.asc())
        .limit(500)
        .all()
    )
    return {
        "task_id": task_id,
        "total": len(items),
        "logs": [_website_log_to_dict(r) for r in items],
    }


@app.delete("/api/admin/website-logs/{log_id}")
async def admin_delete_website_log(
    log_id: int,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """管理员删除单条网站日志。"""
    row = db.query(WebsiteLog).filter(WebsiteLog.id == log_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="日志不存在")
    db.delete(row)
    db.commit()
    return {"ok": True}


@app.delete("/api/admin/website-logs")
async def admin_clear_website_logs(
    confirm: str = "",
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """管理员清空全部网站日志（需 confirm=yes 确认）。"""
    if confirm != "yes":
        raise HTTPException(status_code=400, detail="需携带 confirm=yes 以确认清空")
    deleted = db.query(WebsiteLog).delete()
    db.commit()
    return {"ok": True, "deleted": deleted}


# ---------------------------------------------------------------------------
# 公告（Announcement）与 管理后台通知红点计数
# ---------------------------------------------------------------------------

ANNOUNCEMENT_UPLOAD_DIR = WEB_DIR / "uploads" / "announcements"
ALLOWED_ANNOUNCEMENT_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
ANNOUNCEMENT_IMAGE_MAX_BYTES = 5 * 1024 * 1024  # 5MB


def _announcement_to_dict(row: "Announcement") -> Dict:
    return {
        "id": row.id,
        "title": row.title,
        "content": row.content,
        "imageUrl": row.image_url,
        "isPublished": row.is_published,
        "isPinned": bool(row.is_pinned),
        "isHomeBanner": bool(row.is_home_banner),
        "publishedBy": row.published_by,
        "category": row.category or "system",
        "createdAt": row.created_at.isoformat() + "Z" if row.created_at else None,
    }


def _get_last_seen_error_log_id(db: Session) -> int:
    """读取管理后台已查看的最新错误日志 ID；首次访问初始化为当前最大 ID，避免误报红点。"""
    row = db.query(SystemConfig).filter(SystemConfig.config_key == "last_seen_error_log_id").first()
    if not row:
        max_id = db.query(func.max(WebsiteLog.id)).scalar() or 0
        db.add(
            SystemConfig(
                config_key="last_seen_error_log_id",
                config_value=str(max_id),
                description="管理后台已查看的最新错误日志ID（用于红点计数）",
            )
        )
        db.commit()
        return int(max_id)
    try:
        return int(row.config_value)
    except (TypeError, ValueError):
        return 0


def _set_last_seen_error_log_id(db: Session, value: int) -> None:
    row = db.query(SystemConfig).filter(SystemConfig.config_key == "last_seen_error_log_id").first()
    if row:
        row.config_value = str(value)
    else:
        row = SystemConfig(
            config_key="last_seen_error_log_id",
            config_value=str(value),
            description="管理后台已查看的最新错误日志ID（用于红点计数）",
        )
        db.add(row)
    db.commit()


@app.post("/api/admin/announcements")
async def admin_create_announcement(
    content: str = Form(...),
    title: str = Form(""),
    image: UploadFile = File(None),
    category: str = Form("system"),
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """管理员发布公告（支持上传一张配图）。

    category：system=系统公告（默认） / activity=活动公告（在「活动通知」中展示）。
    """
    content = (content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="公告内容不能为空")
    if len(content) > 1000:
        raise HTTPException(status_code=400, detail="公告内容不能超过 1000 字")
    title = (title or "").strip()
    if len(title) > 255:
        raise HTTPException(status_code=400, detail="公告标题不能超过 255 字")
    if category not in ("system", "activity"):
        category = "system"

    image_url = None
    if image and image.filename and image.filename.strip():
        ext = Path(image.filename).suffix.lower()
        if ext not in ALLOWED_ANNOUNCEMENT_IMAGE_EXT:
            raise HTTPException(status_code=400, detail="不支持的图片格式，仅支持 PNG/JPG/WEBP/GIF")
        raw = await image.read()
        if len(raw) > ANNOUNCEMENT_IMAGE_MAX_BYTES:
            raise HTTPException(status_code=400, detail="图片大小不能超过 5MB")
        ANNOUNCEMENT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        filename = f"{uuid4().hex}{ext}"
        (ANNOUNCEMENT_UPLOAD_DIR / filename).write_bytes(raw)
        image_url = f"/web/uploads/announcements/{filename}"

    announcement = Announcement(
        title=title,
        content=content,
        image_url=image_url,
        published_by=admin_user.username,
        category=category,
    )
    db.add(announcement)
    db.commit()
    db.refresh(announcement)
    _invalidate_announcement_cache()
    return {"ok": True, "announcement": _announcement_to_dict(announcement)}


# 公告进程内缓存（2026-09-01）：公告低频变化，60s TTL。
# 每次后台变更都会主动清空，保证首页公告和系统消息及时更新。
_ANNOUNCEMENTS_CACHE_TTL = 60.0
_announcements_cache: dict = {}  # category(None=全部) -> (ts, data)


def _invalidate_announcement_cache() -> None:
    """后台修改公告后，立即让后续读取获取数据库中的最新内容。"""
    _announcements_cache.clear()


class AnnouncementUpdatePayload(BaseModel):
    """管理后台编辑公告的可修改字段。"""
    title: Optional[str] = None
    content: Optional[str] = None
    category: Optional[str] = None


class AnnouncementHomeBannerPayload(BaseModel):
    """首页公告条展示开关。"""
    enabled: bool


@app.get("/api/announcements")
async def list_announcements(
    category: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_admin_current_user),
):
    """已登录用户获取已发布公告（对接前端系统消息模块）。

    category 可传 'system'（系统公告）或 'activity'（活动公告），不传则返回全部。
    """
    _now = time.time()
    _cached = _announcements_cache.get(category)
    if _cached and (_now - _cached[0]) < _ANNOUNCEMENTS_CACHE_TTL:
        return _cached[1]
    query = db.query(Announcement).filter(Announcement.is_published == True)  # noqa: E712
    if category:
        query = query.filter(Announcement.category == category)
    rows = (
        query
        .order_by(desc(Announcement.is_pinned), desc(Announcement.created_at))
        .limit(50)
        .all()
    )
    _data = {"announcements": [_announcement_to_dict(r) for r in rows]}
    _announcements_cache[category] = (_now, _data)
    return _data


@app.get("/api/public/home-announcement")
async def get_public_home_announcement(db: Session = Depends(get_db)):
    """首页公开读取当前启用的公告条，无需登录。

    为避免将历史系统消息暴露给访客，只返回管理员明确设为首页展示的
    已发布系统公告；同一时刻按后台约束只会有一条。
    """
    row = (
        db.query(Announcement)
        .filter(
            Announcement.is_published == True,  # noqa: E712
            Announcement.category == "system",
            Announcement.is_home_banner == True,  # noqa: E712
        )
        .order_by(desc(Announcement.created_at), desc(Announcement.id))
        .first()
    )
    return {"announcement": _announcement_to_dict(row) if row else None}


# 首页多态公告默认配置：4 态，每态含 enabled / text / link。
# link 支持站内 URL，或 action:open-login / action:open-register（分别触发登录 / 注册弹窗）。
# 文案中 {invited_count} 为占位符，仅会员态使用，前端渲染时替换为当前用户邀请人数。
DEFAULT_HOME_ANNOUNCEMENT_STATES = {
    "enabled": True,
    "states": {
        "guest": {
            "enabled": True,
            "text": "📢 新用户注册即得 8 次免费额度 · 邀请 3 人送 7 天会员体验",
            "cta_text": "立即注册",
            "link": "action:open-register",
        },
        "logged_in_quota": {
            "enabled": True,
            "text": "📢 请邀请好友双方各得 5 次 · 累计满 3 人得 7 天会员体验",
            "cta_text": "去邀请（个人中心）",
            "link": "user_interface.html#invite",
        },
        "member": {
            "enabled": True,
            "text": "📢 会员期内无限次生成 · 本月已邀请 {invited_count} 位，满 10 人送月度会员",
            "cta_text": "去邀请（个人中心）",
            "link": "user_interface.html#invite",
        },
        "quota_exhausted": {
            "enabled": True,
            "text": "📢 额度已用完 · 开通会员 ¥9.9/月起，或邀请 3 人得 7 天会员体验",
            "cta_text": "开通会员（个人中心）",
            "link": "user_interface.html#recharge",
        },
    },
}
DEFAULT_HOME_ANNOUNCEMENT_STATES_JSON = json.dumps(DEFAULT_HOME_ANNOUNCEMENT_STATES, ensure_ascii=False)


@app.get("/api/public/home-announcement-states")
async def get_public_home_announcement_states(db: Session = Depends(get_db)):
    """首页公开读取多态公告配置（无需登录）。

    仅返回前端渲染所需的 enabled/text/link，避免泄露内部字段；
    状态机（未登录/已登录有额度/会员/额度用尽）由前端按用户态选取其一。
    """
    row = db.query(SystemConfig).filter(SystemConfig.config_key == "home_announcement_states").first()
    try:
        data = json.loads(row.config_value) if row and row.config_value else DEFAULT_HOME_ANNOUNCEMENT_STATES
    except Exception:
        data = DEFAULT_HOME_ANNOUNCEMENT_STATES
    safe = {"enabled": bool(data.get("enabled", True)), "states": {}}
    for key in ("guest", "logged_in_quota", "member", "quota_exhausted"):
        s = ((data.get("states") or {}).get(key)) or {}
        safe["states"][key] = {
            "enabled": bool(s.get("enabled", True)),
            "text": str(s.get("text", "") or ""),
            "cta_text": str(s.get("cta_text", "") or ""),
            "link": str(s.get("link", "") or ""),
        }
    return {"config": safe}


def _create_notification(
    db: Session,
    user_id: str,
    category: str,
    title: str,
    content: str,
    target_url: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """写入一条用户通知（互动通知 / 系统通知）。best-effort：异常仅记录不中断主流程。"""
    try:
        db.add(
            Notification(
                user_id=user_id,
                category=category,
                title=title,
                content=content,
                target_url=target_url,
                is_read=False,
                created_at=datetime.utcnow(),
                extra=extra or {},
                source_type=category,
                source_id=(extra or {}).get("task_id") or "",
            )
        )
        db.commit()
    except Exception as e:  # noqa: BLE001
        db.rollback()
        log(f"写入通知失败(user_id={user_id}, category={category}): {e}", "ERROR")


def _notify_interaction(
    db: Session,
    recipient_id: str,
    actor_id: str,
    action: str,
    task_id: str,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """生成一条「互动通知」：当某用户的案例/评论被点赞、评论、回复时通知本人。

    recipient_id 为目标接收者（被点赞/评论者），actor_id 为操作发起者。
    自己操作自己不通知；recipient 缺失也不通知。
    """
    if not recipient_id or recipient_id == actor_id:
        return
    actor = db.query(User).filter(User.user_id == actor_id).first()
    actor_name = actor.username if actor else "有人"
    teaching = db.query(Teaching).filter(Teaching.task_id == task_id).first()
    title = teaching.title if teaching and teaching.title else "你的案例"
    _create_notification(
        db,
        recipient_id,
        "interaction",
        f"{actor_name}{action}",
        f"{actor_name}{action}《{title}》",
        target_url=f"video.html?task_id={task_id}",
        extra={"actor_id": actor_id, "actor_name": actor_name, "task_id": task_id, **(extra or {})},
    )


@app.get("/api/notifications")
async def list_user_notifications(
    db: Session = Depends(get_db),
    user: User = Depends(get_admin_current_user),
):
    """获取当前用户的互动通知与系统通知（含未读计数）。"""
    rows = (
        db.query(Notification)
        .filter(Notification.user_id == user.user_id)
        .order_by(desc(Notification.created_at))
        .all()
    )

    def _ser(n: "Notification") -> Dict[str, Any]:
        return {
            "id": n.id,
            "category": n.category,
            "title": n.title,
            "content": n.content,
            "targetUrl": n.target_url,
            "isRead": bool(n.is_read),
            "createdAt": n.created_at.isoformat() + "Z" if n.created_at else None,
            "extra": n.extra or {},
        }

    interaction = [_ser(n) for n in rows if n.category == "interaction"]
    system = [_ser(n) for n in rows if n.category == "system"]
    unread_interaction = sum(1 for n in interaction if not n["isRead"])
    unread_system = sum(1 for n in system if not n["isRead"])
    return {
        "interaction": interaction,
        "system": system,
        "unread": {
            "interaction": unread_interaction,
            "system": unread_system,
            "total": unread_interaction + unread_system,
        },
    }


@app.post("/api/notifications/{notification_id}/read")
async def mark_notification_read(
    notification_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_admin_current_user),
):
    """标记单条通知为已读（仅限本人）。"""
    n = (
        db.query(Notification)
        .filter(Notification.id == notification_id, Notification.user_id == user.user_id)
        .first()
    )
    if not n:
        raise HTTPException(status_code=404, detail="通知不存在")
    n.is_read = True
    db.commit()
    return {"ok": True}


@app.post("/api/notifications/read-all")
async def mark_all_notifications_read(
    category: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_admin_current_user),
):
    """批量标记已读。category 可传 interaction / system，不传则全部。"""
    q = db.query(Notification).filter(
        Notification.user_id == user.user_id, Notification.is_read == False  # noqa: E712
    )
    if category:
        q = q.filter(Notification.category == category)
    q.update({Notification.is_read: True})
    db.commit()
    return {"ok": True}


@app.get("/api/admin/announcements/all")
async def admin_list_all_announcements(
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    """管理员获取全部公告（用于管理公告模块：置顶 / 删除）。"""
    rows = (
        db.query(Announcement)
        .order_by(desc(Announcement.is_pinned), desc(Announcement.created_at))
        .all()
    )
    return {"announcements": [_announcement_to_dict(r) for r in rows]}


@app.patch("/api/admin/announcements/{announcement_id:int}")
async def admin_update_announcement(
    announcement_id: int,
    payload: AnnouncementUpdatePayload,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    """管理员编辑公告文本与分类；首页公告只能保持为系统通知。"""
    row = db.query(Announcement).filter(Announcement.id == announcement_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="公告不存在")

    if payload.title is not None:
        row.title = str(payload.title).strip()[:255]
    if payload.content is not None:
        content = str(payload.content).strip()
        if not content:
            raise HTTPException(status_code=400, detail="公告内容不能为空")
        if len(content) > 1000:
            raise HTTPException(status_code=400, detail="公告内容不能超过 1000 字")
        row.content = content
    if payload.category is not None:
        category = str(payload.category).strip()
        if category not in ("system", "activity"):
            raise HTTPException(status_code=400, detail="公告类型不正确")
        if row.is_home_banner and category != "system":
            raise HTTPException(status_code=400, detail="首页公告只能设为系统通知，请先撤下首页")
        row.category = category

    db.add(row)
    db.commit()
    db.refresh(row)
    _invalidate_announcement_cache()
    return {"ok": True, "announcement": _announcement_to_dict(row)}


@app.patch("/api/admin/announcements/{announcement_id}/home-banner")
async def admin_set_announcement_home_banner(
    announcement_id: int,
    payload: AnnouncementHomeBannerPayload,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    """设置或撤下首页公告条；开启时自动撤下其他首页公告。"""
    row = db.query(Announcement).filter(Announcement.id == announcement_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="公告不存在")
    if payload.enabled and (not row.is_published or row.category != "system"):
        raise HTTPException(status_code=400, detail="仅已发布的系统通知可设为首页公告")

    if payload.enabled:
        (
            db.query(Announcement)
            .filter(Announcement.id != announcement_id, Announcement.is_home_banner == True)  # noqa: E712
            .update({Announcement.is_home_banner: False}, synchronize_session=False)
        )
    row.is_home_banner = bool(payload.enabled)
    db.add(row)
    db.commit()
    db.refresh(row)
    _invalidate_announcement_cache()
    return {"ok": True, "announcement": _announcement_to_dict(row)}


@app.patch("/api/admin/announcements/{announcement_id}/pin")
async def admin_pin_announcement(
    announcement_id: int,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    """管理员置顶 / 取消置顶公告（切换）。"""
    row = db.query(Announcement).filter(Announcement.id == announcement_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="公告不存在")
    row.is_pinned = not bool(row.is_pinned)
    db.add(row)
    db.commit()
    db.refresh(row)
    _invalidate_announcement_cache()
    return {"ok": True, "announcement": _announcement_to_dict(row)}


@app.delete("/api/admin/announcements/{announcement_id}")
async def admin_delete_announcement(
    announcement_id: int,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    """管理员删除公告（同时尝试删除已上传的配图文件）。"""
    row = db.query(Announcement).filter(Announcement.id == announcement_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="公告不存在")
    if row.image_url and row.image_url.startswith("/web/uploads/announcements/"):
        try:
            filename = row.image_url.rsplit("/", 1)[-1]
            (ANNOUNCEMENT_UPLOAD_DIR / filename).unlink(missing_ok=True)
        except Exception:
            pass
    db.delete(row)
    db.commit()
    _invalidate_announcement_cache()
    return {"ok": True, "id": announcement_id}


@app.get("/api/admin/notifications/counts")
async def notification_counts(
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    """管理后台左侧导航栏红点计数：未处理订单 / 未处理反馈 / 新增错误日志。"""
    new_orders = (
        db.query(RechargeRequest)
        .filter(RechargeRequest.status == "pending")
        .count()
    )
    new_feedbacks = (
        db.query(UserFeedback)
        .filter(UserFeedback.status.in_(["new", "in_progress"]))
        .count()
    )
    last_seen = _get_last_seen_error_log_id(db)
    new_error_logs = (
        db.query(WebsiteLog)
        .filter(WebsiteLog.level == "ERROR", WebsiteLog.id > last_seen)
        .count()
    )
    return {
        "new_orders": int(new_orders),
        "new_feedbacks": int(new_feedbacks),
        "new_error_logs": int(new_error_logs),
    }


@app.post("/api/admin/website-logs/acknowledge")
async def ack_website_logs(
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    """管理后台查看网站日志后，清零“新增错误日志”红点计数。"""
    max_id = db.query(func.max(WebsiteLog.id)).scalar() or 0
    _set_last_seen_error_log_id(db, int(max_id))
    return {"ok": True, "last_seen_error_log_id": int(max_id)}


@app.post("/api/logs/client")
async def client_error_report(
    payload: ClientErrorReport,
    request: Request,
    db: Session = Depends(get_db),
):
    """前端上报页面运行期报错（window.onerror / unhandledrejection / fetch 非 2xx 等）。"""
    message = (payload.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message 不能为空")

    auth = request.headers.get("authorization", "")
    token = auth[7:].strip() if auth.startswith("Bearer ") else None
    user_id = verify_token(token) if token else None

    record_website_log(
        level=payload.level or "ERROR",
        category=payload.category or "client_page",
        message=message,
        user_id=user_id,
        task_id=payload.task_id or None,
        trace_id=payload.trace_id or payload.task_id or None,
        event=payload.event or None,
        stage=payload.stage or None,
        error_type=payload.error_type or None,
        page_url=payload.page_url,
        page_title=payload.page_title,
        device=payload.device or request.headers.get("user-agent", ""),
        error_code=payload.error_code,
        stack_trace=payload.stack_trace,
        context=payload.context,
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return {"ok": True}


@app.get("/api/health")
async def health_check():
    """健康检查端点"""
    # 尝试读取版本信息
    version_info = {}
    try:
        # 尝试从 version.py 导入版本信息
        try:
            from version import VERSION, COMMIT, BRANCH, BUILD_DATE
            version_info = {
                "version": VERSION,
                "commit": COMMIT,
                "branch": BRANCH,
                "build_date": BUILD_DATE
            }
        except ImportError:
            # 如果 version.py 不存在，尝试从 .version 文件读取
            version_file = Path(__file__).parent.parent / ".version"
            if version_file.exists():
                with open(version_file, 'r') as f:
                    for line in f:
                        if '=' in line:
                            key, value = line.strip().split('=', 1)
                            version_info[key.lower()] = value
    except Exception:
        pass  # 版本信息获取失败不影响健康检查
    
    return {
        "status": "ok",
        "message": "XSYY Backend is running",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "version": version_info.get("version", "unknown"),
        "commit": version_info.get("commit", "unknown"),
        "branch": version_info.get("branch", "unknown")
    }


@app.get("/metrics")
async def metrics():
    """Prometheus 指标端点"""
    # 更新数据库连接池指标
    update_db_pool_metrics(engine)
    # 更新缓存大小指标
    html_cache_size.set(len(_html_cache))
    # 更新运行中的任务数
    running_count = sum(1 for t in tasks.values() if t.status == "running")
    tasks_running.set(running_count)
    # 返回 Prometheus 指标
    return get_metrics_response()


@app.get("/api/metrics/summary")
async def metrics_summary():
    """性能监控摘要（JSON 格式，便于前端展示）"""
    # 更新prometheus指标
    update_db_pool_metrics(engine)
    update_memory_usage()

    cache_size = len(_html_cache)
    html_cache_size.set(cache_size)

    # 单次遍历统计所有任务状态，避免多次循环
    running = pending = completed = failed = 0
    for task in tasks.values():
        status = task.status
        if status == "running":
            running += 1
        elif status == "pending":
            pending += 1
        elif status == "completed":
            completed += 1
        elif status == "failed":
            failed += 1
    tasks_running.set(running)

    # 数据库连接池信息
    try:
        pool = engine.pool
        db_status = {
            "pool_size": pool.size(),
            "checked_in": pool.checkedin(),
            "checked_out": pool.checkedout(),
            "overflow": pool.overflow(),
            "total_connections": pool.size() + pool.overflow()
        }
    except Exception as e:
        db_status = {"error": f"无法获取连接池状态: {str(e)}"}

    # 使用to_thread把psutil同步操作丢到线程池，不阻塞事件循环
    def get_memory_info():
        process = psutil.Process(os.getpid())
        mem = process.memory_info()
        return {
            "rss_mb": round(mem.rss / 1024 / 1024, 2),
            "vms_mb": round(mem.vms / 1024 / 1024, 2),
            "percent": round(process.memory_percent(), 2)
        }

    try:
        memory_info = await asyncio.to_thread(get_memory_info)
    except NameError:
        memory_info = {"error": "psutil 未安装"}
    except Exception as e:
        memory_info = {"error": f"无法获取内存信息: {str(e)}"}

    task_stats = {
        "total": len(tasks),
        "running": running,
        "pending": pending,
        "completed": completed,
        "failed": failed
    }

    # =====================重要提醒=====================
    # 【建议直接删除下方整块日志代码！】
    # 监控接口会被频繁轮询，不适合打印密钥信息，移到 startup 事件
    # ==================================================
    """
    if is_test_mode():
        log("注意: 测试模式下不会调用真实 API，不会保存文件", "TEST")
    else:
        kimi_key = os.getenv("KIMI_API_KEY")
        if kimi_key:
            mask = "*" * 10 + kimi_key[-4:] if len(kimi_key) > 4 else "****"
            log(f"Kimi API 密钥: 已配置 ({mask})")
        else:
            log("Kimi API 密钥: 未配置（将在首次调用时检查）", "WARN")

        gptsapi_key = os.getenv("GPTsAPI_KEY")
        if gptsapi_key:
            mask = "*" * 10 + gptsapi_key[-4:] if len(gptsapi_key) > 4 else "****"
            log(f"GPTsAPI 密钥: 已配置 ({mask})")
        else:
            log("GPTsAPI 密钥: 未配置（预览图功能将不可用）", "WARN")
    log("=" * 60)
    """

    return {
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "database": db_status,
        "memory": memory_info,
        "cache": {
            "html_cache_size": cache_size,
            "html_cache_max_size": _cache_max_size
        },
        "tasks": task_stats
    }


# 关闭逻辑已迁移至上方 lifespan()（取代已废弃的 @app.on_event）


class TaskResponse(BaseModel):
    task_id: str
    status: str
    progress: int = 0  # 进度 0-100
    video_url: Optional[str] = None
    preview_image: Optional[str] = None
    metadata: Dict = {}
    error: Optional[str] = None
    trace_id: Optional[str] = None  # 统一链路 ID（与 task_id 1:1）


class AnimationGenerationTestRequest(BaseModel):
    problem: str
    difficulty: str = "medium"
    backend: str = "mock"
    extra_context: Optional[Dict] = None


@app.post("/api/test/animation-generation")
async def test_animation_generation_api(payload: AnimationGenerationTestRequest):
    """测试接口：接入缓存+Gemini 的优化主流程，用于回归测试与效果验证。"""
    problem = (payload.problem or "").strip()
    if not problem:
        raise HTTPException(status_code=400, detail="problem 不能为空")

    try:
        result = get_optimized_generation_service().generate_animation_teaching(
            problem=problem,
            difficulty=(payload.difficulty or "medium").strip(),
            backend=(payload.backend or "mock").strip(),
            extra_context=payload.extra_context or {},
        )
    except Exception as exc:
        log(f"测试接口调用失败: {exc}", "ERROR")
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "success": bool(result.get("success", False)),
        "status_code": int(result.get("status_code", 200)),
        "from_cache": bool(result.get("from_cache", False)),
        "backend": result.get("backend", "unknown"),
        "prompt_hash": result.get("prompt_hash", ""),
        "output": result.get("teaching_content", ""),
        "inference_hints": result.get("inference_hints", {}),
    }


# ===== 提交幂等键（request_id）防重 =====
# 场景：创建/上传请求已到达后端并成功创建任务，但响应在回程丢失（弱网、网关闪断），
# 前端报"网络错误"、用户重试 → 同一次提交被创建成两份任务。
# 方案：前端每次提交生成唯一 request_id 并在重试时复用；后端 TTL 内同 request_id
# 且任务仍进行中 → 直接返回既有任务，不再新建。内存注册表做快速路径，
# task_status.metadata_json 落库做跨 worker 兜底（nginx 轮询可能把重试分到其他进程）。
_IDEMPOTENCY_TTL_SECONDS = 2 * 3600
_idempotency_registry: Dict[str, Dict] = {}


def _prune_idempotency_registry() -> None:
    now = time.time()
    for key in [k for k, v in _idempotency_registry.items()
                if now - v.get("created_at", 0) > _IDEMPOTENCY_TTL_SECONDS]:
        _idempotency_registry.pop(key, None)


def _find_active_task_by_request_id(request_id: Optional[str], user_id: Optional[str]) -> Optional[Task]:
    """按幂等键查找仍进行中的任务（内存优先，task_status 表跨 worker 兜底）。

    仅返回 pending/running 的任务；映射到的任务已终态（completed/failed）则视为
    键失效并清除，允许用户重新提交。
    """
    if not request_id:
        return None
    _prune_idempotency_registry()
    entry = _idempotency_registry.get(request_id)
    if entry:
        if user_id and entry.get("user_id") and entry.get("user_id") != user_id:
            return None
        task = tasks.get(entry.get("task_id")) or _load_task_state(entry.get("task_id"))
        if task and task.status in ("pending", "running"):
            return task
        _idempotency_registry.pop(request_id, None)

    if not user_id:
        return None
    try:
        db = SessionLocal()
        try:
            since = datetime.utcnow() - timedelta(seconds=_IDEMPOTENCY_TTL_SECONDS)
            rows = db.query(TaskStatus).filter(
                TaskStatus.user_id == user_id,
                TaskStatus.created_at >= since,
                TaskStatus.status.in_(["pending", "running"]),
            ).order_by(TaskStatus.created_at.desc()).limit(100).all()
        finally:
            db.close()
    except Exception as e:
        log(f"幂等键查库失败: {e}", "WARN")
        return None
    for row in rows:
        meta = row.metadata_json or {}
        if isinstance(meta, dict) and meta.get("request_id") == request_id:
            return Task(
                task_id=row.task_id,
                status=row.status,
                progress=row.progress,
                metadata=meta,
                user_id=row.user_id,
                topic_id=row.topic_id,
                prompt=row.prompt or "",
                input_file=row.input_file,
            )
    return None


def _register_idempotency_key(request_id: Optional[str], task: Task) -> None:
    if not request_id:
        return
    _prune_idempotency_registry()
    _idempotency_registry[request_id] = {
        "task_id": task.task_id,
        "user_id": task.user_id,
        "created_at": time.time(),
    }


@app.post("/api/tasks", response_model=TaskResponse)
async def create_task(
    background_tasks: BackgroundTasks,
    request: Request,
    file: UploadFile = File(None),
    prompt: str = Form(""),
    topic_id: str = Form(None),  # 新增：可选的专题ID
    page_url: str = Form(None),  # 触发页面 URL（用于网站日志回溯）
    page_title: str = Form(None),  # 触发页面标题
    request_id: str = Form(None),  # 提交幂等键：前端重试时复用，防止响应丢失后重复创建
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    task_id = str(uuid4())

    # 先解析用户 ID（测试模式和生产模式都需要），供任务上下文/链路日志关联
    user_id = None
    if credentials and credentials.credentials:
        user_id = verify_token(credentials.credentials)

    _capture_task_context(task_id, request, prompt=prompt, page_url=page_url, page_title=page_title, user_id=user_id)
    log("=" * 60)
    log(f"收到新任务请求，任务ID: {task_id}")
    log(f"提示词: {prompt[:100]}..." if len(prompt) > 100 else f"提示词: {prompt}")
    log(f"文件名: {file.filename if file and file.filename else '无文件'}")
    log(f"专题ID: {topic_id if topic_id else '未指定（将使用默认专题）'}")
    
    # 封禁检查：被封禁用户禁止创建教学内容（动画）
    if user_id:
        _ban_db = next(get_db())
        try:
            if _is_user_banned(_ban_db, user_id):
                log(f"用户 {user_id} 处于封禁状态，拒绝生成任务", "BAN")
                raise HTTPException(status_code=403, detail="账号已被封禁，暂时无法使用内容生成功能")
        finally:
            _ban_db.close()

    # 提交幂等：同 request_id 且任务仍进行中 → 直接返回既有任务（响应丢失后重试的兜底，
    # 优先级高于同题复用，因为 request_id 精确对应"这一次提交动作"）
    existing_by_request = _find_active_task_by_request_id(request_id, user_id)
    if existing_by_request:
        log(f"幂等键命中，返回既有任务 {existing_by_request.task_id}（status={existing_by_request.status}）", "CACHE")
        return TaskResponse(
            task_id=existing_by_request.task_id,
            status=existing_by_request.status,
            progress=existing_by_request.progress,
            metadata={
                "is_reused": True,
                "reuse_hint": "该题目正在生成中，已为你关联进行中的任务，请勿重复提交",
            },
        )

    # 同题复用：纯文本题目（无上传文件）优先尝试直接复用已生成结果。
    has_upload_file = bool(file and file.filename and file.filename.strip())
    prompt_text = (prompt or "").strip()
    if prompt_text and not has_upload_file:
        prompt_hash, source_task_id = _try_get_reused_task_id(prompt_text)
        db = next(get_db())
        try:
            if source_task_id:
                reused_response, reuse_source = _materialize_reused_task_response(
                    db=db,
                    prompt_hash=prompt_hash,
                    source_task_id=source_task_id,
                    prompt_text=prompt_text,
                )
                if reused_response:
                    log(
                        f"同题复用命中（{reuse_source}）：prompt_hash={prompt_hash}, source_task_id={source_task_id}",
                        "CACHE",
                    )
                    # 添加复用提示信息，供前端显示弹窗
                    if reused_response.metadata:
                        reused_response.metadata["reuse_hint"] = "已有该题的教学内容，将直接跳转，不消耗生成次数"
                    else:
                        reused_response.metadata = {"reuse_hint": "已有该题的教学内容，将直接跳转，不消耗生成次数"}
                    return reused_response

                # 命中映射但实际不可复用，清理脏映射。
                get_task_reuse_cache().delete(prompt_hash)
            else:
                semantic_task_id, semantic_similarity = await _find_semantic_reused_task_id(db, prompt_text)
                if semantic_task_id:
                    semantic_prompt_hash = _set_task_reuse_mapping(prompt_text, semantic_task_id)
                    reused_response, reuse_source = _materialize_reused_task_response(
                        db=db,
                        prompt_hash=semantic_prompt_hash or prompt_hash,
                        source_task_id=semantic_task_id,
                        prompt_text=prompt_text,
                    )
                    if reused_response:
                        log(
                            f"同题复用命中（{reuse_source}，相似度={semantic_similarity:.3f}）：prompt_hash={semantic_prompt_hash or prompt_hash}, source_task_id={semantic_task_id}",
                            "CACHE",
                        )
                        # 添加复用提示信息，供前端显示弹窗
                        if reused_response.metadata:
                            reused_response.metadata["reuse_hint"] = "已有该题的教学内容，将直接跳转，不消耗生成次数"
                        else:
                            reused_response.metadata = {"reuse_hint": "已有该题的教学内容，将直接跳转，不消耗生成次数"}
                        return reused_response
        except Exception as e:
            log(f"同题复用检查失败，继续走正常生成流程: {e}", "WARN")
        finally:
            db.close()

    # 进行中同题任务防重（2026-09-11）：同一用户提交完全相同的题目文字、且该题已有
    # pending/running 任务时，直接返回既有任务。修复场景：前端跳转异常后用户重试，
    # 导致同题创建两份动画（双倍算力 + 成果库重复卡片）。
    if prompt_text and user_id:
        dup_task = _find_active_duplicate_task(user_id, prompt_text)
        if dup_task:
            log(f"命中进行中同题任务，返回既有任务 {dup_task.task_id}（status={dup_task.status}）", "CACHE")
            return TaskResponse(
                task_id=dup_task.task_id,
                status=dup_task.status,
                progress=dup_task.progress,
                metadata={
                    "is_reused": True,
                    "reuse_hint": "该题目正在生成中，已为你关联进行中的任务，请勿重复提交",
                },
            )

    # 额度由前端 /api/v2/generation/consume 统一扣减（v2 邀请额度系统），此处不再重复检查旧版每日次数限制

    # 如果没有指定专题，获取或创建默认专题
    if not topic_id and user_id:
        db = next(get_db())
        try:
            default_topic = db.query(Topic).filter(
                Topic.user_id == user_id,
                Topic.is_default == True
            ).first()
            
            if not default_topic:
                # 创建默认专题
                default_topic_id = str(uuid4())
                default_topic = Topic(
                    topic_id=default_topic_id,
                    user_id=user_id,
                    name="默认专题",
                    is_default=True
                )
                db.add(default_topic)
                db.commit()
                topic_id = default_topic_id
                log(f"为用户 {user_id} 创建默认专题: {topic_id}", "INFO")
            else:
                topic_id = default_topic.topic_id
                log(f"使用用户 {user_id} 的默认专题: {topic_id}", "INFO")
        except Exception as e:
            log(f"获取或创建默认专题失败: {e}", "WARN")
            # 如果失败，topic_id 保持为 None，任务仍然可以创建
        finally:
            db.close()
    
    # 测试模式：不创建文件夹，不保存文件
    if is_test_mode():
        log(f"测试模式：任务 {task_id} 不创建文件夹，不保存文件", "TEST")
        task = Task(
            task_id=task_id,
            input_file=None,  # 测试模式下不保存文件
            prompt=prompt,
            user_id=user_id,  # 测试模式下也设置 user_id
            topic_id=topic_id,
        )
        tasks[task_id] = task
        if request_id:
            task.metadata = dict(task.metadata or {})
            task.metadata["request_id"] = request_id
            _register_idempotency_key(request_id, task)
        _persist_task_state(task)
        background_tasks.add_task(run_pipeline, task_id)
        log(f"任务 {task_id} 已加入后台任务队列", "TASK")
        return TaskResponse(task_id=task_id, status=task.status, progress=task.progress)
    
    # 生产模式：如果用户上传了文件，先保存到临时位置
    # 等 pipeline 成功生成 HTML 后再移动到最终位置
    input_file_path = None
    if file and file.filename and file.filename.strip():
        # 创建临时目录保存文件（如果 pipeline 失败，这些文件会被清理）
        temp_dir = DATA_DIR / f"temp_{task_id}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        file_path = temp_dir / file.filename
        log(f"临时保存上传文件: {file.filename} 到 {file_path}")
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            log(f"文件已临时保存: {file_path}，大小: {file_path.stat().st_size} 字节")
            input_file_path = str(file_path)
    
    task = Task(
        task_id=task_id,
        input_file=input_file_path,
        prompt=prompt,
        user_id=user_id,
        topic_id=topic_id,
    )
    tasks[task_id] = task
    if request_id:
        task.metadata = dict(task.metadata or {})
        task.metadata["request_id"] = request_id
        _register_idempotency_key(request_id, task)
    _persist_task_state(task)

    # 更新监控指标（注意：这里先不增加 running，等任务真正开始运行时再增加）
    tasks_total.labels(status="pending").inc()

    background_tasks.add_task(run_pipeline, task_id)
    log(f"任务 {task_id} 已加入后台任务队列，开始处理", "TASK")
    return TaskResponse(task_id=task_id, status=task.status)


@app.post("/api/upload-and-parse")
async def upload_and_parse_file(
    background_tasks: BackgroundTasks,
    request: Request,
    file: UploadFile = File(...),
    type: str = Form("document"),
    topic_id: str = Form(None),
    page_url: str = Form(None),
    page_title: str = Form(None),
    request_id: str = Form(None),  # 提交幂等键：前端重试时复用，防止响应丢失后重复创建
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    """保存上传文件并立即创建任务，解析与生成在后台执行。"""
    if not file or not file.filename:
        raise HTTPException(status_code=400, detail="请先选择一个文件")

    user_id = None
    if credentials and credentials.credentials:
        user_id = verify_token(credentials.credentials)

    # 提交幂等：同 request_id 且任务仍进行中 → 直接返回既有任务，不再保存文件/建任务。
    # 修复场景：上传请求已到达后端（任务已在跑），响应在回程丢失，前端报"网络错误"，
    # 用户重试 → 之前会重复创建同题任务。
    existing_by_request = _find_active_task_by_request_id(request_id, user_id)
    if existing_by_request:
        log(f"上传幂等键命中，返回既有任务 {existing_by_request.task_id}（request_id={str(request_id)[:8]}...）", "CACHE")
        return {
            "success": True,
            "message": "检测到本次提交已开始生成，已为你返回原任务",
            "processedCount": 1,
            "tasks": [existing_by_request.task_id],
            "task_id": existing_by_request.task_id,
            "reused": True,
            "reuse_hint": "该题目正在生成中，已为你关联进行中的任务，请勿重复提交",
        }

    safe_filename = Path(file.filename).name
    file_suffix = Path(safe_filename).suffix.lower()
    allowed_suffixes = {".docx", ".doc", ".pdf", ".txt", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
    if file_suffix not in allowed_suffixes:
        raise HTTPException(status_code=400, detail="仅支持 .docx、.doc、.pdf、.txt 文件或图片文件")

    resolved_topic_id = topic_id
    if not resolved_topic_id and user_id:
        default_topic = db.query(Topic).filter(
            Topic.user_id == user_id,
            Topic.is_default == True,
        ).first()
        if not default_topic:
            resolved_topic_id = str(uuid4())
            db.add(Topic(
                topic_id=resolved_topic_id,
                user_id=user_id,
                name="默认专题",
                is_default=True,
            ))
            db.commit()
        else:
            resolved_topic_id = default_topic.topic_id

    task_id = str(uuid4())
    _capture_task_context(task_id, request, page_url=page_url, page_title=page_title, user_id=user_id)
    input_file_path = None
    if not is_test_mode():
        temp_dir = DATA_DIR / f"temp_upload_{task_id}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        file_path = temp_dir / safe_filename
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        input_file_path = str(file_path)

    task = Task(
        task_id=task_id,
        status="pending",
        progress=0,
        input_file=input_file_path,
        user_id=user_id,
        topic_id=resolved_topic_id,
        metadata={
            "source_file_name": safe_filename,
            "source_type": type,
            "source_upload_type": file_suffix,
            "upload_mode": "upload-and-parse",
            "request_id": request_id or "",
        },
    )
    tasks[task_id] = task
    if request_id:
        _register_idempotency_key(request_id, task)
    _persist_task_state(task)
    tasks_total.labels(status="pending").inc()
    background_tasks.add_task(_run_upload_and_parse_pipeline, task_id)
    log(f"上传文件已保存并创建后台解析任务: task_id={task_id}", "TASK")

    return {
        "success": True,
        "message": "文件已接收，正在为您生成...",
        "processedCount": 1,
        "tasks": [task_id],
        "task_id": task_id,
    }


@app.get("/api/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: str):
    task = tasks.get(task_id)
    if not task:
        # 1) task_status 表兜底：多 worker 部署下，任务可能在【其他 worker 进程】的内存中，
        #    创建/进度更新时已把状态落库（见 _persist_task_state），这里从数据库回填，
        #    避免前端把仍在生成的任务误判为 not_found。
        task = _load_task_state(task_id)
        if task:
            return TaskResponse(
                task_id=task.task_id,
                status=task.status,
                progress=task.progress,
                video_url=task.video_url,
                preview_image=task.preview_image,
                metadata=task.metadata,
                error=task.error,
                trace_id=task.task_id,
            )

        # 2) Teaching 表兜底：进程重启后内存态 tasks 会丢失，但已完成任务会持久化到 Teaching 表中。
        try:
            db = SessionLocal()
            try:
                teaching = db.query(Teaching).filter(Teaching.task_id == task_id).first()
            finally:
                db.close()
        except Exception as exc:
            log(f"查询持久化任务状态失败: {task_id}, {exc}", "WARN")
            teaching = None

        if teaching:
            metadata = {
                "task_id": teaching.task_id,
                "question": teaching.question,
                "prompt": teaching.prompt,
                "title": teaching.title,
                "is_math_problem": teaching.is_math_problem,
                "has_pic": teaching.has_pic,
                "tags": {
                    "main_tag": teaching.main_tag,
                    "sub_tags": teaching.sub_tags or [],
                } if teaching.main_tag else None,
            }
            return TaskResponse(
                task_id=task_id,
                status="completed",
                progress=100,
                video_url="",
                preview_image=get_preview_image_name(DATA_DIR / task_id, teaching.preview_image),
                metadata=metadata,
                error=None,
                trace_id=task_id,
            )
        
        return TaskResponse(task_id=task_id, status="not_found", progress=0, trace_id=task_id)

    return TaskResponse(
        task_id=task.task_id,
        status=task.status,
        progress=task.progress,
        video_url=task.video_url,
        preview_image=task.preview_image,
        metadata=task.metadata,
        error=task.error,
        trace_id=task.task_id,
    )


class Feedback(BaseModel):
    task_id: str
    understood: bool
    comments: Optional[str] = ""


@app.post("/api/feedback")
async def submit_feedback(feedback: Feedback):
    task = tasks.get(feedback.task_id)
    if task:
        task.metadata.setdefault("feedback", []).append(feedback.dict())
    return {"ok": True}


class FeedbackSubmit(BaseModel):
    description: str
    images: Optional[List[str]] = []
    page_url: Optional[str] = ""
    page_title: Optional[str] = ""


def _feedback_to_dict(fb: UserFeedback) -> dict:
    """将反馈记录序列化为管理后台前端所需的字段格式。"""
    return {
        "id": fb.id,
        "userId": fb.user_id,
        "userName": fb.user_name,
        "description": fb.description,
        "images": fb.images or [],
        "createdAt": fb.created_at.isoformat() + "Z" if fb.created_at else None,
        "status": fb.status or "new",
        "pageUrl": fb.page_url,
        "pageTitle": fb.page_title,
        "handledAt": fb.handled_at.isoformat() + "Z" if fb.handled_at else None,
        "handledBy": fb.handled_by,
        "adminNote": fb.admin_note or "",
    }


@app.post("/api/feedback/submit")
async def submit_user_feedback(
    payload: FeedbackSubmit,
    user: User = Depends(get_admin_current_user),
    db: Session = Depends(get_db),
):
    """用户提交问题反馈（写入数据库）。"""
    description = (payload.description or "").strip()
    if not description:
        raise HTTPException(status_code=400, detail="反馈内容不能为空")
    if len(description) > 2000:
        raise HTTPException(status_code=400, detail="反馈内容过长")

    images = [img for img in (payload.images or []) if isinstance(img, str)][:5]
    fb = UserFeedback(
        user_id=user.user_id,
        user_name=user.username,
        description=description,
        images=images,
        page_url=(payload.page_url or "")[:500],
        page_title=(payload.page_title or "")[:255],
        status="new",
    )
    db.add(fb)
    db.commit()
    db.refresh(fb)
    log(f"用户反馈已提交: id={fb.id}, user={user.user_id}", "INFO")
    return {"ok": True, "id": fb.id}


@app.get("/api/feedback/mine")
async def get_my_feedbacks(
    user: User = Depends(get_admin_current_user),
    db: Session = Depends(get_db),
):
    """获取当前用户提交的问题反馈及处理进度。"""
    items = (
        db.query(UserFeedback)
        .filter(UserFeedback.user_id == user.user_id)
        .order_by(desc(UserFeedback.created_at))
        .all()
    )
    return {"feedbacks": [_feedback_to_dict(fb) for fb in items]}


@app.get("/api/admin/feedbacks")
async def admin_get_feedbacks(
    page: int = 1,
    page_size: int = 20,
    status: Optional[str] = None,
    search: Optional[str] = None,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """管理员获取用户反馈列表（支持分页、状态筛选、关键词搜索）。"""
    page = max(1, page)
    page_size = min(max(1, page_size), 500)

    query = db.query(UserFeedback).filter(UserFeedback.status != "deleted")
    if status:
        query = query.filter(UserFeedback.status == status)
    if search and search.strip():
        keyword = f"%{search.strip()}%"
        query = query.filter(or_(
            UserFeedback.description.like(keyword),
            UserFeedback.user_name.like(keyword),
            UserFeedback.user_id.like(keyword),
            UserFeedback.page_url.like(keyword),
            UserFeedback.page_title.like(keyword),
        ))

    total = query.count()
    items = (
        query.order_by(desc(UserFeedback.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
        "feedbacks": [_feedback_to_dict(fb) for fb in items],
    }


class FeedbackStatusUpdate(BaseModel):
    status: Optional[str] = None
    admin_note: Optional[str] = None


@app.put("/api/admin/feedbacks/{feedback_id}")
async def admin_update_feedback_status(
    feedback_id: int,
    payload: FeedbackStatusUpdate,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """管理员更新反馈处理状态。"""
    fb = db.query(UserFeedback).filter(UserFeedback.id == feedback_id).first()
    if not fb:
        raise HTTPException(status_code=404, detail="反馈不存在")

    new_status = (payload.status or "").strip() if payload.status else None
    if new_status is not None and new_status not in ("new", "in_progress", "resolved", "ignored"):
        raise HTTPException(status_code=400, detail="无效的反馈状态")

    if new_status is not None:
        fb.status = new_status
    if payload.admin_note is not None:
        fb.admin_note = payload.admin_note
    if new_status is not None or payload.admin_note is not None:
        fb.handled_by = admin_user.username
        fb.handled_at = datetime.utcnow()
    db.commit()
    db.refresh(fb)
    log(f"管理员更新反馈: id={feedback_id}, status={new_status}, by={admin_user.username}", "INFO")
    return {"ok": True, "feedback": _feedback_to_dict(fb)}


@app.delete("/api/admin/feedbacks/{feedback_id}")
async def admin_delete_feedback(
    feedback_id: int,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """管理员删除反馈。"""
    fb = db.query(UserFeedback).filter(UserFeedback.id == feedback_id).first()
    if not fb:
        raise HTTPException(status_code=404, detail="反馈不存在")

    # 软删除：记录保留在数据库中，用户中心仍会显示为“已提交”
    fb.status = "deleted"
    fb.handled_by = admin_user.username
    fb.handled_at = datetime.utcnow()
    db.commit()
    log(f"管理员删除反馈(软删除): id={feedback_id}, by={admin_user.username}", "INFO")
    return {"ok": True}


class TeachingItem(BaseModel):
    task_id: str
    question: str
    title: str
    generated_at: str
    preview: Optional[str] = None
    preview_image: Optional[str] = None  # 预览图片文件名（如果有）
    preview_version: Optional[int] = None  # 封面文件 mtime（秒），前端用作 ?v= 缓存失效参数
    tags: Optional[Dict] = None  # 标签信息（主标签和副标签）
    likes_count: int = 0  # 点赞数
    status: Optional[str] = "completed"  # 任务状态：completed, pending, running, failed
    progress: Optional[int] = 100  # 进度 0-100（已完成默认为 100）
    topic_id: Optional[str] = None  # 所属专题ID
    topic_name: Optional[str] = None  # 所属专题名称
    knowledge_tags: Optional[Dict] = None  # 知识点标签（版本/年级/主标签/子标签）
    second_knowledge_tag: Optional[Dict] = None  # 第二标签组（多知识点，结构同 knowledge_tags，可空）
    is_pinned: Optional[bool] = False
    has_error: Optional[bool] = False
    error_reason: Optional[str] = None


def _read_knowledge_tags(task_id: str, teaching=None) -> Optional[Dict]:
    """读取知识点标签，优先从数据库，回退到 metadata.json。"""
    # 1. 优先从数据库读取
    if teaching is not None:
        try:
            kt = getattr(teaching, 'knowledge_tags', None)
            if kt:
                return kt
        except Exception:
            pass
    # 2. 回退到 metadata.json
    try:
        metadata_path = DATA_DIR / task_id / "metadata.json"
        if metadata_path.exists():
            with open(metadata_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            return meta.get("knowledge_tags")
    except Exception:
        pass
    # 3. 兜底：用数据库已有的 main_tag/sub_tags 反查知识域/年级（不调 LLM）
    if teaching is not None and getattr(teaching, 'main_tag', None) and getattr(teaching, 'sub_tags', None):
        try:
            from knowledge_tag_injector import build_knowledge_tags_from_existing
            return build_knowledge_tags_from_existing(teaching.main_tag, teaching.sub_tags)
        except Exception:
            pass
    return None


def _read_second_tag(task_id: str, teaching=None) -> Optional[Dict]:
    """读取第二标签组，优先从数据库，回退到 metadata.json。"""
    if teaching is not None:
        try:
            st = getattr(teaching, 'second_tag', None)
            if st:
                return st
        except Exception:
            pass
    try:
        metadata_path = DATA_DIR / task_id / "metadata.json"
        if metadata_path.exists():
            with open(metadata_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            return meta.get("second_tag")
    except Exception:
        pass
    return None


def _build_legacy_tags(knowledge_tags: Optional[Dict], teaching=None) -> Optional[Dict]:
    """最小兼容旧前端字段，统一由 knowledge_tags 派生。"""
    if isinstance(knowledge_tags, dict) and knowledge_tags.get("main_tag"):
        return {
            "main_tag": knowledge_tags.get("main_tag"),
            "sub_tags": knowledge_tags.get("sub_tags") or [],
        }
    if teaching is not None and getattr(teaching, "main_tag", None):
        return {
            "main_tag": teaching.main_tag,
            "sub_tags": getattr(teaching, "sub_tags", None) or [],
        }
    return None


# 首页公开教学列表进程内缓存（2026-09-01）：列表低频变化，60s TTL 内
# DB 零查询、磁盘零 stat；新增/编辑教学内容最多延迟 60s 可见（可接受）。
_TEACHINGS_CACHE_TTL = 300.0
_teachings_cache: dict = {"ts": 0.0, "data": None}
_TEACHING_PIN_LIMIT_KEY = "teaching_pin_limit"
_TEACHING_PIN_LIMIT_DEFAULT = 5


def _invalidate_teachings_cache() -> None:
    _teachings_cache["ts"] = 0.0
    _teachings_cache["data"] = None


def _get_teaching_pin_limit(db: Session) -> int:
    row = db.query(SystemConfig).filter(SystemConfig.config_key == _TEACHING_PIN_LIMIT_KEY).first()
    if not row:
        return _TEACHING_PIN_LIMIT_DEFAULT
    try:
        value = int(str(row.config_value).strip())
        return max(_TEACHING_PIN_LIMIT_DEFAULT, value)
    except Exception:
        return _TEACHING_PIN_LIMIT_DEFAULT


@app.get("/api/teachings", response_model=List[TeachingItem])
async def list_teachings(db: Session = Depends(get_db)):
    """获取 storage 中所有已存储的教学内容列表。"""
    # 命中缓存直接返回（公开接口，无鉴权差异，可安全共享）
    now = time.time()
    if _teachings_cache["data"] is not None and (now - _teachings_cache["ts"]) < _TEACHINGS_CACHE_TTL:
        return _teachings_cache["data"]
    teachings = db.query(
        Teaching,
        func.count(TeachingLikeModel.task_id).label('likes_count')
    ).outerjoin(
        TeachingLikeModel, Teaching.task_id == TeachingLikeModel.task_id
    ).group_by(Teaching.task_id).order_by(
        Teaching.generated_at.desc()
    ).all()
    
    teaching_list = []
    
    for teaching, likes_count in teachings:
        task_dir = DATA_DIR / teaching.task_id
        teaching_html_path = task_dir / (teaching.teaching_html_file or "teaching.html")
        
        # 首页和公开教学列表只展示已生成且教学文件存在的案例。
        if not teaching_html_path.exists():
            continue
        
        # 提取标题
        title = teaching.title or ""
        if not title:
            question = teaching.question or ""
            title = question[:30] + "..." if len(question) > 30 else question
        if not title:
            title = "数学问题讲解"
        
        knowledge_tags = _read_knowledge_tags(teaching.task_id, teaching)
        tags = _build_legacy_tags(knowledge_tags, teaching)
        
        # 检查是否有预览图
        preview_image = teaching.preview_image or (
            "Preview.webp" if (task_dir / "Preview.webp").exists() else (
                "preview.webp" if (task_dir / "preview.webp").exists() else (
                    "preview.png" if (task_dir / "preview.png").exists() else None
                )
            )
        )
        has_preview_image = check_preview_image_exists(task_dir, preview_image)
        
        teaching_list.append(TeachingItem(
            task_id=teaching.task_id,
            question=teaching.question or "",
            title=title,
            generated_at=(teaching.generated_at.isoformat() + "Z") if teaching.generated_at else "",
            preview=None,  # 预览文本可以从数据库扩展字段获取
            preview_image=preview_image if has_preview_image else None,
            preview_version=get_preview_version(task_dir, preview_image) if has_preview_image else None,
            tags=tags,
            likes_count=likes_count or 0,
            knowledge_tags=knowledge_tags,
            second_knowledge_tag=_read_second_tag(teaching.task_id, teaching),
            is_pinned=bool(teaching.is_pinned),
        ))

    _teachings_cache["ts"] = time.time()
    _teachings_cache["data"] = teaching_list
    return teaching_list


@app.get("/api/teachings/mine", response_model=List[TeachingItem])
async def list_my_teachings(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    """获取当前用户的教学内容列表（包括正在生成的任务）。需要登录。"""
    token = credentials.credentials if credentials else None
    user_id = verify_token(token) if token else None
    if not user_id:
        raise HTTPException(status_code=401, detail="请先登录")
    
    teaching_list = []
    
    # 1. 获取数据库中已完成的 Teaching 记录
    completed_teachings = db.query(
        Teaching,
        func.count(TeachingLikeModel.task_id).label('likes_count')
    ).outerjoin(
        TeachingLikeModel, Teaching.task_id == TeachingLikeModel.task_id
    ).filter(
        Teaching.user_id == user_id
    ).group_by(Teaching.task_id).order_by(
        Teaching.generated_at.desc()
    ).all()
    
    for teaching, likes_count in completed_teachings:
        task_dir = DATA_DIR / teaching.task_id
        teaching_html_path = task_dir / (teaching.teaching_html_file or "teaching.html")
        if not teaching_html_path.exists() and not (teaching.question or teaching.title):
            continue
        
        title = teaching.title or ""
        if not title:
            question = teaching.question or ""
            title = question[:30] + "..." if len(question) > 30 else question
        if not title:
            title = "数学问题讲解"
        
        knowledge_tags = _read_knowledge_tags(teaching.task_id, teaching)
        tags = _build_legacy_tags(knowledge_tags, teaching)
        
        preview_image = teaching.preview_image
        has_preview_image = check_preview_image_exists(task_dir, preview_image)
        
        # 获取专题信息
        topic_id = teaching.topic_id
        topic_name = None
        if topic_id:
            topic = db.query(Topic).filter(Topic.topic_id == topic_id).first()
            if topic:
                topic_name = topic.name
        
        teaching_list.append(TeachingItem(
            task_id=teaching.task_id,
            question=teaching.question or "",
            title=title,
            generated_at=(teaching.generated_at.isoformat() + "Z") if teaching.generated_at else "",
            preview=None,
            preview_image=preview_image if has_preview_image else None,
            preview_version=get_preview_version(task_dir, preview_image) if has_preview_image else None,
            tags=tags,
            likes_count=likes_count,
            status="completed",  # 已完成
            progress=100,  # 已完成，进度 100%
            topic_id=topic_id,
            topic_name=topic_name,
            knowledge_tags=knowledge_tags,
            second_knowledge_tag=_read_second_tag(teaching.task_id, teaching),
        ))
    
    # 2. 获取正在生成的任务（pending/running 状态）。
    #    公网为多 worker 部署（--workers 2/4），内存 tasks 只存在于创建任务的进程，
    #    请求随机落到其他 worker 时仅靠内存会漏掉正在生成的任务（成果库时有时无）。
    #    故内存优先、task_status 表跨进程兜底合并（进度落库见 _persist_task_state / update_progress）。
    generating_tasks: Dict[str, Task] = {}
    for task_id, task in tasks.items():
        if task.user_id == user_id and task.status in ["pending", "running"]:
            generating_tasks[task_id] = task

    # 2b. task_status 表兜底：补齐其他 worker 进程 / 进程重启后内存丢失的进行中任务
    try:
        status_rows = db.query(TaskStatus).filter(
            TaskStatus.user_id == user_id,
            TaskStatus.status.in_(["pending", "running"]),
        ).all()
    except Exception as e:
        log(f"查询 task_status 进行中任务失败: {e}", "WARN")
        status_rows = []
    for row in status_rows:
        if row.task_id in generating_tasks:
            continue
        # 长时间未更新的残留记录（如服务器重启遗留）视为失效，跳过
        last_updated = row.updated_at or row.created_at
        if last_updated and (datetime.utcnow() - last_updated).total_seconds() > TASK_STATUS_STALE_SECONDS:
            continue
        generating_tasks[row.task_id] = Task(
            task_id=row.task_id,
            status=row.status,
            progress=row.progress,
            metadata=row.metadata_json or {},
            user_id=row.user_id,
            topic_id=row.topic_id,
            prompt=row.prompt or "",
            input_file=row.input_file,
        )

    for task_id, task in generating_tasks.items():
        # 尝试从任务中获取题目信息（标题兜底顺序：metadata.title → question → prompt → 文件名）
        title, question = _derive_generating_titles(task)
        if not question:
            question = "正在生成中..."
        
        # 获取任务的专题信息
        task_topic_id = task.topic_id if hasattr(task, 'topic_id') else None
        task_topic_name = None
        if task_topic_id:
            topic = db.query(Topic).filter(Topic.topic_id == task_topic_id).first()
            if topic:
                task_topic_name = topic.name
        
        teaching_list.append(TeachingItem(
            task_id=task_id,
            question=question,
            title=title,
            generated_at="",  # 正在生成，还没有生成时间
            preview=None,
            preview_image=None,  # 正在生成，还没有预览图
            tags=None,  # 正在生成，还没有标签
            likes_count=0,
            status=task.status,  # pending 或 running
            progress=task.progress,  # 当前进度 0-100
            topic_id=task_topic_id,
            topic_name=task_topic_name,
        ))
    
    # 3. 按状态和时间排序（正在生成的任务排在最前面）
    # 分离正在生成的任务和已完成的任务
    generating_items = [x for x in teaching_list if x.status in ["pending", "running"]]
    completed_items = [x for x in teaching_list if x.status == "completed"]
    
    # 已完成的任务按生成时间倒序排列（最新的在前）
    completed_items.sort(key=lambda x: x.generated_at or "", reverse=True)
    
    # 正在生成的任务按 task_id 倒序排列（最新的在前，task_id 是 UUID，按字符串排序）
    generating_items.sort(key=lambda x: x.task_id, reverse=True)
    
    # 重新组合：正在生成的任务在最前面，已完成的任务在后面
    teaching_list = generating_items + completed_items
    
    return teaching_list


# ========== 专题管理API ==========

class TopicCreate(BaseModel):
    name: str
    description: Optional[str] = None

class TopicUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None

@app.get("/api/topics")
async def list_topics(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    """获取当前用户的所有专题"""
    user_id = verify_token(credentials.credentials) if credentials and credentials.credentials else None
    if not user_id:
        raise HTTPException(status_code=401, detail="未授权")
    
    topics = db.query(Topic).filter(Topic.user_id == user_id).order_by(Topic.created_at).all()
    
    # 统计每个专题中的教学HTML数量
    result = []
    for topic in topics:
        count = db.query(Teaching).filter(Teaching.topic_id == topic.topic_id).count()
        result.append({
            "topic_id": topic.topic_id,
            "name": topic.name,
            "description": topic.description,
            "is_default": topic.is_default,
            "teaching_count": count,
            "created_at": topic.created_at.isoformat() if topic.created_at else "",
            "updated_at": topic.updated_at.isoformat() if topic.updated_at else ""
        })
    
    return {"topics": result}


@app.post("/api/topics")
async def create_topic(
    topic_data: TopicCreate,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    """创建新专题"""
    user_id = verify_token(credentials.credentials) if credentials and credentials.credentials else None
    if not user_id:
        raise HTTPException(status_code=401, detail="未授权")
    
    # 创建专题
    topic_id = str(uuid4())
    topic = Topic(
        topic_id=topic_id,
        user_id=user_id,
        name=topic_data.name or "未命名专题",
        description=topic_data.description,
        is_default=False
    )
    db.add(topic)
    db.commit()
    db.refresh(topic)
    
    return {
        "topic_id": topic_id,
        "message": "专题创建成功",
        "topic": {
            "topic_id": topic.topic_id,
            "name": topic.name,
            "description": topic.description,
            "is_default": topic.is_default,
            "teaching_count": 0,
            "created_at": topic.created_at.isoformat() if topic.created_at else "",
            "updated_at": topic.updated_at.isoformat() if topic.updated_at else ""
        }
    }


@app.put("/api/topics/{topic_id}")
async def update_topic(
    topic_id: str,
    topic_data: TopicUpdate,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    """更新专题信息"""
    user_id = verify_token(credentials.credentials) if credentials and credentials.credentials else None
    if not user_id:
        raise HTTPException(status_code=401, detail="未授权")
    
    topic = db.query(Topic).filter(
        Topic.topic_id == topic_id,
        Topic.user_id == user_id
    ).first()
    
    if not topic:
        raise HTTPException(status_code=404, detail="专题不存在")
    
    if topic_data.name is not None:
        topic.name = topic_data.name
    if topic_data.description is not None:
        topic.description = topic_data.description
    
    topic.updated_at = datetime.utcnow()
    db.commit()
    
    return {"message": "专题更新成功"}


@app.delete("/api/topics/{topic_id}")
async def delete_topic(
    topic_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    """删除专题（教学HTML的topic_id会被设置为NULL）"""
    user_id = verify_token(credentials.credentials) if credentials and credentials.credentials else None
    if not user_id:
        raise HTTPException(status_code=401, detail="未授权")
    
    topic = db.query(Topic).filter(
        Topic.topic_id == topic_id,
        Topic.user_id == user_id
    ).first()
    
    if not topic:
        raise HTTPException(status_code=404, detail="专题不存在")
    
    if topic.is_default:
        raise HTTPException(status_code=400, detail="不能删除默认专题")
    
    db.delete(topic)
    db.commit()
    
    return {"message": "专题删除成功"}


@app.post("/api/topics/{topic_id}/teachings/{task_id}")
async def move_teaching_to_topic(
    topic_id: str,
    task_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    """将教学HTML移动到指定专题"""
    user_id = verify_token(credentials.credentials) if credentials and credentials.credentials else None
    if not user_id:
        raise HTTPException(status_code=401, detail="未授权")
    
    # 验证专题属于当前用户
    topic = db.query(Topic).filter(
        Topic.topic_id == topic_id,
        Topic.user_id == user_id
    ).first()
    if not topic:
        raise HTTPException(status_code=404, detail="专题不存在")
    
    # 验证教学HTML属于当前用户
    teaching = db.query(Teaching).filter(
        Teaching.task_id == task_id,
        Teaching.user_id == user_id
    ).first()
    if not teaching:
        raise HTTPException(status_code=404, detail="教学HTML不存在")
    
    teaching.topic_id = topic_id
    db.commit()
    
    return {"message": "移动成功"}


@app.delete("/api/topics/{topic_id}/teachings/{task_id}")
async def remove_teaching_from_topic(
    topic_id: str,
    task_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    """从专题中移除教学HTML（设置为NULL）"""
    user_id = verify_token(credentials.credentials) if credentials and credentials.credentials else None
    if not user_id:
        raise HTTPException(status_code=401, detail="未授权")
    
    # 验证专题属于当前用户
    topic = db.query(Topic).filter(
        Topic.topic_id == topic_id,
        Topic.user_id == user_id
    ).first()
    if not topic:
        raise HTTPException(status_code=404, detail="专题不存在")
    
    # 验证教学HTML属于当前用户
    teaching = db.query(Teaching).filter(
        Teaching.task_id == task_id,
        Teaching.user_id == user_id
    ).first()
    if not teaching:
        raise HTTPException(status_code=404, detail="教学HTML不存在")
    
    # 验证教学HTML确实在这个专题中
    if teaching.topic_id != topic_id:
        raise HTTPException(status_code=400, detail="教学HTML不在该专题中")
    
    teaching.topic_id = None
    db.commit()
    
    return {"message": "移除成功"}


@app.post("/api/topics/{topic_id}/batch-import")
async def batch_import_to_topic(
    topic_id: str,
    files: List[UploadFile] = File(None),
    texts: str = Form(None),  # 多行文本，每行一个题目
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    """批量导入图片或文本到专题，为每个文件/每行文本创建一个教学HTML生成任务
    
    限制：
    - 最多只能选择6个文件或6行文本（文件+文本总数不超过6个）
    - 每个任务都会消耗用户的每日调用次数
    - 如果剩余次数不足，会拒绝整个批量生成请求
    - 所有任务会并发执行，而不是顺序执行
    """
    user_id = verify_token(credentials.credentials) if credentials and credentials.credentials else None
    if not user_id:
        raise HTTPException(status_code=401, detail="未授权")
    
    # 验证专题
    topic = db.query(Topic).filter(
        Topic.topic_id == topic_id,
        Topic.user_id == user_id
    ).first()
    if not topic:
        raise HTTPException(status_code=404, detail="专题不存在")
    
    # 收集所有要创建的任务
    items_to_process = []
    
    # 处理上传的文件
    if files:
        if len(files) > 6:
            raise HTTPException(status_code=400, detail="最多只能选择6个文件")
        items_to_process.extend([("file", f) for f in files])
    
    # 处理文本输入（每行一个题目）
    if texts:
        lines = [line.strip() for line in texts.split('\n') if line.strip()]
        if len(lines) > 6:
            raise HTTPException(status_code=400, detail="最多只能输入6行文本")
        items_to_process.extend([("text", line) for line in lines])
    
    # 检查总数不超过6个
    if len(items_to_process) > 6:
        raise HTTPException(status_code=400, detail="文件+文本总数不能超过6个")
    
    if len(items_to_process) == 0:
        raise HTTPException(status_code=400, detail="请至少选择一个文件或输入一行文本")

    # 额度由前端 /api/v2/generation/consume 统一扣减，此处不再重复检查旧版每日次数限制

    task_ids = []
    
    # 为每个项目创建任务
    for item_type, item_data in items_to_process:
        task_id = str(uuid4())

        if item_type == "file":
            # 保存文件到临时位置
            file = item_data
            temp_dir = DATA_DIR / f"temp_{task_id}"
            temp_dir.mkdir(parents=True, exist_ok=True)
            file_path = temp_dir / file.filename
            with file_path.open("wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            input_file_path = str(file_path)
            prompt = ""
        else:
            # 文本输入
            input_file_path = None
            prompt = item_data
        
        # 创建任务
        task = Task(
            task_id=task_id,
            input_file=input_file_path,
            prompt=prompt,
            user_id=user_id,
            topic_id=topic_id
        )
        tasks[task_id] = task
        _persist_task_state(task)
        task_ids.append(task_id)
    
    # 使用 asyncio.create_task 并发执行所有任务
    # 这样所有任务会同时开始执行，而不是顺序执行
    for task_id in task_ids:
        asyncio.create_task(run_pipeline(task_id))
        log(f"批量生成：任务 {task_id} 已启动（并发执行）", "INFO")
    
    log(f"批量生成：成功创建 {len(task_ids)} 个任务，全部并发执行", "INFO")
    
    return {
        "task_ids": task_ids,
        "count": len(task_ids),
        "message": f"成功创建{len(task_ids)}个任务，正在并发生成中..."
    }


class ShareTopicRequest(BaseModel):
    expires_days: Optional[int] = None  # 分享有效期（天数），None表示永久有效


@app.post("/api/topics/{topic_id}/share")
async def share_topic(
    topic_id: str,
    share_data: Optional[ShareTopicRequest] = None,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    """生成专题分享链接"""
    user_id = verify_token(credentials.credentials) if credentials and credentials.credentials else None
    if not user_id:
        raise HTTPException(status_code=401, detail="未授权")
    
    # 验证专题属于当前用户
    topic = db.query(Topic).filter(
        Topic.topic_id == topic_id,
        Topic.user_id == user_id
    ).first()
    if not topic:
        raise HTTPException(status_code=404, detail="专题不存在")
    
    # 生成分享令牌（32字节的随机十六进制字符串）
    share_token = secrets.token_urlsafe(32)
    
    # 计算过期时间
    share_expires_at = None
    if share_data and share_data.expires_days:
        share_expires_at = datetime.utcnow() + timedelta(days=share_data.expires_days)
    
    # 更新专题
    topic.share_token = share_token
    topic.is_shared = True
    topic.share_expires_at = share_expires_at
    db.commit()
    
    # 构建分享URL
    share_url = f"/share_topic.html?token={share_token}"
    
    return {
        "share_token": share_token,
        "share_url": share_url,
        "expires_at": share_expires_at.isoformat() + "Z" if share_expires_at else None,
        "message": "分享链接生成成功"
    }


@app.get("/api/topics/shared/{share_token}")
async def get_shared_topic(
    share_token: str,
    db: Session = Depends(get_db)
):
    """通过分享令牌获取专题详情（公开访问，无需登录）"""
    topic = db.query(Topic).filter(Topic.share_token == share_token).first()
    
    if not topic:
        raise HTTPException(status_code=404, detail="分享链接不存在或已失效")
    
    # 检查是否已过期
    if topic.share_expires_at and topic.share_expires_at < datetime.utcnow():
        raise HTTPException(status_code=410, detail="分享链接已过期")
    
    if not topic.is_shared:
        raise HTTPException(status_code=403, detail="分享已取消")
    
    # 获取专题下的所有教学内容
    teachings = db.query(Teaching).filter(
        Teaching.topic_id == topic.topic_id
    ).order_by(Teaching.generated_at.desc()).all()
    
    teaching_list = []
    for teaching in teachings:
        task_dir = DATA_DIR / teaching.task_id
        teaching_html_path = task_dir / teaching.teaching_html_file
        
        # 检查 teaching.html 文件是否存在
        if not teaching_html_path.exists():
            continue
        
        # 提取标题
        title = teaching.title or ""
        if not title:
            question = teaching.question or ""
            title = question[:30] + "..." if len(question) > 30 else question
        if not title:
            title = "数学问题讲解"
        
        # 构建标签信息
        tags = None
        if teaching.main_tag:
            tags = {
                "main_tag": teaching.main_tag,
                "sub_tags": teaching.sub_tags if teaching.sub_tags else []
            }
        
        # 检查是否有预览图
        preview_image = teaching.preview_image
        has_preview_image = check_preview_image_exists(task_dir, preview_image)
        
        teaching_list.append({
            "task_id": teaching.task_id,
            "question": teaching.question or "",
            "title": title,
            "generated_at": (teaching.generated_at.isoformat() + "Z") if teaching.generated_at else "",
            "preview_image": preview_image if has_preview_image else None,
            "preview_version": get_preview_version(task_dir, preview_image) if has_preview_image else None,
            "tags": tags,
        })
    
    return {
        "topic": {
            "topic_id": topic.topic_id,
            "name": topic.name,
            "description": topic.description,
            "created_at": topic.created_at.isoformat() if topic.created_at else "",
        },
        "teachings": teaching_list,
        "teaching_count": len(teaching_list)
    }


@app.delete("/api/topics/{topic_id}/share")
async def cancel_share_topic(
    topic_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    """取消专题分享"""
    user_id = verify_token(credentials.credentials) if credentials and credentials.credentials else None
    if not user_id:
        raise HTTPException(status_code=401, detail="未授权")
    
    # 验证专题属于当前用户
    topic = db.query(Topic).filter(
        Topic.topic_id == topic_id,
        Topic.user_id == user_id
    ).first()
    if not topic:
        raise HTTPException(status_code=404, detail="专题不存在")
    
    # 取消分享
    topic.share_token = None
    topic.is_shared = False
    topic.share_expires_at = None
    db.commit()
    
    return {"message": "分享已取消"}


@app.get("/api/topics/{topic_id}/share-status")
async def get_topic_share_status(
    topic_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    """获取专题分享状态"""
    user_id = verify_token(credentials.credentials) if credentials and credentials.credentials else None
    if not user_id:
        raise HTTPException(status_code=401, detail="未授权")
    
    # 验证专题属于当前用户
    topic = db.query(Topic).filter(
        Topic.topic_id == topic_id,
        Topic.user_id == user_id
    ).first()
    if not topic:
        raise HTTPException(status_code=404, detail="专题不存在")
    
    share_url = None
    if topic.is_shared and topic.share_token:
        share_url = f"/share_topic.html?token={topic.share_token}"
    
    return {
        "is_shared": topic.is_shared,
        "share_token": topic.share_token,
        "share_url": share_url,
        "expires_at": topic.share_expires_at.isoformat() + "Z" if topic.share_expires_at else None,
        "is_expired": topic.share_expires_at is not None and topic.share_expires_at < datetime.utcnow() if topic.share_expires_at else False
    }


# 主标签类别分类（按关键词自动归类，用于相似推荐）
MAIN_TAG_CATEGORIES = {
    "数与式": ["有理数", "实数", "无理数", "平方根", "立方根", "二次根式", "整式", "代数式", "分式", "幂", "科学记数法", "百分数", "比", "比例"],
    "方程与不等式": ["方程", "不等式", "因式分解", "消元", "代入法", "加减法"],
    "函数": ["函数", "坐标系", "坐标", "抛物线", "图象", "图像", "变量"],
    "图形与几何": ["三角形", "四边形", "平行四边形", "矩形", "菱形", "正方形", "梯形", "圆", "图形", "几何", "勾股", "相似", "全等", "对称", "旋转", "平移", "投影", "视图", "线段", "角", "命题", "证明", "多边形", "圆柱", "圆锥", "扇形", "展开", "尺规", "三角函数", "解直角三角形"],
    "统计与概率": ["数据", "统计", "概率", "样本", "总体", "事件", "可能性", "频率", "平均数", "中位数", "众数", "方差"],
}

def get_main_tag_category(main_tag):
    """根据章/单元名称推断所属知识域（兜底用，优先使用 knowledge_tags.version）"""
    if not main_tag:
        return None
    for category, keywords in MAIN_TAG_CATEGORIES.items():
        if any(kw in main_tag for kw in keywords):
            return category
    return None


# 年级中文前缀 → 数值层级（一上→1、三下→3）。个人中心年级为 1-9，教学内容年级为中文学期（一上…九下）。
_GRADE_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def _teaching_grade_level(teaching) -> Optional[int]:
    """取教学内容的年级数值层级，用于“不超过用户年级”的推荐过滤。"""
    kt = _read_knowledge_tags(teaching.task_id, teaching)
    g = ""
    if isinstance(kt, dict):
        g = (kt.get("grade") or "").strip()
    if not g and getattr(teaching, "grade", None):
        g = str(getattr(teaching, "grade")).strip()
    if not g:
        return None
    return _GRADE_CN_NUM.get(g[0])


def _teaching_version(teaching) -> str:
    """取教学内容的所属知识域（knowledge_tags.version）。"""
    kt = _read_knowledge_tags(teaching.task_id, teaching)
    if isinstance(kt, dict):
        return (kt.get("version") or "").strip()
    return ""


def _filter_similar_by_domain_and_grade(items, current_version, user_grade):
    """
    相似推荐过滤（探寻更多相似推演）：
    1) 优先同知识域：与当前教学内容 knowledge_tags.version 一致者优先；
    2) 年级不超过 所选年级 + 1 个年级段（例如所选二年级 → 不推荐超过三年级）。
    user_grade 为用户所选年级数值(1-9)；为空表示未选/未登录，则不过滤直接返回。
    已知年级且超出边界的项一律排除；同域内无合格项时仅回退到“同域且年级未知”的项，
    不再回退到超年级内容，避免推荐超过所选年级。
    """
    if not user_grade:
        return items
    try:
        user_level = int(str(user_grade).strip())
    except (ValueError, TypeError):
        return items
    if user_level <= 0:
        return items
    boundary = user_level + 1  # 不超过所选年级两个年级段

    def _lvl(t):
        return _teaching_grade_level(t)

    # 同知识域优先（当前教学无域信息时退化为全部）
    same = [t for t in items if (not current_version) or _teaching_version(t) == current_version]
    # 年级合格：已知年级且 <= 边界
    in_boundary = [t for t in same if (_lvl(t) is not None and _lvl(t) <= boundary)]
    if in_boundary:
        return in_boundary
    # 同域内年级未知的项保守保留（至少同知识域）
    unknown_grade = [t for t in same if _lvl(t) is None]
    if unknown_grade:
        return unknown_grade
    # 同知识域内既无年级合格项也无未知项，返回空（前端显示空态），不推荐超年级内容
    return []


@app.get("/api/teachings/{task_id}/similar", response_model=List[TeachingItem])
async def get_similar_teachings(task_id: str, max_grade: Optional[str] = None, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security), db: Session = Depends(get_db)):
    """
    获取与指定题目语义相似的其他题目（最多 10 个）
    使用 Chroma 向量数据库进行高效相似度搜索
    
    注意：即使数据库记录尚未创建，只要向量数据库中有 embedding，也可以进行查询
    """
    # —— 相似推荐年级/知识域过滤准备 ——
    # 当前教学内容的知识域（用于“先按知识域”过滤）
    _cur_kt = _read_knowledge_tags(task_id)
    current_version = (_cur_kt or {}).get("version", "").strip() if isinstance(_cur_kt, dict) else ""
    # 当前登录用户的年级：服务端从 token 解析，避免前端 localStorage 快照过期导致过滤失效；
    # 未登录时回退到 max_grade 查询参数（前端传入的所选年级）。
    user_grade = None
    try:
        if credentials and credentials.credentials:
            _uid = verify_token(credentials.credentials)
            if _uid:
                _u = db.query(User).filter(User.user_id == _uid).first()
                if _u and _u.grade:
                    user_grade = _u.grade
    except Exception:
        pass
    if not user_grade and max_grade:
        user_grade = max_grade

    # 先检查向量数据库中是否有 embedding（即使数据库记录还没创建）
    from utils.vector_db import get_teaching_embedding, query_similar_teachings
    
    # 尝试从向量数据库获取当前题目的 embedding
    current_embedding = get_teaching_embedding(task_id)
    
    # 如果向量数据库中有 embedding，即使数据库记录不存在，也可以进行查询
    # 注意：需要检查是否为 None 且长度大于 0（不能直接用 if current_embedding，因为列表的真假值判断会报错）
    if current_embedding is not None and len(current_embedding) > 0:
        try:
            # 使用向量数据库进行相似度搜索
            similar_items = query_similar_teachings(
                query_embedding=current_embedding,
                n_results=10,
                exclude_ids=[task_id]
            )
            
            # 从相似度结果中提取 task_id 列表
            similar_task_ids = [item["id"] for item in similar_items]
            
            if similar_task_ids:
                # 从数据库获取完整的题目信息（只获取已存在的记录）
                similar_teachings = db.query(Teaching).filter(
                    Teaching.task_id.in_(similar_task_ids)
                ).all()
                
                # 按照相似度排序
                similarity_map = {item["id"]: item["similarity"] for item in similar_items}
                similar_teachings.sort(key=lambda t: similarity_map.get(t.task_id, 0), reverse=True)
                
                # 转换为 TeachingItem 格式并返回
                # 一次聚合本批记录点赞数（替代原来的 N+1 逐条 COUNT）
                batch = similar_teachings[:10]
                like_map = {}
                if batch:
                    like_rows = db.execute(
                        text(
                            "SELECT task_id, COUNT(*) AS c FROM teaching_likes "
                            "WHERE task_id IN :task_ids GROUP BY task_id"
                        ),
                        {'task_ids': [t.task_id for t in batch]}
                    ).fetchall()
                    like_map = {row[0]: row[1] for row in like_rows}
                teaching_list = []
                for teaching in batch:
                    task_dir = DATA_DIR / teaching.task_id
                    teaching_html_path = task_dir / teaching.teaching_html_file
                    
                    if not teaching_html_path.exists():
                        continue
                    
                    title = teaching.title or ""
                    if not title:
                        question = teaching.question or ""
                        title = question[:30] + "..." if len(question) > 30 else question
                    if not title:
                        title = "数学问题讲解"
                    
                    tags = None
                    if teaching.main_tag:
                        tags = {
                            "main_tag": teaching.main_tag,
                            "sub_tags": teaching.sub_tags if teaching.sub_tags else []
                        }
                    
                    preview_image = get_preview_image_name(task_dir, teaching.preview_image)
                    has_preview_image = preview_image is not None
                    
                    # 获取点赞数
                    likes_count = like_map.get(teaching.task_id, 0)
                    
                    teaching_list.append(TeachingItem(
                        task_id=teaching.task_id,
                        question=teaching.question or "",
                        title=title,
                        generated_at=(teaching.generated_at.isoformat() + "Z") if teaching.generated_at else "",
                        preview=None,
                        preview_image=preview_image if has_preview_image else None,
                        preview_version=get_preview_version(task_dir, preview_image) if has_preview_image else None,
                        tags=tags,
                        likes_count=likes_count,
                        knowledge_tags=_read_knowledge_tags(teaching.task_id, teaching),
                        second_knowledge_tag=_read_second_tag(teaching.task_id, teaching),
                    ))
                
                teaching_list = _filter_similar_by_domain_and_grade(teaching_list, current_version, user_grade)
                return teaching_list
        except Exception as e:
            log(f"向量相似度查询失败: {e}", "WARN")
            # 继续执行下面的逻辑
    
    # 如果向量数据库中没有 embedding，或者查询失败，尝试从数据库获取题目信息
    current_teaching = db.query(Teaching).filter(Teaching.task_id == task_id).first()
    if not current_teaching:
        # 如果数据库记录也不存在，返回空列表（而不是 404）
        # 这样前端可以继续等待，直到向量计算完成
        return []
    
    if not current_teaching.question:
        # 如果没有题目文本，返回空列表
        return []
    
    # 使用原有的逻辑（通过 find_similar_questions_async）
    similar_teachings = []
    try:
        # 延迟导入，避免启动时加载 PyTorch（如果 torch 有问题，应用仍可启动）
        from utils.embedding_utils import find_similar_questions_async
        similar_results = await find_similar_questions_async(
            current_question=current_teaching.question,
            current_task_id=task_id,
            top_k=10
        )
        
        # 从相似度结果中提取 task_id 列表
        similar_task_ids = [task_id for task_id, _ in similar_results]
        
        if similar_task_ids:
            # 从数据库获取完整的题目信息
            similar_teachings = db.query(Teaching).filter(
                Teaching.task_id.in_(similar_task_ids)
            ).all()
            
            # 按照相似度排序
            similarity_map = {task_id: similarity for task_id, similarity in similar_results}
            similar_teachings.sort(key=lambda t: similarity_map.get(t.task_id, 0), reverse=True)
    except Exception as e:
        log(f"计算相似度失败: {e}", "ERROR")
        # 如果相似度计算失败，回退到基于标签的推荐
        # 获取所有其他题目（排除当前题目）
        other_teachings = db.query(Teaching).filter(
            Teaching.task_id != task_id,
            Teaching.question.isnot(None),
            Teaching.question != ""
        ).all()
        
        # 优先返回相同主标签的题目
        if current_teaching.main_tag:
            tag_matched = [t for t in other_teachings if t.main_tag == current_teaching.main_tag]
            similar_teachings.extend(tag_matched[:10])
        
        # 如果还不够，添加其他题目
        remaining = [t for t in other_teachings if t not in similar_teachings]
        similar_teachings.extend(remaining[:10 - len(similar_teachings)])

    # embedding 不可用或返回空时，按标签匹配（三级优先：章/单元精确匹配 → 同知识域 → 不跨域）
    if not similar_teachings:
        other_teachings = db.query(Teaching).filter(
            Teaching.task_id != task_id,
            Teaching.question.isnot(None),
            Teaching.question != ""
        ).all()
        # 当前题目的章/单元 与 知识域（优先 knowledge_tags.version）
        current_main_tag = current_teaching.main_tag or ""
        kt = _read_knowledge_tags(task_id, current_teaching)
        current_domain = ""
        if isinstance(kt, dict):
            current_domain = (kt.get("version") or "").strip()
        if not current_domain:
            current_domain = get_main_tag_category(current_main_tag) or ""

        def _teaching_domain(t) -> str:
            """获取题目知识域：优先 knowledge_tags.version，兜底按章/单元关键词推断。"""
            tkt = _read_knowledge_tags(t.task_id, t)
            if isinstance(tkt, dict) and (tkt.get("version") or "").strip():
                return (tkt.get("version") or "").strip()
            return get_main_tag_category(t.main_tag) or ""

        # 1) 章/单元（主标签）精确匹配
        if current_main_tag:
            similar_teachings = [t for t in other_teachings if t.main_tag == current_main_tag][:10]
        # 2) 同知识域匹配补充（不跨知识域）
        if len(similar_teachings) < 5 and current_domain:
            for t in other_teachings:
                if t in similar_teachings:
                    continue
                if _teaching_domain(t) == current_domain:
                    similar_teachings.append(t)
                    if len(similar_teachings) >= 10:
                        break

    # 转换为 TeachingItem 格式
    # 一次聚合本批记录点赞数（替代原来的 N+1 逐条 COUNT）
    batch = similar_teachings[:10]
    like_map = {}
    if batch:
        like_rows = db.execute(
            text(
                "SELECT task_id, COUNT(*) AS c FROM teaching_likes "
                "WHERE task_id IN :task_ids GROUP BY task_id"
            ),
            {'task_ids': [t.task_id for t in batch]}
        ).fetchall()
        like_map = {row[0]: row[1] for row in like_rows}
    teaching_list = []
    for teaching in batch:
        task_dir = DATA_DIR / teaching.task_id
        teaching_html_path = task_dir / teaching.teaching_html_file
        
        if not teaching_html_path.exists():
            continue
        
        title = teaching.title or ""
        if not title:
            question = teaching.question or ""
            title = question[:30] + "..." if len(question) > 30 else question
        if not title:
            title = "数学问题讲解"
        
        tags = None
        if teaching.main_tag:
            tags = {
                "main_tag": teaching.main_tag,
                "sub_tags": teaching.sub_tags if teaching.sub_tags else []
            }
        
        preview_image = get_preview_image_name(task_dir, teaching.preview_image)
        has_preview_image = preview_image is not None
        
        # 获取点赞数
        likes_count = like_map.get(teaching.task_id, 0)
        
        teaching_list.append(TeachingItem(
            task_id=teaching.task_id,
            question=teaching.question or "",
            title=title,
            generated_at=(teaching.generated_at.isoformat() + "Z") if teaching.generated_at else "",
            preview=None,
            preview_image=preview_image if has_preview_image else None,
            preview_version=get_preview_version(task_dir, preview_image) if has_preview_image else None,
            tags=tags,
            likes_count=likes_count,
            knowledge_tags=_read_knowledge_tags(teaching.task_id, teaching),
            second_knowledge_tag=_read_second_tag(teaching.task_id, teaching),
        ))

    teaching_list = _filter_similar_by_domain_and_grade(teaching_list, current_version, user_grade)
    return teaching_list


@app.get("/api/teachings/{task_id}/metadata")
async def get_teaching_metadata(task_id: str, db: Session = Depends(get_db)):
    """获取指定任务的教学内容元数据。"""
    teaching = db.query(Teaching).filter(Teaching.task_id == task_id).first()
    
    if not teaching:
        # 检查内存中的任务是否还在进行中
        task = tasks.get(task_id)
        if not task:
            # task_status 表兜底：多 worker 部署下，任务可能在【其他 worker 进程】的内存中，
            # 创建/进度更新时已把状态落库（见 _persist_task_state），这里从数据库回填，
            # 避免前端把仍在生成的任务误判为「教学内容不存在」。
            task = _load_task_state(task_id)
        if task:
            if task.status == "running" or task.status == "pending":
                return {"task_id": task_id, "status": task.status, "progress": task.progress}
            elif task.status == "failed":
                raise HTTPException(status_code=404, detail=f"任务生成失败: {task.error or '未知错误'}")
        raise HTTPException(status_code=404, detail="Teaching not found")
    
    # 增加观看次数（如果字段存在）
    try:
        if hasattr(teaching, 'view_count'):
            teaching.view_count = (teaching.view_count or 0) + 1
            db.commit()
    except Exception as e:
        db.rollback()
        log(f"增加观看次数失败（可能字段尚未添加）: {e}", "WARN")
    
    # 查询作者用户名（如有）
    author_username = None
    if teaching.user_id:
        try:
            author = db.query(User).filter(User.user_id == teaching.user_id).first()
            if author:
                author_username = author.username
        except Exception as e:
            log(f"查询作者用户名失败: {e}", "WARN")
    
    # knowledge_tags 是新标签体系的唯一业务来源，旧字段仅用于兼容历史客户端。
    knowledge_tags = _read_knowledge_tags(task_id, teaching)
    second_knowledge_tag = _read_second_tag(task_id, teaching)
    legacy_tags = _build_legacy_tags(knowledge_tags, teaching)
    # 预览图：读取实际存在的预览图文件名（未生成时为 None）
    task_dir = DATA_DIR / task_id
    preview_image = get_preview_image_name(task_dir, teaching.preview_image)
    metadata = {
        "task_id": teaching.task_id,
        "question": teaching.question,
        "prompt": teaching.prompt,
        "title": teaching.title,
        "is_math_problem": teaching.is_math_problem,
        "main_tag": knowledge_tags.get("main_tag") if knowledge_tags else None,
        "sub_tags": knowledge_tags.get("sub_tags") if knowledge_tags else [],
        "reasoning": teaching.reasoning,
        "generated_at": (teaching.generated_at.isoformat() + "Z") if teaching.generated_at else None,
        "input_file": teaching.input_file,
        "teaching_html_file": teaching.teaching_html_file,
        "preview_image": preview_image,
        "preview_version": get_preview_version(task_dir, preview_image),
        "view_count": getattr(teaching, 'view_count', 0) or 0,
        "author_username": author_username,
        "tags": legacy_tags,
        "knowledge_tags": knowledge_tags,
        "second_knowledge_tag": second_knowledge_tag,
    }

    # 如果数据库中的标题缺失，尝试读取存储目录的 metadata.json 作为补充
    try:
        task_dir = DATA_DIR / task_id
        metadata_path = task_dir / "metadata.json"
        if metadata_path.exists():
            with metadata_path.open("r", encoding="utf-8") as f:
                file_meta = json.load(f)
            # 仅在缺失或为空时补齐
            if not metadata.get("title") and file_meta.get("title"):
                metadata["title"] = file_meta.get("title")
            if not metadata.get("question") and file_meta.get("question"):
                metadata["question"] = file_meta.get("question")
            # 知识点标签：如果数据库没有，从 metadata.json 补充
            if not metadata.get("knowledge_tags") and file_meta.get("knowledge_tags"):
                metadata["knowledge_tags"] = file_meta["knowledge_tags"]
                metadata["main_tag"] = metadata["knowledge_tags"].get("main_tag")
                metadata["sub_tags"] = metadata["knowledge_tags"].get("sub_tags") or []
                metadata["tags"] = _build_legacy_tags(metadata["knowledge_tags"], teaching)
            if not metadata.get("second_knowledge_tag") and file_meta.get("second_tag"):
                metadata["second_knowledge_tag"] = file_meta["second_tag"]
            # 是否需要手动选择标签
            if file_meta.get("needs_tag_selection"):
                metadata["needs_tag_selection"] = file_meta["needs_tag_selection"]
    except Exception as e:
        log(f"读取本地 metadata.json 失败: {e}", "WARN")
    
    return metadata


@app.get("/api/teachings/{task_id}/content-profile")
async def get_teaching_content_profile(task_id: str):
    """读取教学画像 content_profile.json（P0 起落盘；调试/抽查用，只读不写库）.

    返回 {"content_profile": {...}, "recognition_meta": {...}}；文件不存在 → 404。
    """
    from fastapi import HTTPException

    task_dir = DATA_DIR / task_id
    cp_path = task_dir / "content_profile.json"
    if not cp_path.exists():
        raise HTTPException(status_code=404, detail="content_profile.json not found")

    with cp_path.open("r", encoding="utf-8") as f:
        profile = json.load(f)

    recognition_meta = {}
    meta_path = task_dir / "metadata.json"
    if meta_path.exists():
        try:
            with meta_path.open("r", encoding="utf-8") as f:
                file_meta = json.load(f)
            recognition_meta = file_meta.get("recognition_meta") or {}
        except Exception:
            pass
    return {"content_profile": profile, "recognition_meta": recognition_meta}


# ==================== 知识点标签手动选择 API ====================

# 数据库读取的框架数据缓存（60 秒内复用，避免频繁查表）
_KNOWLEDGE_FRAMEWORK_DB_CACHE: dict | None = None
_KNOWLEDGE_FRAMEWORK_DB_CACHE_TIME: float = 0.0
_KNOWLEDGE_FRAMEWORK_DB_CACHE_TTL: float = 300.0


def _load_knowledge_framework_from_db() -> dict | None:
    """
    从数据库 knowledge_tag_framework 表读取框架数据，构建与 JSON 文件相同的数据结构。

    返回结构：
        {
            "versions": [...],
            "grades": [...],
            "main_tags": [...],
            "main_tag_info": { main_tag: { grades: [...], sub_tags: [...] } },
            "hierarchy": { version: { grade: { main_tag: [sub_tag, ...] } } }
        }

    查询失败或表不存在时返回 None，调用方应回退到 JSON 文件。
    """
    global _KNOWLEDGE_FRAMEWORK_DB_CACHE, _KNOWLEDGE_FRAMEWORK_DB_CACHE_TIME
    now = time.time()
    if _KNOWLEDGE_FRAMEWORK_DB_CACHE and (now - _KNOWLEDGE_FRAMEWORK_DB_CACHE_TIME) < _KNOWLEDGE_FRAMEWORK_DB_CACHE_TTL:
        return _KNOWLEDGE_FRAMEWORK_DB_CACHE

    try:
        from database import SessionLocal  # 局部导入，避免影响顶层模块加载
        from database.models import KnowledgeTagFramework

        db = SessionLocal()
        try:
            rows = db.query(KnowledgeTagFramework).order_by(KnowledgeTagFramework.id).all()

            versions: list[str] = []
            grades: list[str] = []
            main_tags: list[str] = []
            # main_tag -> { grades: set, sub_tags: set }
            main_tag_info: dict[str, dict] = {}
            # version -> grade -> main_tag -> [sub_tag, ...]
            hierarchy: dict[str, dict[str, dict[str, list[str]]]] = {}

            for row in rows:
                for values, value in (
                    (versions, row.version),
                    (grades, row.grade),
                    (main_tags, row.main_tag),
                ):
                    if value and value not in values:
                        values.append(value)

                # 构建 hierarchy
                hierarchy.setdefault(row.version, {}) \
                    .setdefault(row.grade, {}) \
                    .setdefault(row.main_tag, [])
                if row.sub_tag and row.sub_tag not in hierarchy[row.version][row.grade][row.main_tag]:
                    hierarchy[row.version][row.grade][row.main_tag].append(row.sub_tag)

                # 构建 main_tag_info
                info = main_tag_info.setdefault(row.main_tag, {"grades": set(), "sub_tags": set()})
                info["grades"].add(row.grade)
                if row.sub_tag:
                    info["sub_tags"].add(row.sub_tag)

            # 将 set 转为有序 list
            result = {
                "versions": versions,
                "grades": grades,
                "main_tags": main_tags,
                "main_tag_info": {
                    mt: {
                        "grades": sorted(info["grades"]),
                        "sub_tags": sorted(info["sub_tags"]),
                    }
                    for mt, info in main_tag_info.items()
                },
                "hierarchy": {
                    ver: {
                        gr: {
                            mt: subs
                            for mt, subs in mains.items()
                        }
                        for gr, mains in grades.items()
                    }
                    for ver, grades in hierarchy.items()
                },
            }

            _KNOWLEDGE_FRAMEWORK_DB_CACHE = result
            _KNOWLEDGE_FRAMEWORK_DB_CACHE_TIME = now
            return result
        finally:
            db.close()
    except Exception as e:
        log(f"从数据库读取知识点标签框架失败: {e}", "WARN")
        return None


@app.get("/api/knowledge-tag-framework")
async def get_knowledge_tag_framework():
    """获取数据库中的知识点标签框架数据。"""
    data = _load_knowledge_framework_from_db()
    if data is None:
        raise HTTPException(status_code=503, detail="知识点标签框架数据库不可用")
    return {
        "versions": data.get("versions", []),
        "grades": data.get("grades", []),
        "main_tags": data.get("main_tags", []),
        "main_tag_info": data.get("main_tag_info", {}),
        "hierarchy": data.get("hierarchy", {}),
        "source": "database",
    }


def _parse_tag_group_payload(payload):
    """从单组标签 payload 解析字段。返回 (version, grade, main_tag, sub_tags)。"""
    version = (payload.get("version") or "").strip()
    grade = (payload.get("grade") or "").strip()
    main_tag = (payload.get("main_tag") or "").strip()
    sub_tags = payload.get("sub_tags", [])
    if not isinstance(sub_tags, list):
        raise HTTPException(status_code=400, detail="知识点标签必须是列表")
    sub_tags = list(dict.fromkeys(str(tag).strip() for tag in sub_tags if str(tag).strip()))
    return version, grade, main_tag, sub_tags


def _validate_tag_group_against_framework(version, grade, main_tag, sub_tags):
    """校验单组标签是否合法（组合存在且子标签归属正确），合法则返回标准化标签组 dict。"""
    from database import SessionLocal
    from database.models import KnowledgeTagFramework
    validation_db = SessionLocal()
    try:
        rows = validation_db.query(KnowledgeTagFramework).filter(
            KnowledgeTagFramework.version == version,
            KnowledgeTagFramework.grade == grade,
            KnowledgeTagFramework.main_tag == main_tag,
        ).all()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"知识点标签框架数据库不可用: {e}")
    finally:
        validation_db.close()

    if not rows:
        raise HTTPException(status_code=400, detail="知识域、年级和章/单元组合不存在")
    valid_sub_tags = {row.sub_tag for row in rows}
    invalid_sub_tags = [tag for tag in sub_tags if tag not in valid_sub_tags]
    if invalid_sub_tags:
        raise HTTPException(
            status_code=400,
            detail=f"知识点标签不属于指定的知识域、年级和章/单元: {invalid_sub_tags}",
        )
    return {
        "version": version,   # 知识域
        "grade": grade,       # 年级
        "main_tag": main_tag, # 章/单元
        "sub_tags": sub_tags, # 知识点标签（隐性属性）
    }


def _validate_tag_group_lenient(version, grade, main_tag, sub_tags):
    """宽容校验标签组（学习路径用）：框架外标签允许保存，返回新标签信息.

    与 _validate_tag_group_against_framework 的区别：
    - 组合 (version/grade/main_tag) 不存在 → 不抛 400，标记为"新章/单元"
    - 子标签不在该组合下 → 不抛 400，收集为"新知识点标签"
    管理员人工保存的标签以管理员为准（宽容保存），框架外部分由智能体
    学习并提交审核提案，审核通过后补入正式框架。

    Returns:
        (group, new_main_tag, new_sub_tags)
        - group: 标准化标签组 dict（保留全部输入）
        - new_main_tag: True=章/单元组合不在正式框架（新章/单元）
        - new_sub_tags: 不在该组合下的子标签列表（新知识点标签）
    """
    from database import SessionLocal
    from database.models import KnowledgeTagFramework
    validation_db = SessionLocal()
    try:
        rows = validation_db.query(KnowledgeTagFramework).filter(
            KnowledgeTagFramework.version == version,
            KnowledgeTagFramework.grade == grade,
            KnowledgeTagFramework.main_tag == main_tag,
        ).all()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"知识点标签框架数据库不可用: {e}")
    finally:
        validation_db.close()

    if not rows:
        # 组合不存在：整个标签组视为新标签（新章/单元 + 全部子标签视为新）
        return (
            {
                "version": version,
                "grade": grade,
                "main_tag": main_tag,
                "sub_tags": sub_tags,
            },
            True,
            list(sub_tags),
        )
    valid_sub_tags = {row.sub_tag for row in rows}
    new_sub_tags = [tag for tag in sub_tags if tag not in valid_sub_tags]
    return (
        {
            "version": version,
            "grade": grade,
            "main_tag": main_tag,
            "sub_tags": sub_tags,
        },
        False,
        new_sub_tags,
    )


@app.post("/api/teachings/{task_id}/knowledge-tags")
async def update_knowledge_tags(task_id: str, payload: dict):
    """更新教学内容的知识点标签。

    允许反复修改，无次数限制。
    双标签组模式（向后兼容单组）：
    - 主标签组（必填）：payload.version(知识域)/grade(年级)/main_tag(章/单元)/sub_tags(知识点标签)。
    - 第二标签组（可选）：payload.second_tag = {version, grade, main_tag, sub_tags}。
      仅当第二标签组完整填写（含知识域/年级/章单元）时才持久化；否则视为清空第二标签。
    """
    confirmed = bool(payload.get("confirmed", False))
    # 学习路径标记：仅管理后台「编辑内容」保存时前端显式传 learn=true，
    # 普通用户侧（首页标签选择对话框）不传，不触发智能体学习/审核提案。
    learn = bool(payload.get("learn", False))

    # 主标签组（必填）
    p_version, p_grade, p_main_tag, p_sub_tags = _parse_tag_group_payload(payload)
    if not p_version or not p_grade or not p_main_tag:
        raise HTTPException(status_code=400, detail="知识域、年级和章/单元不能为空")
    # 宽容校验：框架外新标签允许保存，返回 (group, 是否新章/单元, 新知识点标签列表)
    primary_group, p_new_main, p_new_subs = _validate_tag_group_lenient(
        p_version, p_grade, p_main_tag, p_sub_tags,
    )

    # 第二标签组（可选）
    second_group = None
    s_new_main, s_new_subs = False, []
    raw_second = payload.get("second_tag")
    if raw_second and isinstance(raw_second, dict):
        s_version, s_grade, s_main_tag, s_sub_tags = _parse_tag_group_payload(raw_second)
        if s_version and s_grade and s_main_tag:
            second_group, s_new_main, s_new_subs = _validate_tag_group_lenient(
                s_version, s_grade, s_main_tag, s_sub_tags,
            )

    # 更新 metadata.json
    metadata_path = DATA_DIR / task_id / "metadata.json"
    try:
        if metadata_path.exists():
            with open(metadata_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        else:
            meta = {}

        # 学习路径：保存前快照旧标签（对比管理员更改）
        before_knowledge_tags = meta.get("knowledge_tags")
        before_second_tag = meta.get("second_tag")

        meta["knowledge_tags"] = primary_group
        meta["second_tag"] = second_group
        meta["needs_tag_selection"] = False
        meta["knowledge_tags_updated_at"] = datetime.utcnow().isoformat() + "Z"
        # 用户在前端确认保存后，标记为已确认（仅控制弹窗是否再次弹出，不限制编辑）
        if confirmed:
            meta["knowledge_tags_confirmed"] = True
        # 确保父目录存在（避免目录不存在导致写入失败）
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        # 原子写入 + 重试：并发场景（如重新生成动画的后台流水线同时写 metadata.json）
        # 会触发 Windows 文件锁（WinError 5 / Errno 13），瞬时锁通过重试即可恢复。
        _atomic_write_json(metadata_path, meta)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存标签失败: {e}")

    # 同步更新数据库中的 main_tag / sub_tags / second_tag（teachings 表）
    try:
        from database import SessionLocal
        db = SessionLocal()
        teaching = db.query(Teaching).filter(Teaching.task_id == task_id).first()
        if teaching:
            teaching.main_tag = primary_group["main_tag"]
            teaching.sub_tags = primary_group["sub_tags"]
            teaching.knowledge_tags = primary_group
            teaching.second_tag = second_group
            flag_modified(teaching, "sub_tags")
            flag_modified(teaching, "knowledge_tags")
            flag_modified(teaching, "second_tag")
            db.commit()
        db.close()
    except Exception as e:
        log(f"同步更新数据库标签失败（不影响 metadata）: {e}", "WARN")

    # ── 学习路径：管理员在「编辑内容」中保存标签 → 智能体学习 + 提交审核 ──
    learning = {"enabled": False, "learned": False, "proposals": 0, "new_tags": []}
    if learn:
        try:
            learning = _submit_teaching_tag_learning(
                task_id=task_id,
                before={"primary": before_knowledge_tags, "second": before_second_tag},
                after={"primary": primary_group, "second": second_group},
                new_tags={
                    "primary": {"new_main": p_new_main, "new_subs": p_new_subs},
                    "second": {"new_main": s_new_main, "new_subs": s_new_subs},
                },
            )
            learning["enabled"] = True
        except Exception as e:  # noqa: BLE001
            log(f"智能体学习路径执行失败（不影响标签保存）: {e}", "WARN")
            learning = {"enabled": True, "learned": False, "proposals": 0,
                        "new_tags": [], "error": f"{type(e).__name__}: {str(e)[:200]}"}

    # ── P1.5 标签修改学习：管理员改标签 → 自动提炼可泛化强关键词（后台异步，不阻塞保存）──
    if learn:
        try:
            import asyncio as _asyncio
            from tag_agent.learn_correction import schedule_label_learning
            _asyncio.create_task(schedule_label_learning(
                task_id=task_id,
                question_text=None,  # 内部按 task_id 查库取题干
                before={"primary": before_knowledge_tags, "second": before_second_tag},
                after={"primary": primary_group, "second": second_group},
                new_tags={
                    "primary": {"new_main": p_new_main, "new_subs": p_new_subs},
                    "second": {"new_main": s_new_main, "new_subs": s_new_subs},
                },
                admin_id="admin",
            ))
        except Exception as _e:  # noqa: BLE001
            log(f"P1.5 标签学习后台调度失败（不影响保存）: {_e}", "WARN")


    return {
        "success": True,
        "knowledge_tags": primary_group,
        "second_tag": second_group,
        "confirmed": confirmed,
        "learning": learning,
    }


def _submit_teaching_tag_learning(
    task_id: str,
    before: dict,
    after: dict,
    new_tags: dict,
    created_by: str = "admin",
) -> dict:
    """管理员在教学内容「编辑内容」保存标签后的智能体学习路径（同步实现）.

    触发时机：管理后台编辑内容弹窗保存标签（前端显式传 learn=true）。

    学习内容（闭环：管理员人工修正 → 智能体学习 → 审核 → 补入正式框架）：
    1. 管理员更改了标签（before != after）→ 写学习闭环记录
       TagLearningRecord(action_type="admin_correction")，记录 题目→标签
       的人工修正样本，供智能体后续识别参考。
    2. after 中不在正式框架的"新标签"（新章/单元或新知识点标签）→
       逐条创建 PendingTag(operation=add) 提案进入「标签智能体审核」队列，
       管理员在 tag_review.html 审核通过后（framework_sync 回写）
       补入正式标签框架 knowledge_tag_framework。

    全部异常仅告警，绝不影响标签保存主流程。

    Returns:
        {"learned": bool, "proposals": int, "new_tags": list[str]}
    """
    from database import SessionLocal
    from database.models import Teaching
    from tag_agent.models import PendingTag, TagLearningRecord

    # 规范化单组标签（主 / 第二），用于对比与记录
    def _norm(g):
        if not g or not isinstance(g, dict):
            return None
        return {
            "version": (g.get("version") or "").strip(),
            "grade": (g.get("grade") or "").strip(),
            "main_tag": (g.get("main_tag") or "").strip(),
            "sub_tags": sorted(
                str(s).strip() for s in (g.get("sub_tags") or []) if str(s).strip()
            ),
        }

    before_primary = _norm(before.get("primary"))
    before_second = _norm(before.get("second"))
    after_primary = _norm(after.get("primary"))
    after_second = _norm(after.get("second"))
    changed = (before_primary, before_second) != (after_primary, after_second)

    db = SessionLocal()
    try:
        # 同库探测：智能体四张表必须与业务库同库（不同库部署时跳过学习，仅告警）
        try:
            db.execute(text("SELECT 1 FROM tag_agent_pending_tags LIMIT 1")).fetchone()
        except Exception:
            raise RuntimeError("智能体审核表与业务库不同库或未建表，学习路径跳过")

        # 题目文本（提案依据）
        question_text = ""
        try:
            t = db.query(Teaching).filter(Teaching.task_id == task_id).first()
            if t:
                question_text = (t.question or "")[:200]
        except Exception:
            pass

        learned = False
        if changed:
            db.add(TagLearningRecord(
                action_type="admin_correction",
                question_id=task_id,
                domain=(after_primary or {}).get("version", ""),
                grade=(after_primary or {}).get("grade", ""),
                chapter=(after_primary or {}).get("main_tag", ""),
                tag_name=((after_primary or {}).get("sub_tags") or [""])[0],
                agent_data={
                    "source": "teaching_edit_save",
                    "before": {"primary": before_primary, "second": before_second},
                    "after": {"primary": after_primary, "second": after_second},
                },
                admin_data={
                    "admin_id": created_by,
                    "task_id": task_id,
                    "new_tags": new_tags,
                },
                note="管理员在「教学内容-编辑内容」保存了标签更改，智能体学习该人工修正（admin_correction）",
            ))
            learned = True

        # 去重查询：同 (operation, domain, grade, chapter, tag_name) 的待审 add 提案已存在则跳过
        def _existing_add(d, domain, grade, chapter, tag_name):
            return d.query(PendingTag).filter(
                PendingTag.operation == "add",
                PendingTag.status == "pending",
                PendingTag.domain == domain,
                PendingTag.grade == grade,
                PendingTag.chapter == chapter,
                PendingTag.tag_name == tag_name,
            ).first()

        # 收集新标签提案（主标签组 + 第二标签组）
        proposals = []
        new_tag_names = []
        seen = set()

        def _add_pending(d, domain, grade, chapter, tag_name, note, reason):
            key = (domain, grade, chapter, tag_name)
            if key in seen:
                return
            seen.add(key)
            if _existing_add(d, domain, grade, chapter, tag_name):
                return
            d.add(PendingTag(
                operation="add",
                domain=domain, grade=grade,
                chapter=chapter, tag_name=tag_name,
                keywords=[],
                evidence="管理员在「教学内容-编辑内容」人工保存的新标签"
                         "（学习路径自动提交，待审核）",
                source_question_id=task_id,
                source_question_text=question_text,
                created_by=created_by,
                status="pending",
                agent_reason=reason,
                confidence=1.0,
                temp_question_ids=[task_id],
            ))
            proposals.append(tag_name)

        for slot in ("primary", "second"):
            g = after_primary if slot == "primary" else after_second
            nt = new_tags.get(slot) or {}
            if not g:
                continue
            domain, grade, chapter = g["version"], g["grade"], g["main_tag"]
            if nt.get("new_main"):
                # 新章/单元：以章名作占位知识点标签提交 add 提案（审核通过后组合即存在）
                new_tag_names.append(f"{domain}/{grade}/{chapter}（新章/单元）")
                _add_pending(
                    db, domain, grade, chapter, chapter,
                    "新章/单元", "管理员人工选择该章/单元，智能体学习后提交审核；"
                    "通过后补入正式标签框架",
                )
            for sub in (nt.get("new_subs") or []):
                if not sub:
                    continue
                new_tag_names.append(sub)
                _add_pending(
                    db, domain, grade, chapter, sub,
                    "新知识点标签", "管理员人工选择该知识点标签，智能体学习后提交审核；"
                    "通过后补入正式标签框架",
                )

        if learned or proposals:
            db.commit()
        return {
            "learned": learned,
            "proposals": len(proposals),
            "new_tags": new_tag_names,
        }
    finally:
        db.close()


_TEACHING_TEMPLATE_PATH = Path(__file__).resolve().parent / "prompt" / "teaching_template.html"
_template_cache: tuple[float, str] | None = None


def _load_teaching_template() -> str:
    """加载并缓存 teaching_template.html，文件修改后自动刷新。"""
    global _template_cache
    if not _TEACHING_TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"模板文件不存在: {_TEACHING_TEMPLATE_PATH}")
    mtime = _TEACHING_TEMPLATE_PATH.stat().st_mtime
    if _template_cache and _template_cache[0] == mtime:
        return _template_cache[1]
    with open(_TEACHING_TEMPLATE_PATH, "r", encoding="utf-8") as f:
        content = f.read()
    _template_cache = (mtime, content)
    return content


def _compose_teaching_html(task_dir: Path) -> str | None:
    """从 teaching_data.json + 模板组合生成完整 HTML。返回 None 如果数据文件不存在。"""
    data_path = task_dir / "teaching_data.json"
    if not data_path.exists():
        return None
    with open(data_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    template = _load_teaching_template()
    html = template
    html = html.replace("__TITLE__", data.get("title", "数学互动教学"))
    # 题目原文：优先 teaching_data.json，旧记录回退 metadata.json，并做 HTML 转义
    question = data.get("question", "")
    if not question:
        try:
            meta_path = task_dir / "metadata.json"
            if meta_path.exists():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                question = meta.get("question") or meta.get("prompt") or ""
        except Exception:
            question = ""
    question = (
        (question or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
    html = html.replace("__QUESTION__", question)
    html = html.replace("__SUMMARY_TEXT__", data.get("summary", ""))
    html = html.replace("__DYNAMIC_SCENE_SVG__", data.get("scene_svg", ""))
    # 防御性转义：旧数据/未转义的 steps_json 若含 "</" 会提前闭合内联 <script>，
    # 导致 Alpine 初始化失败、右侧"完整解法"步骤面板不渲染
    steps_json = data.get("steps_json", "[]")
    steps_json = (
        steps_json.replace("</", "<\\/")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    html = html.replace("__STEPS_JSON__", steps_json)
    return html


def _normalize_legacy_teaching_html(html: str) -> str:
    """兜底读取的旧 teaching.html 仍可能引用外部 CDN（cdn.tailwindcss.com / jsdelivr / Google Fonts）。
    公网/国内网络下这些 CDN 不稳定会导致整页裸奔、公式变源码、交互失效。
    在返回前把外部依赖改写为本地化路径，与 teaching_template.html 现行引用保持一致。"""
    if not html:
        return html
    repl = [
        ('    <!-- Tailwind CSS -->\n    <script src="https://cdn.tailwindcss.com"></script>',
         '    <!-- Tailwind CSS（本地预编译） -->\n    <link rel="stylesheet" href="/vendor/teaching-tailwind.20260910.css">'),
        ('https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css',
         '/katex/katex.min.20260902b.css'),
        ('https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js',
         '/katex/katex.min.js?v=20260902'),
        ('https://cdn.jsdelivr.net/npm/alpinejs@3.13.3/dist/cdn.min.js',
         '/vendor/alpine.min.js?v=20260910'),
    ]
    for old, new in repl:
        if old in html:
            html = html.replace(old, new)
    # 移除 Google Fonts @import（改走系统字体栈，避免外部依赖）
    html = re.sub(r"\s*@import url\('https://fonts\.googleapis\.com[^']*'\);\s*\n", "", html)
    return html


@app.get("/api/teachings/{task_id}/html")
async def get_teaching_html(task_id: str, db: Session = Depends(get_db)):
    """
    获取指定任务的教学 HTML 内容（仅数据库中存在的任务）。
    优先从 teaching_data.json + 模板组合生成；向后兼容旧的 teaching.html 文件。
    """
    from fastapi.responses import Response
    from fastapi import HTTPException
    
    task_dir = DATA_DIR / task_id
    data_path = task_dir / "teaching_data.json"
    html_path = task_dir / "teaching.html"

    # 确定缓存 key 所用的文件路径和 mtime
    if data_path.exists():
        source_path = data_path
    elif html_path.exists():
        source_path = html_path
    else:
        source_path = None

    # 缓存失效依据：数据文件 + 模板文件的最新 mtime
    source_mtime = source_path.stat().st_mtime if source_path and source_path.exists() else 0
    template_mtime = _TEACHING_TEMPLATE_PATH.stat().st_mtime if source_path == data_path and _TEACHING_TEMPLATE_PATH.exists() else 0
    cache_mtime = max(source_mtime, template_mtime)

    # 检查缓存
    if task_id in _html_cache and source_path and source_path.exists():
        cached_data = _html_cache[task_id]
        if len(cached_data) == 3:
            cached_content, cached_time, is_compressed = cached_data
        else:
            cached_content, cached_time = cached_data
            is_compressed = True
        
        if cache_mtime <= cached_time:
            html_cache_hits_total.inc()
            headers = {}
            if is_compressed:
                headers["Content-Encoding"] = "gzip"
            return Response(
                content=cached_content,
                media_type="text/html",
                headers=headers
            )
        else:
            _html_cache.pop(task_id, None)
    
    # 仅当数据库存在记录时才对外提供
    exists = db.query(Teaching).filter(Teaching.task_id == task_id).first()
    if not exists:
        raise HTTPException(status_code=404, detail="Teaching not found")
    
    # 获取 HTML 内容：优先从 teaching_data.json 组合，兜底读 teaching.html
    html_content = _compose_teaching_html(task_dir)
    if html_content is None:
        if html_path.exists():
            with open(html_path, "r", encoding="utf-8") as f:
                html_content = f.read()
            # 旧文件可能仍带外部 CDN 引用，统一改写为本地路径（同现行模板）
            html_content = _normalize_legacy_teaching_html(html_content)
        else:
            raise HTTPException(status_code=404, detail="Teaching HTML not found")
    
    html_cache_misses_total.inc()

    # 压缩并缓存
    if len(html_content) > 1024:
        compressed = gzip.compress(html_content.encode('utf-8'))
        
        if len(_html_cache) >= _cache_max_size:
            _html_cache.pop(next(iter(_html_cache)))
        
        if _low_memory_mode and len(_html_cache) > _cache_max_size * 0.8:
            cache_items = list(_html_cache.items())
            items_to_keep = cache_items[-int(_cache_max_size * 0.5):]
            _html_cache.clear()
            for key, value in items_to_keep:
                _html_cache[key] = value
        
        _html_cache[task_id] = (compressed, cache_mtime, True)
        
        return Response(
            content=compressed,
            media_type="text/html",
            headers={"Content-Encoding": "gzip"}
        )
    else:
        if len(_html_cache) >= _cache_max_size:
            _html_cache.pop(next(iter(_html_cache)))
        
        if _low_memory_mode and len(_html_cache) > _cache_max_size * 0.8:
            cache_items = list(_html_cache.items())
            items_to_keep = cache_items[-int(_cache_max_size * 0.5):]
            _html_cache.clear()
            for key, value in items_to_keep:
                _html_cache[key] = value
        
        _html_cache[task_id] = (html_content, cache_mtime, False)
        
        return Response(content=html_content, media_type="text/html")


# 预览图 task_id 存在性缓存（2026-09-02）：首页 18+ 张卡片每张请求一次 preview，
# 每个请求此前都执行一次 SELECT Teaching —— 一个 worker 内同一 task_id 300s 只查 1 次 DB。
# 注意只缓存「存在性」不缓存文件内容：图片已由 Cache-Control 1y immutable 交给浏览器/CF。
_PREVIEW_TASK_CACHE_TTL: float = 300.0
_preview_task_exist_cache: dict = {}


@app.get("/api/teachings/{task_id}/preview")
async def get_teaching_preview(task_id: str, db: Session = Depends(get_db)):
    """获取指定任务的预览图片（仅数据库中存在的任务）。"""
    from fastapi import HTTPException
    from fastapi.responses import FileResponse

    # 进程内存在性缓存（TTL 300s），miss 时查 DB 并写入，消除同一任务重复 DB 往返。
    now = time.time()
    cached = _preview_task_exist_cache.get(task_id)
    if cached is None or (now - cached[1]) >= _PREVIEW_TASK_CACHE_TTL:
        _preview_task_exist_cache[task_id] = (
            db.query(Teaching).filter(Teaching.task_id == task_id).first() is not None,
            now,
        )
    if not _preview_task_exist_cache[task_id][0]:
        raise HTTPException(status_code=404, detail="Teaching not found")

    task_dir = DATA_DIR / task_id
    preview_candidates = [
        (task_dir / "Preview.webp", "image/webp"),
        (task_dir / "preview.webp", "image/webp"),
        (task_dir / "preview.png", "image/png"),
    ]

    preview_path = None
    media_type = None

    for candidate_path, candidate_media_type in preview_candidates:
        if candidate_path.exists():
            preview_path = candidate_path
            media_type = candidate_media_type
            break

    if not preview_path:
        raise HTTPException(status_code=404, detail="Preview image not found")

    # FileResponse 流式输出（替代 read_bytes 全量读内存），保留原缓存/ETag 语义
    return FileResponse(
        path=preview_path,
        media_type=media_type,
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",  # 缓存1年（图片不变）
            "ETag": f'"{task_id}-{preview_path.stat().st_mtime}"',  # 基于文件修改时间的ETag
        },
    )


# 并发生成任务信号量（2026-09-01）：限制同时执行的 LLM 生成流水线数，
# 防止"一次几百并行"打爆 LLM API 配额（429）与线程池（anyio 默认 40）。
# 超出并发数的任务在信号量处排队等待（有意的背压），不会失败、不会丢任务，
# 网页与任务进度轮询完全不受影响。默认 20，可用 MAX_CONCURRENT_PIPELINES 覆盖。
_MAX_CONCURRENT_PIPELINES = int(os.getenv("MAX_CONCURRENT_PIPELINES", "20"))
_pipeline_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_PIPELINES)


async def run_pipeline(task_id: str):
    task = tasks[task_id]
    pipeline_start_time = datetime.now()
    
    def update_progress(progress: int):
        """更新任务进度"""
        task.progress = progress
        _persist_task_state(task)
        log(f"任务 {task_id} 进度更新: {progress}%", "PROGRESS")
    
    try:
        log("=" * 60)
        log(f"开始执行任务流水线，任务ID: {task_id}", "TASK")
        task.status = "running"
        task.progress = 0
        _persist_task_state(task)
        
        # 更新监控指标
        tasks_total.labels(status="running").inc()
        tasks_running.inc()  # 增加运行中的任务数

        # 链路事件：流水线开始执行
        _record_pipeline_log(
            task_id, "INFO", "animation_generation",
            f"流水线开始执行",
            event=EVENT_TASK_STARTED,
            stage=STAGE_PIPELINE,
        )

        update_progress(5)  # 初始化完成
        await asyncio.sleep(0)

        # 测试模式：不创建文件夹，使用临时路径
        if is_test_mode():
            # 测试模式下，task_dir 可以是任意路径，pipeline 不会保存文件
            # 使用一个临时路径，但不会实际创建
            task_dir = Path("/tmp") / task_id
            log(f"测试模式：使用临时路径 {task_dir}（不会实际创建）", "TEST")
        else:
            # 生产模式：只有在 pipeline 成功生成 HTML 后才会创建最终的任务目录
            # 这里先使用一个临时路径，pipeline 会在成功时创建最终目录
            # 如果用户上传了文件，文件已经在临时目录中
            if task.input_file:
                # 文件在临时目录中，pipeline 成功后会移动到最终目录
                temp_dir = Path(task.input_file).parent
                log(f"文件在临时目录: {temp_dir}，pipeline 成功后会移动到最终目录")
                # 使用最终的任务目录路径（pipeline 会创建）
                task_dir = DATA_DIR / task_id
            else:
                # 如果没有文件，pipeline 会在成功时创建任务目录
                task_dir = DATA_DIR / task_id
                log(f"等待 pipeline 成功生成 HTML 后创建任务目录: {task_dir}")

        log(f"调用 pipeline.execute()，输入路径: {task.input_file or '无'}")
        # 信号量限流：同一时刻最多 _MAX_CONCURRENT_PIPELINES 个 LLM 生成流水线，
        # 超出的在此排队等待（背压），防止几百并行打爆 API 配额与线程池。
        async with _pipeline_semaphore:
            result = await get_pipeline().execute(
                input_path=task.input_file or "",
                prompt=task.prompt,
                task_dir=task_dir,
                user_id=task.user_id,
                progress_callback=update_progress,  # 传入进度回调
            )

        # 检查是否有错误（例如：输入不是数学题）。
        # 注意：HTML 生成失败也带 error（error_stage="html"），走下方"无有效输出"分支，此处仅处理输入校验类错误。
        if result.metadata.get("error") and result.metadata.get("error_stage") != "html":
            task.status = "failed"
            task.progress = 0
            task.error = result.metadata.get("error")
            task.metadata = result.metadata
            _persist_task_state(task)
            # 失败归因文案按真实阶段区分：预检判无解 ≠ 输入不是数学题，
            # 此前一律写"输入不是数学题"，预检误杀时排查会被带偏
            _fail_label = (
                "解题预检未通过"
                if result.metadata.get("error_stage") == "solvability"
                else "输入不是数学题"
            )
            _record_pipeline_log(
                task_id, "WARN", "animation_generation",
                f"未生成动画（{_fail_label}）: {task.error}",
                event=EVENT_TASK_FAILED,
                stage=STAGE_PIPELINE,
            )
            total_elapsed = (datetime.now() - pipeline_start_time).total_seconds()

            # 更新监控指标
            tasks_total.labels(status="failed").inc()
            tasks_running.dec()
            task_duration_seconds.labels(status="failed").observe(total_elapsed)

            log("=" * 60)
            log(f"任务 {task_id} 执行失败（{_fail_label}），总耗时: {total_elapsed:.2f} 秒", "WARN")
            log(f"错误信息: {task.error}", "WARN")
            log("=" * 60)
            
            # 清理临时文件（如果存在）
            if task.input_file and not is_test_mode():
                temp_path = Path(task.input_file)
                if temp_path.exists() and "temp_" in str(temp_path.parent):
                    try:
                        temp_dir = temp_path.parent
                        shutil.rmtree(temp_dir)
                        log(f"已清理临时目录: {temp_dir}", "CLEANUP")
                    except Exception as e:
                        log(f"清理临时目录失败: {e}", "WARN")
            return
        
        # 检查是否成功生成了教学 HTML
        if not result.metadata.get("teaching_html") or not result.metadata.get("teaching_html").strip():
            task.status = "failed"
            task.progress = 0
            task.error = "教学 HTML 生成失败"
            task.metadata = result.metadata
            _persist_task_state(task)
            fail_reason = (result.metadata.get("error") or "").strip()
            if len(fail_reason) > 300:
                fail_reason = fail_reason[:300] + "…"
            _record_pipeline_log(
                task_id, "ERROR", "animation_generation",
                f"教学 HTML 生成失败（无有效输出，未保存）{'，原因：' + fail_reason if fail_reason else ''}",
                event=EVENT_TASK_FAILED,
                stage=STAGE_PIPELINE,
            )
            total_elapsed = (datetime.now() - pipeline_start_time).total_seconds()
            
            # 更新监控指标
            tasks_total.labels(status="failed").inc()
            tasks_running.dec()
            task_duration_seconds.labels(status="failed").observe(total_elapsed)
            
            # HTML 生成失败时删除数据库中该任务的 Teaching 记录（若存在）。
            # 注意：仅限【首次创建】类任务（无存量内容可保留）；管理员"重新生成"
            # （preserve_on_failure=True）复用同一 task_id，失败时严禁删除已有记录，
            # 否则后续重识别/重生成封面/再次编辑全部 404"教学内容不存在"。
            if not task.preserve_on_failure:
                try:
                    _db = SessionLocal()
                    try:
                        teaching_row = _db.query(Teaching).filter(Teaching.task_id == task_id).first()
                        if teaching_row:
                            _db.delete(teaching_row)
                            _db.commit()
                            log(f"HTML 生成失败，已删除数据库中的 Teaching 记录: task_id={task_id}", "CLEANUP")
                    except Exception as e:
                        _db.rollback()
                        log(f"删除 Teaching 记录失败: {e}", "WARN")
                    finally:
                        _db.close()
                except Exception as e:
                    log(f"删除 Teaching 记录时出错: {e}", "WARN")
            
            log("=" * 60)
            log(f"任务 {task_id} 执行失败（教学 HTML 生成失败），总耗时: {total_elapsed:.2f} 秒", "WARN")
            log("=" * 60)
            
            # 清理临时文件（如果存在）
            if task.input_file and not is_test_mode():
                temp_path = Path(task.input_file)
                if temp_path.exists() and "temp_" in str(temp_path.parent):
                    try:
                        temp_dir = temp_path.parent
                        shutil.rmtree(temp_dir)
                        log(f"已清理临时目录: {temp_dir}", "CLEANUP")
                    except Exception as e:
                        log(f"清理临时目录失败: {e}", "WARN")
            return

        task.status = "completed"
        task.progress = 100
        task.video_url = result.video_url
        task.preview_image = result.preview_image
        task.metadata = result.metadata
        _persist_task_state(task)
        
        # 更新监控指标（稍后在 finally 中记录耗时）
        tasks_total.labels(status="completed").inc()
        
        # 保存到数据库
        try:
            db = SessionLocal()
            try:
                # 检查是否已存在
                existing_teaching = db.query(Teaching).filter(Teaching.task_id == task_id).first()
                
                # 从 metadata 中提取信息
                metadata = result.metadata
                tags = metadata.get("tags", {})
                main_tag = tags.get("main_tag") if tags else None
                sub_tags = tags.get("sub_tags", []) if tags else None
                knowledge_tags = metadata.get("knowledge_tags")  # 新标签体系
                
                if existing_teaching:
                    # 更新现有记录
                    existing_teaching.question = metadata.get("question", "")
                    existing_teaching.prompt = task.prompt
                    existing_teaching.title = metadata.get("title")
                    existing_teaching.is_math_problem = metadata.get("is_math_problem", True)
                    existing_teaching.main_tag = main_tag
                    existing_teaching.sub_tags = sub_tags
                    existing_teaching.reasoning = metadata.get("reasoning")
                    existing_teaching.input_file = metadata.get("input_file")
                    existing_teaching.teaching_html_file = "teaching_data.json" if (DATA_DIR / task_id / "teaching_data.json").exists() else "teaching.html"
                    # 同步知识点标签到数据库
                    if knowledge_tags:
                        existing_teaching.knowledge_tags = knowledge_tags
                        flag_modified(existing_teaching, "knowledge_tags")
                    flag_modified(existing_teaching, "sub_tags")
                    # 只在 preview_image 不为空时才更新（避免覆盖 _save_teaching_content 中已设置的预览图）
                    if result.preview_image:
                        existing_teaching.preview_image = result.preview_image
                    # 注意：生成时间（generated_at）只在【初次创建】时写入（见 else 分支），
                    # 此处为已存在记录的更新（管理员修改/重新生成等），严禁改写 generated_at，
                    # 以保证“创建时间”只记录初次创建时间，后期管理员修改不会被记录。
                    if task.user_id and not existing_teaching.user_id:
                        existing_teaching.user_id = task.user_id
                    if task.topic_id:
                        existing_teaching.topic_id = task.topic_id
                else:
                    # 创建新记录
                    new_teaching = Teaching(
                        task_id=task_id,
                        user_id=task.user_id,
                        question=metadata.get("question", ""),
                        prompt=task.prompt,
                        title=metadata.get("title"),
                        is_math_problem=metadata.get("is_math_problem", True),
                        main_tag=main_tag,
                        sub_tags=sub_tags,
                        reasoning=metadata.get("reasoning"),
                        generated_at=datetime.utcnow(),
                        input_file=metadata.get("input_file"),
                        teaching_html_file="teaching_data.json" if (DATA_DIR / task_id / "teaching_data.json").exists() else "teaching.html",
                        preview_image=result.preview_image if result.preview_image else None,
                        topic_id=task.topic_id,
                        knowledge_tags=knowledge_tags if knowledge_tags else None,
                    )
                    db.add(new_teaching)
                
                db.commit()
                log(f"教学内容已保存到数据库: {task_id}", "SUCCESS")

            except Exception as e:
                db.rollback()
                log(f"保存到数据库失败: {e}", "WARN")
            finally:
                db.close()
        except Exception as e:
            log(f"数据库连接失败: {e}", "WARN")
        
        total_elapsed = (datetime.now() - pipeline_start_time).total_seconds()

        # 写入同题复用映射（仅纯文本题目；不依赖数据库成功）。
        if task.status == "completed" and task.prompt and not task.input_file:
            prompt_hash = _set_task_reuse_mapping(task.prompt, task_id)
            if prompt_hash:
                log(
                    f"已写入同题复用映射: prompt_hash={prompt_hash}, task_id={task_id}",
                    "CACHE",
                )
        
        # 更新监控指标
        tasks_running.dec()
        task_duration_seconds.labels(status="completed").observe(total_elapsed)
        
        log("=" * 60)
        log(f"任务 {task_id} 执行成功，总耗时: {total_elapsed:.2f} 秒", "SUCCESS")
        log(f"生成的 HTML 长度: {len(result.metadata.get('teaching_html', ''))} 字符")
        log("=" * 60)

        # 记录动画生成成功日志（INFO），便于追溯每次正常生产的触发用户与上下文
        try:
            _title_snip = (result.metadata.get("title") or result.metadata.get("question") or "").strip()
            if len(_title_snip) > 40:
                _title_snip = _title_snip[:40] + "…"
            _succ_msg = f"动画生成成功（耗时 {round(total_elapsed, 2)} 秒）"
            if _title_snip:
                _succ_msg += f"｜{_title_snip}"
            _record_pipeline_log(
                task_id,
                "INFO",
                "animation_generation",
                _succ_msg,
                event=EVENT_TASK_COMPLETED,
                stage=STAGE_PIPELINE,
                context_extra={"duration_seconds": round(total_elapsed, 2)},
            )
        except Exception:
            pass

    except Exception as exc:  # pragma: no cover - 错误日志
        import traceback
        task.status = "failed"
        task.progress = 0
        task.error = str(exc)
        _persist_task_state(task)
        total_elapsed = (datetime.now() - pipeline_start_time).total_seconds()
        _record_pipeline_log(
            task_id,
            "ERROR",
            "animation_generation",
            f"动画生成任务执行异常: {exc}",
            event=EVENT_TASK_FAILED,
            stage=STAGE_PIPELINE,
            error_type=ERROR_TYPE_UNKNOWN,
            stack_trace="".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        )
        
        # 更新监控指标
        tasks_total.labels(status="failed").inc()
        tasks_running.dec()
        task_duration_seconds.labels(status="failed").observe(total_elapsed)
        
        # 异常导致 HTML 生成失败时，删除数据库中该任务的 Teaching 记录（若存在）。
        # 仅限【首次创建】类任务；管理员"重新生成"（preserve_on_failure=True）失败时保留记录。
        if not task.preserve_on_failure:
            try:
                _db = SessionLocal()
                try:
                    teaching_row = _db.query(Teaching).filter(Teaching.task_id == task_id).first()
                    if teaching_row:
                        _db.delete(teaching_row)
                        _db.commit()
                        log(f"任务执行异常，已删除数据库中的 Teaching 记录: task_id={task_id}", "CLEANUP")
                except Exception as e:
                    _db.rollback()
                    log(f"删除 Teaching 记录失败: {e}", "WARN")
                finally:
                    _db.close()
            except Exception as e:
                log(f"删除 Teaching 记录时出错: {e}", "WARN")
        
        log("=" * 60)
        log(f"任务 {task_id} 执行失败，总耗时: {total_elapsed:.2f} 秒", "ERROR")
        log(f"错误信息: {exc}", "ERROR")
        log("=" * 60)
        traceback.print_exc()
    finally:
        # 清理任务请求上下文，避免内存泄漏
        _task_request_context.pop(task_id, None)


# ==================== 用户认证 API ====================
# 【保留说明 / C1 结论：v1 auth 不得下线】
# v1 的 /api/auth/* 是当前部署前端的主认证面，强依赖、不可删：
#   - 会话校验普遍依赖 GET /api/auth/me（index.html ×2、user_interface.html ×3、share_topic.html、
#     video.html、js/ai-assistant.js 等）
#   - 用户登录走 POST /api/auth/login（web/js/auth.js）；管理后台登录走 /api/auth/login（admin/js/admin-api.js）
# v2 路由（invite_quota_api.py，前缀 /api/v2）仅承载邀请/额度/返佣，【没有】/api/v2/auth/me 镜像，
# 因此前端无法在不新增端点的前提下迁离 v1 auth。
# ⇒ 结论：v1 /api/auth/* 必须保留；邀请返利改造的 v2 端点与 auth 无关，不构成 v1 auth 的下线理由。
# 未来若需下线 v1 auth，路径为：①在 v2 路由补 /api/v2/auth/me 镜像；
#   ②将前端 /api/auth/me、/api/auth/login 等调用点迁到 v2；③确认无调用方后再废弃本段。

@app.post("/api/auth/register/password")
async def register_password(user_data: UserRegisterPassword, request: Request, db: Session = Depends(get_db)):
    """用户名密码注册"""
    return register_user_password(user_data, db, ip_address=_get_client_ip(request))

@app.post("/api/auth/register/phone")
async def register_phone(user_data: UserRegisterPhone, request: Request, db: Session = Depends(get_db)):
    """手机号验证码注册"""
    return register_user_phone(user_data, db, ip_address=_get_client_ip(request))

@app.post("/api/auth/send-code")
async def send_code(phone_data: SendVerificationCode, db: Session = Depends(get_db)):
    """发送验证码"""
    return send_verification_code(phone_data, db)

@app.post("/api/auth/login")
async def login(login_data: UserLogin, request: Request, db: Session = Depends(get_db)):
    """用户登录（用户名密码）"""
    return login_user(login_data, db, ip_address=_get_client_ip(request))

@app.post("/api/auth/login/phone")
async def login_phone(login_data: UserLoginPhone, request: Request, db: Session = Depends(get_db)):
    """手机号验证码登录"""
    return login_user_phone(login_data, db, ip_address=_get_client_ip(request))

@app.post("/api/auth/forgot-password")
async def forgot_password(forgot_data: ForgotPassword, db: Session = Depends(get_db)):
    """忘记密码 - 发送重置 token"""
    return forgot_password_request(forgot_data, db)

@app.post("/api/auth/reset-password")
async def reset_password_endpoint(reset_data: ResetPassword, db: Session = Depends(get_db)):
    """重置密码"""
    return reset_password(reset_data, db)

@app.get("/api/auth/me")
async def get_current_user_info(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    """获取当前用户信息"""
    if not credentials or not credentials.credentials:
        raise HTTPException(status_code=401, detail="未登录")
    token = credentials.credentials
    return get_user_by_token(token, db)


# 用户鉴权短缓存（2026-09-01）：_get_current_user 每请求查 users 表 1 次往返，
# 30s TTL 缓存缓解并发压力；对象经 db.expunge 分离后可跨请求安全复用。
# 注意：用户被删/封禁等变更最多延迟 30s 生效（可接受）。
_USER_CACHE_TTL = 30.0
_user_cache: dict = {}  # user_id -> (expire_ts, user)


def _get_current_user(credentials: HTTPAuthorizationCredentials, db: Session) -> User:
    if not credentials or not credentials.credentials:
        raise HTTPException(status_code=401, detail="未登录")
    user_id = verify_token(credentials.credentials)
    if not user_id:
        raise HTTPException(status_code=401, detail="无效的 token")
    _now = time.time()
    _cached = _user_cache.get(user_id)
    if _cached and _cached[0] > _now:
        return _cached[1]
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    try:
        db.expunge(user)  # 从 session 分离，允许跨请求安全复用
    except Exception:
        pass
    _user_cache[user_id] = (_now + _USER_CACHE_TTL, user)
    return user


class RechargeRequestCreate(BaseModel):
    amount: int = 0
    note: Optional[str] = None
    plan: Optional[str] = None  # 订阅套餐：monthly / quarterly / halfyear / yearly
    price: Optional[float] = None  # 客户端展示价，仅用于校验，不作为入账依据
    use_commission: bool = True  # 优先使用可用返利抵扣套餐价格


class RechargeOrderQuote(BaseModel):
    plan: str
    plan_name: str
    total_price: float
    total_price_fen: int
    commission_available: int
    commission_used: int
    cash_due: int
    duration_days: int


def _commission_quote(db: Session, user_id: str, total_price: float, use_commission: bool = True) -> Dict[str, int]:
    """按分计算返利抵扣，避免浮点金额造成少扣或多扣。

    可用口径与 _commission_summary（页面"可提现"）对齐：
    available = total_reward - frozen_amount - withdrawn_amount - pending_amount，
    冻结中（解冻期内）的佣金不得用于下单抵扣，防止超前消耗导致账目错位。
    """
    total_fen = max(0, int(round(total_price * 100)))
    account = db.query(CommissionAccount).filter(CommissionAccount.user_id == user_id).with_for_update().first()
    total = int(account.total_reward or 0) if account else 0
    withdrawn = int(account.withdrawn_amount or 0) if account else 0
    pending = int(account.pending_amount or 0) if account else 0
    frozen = int(account.frozen_amount or 0) if account else 0
    available = max(0, total - frozen - withdrawn - pending)
    used = min(available, total_fen) if use_commission else 0
    return {
        "commission_available": available,
        "commission_used": used,
        "cash_due": max(0, total_fen - used),
    }


@app.get("/api/recharge-orders/quote")
async def quote_recharge_order(
    plan: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    """返回套餐价格及当前用户返利抵扣、补差价金额。"""
    user = _get_current_user(credentials, db)
    plan = (plan or "").strip().lower()
    if plan not in PLAN_KEYS:
        raise HTTPException(status_code=400, detail="请选择月度、季度、半年或年度订阅套餐")
    price = _plan_price(_get_plan_config(db, plan))
    quote = _commission_quote(db, user.user_id, price)
    return {
        "success": True,
        "plan": plan,
        "plan_name": _plan_display_name(db, plan),
        "total_price": price,
        "total_price_fen": int(round(price * 100)),
        "duration_days": _plan_duration_days(db, plan),
        **quote,
    }


@app.get("/api/recharge-orders")
async def get_my_recharge_orders(
    page: int = 1,
    page_size: int = 20,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    """获取当前用户的充值订单记录，支持分页"""
    user = _get_current_user(credentials, db)
    base_query = db.query(RechargeRequest).filter(RechargeRequest.user_id == user.user_id)
    total = base_query.count()
    offset = (page - 1) * page_size
    requests = base_query.order_by(desc(RechargeRequest.created_at)).offset(offset).limit(page_size).all()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
        "data": [
            {
                "request_id": req.request_id,
                "amount": req.amount,
                "status": req.status,
                "note": req.note,
                "admin_note": req.admin_note,
                "processed_by": req.processed_by,
                "created_at": req.created_at.isoformat() + "Z",
                "processed_at": req.processed_at.isoformat() + "Z" if req.processed_at else None,
            }
            for req in requests
        ]
    }


@app.post("/api/recharge-orders")
async def create_recharge_order(
    payload: RechargeRequestCreate,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    """创建订阅订单；审核通过后只开通会员有效期，不增加额度。"""
    user = _get_current_user(credentials, db)
    plan = (payload.plan or "").strip().lower()
    if plan not in PLAN_KEYS:
        raise HTTPException(status_code=400, detail="请选择月度、季度、半年或年度订阅套餐")

    cfg = _get_plan_config(db, plan)
    price = _plan_price(cfg)
    if price <= 0:
        raise HTTPException(status_code=400, detail="当前套餐价格配置无效")
    if payload.price is not None and abs(float(payload.price) - price) > 0.01:
        raise HTTPException(status_code=400, detail="套餐价格已变动，请刷新页面后重新下单")

    quote = _commission_quote(db, user.user_id, price, payload.use_commission)
    account = db.query(CommissionAccount).filter(CommissionAccount.user_id == user.user_id).with_for_update().first()
    if quote["commission_used"] > 0:
        if not account:
            account = CommissionAccount(user_id=user.user_id)
            db.add(account)
            db.flush()
        account.pending_amount = int(account.pending_amount or 0) + quote["commission_used"]

    user_note = (payload.note or "").strip()
    # 首单/续费标识：当前无有效订阅=first（首单），有=renewal（续费）；审批时据此计算佣金档位
    from invite_quota_api import _get_user_subscription as _iq_get_user_subscription
    order_type = "renewal" if _iq_get_user_subscription(db, user.user_id) else "first"
    order_note = (
        f"[plan:{plan}][otype:{order_type}][commission:{quote['commission_used']}][cash:{quote['cash_due']}]"
        f"{_plan_display_name(db, plan)}，套餐价{price:g}元，返利抵扣{quote['commission_used'] / 100:.2f}元，补差价{quote['cash_due'] / 100:.2f}元"
    )
    if user_note:
        order_note += f"；{user_note}"

    request_id = str(uuid4())
    recharge_request = RechargeRequest(
        request_id=request_id,
        user_id=user.user_id,
        amount=0,
        status="pending",
        note=order_note,
        created_at=datetime.utcnow(),
    )
    db.add(recharge_request)
    db.commit()
    return {
        "success": True,
        "message": "订阅订单已创建，管理员确认后将开通会员有效期。",
        "request": {
            "request_id": request_id,
            "plan": plan,
            "plan_name": _plan_display_name(db, plan),
                "price": price,
                "duration_days": _plan_duration_days(db, plan),
            "status": "pending",
            "note": order_note,
            "created_at": recharge_request.created_at.isoformat() + "Z",
        },
    }


@app.get("/api/admin/recharge-orders")
async def admin_get_recharge_orders(
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """管理员获取充值订单列表"""
    query = db.query(RechargeRequest).options(joinedload(RechargeRequest.user))
    if status:
        query = query.filter(RechargeRequest.status == status)

    total = query.count()
    offset = (page - 1) * page_size
    requests = query.order_by(desc(RechargeRequest.created_at)).offset(offset).limit(page_size).all()

    result = []
    for req in requests:
        user = req.user  # 通过 joinedload 一次性加载，无额外查询
        result.append({
            "request_id": req.request_id,
            "user_id": req.user_id,
            "username": user.username if user else None,
            "phone": user.phone if user else None,
            "email": user.email if user else None,
            "amount": req.amount,
            "status": req.status,
            "note": req.note,
            "admin_note": req.admin_note,
            "processed_by": req.processed_by,
            "created_at": req.created_at.isoformat() + "Z",
            "processed_at": req.processed_at.isoformat() + "Z" if req.processed_at else None,
        })

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
        "data": result,
    }


class AdminRechargeProcess(BaseModel):
    action: str
    admin_note: Optional[str] = None


@app.put("/api/admin/recharge-orders/{request_id}")
async def admin_process_recharge_order(
    request_id: str,
    payload: AdminRechargeProcess,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """管理员确认充值订单"""
    # 使用 FOR UPDATE 行级锁 + 状态条件，防止并发重复审批
    req = db.query(RechargeRequest).filter(
        RechargeRequest.request_id == request_id,
        RechargeRequest.status == "pending"
    ).with_for_update().first()

    if not req:
        # 区分"不存在"还是"已处理"
        existing = db.query(RechargeRequest.request_id).filter(
            RechargeRequest.request_id == request_id
        ).first()
        if not existing:
            raise HTTPException(status_code=404, detail="充值订单不存在")
        raise HTTPException(status_code=400, detail="该订单已处理，无需重复操作")

    action = (payload.action or "").strip().lower()
    if action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="操作类型只能是 approve 或 reject")

    if action == "approve":
        plan = _extract_plan_from_note(req.note)
        if plan:
            # 订阅订单：审批通过后开通订阅（无限次使用），不走次数额度
            from invite_quota_api import _set_user_subscription, _get_user_subscription
            _set_user_subscription(db, req.user_id, plan)
            commission_used = _extract_commission_from_note(req.note)
            if commission_used:
                commission_account = db.query(CommissionAccount).filter(
                    CommissionAccount.user_id == req.user_id
                ).with_for_update().first()
                if not commission_account or int(commission_account.pending_amount or 0) < commission_used:
                    raise HTTPException(status_code=400, detail="订单返利抵扣状态异常，请联系管理员")
                commission_account.pending_amount = int(commission_account.pending_amount or 0) - commission_used
                commission_account.withdrawn_amount = int(commission_account.withdrawn_amount or 0) + commission_used
            # 首次订阅成交：标记该用户 paid_once=1（「已付费邀请人」佣金资格；续费不再重复标记）
            subscriber = db.query(User).filter(User.user_id == req.user_id).first()
            if subscriber:
                subscriber.paid_once = True
            # 单级返佣：仅直接邀请人拿固定佣金（活动总控/资格/首续费档位在函数内按配置判定）
            from invite_quota_api import _distribute_commission_on_subscription
            commission_granted = _distribute_commission_on_subscription(
                db,
                recharge_user_id=req.user_id,
                plan=plan,
                order_type=_extract_order_type_from_note(req.note),
                order_id=req.request_id,
            )
            req.status = "approved"
            sub = _get_user_subscription(db, req.user_id) or {}
            log(
                f"管理员 {admin_user.username} 为用户 {req.user_id} 开通订阅 {plan}，有效期至 {(sub.get('expire_at') or '')[:10]}",
                "ADMIN",
            )
        else:
            # 按次充值已彻底下线：无套餐标识的历史订单不再发放任何额度，仅归档为已处理
            req.status = "approved"
            req.admin_note = (req.admin_note or "") + "；按次充值已下线，订单不发放额度"
            commission_granted = []
            log(
                f"管理员 {admin_user.username} 处理无订阅套餐的旧订单 {req.request_id}：按次充值已下线，订单不生效",
                "ADMIN",
            )
    else:
        plan = _extract_plan_from_note(req.note)
        if plan:
            commission_used = _extract_commission_from_note(req.note)
            if commission_used:
                commission_account = db.query(CommissionAccount).filter(
                    CommissionAccount.user_id == req.user_id
                ).with_for_update().first()
                if commission_account:
                    _pending_now = int(commission_account.pending_amount or 0)
                    if _pending_now >= commission_used:
                        commission_account.pending_amount = _pending_now - commission_used
                    else:
                        # P1 修复（2026-09-11）：原 max(0, pending-X) 在账目已不一致时会把
                        # 其他冻结（提现/其他订单）静默解冻掉，侵蚀账本并导致后续订单
                        # 审批报「返利抵扣状态异常」。此处改为显式校验：冻结不足时
                        # 不动账、记 ERROR 供人工对账，拒绝流程照常继续（不卡管理员操作）。
                        log(
                            f"订单 {req.request_id} 拒绝时返利冻结异常：note 记录抵扣 "
                            f"{commission_used} 分，账户 pending_amount 仅 {_pending_now} 分，"
                            f"未做解冻，请人工对账（user_id={req.user_id}）",
                            "ERROR",
                        )
        req.status = "rejected"
        commission_granted = []

    req.admin_note = payload.admin_note
    req.processed_by = admin_user.username
    req.processed_at = datetime.utcnow()
    db.commit()

    log(
        f"管理员 {admin_user.username} {action} 了用户 {req.user_id} 的充值订单 {req.request_id}，数量 {req.amount}"
        + (f"，单级返佣发放 {len(commission_granted)} 笔" if commission_granted else ""),
        "ADMIN",
    )

    return {
        "success": True,
        "message": f"充值订单已{action}。",
        "request": {
            "request_id": req.request_id,
            "status": req.status,
            "amount": req.amount,
            "admin_note": req.admin_note,
            "processed_by": req.processed_by,
            "processed_at": req.processed_at.isoformat() + "Z",
        },
        "commission_granted": commission_granted,
    }

@app.post("/api/auth/bind-phone")
async def bind_user_phone(
    bind_data: BindPhone,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    """绑定手机号"""
    token = credentials.credentials
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="无效的 token")
    return bind_phone(user_id, bind_data, db)

@app.post("/api/auth/bind-email")
async def bind_user_email(
    bind_data: BindEmail,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    """绑定邮箱"""
    token = credentials.credentials
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="无效的 token")
    return bind_email(user_id, bind_data, db)

@app.post("/api/auth/update-profile")
async def update_user_profile(
    profile_data: UpdateProfile,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    """更新个人资料"""
    token = credentials.credentials
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="无效的 token")
    return update_profile(user_id, profile_data, db)

@app.post("/api/auth/change-password")
async def change_user_password(
    password_data: ChangePassword,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    """修改密码"""
    token = credentials.credentials
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="无效的 token")
    return change_password(user_id, password_data, db)

class UpdateDailyMaxCalls(BaseModel):
    """更新每日最大调用次数"""
    daily_max_calls: int

@app.post("/api/auth/update-daily-max-calls")
async def update_daily_max_calls_endpoint(
    update_data: UpdateDailyMaxCalls,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    """更新用户的每日最大调用次数（管理员功能）"""
    token = credentials.credentials
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="无效的 token")
    return update_user_daily_max_calls(user_id, update_data.daily_max_calls, db)

@app.post("/api/auth/favorite")
async def toggle_user_favorite(
    favorite_data: FavoriteAction,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    """添加或移除收藏"""
    token = credentials.credentials
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="无效的 token")
    return toggle_favorite(user_id, favorite_data, db)

@app.get("/api/auth/favorites")
async def get_user_favorites_list(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    """获取用户的收藏列表"""
    token = credentials.credentials
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="无效的 token")
    favorites = get_user_favorites(user_id, db)
    return {
        "success": True,
        "favorites": favorites
    }

@app.post("/api/user/view-history")
async def record_view_history(
    task_id: str = Form(...),
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    """记录用户浏览历史"""
    token = credentials.credentials
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="无效的 token")
    
    # 检查教学内容是否存在
    teaching = db.query(Teaching).filter(Teaching.task_id == task_id).first()
    if not teaching:
        raise HTTPException(status_code=404, detail="教学内容不存在")
    
    # 检查是否已有浏览记录（同一用户同一内容）
    existing_view = db.query(UserViewHistory).filter(
        UserViewHistory.user_id == user_id,
        UserViewHistory.task_id == task_id
    ).first()
    
    if existing_view:
        # 更新浏览时间和次数
        existing_view.viewed_at = datetime.utcnow()
        existing_view.view_count = (existing_view.view_count or 0) + 1
    else:
        # 创建新的浏览记录
        new_view = UserViewHistory(
            view_id=str(uuid4()),
            user_id=user_id,
            task_id=task_id,
            viewed_at=datetime.utcnow(),
            view_count=1
        )
        db.add(new_view)
    
    try:
        db.commit()
        return {"success": True, "message": "浏览记录已保存"}
    except Exception as e:
        db.rollback()
        log(f"保存浏览记录失败: {e}", "WARN")
        raise HTTPException(status_code=500, detail="保存浏览记录失败")

@app.get("/api/user/view-history")
async def get_user_view_history(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
    limit: int = 100
):
    """获取用户的浏览记录（最近30天）"""
    from datetime import timedelta

    if credentials is None or not credentials.credentials:
        # auto_error=False 时未携带 token 会得到 None，应返回 401 而非抛 500
        raise HTTPException(status_code=401, detail="无效的 token")

    token = credentials.credentials
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="无效的 token")
    
    # 获取最近30天的浏览记录
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    view_history = db.query(UserViewHistory).filter(
        UserViewHistory.user_id == user_id,
        UserViewHistory.viewed_at >= thirty_days_ago
    ).order_by(UserViewHistory.viewed_at.desc()).limit(limit).all()
    
    # 获取对应的教学内容信息
    result = []
    for view in view_history:
        teaching = db.query(Teaching).filter(Teaching.task_id == view.task_id).first()
        if teaching:
            result.append({
                "view_id": view.view_id,
                "task_id": view.task_id,
                "title": teaching.title or teaching.question[:50] if teaching.question else "无标题",
                "question": teaching.question,
                "viewed_at": (view.viewed_at.isoformat() + "Z") if view.viewed_at else None,
                "view_count": view.view_count,
                "preview_image": get_preview_image_name(DATA_DIR / teaching.task_id, teaching.preview_image),
                "preview_version": get_preview_version(DATA_DIR / teaching.task_id, teaching.preview_image),
                "main_tag": teaching.main_tag,
                "sub_tags": teaching.sub_tags
            })
    
    return {
        "success": True,
        "history": result,
        "total": len(result)
    }

@app.get("/api/teachings/{task_id}/download")
async def download_teaching(task_id: str):
    """下载教学内容的HTML文件"""
    from fastapi.responses import Response
    from fastapi import HTTPException
    
    task_dir = DATA_DIR / task_id
    html_path = task_dir / "teaching.html"
    
    if html_path.exists():
        with open(html_path, "r", encoding="utf-8") as f:
            html_content = f.read()
    else:
        html_content = _compose_teaching_html(task_dir)
        if html_content is None:
            raise HTTPException(status_code=404, detail="Teaching HTML not found")
    
    return Response(
        content=html_content,
        media_type="text/html",
        headers={"Content-Disposition": f'attachment; filename="teaching_{task_id}.html"'}
    )


class UpdateTeachingTitle(BaseModel):
    """更新教学内容标题"""
    title: str


@app.patch("/api/teachings/{task_id}")
async def update_teaching_title(
    task_id: str,
    body: UpdateTeachingTitle,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    """更新教学内容的标题。只能修改自己创建的内容。"""
    token = credentials.credentials if credentials else None
    user_id = verify_token(token) if token else None
    if not user_id:
        raise HTTPException(status_code=401, detail="请先登录")
    
    teaching = db.query(Teaching).filter(Teaching.task_id == task_id).first()
    if not teaching:
        raise HTTPException(status_code=404, detail="教学内容不存在")
    
    if teaching.user_id != user_id:
        raise HTTPException(status_code=403, detail="无权修改他人的教学内容")
    
    new_title = (body.title or "").strip()
    if not new_title:
        raise HTTPException(status_code=400, detail="标题不能为空")
    if len(new_title) > 100:
        raise HTTPException(status_code=400, detail="标题不能超过100个字符")
    
    teaching.title = new_title
    db.commit()
    
    return {"success": True, "title": teaching.title, "message": "标题已更新"}


@app.delete("/api/teachings/{task_id}")
async def delete_teaching(
    task_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    """删除教学内容。只能删除自己创建的内容。"""
    token = credentials.credentials if credentials else None
    user_id = verify_token(token) if token else None
    if not user_id:
        raise HTTPException(status_code=401, detail="请先登录")
    
    # 查找教学内容
    teaching = db.query(Teaching).filter(Teaching.task_id == task_id).first()
    if not teaching:
        raise HTTPException(status_code=404, detail="教学内容不存在")
    
    # 检查是否是当前用户创建的内容
    if teaching.user_id != user_id:
        raise HTTPException(status_code=403, detail="无权删除他人的教学内容")
    
    try:
        # 删除数据库记录（级联删除会自动处理关联的评论、点赞、收藏等）
        db.delete(teaching)
        db.commit()
        
        # 可选：删除storage中的文件（如果需要）
        # task_dir = DATA_DIR / task_id
        # if task_dir.exists():
        #     import shutil
        #     shutil.rmtree(task_dir)
        
        return {"success": True, "message": "删除成功"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")


# ==================== 评论和点赞 API ====================

class CommentCreate(BaseModel):
    """创建评论或回复"""
    task_id: str
    content: str
    parent_id: Optional[str] = None

class CommentResponse(BaseModel):
    """评论响应"""
    comment_id: str
    user_id: str
    username: str
    content: str
    created_at: str
    likes: int = 0
    is_liked: bool = False
    parent_id: Optional[str] = None
    replies: list = []
    can_delete: bool = False

class LikeAction(BaseModel):
    """点赞操作"""
    task_id: str
    comment_id: Optional[str] = None  # 如果为None，则点赞/取消点赞教学内容本身

@app.get("/api/teachings/{task_id}/comments")
async def get_comments(
    task_id: str,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db)
):
    """获取教学内容的评论列表。

    首次查看（尚无评论 / 教学记录尚未入库）时仍返回 200，
    默认空列表，避免前端因 404 反复报错。
    """
    # 检查教学内容是否存在：不存在时返回空评论（默认值），HTTP 200
    teaching = db.query(Teaching).filter(Teaching.task_id == task_id).first()
    if not teaching:
        return {"comments": []}

    # 获取评论列表（无评论时自然为空列表）
    comments = db.query(Comment).filter(Comment.task_id == task_id).order_by(Comment.created_at.desc()).all()

    # 获取当前用户ID（如果已登录）
    user_id = None
    if credentials:
        try:
            token = credentials.credentials
            user_id = verify_token(token)
        except Exception:
            pass

    from config import is_admin
    current_user = db.query(User).filter(User.user_id == user_id).first() if user_id else None
    admin = bool(current_user and is_admin(current_user.username))

    def serialize(comment):
        is_liked = bool(user_id and db.query(CommentLike).filter(
            and_(CommentLike.comment_id == comment.comment_id, CommentLike.user_id == user_id)
        ).first())
        return {
            "comment_id": comment.comment_id,
            "user_id": comment.user_id,
            "username": comment.username or "",
            "content": comment.content or "",
            "created_at": (comment.created_at.isoformat() + "Z") if comment.created_at else "",
            "likes": int(comment.likes or 0),
            "is_liked": is_liked,
            "parent_id": comment.parent_id,
            "can_delete": bool(user_id and (comment.user_id == user_id or admin)),
            "replies": [serialize(reply) for reply in sorted(comment.replies, key=lambda item: item.created_at or datetime.min)]
        }

    return {"comments": [serialize(comment) for comment in comments if comment.parent_id is None]}

@app.post("/api/teachings/{task_id}/comments")
async def create_comment(
    task_id: str,
    comment_data: CommentCreate,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    """创建评论"""
    if not credentials:
        raise HTTPException(status_code=401, detail="需要登录")
    
    token = credentials.credentials
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="无效的 token")
    
    # 检查教学内容是否存在
    teaching = db.query(Teaching).filter(Teaching.task_id == task_id).first()
    if not teaching:
        raise HTTPException(status_code=404, detail="Teaching not found")
    
    # 获取用户名
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    username = user.username
    content = comment_data.content.strip()
    if not content or len(content) > 1000:
        raise HTTPException(status_code=400, detail="评论内容不能为空且不能超过1000字")

    parent_id = comment_data.parent_id
    recipient_id = teaching.user_id  # 默认：直接评论案例，通知案例作者
    if parent_id:
        parent = db.query(Comment).filter(
            Comment.comment_id == parent_id,
            Comment.task_id == task_id
        ).first()
        if not parent:
            raise HTTPException(status_code=404, detail="回复目标不存在")
        if parent.parent_id:
            parent_id = parent.parent_id
        recipient_id = parent.user_id  # 回复：通知被回复评论的作者

    # 创建新评论（likes 默认 0）
    comment_id = str(uuid4())
    new_comment = Comment(
        comment_id=comment_id,
        task_id=task_id,
        user_id=user_id,
        username=username,
        content=content,
        created_at=datetime.utcnow(),
        likes=0,
        parent_id=parent_id
    )
    db.add(new_comment)
    db.commit()
    db.refresh(new_comment)

    # 互动通知：评论/回复通知对方（非本人）
    if recipient_id and recipient_id != user_id:
        action = "回复了你的评论" if comment_data.parent_id else "评论了你的案例"
        _notify_interaction(
            db, recipient_id, user_id, action, task_id,
            extra={"comment_id": comment_id},
        )

    return {
        "success": True,
        "comment": {
            "comment_id": new_comment.comment_id,
            "user_id": new_comment.user_id,
            "username": new_comment.username or "",
            "content": new_comment.content or "",
            "created_at": (new_comment.created_at.isoformat() + "Z") if new_comment.created_at else "",
            "likes": int(new_comment.likes or 0),
            "is_liked": False,
            "parent_id": new_comment.parent_id,
            "replies": [],
            "can_delete": True
        }
    }

@app.delete("/api/teachings/{task_id}/comments/{comment_id}")
async def delete_comment(
    task_id: str,
    comment_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    if not credentials:
        raise HTTPException(status_code=401, detail="需要登录")
    user_id = verify_token(credentials.credentials)
    if not user_id:
        raise HTTPException(status_code=401, detail="无效的 token")
    comment = db.query(Comment).filter(
        Comment.comment_id == comment_id,
        Comment.task_id == task_id
    ).first()
    if not comment:
        raise HTTPException(status_code=404, detail="评论不存在")
    user = db.query(User).filter(User.user_id == user_id).first()
    from config import is_admin
    if not user or (comment.user_id != user_id and not is_admin(user.username)):
        raise HTTPException(status_code=403, detail="只有评论作者或管理员可以删除")
    db.delete(comment)
    db.commit()
    return {"success": True}

@app.post("/api/teachings/{task_id}/like")
async def toggle_like(
    task_id: str,
    like_data: LikeAction,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    """点赞/取消点赞（教学内容或评论）"""
    if not credentials:
        raise HTTPException(status_code=401, detail="需要登录")
    
    token = credentials.credentials
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="无效的 token")
    
    # 检查教学内容是否存在
    teaching = db.query(Teaching).filter(Teaching.task_id == task_id).first()
    if not teaching:
        raise HTTPException(status_code=404, detail="Teaching not found")
    
    if like_data.comment_id:
        # 点赞评论
        comment = db.query(Comment).filter(
            Comment.comment_id == like_data.comment_id,
            Comment.task_id == task_id
        ).first()
        if not comment:
            raise HTTPException(status_code=404, detail="Comment not found")
        
        # 检查是否已点赞
        existing_like = db.query(CommentLike).filter(
            and_(CommentLike.comment_id == like_data.comment_id, CommentLike.user_id == user_id)
        ).first()
        
        current_likes = int(comment.likes or 0)
        if existing_like:
            # 取消点赞
            db.delete(existing_like)
            comment.likes = max(0, current_likes - 1)
            is_liked = False
        else:
            # 点赞
            new_like = CommentLike(comment_id=like_data.comment_id, user_id=user_id)
            db.add(new_like)
            comment.likes = current_likes + 1
            is_liked = True

        db.commit()
        # 互动通知：被点赞者收到提醒（仅点赞、且非本人）
        if is_liked and comment.user_id != user_id:
            _notify_interaction(
                db, comment.user_id, user_id, "赞了你的评论", task_id,
                extra={"comment_id": like_data.comment_id},
            )
        return {"success": True, "is_liked": bool(is_liked), "likes": int(comment.likes or 0)}
    else:
        # 点赞教学内容本身
        existing_like = db.query(TeachingLike).filter(
            and_(TeachingLike.task_id == task_id, TeachingLike.user_id == user_id)
        ).first()

        if existing_like:
            # 取消点赞
            db.delete(existing_like)
            is_liked = False
        else:
            # 点赞
            new_like = TeachingLike(task_id=task_id, user_id=user_id)
            db.add(new_like)
            is_liked = True

        db.commit()
        # 互动通知：案例作者收到提醒（仅点赞、且非本人）
        if is_liked and teaching.user_id != user_id:
            _notify_interaction(db, teaching.user_id, user_id, "赞了你的案例", task_id)
        
        # 获取点赞总数（无记录时为 0）
        likes_count = db.query(TeachingLike).filter(TeachingLike.task_id == task_id).count() or 0
        
        return {"success": True, "is_liked": bool(is_liked), "likes": int(likes_count)}

@app.get("/api/teachings/{task_id}/like-status")
async def get_like_status(
    task_id: str,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db)
):
    """获取点赞状态。

    首次查看（尚无点赞 / 教学记录尚未入库）时仍返回 200，
    默认 likes=0、is_liked=false。
    """
    # 教学内容不存在：返回空默认值，HTTP 200（避免首次打开报 404）
    teaching = db.query(Teaching).filter(Teaching.task_id == task_id).first()
    if not teaching:
        return {
            "likes": 0,
            "is_liked": False,
        }

    is_liked = False
    if credentials:
        try:
            token = credentials.credentials
            user_id = verify_token(token)
            if user_id:
                existing_like = db.query(TeachingLike).filter(
                    and_(TeachingLike.task_id == task_id, TeachingLike.user_id == user_id)
                ).first()
                is_liked = existing_like is not None
        except Exception:
            pass

    # 获取点赞总数（无记录时 count 为 0）
    likes_count = db.query(TeachingLike).filter(TeachingLike.task_id == task_id).count() or 0

    return {
        "likes": int(likes_count),
        "is_liked": bool(is_liked),
    }


# ==================== 管理后台 API ====================

@app.get("/api/admin/check")
async def check_admin(
    user: User = Depends(get_admin_current_user)
):
    """检查当前用户是否为管理员"""
    from config import is_admin
    return {
        "is_admin": is_admin(user.username),
        "username": user.username
    }


@app.get("/api/admin/teachings")
async def admin_get_teachings(
    page: int = 1,
    page_size: int = 20,
    search: Optional[str] = None,
    user_id: Optional[str] = None,
    main_tag: Optional[str] = None,
    version: Optional[str] = None,
    grade: Optional[str] = None,
    sort_by: str = "generated_at",
    sort_order: str = "desc",
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """获取所有教学内容列表（管理员）"""
    # 构建查询
    query = db.query(Teaching)

    # 搜索过滤
    if search:
        query = query.filter(
            or_(
                Teaching.title.contains(search),
                Teaching.question.contains(search)
            )
        )

    # 用户过滤
    if user_id:
        query = query.filter(Teaching.user_id == user_id)

    # 标签过滤
    if main_tag:
        query = query.filter(Teaching.main_tag == main_tag)

    # 知识域和年级过滤（单标签组：knowledge_tags.version 为知识域）
    if version or grade:
        all_teachings = query.all()
        filtered = []
        for t in all_teachings:
            kt = t.knowledge_tags
            if not isinstance(kt, dict):
                continue
            v_match = (not version) or (kt.get('version') == version)
            g_match = (not grade) or (kt.get('grade') == grade)
            if v_match and g_match:
                filtered.append(t)
        # 排序
        reverse = (sort_order == "desc")
        if sort_by == "view_count":
            filtered.sort(key=lambda x: x.view_count or 0, reverse=reverse)
        elif sort_by == "title":
            filtered.sort(key=lambda x: x.title or '', reverse=reverse)
        else:
            filtered.sort(key=lambda x: x.generated_at or datetime.min, reverse=reverse)
        total = len(filtered)
        offset = (page - 1) * page_size
        teachings = filtered[offset:offset + page_size]
    else:
        # 排序
        if sort_by == "generated_at":
            order_column = Teaching.generated_at
        elif sort_by == "view_count":
            order_column = Teaching.view_count
        elif sort_by == "title":
            order_column = Teaching.title
        else:
            order_column = Teaching.generated_at
        if sort_order == "desc":
            query = query.order_by(desc(order_column))
        else:
            query = query.order_by(order_column)
        total = query.count()
        offset = (page - 1) * page_size
        teachings = query.offset(offset).limit(page_size).all()
    
    # 获取用户信息
    user_map = {}
    if teachings:
        user_ids = [t.user_id for t in teachings if t.user_id]
        if user_ids:
            users = db.query(User).filter(User.user_id.in_(user_ids)).all()
            user_map = {u.user_id: u.username for u in users}

    # 一次聚合本页所有记录的点赞数（替代原来的 N+1 逐条 COUNT）
    like_map = {}
    if teachings:
        like_rows = db.execute(
            text(
                "SELECT task_id, COUNT(*) AS c FROM teaching_likes "
                "WHERE task_id IN :task_ids GROUP BY task_id"
            ),
            {'task_ids': [t.task_id for t in teachings]}
        ).fetchall()
        like_map = {row[0]: row[1] for row in like_rows}

    # 格式化返回数据
    result = []
    for teaching in teachings:
        # 获取点赞数
        likes_count = like_map.get(teaching.task_id, 0)
        task_dir = DATA_DIR / teaching.task_id
        # 完整性检测：与详情页 ensure-complete 共用 _compute_teaching_defects（同口径）
        defect_list = _compute_teaching_defects(task_dir, teaching)
        error_reasons = [d["reason"] for d in defect_list]
        preview_exists = not any(d["asset"] == "cover" for d in defect_list)
        
        result.append({
            "task_id": teaching.task_id,
            "user_id": teaching.user_id,
            "username": user_map.get(teaching.user_id, "匿名用户"),
            "question": teaching.question,
            "title": teaching.title,
            "main_tag": teaching.main_tag,
            "sub_tags": teaching.sub_tags,
            "knowledge_tags": teaching.knowledge_tags,
            "second_knowledge_tag": _read_second_tag(teaching.task_id, teaching),
            "generated_at": (teaching.generated_at.isoformat() + "Z") if teaching.generated_at else None,
            "view_count": teaching.view_count,
            "likes_count": likes_count,
            "has_pic": teaching.has_pic,
            "preview_image": teaching.preview_image,
            "preview_version": get_preview_version(task_dir, teaching.preview_image) if preview_exists else None,
            "is_pinned": bool(teaching.is_pinned),
            "has_error": len(error_reasons) > 0,
            "error_reason": "；".join(error_reasons) if error_reasons else None
        })
    
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
        "data": result
    }


class TeachingPinRequest(BaseModel):
    pinned: bool


class TeachingPinLimitRequest(BaseModel):
    limit: int


@app.get("/api/teachings/pinned", response_model=List[TeachingItem])
async def list_pinned_teachings(db: Session = Depends(get_db)):
    teachings = db.query(
        Teaching,
        func.count(TeachingLikeModel.task_id).label('likes_count')
    ).outerjoin(
        TeachingLikeModel, Teaching.task_id == TeachingLikeModel.task_id
    ).filter(
        Teaching.is_pinned.is_(True)
    ).group_by(Teaching.task_id).order_by(
        Teaching.generated_at.desc()
    ).all()

    teaching_list = []
    for teaching, likes_count in teachings:
        task_dir = DATA_DIR / teaching.task_id
        teaching_html_path = task_dir / (teaching.teaching_html_file or "teaching.html")
        if not teaching_html_path.exists():
            continue

        title = teaching.title or ""
        if not title:
            question = teaching.question or ""
            title = question[:30] + "..." if len(question) > 30 else question
        if not title:
            title = "数学问题讲解"

        knowledge_tags = _read_knowledge_tags(teaching.task_id, teaching)
        tags = _build_legacy_tags(knowledge_tags, teaching)
        preview_image = teaching.preview_image or (
            "Preview.webp" if (task_dir / "Preview.webp").exists() else (
                "preview.webp" if (task_dir / "preview.webp").exists() else (
                    "preview.png" if (task_dir / "preview.png").exists() else None
                )
            )
        )
        has_preview_image = check_preview_image_exists(task_dir, preview_image)

        teaching_list.append(TeachingItem(
            task_id=teaching.task_id,
            question=teaching.question or "",
            title=title,
            generated_at=(teaching.generated_at.isoformat() + "Z") if teaching.generated_at else "",
            preview=None,
            preview_image=preview_image if has_preview_image else None,
            preview_version=get_preview_version(task_dir, preview_image) if has_preview_image else None,
            tags=tags,
            likes_count=likes_count or 0,
            knowledge_tags=knowledge_tags,
            second_knowledge_tag=_read_second_tag(teaching.task_id, teaching),
            is_pinned=bool(teaching.is_pinned),
        ))

    return teaching_list


@app.get("/api/admin/teachings/pins")
async def admin_get_teaching_pins(
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    teachings = db.query(Teaching).filter(Teaching.is_pinned.is_(True)).order_by(desc(Teaching.generated_at)).all()
    return {
        "limit": _get_teaching_pin_limit(db),
        "count": len(teachings),
        "data": [{"task_id": t.task_id, "title": t.title or "无标题", "generated_at": (t.generated_at.isoformat() + "Z") if t.generated_at else None} for t in teachings]
    }


@app.put("/api/admin/teachings/pin-limit")
async def admin_update_teaching_pin_limit(
    body: TeachingPinLimitRequest,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    if body.limit < _TEACHING_PIN_LIMIT_DEFAULT:
        raise HTTPException(status_code=400, detail="最多置顶数量不能少于5个")
    pinned_count = db.query(Teaching).filter(Teaching.is_pinned.is_(True)).count()
    if body.limit < pinned_count:
        raise HTTPException(status_code=400, detail=f"当前已置顶{pinned_count}个，数量上限不能低于已置顶数量")
    row = db.query(SystemConfig).filter(SystemConfig.config_key == _TEACHING_PIN_LIMIT_KEY).first()
    if row:
        row.config_value = str(body.limit)
    else:
        db.add(SystemConfig(config_key=_TEACHING_PIN_LIMIT_KEY, config_value=str(body.limit), description="教学内容首页轮播最大置顶数量"))
    db.commit()
    return {"success": True, "limit": body.limit, "count": pinned_count}


@app.post("/api/admin/teachings/{task_id}/pin")
async def admin_toggle_teaching_pin(
    task_id: str,
    body: TeachingPinRequest,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    teaching = db.query(Teaching).filter(Teaching.task_id == task_id).first()
    if not teaching:
        raise HTTPException(status_code=404, detail="教学内容不存在")
    was_pinned = bool(teaching.is_pinned)
    pinned_count = db.query(Teaching).filter(Teaching.is_pinned.is_(True)).count()
    limit = _get_teaching_pin_limit(db)
    if body.pinned and not was_pinned and pinned_count >= limit:
        raise HTTPException(status_code=400, detail=f"最多只能置顶{limit}个教学内容")
    teaching.is_pinned = body.pinned
    db.commit()
    _invalidate_teachings_cache()
    return {"success": True, "task_id": task_id, "is_pinned": bool(teaching.is_pinned), "count": pinned_count + (1 if body.pinned and not was_pinned else -1 if was_pinned and not body.pinned else 0)}


@app.get("/api/admin/teachings/{task_id}")
async def admin_get_teaching_detail(
    task_id: str,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """获取单个教学内容详情（管理员）"""
    teaching = db.query(Teaching).filter(Teaching.task_id == task_id).first()
    if not teaching:
        raise HTTPException(status_code=404, detail="教学内容不存在")
    
    # 获取用户信息
    username = "匿名用户"
    if teaching.user_id:
        user = db.query(User).filter(User.user_id == teaching.user_id).first()
        if user:
            username = user.username
    
    # 获取点赞数
    likes_count = db.query(TeachingLike).filter(TeachingLike.task_id == task_id).count()
    
    # 获取评论数
    comments_count = db.query(Comment).filter(Comment.task_id == task_id).count()
    
    return {
        "task_id": teaching.task_id,
        "user_id": teaching.user_id,
        "username": username,
        "question": teaching.question,
        "prompt": teaching.prompt,
        "title": teaching.title,
        "main_tag": teaching.main_tag,
        "sub_tags": teaching.sub_tags,
        "reasoning": teaching.reasoning,
        "generated_at": (teaching.generated_at.isoformat() + "Z") if teaching.generated_at else None,
        "view_count": teaching.view_count,
        "likes_count": likes_count,
        "comments_count": comments_count,
        "has_pic": teaching.has_pic,
        "is_math_problem": teaching.is_math_problem,
        "input_file": teaching.input_file,
        "teaching_html_file": teaching.teaching_html_file,
        "preview_image": get_preview_image_name(DATA_DIR / task_id, teaching.preview_image),
        "preview_version": get_preview_version(DATA_DIR / task_id, teaching.preview_image),
    }


class AdminUpdateTeachingRequest(BaseModel):
    """管理员更新教学内容的标题与题目内容（绕过所有权校验）。"""
    title: Optional[str] = None
    question: Optional[str] = None


class AdminRegenerateRequest(BaseModel):
    """管理员基于编辑后的题目内容（可附带纠错信息）重新生成动画/解题过程。"""
    question: str
    title: Optional[str] = None
    error_feedback: Optional[str] = None
    target: str = "both"  # animation | solution | both


@app.put("/api/admin/teachings/{task_id}")
async def admin_update_teaching(
    task_id: str,
    body: AdminUpdateTeachingRequest,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """管理员更新教学内容的标题与题目（绕过普通用户的所有权校验）。"""
    teaching = db.query(Teaching).filter(Teaching.task_id == task_id).first()
    if not teaching:
        raise HTTPException(status_code=404, detail="教学内容不存在")

    changed = False
    if body.title is not None:
        t = body.title.strip()
        if t:
            if len(t) > 100:
                raise HTTPException(status_code=400, detail="标题不能超过100个字符")
            teaching.title = t
            changed = True
    if body.question is not None:
        q = body.question.strip()
        if q:
            teaching.question = q
            teaching.prompt = q
            changed = True

    if changed:
        db.commit()
        # 同步更新本地 metadata.json（如存在），保证存储与数据库一致
        try:
            meta_path = DATA_DIR / task_id / "metadata.json"
            if meta_path.exists():
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                if body.title is not None and body.title.strip():
                    meta["title"] = body.title.strip()
                if body.question is not None and body.question.strip():
                    meta["question"] = body.question.strip()
                    meta["prompt"] = body.question.strip()
                _atomic_write_json(meta_path, meta)
        except Exception as e:
            log(f"同步 metadata.json 失败（忽略）: {e}", "WARN")

    return {"success": True, "title": teaching.title, "question": teaching.question}


@app.post("/api/admin/teachings/{task_id}/regenerate")
async def admin_regenerate_teaching(
    task_id: str,
    body: AdminRegenerateRequest,
    background_tasks: BackgroundTasks,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """管理员调用与首页相同的生成流水线（动画生成模型），以弹窗内编辑后的题目内容为输入，
    原地重新生成该教学内容的动画（teaching.html）与解题过程。

    - question: 弹窗内编辑后的题目内容（必填）
    - error_feedback: 手动填写的纠错信息，拼接进 prompt 引导模型直接修正
    - target: animation / solution / both（当前流水线一次性生成动画与解题步骤）
    """
    teaching = db.query(Teaching).filter(Teaching.task_id == task_id).first()
    if not teaching:
        raise HTTPException(status_code=404, detail="教学内容不存在")

    question = (body.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="题目内容不能为空")

    # 纠错信息拼接到生成用的 prompt；持久化的 question/prompt 保持干净（不含纠错提示）
    prompt = question
    if body.error_feedback and body.error_feedback.strip():
        prompt = question + "\n\n【纠错要求】\n" + body.error_feedback.strip()

    teaching.question = question
    teaching.prompt = prompt
    if body.title and body.title.strip():
        teaching.title = body.title.strip()[:100]
    db.commit()

    # 同步 metadata.json（question 保持干净，不含纠错提示）
    try:
        meta_path = DATA_DIR / task_id / "metadata.json"
        if meta_path.exists():
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            meta["question"] = question
            meta["prompt"] = question
            if body.title and body.title.strip():
                meta["title"] = body.title.strip()
            _atomic_write_json(meta_path, meta)
    except Exception as e:
        log(f"同步 metadata.json 失败（忽略）: {e}", "WARN")

    # 复用首页同款生成流水线，原地重新生成（动画与解题过程均包含在 teaching.html 中）。
    # preserve_on_failure=True：流水线失败时保留已有 Teaching 记录与旧文件，
    # 避免"重新生成失败 → 记录被删 → 后续操作报 题目不存在"。
    tasks[task_id] = Task(
        task_id=task_id,
        input_file=teaching.input_file or None,
        prompt=prompt,
        user_id=teaching.user_id,
        topic_id=teaching.topic_id,
        preserve_on_failure=True,
    )
    _persist_task_state(tasks[task_id])
    background_tasks.add_task(run_pipeline, task_id)

    return {"success": True, "task_id": task_id, "status": "running", "target": body.target}


async def run_cover_regeneration(task_id: str):
    """后台任务：调用封面生成模型（与首页流水线同款）强制重新生成 Preview.webp。"""
    task = tasks.get(task_id)
    if not task:
        return
    task.status = "running"
    task.progress = 5
    _persist_task_state(task)
    log(f"开始重新生成封面，任务ID: {task_id}", "TASK")
    try:
        task_dir = DATA_DIR / task_id
        # 生成输入优先读取 metadata.json；缺失字段从数据库兜底
        metadata = {}
        meta_path = task_dir / "metadata.json"
        if meta_path.exists():
            with open(meta_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)
        if not metadata.get("question") or not metadata.get("prompt"):
            try:
                db = SessionLocal()
                teaching = db.query(Teaching).filter(Teaching.task_id == task_id).first()
                if teaching:
                    metadata.setdefault("title", teaching.title or "")
                    metadata.setdefault("question", teaching.question or "")
                    metadata.setdefault("prompt", teaching.prompt or teaching.question or "")
                    if teaching.knowledge_tags:
                        metadata.setdefault("knowledge_tags", teaching.knowledge_tags)
                db.close()
            except Exception as db_err:
                log(f"读取数据库教学信息失败（忽略）: {db_err}", "WARN")
        task.progress = 10
        _persist_task_state(task)

        # 内层预算必须小于外层兜底超时，否则重试会被掐断（历史封面丢失根因）
        inner_budget = env_int("PREVIEW_TOTAL_TIMEOUT_SECONDS", 270)
        timeout_seconds = env_int("PREVIEW_TASK_TIMEOUT_SECONDS", 300)
        if timeout_seconds <= inner_budget:
            timeout_seconds = inner_budget + 30

        # 备用模型预算已独立（切换时 deadline 重置），外层兜底计入已配置备用模型的独立预算
        backup_extra = preview_backup_extra_seconds()
        if backup_extra:
            timeout_seconds += backup_extra
            log(f"计入备用模型独立预算 {backup_extra} 秒，外层兜底调整为 {timeout_seconds} 秒")

        log(f"正在调用封面生成模型（force=True，内层预算 {inner_budget} 秒）...")
        await asyncio.wait_for(
            generate_image_for_task(task_dir, metadata, force=True, timeout_seconds=inner_budget),
            timeout=timeout_seconds,
        )

        if not (task_dir / "Preview.webp").exists():
            raise RuntimeError("封面接口调用结束，但未生成 Preview.webp")

        task.progress = 100
        task.status = "completed"
        _persist_task_state(task)
        log(f"封面重新生成完成: {task_id}/Preview.webp", "TASK")
    except Exception as e:
        task_dir = DATA_DIR / task_id
        existing_preview = get_preview_image_name(task_dir)
        task.status = "failed"
        task.preview_image = existing_preview
        task.error = str(e)
        _persist_task_state(task)
        log(f"封面重新生成失败 {task_id}: {e}", "ERROR")
        if existing_preview:
            log(f"保留旧封面继续使用: {task_id}/{existing_preview}", "WARN")
        import traceback
        traceback.print_exc()


@app.post("/api/admin/teachings/{task_id}/regenerate-cover")
async def admin_regenerate_cover(
    task_id: str,
    background_tasks: BackgroundTasks,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """管理员调用封面生成模型（与首页生成封面同款）重新生成封面 Preview.webp。

    - 强制覆盖已有封面
    - 生成耗时较长（内层预算约 270s），通过后台任务执行，前端轮询 /api/tasks/{task_id} 获取进度
    """
    teaching = db.query(Teaching).filter(Teaching.task_id == task_id).first()
    if not teaching:
        raise HTTPException(status_code=404, detail="教学内容不存在")

    task_dir = DATA_DIR / task_id
    if not task_dir.exists():
        raise HTTPException(status_code=404, detail="教学内容文件目录不存在")

    tasks[task_id] = Task(
        task_id=task_id,
        input_file=teaching.input_file or None,
        prompt="封面重新生成",
        user_id=teaching.user_id,
        topic_id=teaching.topic_id,
    )
    _persist_task_state(tasks[task_id])
    background_tasks.add_task(run_cover_regeneration, task_id)
    log(f"管理员 {admin_user.username} 请求重新生成封面: {task_id}", "ADMIN")

    return {"success": True, "task_id": task_id, "status": "running", "target": "cover"}


class AdminReidentifyTagsRequest(BaseModel):
    """管理员重新识别知识点标签请求。"""
    question: Optional[str] = None  # 可选：前端编辑后的题目内容；为空时回退到数据库/metadata


@app.post("/api/admin/teachings/{task_id}/reidentify-tags")
async def admin_reidentify_tags(
    task_id: str,
    body: Optional[AdminReidentifyTagsRequest] = None,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """管理员调用标签识别模型（与首页流水线同款）重新识别知识点标签。

    - 只返回识别结果，不自动保存，保留手动选择标签能力
    - 优先使用请求体中的 question（编辑后未保存的题目），否则回退数据库/metadata
    """
    teaching = db.query(Teaching).filter(Teaching.task_id == task_id).first()
    if not teaching:
        raise HTTPException(status_code=404, detail="教学内容不存在")

    question = ""
    if body and body.question:
        question = body.question.strip()
    if not question:
        question = (teaching.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="题目内容不能为空，请先在「题目内容」中填写题目")

    log(f"管理员 {admin_user.username} 请求重新识别标签: {task_id}（题目长度 {len(question)}）", "ADMIN")

    # 识别总预算：必须小于前端超时（175s），让后端先返回明确的 504，
    # 避免前端 abort 造成的"转圈后无响应"；环境变量可调。
    total_timeout = env_int("TAG_RECOGNIZE_TOTAL_TIMEOUT_SECONDS", 170)

    async def _do_recognize() -> dict:
        """按引擎开关执行一次识别，返回统一结构（永不返回 None）。"""
        # 阶段三：按引擎开关选择识别方式（agent 智能体 / legacy 提示词）
        from tag_agent.config import get_recognition_engine
        from knowledge_tag_injector import inject_knowledge_tags_full
        engine = get_recognition_engine()
        if engine == "legacy":
            # legacy 提示词模型：仅返回识别结果，不支持新建标签（不进审核队列）
            from knowledge_tag_injector import inject_knowledge_tags
            legacy_res = await inject_knowledge_tags(question)
            return {
                "primary": legacy_res or {},
                "knowledge_tags": legacy_res or {},
                "pending_tag_id": "",
                "question_proposal_id": "",
                "_meta": {"source": "legacy", "engine": "legacy"},
            }
        # 智能体流水线：与创建内容同款，遵从识别规则（含「新建标签」三场景）
        from tag_agent.client import recognize_or_fallback
        async def _legacy(q: str, t: str = ""):
            full = await inject_knowledge_tags_full(q, title=t)
            return (full or {}).get("primary")
        mapped, engine_used = await recognize_or_fallback(
            question, question_id="", legacy_caller=_legacy,
        )
        if mapped is None:
            mapped = {}
        # recognize_or_fallback 在智能体不可用时内部降级到 legacy，
        # 此时 mapped 为裸 primary 结构，统一包装以保持返回结构稳定
        if engine_used == "legacy" and isinstance(mapped, dict) \
                and "knowledge_tags" not in mapped and "pending_tag_id" not in mapped:
            mapped = {
                "primary": mapped or {},
                "knowledge_tags": mapped or {},
                "pending_tag_id": "",
                "question_proposal_id": "",
                "_meta": {"source": "legacy_fallback", "engine": "legacy"},
            }
        return mapped

    try:
        _t0 = time.time()
        result = await asyncio.wait_for(_do_recognize(), timeout=total_timeout)
        # 自动重试：首次未命中 main_tag 且耗时在预算前半程内（多为网关抖动/低置信），
        # 自动补跑一次（RAG 预检命中时秒回），减少"需要手动点多好几次"的体验问题。
        _kt = result.get("knowledge_tags") or result.get("primary") or {}
        if not _kt.get("main_tag") and (time.time() - _t0) < total_timeout / 2:
            log(f"首次识别未命中标签，自动重试一次: {task_id}", "WARN")
            _remain = max(10, total_timeout - (time.time() - _t0))
            result = await asyncio.wait_for(_do_recognize(), timeout=_remain)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="标签识别超时，请重试或手动选择")
    except Exception as e:
        log(f"标签识别失败: {task_id}: {e}", "ERROR")
        raise HTTPException(status_code=500, detail=f"标签识别失败: {e}")

    # 识别结果判定：优先看完整 knowledge_tags，兼容 legacy 的 primary 结构
    _kt = result.get("knowledge_tags") or result.get("primary") or {}
    if not _kt.get("main_tag"):
        return {
            "success": False,
            "message": "未能识别出标签，请手动选择",
            "knowledge_tags": None,
        }

    return {
        "success": True,
        "knowledge_tags": result.get("knowledge_tags"),
        "primary": result.get("primary"),
        # 新建标签提案：进入「标签智能体审核」队列（operation=add），
        # 需管理员确认后方可正式使用（与创建内容同款的识别规则）
        "pending_tag_id": result.get("pending_tag_id", ""),
        "question_proposal_id": result.get("question_proposal_id", ""),
        "_meta": result.get("_meta", {}),
    }


# ==================== 教学内容完整性自动补全（详情页进入时触发，2026-09-11） ====================
# 背景：管理后台 /api/admin/teachings 已有封面/动画缺失检测，但用户进入教学详情页时
# 此前对缺失资产只做静默兜底。本节把检测判据抽为共享函数（_compute_teaching_defects，
# 管理后台列表同口径复用），并在详情页加载时同步检测、按需异步补全：
#   - 动画缺失 → 复用管理后台同款 run_pipeline（连带封面；自动走 _pipeline_semaphore 并发闸）
#   - 仅封面缺失 → 复用 run_cover_regeneration
#   - 标签缺失 → 后台自动识别（run_tag_completion）：命中官方库（inject_official）
#               自动落库；低置信/新建提案 → 仅写 tag_agent 审核队列，不写 teachings
# 检测本身只做文件/DB 判断（毫秒级）；生成全部复用既有后台任务积木，不新建队列表。

# 标签补全进行中标记（防同一题目重复触发；动画/封面复用 tasks 字典的 pending/running 状态判重）
_ensure_tags_inflight: set[str] = set()


def _compute_teaching_defects(task_dir, teaching) -> list:
    """教学内容完整性共享检测（管理后台列表与详情页 ensure-complete 同口径）。

    判据：
    - 封面：目录下无 Preview.webp/preview.webp/preview.png（check_preview_image_exists）
    - 动画：teaching_data.json（新版）与 teaching.html（旧版）均不可用；
            旧版 html 内容为 {"detail":"Teaching HTML not found"} 视为缺失
    - 标签：knowledge_tags（DB 优先，回退 metadata.json）为空或无 main_tag

    Returns:
        [{"asset": "cover"|"animation"|"tags", "reason": str}, ...]（无缺失时为空列表）
    """
    defects = []
    if not check_preview_image_exists(task_dir, teaching.preview_image):
        defects.append({"asset": "cover", "reason": "封面未生成"})
    has_animation = (task_dir / "teaching_data.json").exists()
    if not has_animation:
        html_path = task_dir / (teaching.teaching_html_file or "teaching.html")
        if html_path.exists():
            try:
                has_animation = html_path.read_text(encoding="utf-8", errors="replace").strip() != '{"detail":"Teaching HTML not found"}'
            except OSError:
                has_animation = False
    if not has_animation:
        defects.append({"asset": "animation", "reason": '动画内容缺失（{"detail":"Teaching HTML not found"}）'})
    kt = _read_knowledge_tags(teaching.task_id, teaching)
    if not (isinstance(kt, dict) and kt.get("main_tag")):
        defects.append({"asset": "tags", "reason": "知识点标签缺失"})
    return defects


@app.post("/api/teachings/{task_id}/ensure-complete")
async def ensure_teaching_complete(
    task_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """教学详情页进入时触发的完整性检测 + 自动补全。

    检测同步执行（文件/DB 判断，毫秒级）；对缺失资产按需触发后台补全任务：
    - 动画缺失：复用管理后台同款 run_pipeline（连带封面，走 _pipeline_semaphore）
    - 仅封面缺失：复用 run_cover_regeneration
    - 标签缺失：后台自动识别（高置信官方标签自动落库，其余进审核队列）
    同一题目已有生成任务在跑（pending/running）时不重复触发。
    """
    teaching = db.query(Teaching).filter(Teaching.task_id == task_id).first()
    if not teaching:
        raise HTTPException(status_code=404, detail="Teaching not found")

    task_dir = DATA_DIR / task_id
    defects = _compute_teaching_defects(task_dir, teaching)
    if not defects:
        return {"task_id": task_id, "complete": True, "defects": [], "triggered": [], "task_running": False}

    # 生成任务判重：该 task_id 已有 pending/running 任务（本功能、创建流程或管理员重生成）时不叠加
    existing = tasks.get(task_id)
    task_running = bool(existing and existing.status in ("pending", "running"))

    triggered = []
    assets = {d["asset"] for d in defects}
    if not task_running:
        if "animation" in assets:
            # 与管理后台「重新生成动画」同款：以库内 question/prompt 为输入原地重生成
            prompt = (teaching.prompt or teaching.question or "").strip()
            if prompt:
                tasks[task_id] = Task(
                    task_id=task_id,
                    input_file=teaching.input_file or None,
                    prompt=prompt,
                    user_id=teaching.user_id,
                    topic_id=teaching.topic_id,
                    preserve_on_failure=True,
                    metadata={"trigger": "ensure_complete"},  # 标记来源：详情页自动补全（前端据此静默失败，用户主动生成仍弹窗）
                )
                _persist_task_state(tasks[task_id])
                background_tasks.add_task(run_pipeline, task_id)
                triggered.append("animation")
        elif "cover" in assets:
            tasks[task_id] = Task(
                task_id=task_id,
                input_file=teaching.input_file or None,
                prompt="封面重新生成",
                user_id=teaching.user_id,
                topic_id=teaching.topic_id,
                metadata={"trigger": "ensure_complete"},  # 标记来源：详情页自动补全（前端据此静默失败）
            )
            _persist_task_state(tasks[task_id])
            background_tasks.add_task(run_cover_regeneration, task_id)
            triggered.append("cover")
        if "tags" in assets and task_id not in _ensure_tags_inflight:
            _ensure_tags_inflight.add(task_id)
            background_tasks.add_task(run_tag_completion, task_id)
            triggered.append("tags")
        if triggered:
            log(f"详情页进入触发内容补全: {task_id} → {triggered}", "TASK")

    return {
        "task_id": task_id,
        "complete": False,
        "defects": defects,
        "triggered": triggered,
        "task_running": task_running or bool(triggered),
    }


async def run_tag_completion(task_id: str):
    """后台任务：标签缺失自动补全（详情页 ensure-complete 触发）。

    与 /tag-agent/recognize 同链路：orchestrator 识别 → persist_recognition
    （识别日志 + 题目标签提案入审核队列）。结果判定：
    - 命中官方库（action=inject_official 且无 pending 提案）→ 自动写入
      teachings.knowledge_tags/main_tag/sub_tags 并同步 metadata.json（高置信自动落库）
    - 其余（低置信/新建标签提案）→ 仅留在审核队列由管理员确认（不阻塞页面）
    """
    try:
        # 题目来源：数据库 question，回退 metadata.json
        question = ""
        try:
            db = SessionLocal()
            try:
                teaching = db.query(Teaching).filter(Teaching.task_id == task_id).first()
                if teaching:
                    question = (teaching.question or "").strip()
            finally:
                db.close()
        except Exception as db_err:
            log(f"标签补全读取数据库失败（忽略）: {task_id}: {db_err}", "WARN")
        if not question:
            try:
                meta_path = DATA_DIR / task_id / "metadata.json"
                if meta_path.exists():
                    with open(meta_path, "r", encoding="utf-8") as f:
                        question = (json.load(f).get("question") or "").strip()
            except Exception:
                question = ""
        if not question:
            log(f"标签补全跳过（无题目内容）: {task_id}", "WARN")
            return

        from tag_agent import service as tag_service
        from tag_agent.client import get_orchestrator as get_agent_orchestrator
        from tag_agent.db import get_session_factory

        # 识别总预算与管理后台「重新识别标签」一致（防长挂）
        total_timeout = env_int("TAG_RECOGNIZE_TOTAL_TIMEOUT_SECONDS", 170)
        factory = get_session_factory()
        async with factory() as session:
            async def pending_provider(domain: str, grade: str, chapter: str):
                return await tag_service.list_pending_names(session, domain, grade, chapter)

            outcome = await asyncio.wait_for(
                get_agent_orchestrator().recognize(
                    question, question_id=task_id, creator_id="ensure_complete",
                    pending_name_provider=pending_provider,
                ),
                timeout=total_timeout,
            )
            result = await tag_service.persist_recognition(
                session, question=question, outcome=outcome,
                question_id=task_id, creator_id="ensure_complete",
            )

        # 高置信官方标签 → 自动落库（与题目标签审核通过后的宿主落地同款）
        kt = (result or {}).get("knowledge_tags") or {}
        if getattr(outcome, "action", "") == "inject_official" and kt.get("main_tag") \
                and not result.get("pending_tag_id"):
            try:
                from tag_agent.question_queue import apply_knowledge_tags_to_teaching
                db = SessionLocal()
                try:
                    teaching = db.query(Teaching).filter(Teaching.task_id == task_id).first()
                    if teaching and apply_knowledge_tags_to_teaching(teaching, kt, task_id=task_id):
                        teaching.main_tag = kt.get("main_tag")
                        teaching.sub_tags = kt.get("sub_tags") or []
                        flag_modified(teaching, "sub_tags")
                        flag_modified(teaching, "knowledge_tags")
                        db.commit()
                finally:
                    db.close()
                # 同步 metadata.json（needs_tag_selection=False，与手动保存标签同口径）
                try:
                    metadata_path = DATA_DIR / task_id / "metadata.json"
                    meta = {}
                    if metadata_path.exists():
                        with open(metadata_path, "r", encoding="utf-8") as f:
                            meta = json.load(f)
                    meta["knowledge_tags"] = kt
                    meta["needs_tag_selection"] = False
                    meta["knowledge_tags_updated_at"] = datetime.utcnow().isoformat() + "Z"
                    metadata_path.parent.mkdir(parents=True, exist_ok=True)
                    _atomic_write_json(metadata_path, meta)
                except Exception as meta_err:
                    log(f"标签补全同步 metadata.json 失败（不影响 DB）: {task_id}: {meta_err}", "WARN")
                log(f"标签补全完成（官方标签自动落库）: {task_id} → {kt.get('main_tag')}", "TASK")
            except Exception as apply_err:
                log(f"标签补全自动落库失败: {task_id}: {apply_err}", "ERROR")
        else:
            log(
                f"标签补全：未达自动落库条件（action={getattr(outcome, 'action', '?')}），"
                f"已写入审核队列待管理员确认: {task_id}", "WARN",
            )
    except asyncio.TimeoutError:
        log(f"标签补全识别超时（可稍后进入详情页重试或管理员手动识别）: {task_id}", "WARN")
    except Exception as e:
        log(f"标签补全失败: {task_id}: {e}", "ERROR")
        import traceback
        traceback.print_exc()
    finally:
        _ensure_tags_inflight.discard(task_id)


@app.delete("/api/admin/teachings/{task_id}")
async def admin_delete_teaching(
    task_id: str,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """删除教学内容（管理员）"""
    teaching = db.query(Teaching).filter(Teaching.task_id == task_id).first()
    if not teaching:
        raise HTTPException(status_code=404, detail="教学内容不存在")
    
    try:
        # 1. 删除向量数据库中的 embedding
        delete_teaching_embedding(task_id)
        
        # 2. 删除文件（HTML、预览图等）
        task_dir = DATA_DIR / task_id
        if task_dir.exists():
            shutil.rmtree(task_dir)
            log(f"已删除任务目录: {task_dir}", "ADMIN")
        
        # 3. 删除数据库记录（级联删除会处理评论、点赞、收藏等）
        db.delete(teaching)
        db.commit()
        
        log(f"管理员 {admin_user.username} 删除了教学内容: {task_id}", "ADMIN")
        
        return {
            "success": True,
            "message": "教学内容已删除"
        }
    except Exception as e:
        db.rollback()
        log(f"删除教学内容失败: {str(e)}", "ERROR")
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")


@app.get("/api/admin/users")
async def admin_get_users(
    page: int = 1,
    page_size: int = 20,
    search: Optional[str] = None,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """获取用户列表（管理员）"""
    query = db.query(User)
    
    # 搜索过滤
    if search:
        query = query.filter(
            or_(
                User.username.contains(search),
                User.phone.contains(search) if User.phone else False,
                User.email.contains(search) if User.email else False
            )
        )
    
    # 总数
    total = query.count()
    
    # 分页
    offset = (page - 1) * page_size
    users = query.order_by(desc(User.created_at)).offset(offset).limit(page_size).all()

    # 一次性查询本页用户的邀请关系（被邀请 → 邀请人），避免 N+1
    page_user_ids = [u.user_id for u in users]
    invite_map = {}  # invited_user_id -> inviter_user_id
    if page_user_ids:
        relations = (
            db.query(InviteRelation.invited_user_id, InviteRelation.inviter_user_id)
            .filter(InviteRelation.invited_user_id.in_(page_user_ids))
            .all()
        )
        invite_map = {invited: inviter for invited, inviter in relations}

    # 批量查询邀请人信息（用户名/邀请码/成功邀请人数）
    inviter_ids = set(invite_map.values())
    inviter_info: Dict[str, dict] = {}
    if inviter_ids:
        inviter_users = db.query(User).filter(User.user_id.in_(inviter_ids)).all()
        for inv in inviter_users:
            inviter_info[inv.user_id] = {
                "user_id": inv.user_id,
                "username": inv.username,
                "phone": inv.phone,
                "email": inv.email,
                "invite_code": inv.invite_code,
            }

    # 以邀请关系表为准统计一级邀请人的实际已邀请人数（避免进度表计数漂移）
    all_inviter_ids = set(inviter_ids)
    invited_count_map: Dict[str, int] = {}
    if all_inviter_ids:
        count_rows = (
            db.query(InviteRelation.inviter_user_id, func.count(InviteRelation.id))
            .filter(InviteRelation.inviter_user_id.in_(all_inviter_ids))
            .group_by(InviteRelation.inviter_user_id)
            .all()
        )
        invited_count_map = {uid: int(cnt) for uid, cnt in count_rows}
    for uid in inviter_info:
        inviter_info[uid]["invited_count"] = invited_count_map.get(uid, 0)

    # 获取每个用户的教学内容数量
    result = []
    commission_accounts = {
        account.user_id: account
        for account in db.query(CommissionAccount).filter(CommissionAccount.user_id.in_(page_user_ids)).all()
    }
    # 赠送余额：按“未过期批次剩余之和”实时计算（聚合缓存可能仍含已过期批次）
    from database import QuotaGrant
    _now = datetime.utcnow()
    _grant_rows = (
        db.query(QuotaGrant.user_id, func.coalesce(func.sum(QuotaGrant.remaining), 0))
        .filter(
            QuotaGrant.user_id.in_(page_user_ids),
            or_(QuotaGrant.expire_at.is_(None), QuotaGrant.expire_at >= _now),
        )
        .group_by(QuotaGrant.user_id)
        .all()
    )
    _grant_balance_map = {uid: int(total or 0) for uid, total in _grant_rows}
    for user in users:
        teachings_count = db.query(Teaching).filter(Teaching.user_id == user.user_id).count()
        # 获取用户配额中的赠送余额（聚合值；按次付费额度已下线）
        free_balance = _grant_balance_map.get(user.user_id, 0)

        # 返利账户数据（单位：分）
        commission = commission_accounts.get(user.user_id)
        total_reward = int(commission.total_reward or 0) if commission else 0
        withdrawn_amount = int(commission.withdrawn_amount or 0) if commission else 0
        pending_amount = int(commission.pending_amount or 0) if commission else 0

        inviter_user_id = invite_map.get(user.user_id)
        inviter = inviter_info.get(inviter_user_id) if inviter_user_id else None

        result.append({
            "user_id": user.user_id,
            "username": user.username,
            "phone": user.phone,
            "email": user.email,
            "grade": user.grade,
            "signature": user.signature,
            "created_at": (user.created_at.isoformat() + "Z") if user.created_at else None,
            "extra_balance": free_balance,
            "free_balance": free_balance,
            "paid_balance": 0,             # 按次付费已下线，保留字段以兼容旧版后台页面
            "teachings_count": teachings_count,
            "ip_address": user.ip_address,              # 最近一次登录时记录的客户端 IP（每次登录都会刷新）
            "invite_code": user.invite_code,            # 该用户自己的邀请码
            "used_invite_code": (inviter or {}).get("invite_code"),  # 该用户注册时使用的邀请码（邀请人的码）
            "inviter": inviter,                          # 邀请人信息（无则 null）
            "commission": {                              # 返利账户（单位：分）
                "total_reward": total_reward,
                "withdrawn_amount": withdrawn_amount,
                "pending_amount": pending_amount,
                "available_amount": max(0, total_reward - withdrawn_amount - pending_amount),
            },
        })
    
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
        "data": result
    }


@app.get("/api/admin/users/{user_id}")
async def admin_get_user_detail(
    user_id: str,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """获取用户详情（管理员）"""
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    # 获取用户的教学内容数量
    teachings_count = db.query(Teaching).filter(Teaching.user_id == user_id).count()
    
    # 获取用户的收藏数量
    favorites_count = db.query(Favorite).filter(Favorite.user_id == user_id).count()
    # 获取用户配额中的赠送余额（聚合值；按次付费额度已下线）
    user_quota = db.query(UserQuota).filter(UserQuota.user_id == user_id).first()
    free_balance = int(user_quota.extra_balance or 0) if user_quota else 0

    # 该用户自己的成功邀请人数
    progress = db.query(InviteProgress).filter(InviteProgress.user_id == user_id).first()
    invited_count = int(progress.invited_count or 0) if progress else 0

    # 该用户注册时使用的邀请码（邀请人信息）
    relation = db.query(InviteRelation).filter(InviteRelation.invited_user_id == user_id).first()
    inviter = None
    if relation:
        inv = db.query(User).filter(User.user_id == relation.inviter_user_id).first()
        if inv:
            inv_progress = db.query(InviteProgress).filter(InviteProgress.user_id == inv.user_id).first()
            inviter = {
                "user_id": inv.user_id,
                "username": inv.username,
                "phone": inv.phone,
                "email": inv.email,
                "invite_code": inv.invite_code,
                "invited_count": int(inv_progress.invited_count or 0) if inv_progress else 0,
            }

    # 返利账户数据（单位：分）
    commission_account = db.query(CommissionAccount).filter(CommissionAccount.user_id == user_id).first()
    total_reward = int(commission_account.total_reward or 0) if commission_account else 0
    withdrawn_amount = int(commission_account.withdrawn_amount or 0) if commission_account else 0
    pending_amount = int(commission_account.pending_amount or 0) if commission_account else 0

    return {
        "user_id": user.user_id,
        "username": user.username,
        "phone": user.phone,
        "email": user.email,
        "grade": user.grade,
        "signature": user.signature,
        "created_at": (user.created_at.isoformat() + "Z") if user.created_at else None,
        "extra_balance": free_balance,
        "free_balance": free_balance,
        "paid_balance": 0,             # 按次付费已下线，保留字段以兼容旧版后台页面
        "teachings_count": teachings_count,
        "favorites_count": favorites_count,
        "invite_code": user.invite_code,            # 该用户自己的邀请码
        "invited_count": invited_count,             # 该用户成功邀请的人数
        "used_invite_code": (inviter or {}).get("invite_code"),  # 注册时使用的邀请码
        "inviter": inviter,                         # 邀请人信息（无则 null）
        "commission": {                             # 返利账户（单位：分）
            "total_reward": total_reward,
            "withdrawn_amount": withdrawn_amount,
            "pending_amount": pending_amount,
            "available_amount": max(0, total_reward - withdrawn_amount - pending_amount),
        },
    }


@app.put("/api/admin/users/{user_id}")
async def admin_update_user(
    user_id: str,
    extra_balance: Optional[int] = None,
    add_balance: Optional[int] = None,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """更新用户信息（管理员）—— 支持设置/增减赠送余额（走 quota_grants 批次账本，长期有效）"""
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    from invite_quota_api import _admin_add_balance, _sync_extra_balance, _ensure_user_quota
    _sync_extra_balance(db, user.user_id)
    user_quota = _ensure_user_quota(db, user.user_id)
    old_balance = int(user_quota.extra_balance or 0)

    if extra_balance is not None:
        if extra_balance < 0:
            raise HTTPException(status_code=400, detail="余额不能为负数")
        new_balance = _admin_add_balance(db, user.user_id, int(extra_balance) - old_balance)
        db.commit()
        log(f"管理员 {admin_user.username} 将用户 {user.username} 的余额从 {old_balance} 设置为 {new_balance}", "ADMIN")
        return {
            "success": True,
            "message": f"余额已更新：{old_balance} → {new_balance}",
            "user": {
                "user_id": user.user_id,
                "username": user.username,
                "extra_balance": new_balance
            }
        }

    if add_balance is not None:
        new_balance = _admin_add_balance(db, user.user_id, int(add_balance))
        db.commit()
        action = "增加" if add_balance >= 0 else "扣除"
        log(f"管理员 {admin_user.username} 为用户 {user.username} {action}了 {abs(add_balance)} 余额（{old_balance} → {new_balance}）", "ADMIN")
        return {
            "success": True,
            "message": f"已{action} {abs(add_balance)} 余额（{old_balance} → {new_balance}）",
            "user": {
                "user_id": user.user_id,
                "username": user.username,
                "extra_balance": new_balance
            }
        }

    # 没有提供任何更新参数
    return {
        "success": False,
        "message": "未提供任何更新参数，请提供 extra_balance 或 add_balance",
        "user": {
            "user_id": user.user_id,
            "username": user.username,
            "extra_balance": user_quota.extra_balance
        }
    }


@app.get("/api/admin/users/{user_id}/account")
async def admin_get_user_account(
    user_id: str,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """获取用户账号信息（管理员）"""
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    has_password = bool(user.password_hash)
    return {
        "success": True,
        "user": {
            "user_id": user.user_id,
            "username": user.username,
            "has_password": has_password,
            "password_masked": "1****6" if has_password else "未设置密码",
            "password_plain": None,
        }
    }


@app.put("/api/admin/users/{user_id}/reset-password")
async def admin_reset_user_password(
    user_id: str,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """管理员初始化用户密码为 123456"""
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    default_password = "123456"
    user.password_hash = hash_password(default_password)
    db.commit()
    log(f"管理员 {admin_user.username} 将用户 {user.username} 的密码初始化为默认密码", "ADMIN")

    return {
        "success": True,
        "message": f"用户 {user.username} 的密码已初始化为 123456",
        "user": {
            "user_id": user.user_id,
            "username": user.username,
        }
    }


# ===================== 用户封禁 / 删除（管理员） =====================

def _get_user_bans(db: Session) -> Dict[str, str]:
    """读取封禁列表（存于 system_configs 表，key=user_bans，value=JSON：{user_id: 解封时间或 permanent}）"""
    row = db.query(SystemConfig).filter(SystemConfig.config_key == "user_bans").first()
    if not row or not row.config_value:
        return {}
    try:
        return json.loads(row.config_value)
    except Exception:
        return {}


def _is_user_banned(db: Session, user_id: str) -> bool:
    """判断用户当前是否处于封禁状态（未过期或永久封禁）"""
    bans = _get_user_bans(db)
    until = bans.get(user_id)
    if not until:
        return False
    if until == "permanent":
        return True
    try:
        expire = datetime.fromisoformat(until.replace("Z", "+00:00"))
        if expire.tzinfo is None:
            # 无时区历史数据：按服务器本地时区补全，避免 naive/aware 比较崩溃
            expire = expire.replace(tzinfo=datetime.now().astimezone().tzinfo)
        return datetime.now().astimezone() < expire
    except Exception:
        return True  # 时间解析失败时保守视为封禁


def _set_user_ban(db: Session, user_id: str, until: Optional[str]) -> None:
    """写入/清除封禁状态；until 为 None 时解封"""
    bans = _get_user_bans(db)
    if until is None:
        bans.pop(user_id, None)
    else:
        bans[user_id] = until
    row = db.query(SystemConfig).filter(SystemConfig.config_key == "user_bans").first()
    value = json.dumps(bans, ensure_ascii=False)
    if row:
        row.config_value = value
    else:
        db.add(SystemConfig(config_key="user_bans", config_value=value, description="被封禁用户（value: 解封时间或 permanent）"))


class AdminBanUpdate(BaseModel):
    """管理员封禁请求：ban_until 为 ISO 时间字符串或 "permanent"；传 null 表示解封"""
    ban_until: Optional[str] = None


@app.put("/api/admin/users/{user_id}/ban")
async def admin_ban_user(
    user_id: str,
    payload: AdminBanUpdate,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """封禁 / 解封用户（存于 system_configs，实时生效，无需重启）"""
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if payload.ban_until is None:
        _set_user_ban(db, user_id, None)
        db.commit()
        log(f"管理员 {admin_user.username} 解除了用户 {user.username} 的封禁", "ADMIN")
        return {"success": True, "message": "已解除封禁"}
    _set_user_ban(db, user_id, payload.ban_until)
    db.commit()
    # 系统通知：向被封禁用户推送一条系统消息
    ban_text = "永久封禁" if payload.ban_until == "permanent" else f"封禁至 {payload.ban_until}"
    _create_notification(
        db,
        user_id,
        "system",
        "账号已被封禁",
        f"您的账号已被管理员{ban_text}，部分功能将受到限制。如有疑问请联系管理员。",
        extra={"type": "ban", "ban_until": payload.ban_until},
    )
    log(f"管理员 {admin_user.username} 封禁用户 {user.username}（{payload.ban_until}）", "ADMIN")
    return {"success": True, "message": "已封禁该用户"}


@app.delete("/api/admin/users/{user_id}")
async def admin_delete_user(
    user_id: str,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """彻底删除用户账号及关联数据（依赖数据库级联 + 显式清理邀请/返利/配额等表）"""
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if admin_user.user_id == user_id:
        raise HTTPException(status_code=400, detail="不能删除当前登录的管理员账号")

    from database import DeviceBinding
    # 显式清理与邀请/返利/配额/设备相关的关联数据
    db.query(InviteRelation).filter(
        or_(InviteRelation.inviter_user_id == user_id, InviteRelation.invited_user_id == user_id)
    ).delete(synchronize_session=False)
    db.query(CommissionRecord).filter(
        or_(
            CommissionRecord.source_user_id == user_id,
            CommissionRecord.recipient_user_id == user_id,
            CommissionRecord.inviter_user_id == user_id,
        )
    ).delete(synchronize_session=False)
    db.query(CommissionAccount).filter(CommissionAccount.user_id == user_id).delete(synchronize_session=False)
    db.query(UserQuota).filter(UserQuota.user_id == user_id).delete(synchronize_session=False)
    db.query(DeviceBinding).filter(DeviceBinding.user_id == user_id).delete(synchronize_session=False)
    db.query(InviteProgress).filter(InviteProgress.user_id == user_id).delete(synchronize_session=False)
    _set_user_ban(db, user_id, None)

    username = user.username
    db.delete(user)
    db.commit()
    log(f"管理员 {admin_user.username} 彻底删除了用户 {username}（{user_id}）", "ADMIN")
    return {"success": True, "message": f"用户 {username} 已删除"}


# ===================== 订阅套餐与价格（管理员可配置，实时生效） =====================

PLAN_KEYS = {"monthly": "plan_monthly", "quarterly": "plan_quarterly", "halfyear": "plan_halfyear", "yearly": "plan_yearly"}
PLAN_DEFAULTS = {
    "monthly": {"original": 39, "discount": 9.9, "discount_until": "", "duration_days": 30},
    "quarterly": {"original": 99, "discount": 26.9, "discount_until": "", "duration_days": 90},
    "halfyear": {"original": 199, "discount": 52, "discount_until": "", "duration_days": 180},
    "yearly": {"original": 299, "discount": 89, "discount_until": "", "duration_days": 365},
}
PLAN_NAMES = {"monthly": "月度订阅", "quarterly": "季度订阅", "halfyear": "半年订阅", "yearly": "年度订阅", "free": "免费版"}
PLAN_DURATION_DAYS = {"monthly": 30, "quarterly": 90, "halfyear": 180, "yearly": 365}
PLAN_RIGHTS = {
    "free": "注册送5次免费额度",
    "monthly": "当月无限次使用",
    "quarterly": "当季无限次使用",
    "halfyear": "会员期内无限次使用",
    "yearly": "当年无限次使用",
}


def _get_plan_config(db: Session, plan: str) -> Dict[str, Any]:
    """读取套餐价格配置（SystemConfig，JSON），未配置时返回默认值"""
    key = PLAN_KEYS.get(plan)
    default = PLAN_DEFAULTS.get(plan, {})
    if not key:
        return dict(default)
    row = db.query(SystemConfig).filter(SystemConfig.config_key == key).first()
    if not row or not row.config_value:
        return dict(default)
    try:
        data = json.loads(row.config_value)
        merged = dict(default)
        merged.update(data if isinstance(data, dict) else {})
        return merged
    except Exception:
        return dict(default)


def _plan_duration_days(db: Session, plan: str) -> int:
    """订阅时长（天）：优先读 SystemConfig(plan_*) 的 duration_days，回退写死默认值。

    单一数据源 = 后台「订阅价格体系」；删掉调用方直接读 PLAN_DURATION_DAYS 的写法。
    """
    try:
        d = int(_get_plan_config(db, plan).get("duration_days") or 0)
    except Exception:
        d = 0
    return d if d > 0 else PLAN_DURATION_DAYS.get(plan, 0)


def _is_discount_active(cfg: Dict[str, Any]) -> bool:
    """优惠价是否生效：未设置截止时间视为长期优惠，否则截止日当天仍有效"""
    until = str(cfg.get("discount_until") or "").strip()
    if not until:
        return True
    try:
        expire = datetime.fromisoformat(until)
        return datetime.now().astimezone().date() <= expire
    except Exception:
        return True


def _plan_price(cfg: Dict[str, Any]) -> float:
    """当前应支付价格：优惠期内用优惠价，否则原价"""
    try:
        if _is_discount_active(cfg):
            discount = float(cfg.get("discount") or 0)
            if discount > 0:
                return discount
        return float(cfg.get("original") or 0)
    except (TypeError, ValueError):
        return 0.0


def _plan_display_name(db: Session, plan: str) -> str:
    """套餐展示名：优先后台配置的 name（可编辑），为空回退内置 PLAN_NAMES"""
    try:
        name = str((_get_plan_config(db, plan) or {}).get("name") or "").strip()
    except Exception:
        name = ""
    return name or PLAN_NAMES.get(plan, plan)


def _extract_plan_from_note(note: Optional[str]) -> Optional[str]:
    """从订单 note 中解析订阅套餐标识（[plan:xxx]）"""
    if not note:
        return None
    m = re.search(r"\[plan:(\w+)\]", note)
    return m.group(1) if m and m.group(1) in PLAN_KEYS else None


def _extract_order_type_from_note(note: Optional[str]) -> str:
    """从订单 note 中解析首单/续费标识（[otype:first|renewal]）；缺失按首单处理"""
    if not note:
        return "first"
    m = re.search(r"\[otype:(first|renewal)\]", note)
    return m.group(1) if m else "first"


def _extract_commission_from_note(note: Optional[str]) -> int:
    """从订阅订单备注中解析已锁定的返利金额（单位：分）。"""
    if not note:
        return 0
    m = re.search(r"\[commission:(\d+)\]", note)
    return int(m.group(1)) if m else 0


@app.get("/api/plans")
async def get_plans(db: Session = Depends(get_db)):
    """公开的订阅套餐与价格配置（供前端充值页渲染）"""
    plans = []
    for plan_id in ("free", "monthly", "quarterly", "halfyear", "yearly"):
        cfg = _get_plan_config(db, plan_id)
        original = float(cfg.get("original") or 0)
        discount = float(cfg.get("discount") or 0)
        price = original if plan_id == "free" else _plan_price(cfg)
        plans.append({
            "id": plan_id,
            "name": _plan_display_name(db, plan_id),
            "original": original,
            "discount": discount,
            "discount_until": cfg.get("discount_until", ""),
            "discount_active": _is_discount_active(cfg),
            "price": price,
            "rights": PLAN_RIGHTS.get(plan_id, ""),
            "duration_days": _plan_duration_days(db, plan_id),
        })
    return {"success": True, "plans": plans}


# ===================== 返利管理（管理员） =====================


def _commission_account_dict(db: Session, user_id: str) -> Dict[str, int]:
    """管理员视角的返利账户数据（单位：分）"""
    account = db.query(CommissionAccount).filter(CommissionAccount.user_id == user_id).first()
    total = int(account.total_reward or 0) if account else 0
    withdrawn = int(account.withdrawn_amount or 0) if account else 0
    pending = int(account.pending_amount or 0) if account else 0
    return {
        "total_reward": total,
        "withdrawn_amount": withdrawn,
        "pending_amount": pending,
        "available_amount": max(0, total - withdrawn - pending),
    }


@app.get("/api/admin/commission/{user_id}")
async def admin_get_commission(
    user_id: str,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """查看指定用户的返利数据（汇总 + 最近返利明细 + 提现记录）"""
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    recent_records = (
        db.query(CommissionRecord)
        .filter(CommissionRecord.recipient_user_id == user_id)
        .order_by(CommissionRecord.created_at.desc())
        .limit(50)
        .all()
    )
    source_ids = {r.source_user_id for r in recent_records} | {r.inviter_user_id for r in recent_records}
    username_map = {}
    invite_code_map = {}
    if source_ids:
        for u in db.query(User).filter(User.user_id.in_(source_ids)).all():
            username_map[u.user_id] = u.username
            invite_code_map[u.user_id] = u.invite_code

    withdrawals = (
        db.query(WithdrawalRequest)
        .filter(WithdrawalRequest.user_id == user_id)
        .order_by(WithdrawalRequest.created_at.desc())
        .limit(50)
        .all()
    )

    return {
        "success": True,
        "username": user.username,
        "account": _commission_account_dict(db, user_id),
        "records": [
            {
                "id": record.id,
                "sourceUserId": record.source_user_id,
                "sourceUsername": username_map.get(record.source_user_id),
                "sourceInviteCode": invite_code_map.get(record.source_user_id),
                "inviterUsername": username_map.get(record.inviter_user_id),
                "inviterInviteCode": invite_code_map.get(record.inviter_user_id),
                "level": record.level,
                "amount": int(record.amount or 0),
                "status": record.status,
                "createdAt": (record.created_at.isoformat() + "Z") if record.created_at else None,
            }
            for record in recent_records
        ],
        "withdrawals": [
            {
                "request_id": req.request_id,
                "amount": int(req.amount or 0),
                "status": req.status,
                "admin_note": req.admin_note,
                "processed_by": req.processed_by,
                "created_at": (req.created_at.isoformat() + "Z") if req.created_at else None,
                "processed_at": (req.processed_at.isoformat() + "Z") if req.processed_at else None,
            }
            for req in withdrawals
        ],
    }


class AdminCommissionUpdate(BaseModel):
    """管理员编辑用户返利数据：set_* 为覆盖设置，add_* 为增减"""
    set_total_reward: Optional[int] = None
    set_withdrawn_amount: Optional[int] = None
    set_pending_amount: Optional[int] = None
    add_total_reward: Optional[int] = None
    add_withdrawn_amount: Optional[int] = None
    add_pending_amount: Optional[int] = None


@app.put("/api/admin/commission/{user_id}")
async def admin_update_commission(
    user_id: str,
    payload: AdminCommissionUpdate,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """编辑指定用户的返利数据（总返利金额 / 已提现金额 / 待提现金额）"""
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    account = db.query(CommissionAccount).filter(CommissionAccount.user_id == user_id).first()
    if not account:
        account = CommissionAccount(user_id=user_id, total_reward=0, withdrawn_amount=0, pending_amount=0)
        db.add(account)
        db.flush()

    changes = []

    def apply(field: str, set_value, add_value) -> None:
        nonlocal account, changes
        old_value = int(getattr(account, field) or 0)
        if set_value is not None:
            if set_value < 0:
                raise HTTPException(status_code=400, detail=f"{field} 不能为负数")
            if set_value != old_value:
                setattr(account, field, set_value)
                changes.append(f"{field}: {old_value} → {set_value}")
        if add_value is not None:
            new_value = old_value + add_value
            if new_value < 0:
                raise HTTPException(status_code=400, detail=f"{field} 不足，无法扣除 {abs(add_value)}")
            setattr(account, field, new_value)
            action = "增加" if add_value >= 0 else "扣除"
            changes.append(f"{field}: {old_value} → {new_value} ({action} {abs(add_value)})")

    apply("total_reward", payload.set_total_reward, payload.add_total_reward)
    apply("withdrawn_amount", payload.set_withdrawn_amount, payload.add_withdrawn_amount)
    apply("pending_amount", payload.set_pending_amount, payload.add_pending_amount)

    if not changes:
        return {
            "success": False,
            "message": "未提供任何修改参数",
            "account": _commission_account_dict(db, user_id),
        }

    db.commit()
    log(f"管理员 {admin_user.username} 修改用户 {user.username} 返利数据：" + "；".join(changes), "ADMIN")
    return {
        "success": True,
        "message": "返利数据已更新：" + "；".join(changes),
        "account": _commission_account_dict(db, user_id),
    }


@app.get("/api/admin/commission/withdrawals")
async def admin_get_commission_withdrawals(
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """管理员获取返利提现申请列表"""
    query = db.query(WithdrawalRequest).options(joinedload(WithdrawalRequest.user))
    if status:
        query = query.filter(WithdrawalRequest.status == status)

    total = query.count()
    offset = (page - 1) * page_size
    requests = query.order_by(desc(WithdrawalRequest.created_at)).offset(offset).limit(page_size).all()

    result = []
    for req in requests:
        user = req.user
        result.append({
            "request_id": req.request_id,
            "user_id": req.user_id,
            "username": user.username if user else None,
            "phone": user.phone if user else None,
            "amount": int(req.amount or 0),
            "status": req.status,
            "note": req.note,
            "admin_note": req.admin_note,
            "processed_by": req.processed_by,
            "created_at": (req.created_at.isoformat() + "Z") if req.created_at else None,
            "processed_at": (req.processed_at.isoformat() + "Z") if req.processed_at else None,
        })

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
        "data": result,
    }


class AdminCommissionWithdrawalProcess(BaseModel):
    action: str
    admin_note: Optional[str] = None


@app.put("/api/admin/commission/withdrawals/{request_id}")
async def admin_process_commission_withdrawal(
    request_id: str,
    payload: AdminCommissionWithdrawalProcess,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """管理员审核返利提现申请（approve 通过 / reject 驳回）"""
    req = db.query(WithdrawalRequest).filter(
        WithdrawalRequest.request_id == request_id,
        WithdrawalRequest.status == "pending",
    ).with_for_update().first()

    if not req:
        existing = db.query(WithdrawalRequest.request_id).filter(
            WithdrawalRequest.request_id == request_id
        ).first()
        if not existing:
            raise HTTPException(status_code=404, detail="提现申请不存在")
        raise HTTPException(status_code=400, detail="该提现申请已处理，无需重复操作")

    action = (payload.action or "").strip().lower()
    if action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="操作类型只能是 approve 或 reject")

    # P1 修复（2026-09-11）：加 FOR UPDATE 行锁，防止与下单预留/订单审批并发时
    # 读-改-写覆盖（丢失更新）把 pending_amount 算错。
    account = db.query(CommissionAccount).filter(
        CommissionAccount.user_id == req.user_id
    ).with_for_update().first()
    if not account:
        account = CommissionAccount(user_id=req.user_id, total_reward=0, withdrawn_amount=0, pending_amount=0)
        db.add(account)
        db.flush()

    amount = int(req.amount or 0)
    pending = int(account.pending_amount or 0)

    if action == "approve":
        if pending < amount:
            raise HTTPException(status_code=400, detail="用户待提现金额不足，无法通过")
        account.pending_amount = pending - amount
        account.withdrawn_amount = int(account.withdrawn_amount or 0) + amount
        req.status = "approved"
        req.processed_by = admin_user.username
        req.admin_note = payload.admin_note
        req.processed_at = datetime.utcnow()
        # 将该用户的返利记录标记为已提现
        db.query(CommissionRecord).filter(CommissionRecord.recipient_user_id == req.user_id).update(
            {CommissionRecord.status: "withdrawn"},
            synchronize_session=False,
        )
        message = "提现申请已通过"
    else:
        if pending < amount:
            raise HTTPException(status_code=400, detail="用户待提现金额不足，无法驳回")
        account.pending_amount = pending - amount
        req.status = "rejected"
        req.processed_by = admin_user.username
        req.admin_note = payload.admin_note
        req.processed_at = datetime.utcnow()
        message = "提现申请已驳回，金额已退回可提现"

    db.commit()
    log(f"管理员 {admin_user.username} 处理返利提现 {request_id}（{action}，金额 {amount} 分）", "ADMIN")
    return {
        "success": True,
        "message": message,
        "account": _commission_account_dict(db, req.user_id),
    }


@app.get("/api/admin/orders")
async def admin_get_orders(
    status: Optional[str] = None,
    order_type: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """订单管理：统一返回充值/订阅订单与返利提现申请，带 type 区分"""
    items = []

    # 充值/订阅订单
    recharge_query = db.query(RechargeRequest).options(joinedload(RechargeRequest.user))
    if status:
        recharge_query = recharge_query.filter(RechargeRequest.status == status)
    for req in recharge_query.all():
        user = req.user
        plan = _extract_plan_from_note(req.note)
        is_sub = bool(plan)
        items.append({
            "type": "subscription" if is_sub else "recharge",
            "type_name": "订阅" if is_sub else "充值",
            "request_id": req.request_id,
            "user_id": req.user_id,
            "username": user.username if user else None,
            "phone": user.phone if user else None,
            "email": user.email if user else None,
            "amount": req.amount,
            "plan": plan,
            "plan_price": _plan_price(_get_plan_config(db, plan)) if plan else None,
            "status": req.status,
            "note": req.note,
            "admin_note": req.admin_note,
            "processed_by": req.processed_by,
            "created_at": (req.created_at.isoformat() + "Z") if req.created_at else None,
            "processed_at": (req.processed_at.isoformat() + "Z") if req.processed_at else None,
        })

    # 返利提现申请
    withdraw_query = db.query(WithdrawalRequest).options(joinedload(WithdrawalRequest.user))
    if status:
        withdraw_query = withdraw_query.filter(WithdrawalRequest.status == status)
    for req in withdraw_query.all():
        user = req.user
        items.append({
            "type": "withdraw",
            "type_name": "提现",
            "request_id": req.request_id,
            "user_id": req.user_id,
            "username": user.username if user else None,
            "phone": user.phone if user else None,
            "email": None,
            "amount": int(req.amount or 0),
            "plan": None,
            "plan_price": None,
            "status": req.status,
            "note": req.note,
            "admin_note": req.admin_note,
            "processed_by": req.processed_by,
            "created_at": (req.created_at.isoformat() + "Z") if req.created_at else None,
            "processed_at": (req.processed_at.isoformat() + "Z") if req.processed_at else None,
        })

    # 类型筛选
    if order_type == "recharge":
        items = [i for i in items if i["type"] in ("recharge", "subscription")]
    elif order_type == "subscription":
        items = [i for i in items if i["type"] == "subscription"]
    elif order_type == "withdraw":
        items = [i for i in items if i["type"] == "withdraw"]

    # 按创建时间倒序
    items.sort(key=lambda x: x["created_at"] or "", reverse=True)

    total = len(items)
    offset = (page - 1) * page_size
    page_items = items[offset:offset + page_size]

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, (total + page_size - 1) // page_size),
        "data": page_items,
    }


@app.get("/api/admin/statistics")
async def admin_get_statistics(
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """获取系统统计数据（管理员）"""
    from datetime import timedelta
    
    # 数据库统一存 UTC，统计口径用 UTC 日期（与 created_at/generated_at 一致）
    today = datetime.utcnow().date()
    tomorrow = today + timedelta(days=1)
    seven_days_ago = datetime.utcnow() - timedelta(days=7)

    # 所有计数合并为单条 SQL（1 次往返替代原 10 次串行 COUNT；
    # 今日口径用范围比较 [t0, t1) 替代 func.date()==today，可走索引）
    _t0 = datetime.combine(today, datetime.min.time())
    _t1 = datetime.combine(tomorrow, datetime.min.time())
    _stats = db.execute(text("""
        SELECT
            (SELECT COUNT(*) FROM users)                                                       AS total_users,
            (SELECT COUNT(*) FROM users WHERE created_at >= :t0 AND created_at < :t1)           AS today_new_users,
            (SELECT COUNT(*) FROM users WHERE last_call_date >= :sd)                           AS active_users,
            (SELECT COUNT(*) FROM teachings)                                                   AS total_teachings,
            (SELECT COUNT(*) FROM teachings WHERE generated_at >= :t0 AND generated_at < :t1)   AS today_new_teachings,
            (SELECT COUNT(*) FROM comments)                                                    AS total_comments,
            (SELECT COUNT(*) FROM teaching_likes)                                              AS total_likes,
            (SELECT COUNT(*) FROM favorites)                                                   AS total_favorites,
            (SELECT COALESCE(SUM(view_count), 0) FROM teachings)                               AS total_views,
            (SELECT COUNT(*) FROM recharge_requests WHERE status = 'pending')                  AS pending_recharge_count
    """), {"t0": _t0, "t1": _t1, "sd": seven_days_ago}).fetchone()
    total_users, today_new_users, active_users = _stats[0], _stats[1], _stats[2]
    total_teachings, today_new_teachings = _stats[3], _stats[4]
    total_comments, total_likes, total_favorites = _stats[5], _stats[6], _stats[7]
    total_views = _stats[8] or 0
    pending_recharge_count = _stats[9] or 0
    
    # 系统资源使用情况
    memory_info = {}
    try:
        import psutil
        import os
        process = psutil.Process(os.getpid())
        memory_info = {
            "rss_mb": round(process.memory_info().rss / 1024 / 1024, 2),
            "vms_mb": round(process.memory_info().vms / 1024 / 1024, 2),
            "percent": round(process.memory_percent(), 2)
        }
    except ImportError:
        memory_info = {"error": "psutil 未安装"}
    except Exception:
        memory_info = {"error": "无法获取内存信息"}
    
    # 数据库连接池状态
    try:
        pool = engine.pool
        db_status = {
            "pool_size": pool.size(),
            "checked_in": pool.checkedin(),
            "checked_out": pool.checkedout(),
            "overflow": pool.overflow(),
            "total_connections": pool.size() + pool.overflow()
        }
    except Exception:
        db_status = {"error": "无法获取连接池状态"}
    
    # HTML 缓存状态
    cache_status = {
        "size": len(_html_cache),
        "max_size": _cache_max_size
    }
    
    # 任务统计
    running_count = sum(1 for t in tasks.values() if t.status == "running")
    task_stats = {
        "total": len(tasks),
        "running": running_count,
        "pending": sum(1 for t in tasks.values() if t.status == "pending"),
        "completed": sum(1 for t in tasks.values() if t.status == "completed"),
        "failed": sum(1 for t in tasks.values() if t.status == "failed")
    }
    # pending_recharge_count 已并入上方聚合 SQL（_stats[9]）

    return {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "users": {
            "total": total_users,
            "today_new": today_new_users,
            "active_7days": active_users
        },
        "teachings": {
            "total": total_teachings,
            "today_new": today_new_teachings
        },
        "interactions": {
            "total_comments": total_comments,
            "total_likes": total_likes,
            "total_favorites": total_favorites,
            "total_views": total_views
        },
        "pending_recharge_count": pending_recharge_count,
        "system": {
            "memory": memory_info,
            "database": db_status,
            "cache": cache_status,
            "tasks": task_stats
        }
    }


@app.get("/api/admin/config")
async def admin_get_config(
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """获取系统配置（管理员）—— 数据库配置实时读取"""
    from config import get_admin_usernames

    def _read_config(key: str, default: str) -> str:
        row = db.query(SystemConfig).filter(SystemConfig.config_key == key).first()
        return row.config_value if row and row.config_value is not None and str(row.config_value).strip() != "" else default

    return {
        "beta_code": DEFAULT_BETA_CODE,
        "default_daily_max_calls": DEFAULT_DAILY_MAX_CALLS,
        "admin_usernames": get_admin_usernames(),
        # ⓪ 活动总控
        "invite_activity_enabled": int(_read_config("invite_activity_enabled", "1")),
        "invite_commission_enabled": int(_read_config("invite_commission_enabled", "1")),
        # ① 赠送与邀请额度
        "new_user_gift_quota": int(_read_config("new_user_gift_quota", "8")),
        "new_user_gift_valid_days": int(_read_config("new_user_gift_valid_days", "7")),
        "invited_extra_quota": int(_read_config("invited_extra_quota", "5")),
        "invited_extra_valid_days": int(_read_config("invited_extra_valid_days", "30")),
        "invite_reward_quota": int(_read_config("invite_reward_quota", "5")),
        "invite_reward_valid_days": int(_read_config("invite_reward_valid_days", "30")),
        "invite_reward_monthly_cap": int(_read_config("invite_reward_monthly_cap", "30")),
        # ② 返佣规则
        "commission_first_fen": _read_config("commission_first_fen", '{"monthly":1000,"quarterly":2500,"yearly":6000}'),
        "commission_renewal_pct": int(_read_config("commission_renewal_pct", "30")),
        "commission_inviter_paid": int(_read_config("commission_inviter_paid", "1")),
        "commission_freeze_days": int(_read_config("commission_freeze_days", "7")),
        # ③ 提现规则
        "withdraw_min_fen": int(_read_config("withdraw_min_fen", "5000")),
        "withdraw_monthly_times": int(_read_config("withdraw_monthly_times", "2")),
        # ④ 累计邀请里程碑
        "invite_milestones": _read_config(
            "invite_milestones",
            '[{"invited":3,"days":7,"label":"7天会员体验"},{"invited":10,"days":30,"label":"月度会员1个月"},{"invited":30,"days":90,"label":"季度会员1个季度"}]',
        ),
        "invite_manual_review_threshold": int(_read_config("invite_manual_review_threshold", "50")),
        # 套餐价格
        "plan_monthly": json.dumps(_get_plan_config(db, "monthly"), ensure_ascii=False),
        "plan_quarterly": json.dumps(_get_plan_config(db, "quarterly"), ensure_ascii=False),
        "plan_halfyear": json.dumps(_get_plan_config(db, "halfyear"), ensure_ascii=False),
        "plan_yearly": json.dumps(_get_plan_config(db, "yearly"), ensure_ascii=False),
        # 首页多态公告文案配置（4 态，每态 enabled/text/link）
        "home_announcement_states": _read_config(
            "home_announcement_states",
            DEFAULT_HOME_ANNOUNCEMENT_STATES_JSON,
        ),
    }


# ==================== 官方邀请码管理（注册须命中 official_invite_codes 表） ====================

class OfficialInviteCodeCreate(BaseModel):
    code: Optional[str] = None  # 留空则自动生成
    description: Optional[str] = None


@app.get("/api/admin/official-invite-codes")
async def admin_list_official_invite_codes(
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """列出全部官方邀请码（含启用状态与使用情况）"""
    del admin_user
    rows = db.query(OfficialInviteCode).order_by(OfficialInviteCode.created_at.desc()).all()
    return {
        "items": [
            {
                "id": r.id,
                "code": r.code,
                "isActive": bool(r.is_active),
                "description": r.description,
                "createdBy": r.created_by,
                "usedCount": int(r.used_count or 0),
                "lastUsedAt": (r.last_used_at.isoformat() + "Z") if r.last_used_at else None,
                "createdAt": (r.created_at.isoformat() + "Z") if r.created_at else None,
            }
            for r in rows
        ]
    }


@app.post("/api/admin/official-invite-codes")
async def admin_create_official_invite_code(
    payload: OfficialInviteCodeCreate,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """创建官方邀请码：不传 code 则自动生成（XSYY + 6 位易读字符）"""
    code = (payload.code or "").strip().upper()
    if not code:
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        code = "XSYY" + "".join(secrets.choice(alphabet) for _ in range(6))
    if not re.match(r"^[A-Za-z0-9]{4,16}$", code):
        raise HTTPException(status_code=400, detail="邀请码格式不合法（4-16 位字母或数字）")
    exists = db.query(OfficialInviteCode).filter(OfficialInviteCode.code == code).first()
    if exists:
        raise HTTPException(status_code=400, detail="该邀请码已存在")
    row = OfficialInviteCode(
        code=code,
        is_active=True,
        description=payload.description,
        created_by=admin_user.username if admin_user else "admin",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"success": True, "id": row.id, "code": row.code}


@app.post("/api/admin/official-invite-codes/{code_id}/toggle")
async def admin_toggle_official_invite_code(
    code_id: int,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """启停某个官方邀请码（停用后注册将不再接受该码）"""
    del admin_user
    row = db.query(OfficialInviteCode).filter(OfficialInviteCode.id == code_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="邀请码不存在")
    row.is_active = not row.is_active
    db.commit()
    return {"success": True, "id": row.id, "isActive": bool(row.is_active)}


class AdminConfigUpdate(BaseModel):
    """管理员更新数据库配置项（实时生效）。字段与 system_configs.config_key 同名。"""
    # ⓪ 活动总控
    invite_activity_enabled: Optional[int] = None    # 邀请返利活动总开关 0/1
    invite_commission_enabled: Optional[int] = None  # 返佣分发明细开关 0/1
    # ① 赠送与邀请额度
    new_user_gift_quota: Optional[int] = None        # 注册赠送额度（次）
    new_user_gift_valid_days: Optional[int] = None   # 注册赠送有效期（天）
    invited_extra_quota: Optional[int] = None        # 被邀额外赠送额度（次）
    invited_extra_valid_days: Optional[int] = None   # 被邀额外有效期（天）
    invite_reward_quota: Optional[int] = None        # 每邀请 1 人奖励额度（次）
    invite_reward_valid_days: Optional[int] = None   # 邀请奖励有效期（天）
    invite_reward_monthly_cap: Optional[int] = None  # 邀请奖励月上限（次）
    # ② 返佣规则
    commission_first_fen: Optional[str] = None       # 首单固定佣金 JSON 对象（分）
    commission_renewal_pct: Optional[int] = None     # 续费佣金百分比
    commission_inviter_paid: Optional[int] = None    # 1=仅已付费邀请人；0=任意邀请人
    commission_freeze_days: Optional[int] = None     # 佣金解冻期（天）
    # ③ 提现规则
    withdraw_min_fen: Optional[int] = None           # 最低提现金额（分）
    withdraw_monthly_times: Optional[int] = None     # 每月提现次数上限
    # ④ 累计邀请里程碑
    invite_milestones: Optional[str] = None          # JSON 数组 [{invited,days,label}]
    invite_manual_review_threshold: Optional[int] = None
    # 套餐价格
    plan_monthly: Optional[str] = None
    plan_quarterly: Optional[str] = None
    plan_halfyear: Optional[str] = None
    plan_yearly: Optional[str] = None
    # 首页多态公告文案配置（4 态）
    home_announcement_states: Optional[str] = None


CONFIG_FIELD_MAP = {
    # ⓪ 活动总控
    "invite_activity_enabled": "邀请返利活动总开关",
    "invite_commission_enabled": "返佣分发明细开关",
    # ① 赠送与邀请额度
    "new_user_gift_quota": "注册赠送额度（次）",
    "new_user_gift_valid_days": "注册赠送有效期（天）",
    "invited_extra_quota": "被邀额外赠送额度（次）",
    "invited_extra_valid_days": "被邀额外有效期（天）",
    "invite_reward_quota": "每邀请 1 人奖励额度（次）",
    "invite_reward_valid_days": "邀请奖励有效期（天）",
    "invite_reward_monthly_cap": "邀请奖励月度上限（次）",
    # ② 返佣规则
    "commission_first_fen": "订阅首单固定佣金（分）",
    "commission_renewal_pct": "续费佣金百分比",
    "commission_inviter_paid": "佣金资格（仅已付费邀请人）",
    "commission_freeze_days": "佣金解冻期（天）",
    # ③ 提现规则
    "withdraw_min_fen": "最低提现金额（分）",
    "withdraw_monthly_times": "每月提现次数上限",
    # ④ 里程碑
    "invite_milestones": "累计邀请里程碑",
    "invite_manual_review_threshold": "月度邀请告警阈值",
    "plan_monthly": "月度订阅价格",
    "plan_quarterly": "季度订阅价格",
    "plan_halfyear": "半年订阅价格",
    "plan_yearly": "年度订阅价格",
    "home_announcement_states": "首页多态公告文案配置",
}

# 需要 JSON 解析的配置项：value = (期望顶层类型, 说明)
CONFIG_JSON_FIELDS = {
    "plan_monthly": (dict, "月度订阅价格"),
    "plan_quarterly": (dict, "季度订阅价格"),
    "plan_halfyear": (dict, "半年订阅价格"),
    "plan_yearly": (dict, "年度订阅价格"),
    "commission_first_fen": (dict, "订阅首单固定佣金"),
    "invite_milestones": (list, "累计邀请里程碑"),
    "home_announcement_states": (dict, "首页多态公告文案配置"),
}


def _validate_home_announcement_states(obj: Any) -> None:
    """校验首页多态公告配置结构；非法整体抛出 ValueError（由 PUT 处理器转 400）。"""
    if not isinstance(obj, dict):
        raise ValueError("应为 JSON 对象")
    if not isinstance(obj.get("enabled"), bool):
        raise ValueError("缺少 enabled 布尔字段")
    states = obj.get("states")
    if not isinstance(states, dict):
        raise ValueError("缺少 states 对象")
    valid_keys = {"guest", "logged_in_quota", "member", "quota_exhausted"}
    if set(states.keys()) != valid_keys:
        raise ValueError("states 必须恰好包含 4 个固定态：guest / logged_in_quota / member / quota_exhausted")
    for key, val in states.items():
        if not isinstance(val, dict):
            raise ValueError(f"态 {key} 应为对象")
        if not isinstance(val.get("enabled"), bool):
            raise ValueError(f"态 {key} 缺少 enabled 布尔字段")
        text = val.get("text", "")
        if not isinstance(text, str) or len(text) > 1000:
            raise ValueError(f"态 {key} 文案须为字符串且 ≤1000 字")
        link = val.get("link", "")
        if link and not isinstance(link, str):
            raise ValueError(f"态 {key} 链接须为字符串")
        cta_text = val.get("cta_text", "")
        if cta_text and not isinstance(cta_text, str):
            raise ValueError(f"态 {key} CTA 按钮文字须为字符串")
        if isinstance(cta_text, str) and len(cta_text) > 50:
            raise ValueError(f"态 {key} CTA 按钮文字须 ≤ 50 字")


@app.put("/api/admin/config")
async def admin_update_config(
    payload: AdminConfigUpdate,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """更新系统配置（管理员）—— 写入 system_configs 表实时生效，并记录修改日志"""
    payload_dict = payload.model_dump(exclude_none=True) if hasattr(payload, "model_dump") else payload.dict(exclude_none=True)
    updates = {
        key: value
        for key, value in payload_dict.items()
        if key in CONFIG_FIELD_MAP and value is not None
    }

    if not updates:
        raise HTTPException(status_code=400, detail="没有提供要更新的配置项")

    changes: List[str] = []
    for key, new_value in updates.items():
        if key in CONFIG_JSON_FIELDS:
            # JSON 配置：按期望类型解析后规范化存储
            expect_type, label = CONFIG_JSON_FIELDS[key]
            try:
                parsed = json.loads(new_value)
                if not isinstance(parsed, expect_type):
                    raise ValueError(f"应为{'对象' if expect_type is dict else '数组'}")
                if key == "home_announcement_states":
                    # 额外结构校验（4 态 + 每态字段）
                    _validate_home_announcement_states(parsed)
                if key == "commission_first_fen":
                    for plan_id in ("monthly", "quarterly", "halfyear", "yearly"):
                        if int(parsed.get(plan_id) or 0) < 0:
                            raise ValueError("佣金不能为负数")
                if key == "invite_milestones":
                    for item in parsed:
                        if int(item.get("invited") or 0) <= 0 or int(item.get("days") or 0) <= 0:
                            raise ValueError("每条里程碑需含 invited(>0) 与 days(>0)")
            except Exception:
                raise HTTPException(status_code=400, detail=f"{label}格式不正确，应为JSON{'对象' if expect_type is dict else '数组'}")
            new_value = json.dumps(parsed, ensure_ascii=False)
        elif key in ("invite_activity_enabled", "invite_commission_enabled", "commission_inviter_paid"):
            if int(new_value) not in (0, 1):
                raise HTTPException(status_code=400, detail=f"{CONFIG_FIELD_MAP[key]}只能为 0 或 1")
        else:
            if int(new_value) < 0:
                raise HTTPException(status_code=400, detail=f"{CONFIG_FIELD_MAP[key]}不能为负数")

        old_row = db.query(SystemConfig).filter(SystemConfig.config_key == key).first()
        old_value = old_row.config_value if old_row else ""
        if old_row:
            old_row.config_value = str(new_value)
        else:
            db.add(SystemConfig(config_key=key, config_value=str(new_value), description=CONFIG_FIELD_MAP[key]))
        db.add(
            ConfigChangeLog(
                config_key=key,
                old_value=old_value,
                new_value=str(new_value),
                operator=admin_user.username,
            )
        )
        changes.append(f"{CONFIG_FIELD_MAP[key]}: {old_value or '未设置'} → {new_value}")

    db.commit()
    log(f"管理员 {admin_user.username} 更新系统配置：" + "；".join(changes), "ADMIN")
    return {
        "success": True,
        "message": "配置已更新并实时生效：" + "；".join(changes),
        "changes": changes,
    }


# ==================== 知识点标签框架管理 API（管理员） ====================

def _clear_knowledge_framework_cache():
    """清除知识点标签框架数据库缓存（在增删改后调用，确保下次读取最新数据）。"""
    global _KNOWLEDGE_FRAMEWORK_DB_CACHE, _KNOWLEDGE_FRAMEWORK_DB_CACHE_TIME
    _KNOWLEDGE_FRAMEWORK_DB_CACHE = None
    _KNOWLEDGE_FRAMEWORK_DB_CACHE_TIME = 0.0
    # 同步重置标签智能体的进程内标签库单例（2026-09-14 P1）：
    # 否则 agent 识别用的 TagLibrary 是进程级快照，管理后台改库后不重启看不到，
    # 会持续"识别不出新标签 / 对已有标签重复提案"。
    try:
        from tag_agent.client import reload_library as _reload_tag_agent_library
        _reload_tag_agent_library()
    except Exception as e:  # noqa: BLE001
        log(f"标签智能体库重置失败（不影响本次保存）: {e}", "WARN")


@app.get("/api/admin/knowledge-tag-framework")
async def admin_list_knowledge_tag_framework(
    page: int = 1,
    page_size: int = 20,
    version: Optional[str] = None,
    grade: Optional[str] = None,
    main_tag: Optional[str] = None,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """获取知识点标签框架列表（管理员，分页+筛选）"""
    from database.models import KnowledgeTagFramework

    query = db.query(KnowledgeTagFramework)

    if version:
        query = query.filter(KnowledgeTagFramework.version == version)
    if grade:
        query = query.filter(KnowledgeTagFramework.grade == grade)
    if main_tag:
        query = query.filter(KnowledgeTagFramework.main_tag == main_tag)

    query = query.order_by(KnowledgeTagFramework.id.desc())

    total = query.count()
    offset = (page - 1) * page_size
    rows = query.offset(offset).limit(page_size).all()

    result = []
    for row in rows:
        result.append({
            "id": row.id,
            "version": row.version,
            "grade": row.grade,
            "main_tag": row.main_tag,
            "sub_tag": row.sub_tag,
            "keyword": row.keyword,
            "created_at": (
                row.created_at.isoformat().replace("+00:00", "") + "Z"
                if row.created_at else None
            ),
        })

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
        "data": result
    }


@app.post("/api/admin/knowledge-tag-framework")
async def admin_add_knowledge_tag_framework(
    payload: dict,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """添加知识点标签（管理员）"""
    from database.models import KnowledgeTagFramework

    version = (payload.get("version") or "").strip()
    grade = (payload.get("grade") or "").strip()
    main_tag = (payload.get("main_tag") or "").strip()
    sub_tag = (payload.get("sub_tag") or "").strip()
    keyword = (payload.get("keyword") or "").strip()

    if not version or not grade or not main_tag or not sub_tag:
        raise HTTPException(status_code=400, detail="知识域、年级、章/单元、知识点标签均为必填项")

    # 检查是否已存在相同组合
    existing = db.query(KnowledgeTagFramework).filter(
        KnowledgeTagFramework.version == version,
        KnowledgeTagFramework.grade == grade,
        KnowledgeTagFramework.main_tag == main_tag,
        KnowledgeTagFramework.sub_tag == sub_tag,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="该标签组合已存在")

    new_tag = KnowledgeTagFramework(
        version=version,
        grade=grade,
        main_tag=main_tag,
        sub_tag=sub_tag,
        keyword=keyword or None,
    )
    db.add(new_tag)
    db.commit()
    db.refresh(new_tag)

    # 清除框架缓存
    _clear_knowledge_framework_cache()

    log(f"管理员 {admin_user.username} 添加了知识点标签: {version}/{grade}/{main_tag}/{sub_tag}", "ADMIN")

    return {
        "success": True,
        "message": "标签添加成功",
        "id": new_tag.id
    }


@app.put("/api/admin/knowledge-tag-framework/{tag_id}")
async def admin_update_knowledge_tag_framework(
    tag_id: int,
    payload: dict,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """编辑知识点标签（管理员）"""
    from database.models import KnowledgeTagFramework

    tag = db.query(KnowledgeTagFramework).filter(KnowledgeTagFramework.id == tag_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="标签不存在")

    version = payload.get("version")
    grade = payload.get("grade")
    main_tag = payload.get("main_tag")
    sub_tag = payload.get("sub_tag")

    if version is not None:
        version = version.strip()
        if not version:
            raise HTTPException(status_code=400, detail="知识域不能为空")
        tag.version = version
    if grade is not None:
        grade = grade.strip()
        if not grade:
            raise HTTPException(status_code=400, detail="年级不能为空")
        tag.grade = grade
    if main_tag is not None:
        main_tag = main_tag.strip()
        if not main_tag:
            raise HTTPException(status_code=400, detail="章/单元不能为空")
        tag.main_tag = main_tag
    if sub_tag is not None:
        sub_tag = sub_tag.strip()
        if not sub_tag:
            raise HTTPException(status_code=400, detail="知识点标签不能为空")
        tag.sub_tag = sub_tag
    keyword = payload.get("keyword")
    if keyword is not None:
        tag.keyword = keyword.strip() or None

    db.commit()

    # 清除框架缓存
    _clear_knowledge_framework_cache()

    log(f"管理员 {admin_user.username} 编辑了知识点标签 id={tag_id}", "ADMIN")

    return {
        "success": True,
        "message": "标签更新成功"
    }


@app.delete("/api/admin/knowledge-tag-framework/{tag_id}")
async def admin_delete_knowledge_tag_framework(
    tag_id: int,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """删除知识点标签（管理员）"""
    from database.models import KnowledgeTagFramework

    tag = db.query(KnowledgeTagFramework).filter(KnowledgeTagFramework.id == tag_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="标签不存在")

    db.delete(tag)
    db.commit()

    # 清除框架缓存
    _clear_knowledge_framework_cache()

    log(f"管理员 {admin_user.username} 删除了知识点标签 id={tag_id}", "ADMIN")

    return {
        "success": True,
        "message": "标签删除成功"
    }


# ===== 前端静态资源挂载到根路径 =====
# index.html 内引用的是根路径绝对资源（如 /css/auth.css、/xsyy-logo.webp），
# 因此除了 /web 挂载外，还需在根路径挂载 web 目录，使 http://host:port/ 直接打开前端。
# 注意：必须放在所有 @app.* 路由注册之后，否则会遮挡 /api/* 等接口路由。
if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web-root")


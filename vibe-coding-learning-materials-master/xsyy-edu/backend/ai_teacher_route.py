import hashlib
import asyncio
import json
import os
import re
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, AsyncIterator, Dict, List, Optional

import aiohttp
from openai import OpenAI
from fastapi import APIRouter, Depends, HTTPException

from kimi_config import (
    get_active_model,
    get_api_key,
    get_base_url,
    get_backup_api_key,
    get_backup_base_url,
    get_backup_model,
    get_params_for_model,
    is_backup_configured,
    is_timeout_error,
    record_success,
    record_failure,
)
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from auth import verify_token
from database import AITeachingQA, AITeachingSession, User, get_db

router = APIRouter(prefix='/api/ai-teacher', tags=['AITeacher'])
security = HTTPBearer(auto_error=False)
STORAGE_DIR = Path(__file__).resolve().parent.parent / 'storage'
CACHE_DIR = STORAGE_DIR / 'ai_teacher_cache'
FALLBACK_CACHE_FILE = CACHE_DIR / 'cache.json'
_AI_TABLES_READY = False
_KIMI_CLIENT: Optional[OpenAI] = None


class InitSummaryRequest(BaseModel):
    pageId: str
    content: str


class ChatRequest(BaseModel):
    sessionHash: str
    question: str
    recentHistory: List[dict] = Field(default_factory=list)


def generate_hash(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _truncate_text(text: str, max_len: int) -> str:
    return (text or '')[:max_len]


def _extract_gateway_text(result: Dict[str, Any]) -> str:
    if not isinstance(result, dict):
        return ''

    data = result.get('data')
    if isinstance(data, dict):
        choices = data.get('choices')
        if isinstance(choices, list) and choices:
            message = choices[0].get('message', {})
            if isinstance(message, dict) and message.get('content'):
                return str(message.get('content'))
        if data.get('content'):
            return str(data.get('content'))

    choices = result.get('choices')
    if isinstance(choices, list) and choices:
        message = choices[0].get('message', {})
        if isinstance(message, dict) and message.get('content'):
            return str(message.get('content'))
        delta = choices[0].get('delta', {})
        if isinstance(delta, dict) and delta.get('content'):
            return str(delta.get('content'))

    candidates = result.get('candidates')
    if isinstance(candidates, list) and candidates:
        parts = candidates[0].get('content', {}).get('parts', [])
        if parts and isinstance(parts[0], dict) and parts[0].get('text'):
            return str(parts[0].get('text'))

    if result.get('content'):
        return str(result.get('content'))
    if result.get('message'):
        return str(result.get('message'))
    if result.get('text'):
        return str(result.get('text'))
    return ''


def _extract_stream_chunk_text(payload: Dict[str, Any]) -> str:
    text = _extract_gateway_text(payload)
    if text:
        return text
    delta = payload.get('delta') if isinstance(payload, dict) else None
    if isinstance(delta, dict) and delta.get('content'):
        return str(delta.get('content'))
    return ''


def _normalize_recent_history(raw_history: List[dict]) -> List[dict]:
    normalized: List[dict] = []
    for item in raw_history[-4:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get('role', '')).strip().lower()
        if role in ('assistant', 'ai'):
            role = 'assistant'
        elif role in ('user', 'human'):
            role = 'user'
        else:
            continue
        content = str(item.get('content', '')).strip()
        if not content:
            continue
        normalized.append({'role': role, 'content': content})
    return normalized


def _format_recent_history(history: List[dict]) -> str:
    if not history:
        return 'none'
    lines: List[str] = []
    for item in history:
        speaker = 'User' if item.get('role') == 'user' else 'AI'
        lines.append(f"{speaker}: {item.get('content', '')}")
    return '\n'.join(lines)


def _tokenize_for_similarity(text: str) -> set[str]:
    tokens = set(re.findall(r'[\u4e00-\u9fffA-Za-z0-9]{2,}', (text or '').lower()))
    if tokens:
        return tokens
    return set(ch for ch in (text or '') if ch.strip())


def _extract_text_from_html(raw_html: str) -> str:
    if not raw_html:
        return ''
    text_value = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', raw_html, flags=re.I | re.S)
    text_value = re.sub(r'<[^>]+>', ' ', text_value)
    text_value = re.sub(r'\s+', ' ', text_value)
    return text_value.strip()


def _chinese_numeral_to_int(raw_value: str) -> Optional[int]:
    if not raw_value:
        return None
    raw_value = raw_value.strip()
    if not raw_value:
        return None

    if raw_value.isdigit():
        return int(raw_value)

    digit_map = {
        '零': 0,
        '一': 1,
        '二': 2,
        '两': 2,
        '三': 3,
        '四': 4,
        '五': 5,
        '六': 6,
        '七': 7,
        '八': 8,
        '九': 9,
    }

    if raw_value == '十':
        return 10

    if '十' in raw_value:
        parts = raw_value.split('十', 1)
        tens_part = parts[0]
        ones_part = parts[1] if len(parts) > 1 else ''
        tens = digit_map.get(tens_part, 1 if tens_part == '' else -1)
        if tens < 0:
            return None
        if ones_part == '':
            return tens * 10
        ones = digit_map.get(ones_part)
        if ones is None:
            return None
        return tens * 10 + ones

    return digit_map.get(raw_value)


def _extract_step_index(raw_marker: str) -> Optional[int]:
    if not raw_marker:
        return None

    match_digit = re.search(r'(\d+)', raw_marker)
    if match_digit:
        try:
            return int(match_digit.group(1))
        except ValueError:
            return None

    match_cn = re.search(r'第\s*([零一二两三四五六七八九十]+)\s*步', raw_marker)
    if match_cn:
        return _chinese_numeral_to_int(match_cn.group(1))

    match_cn_step = re.search(r'步骤\s*([零一二两三四五六七八九十]+)', raw_marker)
    if match_cn_step:
        return _chinese_numeral_to_int(match_cn_step.group(1))

    return None


def _extract_step_blocks(content: str, max_steps: int = 12) -> List[Dict[str, Any]]:
    normalized = re.sub(r'\s+', ' ', (content or '').strip())
    if not normalized:
        return []

    marker_pattern = re.compile(
        r'(第\s*[零一二两三四五六七八九十\d]+\s*步\s*[：:：\-]?|步骤\s*[零一二两三四五六七八九十\d]+\s*[：:：\-]?|step\s*\d+\s*[:：\-]?)',
        flags=re.I,
    )
    matches = list(marker_pattern.finditer(normalized))
    if not matches:
        return []

    blocks: List[Dict[str, Any]] = []
    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(normalized)
        segment = normalized[start:end].strip(' \n\t:：-')
        if not segment:
            continue
        marker = match.group(1)
        step_index = _extract_step_index(marker)
        blocks.append({
            'index': step_index if step_index is not None else (idx + 1),
            'marker': marker,
            'content': _truncate_text(segment, 420),
        })
        if len(blocks) >= max_steps:
            break

    return blocks


def _extract_question_step_index(question: str) -> Optional[int]:
    question = (question or '').strip()
    if not question:
        return None

    match_digit = re.search(r'第\s*(\d+)\s*步', question)
    if match_digit:
        return int(match_digit.group(1))

    match_cn = re.search(r'第\s*([零一二两三四五六七八九十]+)\s*步', question)
    if match_cn:
        return _chinese_numeral_to_int(match_cn.group(1))

    match_en = re.search(r'step\s*(\d+)', question, flags=re.I)
    if match_en:
        return int(match_en.group(1))

    return None


def _build_step_context(question: str, core_summary: str, page_content: str) -> str:
    step_index = _extract_question_step_index(question)
    if step_index is None:
        return ''

    source_text = page_content if (page_content or '').strip() else core_summary
    step_blocks = _extract_step_blocks(source_text)
    if not step_blocks:
        return f'用户提到第{step_index}步，但当前材料中未直接识别到显式步骤编号。请基于摘要推断并解释第{step_index}步。'

    exact_block = next((item for item in step_blocks if item.get('index') == step_index), None)
    if exact_block:
        return f"用户当前问题指向第{step_index}步。该步骤内容：{exact_block.get('content', '')}"

    sorted_blocks = sorted(step_blocks, key=lambda x: int(x.get('index', 0) or 0))
    nearest = min(sorted_blocks, key=lambda x: abs(int(x.get('index', 0) or 0) - step_index))
    return (
        f"用户当前问题指向第{step_index}步，但未找到完全同号步骤。"
        f"最接近的是第{nearest.get('index')}步，其内容：{nearest.get('content', '')}"
    )


def _load_content_from_storage(page_id: str) -> str:
    if not page_id:
        return ''

    task_dir = STORAGE_DIR / page_id
    if not task_dir.exists() or not task_dir.is_dir():
        return ''

    candidate_files = [
        task_dir / 'teaching.html',
        task_dir / 'teaching.txt',
        task_dir / 'content.txt',
        task_dir / 'index.html',
    ]

    for file_path in candidate_files:
        if file_path.exists() and file_path.is_file():
            try:
                raw_value = file_path.read_text(encoding='utf-8', errors='ignore')
            except Exception:
                continue
            if file_path.suffix.lower() == '.html':
                raw_value = _extract_text_from_html(raw_value)
            cleaned = (raw_value or '').strip()
            if cleaned:
                return cleaned[:10000]

    return ''


def _resolve_teaching_content(page_id: str, request_content: str) -> str:
    request_content = (request_content or '').strip()
    storage_content = _load_content_from_storage(page_id)

    if storage_content:
        return storage_content
    return request_content


def _load_fallback_cache() -> Dict[str, Any]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if not FALLBACK_CACHE_FILE.exists():
        return {'sessions': {}, 'qas': []}

    try:
        raw_value = FALLBACK_CACHE_FILE.read_text(encoding='utf-8', errors='ignore')
        parsed = json.loads(raw_value)
        if isinstance(parsed, dict):
            parsed.setdefault('sessions', {})
            parsed.setdefault('qas', [])
            return parsed
    except Exception:
        pass
    return {'sessions': {}, 'qas': []}


def _save_fallback_cache(cache_obj: Dict[str, Any]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    FALLBACK_CACHE_FILE.write_text(
        json.dumps(cache_obj, ensure_ascii=False, separators=(',', ':')),
        encoding='utf-8',
    )


def _fallback_get_session_summary(session_hash: str) -> Optional[str]:
    cache_obj = _load_fallback_cache()
    sessions = cache_obj.get('sessions', {})
    session_obj = sessions.get(session_hash)
    if isinstance(session_obj, dict):
        summary_value = session_obj.get('summary')
        if isinstance(summary_value, str) and summary_value.strip():
            return summary_value
    return None


def _fallback_save_session(session_hash: str, page_id: str, content_hash: str, summary: str) -> None:
    cache_obj = _load_fallback_cache()
    sessions = cache_obj.setdefault('sessions', {})
    sessions[session_hash] = {
        'session_hash': session_hash,
        'page_id': page_id,
        'content_full_hash': content_hash,
        'summary': summary,
        'created_at': datetime.utcnow().isoformat() + 'Z',
    }
    _save_fallback_cache(cache_obj)


def _fallback_find_similar_answer(session_hash: str, question: str, question_hash: str) -> Optional[str]:
    cache_obj = _load_fallback_cache()
    qas = cache_obj.get('qas', [])

    for qa in reversed(qas):
        if qa.get('session_hash') == session_hash and qa.get('question_hash') == question_hash:
            answer_summary = qa.get('answer_summary')
            if isinstance(answer_summary, str) and answer_summary.strip():
                return answer_summary

    threshold = float(os.getenv('AI_TEACHER_SIMILARITY_THRESHOLD', '0.8'))
    source_tokens = _tokenize_for_similarity(question)
    if not source_tokens:
        return None

    best_answer: Optional[str] = None
    best_score = 0.0
    for qa in reversed(qas[-100:]):
        if qa.get('session_hash') != session_hash:
            continue
        question_text = str(qa.get('question_text', ''))
        answer_summary = str(qa.get('answer_summary', ''))
        if not question_text or not answer_summary:
            continue
        candidate_tokens = _tokenize_for_similarity(question_text)
        if not candidate_tokens:
            continue
        overlap = len(source_tokens & candidate_tokens)
        union = max(1, len(source_tokens | candidate_tokens))
        score = overlap / union
        if score >= threshold and score > best_score:
            best_score = score
            best_answer = answer_summary

    return best_answer


def _fallback_save_qa(
    session_hash: str,
    user_id: str,
    question_hash: str,
    question_text: str,
    answer_text: str,
    recent_history: List[dict],
    model_name: str,
    source: str,
) -> None:
    cache_obj = _load_fallback_cache()
    qas = cache_obj.setdefault('qas', [])
    qas.append({
        'session_hash': session_hash,
        'user_id': user_id,
        'question_hash': question_hash,
        'question_text': question_text,
        'answer_summary': _truncate_text(answer_text, 200),
        'full_qa_data': {
            'question': question_text,
            'answer': answer_text,
            'recentHistory': recent_history,
            'model': model_name,
            'source': source,
        },
        'created_at': datetime.utcnow().isoformat() + 'Z',
    })

    if len(qas) > 5000:
        cache_obj['qas'] = qas[-5000:]
    _save_fallback_cache(cache_obj)


def _ensure_ai_tables(db: Session) -> None:
    global _AI_TABLES_READY
    if _AI_TABLES_READY:
        return

    db.execute(text(
        """
        CREATE TABLE IF NOT EXISTS ai_teaching_session (
            session_hash VARCHAR(64) PRIMARY KEY,
            page_id VARCHAR(128) NOT NULL,
            content_full_hash VARCHAR(64) NOT NULL,
            summary TEXT NOT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_ai_teaching_session_page_id (page_id),
            INDEX idx_ai_teaching_session_content_full_hash (content_full_hash),
            INDEX idx_ai_teaching_session_created_at (created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    ))
    db.execute(text(
        """
        CREATE TABLE IF NOT EXISTS ai_teaching_qa (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            session_hash VARCHAR(64) NOT NULL,
            user_id VARCHAR(36) NOT NULL,
            question_hash VARCHAR(64) NOT NULL,
            question_text TEXT NOT NULL,
            answer_summary TEXT NOT NULL,
            full_qa_data JSON NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_ai_teaching_qa_session_hash (session_hash),
            INDEX idx_ai_teaching_qa_user_id (user_id),
            INDEX idx_ai_teaching_qa_question_hash (question_hash),
            INDEX idx_ai_teaching_qa_created_at (created_at),
            CONSTRAINT fk_ai_teaching_qa_session_hash FOREIGN KEY (session_hash)
                REFERENCES ai_teaching_session(session_hash) ON DELETE CASCADE,
            CONSTRAINT fk_ai_teaching_qa_user_id FOREIGN KEY (user_id)
                REFERENCES users(user_id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    ))
    # 添加点赞表
    db.execute(text(
        """
        CREATE TABLE IF NOT EXISTS ai_teaching_like (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            qa_id BIGINT NOT NULL,
            user_id VARCHAR(36) NOT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uk_qa_user (qa_id, user_id),
            INDEX idx_ai_teaching_like_qa_id (qa_id),
            INDEX idx_ai_teaching_like_user_id (user_id),
            CONSTRAINT fk_ai_teaching_like_qa_id FOREIGN KEY (qa_id)
                REFERENCES ai_teaching_qa(id) ON DELETE CASCADE,
            CONSTRAINT fk_ai_teaching_like_user_id FOREIGN KEY (user_id)
                REFERENCES users(user_id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    ))
    db.commit()
    _AI_TABLES_READY = True


_KIMI_CLIENT: Optional[OpenAI] = None
_KIMI_MODEL = get_active_model()
_BACKUP_CLIENT: Optional[OpenAI] = None


def _get_kimi_client() -> OpenAI:
    global _KIMI_CLIENT
    if _KIMI_CLIENT is not None:
        return _KIMI_CLIENT

    api_key = get_api_key()
    if not api_key:
        raise RuntimeError('Missing KIMI_API_KEY')

    _KIMI_CLIENT = OpenAI(
        api_key=api_key,
        base_url=get_base_url(),
        timeout=600.0,
    )
    return _KIMI_CLIENT


def _get_backup_client() -> OpenAI:
    """获取备用模型 Client（默认模型超时/网络异常时切换，延迟初始化）。"""
    global _BACKUP_CLIENT
    if _BACKUP_CLIENT is not None:
        return _BACKUP_CLIENT

    api_key = get_backup_api_key()
    if not api_key:
        raise RuntimeError('备用模型未配置 BACKUP_MODEL_API_KEY，请在 .env 中配置')

    _BACKUP_CLIENT = OpenAI(
        api_key=api_key,
        base_url=get_backup_base_url(),
        timeout=600.0,
    )
    return _BACKUP_CLIENT


# AI 助教问答并发信号量（2026-09-01）：限制同时进行的 LLM 调用数，
# 防止大量用户并发问答时打爆 API 配额与线程池。超出排队等待（背压），不失败。
# 默认 20，可用 AI_LLM_MAX_CONCURRENCY 覆盖。
_AI_LLM_MAX_CONCURRENCY = int(os.getenv("AI_LLM_MAX_CONCURRENCY", "20"))
_ai_llm_semaphore = asyncio.Semaphore(_AI_LLM_MAX_CONCURRENCY)


async def _call_gateway_once(prompt: str, model_name: str) -> str:
    client = _get_kimi_client()

    def _generate(c: OpenAI, m: str) -> Any:
        return c.chat.completions.create(
            model=m,
            messages=[{'role': 'user', 'content': prompt}],
            max_completion_tokens=4096,
            **get_params_for_model(m),
        )

    try:
        async with _ai_llm_semaphore:
            response = await asyncio.to_thread(_generate, client, get_active_model())
        record_success()
        return response.choices[0].message.content or ''
    except Exception as exc:
        # 默认模型超时/网络异常 → 先切备用模型重试一次，而非直接失败
        if is_timeout_error(exc) and is_backup_configured():
            try:
                async with _ai_llm_semaphore:
                    response = await asyncio.to_thread(
                        _generate, _get_backup_client(), get_backup_model()
                    )
                record_success()
                return response.choices[0].message.content or ''
            except Exception as exc2:
                record_failure()
                raise
        record_failure()
        raise


async def _stream_gateway_answer(prompt: str, model_name: str) -> AsyncIterator[str]:
    full_text = await _call_gateway_once(prompt, model_name)
    chunk_size = 120
    for idx in range(0, len(full_text), chunk_size):
        yield full_text[idx: idx + chunk_size]


async def _get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    if not credentials or not credentials.credentials:
        raise HTTPException(status_code=401, detail='Unauthorized')

    user_id = verify_token(credentials.credentials)
    if not user_id:
        raise HTTPException(status_code=401, detail='Invalid token')

    try:
        user = db.query(User).filter(User.user_id == user_id).first()
    except SQLAlchemyError:
        return SimpleNamespace(user_id=user_id, username='token-user')
    if not user:
        raise HTTPException(status_code=401, detail='User not found')
    return user


def _build_summary_prompt(page_id: str, content: str) -> str:
    trimmed = _truncate_text(content, 8000)
    step_blocks = _extract_step_blocks(trimmed)
    if step_blocks:
        step_outline = '\n'.join([
            f"- 步骤{item.get('index')}：{_truncate_text(item.get('content', ''), 90)}"
            for item in step_blocks
        ])
    else:
        step_outline = '- 未识别到显式步骤编号，请按逻辑顺序提炼关键步骤。'
    return (
        '你是一个专业的数学助教。请阅读以下教学内容并按“解题步骤”理解后生成摘要。\n'
        '输出格式要求：\n'
        '1) 【原题与答案】先原样保留题目题干，再给出最终答案。\n'
        '2) 【核心思路】不超过180字。\n'
        '3) 【步骤索引】列出步骤1..N，每步1-2句，保留步骤编号。\n'
        '4) 【易错点】最多3条。\n'
        '总长度不超过1000字。仅输出摘要正文，不要额外解释。\n\n'
        f'页面ID：{page_id}\n\n'
        f'预识别步骤：\n{step_outline}\n\n'
        f'教学内容：\n{trimmed}'
    )


def _build_material_context(page_content: str) -> str:
    content = (page_content or '').strip()
    if not content:
        return ''
    max_chars = int(os.getenv('AI_TEACHER_MATERIAL_MAX_CHARS', '6000'))
    return _truncate_text(content, max_chars)


def _build_chat_prompt(
    core_summary: str,
    question: str,
    recent_history: List[dict],
    step_context: str = '',
    material_context: str = '',
) -> str:
    sections = [
        '你是一个专业的数学助教，必须严格遵守以下内容边界规则：',
        '1. 优先且主要依据下方【教学内容】作答；涉及具体步骤时，请引用对应步骤编号；',
        '2. 若问题超出教学内容范围，可以补充通用知识，但必须先标注：（以下为补充知识，非本题教学内容）；',
        '3. 回答应简洁、直接，无需重复问题本身。',
        f'【教学内容摘要】\n{core_summary}',
    ]
    if material_context:
        sections.append(f'【教学材料原文摘录】\n{material_context}')
    if step_context:
        sections.append(f'【步骤上下文】\n{step_context}')
    if recent_history:
        sections.append(f'【最近对话历史】\n{_format_recent_history(recent_history)}')
    sections.append(f'【用户当前问题】\n{question}')
    return '\n\n'.join(sections)


def _to_sse(payload: Dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _find_similar_cached_answer(db: Session, session_hash: str, question: str, question_hash: str) -> Optional[str]:
    exact_hit = (
        db.query(AITeachingQA)
        .filter(
            AITeachingQA.session_hash == session_hash,
            AITeachingQA.question_hash == question_hash,
        )
        .order_by(AITeachingQA.created_at.desc())
        .first()
    )
    if exact_hit and exact_hit.answer_summary:
        return exact_hit.answer_summary

    threshold = float(os.getenv('AI_TEACHER_SIMILARITY_THRESHOLD', '0.8'))
    source_tokens = _tokenize_for_similarity(question)
    if not source_tokens:
        return None

    candidates = (
        db.query(AITeachingQA)
        .filter(AITeachingQA.session_hash == session_hash)
        .order_by(AITeachingQA.created_at.desc())
        .limit(50)
        .all()
    )

    best_answer: Optional[str] = None
    best_score = 0.0
    for candidate in candidates:
        if not candidate.question_text or not candidate.answer_summary:
            continue
        candidate_tokens = _tokenize_for_similarity(candidate.question_text)
        if not candidate_tokens:
            continue
        overlap = len(source_tokens & candidate_tokens)
        union = max(1, len(source_tokens | candidate_tokens))
        score = overlap / union
        if score >= threshold and score > best_score:
            best_score = score
            best_answer = candidate.answer_summary

    return best_answer


@router.post('/init-summary')
async def init_summary(
    req: InitSummaryRequest,
    user: User = Depends(_get_current_user),
    db: Session = Depends(get_db),
):
    page_id = (req.pageId or '').strip() or 'default-page'
    content = _resolve_teaching_content(page_id, req.content)
    if not content:
        raise HTTPException(status_code=400, detail='content is required')

    content_hash = generate_hash(content)
    session_hash = generate_hash(f'{page_id}_{content_hash}')

    model_name = get_active_model()

    try:
        _ensure_ai_tables(db)

        existing = db.query(AITeachingSession).filter(AITeachingSession.session_hash == session_hash).first()
        if existing:
            return {
                'sessionHash': existing.session_hash,
                'summary': existing.summary,
            }
    except SQLAlchemyError:
        db.rollback()
        existing_summary = _fallback_get_session_summary(session_hash)
        if existing_summary:
            return {
                'sessionHash': session_hash,
                'summary': existing_summary,
            }

    summary_prompt = _build_summary_prompt(page_id=page_id, content=content)
    summary_raw = await _call_gateway_once(summary_prompt, model_name)
    summary = _truncate_text(summary_raw.strip(), 1000)
    if not summary:
        summary = _truncate_text(content, 1000)

    try:
        _ensure_ai_tables(db)
        session_row = AITeachingSession(
            session_hash=session_hash,
            page_id=page_id,
            content_full_hash=content_hash,
            summary=summary,
            created_at=datetime.utcnow(),
        )
        db.add(session_row)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        _fallback_save_session(session_hash, page_id, content_hash, summary)

    return {
        'sessionHash': session_hash,
        'summary': summary,
    }


@router.post('/chat')
async def ai_chat(
    req: ChatRequest,
    user: User = Depends(_get_current_user),
    db: Session = Depends(get_db),
):
    session_hash = (req.sessionHash or '').strip()
    question = (req.question or '').strip()
    if not session_hash:
        raise HTTPException(status_code=400, detail='sessionHash is required')
    if not question:
        raise HTTPException(status_code=400, detail='question is required')

    db_usable = True
    try:
        _ensure_ai_tables(db)
        session_row = db.query(AITeachingSession).filter(AITeachingSession.session_hash == session_hash).first()
        core_summary = session_row.summary if session_row else None
    except SQLAlchemyError:
        db.rollback()
        db_usable = False
        core_summary = _fallback_get_session_summary(session_hash)

    if not core_summary:
        raise HTTPException(status_code=404, detail='Session not found, call init-summary first')

    page_content = ''
    if db_usable and session_row and getattr(session_row, 'page_id', None):
        page_content = _load_content_from_storage(str(session_row.page_id))

    step_index = _extract_question_step_index(question)
    step_context = _build_step_context(question=question, core_summary=core_summary, page_content=page_content)
    material_context = _build_material_context(page_content)
    recent_history = _normalize_recent_history(req.recentHistory or [])
    question_hash = generate_hash(question)

    # 用户明确问“第x步”时，优先走模型推理，避免命中旧缓存导致步骤解释不完整。
    if step_index is not None:
        cached_answer = None
    elif db_usable:
        cached_answer = _find_similar_cached_answer(db, session_hash, question, question_hash)
    else:
        cached_answer = _fallback_find_similar_answer(session_hash, question, question_hash)
    model_name = get_active_model()

    async def event_generator() -> AsyncIterator[str]:
        answer_buffer: List[str] = []
        source = 'llm'

        try:
            if cached_answer:
                source = 'cache'
                answer_text = _truncate_text(cached_answer, 1200)
                answer_buffer.append(answer_text)
                yield _to_sse({'type': 'chunk', 'content': answer_text, 'cached': True})
            else:
                prompt = _build_chat_prompt(
                    core_summary,
                    question,
                    recent_history,
                    step_context=step_context,
                    material_context=material_context,
                )
                async for chunk in _stream_gateway_answer(prompt, model_name):
                    if not chunk:
                        continue
                    answer_buffer.append(chunk)
                    yield _to_sse({'type': 'chunk', 'content': chunk, 'cached': False})

            answer_text = ''.join(answer_buffer).strip()
            if answer_text:
                if db_usable:
                    try:
                        qa_row = AITeachingQA(
                            session_hash=session_hash,
                            user_id=user.user_id,
                            question_hash=question_hash,
                            question_text=question,
                            answer_summary=_truncate_text(answer_text, 200),
                            full_qa_data={
                                'question': question,
                                'answer': answer_text,
                                'recentHistory': recent_history,
                                'model': model_name,
                                'source': source,
                            },
                            created_at=datetime.utcnow(),
                        )
                        db.add(qa_row)
                        db.commit()
                    except SQLAlchemyError:
                        db.rollback()
                        _fallback_save_qa(
                            session_hash=session_hash,
                            user_id=user.user_id,
                            question_hash=question_hash,
                            question_text=question,
                            answer_text=answer_text,
                            recent_history=recent_history,
                            model_name=model_name,
                            source=source,
                        )
                else:
                    _fallback_save_qa(
                        session_hash=session_hash,
                        user_id=user.user_id,
                        question_hash=question_hash,
                        question_text=question,
                        answer_text=answer_text,
                        recent_history=recent_history,
                        model_name=model_name,
                        source=source,
                    )

            yield _to_sse({'type': 'done'})
        except HTTPException as exc:
            yield _to_sse({'type': 'error', 'message': exc.detail})
        except Exception as exc:
            yield _to_sse({'type': 'error', 'message': f'AI service error: {str(exc)}'})

    return StreamingResponse(event_generator(), media_type='text/event-stream')


@router.get('/history')
async def get_history(
    pageId: str,
    user: User = Depends(_get_current_user),
    db: Session = Depends(get_db),
    limit: int = 20,
    offset: int = 0,
):
    """获取指定页面的历史对话记录"""
    if not pageId:
        raise HTTPException(status_code=400, detail='pageId is required')

    try:
        _ensure_ai_tables(db)
        
        # 首先获取该页面的所有会话
        sessions = db.query(AITeachingSession).filter(
            AITeachingSession.page_id == pageId
        ).all()
        
        session_hashes = [session.session_hash for session in sessions]
        
        if not session_hashes:
            return {'history': []}
        
        # 查询这些会话的所有问答记录
        history_records = db.query(AITeachingQA).filter(
            AITeachingQA.session_hash.in_(session_hashes),
            AITeachingQA.user_id == user.user_id
        ).order_by(
            AITeachingQA.created_at.desc()
        ).limit(limit).offset(offset).all()
        
        # 一次聚合查询本页所有记录的点赞数（替代原来的 N+1 逐条 COUNT）
        # 注意：ai_teaching_like 表可能尚未建立（生产/测试库历史缺失），
        # 聚合失败时降级为 likes=0，不影响主历史数据展示。
        from sqlalchemy import text
        like_map = {}
        if history_records:
            try:
                like_rows = db.execute(
                    text(
                        "SELECT qa_id, COUNT(*) AS c FROM ai_teaching_like "
                        "WHERE qa_id IN :qa_ids GROUP BY qa_id"
                    ),
                    {'qa_ids': [r.id for r in history_records]}
                ).fetchall()
                like_map = {row[0]: row[1] for row in like_rows}
            except SQLAlchemyError:
                like_map = {}

        # 构建返回数据
        history = []
        for record in history_records:
            # 从full_qa_data中获取完整的answer，如果没有则使用answer_summary
            full_answer = record.answer_summary
            if record.full_qa_data:
                try:
                    full_answer = record.full_qa_data.get('answer', record.answer_summary)
                except Exception:
                    pass

            history.append({
                'id': record.id,
                'user_id': record.user_id,
                'question': record.question_text,
                'answer': full_answer,
                'likes': like_map.get(record.id, 0),
                'created_at': record.created_at.isoformat()
            })
        
        return {'history': history}
    
    except SQLAlchemyError as e:
        db.rollback()
        # 数据库错误时使用fallback
        return _get_fallback_history(pageId, user.user_id, limit, offset)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'获取历史记录失败: {str(e)}')


def _get_fallback_history(pageId: str, user_id: str, limit: int, offset: int):
    """从fallback缓存中获取历史记录"""
    cache_obj = _load_fallback_cache()
    qas = cache_obj.get('qas', [])
    
    # 过滤出该用户在指定页面的记录
    filtered_qas = []
    for qa in qas:
        # 从session_hash中提取page_id
        session_hash = qa.get('session_hash', '')
        if not session_hash:
            continue
        
        # 尝试从缓存中获取session信息，找到对应的page_id
        sessions = cache_obj.get('sessions', {})
        session_info = sessions.get(session_hash, {})
        if session_info.get('page_id') == pageId and qa.get('user_id') == user_id:
            filtered_qas.append(qa)
    
    # 按创建时间倒序排序
    filtered_qas.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    
    # 应用分页
    paginated_qas = filtered_qas[offset:offset + limit]
    
    # 构建返回数据
    history = []
    for idx, qa in enumerate(paginated_qas, offset + 1):
        history.append({
            'id': idx,  # 临时ID
            'user_id': qa.get('user_id', ''),
            'question': qa.get('question_text', ''),
            'answer': qa.get('full_qa_data', {}).get('answer', qa.get('answer_summary', '')),
            'likes': 0,  # 暂时设为0
            'created_at': qa.get('created_at', '')
        })
    
    return {'history': history}


class LikeRequest(BaseModel):
    itemId: int


class DeleteRequest(BaseModel):
    itemId: int


@router.post('/history/like')
async def like_history(
    req: LikeRequest,
    user: User = Depends(_get_current_user),
    db: Session = Depends(get_db),
):
    """点赞历史记录"""
    item_id = req.itemId
    
    try:
        _ensure_ai_tables(db)
        
        # 查找记录
        record = db.query(AITeachingQA).filter(
            AITeachingQA.id == item_id
        ).first()
        
        if not record:
            raise HTTPException(status_code=404, detail='记录不存在')
        
        # 幂等点赞：INSERT IGNORE 依赖 uk_qa_user(qa_id, user_id) 唯一键防并发重复，
        # 无论本次是新增还是已存在，最终统一查询一次点赞数（合并原两处重复 COUNT）。
        from sqlalchemy import text
        db.execute(
            text("INSERT IGNORE INTO ai_teaching_like (qa_id, user_id) VALUES (:qa_id, :user_id)"),
            {'qa_id': item_id, 'user_id': user.user_id}
        )
        db.commit()
        
        # 计算点赞数
        like_count = db.execute(
            text("SELECT COUNT(*) as count FROM ai_teaching_like WHERE qa_id = :qa_id"),
            {'qa_id': item_id}
        ).fetchone()[0]
        
        return {'success': True, 'likes': like_count}
    
    except SQLAlchemyError as e:
        db.rollback()
        # 数据库错误时返回成功（fallback）
        return {'success': True, 'likes': 1}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'点赞失败: {str(e)}')


@router.post('/history/delete')
async def delete_history(
    req: DeleteRequest,
    user: User = Depends(_get_current_user),
    db: Session = Depends(get_db),
):
    """删除历史记录"""
    item_id = req.itemId
    
    try:
        _ensure_ai_tables(db)
        
        # 查找并删除记录
        result = db.query(AITeachingQA).filter(
            AITeachingQA.id == item_id,
            AITeachingQA.user_id == user.user_id
        ).delete()
        
        if result == 0:
            raise HTTPException(status_code=404, detail='记录不存在')
        
        db.commit()
        return {'success': True}
    
    except SQLAlchemyError as e:
        db.rollback()
        # 数据库错误时返回成功（fallback）
        return {'success': True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'删除失败: {str(e)}')

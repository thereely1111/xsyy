# -*- coding: utf-8 -*-
"""标签识别智能体数据模型。

四张表：
    tag_agent_pending_tags     — 预修改审核队列（原"预加入库"，阶段二扩展为增/改/删/合并四类操作）
    tag_agent_question_proposals — 题目标签审核队列（题目级标签，阶段二新增）
    tag_agent_learning_records — 学习闭环记录（方案"九"）
    tag_agent_recognition_logs — 识别日志（准确率监控）
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from tag_agent.db import Base


class PendingTagStatus:
    """预修改标签状态常量（方案"五.4"第 10 项）."""

    PENDING = "pending"                    # 待审核
    APPROVED = "approved"                  # 已通过
    APPROVED_MODIFIED = "approved_modified"  # 已修改通过
    MERGED = "merged"                      # 已合并到已有标签
    REJECTED = "rejected"                  # 已驳回


class PendingTagOperation:
    """预修改操作类型（阶段二：增/改/删/合并）."""

    ADD = "add"          # 新增（原预加入）
    MODIFY = "modify"    # 修改已有标签（字段级）
    DELETE = "delete"    # 删除/下线已有标签（硬删除，管理员确认后）
    MERGE = "merge"      # 合并重复标签


class QuestionTagProposalStatus:
    """题目标签审核队列状态."""

    PENDING = "pending"                  # 待审核
    APPROVED = "approved"                # 已通过（已写题目标签）
    APPROVED_MODIFIED = "approved_modified"  # 修改后通过
    REJECTED = "rejected"                # 已驳回


class PendingTag(Base):
    """预修改审核队列记录.

    智能体对正式标签库的所有操作（新增/修改/删除/合并）只能写入本表，
    等待管理员在管理后台审核，不能直接写入正式标签库。
    operation 默认 add，兼容阶段一之前的"预加入"语义。
    """

    __tablename__ = "tag_agent_pending_tags"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4()),
    )
    # 操作类型：add / modify / delete / merge（阶段二）
    operation: Mapped[str] = mapped_column(
        String(20), default=PendingTagOperation.ADD, index=True,
    )
    # 标签链路：知识域 → 年级 → 章/单元 → 知识点标签
    domain: Mapped[str] = mapped_column(String(50), default="")
    grade: Mapped[str] = mapped_column(String(10), default="")
    chapter: Mapped[str] = mapped_column(String(100), default="")
    tag_name: Mapped[str] = mapped_column(String(100), default="")
    keywords: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)  # 关键词集合

    # 被操作标签定位（modify/delete/merge 使用）
    target_domain: Mapped[str] = mapped_column(String(50), default="")
    target_grade: Mapped[str] = mapped_column(String(10), default="")
    target_chapter: Mapped[str] = mapped_column(String(100), default="")
    target_tag: Mapped[str] = mapped_column(String(100), default="")
    # 操作前后快照（modify/delete 使用）
    before_snapshot: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    after_snapshot: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # 提案依据（示例题目 / 相似度 / 纠错来源）
    evidence: Mapped[str] = mapped_column(Text, default="")

    # 来源与创建者
    source_question_id: Mapped[str] = mapped_column(String(100), default="")
    source_question_text: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(36), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(),
    )

    # 状态与审核
    status: Mapped[str] = mapped_column(String(20), default=PendingTagStatus.PENDING, index=True)
    agent_reason: Mapped[str] = mapped_column(Text, default="")   # 智能体生成理由
    confidence: Mapped[float] = mapped_column(Float, default=0.0)  # 智能体置信度
    reviewed_by: Mapped[str] = mapped_column(String(36), default="")
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    admin_note: Mapped[str] = mapped_column(Text, default="")
    # 驳回原因（action=reject 时必填，供智能体学习"为什么被驳回"）
    reject_reason: Mapped[str] = mapped_column(Text, default="")
    # 审核变更记录（每次审核/重新审核追加一条，记录 from→to / 操作 / 原因）
    review_history: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    # 临时使用（方案"八"）：使用该预加入标签的题目 ID 列表
    temp_question_ids: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    # 场景三专用字段（章/单元级别候选需更严格审核）
    is_chapter_level: Mapped[bool] = mapped_column(Boolean, default=False)
    candidate_chapters: Mapped[Optional[list]] = mapped_column(
        JSON, nullable=True,  # 候选相近章/单元列表
    )
    no_match_reason: Mapped[str] = mapped_column(Text, default="")  # 无法匹配章/单元原因

    # 合并到已有标签时记录目标标签（审核操作"合并"）
    merged_to_tag: Mapped[str] = mapped_column(String(100), default="")

    def to_dict(self) -> dict:
        """转为字典（供 API 返回）. """
        return {
            "id": self.id,
            "operation": self.operation,
            "domain": self.domain,
            "grade": self.grade,
            "chapter": self.chapter,
            "tag_name": self.tag_name,
            "keywords": self.keywords or [],
            "target": {
                "domain": self.target_domain,
                "grade": self.target_grade,
                "chapter": self.target_chapter,
                "tag": self.target_tag,
            },
            "before_snapshot": self.before_snapshot,
            "after_snapshot": self.after_snapshot,
            "evidence": self.evidence,
            "source_question_id": self.source_question_id,
            "source_question_text": self.source_question_text,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "status": self.status,
            "agent_reason": self.agent_reason,
            "confidence": self.confidence,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "admin_note": self.admin_note,
            "reject_reason": self.reject_reason or "",
            "review_history": self.review_history or [],
            "temp_question_ids": self.temp_question_ids or [],
            "is_chapter_level": self.is_chapter_level,
            "candidate_chapters": self.candidate_chapters or [],
            "no_match_reason": self.no_match_reason,
            "merged_to_tag": self.merged_to_tag,
        }


class QuestionTagProposal(Base):
    """题目标签审核队列（阶段二新增，落实"题目级标签全人工审核"决策）.

    智能体对单道题目的标签建议先写入本表，管理员确认（可批量）后
    才写入题目的 knowledge_tags 并触发动画生成。
    """

    __tablename__ = "tag_agent_question_proposals"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4()),
    )
    question_id: Mapped[str] = mapped_column(String(100), default="", index=True)
    question_text: Mapped[str] = mapped_column(Text, default="")
    # 建议标签（agent 识别结果，四级结构）
    domain: Mapped[str] = mapped_column(String(50), default="")
    grade: Mapped[str] = mapped_column(String(10), default="")
    chapter: Mapped[str] = mapped_column(String(100), default="")
    sub_tags: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    source_action: Mapped[str] = mapped_column(String(30), default="")   # 识别 action
    # 审核状态
    status: Mapped[str] = mapped_column(
        String(20), default=QuestionTagProposalStatus.PENDING, index=True,
    )
    applied: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否已写题目标签
    reviewed_by: Mapped[str] = mapped_column(String(36), default="")
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    admin_note: Mapped[str] = mapped_column(Text, default="")
    # 驳回原因（action=reject 时必填，供智能体学习"为什么被驳回"）
    reject_reason: Mapped[str] = mapped_column(Text, default="")
    # 审核变更记录（每次审核/重新审核追加一条，记录 from→to / 操作 / 原因）
    review_history: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # 智能体识别原始输出（学习/日志用）
    agent_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "question_id": self.question_id,
            "question_text": self.question_text[:200],
            "domain": self.domain,
            "grade": self.grade,
            "chapter": self.chapter,
            "sub_tags": self.sub_tags or [],
            "confidence": self.confidence,
            "source_action": self.source_action,
            "status": self.status,
            "applied": self.applied,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "admin_note": self.admin_note,
            "reject_reason": self.reject_reason or "",
            "review_history": self.review_history or [],
            "agent_data": self.agent_data,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class TagLearningRecord(Base):
    """学习闭环记录（方案"九"）.

    记录每次智能体创建标签、提取关键词、管理员审核结论与修改前后差异，
    用于提升后续判断是否需要生成新标签、命名是否精炼、关键词是否可复用。
    """

    __tablename__ = "tag_agent_learning_records"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4()),
    )
    # 行为类型：create_pending / extract_keyword / review_approve /
    # review_modified / review_merge / review_reject
    action_type: Mapped[str] = mapped_column(String(50), index=True)
    question_id: Mapped[str] = mapped_column(String(100), default="", index=True)
    # 本次涉及的知识域/年级/章/单元/知识点标签
    domain: Mapped[str] = mapped_column(String(50), default="")
    grade: Mapped[str] = mapped_column(String(10), default="")
    chapter: Mapped[str] = mapped_column(String(100), default="")
    tag_name: Mapped[str] = mapped_column(String(100), default="")
    # 智能体原始输出
    agent_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # 管理员操作结果 / 修改前后差异（学习样本）
    admin_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "action_type": self.action_type,
            "question_id": self.question_id,
            "domain": self.domain,
            "grade": self.grade,
            "chapter": self.chapter,
            "tag_name": self.tag_name,
            "agent_data": self.agent_data,
            "admin_data": self.admin_data,
            "note": self.note,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class RecognitionLog(Base):
    """识别日志（准确率监控）.

    每次识别记录题目、判定结果、动作与置信度，用于量化监控。
    """

    __tablename__ = "tag_agent_recognition_logs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4()),
    )
    question: Mapped[str] = mapped_column(Text, default="")
    is_math_problem: Mapped[bool] = mapped_column(Boolean, default=True)
    domain: Mapped[str] = mapped_column(String(50), default="")
    grade: Mapped[str] = mapped_column(String(10), default="")
    chapter: Mapped[str] = mapped_column(String(100), default="")
    tag_name: Mapped[str] = mapped_column(String(100), default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    # 动作：inject_official / add_keywords / create_pending_tag /
    # create_pending_chain / non_math / low_confidence
    action: Mapped[str] = mapped_column(String(30), default="")
    matched_existing: Mapped[bool] = mapped_column(Boolean, default=True)
    pending_tag_id: Mapped[str] = mapped_column(String(36), default="")
    raw_result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "question": self.question[:200],
            "is_math_problem": self.is_math_problem,
            "domain": self.domain,
            "grade": self.grade,
            "chapter": self.chapter,
            "tag_name": self.tag_name,
            "confidence": self.confidence,
            "action": self.action,
            "matched_existing": self.matched_existing,
            "pending_tag_id": self.pending_tag_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

# ============================================================================
# P1.5 补丁：追加到 backend/tag_agent/models.py 末尾
# 作用：新增「标签增强建议」审核表 LabelSuggestion（tag_agent_label_suggestions）。
# 合并方式：整段复制到 models.py 末尾即可（所需 import 已在文件顶部）。
# 建表：app 启动时 tag_agent.db.create_tables() 会 Base.metadata.create_all 自动建表。
# ============================================================================

class LabelSuggestionStatus:
    """标签增强建议状态（复用标签审核闭环的 pending/approved/rejected 语义）."""

    PENDING = "pending"        # 待审核
    APPROVED = "approved"      # 已通过（判词已并入词库）
    REJECTED = "rejected"      # 已驳回


class LabelSuggestion(Base):
    """标签增强建议审核队列（P1.5：管理员改标签自动提炼可泛化强关键词）.

    管理员在「教学内容-编辑内容」保存标签更改后，对“变更后新增/替换到的正式标签 B”
    自动提炼候选强关键词并干跑回验，写入本表；管理员审核通过后并入标签 B 的
    关键词集合（framework_sync 回写），全程人工把关、不通过不入库。
    """

    __tablename__ = "tag_agent_label_suggestions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4()),
    )
    # 来源题（管理员改标签的那道题）
    task_id: Mapped[str] = mapped_column(String(100), default="", index=True)
    question_text: Mapped[str] = mapped_column(Text, default="")  # 来源题干（提案依据）

    # 改前标签（sub_tags 列表，供审核人看“新旧标签对照”）
    old_tags: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    # 新标签 B（被增强的正式标签）
    new_tag: Mapped[str] = mapped_column(String(100), default="", index=True)
    new_tag_domain: Mapped[str] = mapped_column(String(50), default="")
    new_tag_grade: Mapped[str] = mapped_column(String(10), default="")
    new_tag_chapter: Mapped[str] = mapped_column(String(100), default="")

    # 候选强关键词（每条含泛化理由 + 干跑命中数 + 命中样例 + 是否疑似过窄）
    # 结构：[{"keyword","reason","hits":int,"hit_samples":[str],"too_narrow":bool}, ...]
    candidates: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    # 审核状态
    status: Mapped[str] = mapped_column(
        String(20), default=LabelSuggestionStatus.PENDING, index=True,
    )
    created_by: Mapped[str] = mapped_column(String(36), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    reviewed_by: Mapped[str] = mapped_column(String(36), default="")
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    admin_note: Mapped[str] = mapped_column(Text, default="")
    reject_reason: Mapped[str] = mapped_column(Text, default="")
    review_history: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "question_text": (self.question_text or "")[:200],
            "old_tags": self.old_tags or [],
            "new_tag": self.new_tag,
            "new_tag_domain": self.new_tag_domain,
            "new_tag_grade": self.new_tag_grade,
            "new_tag_chapter": self.new_tag_chapter,
            "candidates": self.candidates or [],
            "status": self.status,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "admin_note": self.admin_note,
            "reject_reason": self.reject_reason or "",
            "review_history": self.review_history or [],
        }
# ============================================================================
# P3 补丁：追加到 backend/tag_agent/models.py 末尾
# 作用：复用建议队列 / 复用统计 / 题型提示词沉淀 三张表（create_all 自动建表，无需迁移 SQL）。
# 合并方式：整段复制到 models.py 末尾即可（文件顶部已 import uuid / Boolean / Float / JSON / DateTime）。
# ============================================================================

class ReuseSuggestionStatus:
    """复用建议状态常量（方案 §10.7）."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ReuseSuggestion(Base):
    """相似题复用建议审核队列（0.85~0.95 档待人工确认；展示模板题与新题对照 + 判定理由）。"""

    __tablename__ = "tag_agent_reuse_suggestions"

    id = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id = mapped_column(String(64), nullable=False)          # 新题 task_id（复用目标）
    question_text = mapped_column(Text)
    title = mapped_column(String(255))
    template_task_id = mapped_column(String(64))                 # 命中的模板题
    template_title = mapped_column(String(255))
    method_signature = mapped_column(String(255))
    confidence = mapped_column(Float, default=0.0)
    mode = mapped_column(String(16), default="L1")               # L0/L1（当前仅 L1 同法异数）
    slot_map = mapped_column(JSON)                               # [{slot, label, new_value}]
    reason = mapped_column(Text)
    status = mapped_column(String(16), default=ReuseSuggestionStatus.PENDING)
    reviewed_by = mapped_column(String(64))
    reviewed_at = mapped_column(DateTime)
    admin_note = mapped_column(Text)
    reject_reason = mapped_column(Text)
    review_history = mapped_column(JSON)
    created_at = mapped_column(DateTime, default=datetime.utcnow)
    created_by = mapped_column(String(64))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "question_text": self.question_text,
            "title": self.title,
            "template_task_id": self.template_task_id,
            "template_title": self.template_title,
            "method_signature": self.method_signature,
            "confidence": self.confidence,
            "mode": self.mode,
            "slot_map": self.slot_map,
            "reason": self.reason,
            "status": self.status,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "admin_note": self.admin_note,
            "reject_reason": self.reject_reason,
            "created_at": self.reviewed_at.isoformat() if self.reviewed_at else (
                self.created_at.isoformat() if self.created_at else None),
            "review_history": self.review_history or [],
        }


class ReuseStat(Base):
    """复用统计（按 method_signature 桶；成功复用次数用于 §10.9 题型沉淀阈值）。"""

    __tablename__ = "tag_agent_reuse_stats"

    id = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    method_signature = mapped_column(String(255), unique=True)
    template_task_id = mapped_column(String(64))                 # 当前最佳模板
    reuse_count = mapped_column(Integer, default=0)              # 复用机会/命中次数（含 miss）
    success_count = mapped_column(Integer, default=0)            # 成功复用次数（仅 L1 成功）
    pattern_sedimented = mapped_column(Boolean, default=False)   # 是否已沉淀题型提示词
    last_reuse_at = mapped_column(DateTime)
    updated_at = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PatternSuggestionStatus:
    """题型提示词沉淀状态常量（方案 §10.9）。"""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class PatternSuggestion(Base):
    """题型提示词沉淀审核队列（同 method_signature 复用 ≥ 阈值自动生成草稿，审核通过后写入 scene_patterns）。"""

    __tablename__ = "tag_agent_pattern_suggestions"

    id = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    method_signature = mapped_column(String(255))
    draft_markdown = mapped_column(Text)                         # 题型提示词草稿（50_pattern 结构）
    question_type_hint = mapped_column(String(255))
    source_task_id = mapped_column(String(64))                   # 最佳产物来源
    status = mapped_column(String(16), default=PatternSuggestionStatus.PENDING)
    reviewed_by = mapped_column(String(64))
    reviewed_at = mapped_column(DateTime)
    admin_note = mapped_column(Text)
    reject_reason = mapped_column(Text)
    review_history = mapped_column(JSON)
    created_at = mapped_column(DateTime, default=datetime.utcnow)
    created_by = mapped_column(String(64))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "method_signature": self.method_signature,
            "draft_markdown": self.draft_markdown,
            "question_type_hint": self.question_type_hint,
            "source_task_id": self.source_task_id,
            "status": self.status,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "admin_note": self.admin_note,
            "reject_reason": self.reject_reason,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "review_history": self.review_history or [],
        }

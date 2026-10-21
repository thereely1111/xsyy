# -*- coding: utf-8 -*-
"""API 请求/响应模型."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class RecognizeRequest(BaseModel):
    """识别请求."""

    question: str = Field(..., min_length=1, description="题目文本")
    question_id: str = Field(default="", description="题目 ID（来源题目）")
    creator_id: str = Field(default="", description="创建者 ID")


class ReviewRequest(BaseModel):
    """预修改提案审核请求（方案"七.2"，阶段二扩展）.

    action: approve | approve_modified | merge | reject
    提案 operation 为 delete 时必须 confirmed=true（二次确认）。
    """

    action: str = Field(..., description="审核动作")
    admin_note: str = Field(default="", description="管理员备注")
    reject_reason: str = Field(default="", description="驳回原因（action=reject 时必填，供智能体学习）")
    confirmed: bool = Field(default=False, description="删除/危险操作二次确认")
    # 修改后通过时使用（approve_modified）
    domain: str = Field(default="", description="修改后的知识域")
    grade: str = Field(default="", description="修改后的年级")
    chapter: str = Field(default="", description="修改后的章/单元")
    tag_name: str = Field(default="", description="修改后的知识点标签")
    keywords: list[str] = Field(default_factory=list, description="修改后的关键词集合")
    # 合并到已有标签时使用（merge / operation=merge 的保留方）
    merged_to_tag: str = Field(default="", description="目标正式标签")


class BatchReviewRequest(BaseModel):
    """批量审核请求（阶段二：管理员勾选多条一次通过/驳回/合并）."""

    pending_ids: list[str] = Field(..., min_length=1, description="提案 ID 列表")
    action: str = Field(..., description="审核动作（approve/approve_modified/merge/reject）")
    admin_note: str = Field(default="", description="管理员备注")
    confirmed: bool = Field(default=False, description="删除/危险操作二次确认")
    merged_to_tag: str = Field(default="", description="批量 merge 的目标正式标签")


class PaginatedQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    size: int = Field(default=20, ge=1, le=200)


class PendingQuery(PaginatedQuery):
    status: str = Field(default="", description="过滤状态，空为全部")
    operation: str = Field(default="", description="过滤操作类型（add/modify/delete/merge），空为全部")


class QuestionProposalQuery(PaginatedQuery):
    status: str = Field(default="", description="过滤状态，空为全部")


class QuestionProposalReviewRequest(BaseModel):
    """题目标签建议审核请求（阶段二：题目级标签全人工审核）."""

    action: str = Field(..., description="审核动作（approve/approve_modified/reject）")
    admin_note: str = Field(default="", description="管理员备注")
    reject_reason: str = Field(default="", description="驳回原因（action=reject 时必填，供智能体学习）")
    # 修改后通过时使用（approve_modified）
    domain: str = Field(default="", description="修改后的知识域")
    grade: str = Field(default="", description="修改后的年级")
    chapter: str = Field(default="", description="修改后的章/单元")
    sub_tags: list[str] = Field(default_factory=list, description="修改后的知识点标签列表")

# ============================================================================
# P1.5 补丁：追加到 backend/tag_agent/schemas.py 末尾
# 作用：标签增强建议列表查询 + 审核请求的数据模型。
# 合并方式：整段复制到 schemas.py 末尾即可（文件已有 pydantic 基础 import）。
# ============================================================================

from pydantic import BaseModel, Field


class LabelSuggestionQuery(BaseModel):
    """标签增强建议列表查询参数."""
    status: str | None = None
    page: int = 1
    size: int = 20


class LabelSuggestionReviewRequest(BaseModel):
    """标签增强建议审核请求."""
    action: str = Field(..., description="approve | reject")
    approved_keywords: list[str] | None = Field(
        None, description="仅 approve 使用：指定并入的判词；不传则默认采纳非“疑似过窄”候选",
    )
    admin_note: str = ""
    reject_reason: str = ""
# ============================================================================
# P3 补丁：追加到 backend/tag_agent/schemas.py 末尾
# 作用：复用建议 / 题型提示词 的查询与审核请求体。合并方式：整段复制末尾即可。
# ============================================================================

class ReuseSuggestionQuery(BaseModel):
    """相似题复用建议列表查询参数."""

    status: str | None = None
    page: int = 1
    size: int = 20


class ReuseSuggestionReviewRequest(BaseModel):
    """相似题复用建议审核请求。

    action=approve：用模板骨架 + slot_map 渲染复用产物，覆盖目标题 teaching_data.json（写 reuse_info 溯源）。
    action=reject ：必须传 reject_reason，仅记录不落地。
    """

    action: str = Field(..., description="approve | reject")
    admin_note: str = ""
    reject_reason: str = ""


class PatternSuggestionQuery(BaseModel):
    """题型提示词沉淀列表查询参数."""

    status: str | None = None
    page: int = 1
    size: int = 20


class PatternSuggestionReviewRequest(BaseModel):
    """题型提示词沉淀审核请求。

    action=approve：把草稿写入 prompt/animation/scene_patterns/50_pattern_{key}.md 并生效。
    action=reject ：必须传 reject_reason。
    """

    action: str = Field(..., description="approve | reject")
    admin_note: str = ""
    reject_reason: str = ""

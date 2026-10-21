# -*- coding: utf-8 -*-
"""标签识别智能体三场景编排主流程.

遵循方案"三"的标准识别流程，不允许跳级：
    1. 识别知识域和年级
    2. 匹配章/单元
    3. 匹配知识点标签
    4. 匹配或补全关键词

场景分支（方案"四/五/六"）：
    场景一：已匹配知识点标签但无可用关键词 → 只补关键词
    场景二：已匹配章/单元但无知识点标签 → 生成预加入知识点标签
    场景三：无法匹配章/单元 → 生成预加入标签链路（更严格）

所有新标签一律进入预加入库，由管理员审核，绝不直接写入正式库。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from tag_agent.agents.correction_agent import CorrectionAgent, CorrectionProposal
from tag_agent.agents.dedup_agent import DedupAgent, DedupProposal
from tag_agent.agents.domain_grade_agent import DomainGradeAgent
from tag_agent.agents.keyword_agent import KeywordExtractAgent
from tag_agent.agents.match_agent import MatchAgent
from tag_agent.agents.new_tag_agent import NewTagAgent
from tag_agent.agents.validate_agent import ValidateAgent
from tag_agent.config import TagAgentSettings
from tag_agent.tag_library import TagLibrary

logger = logging.getLogger(__name__)

# 动作常量
ACT_NON_MATH = "non_math"
ACT_LOW_CONFIDENCE = "low_confidence"
ACT_INJECT_OFFICIAL = "inject_official"
ACT_ADD_KEYWORDS = "add_keywords"          # 兼容保留（已不再由编排器产出）
ACT_PROPOSE_MODIFY = "propose_modify"      # 阶段一新增：修改提案（补关键词等，待管理员审核）
ACT_CREATE_PENDING_TAG = "create_pending_tag"
ACT_CREATE_PENDING_CHAIN = "create_pending_chain"
ACT_FAILED = "failed"

# 预加入池名称查询函数：async (domain, grade, chapter) -> list[str]
PendingNameProvider = Callable[[str, str, str], Awaitable[list[str]]]


@dataclass
class RecognitionOutcome:
    """一次识别的完整结果."""

    is_math_problem: bool = True
    action: str = ACT_FAILED
    domain: str = ""
    grade: str = ""
    chapter: str = ""
    tag: str = ""
    confidence: float = 0.0
    reasoning: str = ""
    matched_existing: bool = False
    keyword_added: list[str] = field(default_factory=list)
    knowledge_tags: Optional[dict] = None       # 写入题目的最终标签结构
    pending_payload: Optional[dict] = None      # 需要创建预加入记录的数据
    proposal_payload: Optional[dict] = None     # 阶段一新增：预修改提案数据（operation=modify 等）
    raw: dict = field(default_factory=dict)     # 各步骤原始输出（学习/日志用）

    def to_dict(self) -> dict:
        return {
            "is_math_problem": self.is_math_problem,
            "action": self.action,
            "domain": self.domain,
            "grade": self.grade,
            "chapter": self.chapter,
            "tag": self.tag,
            "confidence": round(self.confidence, 4),
            "reasoning": self.reasoning,
            "matched_existing": self.matched_existing,
            "keyword_added": self.keyword_added,
            "knowledge_tags": self.knowledge_tags,
            "pending_tag_id": (self.knowledge_tags or {}).get("pending_tag_id"),
            "proposal_payload": self.proposal_payload,
        }


def build_knowledge_tags(
    domain: str,
    grade: str,
    chapter: str,
    tag: str,
    *,
    tag_source: str,
    pending_tag_id: str = "",
    temporary_use: bool = False,
    pending_review_status: str = "",
    created_by_agent: bool = False,
) -> dict:
    """构建写入题目的 knowledge_tags 结构（方案"八.3"字段）. """
    return {
        "domain": domain,        # 知识域（新标签体系）
        "grade": grade,          # 年级
        "main_tag": chapter,     # 章/单元
        "sub_tags": [tag] if tag else [],  # 知识点标签（隐性属性）
        # 方案"八.3"：临时使用状态字段
        "tag_source": tag_source,                    # official | pre_joined
        "pending_tag_id": pending_tag_id,            # 预加入标签 ID
        "temporary_use": temporary_use,              # true/false
        "pending_review_status": pending_review_status,  # 待审核/已通过/...
        "created_by_agent": created_by_agent,        # true/false
    }


class TagAgentOrchestrator:
    """标签识别编排器：按标准流程执行三场景分支.

    智能体在首次使用时惰性创建（避免未配置 API Key 时无法构建编排器，
    便于离线测试与预加入审核流程复用）。
    """

    def __init__(
        self,
        library: TagLibrary,
        settings: TagAgentSettings,
        *,
        pending_name_provider: Optional[PendingNameProvider] = None,
    ):
        self.library = library
        self.settings = settings
        self._pending_name_provider = pending_name_provider
        self._agents: dict = {}
        self.validate_agent = ValidateAgent(library, settings.new_tag_similarity_threshold)

    def _agent(self, key: str) -> object:
        """惰性创建单个智能体."""
        if key not in self._agents:
            if key == "domain_grade":
                self._agents[key] = DomainGradeAgent(self.library)
            elif key == "match":
                self._agents[key] = MatchAgent(self.library)
            elif key == "keyword":
                self._agents[key] = KeywordExtractAgent()
            elif key == "new_tag":
                self._agents[key] = NewTagAgent(self.library)
            elif key == "correction":
                self._agents[key] = CorrectionAgent(self.library)
            elif key == "dedup":
                self._agents[key] = DedupAgent(self.library, threshold=self.settings.new_tag_similarity_threshold)
        return self._agents[key]

    @property
    def domain_grade_agent(self) -> DomainGradeAgent:
        return self._agent("domain_grade")

    @property
    def match_agent(self) -> MatchAgent:
        return self._agent("match")

    @property
    def keyword_agent(self) -> KeywordExtractAgent:
        return self._agent("keyword")

    @property
    def new_tag_agent(self) -> NewTagAgent:
        return self._agent("new_tag")

    @property
    def correction_agent(self) -> CorrectionAgent:
        return self._agent("correction")

    @property
    def dedup_agent(self) -> DedupAgent:
        return self._agent("dedup")

    async def _pending_names(self, domain: str, grade: str, chapter: str) -> list[str]:
        if self._pending_name_provider is None:
            return []
        try:
            return await self._pending_name_provider(domain, grade, chapter)
        except Exception as e:  # noqa: BLE001
            logger.warning("查询预加入池失败: %s", e)
            return []

    async def recognize(
        self,
        question: str,
        *,
        question_id: str = "",
        creator_id: str = "",
        pending_name_provider: Optional[PendingNameProvider] = None,
    ) -> RecognitionOutcome:
        """标准识别流程入口."""
        question = (question or "").strip()
        if not question:
            return RecognitionOutcome(is_math_problem=False, action=ACT_FAILED, reasoning="题目为空")

        if pending_name_provider is not None:
            self._pending_name_provider = pending_name_provider

        outcome = RecognitionOutcome(raw={"steps": []})

        # ── 步骤 1：知识域 + 年级（方案"三.1"）──────────────────────────────
        r1 = await self.domain_grade_agent.run(question)
        outcome.raw["steps"].append({"step": "domain_grade", **({} if r1.raw is None else r1.raw)})
        outcome.domain, outcome.grade = r1.domain, r1.grade
        outcome.confidence = r1.confidence
        outcome.reasoning = r1.reasoning

        if not r1.is_math_problem:
            outcome.is_math_problem = False
            outcome.action = ACT_NON_MATH
            return outcome
        if not r1.domain or not r1.grade:
            outcome.action = ACT_LOW_CONFIDENCE
            outcome.reasoning = "知识域/年级识别失败：" + (r1.reasoning or "")
            return outcome
        if r1.confidence < self.settings.domain_conf_threshold or r1.confidence < self.settings.grade_conf_threshold:
            outcome.action = ACT_LOW_CONFIDENCE
            outcome.reasoning = f"知识域+年级置信度过低（{r1.confidence:.2f}）"
            return outcome

        # ── 步骤 2：匹配章/单元（方案"三.2"）────────────────────────────────
        r2 = await self.match_agent.match_chapter(question, r1.domain, r1.grade)
        outcome.raw["steps"].append({"step": "chapter_match", **({} if r2.raw is None else r2.raw)})

        if r2.matched and r2.confidence >= self.settings.chapter_conf_threshold:
            return await self._handle_chapter_matched(outcome, question, r1.domain, r1.grade, r2.chapter, question_id, creator_id)

        if not r2.matched:
            # ── 场景三：无法匹配章/单元（方案"六"）────────────────────────
            return await self._handle_no_chapter(outcome, question, r1.domain, r1.grade, question_id, creator_id)

        # 章/单元匹配置信度过低
        outcome.action = ACT_LOW_CONFIDENCE
        outcome.reasoning = f"章/单元匹配置信度过低（{r2.confidence:.2f}）"
        return outcome

    # ── 分支：已匹配章/单元 ──────────────────────────────────────────────────

    async def _handle_chapter_matched(
        self,
        outcome: RecognitionOutcome,
        question: str,
        domain: str,
        grade: str,
        chapter: str,
        question_id: str,
        creator_id: str,
    ) -> RecognitionOutcome:
        outcome.chapter = chapter

        # ── 步骤 3：匹配知识点标签（方案"三.3"）────────────────────────────
        r3 = await self.match_agent.match_tag(question, domain, grade, chapter)
        outcome.raw["steps"].append({"step": "tag_match", **({} if r3.raw is None else r3.raw)})

        if r3.matched and r3.confidence >= self.settings.tag_conf_threshold:
            return await self._handle_tag_matched(outcome, question, domain, grade, chapter, r3.tag, question_id)

        if not r3.matched:
            # ── 场景二：生成预加入知识点标签（方案"五"）───────────────────
            return await self._handle_no_tag(outcome, question, domain, grade, chapter, question_id, creator_id)

        outcome.action = ACT_LOW_CONFIDENCE
        outcome.reasoning = f"知识点标签匹配置信度过低（{r3.confidence:.2f}）"
        return outcome

    async def _handle_tag_matched(
        self,
        outcome: RecognitionOutcome,
        question: str,
        domain: str,
        grade: str,
        chapter: str,
        tag: str,
        question_id: str,
    ) -> RecognitionOutcome:
        """已匹配到知识点标签：检查关键词，不足则走场景一补关键词."""
        outcome.tag = tag
        outcome.matched_existing = True

        # ── 步骤 4：关键词只作证据（2026-09-18 修正）────────────────────────
        # 原逻辑：字面命中才 inject_official，未命中走场景一逐题产「补关键词提案」。
        # 实测：库存关键词大量为公式串（如「相遇：路程和=总」），自然语言题面永远
        # 无法字面命中，导致高置信的正确匹配也进不了 inject_official、整链降级 legacy。
        # 现改为：标签匹配达标即注入官方标签；关键词沉淀由管理后台纠错/学习闭环承担。
        hits = self.library.match_keywords_in_question(question, tag)
        outcome.knowledge_tags = build_knowledge_tags(
            domain, grade, chapter, tag,
            tag_source="official",
        )
        if hits:
            outcome.action = ACT_INJECT_OFFICIAL
            outcome.confidence = max(outcome.confidence, self.settings.tag_conf_threshold)
            outcome.reasoning = f"关键词命中：{'、'.join(hits)}"
        else:
            outcome.action = ACT_INJECT_OFFICIAL
            outcome.reasoning = "标签匹配达标（关键词未字面命中，仅作证据缺失记录，不影响判定）"
        return outcome

    async def _handle_no_tag(
        self,
        outcome: RecognitionOutcome,
        question: str,
        domain: str,
        grade: str,
        chapter: str,
        question_id: str,
        creator_id: str,
    ) -> RecognitionOutcome:
        """场景二：生成预加入知识点标签 + 关键词（方案"五"）."""
        pending_names = await self._pending_names(domain, grade, chapter)
        new = await self.new_tag_agent.run_tag(question, domain, grade, chapter)
        outcome.raw["steps"].append({"step": "new_tag", **({} if new.raw is None else new.raw)})

        if not new.tag_name:
            outcome.action = ACT_FAILED
            outcome.reasoning = "新标签生成失败"
            return outcome

        # 查重（方案"十.3"）
        dup = self.validate_agent.check(new.tag_name, domain, grade, chapter, pending_names)
        if dup.is_duplicate:
            # 与已有标签高度重复：不生成新标签，直接归入相似正式标签
            outcome.action = ACT_INJECT_OFFICIAL
            outcome.matched_existing = True
            outcome.tag = dup.similar_tag
            outcome.reasoning = f"新标签与「{dup.similar_tag}」相似度过高（{dup.similarity:.2f}），已归入正式标签"
            outcome.knowledge_tags = build_knowledge_tags(
                domain, grade, chapter, dup.similar_tag,
                tag_source="official",
            )
            return outcome

        outcome.action = ACT_CREATE_PENDING_TAG
        outcome.confidence = new.confidence
        outcome.reasoning = new.reasoning
        outcome.pending_payload = {
            "domain": domain,
            "grade": grade,
            "chapter": chapter,
            "tag_name": new.tag_name,
            "keywords": new.keywords,
            "confidence": new.confidence,
            "agent_reason": new.reasoning,
            "source_question_id": question_id,
            "source_question_text": question[:500],
            "created_by": creator_id,
            "is_chapter_level": False,
        }
        outcome.knowledge_tags = build_knowledge_tags(
            domain, grade, chapter, new.tag_name,
            tag_source="pre_joined",
            temporary_use=True,
            pending_review_status="pending",
            created_by_agent=True,
        )
        return outcome

    # ── 分支：无法匹配章/单元 ────────────────────────────────────────────────

    async def _handle_no_chapter(
        self,
        outcome: RecognitionOutcome,
        question: str,
        domain: str,
        grade: str,
        question_id: str,
        creator_id: str,
    ) -> RecognitionOutcome:
        """场景三：生成预加入章/单元 + 知识点标签链路（方案"六"，更严格）."""
        new = await self.new_tag_agent.run_chapter(question, domain, grade)
        outcome.raw["steps"].append({"step": "new_chapter", **({} if new.raw is None else new.raw)})

        if not new.chapter or not new.tag_name:
            outcome.action = ACT_FAILED
            outcome.reasoning = "候选章/单元链路生成失败"
            return outcome

        # 查重：章/单元名（与同知识域已有章/单元比较）与知识点标签名（标签级比较）
        pending_names = await self._pending_names(domain, grade, new.chapter)
        dup_tag = self.validate_agent.check(
            new.tag_name, domain, grade, new.chapter, pending_names, mode="tag",
        )
        dup_chapter = self.validate_agent.check(
            new.chapter, domain, grade, new.chapter, pending_names, mode="chapter",
        )
        if dup_tag.is_duplicate or dup_chapter.is_duplicate:
            outcome.action = ACT_LOW_CONFIDENCE
            outcome.reasoning = (
                f"候选链路与已有标签重复（{dup_tag.similar_tag or dup_chapter.similar_tag}），"
                "已拦截，请人工处理"
            )
            return outcome

        outcome.action = ACT_CREATE_PENDING_CHAIN
        outcome.chapter = new.chapter
        outcome.tag = new.tag_name
        outcome.confidence = new.confidence
        outcome.reasoning = new.reasoning
        outcome.pending_payload = {
            "domain": domain,
            "grade": grade,
            "chapter": new.chapter,
            "tag_name": new.tag_name,
            "keywords": new.keywords,
            "confidence": new.confidence,
            "agent_reason": new.reasoning,
            "source_question_id": question_id,
            "source_question_text": question[:500],
            "created_by": creator_id,
            "is_chapter_level": True,
            "candidate_chapters": new.candidate_chapters,
            "no_match_reason": new.no_match_reason,
        }
        outcome.knowledge_tags = build_knowledge_tags(
            domain, grade, new.chapter, new.tag_name,
            tag_source="pre_joined",
            temporary_use=True,
            pending_review_status="pending",
            created_by_agent=True,
        )
        return outcome

    # ── 纠错链路（阶段一新增，方案「自动纠错标签」）──────────────────────────

    async def propose_correction(
        self,
        question: str,
        *,
        domain: str = "",
        grade: str = "",
        chapter: str = "",
        tag: str = "",
        hint: str = "",
    ) -> CorrectionProposal:
        """纠错链路：评估已有标签对题目的适用性，产出修改提案（仅提案，不改库）.

        hint 可选：low_confidence / keyword_missing / semantic_conflict / grade_suspect 等。
        调用方只传 tag 时，自动从标签库反查归属。
        """
        if not (domain and grade and chapter):
            info = self.library.find_tag(tag) if tag else None
            if info:
                domain = domain or info.get("domain", "")
                grade = grade or info.get("grade", "")
                chapter = chapter or info.get("chapter", "")
        if not (domain and grade and chapter and tag):
            return CorrectionProposal(can_propose=False, reason="标签定位信息不完整")
        return await self.correction_agent.propose(
            question,
            domain=domain, grade=grade, chapter=chapter, tag=tag, hint=hint,
        )

    # ── 去重链路（阶段一新增，方案「删除重复标签」）──────────────────────────

    async def scan_duplicates(
        self,
        *,
        use_llm_confirm: bool = True,
    ) -> list[DedupProposal]:
        """去重链路：全库扫描重复标签，产出合并/删除提案（仅提案，不改库）."""
        return await self.dedup_agent.scan(use_llm_confirm=use_llm_confirm)

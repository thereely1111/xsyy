# -*- coding: utf-8 -*-
"""正式标签库仓库.

数据源（**唯一正式源 = 远程 DB**）：
1. 远程数据库 knowledge_tag_framework 表（正式源，管理员审核流持续更新）
2. 本地种子 JSON（seed_data/knowledge_tag_framework.json，**仅应急降级**，
   未配置连接串或 DB 不可用时启用，且一律打印 WARNING）

层级结构（方案"三"）：
    知识域 → 年级 → 章/单元 → 知识点标签（模块级） → 强特征关键词

关键词索引支持持久化追加（场景一"补关键词"写入），单独保存在
seed_data/keyword_index.json，避免污染只读种子文件。
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

from tag_agent.config import TagAgentSettings

logger = logging.getLogger(__name__)

# 知识域 → 年级 → 章/单元 → [知识点标签]
Hierarchy = dict[str, dict[str, dict[str, list[str]]]]


class KeywordStore:
    """强特征关键词索引仓库（可读写）.

    从框架种子文件的 keyword_index 初始化，追加的关键词持久化到
    ``keyword_index.json``（与种子文件同目录）。
    """

    def __init__(self, path: Path, builtin: dict):
        self.path = path
        self.builtin = builtin or {}
        self.extra: dict = {}
        self._load_extra()

    def _load_extra(self) -> None:
        if self.path.exists():
            try:
                self.extra = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning("读取关键词索引失败 %s: %s", self.path, e)
                self.extra = {}

    def get(self, tag: str) -> list[str]:
        """返回某个知识点标签的全部强特征关键词（追加 + 内置）."""
        return self._split(self.extra.get(tag, "")) + self._split(self.builtin.get(tag, ""))

    def has_keywords(self, tag: str) -> bool:
        return bool(self.get(tag))

    def add(self, tag: str, keywords: list[str]) -> None:
        """为知识点标签追加关键词并持久化."""
        if not keywords:
            return
        merged = self.get(tag)
        for kw in keywords:
            kw = kw.strip()
            if kw and kw not in merged:
                merged.append(kw)
        if not merged:
            return
        self.extra[tag] = "、".join(merged)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.extra, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def remove(self, tag: str) -> None:
        """删除某个知识点标签的全部关键词并持久化（阶段二：硬删除配套）."""
        if tag in self.extra:
            del self.extra[tag]
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self.extra, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    @staticmethod
    def _split(text: str) -> list[str]:
        if not text:
            return []
        parts = re.split(r"[、，,/；; ]+", text)
        return [p.strip() for p in parts if p.strip()]


class TagLibrary:
    """正式标签库访问层."""

    GRADE_ORDER = ["六上", "六下", "七上", "七下", "八上", "八下", "九上", "九下"]

    def __init__(self, framework: dict, keyword_store: KeywordStore, source: str = "json"):
        self.framework = framework
        self.keyword_store = keyword_store
        self.source = source  # "json" | "database"
        self._build_index()

    # ── 工厂方法 ─────────────────────────────────────────────────────────────

    @classmethod
    def load(cls, settings: TagAgentSettings) -> "TagLibrary":
        """加载正式标签库：**以远程 DB 为唯一正式源**，种子 JSON 仅作应急降级.

        正式源＝``knowledge_tag_framework`` 表（与旧引擎 / 最终对账同一张表），
        避免出现「智能体认 DB、对账读定义不同」的双源漂移。
        仅以下两种情况回退种子 JSON，且**一律 WARNING**（不再静默）：
          - 未配置 ``TAG_AGENT_REMOTE_DB_URL``
          - 已配置但连接 / 读取失败
        """
        if not settings.remote_db_url:
            logger.warning(
                "标签库降级：未配置 TAG_AGENT_REMOTE_DB_URL，已回退种子快照(%s)。"
                "生产环境必须配置远程库连接串，否则仅能识别种子内的少量标签，"
                "会把正式库中已存在的标签误判为新标签。",
                settings.seed_path,
            )
        else:
            db_framework = cls._load_from_remote_db(settings.remote_db_url)
            if db_framework:
                logger.info("标签库从远程数据库加载: %s", settings.remote_db_url)
                return cls(db_framework, KeywordStore(settings.keyword_store_path, db_framework.get("keyword_index", {})), source="database")
            logger.warning(
                "标签库降级：远程 DB(%s) 连接或读取失败，已回退种子快照(%s)。"
                "请检查 TAG_AGENT_REMOTE_DB_URL 与数据库连通性。",
                settings.remote_db_url,
                settings.seed_path,
            )

        framework = cls._load_from_seed(settings.seed_path)
        keyword_store = KeywordStore(settings.keyword_store_path, framework.get("keyword_index", {}))
        return cls(framework, keyword_store, source="json")

    @staticmethod
    def _load_from_seed(path: Path) -> dict:
        if not path.exists():
            logger.warning("标签框架种子文件不存在: %s", path)
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _load_from_remote_db(remote_db_url: str) -> Optional[dict]:
        """从远程 MySQL knowledge_tag_framework 表构建框架（阶段四落地）.

        表结构（与 xsyy-edu 一致）：
            version(知识域) / grade(年级) / main_tag(章/单元) /
            sub_tag(知识点标签) / keyword(强特征关键词)

        构建与种子 JSON 同构的 framework dict：
            versions / grades / hierarchy / sub_tag_index / keyword_index。
        连接失败或表不可用时返回 None（上层降级种子 JSON）。
        """
        try:
            from urllib.parse import unquote, urlparse

            import pymysql

            # 解析 mysql+pymysql://user:pass@host:port/db?charset=utf8mb4
            scheme, rest = remote_db_url.split("://", 1)
            auth, hostport = rest.split("@", 1)
            user, pwd = auth.split(":", 1)
            pwd = unquote(pwd)
            if ":" in hostport:
                host, port = hostport.rsplit(":", 1)
                port = int(port.split("/")[0])
            else:
                host = hostport.split("/")[0]
                port = 3306
            dbname = hostport.split("/", 1)[1].split("?", 1)[0]
            charset = "utf8mb4"
            if "?" in hostport and "charset=" in hostport.split("/", 1)[1]:
                qs = hostport.split("/", 1)[1].split("?", 1)[1]
                for kv in qs.split("&"):
                    if kv.startswith("charset="):
                        charset = kv.split("=", 1)[1]

            conn = pymysql.connect(
                host=host, port=port, user=user, password=pwd,
                database=dbname, charset=charset,
                cursorclass=pymysql.cursors.DictCursor,
                connect_timeout=8,
            )
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT version, grade, main_tag, sub_tag, keyword "
                        "FROM knowledge_tag_framework WHERE sub_tag IS NOT NULL AND sub_tag != ''"
                    )
                    rows = cur.fetchall()
            finally:
                conn.close()

            if not rows:
                logger.warning("远程标签库为空（%s/%s），降级种子", host, dbname)
                return None

            versions: list[str] = []
            grades: list[str] = []
            hierarchy: dict = {}
            sub_tag_index: dict = {}
            keyword_index: dict = {}
            for r in rows:
                v = (r.get("version") or "").strip()
                g = (r.get("grade") or "").strip()
                m = (r.get("main_tag") or "").strip()
                s = (r.get("sub_tag") or "").strip()
                k = (r.get("keyword") or "").strip()
                if not (v and g and m and s):
                    continue
                if v not in versions:
                    versions.append(v)
                if g not in grades:
                    grades.append(g)
                hierarchy.setdefault(v, {}).setdefault(g, {}).setdefault(m, [])
                if s not in hierarchy[v][g][m]:
                    hierarchy[v][g][m].append(s)
                sub_tag_index.setdefault(s, []).append(
                    {"version": v, "grade": g, "main_tag": m}
                )
                if s not in keyword_index or not keyword_index[s]:
                    keyword_index[s] = k

            logger.info(
                "远程标签库加载完成: %s 域 / %s 年级 / %s 知识点标签（%s）",
                len(versions), len(grades), len(sub_tag_index), dbname,
            )
            return {
                "versions": versions,
                "grades": grades,
                "hierarchy": hierarchy,
                "sub_tag_index": sub_tag_index,
                "keyword_index": keyword_index,
            }
        except Exception as e:  # noqa: BLE001
            logger.warning("远程标签库加载失败，降级种子: %s", e)
            return None

    # ── 索引构建 ─────────────────────────────────────────────────────────────

    def _build_index(self) -> None:
        self.domains: list[str] = list(self.framework.get("versions") or self.framework.get("domains") or [])
        self.grades: list[str] = list(self.framework.get("grades") or self.GRADE_ORDER)

        # domain -> grade -> chapter -> [tags]
        self.hierarchy: Hierarchy = self.framework.get("hierarchy") or {}

        # 知识点标签 -> {domain, grade, chapter, keywords}
        self.tag_info: dict[str, dict] = {}
        for tag, entries in (self.framework.get("sub_tag_index") or {}).items():
            if entries:
                e = entries[0]
                self.tag_info[tag] = {
                    "domain": e.get("version", ""),
                    "grade": e.get("grade", ""),
                    "chapter": e.get("main_tag", ""),
                }
        # 兼容无 sub_tag_index 的种子：从 main_tag_info + hierarchy 反推
        if not self.tag_info:
            for dom, grades in self.hierarchy.items():
                for grade, chapters in grades.items():
                    for chapter, tags in chapters.items():
                        for tag in tags:
                            self.tag_info.setdefault(tag, {
                                "domain": dom, "grade": grade, "chapter": chapter,
                            })

    # ── 查询 API ─────────────────────────────────────────────────────────────

    def list_domains(self) -> list[str]:
        return self.domains

    def list_grades(self) -> list[str]:
        return self.grades

    def list_chapters(self, domain: str, grade: str) -> list[str]:
        """返回知识域+年级下的章/单元候选."""
        return list((self.hierarchy.get(domain, {}).get(grade, {}) or {}).keys())

    def list_tags(self, domain: str, grade: str, chapter: str) -> list[str]:
        """返回章/单元下的知识点标签候选."""
        return list(self.hierarchy.get(domain, {}).get(grade, {}).get(chapter, []))

    def find_tag(self, tag: str) -> Optional[dict]:
        """按知识点标签反查归属（知识域/年级/章/单元）."""
        info = self.tag_info.get(tag)
        if info:
            return dict(info)
        # 兜底：章/单元本身可作为"知识点标签"出现在 sub_tags 中时
        for dom, grades in self.hierarchy.items():
            for grade, chapters in grades.items():
                if tag in chapters:
                    return {"domain": dom, "grade": grade, "chapter": tag}
        return None

    def get_keywords(self, tag: str) -> list[str]:
        return self.keyword_store.get(tag)

    def has_keywords(self, tag: str) -> bool:
        return self.keyword_store.has_keywords(tag)

    def add_keywords(self, tag: str, keywords: list[str]) -> None:
        """场景一：为已匹配的正式知识点标签追加关键词（方案"四"）.

        注意：阶段二起，智能体侧不再直接调用本方法（改为产出提案）；
        仅审核通过后的应用逻辑（service.promote_to_official）使用。
        """
        self.keyword_store.add(tag, keywords)

    def match_keywords_in_question(self, question: str, tag: str) -> list[str]:
        """返回该标签下命中题面的关键词（用于判断是否需要补关键词）."""
        return [kw for kw in self.get_keywords(tag) if len(kw) >= 2 and kw in question]

    def keyword_hit_scores(self, question: str) -> list[tuple[str, float]]:
        """全库关键词匹配：返回 [(知识点标签, 加权得分)]，按得分降序."""
        scores: dict[str, float] = {}
        for tag in self.tag_info:
            score = 0.0
            for kw in self.get_keywords(tag):
                if len(kw) >= 2 and kw in question:
                    score += len(kw) * 2.0  # 长词权重更高
            if score > 0:
                scores[tag] = score
        return sorted(scores.items(), key=lambda x: x[1], reverse=True)

    # ── 正式库写方法（阶段二新增，仅供审核通过后的应用逻辑调用）────────────

    def add_tag(
        self,
        domain: str,
        grade: str,
        chapter: str,
        tag: str,
        keywords: list[str] | None = None,
    ) -> None:
        """审核通过后：新增知识点标签到正式库."""
        chapter_tags = self.hierarchy.setdefault(domain, {}).setdefault(grade, {}).setdefault(chapter, [])
        if tag and tag not in chapter_tags:
            chapter_tags.append(tag)
        if tag:
            self.tag_info[tag] = {"domain": domain, "grade": grade, "chapter": chapter}
        if keywords:
            self.keyword_store.add(tag, keywords)
        logger.info("正式库新增标签: %s / %s / %s / %s", domain, grade, chapter, tag)

    def update_tag(
        self,
        *,
        domain: str,
        grade: str,
        chapter: str,
        tag: str,
        after: dict,
    ) -> None:
        """审核通过后：字段级修改已有标签（如补关键词、改年级/章名等）.

        after 支持键：keywords / tag_name / grade / chapter / domain。
        修改标签名时，会同步修正 tag_info 索引（旧名指向新名）。
        """
        new_tag = (after.get("tag_name") or "").strip() or tag
        # 修改关键词
        new_kws = after.get("keywords")
        if isinstance(new_kws, list) and new_kws:
            self.keyword_store.add(tag, new_kws)
        # 修改层级归属（年级/章/知识域）
        new_domain = (after.get("domain") or "").strip() or domain
        new_grade = (after.get("grade") or "").strip() or grade
        new_chapter = (after.get("chapter") or "").strip() or chapter
        if (new_domain, new_grade, new_chapter) != (domain, grade, chapter):
            self._move_tag(domain, grade, chapter, tag, new_domain, new_grade, new_chapter, new_tag)
        elif new_tag != tag:
            # 仅改名：从原位置移除旧名，加入新名
            chapter_tags = self.hierarchy.get(domain, {}).get(grade, {}).get(chapter, [])
            if tag in chapter_tags:
                chapter_tags.remove(tag)
            if new_tag not in chapter_tags:
                chapter_tags.append(new_tag)
            info = self.tag_info.pop(tag, None)
            if info:
                self.tag_info[new_tag] = {**info, "chapter": chapter}
        logger.info("正式库修改标签: %s → %s（after=%s）", tag, new_tag, after)

    def delete_tag(self, *, domain: str, grade: str, chapter: str, tag: str) -> None:
        """审核通过后：硬删除正式库中的知识点标签（用户确认：删除数据库记录）."""
        chapter_tags = self.hierarchy.get(domain, {}).get(grade, {}).get(chapter, [])
        if tag in chapter_tags:
            chapter_tags.remove(tag)
        # 同步清理 tag_info 与关键词（保留证据由审计日志负责）
        self.tag_info.pop(tag, None)
        self.keyword_store.remove(tag)
        logger.info("正式库硬删除标签: %s / %s / %s / %s", domain, grade, chapter, tag)

    def merge_tags(self, primary_tag: str, duplicate_tag: str) -> None:
        """审核通过后：合并重复标签（duplicate_tag 并入 primary_tag）.

        仅合并索引与关键词，真正的引用迁移由宿主应用按 reference_updates 执行。
        """
        info = self.find_tag(duplicate_tag)
        if info is None:
            logger.warning("合并失败：重复标签不存在 %s", duplicate_tag)
            return
        dup_kws = self.get_keywords(duplicate_tag)
        if dup_kws:
            self.keyword_store.add(primary_tag, dup_kws)
        # 从层级中移除重复标签
        chapter_tags = self.hierarchy.get(info["domain"], {}).get(info["grade"], {}).get(info["chapter"], [])
        if duplicate_tag in chapter_tags:
            chapter_tags.remove(duplicate_tag)
        self.tag_info.pop(duplicate_tag, None)
        self.keyword_store.remove(duplicate_tag)
        logger.info("正式库合并标签: %s ← %s", primary_tag, duplicate_tag)

    def _move_tag(
        self,
        domain: str, grade: str, chapter: str, tag: str,
        new_domain: str, new_grade: str, new_chapter: str, new_tag: str,
    ) -> None:
        """把标签从原层级移动到新层级（含改名）."""
        old_list = self.hierarchy.get(domain, {}).get(grade, {}).get(chapter, [])
        if tag in old_list:
            old_list.remove(tag)
        self.tag_info.pop(tag, None)
        if new_tag:
            new_list = self.hierarchy.setdefault(new_domain, {}).setdefault(new_grade, {}).setdefault(new_chapter, [])
            if new_tag not in new_list:
                new_list.append(new_tag)
            self.tag_info[new_tag] = {
                "domain": new_domain, "grade": new_grade, "chapter": new_chapter,
            }

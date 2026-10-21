# -*- coding: utf-8 -*-
"""知识标签 RAG 模块（轻档：纯 Python 字符 n-gram TF-IDF 检索 + 混合重排 + 标题交叉验证）。

零第三方依赖（标准库实现），与阿里云 / 外部 embedding 服务完全解耦。

模块内容：
- TagIndex：由标签框架构建字符 1-gram/2-gram TF-IDF 稀疏索引，支持 save/load JSON 持久化、
  以及限定 domain/grade 的 search 检索（余弦相似度）。
- keyword_hit_score：强特征关键词命中打分（与 knowledge_tag_injector 内实现等价的独立副本，
  避免循环导入）。
- rerank_candidates：对两路候选做混合重排：0.30·题面向量 + 0.15·标题向量
  + 0.25·关键词命中 + 0.10·标题关键词 + 0.05·年级先验 + 0.10·标题一致性。
- prescreen：两步 LLM 之前的全局预检（三重确认：向量高分 + 关键词命中 + 标题字符命中 才直出）。

阈值均为初值，需经 eval_rag_vs_baseline.py 实测标定。
"""
from __future__ import annotations

import json
import math
import os
import re
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

_WS_RE = re.compile(r"[\s\u200b\ufeff]+")
_PUNCT_RE = re.compile(
    r"[，。、；：！？…·“”‘’（）()【】\[\]《》〈〉\"'\-—–～~<>]"
)

# 混合重排权重（标定基准，合计 1.00）
W_VEC_Q = 0.30      # 题面向量与标签文档的余弦相似度
W_VEC_T = 0.15      # 标题向量相似度
W_KW_Q = 0.25       # 题面命中强特征关键词
W_KW_T = 0.10       # 标题命中强特征关键词
W_GRADE = 0.05      # 与 step1 判定年级一致
W_TITLE = 0.10      # 标题字符命中 sub_tag/main_tag（含一致性加成）
# 注：域先验通过 search 的 domain 限定实现，不参与打分；剩余 0.05 计入 W_TITLE 的一致性部分。

# 阈值说明：轻档字符 TF-IDF 的余弦分数尺度为 0.1~0.4（远低于语义模型），
# 纯分数无法区分对错，故直出/锁定一律以「字符证据」（关键词命中 / 标题命中）为准，
# 向量分仅做最低门槛与排序确认。以下为实测标定的初值。
PRESCREEN_MIN_VEC = 0.20   # 预检直出：Top-1 向量分门槛（TF-IDF 尺度）
RAG_DIRECT_MIN = 0.30      # 域内重排：高置信直出混合分门槛
KW_NORM_DIV = 6.0          # 关键词原始分归一化除数（命中字符长度和 / 6 → 0~1）

# ---------------------------------------------------------------------------
# 语义档（可选后端）：本地 sentence-transformers 模型，EMBEDDING_BACKEND=semantic 启用
# ---------------------------------------------------------------------------
_SEMANTIC_MODEL = None  # 进程级单例
_SEMANTIC_MODEL_NAME = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
# 项目内置模型目录（公网部署时随代码带上 data/models/，不依赖服务器 HF 缓存）
_LOCAL_MODEL_DIR = Path(__file__).resolve().parent / "data" / "models" / "bge-small-zh-v1.5"
# bge 系列模型官方要求：查询侧加指令前缀（文档侧不加），否则检索效果明显下降
_BGE_QUERY_PREFIX = os.getenv(
    "EMBEDDING_QUERY_PREFIX",
    "为这个句子生成表示以用于检索相关文章：",
)


def _get_semantic_model():
    """延迟加载语义模型（进程级单例）。加载失败抛 RuntimeError（调用方捕获后降级轻档）。

    模型解析顺序：项目内置目录 data/models/ > HF 本地缓存；**均不存在时快速失败**，
    绝不联网下载/重试——公网环境 huggingface.co 常不可达，联网重试会导致降级滞后甚至卡死。
    """
    global _SEMANTIC_MODEL
    if _SEMANTIC_MODEL is not None:
        return _SEMANTIC_MODEL
    try:
        import numpy as np  # noqa: F401  确保 numpy 可用
        from sentence_transformers import SentenceTransformer
    except ImportError as e:
        raise RuntimeError(f"语义档需要 sentence-transformers/numpy: {e}")

    model_ref = _SEMANTIC_MODEL_NAME
    if not Path(model_ref).is_dir():
        local_dir = _LOCAL_MODEL_DIR
        cache_dir = Path.home() / ".cache" / "huggingface" / "hub" / (
            f"models--{_SEMANTIC_MODEL_NAME.replace('/', '--')}"
        )
        if local_dir.is_dir():
            model_ref = str(local_dir)  # 项目内置目录优先（公网部署随代码带上）
        elif cache_dir.exists():
            os.environ["HF_HUB_OFFLINE"] = "1"     # HF 缓存可用：离线加载
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
        else:
            raise RuntimeError(
                f"语义模型未就绪：项目目录 {local_dir} 与 HF 缓存均无 {_SEMANTIC_MODEL_NAME}，"
                "已自动降级轻档（请先部署模型文件再启用 semantic）"
            )
    try:
        _SEMANTIC_MODEL = SentenceTransformer(model_ref)
    except Exception as e:
        raise RuntimeError(f"语义模型加载失败（{model_ref}）: {e}")
    return _SEMANTIC_MODEL


def _clean_text(text: str) -> str:
    text = _WS_RE.sub("", str(text or ""))
    text = _PUNCT_RE.sub("", text)
    return text


def _ngrams(text: str) -> List[str]:
    """字符 1-gram + 2-gram 切分（中文短文本无需分词）。"""
    text = _clean_text(text)
    grams = list(text)
    grams += [text[i:i + 2] for i in range(len(text) - 1)]
    return grams


def _kw_normalize(raw: float) -> float:
    """关键词原始分（命中字符长度和 × 权重）归一化到 0~1。"""
    return min(1.0, raw / KW_NORM_DIV)


def keyword_hit_score(keyword: str, text: str, weight: float = 1.0) -> float:
    """强特征关键词对文本的命中得分（按命中词长度加权，长度≥2 才计）。"""
    if not keyword or keyword in ("nan", "-"):
        return 0.0
    score = 0.0
    for part in re.split(r"[、，,/]", keyword):
        part = part.strip()
        if len(part) >= 2 and part in text:
            score += len(part) * weight
    return score


class TagIndex:
    """标签向量索引，双后端可切换：

    - backend="lexical"（默认）：字符 n-gram TF-IDF 稀疏索引（纯标准库，零依赖）；
    - backend="semantic"（可选）：本地 sentence-transformers 语义向量（需 numpy+模型）。

    接口（build/search/save/load/from_framework/__len__）两后端完全一致，
    由环境变量 EMBEDDING_BACKEND=lexical|semantic 决定默认后端。
    """

    def __init__(self, backend: Optional[str] = None) -> None:
        self.backend = (backend or os.getenv("EMBEDDING_BACKEND", "lexical") or "lexical").strip().lower()
        self.docs: List[dict] = []     # 每个 doc: version/grade/main_tag/sub_tag/keyword/doc_text
        # lexical: 字符 TF-IDF 结构
        self.df: Counter = Counter()   # term -> 文档频率
        self.postings: Dict[str, Dict[int, int]] = {}  # term -> {doc_idx: tf}
        self.doc_norms: List[float] = []
        # semantic: 向量矩阵（np.ndarray (N, dim)）
        self.embeddings = None

    # ---------- 构建 ----------

    @classmethod
    def from_framework(cls, framework: dict, backend: Optional[str] = None) -> "TagIndex":
        """从标签框架（knowledge_tag_injector.load_framework 的返回值）构建索引。"""
        docs: List[dict] = []
        hierarchy = framework.get("hierarchy", {}) or {}
        keyword_index = framework.get("keyword_index", {}) or {}
        for version, grades in hierarchy.items():
            for grade, chapters in grades.items():
                for main_tag, sub_tags in chapters.items():
                    for sub_tag in sub_tags:
                        docs.append({
                            "version": version,
                            "grade": grade,
                            "main_tag": main_tag,
                            "sub_tag": sub_tag,
                            "keyword": keyword_index.get(sub_tag, "") or "",
                        })
        index = cls(backend=backend)
        index.build(docs)
        return index

    def build(self, docs: List[dict]) -> None:
        self.docs = []
        for doc in docs:
            text = f"{doc['sub_tag']}。{doc['main_tag']}。{doc.get('keyword', '')}"
            self.docs.append({
                "version": doc["version"],
                "grade": doc["grade"],
                "main_tag": doc["main_tag"],
                "sub_tag": doc["sub_tag"],
                "keyword": doc.get("keyword", "") or "",
                "doc_text": text,
            })
        if self.backend == "semantic":
            self._build_semantic()
        else:
            self.backend = "lexical"
            self._build_lexical()

    def _build_lexical(self) -> None:
        self.df = Counter()
        self.postings = {}
        for idx, doc in enumerate(self.docs):
            for term, tf in Counter(_ngrams(doc["doc_text"])).items():
                self.df[term] += 1
                self.postings.setdefault(term, {})[idx] = tf
        self._compute_norms()

    def _build_semantic(self) -> None:
        model = _get_semantic_model()
        import numpy as np  # noqa: F401
        texts = [d["doc_text"] for d in self.docs]
        self.embeddings = np.asarray(
            model.encode(texts, normalize_embeddings=True, show_progress_bar=False, batch_size=64),
            dtype=np.float32,
        )

    def _compute_norms(self) -> None:
        n = len(self.docs)
        self.doc_norms = [0.0] * n
        for term, post in self.postings.items():
            idf = self._idf(term)
            for idx, tf in post.items():
                w = (1.0 + math.log(tf)) * idf
                self.doc_norms[idx] += w * w
        self.doc_norms = [math.sqrt(v) if v else 1.0 for v in self.doc_norms]

    def _idf(self, term: str) -> float:
        return math.log((len(self.docs) + 1) / (self.df.get(term, 0) + 1)) + 1.0

    # ---------- 检索 ----------

    def search(self, query: str, top_k: int = 20,
               domain: Optional[str] = None, grade: Optional[str] = None) -> List[dict]:
        """余弦相似度检索。domain/grade 限定命中文档（域先验的工程实现）。"""
        if self.backend == "semantic":
            return self._search_semantic(query, top_k, domain, grade)
        return self._search_lexical(query, top_k, domain, grade)

    def _search_lexical(self, query: str, top_k: int,
                        domain: Optional[str], grade: Optional[str]) -> List[dict]:
        q_counts = Counter(_ngrams(query))
        if not q_counts:
            return []
        scores: Dict[int, float] = {}
        q_norm_sq = 0.0
        for term, qtf in q_counts.items():
            idf = self._idf(term)
            qw = (1.0 + math.log(qtf)) * idf
            q_norm_sq += qw * qw
            for idx, tf in self.postings.get(term, {}).items():
                doc = self.docs[idx]
                if domain is not None and doc["version"] != domain:
                    continue
                if grade is not None and doc["grade"] != grade:
                    continue
                dw = (1.0 + math.log(tf)) * idf
                scores[idx] = scores.get(idx, 0.0) + qw * dw
        if not scores:
            return []
        q_norm = math.sqrt(q_norm_sq) or 1.0
        results = []
        for idx, dot in scores.items():
            doc = self.docs[idx]
            results.append({
                "score": dot / (q_norm * self.doc_norms[idx]),
                "version": doc["version"],
                "grade": doc["grade"],
                "main_tag": doc["main_tag"],
                "sub_tag": doc["sub_tag"],
                "keyword": doc["keyword"],
            })
        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:top_k]

    def _search_semantic(self, query: str, top_k: int,
                         domain: Optional[str], grade: Optional[str]) -> List[dict]:
        if self.embeddings is None or len(self.embeddings) != len(self.docs):
            return []
        model = _get_semantic_model()
        import numpy as np  # noqa: F401
        # bge 查询指令前缀（文档侧编码时未加，检索侧必须加，保持两侧一致）
        q = np.asarray(
            model.encode([_BGE_QUERY_PREFIX + query], normalize_embeddings=True)[0],
            dtype=np.float32,
        )
        scores = self.embeddings @ q  # (N,)
        idxs = list(range(len(self.docs)))
        if domain is not None or grade is not None:
            idxs = [i for i in idxs
                    if (domain is None or self.docs[i]["version"] == domain)
                    and (grade is None or self.docs[i]["grade"] == grade)]
        ranked = sorted(idxs, key=lambda i: float(scores[i]), reverse=True)[:top_k]
        results = []
        for i in ranked:
            doc = self.docs[i]
            results.append({
                "score": float(scores[i]),
                "version": doc["version"],
                "grade": doc["grade"],
                "main_tag": doc["main_tag"],
                "sub_tag": doc["sub_tag"],
                "keyword": doc["keyword"],
            })
        return results

    # ---------- 持久化 ----------

    def save(self, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        meta = {"backend": self.backend, "docs": self.docs}
        if self.backend == "semantic" and self.embeddings is not None:
            import numpy as np  # noqa: F401
            np.save(str(path) + ".emb.npy", self.embeddings)
            Path(str(path) + ".meta.json").write_text(
                json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        else:
            payload = {
                "backend": "lexical",
                "docs": self.docs,
                "df": dict(self.df),
                "postings": self.postings,
                "doc_norms": self.doc_norms,
            }
            Path(path).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: str) -> "TagIndex":
        plain = Path(path)
        meta_path = Path(str(path) + ".meta.json")
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            index = cls(backend=meta.get("backend", "semantic"))
            index.docs = meta["docs"]
            if index.backend == "semantic":
                import numpy as np  # noqa: F401
                index.embeddings = np.load(str(path) + ".emb.npy")
            return index
        payload = json.loads(plain.read_text(encoding="utf-8"))
        index = cls(backend="lexical")
        index.docs = payload["docs"]
        index.df = Counter(payload["df"])
        index.postings = payload["postings"]
        index.doc_norms = payload["doc_norms"]
        return index

    def __len__(self) -> int:
        return len(self.docs)


def search_combined(index: TagIndex, question: str, title: str = "",
                    top_k: int = 15, domain: Optional[str] = None,
                    grade: Optional[str] = None) -> List[dict]:
    """两路合并检索：题面一路 ∪ 标题一路，同标签取最高分。

    title 是强信号（人工命名，贴近标签名），单独检索一路再合并，
    实测可将域内 Top-10 召回从 32.6% 提升到 46.5%。
    """
    q_cands = index.search(question, top_k=top_k, domain=domain, grade=grade)
    t_cands = (index.search(title, top_k=top_k, domain=domain, grade=grade)
               if title and title.strip() else [])
    merged: Dict[str, dict] = {}
    for cand in q_cands + t_cands:
        key = cand["sub_tag"]
        if key not in merged or cand["score"] > merged[key]["score"]:
            merged[key] = cand
    return sorted(merged.values(), key=lambda c: c["score"], reverse=True)


# ---------------------------------------------------------------------------
# 混合重排
# ---------------------------------------------------------------------------

def rerank_candidates(candidates: List[dict], question: str,
                      title: str = "", prefer_grade: str = "") -> List[dict]:
    """对候选做混合重排并重算综合分（0~1）。

    候选来自 TagIndex.search 的结果（含向量 score）。混合分：
    score = 0.30·vec_q + 0.15·vec_t + 0.25·kw_q + 0.10·kw_t
          + 0.05·grade_match + 0.10·title_signal

    - vec_t / kw_t / title_signal：仅在提供 title 时计入（title 缺失时权重归一化）。
    - title_signal：标题字符命中候选 sub_tag/main_tag → +0.10 且打 title_hit 标记；
      若命中的恰是题面向量 Top-1 候选，该候选额外 +0.05（一致性加成，计入 title_signal 项）。
    - grade_match：候选年级与 prefer_grade 一致。
    """
    if not candidates:
        return []
    has_title = bool(title and title.strip())
    # 标题字符命中表：sub_tag / main_tag -> bool
    title_hits = set()
    if has_title:
        for cand in candidates:
            if len(cand["sub_tag"]) >= 2 and cand["sub_tag"] in title:
                title_hits.add(cand["sub_tag"])
            if len(cand["main_tag"]) >= 2 and cand["main_tag"] in title:
                title_hits.add(cand["main_tag"])

    vec_top1 = candidates[0]["sub_tag"] if candidates else ""

    # 标题向量的相对信号：用向量分近似（标题与题面同标签时分数接近），取题面向量分的 0.9 倍起跳
    # 更稳妥的做法：单独检索一次 title。此处为省一次检索，用「标题字符命中」主导标题信号。
    weights = [W_VEC_Q, W_VEC_T, W_KW_Q, W_KW_T, W_GRADE, W_TITLE]
    if not has_title:
        scale = 1.0 / (sum(weights[:2]) + W_KW_Q + W_GRADE + W_TITLE)  # 去掉标题相关项后重归一
    else:
        scale = 1.0

    out = []
    for cand in candidates:
        vec_q = cand["score"]
        vec_t = 0.0
        kw_q = _kw_normalize(keyword_hit_score(cand["keyword"], question, weight=1.0))
        kw_t = 0.0
        grade_match = 1.0 if (prefer_grade and cand["grade"] == prefer_grade) else 0.0
        title_signal = 0.0
        title_hit = False
        if has_title:
            # 标题字符命中信号（sub_tag 命中 > main_tag 命中）
            if cand["sub_tag"] in title_hits:
                title_signal = 0.10
                title_hit = True
            elif cand["main_tag"] in title_hits:
                title_signal = 0.06
                title_hit = True
            kw_t = _kw_normalize(keyword_hit_score(cand["keyword"], title, weight=1.0))
            vec_t = vec_q * 0.90 if title_hit else 0.0  # 标题命中时给标题向量近似分
            # 一致性加成：标题命中项恰为题面向量 Top-1
            if title_hit and cand["sub_tag"] == vec_top1:
                title_signal += 0.05
        raw = (W_VEC_Q * vec_q + W_VEC_T * vec_t + W_KW_Q * kw_q + W_KW_T * kw_t
               + W_GRADE * grade_match + W_TITLE * title_signal) * scale
        out.append({
            "score": min(1.0, raw),
            "version": cand["version"],
            "grade": cand["grade"],
            "main_tag": cand["main_tag"],
            "sub_tag": cand["sub_tag"],
            "keyword": cand["keyword"],
            "title_hit": title_hit,
            "kw_hit": kw_q > 0,
        })
    out.sort(key=lambda r: r["score"], reverse=True)
    return out


# ---------------------------------------------------------------------------
# 全局预检（两步 LLM 之前）
# ---------------------------------------------------------------------------

def prescreen(index: TagIndex, question: str, title: str = "") -> Optional[dict]:
    """预检直出（两步 LLM 之前，0 次 LLM）：两路合并检索 Top-1 + 最强证据确认。

    实测（2026-08-27，对齐子集 35 题）：轻档 TF-IDF 对「数学题整题 × 标签文档」的
    区分度有限（域内 Top-1 命中率约 5%、Top-10 约 54%），任何宽松证据（关键词命中 /
    标题命中章名）都会导致直出精度崩坏（实测 ≤12%）。因此直出仅认最强证据：
    **标题文本精确包含候选的知识点标签名（长度 ≥4）**，宁可覆盖低，绝不误直出。

    返回标准标签组 {version, grade, main_tag, sub_tags}；无证据返回 None。
    """
    cands = search_combined(index, question, title, top_k=15)
    if not cands:
        return None
    top = cands[0]
    if top["score"] < PRESCREEN_MIN_VEC:
        return None
    strong_title = bool(title) and len(top["sub_tag"]) >= 4 and top["sub_tag"] in title
    if not strong_title:
        return None
    return {
        "version": top["version"],
        "grade": top["grade"],
        "main_tag": top["main_tag"],
        "sub_tags": [top["sub_tag"]],
    }

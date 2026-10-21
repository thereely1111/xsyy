# -*- coding: utf-8 -*-
"""离线构建知识库（KB）索引：知识域 + 年级 + 章节（**不含教材版本维度**）。

来源（唯一标签真源，不新建第二份标签树）：
- 默认 `backend/prompt/knowledge_tag_framework.json`（dict，含 `hierarchy` + `keyword_index`）
- 也接受「扁平行」形态的 dump（list，每行 `{version, grade, main_tag, sub_tag, keyword}`），
  用于 DB 导出的完整框架快照（如一上…九下全覆盖），由 `--framework` 指定路径即可。

产出（`backend/knowledge/index/`）：
- `tag_index.json` —— 知识点行清单（domain/grade/chapter/section/keyword），
  **只存行、不存倒排表**：检索结构由 `kb_index.load_index` 在内存重建（毫秒级），
  既避免 `knowledge_tag_rag.TagIndex.load()` 词法分支的下标类型缺陷，也保证索引可读可 diff
- `chapters.json`  —— 章节清单 domain → grade → [chapter]，供接口快速列章 / 体检

用法：
    python scripts/build_index.py [--framework <path>] [--out <tag_index.json>] [--report]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

KB_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = KB_DIR.parent

DEFAULT_FRAMEWORK = BACKEND_DIR / "prompt" / "knowledge_tag_framework.json"
DEFAULT_OUT = KB_DIR / "index" / "tag_index.json"
DEFAULT_CHAPTERS = KB_DIR / "index" / "chapters.json"


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def load_framework_file(path: Path) -> Tuple[dict, dict]:
    """读取框架文件，统一返回 (hierarchy, keyword_index)。

    两种形态都支持：dict（含 hierarchy/keyword_index）/ 扁平行 list。
    """
    data = json.loads(path.read_text(encoding="utf-8"))

    if isinstance(data, dict):
        hierarchy = data.get("hierarchy") or {}
        keyword_index = data.get("keyword_index") or {}
        return hierarchy, keyword_index

    if isinstance(data, list):
        # 扁平行 → 组装 hierarchy（domain → grade → chapter → [sub_tag]）
        hierarchy = {}
        keyword_index = {}
        for row in data:
            domain = str(row.get("version") or "").strip()
            grade = str(row.get("grade") or "").strip()
            chapter = str(row.get("main_tag") or "").strip()
            section = str(row.get("sub_tag") or "").strip()
            if not (domain and grade and chapter and section):
                continue
            hierarchy.setdefault(domain, {}).setdefault(grade, {}).setdefault(chapter, [])
            if section not in hierarchy[domain][grade][chapter]:
                hierarchy[domain][grade][chapter].append(section)
            keyword = str(row.get("keyword") or "").strip()
            if keyword:
                keyword_index[section] = keyword
        return hierarchy, keyword_index

    raise ValueError(f"框架文件形态无法识别（{type(data).__name__}）：{path}")


def build_chapters(hierarchy: dict) -> Dict[str, Dict[str, List[str]]]:
    """章节清单：domain → grade → [chapter]（保持框架里的出现顺序）。"""
    return {
        domain: {grade: list(chapters.keys()) for grade, chapters in grades.items()}
        for domain, grades in hierarchy.items()
    }


def build_docs(hierarchy: dict, keyword_index: dict) -> List[dict]:
    """标签树 → 知识点行（domain/grade/chapter/section/keyword）。"""
    docs: List[dict] = []
    for domain, grades in hierarchy.items():
        for grade, chapters in grades.items():
            for chapter, sections in chapters.items():
                for section in sections:
                    docs.append({
                        "domain": domain,
                        "grade": grade,
                        "chapter": chapter,
                        "section": section,
                        "keyword": keyword_index.get(section, "") or "",
                    })
    return docs


def main() -> int:
    parser = argparse.ArgumentParser(description="构建知识库（知识域/年级/章节）离线索引")
    parser.add_argument("--framework", default=str(DEFAULT_FRAMEWORK),
                        help="标签框架文件（dict 形态或扁平行 list 形态）")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="索引输出路径")
    parser.add_argument("--chapters-out", default=str(DEFAULT_CHAPTERS), help="章节清单输出路径")
    parser.add_argument("--report", action="store_true", help="打印索引统计")
    args = parser.parse_args()

    framework_path = Path(args.framework)
    if not framework_path.exists():
        log(f"框架文件不存在：{framework_path}")
        return 1

    log(f"读取标签框架：{framework_path}")
    hierarchy, keyword_index = load_framework_file(framework_path)
    if not hierarchy:
        log("框架 hierarchy 为空，退出")
        return 1

    log("构建知识点行清单（检索结构由 kb_index 在内存重建）...")
    docs = build_docs(hierarchy, keyword_index)
    if not docs:
        log("索引为空，退出")
        return 1

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps({
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "dimensions": ["domain", "grade", "chapter", "section"],
            "source": str(framework_path),
            "n_docs": len(docs),
            "docs": docs,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log(f"索引已保存：{out_path}（{len(docs)} 条知识点）")

    chapters = build_chapters(hierarchy)
    chapters_path = Path(args.chapters_out)
    chapters_path.parent.mkdir(parents=True, exist_ok=True)
    chapters_path.write_text(
        json.dumps({"generated_at": datetime.now().isoformat(timespec="seconds"),
                    "source": str(framework_path),
                    "domains": chapters}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log(f"章节清单已保存：{chapters_path}")

    if args.report:
        grades = sorted({g for dv in hierarchy.values() for g in dv})
        log(f"知识域: {len(hierarchy)} 个 → {'、'.join(hierarchy.keys())}")
        log(f"年级: {len(grades)} 个 → {'、'.join(grades)}")
        log(f"章节: {sum(len(ch) for dv in hierarchy.values() for ch in dv.values())} 个")
    return 0


if __name__ == "__main__":
    sys.exit(main())
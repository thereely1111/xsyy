# -*- coding: utf-8 -*-
"""知识库检索 CLI：题面 → 年级 / 章节（知识域 + 年级 + 章节，无教材版本维度）。

用法：
    python scripts/search.py --question "解方程 2x+3=7" [--domain 方程与不等式] [--grade 七上]
                            [--stage junior_high] [--top-k 5] [--json]

输出（`--json` 时）：{"ok": true, "hits": [{domain, grade, chapter, section, score, keyword}], "best": {...}}
`best` 是 Top-1，即 content_profile 里 `grade_chapter` 的取值来源；无命中时为 null。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

KB_DIR = Path(__file__).resolve().parent.parent
if str(KB_DIR) not in sys.path:
    sys.path.insert(0, str(KB_DIR))

import kb_index  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="知识库（年级/章节）检索")
    parser.add_argument("--question", required=True, help="题面文本")
    parser.add_argument("--domain", default=None, help="知识域限定，如「方程与不等式」")
    parser.add_argument("--grade", default=None, help="精确年级限定，如「七上」")
    parser.add_argument("--stage", default=None, choices=["primary", "junior_high"],
                        help="学段限定（展开为年级集合）")
    parser.add_argument("--top-k", type=int, default=5, help="返回条数")
    parser.add_argument("--index", default=None, help="索引路径（默认 knowledge/index/tag_index.json）")
    parser.add_argument("--json", action="store_true", help="输出 JSON（默认同样输出 JSON，仅便于显式声明）")
    args = parser.parse_args()

    try:
        index = kb_index.load_index(args.index)
    except FileNotFoundError as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        return 2

    hits = kb_index.search(index, args.question, domain=args.domain,
                           grade=args.grade, stage=args.stage, top_k=args.top_k)
    print(json.dumps({
        "ok": True,
        "question": args.question,
        "filters": {"domain": args.domain, "grade": args.grade, "stage": args.stage},
        "hits": hits,
        "best": hits[0] if hits else None,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
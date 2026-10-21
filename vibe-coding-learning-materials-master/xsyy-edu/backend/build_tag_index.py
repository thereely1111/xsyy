# -*- coding: utf-8 -*-
"""构建轻档标签向量索引（纯 Python 字符 n-gram TF-IDF，零第三方依赖）。

从 knowledge_tag_framework（经 knowledge_tag_injector.load_framework 读取）构建
标签文档索引并 dump 为 JSON。在线识别时也可直接用内存构建（from_framework），
本脚本产出的 JSON 用于部署/离线复用/评测。

用法：
    python build_tag_index.py [--out data/tag_index_lexical.json] [--report]

--report 额外打印标签数量、词典大小、词项分布等统计。
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

backend_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(backend_dir))

from knowledge_tag_injector import load_framework  # noqa: E402
from knowledge_tag_rag import TagIndex  # noqa: E402

DEFAULT_OUT = backend_dir / "data" / "tag_index_lexical.json"


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="构建轻档标签向量索引")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="索引输出 JSON 路径")
    parser.add_argument("--report", action="store_true", help="打印索引统计")
    args = parser.parse_args()

    log("加载标签框架（远程数据库）...")
    framework = load_framework()
    if not framework or not framework.get("hierarchy"):
        log("标签框架为空：请确认数据库可达且 knowledge_tag_framework 有数据", "ERROR" if False else "ERROR")
        return 1

    log("构建字符 n-gram TF-IDF 索引...")
    index = TagIndex.from_framework(framework)
    if len(index) == 0:
        log("索引为空，退出", "ERROR")
        return 1

    index.save(args.out)
    log(f"索引已保存：{args.out}（{len(index)} 条标签）")

    if args.report:
        log(f"标签数（sub_tag 条目数）: {len(index)}")
        log(f"知识域分布: {_domain_dist(index)}")
        log(f"词典大小（唯一 n-gram 数）: {len(index.df)}")
        log(f"平均标签文档字符数: {sum(len(d['doc_text']) for d in index.docs) / max(len(index), 1):.1f}")
    return 0


def _domain_dist(index: TagIndex) -> str:
    from collections import Counter
    counter = Counter(d["version"] for d in index.docs)
    return "、".join(f"{k}={v}" for k, v in counter.most_common())


if __name__ == "__main__":
    sys.exit(main())

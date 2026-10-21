#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""为有明确生活题意的案例重新生成 2.0 风格封面。

用法：
    python 按题意重生成封面.py             # 删除旧 Preview.webp 并重新生成
    python 按题意重生成封面.py --dry-run   # 只列出命中的案例，不删除、不生成
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from generate_preview_images import generate_image_for_task, log

backend_dir = Path(__file__).resolve().parent
storage_dir = backend_dir.parent / "storage"
sys.path.insert(0, str(backend_dir))

# 题型词用于识别应用题关系；实体词用于识别题干里的具体故事对象。
TOPIC_WORDS = (
    "相遇", "追及", "追赶", "路程", "速度", "时间", "工程", "工作效率", "和差", "差倍", "倍数",
    "二元", "两元", "两种", "鸡兔", "行程", "平均", "分配", "分给", "分成", "购买", "购物",
    "价格", "找零", "利润", "折扣", "年龄", "面积", "周长", "浓度", "配制", "比例", "百分比",
)
ENTITY_WORDS = (
    "甲", "乙", "姐姐", "妹妹", "哥哥", "弟弟", "爸爸", "妈妈", "老师", "学生", "同学", "小明", "小红",
    "人", "工人", "农民", "客车", "货车", "汽车", "火车", "校车", "自行车", "船", "飞机", "春游",
    "旅行", "学校", "商店", "书", "本", "铅笔", "苹果", "糖果", "水果", "鸡", "兔", "动物", "球",
    "箱", "桶", "水", "钱", "元", "商品", "衣服", "票", "座位", "队伍", "比赛",
)
ACTION_WORDS = (
    "有", "共", "一共", "相差", "多", "少", "每", "分", "买", "卖", "用去", "剩下", "出发", "到达",
    "经过", "返回", "同时", "工作", "完成", "装", "运", "借", "还", "交换", "增加", "减少", "分配",
)


def metadata_text(metadata: dict) -> str:
    tags = metadata.get("knowledge_tags")
    tag_text = " ".join(str(value) for value in tags.values()) if isinstance(tags, dict) else str(tags or "")
    return " ".join(
        str(metadata.get(key, ""))
        for key in ("title", "question", "prompt", "description")
    ) + " " + tag_text


def has_clear_story_context(metadata: dict) -> bool:
    """判断是否值得把已有封面按题意重画，避免只因出现‘函数’就重生成。"""
    text = metadata_text(metadata)
    has_topic = any(word in text for word in TOPIC_WORDS)
    entity_count = sum(word in text for word in ENTITY_WORDS)
    has_action = any(word in text for word in ACTION_WORDS)
    return (has_topic and entity_count >= 1) or (entity_count >= 2 and has_action)


def load_metadata(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log(f"读取 metadata 失败: {path.parent.name}: {exc}", "ERROR")
        return None


async def main(dry_run: bool) -> None:
    if not storage_dir.exists():
        log(f"Storage 目录不存在: {storage_dir}", "ERROR")
        return

    matched = 0
    generated = 0
    skipped = 0
    failed = 0

    for task_dir in sorted(path for path in storage_dir.iterdir() if path.is_dir()):
        metadata_path = task_dir / "metadata.json"
        preview_path = task_dir / "Preview.webp"
        if not metadata_path.exists() or not preview_path.exists():
            skipped += 1
            continue
        if not ((task_dir / "teaching.html").exists() or (task_dir / "teaching_data.json").exists()):
            skipped += 1
            continue

        metadata = load_metadata(metadata_path)
        if metadata is None or not has_clear_story_context(metadata):
            skipped += 1
            continue

        matched += 1
        title = str(metadata.get("title", "数学问题"))[:50]
        if dry_run:
            log(f"[DRY] 命中: {task_dir.name} | {title}")
            continue

        try:
            preview_path.unlink()
            log(f"已删除旧封面: {task_dir.name}")
            if await generate_image_for_task(task_dir, metadata, force=True):
                generated += 1
            else:
                failed += 1
        except Exception as exc:
            failed += 1
            log(f"案例 {task_dir.name} 重生成失败: {exc}", "ERROR")

    log(
        f"题意封面处理完成：命中 {matched} 个，生成 {generated} 张，"
        f"失败 {failed} 个，跳过 {skipped} 个"
        + ("（DRY 模式，未删除和生成）" if dry_run else "")
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="按明显题意重生成封面")
    parser.add_argument("--dry-run", action="store_true", help="只列出命中案例，不修改文件")
    args = parser.parse_args()
    asyncio.run(main(args.dry_run))

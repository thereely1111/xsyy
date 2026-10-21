# -*- coding: utf-8 -*-
"""用两步标签识别模型（知识域+年级 → 知识点标签）重新识别全部存量题目标签。

- 遍历 teachings 表中有题目的记录
- 调用 knowledge_tag_injector.inject_knowledge_tags_full 重新识别
- 同步更新数据库 knowledge_tags / main_tag / sub_tags / second_tag 与 metadata.json
- 保留原 knowledge_tags_confirmed 标记

用法：python reidentify_all_tags.py [--dry]
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

backend_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy.orm.attributes import flag_modified  # noqa: E402

from database import SessionLocal  # noqa: E402
from database.models import Teaching  # noqa: E402
from knowledge_tag_injector import inject_knowledge_tags_full  # noqa: E402

STORAGE_DIR = backend_dir.parent / "storage"
DRY = "--dry" in sys.argv


def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


async def main():
    db = SessionLocal()
    teachings = db.query(Teaching).filter(
        Teaching.question.isnot(None),
        Teaching.question != "",
    ).all()
    total = len(teachings)
    log(f"共 {total} 个教学内容待重新识别" + ("（DRY 模式，不写库）" if DRY else ""))

    ok = fail = skip = 0
    for i, t in enumerate(teachings, 1):
        task_id = t.task_id
        question = (t.question or "").strip()
        if not question:
            skip += 1
            continue
        try:
            kt = await inject_knowledge_tags_full(question, title=(t.title or ""))
        except Exception as e:
            log(f"[{i}/{total}] {task_id[:8]} 识别异常: {e}")
            fail += 1
            continue

        if not kt or not kt.get("primary") or not kt["primary"].get("main_tag"):
            log(f"[{i}/{total}] {task_id[:8]} 未能识别，跳过")
            fail += 1
            continue

        primary = kt["primary"]
        second = kt.get("second")
        log(f"[{i}/{total}] {task_id[:8]} => 主: 知识域={primary.get('version')} 年级={primary.get('grade')} 章/单元={primary.get('main_tag')} 知识点={primary.get('sub_tags')}"
            + (f" | 第二: 知识域={second.get('version')} 章/单元={second.get('main_tag')}" if second else ""))

        if DRY:
            ok += 1
            continue

        # 1) 更新数据库
        t.main_tag = primary["main_tag"]
        t.sub_tags = primary.get("sub_tags", [])
        t.knowledge_tags = {
            "version": primary.get("version", ""),
            "grade": primary.get("grade", ""),
            "main_tag": primary["main_tag"],
            "sub_tags": primary.get("sub_tags", []),
        }
        t.second_tag = second
        flag_modified(t, "sub_tags")
        flag_modified(t, "knowledge_tags")
        flag_modified(t, "second_tag")

        # 2) 更新 metadata.json（保留 confirmed 标记）
        meta_path = STORAGE_DIR / task_id / "metadata.json"
        try:
            if meta_path.exists():
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            else:
                meta = {}
            meta["knowledge_tags"] = t.knowledge_tags
            meta["second_tag"] = t.second_tag
            meta["needs_tag_selection"] = False
            meta["knowledge_tags_updated_at"] = datetime.utcnow().isoformat() + "Z"
            meta_path.parent.mkdir(parents=True, exist_ok=True)
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log(f"  {task_id[:8]} metadata.json 更新失败（不影响数据库）: {e}")

        ok += 1
        # 分批提交，避免长事务
        if i % 5 == 0:
            db.commit()

    db.commit()
    db.close()
    log(f"完成：成功 {ok}，失败 {fail}，跳过 {skip}")


if __name__ == "__main__":
    asyncio.run(main())

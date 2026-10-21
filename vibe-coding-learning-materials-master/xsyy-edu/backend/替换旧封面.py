#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""为所有缺少 Preview.webp 的案例补生成 2.0 风格封面，并同步数据库。

用法：
    python 替换旧封面.py                      # 补生成封面（生成成功后会同步 DB）
    python 替换旧封面.py --sync-db            # DRY：列出 DB preview_image 需要回填的行
    python 替换旧封面.py --sync-db --execute  # 真正回填 DB（Preview.webp 已存在但 DB 未同步的存量数据）
"""

import asyncio
import json
import sys
from pathlib import Path

from generate_preview_images import generate_image_for_task, log

backend_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(backend_dir))
storage_dir = backend_dir.parent / "storage"

SYNC_DB = "--sync-db" in sys.argv
EXECUTE = "--execute" in sys.argv


def sync_db_preview_images() -> None:
    """把磁盘上已存在的 Preview.webp 回填到 DB 的 preview_image 列（默认 DRY）。"""
    from database import SessionLocal
    from database.models import Teaching

    if not storage_dir.exists():
        log(f"Storage 目录不存在: {storage_dir}", "ERROR")
        return

    db = SessionLocal()
    teachings_by_id = {t.task_id: t for t in db.query(Teaching).all()}
    pending = [
        teachings_by_id[task_dir.name]
        for task_dir in sorted(path for path in storage_dir.iterdir() if path.is_dir())
        if (task_dir / "Preview.webp").exists()
        and task_dir.name in teachings_by_id
        and teachings_by_id[task_dir.name].preview_image != "Preview.webp"
    ]

    log(f"共 {len(pending)} 条记录的 DB preview_image 需要回填为 Preview.webp"
        + ("（DRY 模式，不写库）" if not EXECUTE else ""))
    for i, teaching in enumerate(pending, 1):
        log(f"  [{i}/{len(pending)}] {teaching.task_id}  {teaching.preview_image!r} -> 'Preview.webp'")
        if EXECUTE:
            teaching.preview_image = "Preview.webp"
            if i % 20 == 0:
                db.commit()
    if EXECUTE and pending:
        db.commit()
        log(f"回填完成：{len(pending)} 条")
    db.close()


async def main() -> None:
    if SYNC_DB:
        sync_db_preview_images()
        return

    if not storage_dir.exists():
        log(f"Storage 目录不存在: {storage_dir}", "ERROR")
        return

    task_dirs = sorted(path for path in storage_dir.iterdir() if path.is_dir())
    generated = 0
    skipped = 0

    for task_dir in task_dirs:
        new_cover = task_dir / "Preview.webp"
        metadata_path = task_dir / "metadata.json"

        if new_cover.exists() or not metadata_path.exists():
            skipped += 1
            continue
        if not ((task_dir / "teaching.html").exists() or (task_dir / "teaching_data.json").exists()):
            skipped += 1
            continue

        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if await generate_image_for_task(task_dir, metadata):
                generated += 1
        except Exception as exc:
            log(f"案例 {task_dir.name} 生成失败: {exc}", "ERROR")

    log(f"补生成完成：生成 {generated} 张 2.0 封面，跳过 {skipped} 个案例")


if __name__ == "__main__":
    asyncio.run(main())

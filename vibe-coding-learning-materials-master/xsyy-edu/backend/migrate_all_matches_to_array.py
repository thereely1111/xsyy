"""将 teachings.knowledge_tags 归一化为单标签组对象（兼容历史数组/all_matches）。

默认只预览，加 --execute 执行数据库更新。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from database import engine
from sqlalchemy import text

DRY_RUN = "--execute" not in sys.argv


def normalize_knowledge_tags(value):
    """将历史对象或数组压缩为一个 knowledge_tags 对象。"""
    if isinstance(value, str):
        value = json.loads(value)
    if isinstance(value, list):
        value = next((item for item in value if isinstance(item, dict) and item.get("main_tag")), None)
    if not isinstance(value, dict) or not value.get("main_tag"):
        return None
    return {
        "version": value.get("version", ""),
        "grade": value.get("grade", ""),
        "main_tag": value.get("main_tag", ""),
        "sub_tags": value.get("sub_tags", []) if isinstance(value.get("sub_tags", []), list) else [],
    }


def main():
    mode = "DRY-RUN 模式" if DRY_RUN else "执行模式"
    print(f"[{mode}] 清理 teachings.knowledge_tags 中的旧数组和 all_matches")

    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT task_id, knowledge_tags FROM teachings WHERE knowledge_tags IS NOT NULL"
        )).fetchall()
        changes = []
        for task_id, raw_value in rows:
            try:
                normalized = normalize_knowledge_tags(raw_value)
            except Exception as exc:
                print(f"跳过 {task_id}: JSON 解析失败: {exc}")
                continue
            if normalized is None:
                continue
            original = json.loads(raw_value) if isinstance(raw_value, str) else raw_value
            if normalized != original:
                changes.append((task_id, normalized))

        print(f"总记录数: {len(rows)}，待清理: {len(changes)}")
        for task_id, normalized in changes[:10]:
            print(f"  {task_id[:8]}... -> {normalized['version']}·{normalized['grade']}·{normalized['main_tag']}")

        if DRY_RUN or not changes:
            return

        for task_id, normalized in changes:
            conn.execute(text(
                "UPDATE teachings SET knowledge_tags = :kt, main_tag = :mt, sub_tags = :st WHERE task_id = :tid"
            ), {
                "kt": json.dumps(normalized, ensure_ascii=False),
                "mt": normalized["main_tag"],
                "st": json.dumps(normalized["sub_tags"], ensure_ascii=False),
                "tid": task_id,
            })
        conn.commit()
        print(f"迁移完成: {len(changes)} 条")


if __name__ == "__main__":
    main()

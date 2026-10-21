#!/usr/bin/env python3
"""
象数演易 — 教学动画 JSON 一键导入脚本

将网页版 AI 生成的 JSON 导入项目 storage 目录，自动创建：
- teaching_data.json
- metadata.json
- 数据库记录（可选）

用法:
  python scripts/import_teaching_data.py \
    --task-id my-test-001 \
    --json-file ./ai-output.json \
    --question "题目文本" \
    --tag "运算能力"

  # 如果 AI 输出的 JSON 中包含 title/summary/question，可省略部分参数：
  python scripts/import_teaching_data.py \
    --task-id my-test-001 \
    --json-file ./ai-output.json
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
STORAGE_DIR = PROJECT_ROOT / "storage"
VALID_TAGS = [
    "模型意识", "数据意识", "空间观念", "几何直观",
    "符号意识", "量感", "数感", "推理意识", "运算能力",
]


def load_ai_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()

    raw = raw.strip()

    if raw.startswith("```"):
        lines = raw.split("\n")
        start = 0
        end = len(lines)
        for i, line in enumerate(lines):
            if line.strip().startswith("```") and i == 0:
                start = i + 1
            elif line.strip() == "```":
                end = i
        raw = "\n".join(lines[start:end])

    data = json.loads(raw)
    return data


def validate_data(data: dict) -> list[str]:
    errors = []

    if "scene_svg" not in data:
        errors.append("缺少 scene_svg 字段")
    if "steps" not in data:
        errors.append("缺少 steps 字段")

    scene_svg = data.get("scene_svg", "")
    if not scene_svg or not scene_svg.strip():
        errors.append("scene_svg 为空")

    for tag in ["<svg", "<script", "<html", "<body"]:
        if tag in scene_svg.lower():
            errors.append(f"scene_svg 中包含禁止的标签: {tag}")

    if "currentStep" in scene_svg and "sceneStep" not in scene_svg:
        errors.append(
            "scene_svg 中使用了 currentStep 而非 sceneStep。"
            "模板中 SVG 画布使用 sceneStep（1-based），请修正。"
        )

    x_show_count = scene_svg.lower().count("x-show")
    if x_show_count < 8:
        errors.append(f"x-show 条件块仅 {x_show_count} 个（要求 ≥ 8）")

    range_count = 0
    for op in [">=", "<=", "&&"]:
        range_count += scene_svg.count(op)
    if range_count < 3:
        errors.append(f"范围判断仅 {range_count} 个（要求 ≥ 3）")

    transition_count = scene_svg.lower().count("x-transition")
    if transition_count < 3:
        errors.append(f"x-transition 仅 {transition_count} 处（要求 ≥ 3）")

    steps = data.get("steps", [])
    if not isinstance(steps, list):
        errors.append("steps 必须是数组")
    elif len(steps) < 6 or len(steps) > 15:
        errors.append(f"steps 数量 {len(steps)}（要求 6-15）")
    else:
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                errors.append(f"steps[{i}] 不是对象")
                continue
            for field in ["title", "description", "bubbleText"]:
                if not step.get(field, "").strip():
                    errors.append(f"steps[{i}].{field} 为空")
            bp = step.get("bubblePos")
            if not isinstance(bp, dict):
                errors.append(f"steps[{i}].bubblePos 必须为对象")
            elif not isinstance(bp.get("x"), (int, float)) or not isinstance(bp.get("y"), (int, float)):
                errors.append(f"steps[{i}].bubblePos.x/y 必须是数值")

    return errors


def create_teaching_data(data: dict) -> dict:
    title = data.get("title", "数学互动教学")
    summary = data.get("summary", "")
    scene_svg = data.get("scene_svg", "")
    steps = data.get("steps", [])

    steps_json = json.dumps(steps, ensure_ascii=False, indent=4)

    steps_json = steps_json.replace("</", "<\\/")
    steps_json = steps_json.replace("\u2028", "\\u2028")
    steps_json = steps_json.replace("\u2029", "\\u2029")

    summary = summary.replace("'", "\\'")
    summary = summary.replace("\u2028", "\\u2028")
    summary = summary.replace("\u2029", "\\u2029")

    return {
        "title": title,
        "summary": summary,
        "scene_svg": scene_svg,
        "steps_json": steps_json,
    }


def create_metadata(
    task_id: str,
    question: str,
    title: str,
    tag: str,
) -> dict:
    return {
        "question": question,
        "prompt": "",
        "plan": {"steps": []},
        "input_file": "",
        "task_id": task_id,
        "generated_at": datetime.now().isoformat() + "Z",
        "teaching_html_file": "teaching_data.json",
        "is_math_problem": True,
        "title": title,
        "has_pic": False,
        "tags": {
            "reasoning": "手动导入",
            "main_tag": tag,
            "sub_tags": [],
        },
        "tags_updated_at": datetime.now().isoformat() + "Z",
    }


def write_db_record(task_dir: Path, metadata: dict, tag: str):
    db_dir = PROJECT_ROOT / "backend" / "database"
    if not db_dir.exists():
        print(f"  [跳过] 未找到数据库目录: {db_dir}")
        return False

    try:
        sys.path.insert(0, str(PROJECT_ROOT / "backend"))
        from database.models import Teaching
        from database.session import SessionLocal

        db = SessionLocal()
        try:
            existing = db.query(Teaching).filter(
                Teaching.task_id == metadata["task_id"]
            ).first()

            if existing:
                existing.question = metadata["question"]
                existing.title = metadata["title"]
                existing.main_tag = tag
                existing.teaching_html_file = "teaching_data.json"
                existing.generated_at = datetime.fromisoformat(
                    metadata["generated_at"].rstrip("Z")
                )
                print(f"  [更新] 数据库记录已更新: task_id={metadata['task_id']}")
            else:
                record = Teaching(
                    task_id=metadata["task_id"],
                    user_id=None,
                    question=metadata["question"],
                    prompt="",
                    title=metadata["title"],
                    is_math_problem=True,
                    has_pic=False,
                    main_tag=tag,
                    sub_tags=[],
                    reasoning="手动导入",
                    generated_at=datetime.fromisoformat(
                        metadata["generated_at"].rstrip("Z")
                    ),
                    input_file="",
                    teaching_html_file="teaching_data.json",
                    preview_image=None,
                )
                db.add(record)
                print(f"  [创建] 数据库记录已创建: task_id={metadata['task_id']}")

            db.commit()
            return True
        finally:
            db.close()
    except ImportError as e:
        print(f"  [跳过] 无法导入数据库模块: {e}")
        return False
    except Exception as e:
        print(f"  [错误] 数据库操作失败: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="象数演易 — 教学动画 JSON 一键导入"
    )
    parser.add_argument(
        "--task-id", required=True,
        help="任务 ID（将作为 storage 子目录名）"
    )
    parser.add_argument(
        "--json-file", required=True,
        help="AI 输出的 JSON 文件路径"
    )
    parser.add_argument(
        "--question", default="",
        help="题目文本（如 JSON 中不含 question 字段则必填）"
    )
    parser.add_argument(
        "--tag", default="运算能力",
        choices=VALID_TAGS,
        help="主标签（默认: 运算能力）"
    )
    parser.add_argument(
        "--skip-validation", action="store_true",
        help="跳过质量自检"
    )
    parser.add_argument(
        "--skip-db", action="store_true",
        help="跳过数据库写入"
    )
    args = parser.parse_args()

    print(f"\n{'='*50}")
    print(f"  象数演易 — 教学动画导入")
    print(f"  任务 ID: {args.task_id}")
    print(f"  JSON 文件: {args.json_file}")
    print(f"{'='*50}\n")

    print("[1/4] 加载 JSON...")
    try:
        data = load_ai_json(args.json_file)
    except json.JSONDecodeError as e:
        print(f"  [错误] JSON 解析失败: {e}")
        sys.exit(1)
    except FileNotFoundError:
        print(f"  [错误] 文件不存在: {args.json_file}")
        sys.exit(1)
    print(f"  字段: {list(data.keys())}")

    print("\n[2/4] 质量自检...")
    if args.skip_validation:
        print("  [跳过] 已指定 --skip-validation")
    else:
        errors = validate_data(data)
        if errors:
            print(f"  [警告] 发现 {len(errors)} 个问题:")
            for e in errors:
                print(f"    - {e}")
            answer = input("\n  是否仍要继续导入？(y/N): ").strip().lower()
            if answer != "y":
                print("  已取消导入。")
                sys.exit(0)
        else:
            print("  [通过] 所有检查项均通过")

    task_dir = STORAGE_DIR / args.task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n[3/4] 写入文件...")
    print(f"  目录: {task_dir}")

    teaching_data = create_teaching_data(data)
    data_path = task_dir / "teaching_data.json"
    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(teaching_data, f, ensure_ascii=False, indent=2)
    print(f"  [写入] teaching_data.json ({len(json.dumps(teaching_data, ensure_ascii=False))} 字符)")

    title = data.get("title", "数学互动教学")
    question = args.question or data.get("question", "")
    if not question:
        question = title

    metadata = create_metadata(args.task_id, question, title, args.tag)
    meta_path = task_dir / "metadata.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
    print(f"  [写入] metadata.json")

    print(f"\n[4/4] 写入数据库...")
    if args.skip_db:
        print("  [跳过] 已指定 --skip-db")
    else:
        write_db_record(task_dir, metadata, args.tag)

    print(f"\n{'='*50}")
    print(f"  导入完成!")
    print(f"  任务目录: {task_dir}")
    print(f"  预览地址: http://localhost:PORT/api/teachings/{args.task_id}/html")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()

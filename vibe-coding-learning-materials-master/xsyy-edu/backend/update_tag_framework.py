"""更新知识点标签框架：从新 Excel（知识域/年级/章单元/模块级）同步到 数据库表 + JSON 文件。

标签体系（对应《初中数学知识点标签表_知识域年级_模块级.xlsx》）：
    知识域（5） → 年级（8） → 章/单元 → 知识点标签（模块级） + 强特征关键词

字段映射（沿用原有字段名，语义更换）：
    framework.version  = 知识域
    framework.grade    = 年级
    framework.main_tag = 章/单元
    framework.sub_tag  = 知识点标签（模块级）
    framework.keyword  = 强特征关键词（题面命中，仅作大模型判断依据）

用法：
    cd backend
    python update_tag_framework.py            # dry-run 预览
    python update_tag_framework.py --execute  # 执行（备份旧JSON + 加keyword列 + 清空DB重插 + 覆盖JSON）
"""
import sys
import json
import shutil
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

BACKEND = Path(__file__).resolve().parent
EXCEL = Path(r"E:\象数演易\初中数学知识点标签表_知识域年级_模块级.xlsx")
JSON_PATH = BACKEND / "prompt" / "knowledge_tag_framework.json"

# 知识域固定顺序（与 Excel 一致）
DOMAIN_ORDER = ["数与式", "方程与不等式", "函数", "图形与几何", "统计与概率"]
GRADE_ORDER = ["六上", "六下", "七上", "七下", "八上", "八下", "九上", "九下"]

# Excel 标签库未覆盖的基础题型补充项。保留在生成脚本中，避免下次同步 Excel 时丢失。
EXTENDED_ROWS = [
    ("数与式", "六上", "数的运算基础", "基础整数加减法", "被减数、减数、差、加数、和、还剩、花了、一共、加减法各部分名称"),
    ("数与式", "六上", "数的运算基础", "基础整数乘除法", "被除数、除数、商、乘积、因数、倍数、个位的0去掉"),
    ("数与式", "六上", "数的运算基础", "数的组成与位值", "组成三位数、组成两位数、个位、十位、百位、数字各一次、和最大、和最小、差最大、差最小"),
    ("数与式", "六上", "数的运算基础", "整数分配与最值", "每人至少、每天至少、最多、最少、分得最多、分得最少、乘积最大、乘积最小、非零自然数、分给"),
    ("数与式", "六上", "数的运算基础", "逻辑推理", "真假话、小偷、好人、从犯、职业、推理、排除、可疑的人"),
    ("数与式", "六上", "数的运算基础", "整数周期与分配", "每天至少、每天最多、每周、每次至少、最少需要几天、最多需要几天、分配、播放几集"),
    ("数与式", "六上", "数的运算基础", "余数与同余问题", "余数、同余、分别除以、除后余数、余数分别是、最小自然数、被除数、除数、商"),
    ("数与式", "六上", "行程问题", "相遇与追及问题", "相向而行、同向而行、相遇、追及、追上、第一次相遇、第二次相遇、掉头、折返、往返、速度、路程、时间"),
    ("图形与几何", "六上", "平面图形", "长方形周长与面积", "长方形、矩形、长、宽、周长、面积、厘米、平方厘米"),
    ("方程与不等式", "七上", "一元一次方程", "相遇与追及问题", "相向而行、同向而行、相遇、追及、追上、速度、路程、时间"),
    ("方程与不等式", "七上", "一元一次方程", "列车过桥过隧道问题", "列车、火车、隧道、遂道、过桥、通过、错车而过、车长、每秒"),
]


def _normalize_label(value: object) -> str:
    """统一标签名称，移除 Excel 中混入的空白字符。"""
    return "".join(str(value or "").split())


def _clean_chapter(raw: str) -> str:
    """清理章/单元名称中的备注型括号（含"节/参考数据/校正"等说明），保留正式名称。"""
    ch = raw.strip()
    while "（" in ch:
        start = ch.find("（")
        end = ch.find("）", start)
        if end == -1:
            break
        inner = ch[start + 1:end]
        if any(k in inner for k in ("节", "参考数据", "校正", "补全")):
            ch = (ch[:start] + ch[end + 1:]).strip()
        else:
            break
    return ch


def read_excel_rows():
    """读取 Excel 标签行，并追加脚本内置的补充题型（EXTENDED_ROWS）。"""
    import pandas as pd
    df = pd.read_excel(EXCEL, sheet_name="标签总表")
    rows = []
    for _, r in df.iterrows():
        dom = _normalize_label(r["知识域"])
        grade = _normalize_label(r["年级"])
        chapter = _clean_chapter(str(r["章/单元"]))
        tag = _normalize_label(r["知识点标签（模块级）"])
        kw = str(r["强特征关键词（题面命中）"]).strip()
        if dom and grade and chapter and tag and dom != "nan":
            rows.append((dom, grade, chapter, tag, kw))
    # EXTENDED_ROWS 已为规范命名，无需再次归一化
    return rows + list(EXTENDED_ROWS)


def build_json(rows):
    """按固定顺序构建标签框架 JSON（versions/domains 同义，仅保留 versions）。"""
    domains = []
    for d in DOMAIN_ORDER:
        if any(r[0] == d for r in rows):
            domains.append(d)
    grades = [g for g in GRADE_ORDER if any(r[1] == g for r in rows)]
    main_tags = []
    for r in rows:
        if r[2] not in main_tags:
            main_tags.append(r[2])

    main_tag_info = {}
    hierarchy = {}
    sub_tag_index = {}
    keyword_index = {}
    for dom, grade, chapter, tag, kw in rows:
        hierarchy.setdefault(dom, {}).setdefault(grade, {}).setdefault(chapter, [])
        if tag not in hierarchy[dom][grade][chapter]:
            hierarchy[dom][grade][chapter].append(tag)
        info = main_tag_info.setdefault(chapter, {"grades": [], "sub_tags": []})
        if grade not in info["grades"]:
            info["grades"].append(grade)
        if tag not in info["sub_tags"]:
            info["sub_tags"].append(tag)
        sub_tag_index.setdefault(tag, []).append(
            {"main_tag": chapter, "grade": grade, "version": dom, "keyword": kw}
        )
        keyword_index.setdefault(tag, kw)

    return {
        "description": "初中数学知识点标签框架 —— 知识域 → 年级 → 章/单元 → 知识点标签（模块级），附强特征关键词",
        "structure": "domain -> grade -> chapter -> knowledge_tags (+ keywords)",
        "versions": domains,
        "grades": grades,
        "main_tags": main_tags,
        "main_tag_info": main_tag_info,
        "hierarchy": hierarchy,
        "sub_tag_index": sub_tag_index,
        "keyword_index": keyword_index,
    }


def ensure_keyword_column(conn):
    """确保 knowledge_tag_framework 表存在 keyword 列（强特征关键词）。"""
    from sqlalchemy import text
    cols = conn.execute(text("SHOW COLUMNS FROM knowledge_tag_framework")).fetchall()
    col_names = [c[0] for c in cols]
    if "keyword" not in col_names:
        conn.execute(text(
            "ALTER TABLE knowledge_tag_framework ADD COLUMN keyword VARCHAR(500) NULL "
            "AFTER sub_tag"
        ))
        print("已添加 keyword 列")
    else:
        print("keyword 列已存在")


def main():
    execute = "--execute" in sys.argv
    rows = read_excel_rows()
    n_dom = len({r[0] for r in rows})
    n_grade = len({r[1] for r in rows})
    n_ch = len({r[2] for r in rows})
    n_tag = len({r[3] for r in rows})
    print(f"Excel 行数: {len(rows)}  知识域{n_dom} 年级{n_grade} 章/单元{n_ch} 知识点标签{n_tag}")

    if not execute:
        print("[dry-run] 加 --execute 执行")
        return

    shutil.copy(JSON_PATH, str(JSON_PATH) + ".bak")
    print("已备份旧 JSON -> .bak")

    new_json = build_json(rows)
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(new_json, f, ensure_ascii=False, indent=2)
    print(f"已写入新 JSON: domains={len(new_json['versions'])} chapters={len(new_json['main_tags'])} tags={len(new_json['sub_tag_index'])}")

    sys.path.insert(0, str(BACKEND))
    from database.database import engine
    from sqlalchemy import text
    from datetime import datetime
    # 统一使用 UTC 时间入库（与 app.py 中 datetime.utcnow() 的约定一致，
    # 避免用数据库服务器本地时间 NOW() 导致创建时间显示偏移）
    utc_now = datetime.utcnow()
    with engine.begin() as conn:
        ensure_keyword_column(conn)
        old = conn.execute(text("SELECT COUNT(*) FROM knowledge_tag_framework")).scalar()
        conn.execute(text("DELETE FROM knowledge_tag_framework"))
        conn.execute(
            text(
                "INSERT INTO knowledge_tag_framework (version, grade, main_tag, sub_tag, keyword, created_at) "
                "VALUES (:v,:g,:m,:s,:k,:created_at)"
            ),
            [{"v": d, "g": g, "m": ch, "s": t, "k": kw, "created_at": utc_now} for d, g, ch, t, kw in rows],
        )
        new = conn.execute(text("SELECT COUNT(*) FROM knowledge_tag_framework")).scalar()
        print(f"DB 表: {old} -> {new} 行")
    print("完成")


if __name__ == "__main__":
    main()

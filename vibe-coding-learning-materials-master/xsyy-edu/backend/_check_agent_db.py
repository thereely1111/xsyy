# -*- coding: utf-8 -*-
"""检查智能体数据库适配：连通性、库存在性、智能体四张表、关键业务表。"""
import os
import re
import sys

# 从 .env 读取（不硬编码密码）
ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
env = {}
with open(ENV_PATH, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()

url = env.get("TAG_AGENT_REMOTE_DB_URL", "").strip() or env.get("DATABASE_URL", "").strip()
print("TAG_AGENT_REMOTE_DB_URL =", re.sub(r"(//[^:]+:)[^@]+(@)", r"\1***\2", url))

m = re.match(r"mysql\+pymysql://([^:]+):([^@]+)@([^:/]+):(\d+)/([^?]+)", url)
if not m:
    print("!! 无法解析连接串")
    sys.exit(1)
user, pwd, host, port, dbname = m.groups()
print(f"host={host} port={port} user={user} 默认库={dbname}")

import pymysql

TAG_TABLES = [
    "tag_agent_pending_tags",
    "tag_agent_question_proposals",
    "tag_agent_learning_records",
    "tag_agent_recognition_logs",
]
BIZ_TABLES = ["knowledge_tag_framework", "knowledge_point_tags", "user_tags"]

try:
    conn = pymysql.connect(host=host, port=int(port), user=user, password=pwd, connect_timeout=10)
    cur = conn.cursor()
    cur.execute("SELECT VERSION()")
    print("MySQL 版本:", cur.fetchone()[0])

    cur.execute("SHOW DATABASES")
    dbs = [r[0] for r in cur.fetchall()]
    print("\n数据库列表:", dbs)
    for cand in ("xsyy", "test_xsyy", dbname):
        if cand in dbs:
            print(f"  ✓ 库存在: {cand}")
        elif cand != dbname:
            print(f"  ✗ 库不存在: {cand}")

    # 逐库检查智能体表
    for db in ("test_xsyy", "xsyy"):
        if db not in dbs:
            continue
        cur.execute(f"SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=%s", (db,))
        total = cur.fetchone()[0]
        cur.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema=%s",
            (db,),
        )
        tables = {r[0] for r in cur.fetchall()}
        print(f"\n[{db}] 共 {total} 张表")
        for t in TAG_TABLES + BIZ_TABLES:
            mark = "✓" if t in tables else "✗ 缺失"
            kind = "智能体表" if t in TAG_TABLES else "业务表"
            print(f"  {mark} {t} ({kind})")

    cur.close()
    conn.close()
    print("\n== 连通性: OK ==")
except Exception as e:
    print("\n== 连通性: FAIL ==", type(e).__name__, str(e)[:300])
    sys.exit(1)

import sqlite3
from pathlib import Path

db_path = Path(__file__).resolve().parent / "backend" / "xsyy.db"
print("db:", db_path)
con = sqlite3.connect(str(db_path))
cur = con.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%tag%'")
print("tables:", cur.fetchall())
try:
    cur.execute("SELECT id, version, grade, main_tag, sub_tag, created_at FROM knowledge_tag_framework ORDER BY id DESC LIMIT 8")
    for r in cur.fetchall():
        print(r)
except Exception as e:
    print("query error:", e)
con.close()

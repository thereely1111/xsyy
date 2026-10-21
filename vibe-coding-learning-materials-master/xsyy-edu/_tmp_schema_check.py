import sqlite3
from pathlib import Path

db_path = Path("backend/xsyy.db")
con = sqlite3.connect(str(db_path))
cur = con.cursor()
cur.execute(
    "SELECT sql FROM sqlite_master WHERE type='table' AND name='users'"
)
rows = cur.fetchall()
if rows:
    print(rows[0][0])
else:
    print("NO users TABLE")
con.close()

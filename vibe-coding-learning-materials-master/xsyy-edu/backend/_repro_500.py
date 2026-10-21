"""复现 POST /api/admin/tags/corrections 的 500 错误并打印 traceback。"""
import sys, traceback
sys.path.insert(0, ".")

from fastapi.testclient import TestClient
import app as appmod
from types import SimpleNamespace

# 覆盖 require_admin，避免鉴权干扰
def fake_admin():
    return SimpleNamespace(id=1, username="diag", role="admin")

appmod.app.dependency_overrides[appmod.require_admin] = fake_admin

client = TestClient(appmod.app)

# 情况1：仅带 log_id（队列里点改标时前端传的）
payload1 = {
    "log_id": 1,
    "question": "示例题目",
    "correct": False,
    "corrected_version": "数与式",
    "corrected_grade": "一上",
    "corrected_main_tag": "6~10的认识与加减",
    "corrected_sub_tags": ["10以内数的认识"],
    "reason": "测试",
}
try:
    _debug_event("CASE1 request start", {"log_id": payload1["log_id"], "correct": payload1["correct"]})
    r = client.post("/api/admin/tags/corrections", json=payload1)
    _debug_event("CASE1 request end", {"status": r.status_code, "body_prefix": r.text[:120]})
    print("CASE1 status:", r.status_code)
    print("CASE1 body:", r.text[:1000])
except Exception as e:
    print("CASE1 EXCEPTION:")
    traceback.print_exc()

# 情况2：不带 log_id，仅 question
payload2 = {
    "question": "示例题目2",
    "correct": False,
    "corrected_version": "数与式",
    "corrected_grade": "一上",
    "corrected_main_tag": "6~10的认识与加减",
    "corrected_sub_tags": ["10以内数的认识"],
}
try:
    r = client.post("/api/admin/tags/corrections", json=payload2)
    print("CASE2 status:", r.status_code)
    print("CASE2 body:", r.text[:1000])
except Exception as e:
    print("CASE2 EXCEPTION:")
    traceback.print_exc()

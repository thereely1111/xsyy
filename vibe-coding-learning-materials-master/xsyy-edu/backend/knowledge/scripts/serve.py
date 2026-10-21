# -*- coding: utf-8 -*-
"""知识库只读 HTTP 服务（标准库 http.server，零第三方依赖）。

独立进程，**不改动 xsyy 应用代码**、不连数据库、不写任何文件；只读内存索引。

端点（全部 GET，返回 UTF-8 JSON）：
- `/kb/health`                                  → {ok, index_size, domains, grades, generated_at}
- `/kb/search?q=&domain=&grade=&stage=&top_k=`  → {ok, hits[], best}
- `/kb/chapters?domain=&grade=`                 → {ok, domains{}}

启动：
    python scripts/serve.py [--host 127.0.0.1] [--port 18099] [--index <path>]
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

KB_DIR = Path(__file__).resolve().parent.parent
if str(KB_DIR) not in sys.path:
    sys.path.insert(0, str(KB_DIR))

import kb_index  # noqa: E402

_LOCK = threading.Lock()
_INDEX = None
_CHAPTERS: dict = {}
_STATE = {"path": None, "generated_at": None}


def _ensure_index(index_path=None) -> None:
    """懒加载索引（首次请求时载入，进程内单例）。"""
    global _INDEX, _CHAPTERS
    if _INDEX is not None:
        return
    with _LOCK:
        if _INDEX is not None:
            return
        _INDEX = kb_index.load_index(index_path)
        _CHAPTERS = kb_index.load_chapters()
        _STATE["path"] = str(index_path or kb_index.DEFAULT_INDEX)
        _STATE["generated_at"] = _CHAPTERS.get("generated_at")


class KBHandler(BaseHTTPRequestHandler):
    server_version = "xsyy-kb/1.0"

    def _send(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        route = parsed.path.rstrip("/")

        def one(key: str, default=None):
            values = query.get(key) or []
            return values[0].strip() if values and values[0].strip() else default

        try:
            _ensure_index(self.server.index_path)  # type: ignore[attr-defined]
        except Exception as e:  # 索引不可用：明确报错，不静默返回空
            self._send({"ok": False, "error": f"索引不可用：{type(e).__name__}: {e}"}, 503)
            return

        if route in ("/kb/health", "/health"):
            self._send({
                "ok": True,
                "index_size": len(_INDEX),
                "index_path": _STATE["path"],
                "generated_at": _STATE["generated_at"],
                "domains": sorted({d["version"] for d in _INDEX.docs}),
                "grades": sorted({d["grade"] for d in _INDEX.docs}),
                "dimensions": ["domain", "grade", "chapter"],
            })
            return

        if route in ("/kb/search", "/search"):
            question = one("q") or one("question")
            if not question:
                self._send({"ok": False, "error": "缺少查询参数 q"}, 400)
                return
            try:
                top_k = int(one("top_k", "10") or 10)
            except ValueError:
                top_k = 10
            top_k = max(1, min(top_k, 50))
            stage = one("stage")
            if stage and stage not in kb_index.STAGE_GRADES:
                self._send({"ok": False, "error": f"stage 取值仅支持 primary / junior_high"}, 400)
                return
            hits = kb_index.search(_INDEX, question, domain=one("domain"),
                                   grade=one("grade"), stage=stage, top_k=top_k)
            self._send({
                "ok": True,
                "question": question,
                "filters": {"domain": one("domain"), "grade": one("grade"), "stage": stage},
                "hits": hits,
                "best": hits[0] if hits else None,
            })
            return

        if route in ("/kb/chapters", "/chapters"):
            domains = (_CHAPTERS.get("domains") or {})
            domain = one("domain")
            grade = one("grade")
            if domain:
                domains = {domain: domains.get(domain, {})} if domain in domains else {}
            if grade:
                domains = {d: {grade: gs[grade]} for d, gs in domains.items() if grade in gs}
            self._send({"ok": True, "domains": domains})
            return

        self._send({"ok": False, "error": f"未知路由：{parsed.path}"}, 404)

    def log_message(self, fmt: str, *args) -> None:  # 精简访问日志
        sys.stderr.write(f"[{datetime.now().strftime('%H:%M:%S')}] {fmt % args}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="知识库只读 HTTP 服务")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18099)
    parser.add_argument("--index", default=None, help="索引路径（默认 knowledge/index/tag_index.json）")
    args = parser.parse_args()

    try:
        _ensure_index(args.index)
    except Exception as e:
        sys.stderr.write(f"启动失败：{e}\n")
        return 2

    httpd = ThreadingHTTPServer((args.host, args.port), KBHandler)
    httpd.index_path = args.index  # type: ignore[attr-defined]
    sys.stderr.write(
        f"[{datetime.now().strftime('%H:%M:%S')}] KB 服务已启动 http://{args.host}:{args.port}"
        f"（{len(_INDEX)} 条知识点，只读）\n"
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        sys.stderr.write("\n已停止\n")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
"""Owner-managed seats and a separate, token-scoped worker HTTP listener."""

import hashlib
import hmac
import json
import os
import re
import secrets
import tempfile
import threading
import time
import uuid
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from workflow import Problem, check_text


class Slots:
    def __init__(self, directory):
        self.path = directory / "slots.json"
        self.lock = threading.RLock()
        self.rows = json.loads(self.path.read_text("utf8")) if self.path.exists() else {}
        self.seen = {}

    def commit(self, rows):
        fd, name = tempfile.mkstemp(dir=self.path.parent, prefix="slots-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf8") as out:
                json.dump(rows, out, ensure_ascii=False)
                out.flush()
                os.fsync(out.fileno())
            os.replace(name, self.path)
            self.rows = rows
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def list(self):
        with self.lock:
            return [dict(id=id_, name=row["name"], online=time.monotonic()-self.seen.get(id_, -1e9)<35)
                    for id_, row in self.rows.items()]

    def create(self, name):
        name = check_text(name, "成员名称", 24)
        if not name.isprintable():
            raise Problem(400, "成员名称含有控制字符。")
        with self.lock:
            if len(self.rows) >= 12:
                raise Problem(409, "最多可同时连接 12 个协作插槽。")
            if any(row["name"].casefold() == name.casefold() for row in self.rows.values()):
                raise Problem(409, "已有同名插槽。")
            id_ = "slot-" + uuid.uuid4().hex[:12]
            token = secrets.token_urlsafe(32)
            digest = hashlib.sha256(token.encode("ascii")).hexdigest()
            self.commit({**self.rows, id_: {"name": name, "digest": digest}})
            return {"id": id_, "name": name, "token": token}

    def remove(self, id_):
        with self.lock:
            if id_ not in self.rows:
                raise Problem(404, "插槽不存在。")
            self.commit({k:v for k,v in self.rows.items() if k != id_})
            self.seen.pop(id_, None)

    def authenticate(self, authorization):
        if not re.fullmatch(r"Bearer [\w-]{43}", authorization, re.ASCII):
            raise Problem(401, "无效的插槽凭据。")
        digest = hashlib.sha256(authorization[7:].encode("ascii")).hexdigest()
        with self.lock:
            for id_, row in self.rows.items():
                if hmac.compare_digest(row["digest"], digest):
                    self.seen[id_] = time.monotonic()
                    return id_
        raise Problem(401, "无效的插槽凭据。")


class WorkerHandler(BaseHTTPRequestHandler):
    timeout = 12

    def log_message(self, *args):
        pass

    def reply(self, status, value):
        body = json.dumps(value, ensure_ascii=False).encode("utf8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        try:
            if self.path not in ("/api/worker/claim", "/api/worker/result", "/api/worker/heartbeat"):
                raise Problem(404, "Unknown route")
            if not self.server.allow(self.client_address[0]):
                raise Problem(429, "请求频率过高。")
            if self.headers.get("Origin") is not None:
                raise Problem(403, "请从本地连接器访问。")
            auth = self.headers.get_all("Authorization") or []
            if len(auth) != 1:
                raise Problem(401, "需要插槽凭据。")
            agent = self.server.slots.authenticate(auth[0])
            lengths = self.headers.get_all("Content-Length") or []
            if (self.headers.get_content_type() != "application/json" or "Transfer-Encoding" in self.headers
                    or len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,6}", lengths[0]) or int(lengths[0]) > 100000):
                raise Problem(400, "无效的 JSON 请求。")
            data = json.loads(self.rfile.read(int(lengths[0])).decode("utf8"))
            if type(data) is not dict:
                raise Problem(400, "无效的请求。")
            if self.path.endswith("/heartbeat"):
                if data:
                    raise Problem(400, "心跳参数无效。")
                value = {"ok": True}
            elif self.path.endswith("/claim"):
                if data:
                    raise Problem(400, "领取参数无效。")
                value = {"job": self.server.workflow.claim_slot(agent)}
            else:
                value = self.server.workflow.receive_slot(agent, data)
            self.reply(200, value)
        except Problem as exc:
            self.reply(exc.code, {"error": str(exc)})
        except (ValueError, RecursionError):
            self.reply(400, {"error": "无效的数据。"})
        except OSError:
            self.reply(503, {"error": "连接器暂时不可用。"})


class WorkerServer(ThreadingHTTPServer):
    def __init__(self, address, office):
        super().__init__(address, WorkerHandler)
        self.slots, self.workflow = office.slots, office.workflow
        self.rate_lock, self.requests = threading.Lock(), {}

    def allow(self, address):
        with self.rate_lock:
            now = time.monotonic()
            if len(self.requests) > 512:
                self.requests = {k:v for k,v in self.requests.items() if v and v[-1] > now-60}
            recent = self.requests.setdefault(address, deque())
            while recent and recent[0] <= now-60:
                recent.popleft()
            if len(recent) >= 240:
                return False
            recent.append(now)
            return True

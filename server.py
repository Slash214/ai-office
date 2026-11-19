"""Serve the office scene, public status board and private local task console."""

import hashlib
import hmac
import io
import ipaddress
import json
import math
import mimetypes
import os
import re
import secrets
import shutil
import sys
import tempfile
import threading
import time
import zipfile
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import adapters
from dot_bridge import DotBridge
from project_coder import PUBLISH_LOCK
from release_preview import Previews
import releases
from slots import Slots, WorkerServer
from workflow import NAMES, Problem, Workflow


ROOT = Path(__file__).resolve().parent
PUBLIC = (ROOT / "public").resolve()
AGENTS = tuple(NAMES)
STATUSES = {"idle", "coding", "terminal", "browsing", "thinking", "needs_input", "error", "done"}
ACTIVITIES = {"general", "code", "research", "review", "writing", "planning", "media"}
STALE_SECONDS = 30 * 60
MAX_BODY = 4096
WAITING_STATUSES = {"assigned", "queued"}


def iso_time(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def as_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def workflow_timestamp(event):
    return datetime.fromisoformat(event["updatedAt"].replace("Z", "+00:00")).timestamp()


def underway(status):
    return status not in ("idle", "done")


class PublicAssetVersion:
    """Let an open wallpaper pick up a delivered frontend change."""
    def __init__(self):
        self.lock = threading.Lock()
        self.next_check = 0
        self.version = ""

    def read(self):
        with self.lock:
            now = time.monotonic()
            if now >= self.next_check:
                self.next_check = now + 3
                digest = hashlib.sha256()
                with PUBLISH_LOCK:
                    for path in sorted(PUBLIC.rglob("*")):
                        if path.suffix.lower() not in {".html", ".css", ".js", ".mjs", ".svg", ".png", ".webp", ".jpg"}:
                            continue
                        try:
                            stat = path.stat()
                        except FileNotFoundError:
                            continue
                        digest.update(f"{path.relative_to(PUBLIC).as_posix()}\0{stat.st_mtime_ns}:{stat.st_size}\n".encode())
                self.version = digest.hexdigest()[:16]
            return self.version


def validate_report(data):
    if type(data) is not dict or data.keys() - {"id", "status", "activity", "collaborator"}:
        raise ValueError("Expected id, status, optional activity and collaborator")
    aliases = {"gpt": "astra", "gemini": "carbon"}
    agent = data.get("id")
    if isinstance(agent, str):
        agent = aliases.get(agent, agent)
    status = data.get("status")
    activity = data.get("activity", "general")
    peer = data.get("collaborator")
    if isinstance(peer, str):
        peer = aliases.get(peer, peer)
    if agent not in AGENTS or type(status) is not str or status not in STATUSES:
        raise ValueError("Unknown agent or status")
    if type(activity) is not str or activity not in ACTIVITIES:
        raise ValueError("Unknown activity")
    if peer is not None and (peer not in AGENTS or peer == agent):
        raise ValueError("Unknown collaborator")
    return {"id": agent, "status": status, "activity": activity, "collaborator": peer}


def read_token(directory):
    token = os.environ.get("OFFICE_REPORT_TOKEN")
    if token is None:
        path = directory / "report-token"
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            token = path.read_text(encoding="ascii").strip()
        else:
            token = secrets.token_urlsafe(32)
            with os.fdopen(descriptor, "w", encoding="ascii") as output:
                output.write(token + "\n")
    if not token or not token.isascii() or not token.isprintable() or any(c.isspace() for c in token):
        raise ValueError("The reporting token must contain printable ASCII characters without spaces")
    return token.encode("ascii")


class Office:
    def __init__(self, directory):
        if directory == PUBLIC or PUBLIC in directory.parents:
            raise ValueError("OFFICE_DATA_DIR must be outside the public web directory")
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.token = read_token(directory)
        self.path = directory / "state.json"
        self.lock = threading.Lock()
        self.recent = deque()
        self.last_report = {}
        self.rows = {}
        self.slots = Slots(directory)
        self.workflow = Workflow(directory, self.slots, ROOT)
        self.previews = Previews(ROOT, directory)
        self.dot = DotBridge(directory, self.workflow)
        self.worker_port = None
        self.assets = PublicAssetVersion()
        if self.path.exists():
            saved = json.loads(self.path.read_bytes())
            if type(saved) is not list:
                raise ValueError("Invalid state file")
            for item in saved:
                report = validate_report({k: v for k, v in item.items() if k != "timestamp"})
                stamp = item["timestamp"]
                if type(stamp) not in (int, float) or not math.isfinite(stamp):
                    raise ValueError("Invalid timestamp in state file")
                iso_time(stamp)
                self.rows[report["id"]] = dict(report, timestamp=stamp)

    def store_report(self, report):
        with self.lock:
            now = time.monotonic()
            while self.recent and self.recent[0] <= now - 60:
                self.recent.popleft()
            if len(self.recent) >= 120:
                return max(1, math.ceil(self.recent[0] + 60 - now))
            agent = report["id"]
            delay = self.last_report.get(agent, -math.inf) + 2 - now
            if delay > 0:
                return math.ceil(delay)

            updated = dict(self.rows)
            updated[agent] = dict(report, timestamp=time.time())
            fd, name = tempfile.mkstemp(dir=self.path.parent, prefix="state-", suffix=".tmp")
            try:
                with os.fdopen(fd, "wb") as output:
                    output.write(as_json(list(updated.values())))
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(name, self.path)
            finally:
                Path(name).unlink(missing_ok=True)
            self.rows = updated
            self.last_report[agent] = now
            self.recent.append(now)
        return 0

    def desktop_summary(self):
        summary = self.workflow.desktop_summary()
        if summary["running"]:
            return summary
        # Standalone CLI reports have no work-order ID; keep the order counts exact.
        with self.lock:
            fresh = [row for row in self.rows.values()
                     if time.time()-row["timestamp"] < STALE_SECONDS and
                     row["status"] in ("coding", "thinking", "browsing", "terminal")]
        if fresh:
            row = max(fresh,key=lambda r:r["timestamp"])
            official = self.workflow.board_updates().get(row["id"])
            if official and workflow_timestamp(official) >= row["timestamp"]:
                return summary
            verb = {"coding":"编写代码","thinking":"思考中","browsing":"查阅资料","terminal":"操作终端"}[row["status"]]
            summary.update(headline=row["id"].capitalize()+" · "+verb,
                           coding=row["id"]=="codex" and row["status"]=="coding")
        return summary

    def snapshot(self):
        now = time.time()
        updates = self.workflow.board_updates()
        agents = []
        with self.lock:
            for agent in AGENTS:
                item = self.rows.get(agent)
                event = updates.get(agent)
                active_workflow = False
                if event:
                    stamp = workflow_timestamp(event)
                    active_report = item and underway(item["status"]) and now - item["timestamp"] < STALE_SECONDS
                    active_event = underway(event["status"])
                    if active_event and not (event["status"] in WAITING_STATUSES and active_report):
                        item = dict(event, timestamp=stamp)
                        active_workflow = True
                    elif not active_event and (not item or stamp > item["timestamp"]):
                        item = dict(event, timestamp=stamp)
                row = dict(id=agent, status="idle", activity="general", collaborator=None, updatedAt=None)
                if item:
                    if active_workflow or now - item["timestamp"] < STALE_SECONDS:
                        row.update({k: item[k] for k in ("status", "activity", "collaborator")})
                    row["updatedAt"] = iso_time(item["timestamp"])
                agents.append(row)
        guest_seats = []
        for slot in self.slots.list():
            event = updates.get(slot["id"])
            visible = event and (underway(event["status"]) or now - workflow_timestamp(event) < STALE_SECONDS)
            guest_seats.append({"id":slot["id"], "online":slot["online"], "status":event["status"] if visible else "idle"})
        return {"agents": agents, "guestSeats":guest_seats, "serverTime": iso_time(now),
                "assetVersion": self.assets.read()}


class Handler(BaseHTTPRequestHandler):
    server_version = "Office"
    sys_version = ""
    timeout = 10

    def log_message(self, *args):
        # Public URLs and authorization headers never enter the HTTP log.
        pass

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def reply(self, status, value, headers=None):
        body = as_json(value)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for key, val in (headers or {}).items():
            self.send_header(key, val)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_HEAD(self):
        self.do_GET()

    def require_owner(self, write=False):
        port = self.server.server_port
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}
        if port == 80:
            hosts.update(("127.0.0.1", "localhost", "[::1]"))
        host = self.headers.get("Host", "")
        origin = self.headers.get_all("Origin") or []
        forwarded = any(k.lower() == "forwarded" or k.lower().startswith("x-forwarded-") for k in self.headers)
        local = ipaddress.ip_address(self.client_address[0]).is_loopback
        same_host = len(self.headers.get_all("Host") or []) == 1 and host in hosts
        expected = ["http://" + host]
        same_origin = origin == expected or (not origin and not write)
        fetch_site = self.headers.get("Sec-Fetch-Site")
        if not local or not same_host or not same_origin or forwarded or fetch_site not in (None, "none", "same-origin"):
            raise Problem(403, "任务控制台仅允许从本机办公室页面访问。")

    def read_json(self, limit):
        if self.headers.get_content_type() != "application/json":
            raise Problem(415, "请使用 application/json。")
        sizes = self.headers.get_all("Content-Length") or []
        if "Transfer-Encoding" in self.headers or len(sizes) != 1 or not sizes[0].isascii() or not sizes[0].isdigit():
            raise Problem(411, "请提供有效的 Content-Length。")
        if len(sizes[0]) > 7 or int(sizes[0]) > limit:
            raise Problem(413, "请求内容过长。")
        try:
            return json.loads(self.rfile.read(int(sizes[0])).decode("utf-8"))
        except (ValueError, RecursionError):
            raise Problem(400, "JSON 内容无效。")

    def do_GET(self):
        path = self.path.partition("?")[0]
        if path == "/api/dot/connection":
            try:
                self.require_owner()
                return self.reply(200, self.server.office.dot.connection())
            except Problem as exc:
                return self.reply(exc.code, {"error": str(exc)})
        if path == "/api/slots":
            try:
                self.require_owner()
                return self.reply(200, {"slots": self.server.office.slots.list(), "workerPort": self.server.office.worker_port})
            except Problem as exc:
                return self.reply(exc.code, {"error": str(exc)})
        downloads = {"/join/office_connector.py": ROOT / "office_connector.py",
                     "/join/cli.json": ROOT / "connectors" / "cli.json",
                     "/join/api.json": ROOT / "connectors" / "api.json"}
        if path == "/join/office-connector.zip":
            files = [ROOT / "office_connector.py", *(ROOT / "connectors" / name for name in
                     ("api.json", "cli.json", "接入指南.md", "start.cmd"))]
            try:
                buffer = io.BytesIO()
                with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                    for source in files:
                        archive.write(source, source.name)
            except OSError:
                return self.reply(503, {"error": "连接包缺少文件，请检查工作室目录。"})
            blob = buffer.getvalue()
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", 'attachment; filename="office-connector.zip"')
            self.send_header("Content-Length", str(len(blob)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(blob)
            return
        if path in downloads and downloads[path].is_file():
            blob = downloads[path].read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", 'attachment; filename="' + downloads[path].name + '"')
            self.send_header("Content-Length", str(len(blob)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(blob)
            return
        if path == "/api/status":
            return self.reply(200, self.server.office.snapshot())
        if path == "/api/desktop":
            try:
                self.require_owner()
                return self.reply(200, self.server.office.desktop_summary())
            except Problem as exc:
                return self.reply(exc.code, {"error": str(exc)})
        if path == "/api/workstation":
            try:
                self.require_owner()
                return self.reply(200, {"codex": self.server.office.workflow.workstation()})
            except Problem as exc:
                return self.reply(exc.code, {"error": str(exc)})
        if path == "/api/notifications":
            try:
                self.require_owner()
                return self.reply(200, {"notifications": self.server.office.workflow.notifications()})
            except Problem as exc:
                return self.reply(exc.code, {"error": str(exc)})
        preview_match = re.fullmatch(r"/api/tasks/([a-f0-9-]{36})/preview", path)
        if preview_match:
            try:
                self.require_owner()
                office = self.server.office
                ids = parse_qs(urlsplit(self.path).query).get("releaseId", [])
                if len(ids) != 1 or not releases.RELEASE_ID.fullmatch(ids[0]):
                    raise Problem(400, "请指定要预览的候选版。")
                release = office.workflow.preview(preview_match[1], ids[0])
                diff = office.workflow.release_operation(releases.diff, release["id"])
                scene = any(change["path"].startswith("public/") for change in release["changes"])
                url = office.previews.open(release["id"], self.server.server_port, self.headers["Host"]) if scene else None
                return self.reply(200, {"url": url, "diff": diff, "release": release})
            except Problem as exc:
                return self.reply(exc.code, {"error": str(exc)})
            except (OSError, RuntimeError):
                return self.reply(503, {"error": "候选版暂时无法打开。请刷新后重试。"})
        if path in ("/api/tasks", "/api/capabilities"):
            try:
                self.require_owner()
                if path == "/api/tasks":
                    tag, tasks = self.server.office.workflow.list_if_changed(self.headers.get("If-None-Match"))
                    if tasks is None:
                        self.send_response(304)
                        self.send_header("ETag", tag)
                        self.end_headers()
                        return
                    return self.reply(200, {"tasks": tasks}, {"ETag": tag})
                return self.reply(200, {"agents": adapters.capabilities()})
            except Problem as exc:
                return self.reply(exc.code, {"error": str(exc)})
        if path == "/api/report":
            return self.reply(405, {"error": "Use POST"}, {"Allow": "POST"})
        if path.startswith("/api/"):
            return self.reply(404, {"error": "Unknown route"})
        try:
            name = unquote(urlsplit(path).path, errors="strict").lstrip("/") or "index.html"
            if name == "index.html" and parse_qs(urlsplit(self.path).query).get("wallpaper") == ["1"]:
                name = "wallpaper.html"
            if "\\" in name or ":" in name or any(part.startswith(".") for part in name.split("/")):
                raise ValueError
            with PUBLISH_LOCK:
                target = (PUBLIC / name).resolve()
                if PUBLIC not in target.parents or not target.is_file():
                    raise ValueError
                size = target.stat().st_size
                content = b"" if self.command == "HEAD" else target.read_bytes()
        except (OSError, ValueError, RuntimeError):
            return self.reply(404, {"error": "File not found"})
        suffix = target.suffix.lower()
        preferred = {".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".webp": "image/webp"}
        mime = preferred.get(suffix) or mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(size if self.command == "HEAD" else len(content)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(content)

    def do_POST(self):
        path = self.path.partition("?")[0]
        if path in ("/api/dot/inbox", "/api/dot/reply"):
            try:
                self.require_owner(write=True)
                dot = self.server.office.dot
                dot.authorize(self.headers.get("Authorization", ""))
                data = self.read_json(100 * 1024)
                if path == "/api/dot/inbox":
                    if data != {}:
                        raise Problem(400, "收件箱仅接受空对象。")
                    return self.reply(200, dot.inbox())
                return self.reply(200, dot.reply(data))
            except Problem as exc:
                return self.reply(exc.code, {"error": str(exc)})
            except OSError:
                return self.reply(503, {"error": "Dot 收件箱暂时无法保存进度。"})
        if path in ("/api/slots", "/api/slots/revoke"):
            try:
                self.require_owner(write=True)
                data = self.read_json(1024)
                if type(data) is not dict:
                    raise Problem(400, "无效的插槽参数。")
                if path == "/api/slots" and set(data) == {"name"}:
                    return self.reply(201, self.server.office.slots.create(data["name"]))
                if path.endswith("/revoke") and set(data) == {"id"} and isinstance(data["id"], str):
                    self.server.office.slots.remove(data["id"])
                    return self.reply(200, {"ok": True})
                raise Problem(400, "无效的插槽参数。")
            except Problem as exc:
                return self.reply(exc.code, {"error": str(exc)})
            except OSError:
                return self.reply(503, {"error": "无法保存插槽。"})
        task_action = re.fullmatch(r"/api/tasks/([a-f0-9-]{36})/(step|accept|reject|rollback|stop|desktop-txt)", path)
        if path == "/api/tasks" or task_action:
            try:
                self.require_owner(write=True)
                data = self.read_json(128 * 1024)
                workflow = self.server.office.workflow
                if task_action:
                    task_id, action = task_action.groups()
                    if action == "desktop-txt":
                        if data != {}:
                            raise Problem(400,"桌面交付无需路径参数。")
                        return self.reply(200, {"task":workflow.export_text(task_id)})
                    if action == "step":
                        return self.reply(200, {"task": workflow.act(task_id, data)})
                    keys = {"accept": {"releaseId"}, "reject": {"releaseId", "feedback"},
                            "rollback": {"releaseId"}, "stop": {"stepId"}}
                    if type(data) is not dict or data.keys() - keys[action]:
                        raise Problem(400, "工单操作参数无效。")
                    release_id = data.get("releaseId")
                    if "releaseId" in data and (not isinstance(release_id, str) or not releases.RELEASE_ID.fullmatch(release_id)):
                        raise Problem(400, "候选版本标识无效。")
                    if action == "accept":
                        task = workflow.accept(task_id, release_id)
                    elif action == "reject":
                        task = workflow.reject(task_id, data.get("feedback"), release_id)
                    elif action == "rollback":
                        task = workflow.rollback(task_id, release_id)
                    else:
                        task = workflow.stop(task_id, data.get("stepId"))
                    return self.reply(200, {"task": task})
                return self.reply(201, {"task": workflow.create(data)})
            except Problem as exc:
                return self.reply(exc.code, {"error": str(exc)})
            except (OSError, RuntimeError):
                return self.reply(503, {"error": "无法保存任务，请检查数据目录。"})
        if path != "/api/report":
            return self.reply(404, {"error": "Unknown route"})
        office = self.server.office
        auth = self.headers.get("Authorization", "").encode("latin-1")
        if not hmac.compare_digest(auth, b"Bearer " + office.token):
            return self.reply(401, {"error": "Invalid reporting token"}, {"WWW-Authenticate": "Bearer"})
        try:
            report = validate_report(self.read_json(MAX_BODY))
        except Problem as exc:
            return self.reply(exc.code, {"error": str(exc)})
        except (ValueError, RecursionError):
            return self.reply(400, {"error": "Invalid report fields or JSON"})
        try:
            delay = office.store_report(report)
        except OSError:
            return self.reply(503, {"error": "Unable to persist report"})
        if delay:
            return self.reply(429, {"error": "Reporting too quickly"}, {"Retry-After": str(delay)})
        return self.reply(200, {"ok": True})


def main():
    directory = Path(os.environ.get("OFFICE_DATA_DIR", str(ROOT / ".office-data"))).expanduser().resolve()
    host = os.environ.get("OFFICE_HOST", "127.0.0.1")
    port = int(os.environ.get("OFFICE_PORT", 8765))
    with ThreadingHTTPServer((host, port), Handler) as server:
        server.office = Office(directory)
        worker_port = int(os.environ.get("OFFICE_WORKER_PORT", port + 1 if port < 65535 else 65534))
        worker = None
        try:
            worker = WorkerServer(("127.0.0.1", worker_port), server.office)
            server.office.worker_port = worker.server_port
            threading.Thread(target=worker.serve_forever, daemon=True).start()
        except OSError:
            print("Worker listener unavailable. Check OFFICE_WORKER_PORT.", file=sys.stderr, flush=True)
        print(f"AI Office listening on http://{host}:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.office.previews.close()
            if worker:
                worker.shutdown()
                worker.server_close()


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as exc:
        sys.exit(f"Cannot start office: {exc}")

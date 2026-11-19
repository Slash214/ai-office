"""Serve a candidate's public files on an isolated, temporary loopback origin."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import threading
import time
from urllib.parse import unquote, urlsplit

import releases


ASSET_TYPES = {".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css",
               ".webp": "image/webp", ".svg": "image/svg+xml"}
MAX_PREVIEWS = 4
PREVIEW_IDLE_SECONDS = 900


class PreviewHandler(BaseHTTPRequestHandler):
    timeout = 8

    def log_message(self, *_):
        pass

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        preview = self.server
        hosts = ([f"127.0.0.1:{preview.server_port}"], [f"localhost:{preview.server_port}"])
        if self.headers.get_all("Host") not in hosts:
            return self.send_error(403)
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            return self.send_error(403)
        preview.used = time.monotonic()
        path = unquote(urlsplit(self.path).path).lstrip("/") or "index.html"
        if path.startswith("api/"):
            data = {
                "api/status": {"agents": [], "guestSeats": [], "assetVersion": preview.release_id},
                "api/tasks": {"tasks": []},
                "api/workstation": {"codex": None},
                "api/desktop": {"headline":"候选版预览","running":0,"queued":0,"reviews":0,"recent":[]},
                "api/capabilities": {"agents": {}},
                "api/slots": {"slots": [], "workerPort": None},
            }.get(path)
            if data is None:
                return self.send_error(404)
            return self.asset(json.dumps(data).encode(), "application/json")
        try:
            content = releases.preview(preview.root, preview.release_id, path, data_dir=preview.data_dir)
        except FileNotFoundError:
            return self.send_error(404)
        except (OSError, RuntimeError):
            return self.send_error(503)
        mime = ASSET_TYPES.get(Path(path).suffix.lower()) or mimetypes.guess_type(path)[0]
        self.asset(content, mime or "application/octet-stream")

    def asset(self, content, mime):
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "private, no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                         "img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; worker-src 'self'; "
                         f"frame-ancestors {self.server.parent_origins}; "
                         "frame-src 'none'; form-action 'none'; base-uri 'none'; object-src 'none'")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(content)


class Previews:
    def __init__(self, root, data_dir):
        self.root = root
        self.data_dir = data_dir
        self.lock = threading.Lock()
        self.live = {}
        self.timer = None

    def expired(self):
        now = time.monotonic()
        for release_id, server in list(self.live.items()):
            if now - server.used >= PREVIEW_IDLE_SECONDS:
                self.close_one(release_id)

    def close_one(self, release_id):
        server = self.live.pop(release_id)
        server.shutdown()
        server.server_close()

    def sweep(self):
        with self.lock:
            self.timer = None
            self.expired()
            self.schedule_sweep()

    def schedule_sweep(self):
        if self.live and not self.timer:
            self.timer = threading.Timer(60, self.sweep)
            self.timer.daemon = True
            self.timer.start()

    def open(self, release_id, owner_port, owner_host):
        with self.lock:
            self.expired()
            server = self.live.get(release_id)
            if server is None:
                if len(self.live) >= MAX_PREVIEWS:
                    self.close_one(min(self.live, key=lambda key: self.live[key].used))
                server = ThreadingHTTPServer(("127.0.0.1", 0), PreviewHandler)
                server.used = time.monotonic()
                server.root = self.root
                server.data_dir = self.data_dir
                server.release_id = release_id
                server.parent_origins = f"http://127.0.0.1:{owner_port} http://localhost:{owner_port}"
                self.live[release_id] = server
                threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True).start()
            self.schedule_sweep()
            hostname = "localhost" if owner_host.startswith("localhost:") else "127.0.0.1"
            return f"http://{hostname}:{server.server_port}/"

    def close(self):
        with self.lock:
            if self.timer:
                self.timer.cancel()
                self.timer = None
            for release_id in list(self.live):
                self.close_one(release_id)

"""Exercise review, cancellation and attention through the local HTTP entry points."""

import http.client
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

import project_coder
import server


class TaskControls(unittest.TestCase):
    def setUp(self):
        directory = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.root = directory / "source"
        self.public = self.root / "public"
        self.public.mkdir(parents=True)
        self.index = self.public / "index.html"
        self.index.write_text("<h1>Original</h1>", encoding="utf-8")
        self.enterContext(patch.object(server, "ROOT", self.root))
        self.enterContext(patch.object(server, "PUBLIC", self.public))
        self.web = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.web.office = server.Office(directory / "data")
        self.addCleanup(self.web.office.previews.close)
        self.addCleanup(self.web.server_close)
        self.addCleanup(self.web.shutdown)
        threading.Thread(target=self.web.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
        self.origin = f"http://127.0.0.1:{self.web.server_port}"
        self.available = dict.fromkeys(server.AGENTS, True)
        self.available["dot"] = False
        self.enterContext(patch.object(server.adapters, "capabilities", side_effect=lambda: {
            agent: {"ready": ready, "detail": "fixture"} for agent, ready in self.available.items()
        }))

    def request(self, method, path, payload=None, *, port=None, extra=None):
        conn = http.client.HTTPConnection("127.0.0.1", port or self.web.server_port, timeout=4)
        headers = {"Origin": self.origin, "Content-Type": "application/json"} if payload is not None else {}
        headers.update(extra or {})
        try:
            conn.request(method, path, json.dumps(payload).encode() if payload is not None else None, headers)
            res = conn.getresponse()
            body = res.read()
            return res.status, json.loads(body) if res.getheader("Content-Type", "").startswith("application/json") else body
        finally:
            conn.close()

    def create(self, brief, worker):
        status, out = self.request("POST", "/api/tasks", {"brief": brief, "workers": [worker]})
        self.assertEqual(status, 201, out)
        return "/api/tasks/" + out["task"]["id"]

    def wait(self, path, condition):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            _, data = self.request("GET", "/api/tasks")
            task = next(t for t in data["tasks"] if path.endswith(t["id"]))
            if condition(task):
                return task
            time.sleep(0.02)
        self.fail(str(task))

    def test_candidate_preview_reject_publish_rollback(self):
        def code(_cli, _root, work, _env, _node, prompt):
            path = work / "public" / "index.html"
            if "make it purple" in prompt:
                self.assertIn("Candidate", path.read_text())
                path.write_text("<h1>Purple</h1>", encoding="utf-8")
            else:
                path.write_text("<h1>Candidate</h1>", encoding="utf-8")
            return "Implemented"

        def invoke(agent, prompt):
            if agent == "codex":
                return project_coder.run(["fixture"], self.root, prompt)
            return "Reviewed"

        with (
            patch.object(server.adapters, "run_agent", side_effect=invoke),
            patch.object(project_coder, "code", side_effect=code),
            patch.object(project_coder, "verify", return_value="Tests passed"),
            patch.object(project_coder.shutil, "which", return_value="node"),
        ):
            path = self.create("PRIVATE-FIXTURE-BRIEF", "codex")
            first = self.wait(path, lambda item: item.get("release"))
            old = {"releaseId": first["release"]["id"]}
            self.assertEqual(self.index.read_text(), "<h1>Original</h1>")
            self.assertEqual(self.request("POST", path + "/accept", {})[0], 409)
            preview_path = path + "/preview?releaseId=" + old["releaseId"]
            self.assertEqual(self.request("GET", preview_path, extra={"Sec-Fetch-Site": "cross-site"})[0], 403)
            status, pane = self.request("GET", preview_path)
            self.assertEqual(status, 200, pane)
            self.assertIn("+<h1>Candidate</h1>", pane["diff"])
            port = urlsplit(pane["url"]).port
            self.assertNotEqual(port, self.web.server_port)
            self.assertEqual(self.request("GET", "/", port=port), (200, b"<h1>Candidate</h1>"))
            self.assertEqual(self.request("GET", "/api/tasks", port=port), (200, {"tasks": []}))
            self.assertEqual(self.request("POST", path + "/accept", old, port=port)[0], 501)
            _, feed = self.request("GET", "/api/notifications")
            self.assertEqual([n["kind"] for n in feed["notifications"]], ["review"])
            self.assertNotIn("PRIVATE-FIXTURE-BRIEF", str(feed))
            self.assertEqual(self.request("GET", "/api/notifications")[1], feed)
            self.assertEqual(self.request("POST", path + "/reject", dict(old, feedback="make it purple"))[0], 200)
            second = self.wait(path, lambda item: item.get("release") and item["release"]["id"] != old["releaseId"])
            self.assertEqual(second["steps"][-1]["feedback"], "make it purple")
            self.assertEqual(self.request("POST", path + "/accept", old)[0], 409)
            self.assertEqual(self.request("GET", preview_path)[0], 409)
            newest = {"releaseId": second["release"]["id"]}
            self.assertEqual(self.request("POST", path + "/accept", newest)[0], 200)
            self.assertEqual(self.request("GET", "/")[1], b"<h1>Purple</h1>")
            self.assertEqual(self.request("GET", "/api/notifications")[1], {"notifications": []})
            self.assertEqual(self.request("POST", path + "/rollback", newest)[0], 200)
            status, after = self.request("POST", path + "/rollback", newest)
            self.assertEqual(status, 200)
            self.assertTrue(after["task"]["rolledBackAt"])
            self.assertEqual(self.index.read_text(), "<h1>Original</h1>")

    def test_stop_running_and_queued_work_rejects_late_response(self):
        started, finish = threading.Event(), threading.Event()
        self.addCleanup(finish.set)
        calls = []

        def invoke(agent, prompt):
            calls.append((agent, prompt))
            if agent == "carbon" and "FIRST-FIXTURE" in prompt:
                started.set()
                self.assertTrue(finish.wait(3))
            return "Fixture returned late"

        with patch.object(server.adapters, "run_agent", side_effect=invoke):
            first = self.create("FIRST-FIXTURE", "argon")
            self.assertTrue(started.wait(3))
            queued = self.create("QUEUED-FIXTURE", "argon")
            self.assertEqual(self.request("POST", queued + "/stop", {})[1]["task"]["status"], "stopped")
            self.assertEqual(self.request("POST", first + "/stop", {})[1]["task"]["steps"][0]["status"], "cancelled")
            finish.set()
            after = self.create("AFTER-FIXTURE", "argon")
            self.wait(after, lambda item: item["status"] == "complete")
        self.assertEqual([a for a, prompt in calls if "FIRST-FIXTURE" in prompt], ["carbon"])
        self.assertFalse(any("QUEUED-FIXTURE" in prompt for _, prompt in calls))
        self.assertEqual(self.request("POST", first + "/accept", {})[0], 409)
        self.assertEqual(self.request("POST", first + "/stop", {})[1]["task"]["status"], "stopped")

    def test_stop_invalidates_dot_receipt(self):
        with patch.object(server.adapters, "run_agent", return_value="Reviewed"):
            path = self.create("DOT-FIXTURE", "dot")
            self.wait(path, lambda item: item["status"] == "handoff")
        self.assertEqual(self.request("GET", "/api/notifications")[1]["notifications"][0]["kind"], "input")
        self.available["codex"] = False
        with patch.object(server.adapters, "run_agent", return_value="Reviewed"):
            failing = self.create("CODE-FIXTURE", "codex")
            self.wait(failing, lambda item: item["steps"][-1]["status"] == "error")
        self.assertEqual({n["kind"] for n in self.request("GET", "/api/notifications")[1]["notifications"]},
                         {"failed", "input"})
        dot = {"Authorization": "Bearer " + self.web.office.dot.token}
        _, inbox = self.request("POST", "/api/dot/inbox", {}, extra=dot)
        job = inbox["job"]
        self.assertEqual(self.request("POST", path + "/stop", {})[0], 200)
        self.assertIsNone(self.request("POST", "/api/dot/inbox", {}, extra=dot)[1]["job"])
        self.assertEqual(self.request("POST", "/api/dot/reply",
                                      {"taskId": job["taskId"], "receipt": job["receipt"], "result": "late"}, extra=dot)[0], 409)

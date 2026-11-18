"""Owner and worker HTTP integration on ephemeral ports and private temporary data."""

from concurrent.futures import ThreadPoolExecutor
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import office_connector as connector
import server
from slots import WorkerServer


class SlotFlow(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.office = server.Office(self.folder)
        self.owner = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.owner.office = self.office
        self.worker = WorkerServer(("127.0.0.1", 0), self.office)
        self.office.worker_port = self.worker.server_port
        self.serve(self.owner)
        self.serve(self.worker)
        self.origin = f"http://127.0.0.1:{self.owner.server_port}"
        self.worker_url = f"http://127.0.0.1:{self.worker.server_port}"
        self.enterContext(patch.object(server.adapters, "capabilities", return_value={
            a:{"ready":True,"detail":"fixture"} for a in server.AGENTS}))
        self.enterContext(patch.object(server.adapters, "run_agent",
                                      side_effect=lambda agent,prompt: agent + " fixture output"))

    def serve(self, http):
        threading.Thread(target=http.serve_forever, kwargs={"poll_interval":.01}, daemon=True).start()
        self.addCleanup(http.server_close)
        self.addCleanup(http.shutdown)

    def req(self, api, method, path, data=None, token=None, origin=False):
        conn = http.client.HTTPConnection("127.0.0.1", api.server_port, timeout=3)
        headers = {"Content-Type":"application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        if origin:
            headers["Origin"] = self.origin
        try:
            conn.request(method, path, body=json.dumps(data).encode("utf8") if data is not None else None, headers=headers)
            response = conn.getresponse()
            return response.status, json.loads(response.read())
        finally:
            conn.close()

    def admin(self, path, data):
        return self.req(self.owner, "POST", path, data, origin=True)

    def peer(self, route, token, data=None):
        return self.req(self.worker, "POST", "/api/worker/" + route, {} if data is None else data, token)

    def seat(self, name):
        code, slot = self.admin("/api/slots", {"name":name})
        self.assertEqual(code, 201)
        return slot

    def task(self, slots):
        code, result = self.admin("/api/tasks", {"brief":"private fixture assignment", "workers":[s["id"] for s in slots]})
        self.assertEqual(code, 201, result)
        task_id = result["task"]["id"]
        for _ in range(100):
            task = self.get_task(task_id)
            if all(s["status"] == "handoff" for s in task["steps"] if s["kind"] == "execution"):
                return task
            time.sleep(.02)
        self.fail("worker steps never reached handoff")

    def get_task(self, task_id):
        code, result = self.req(self.owner, "GET", "/api/tasks")
        self.assertEqual(code, 200)
        return next(t for t in result["tasks"] if t["id"] == task_id)

    def run_connector(self, slot, config):
        path = self.folder / "worker-config.json"
        path.write_text(json.dumps(config), encoding="utf8")
        done = subprocess.run(
            [sys.executable, str(Path(connector.__file__).resolve()), "--config", str(path),
             "--url", self.worker_url, "--state-dir", str(self.folder / "client"), "--once"],
            env={**os.environ, "OFFICE_SLOT_TOKEN":slot["token"], "PYTHONIOENCODING":"utf8"},
            capture_output=True, text=True, encoding="utf8", timeout=10,
        )
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_two_protocols_deliver_to_the_same_job_with_separate_credentials(self):
        received = []
        class Model(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                value = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                received.append((self.path, self.headers.get("Authorization"), value["model"], value["messages"][0]["content"]))
                body = json.dumps({"choices":[{"message":{"content":"local API success"}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        model = ThreadingHTTPServer(("127.0.0.1", 0), Model)
        self.serve(model)
        cli, api = self.seat("CLI Alice"), self.seat("API Bob")
        job = self.task([cli, api])
        self.run_connector(cli, {"type":"cli", "argv":[sys.executable, "-c",
                           "import sys;assert 'fixture assignment' in sys.stdin.read(); print('local CLI success')"]})
        self.run_connector(api, {"type":"openai-compatible","base_url":f"http://127.0.0.1:{model.server_port}/v1",
                                 "model":"fixture-without-key"})
        latest = self.get_task(job["id"])
        self.assertEqual(latest["status"], "complete")
        self.assertEqual([s["result"] for s in latest["steps"][-2:]], ["local CLI success", "local API success"])
        self.assertEqual(received[0][:3], ("/v1/chat/completions", None, "fixture-without-key"))
        self.assertIn("private fixture assignment", received[0][3])
        public = self.req(self.owner, "GET", "/api/status")[1]
        for private in ("fixture assignment", "local API success", "CLI Alice", "API Bob", cli["token"], api["token"], "lease"):
            self.assertNotIn(private, json.dumps(public, ensure_ascii=False))
        self.assertNotIn("lease", json.dumps(latest))

    def test_slot_scope_revocation_and_manual_fallback(self):
        chosen, other = self.seat("chosen"), self.seat("other")
        job = self.task([chosen])
        self.assertEqual(self.peer("claim", other["token"]), (200, {"job":None}))
        self.assertEqual(self.peer("heartbeat", None)[0], 401)
        with connector.keep_online(self.worker_url, chosen["token"], interval=.02):
            for _ in range(30):
                slots = self.req(self.owner, "GET", "/api/slots")[1]["slots"]
                if any(s["online"] and s["id"] == chosen["id"] for s in slots):
                    break
                time.sleep(.02)
        status = self.req(self.owner, "GET", "/api/slots")[1]
        self.assertTrue(next(s["online"] for s in status["slots"] if s["id"] == chosen["id"]))
        self.assertNotIn(chosen["token"], json.dumps(status))
        self.assertNotIn(chosen["token"], (self.folder / "slots.json").read_text(encoding="utf8"))
        with ThreadPoolExecutor(max_workers=2) as pool:
            claims = list(pool.map(lambda _: self.peer("claim", chosen["token"])[1]["job"], range(2)))
        self.assertEqual(sum(bool(c) for c in claims), 1)
        lease = next(c["lease"] for c in claims if c)
        self.assertNotIn(lease, json.dumps(self.get_task(job["id"])))
        self.assertEqual(self.peer("result", other["token"], {"lease":lease,"result":"wrong seat"})[0], 409)
        self.assertEqual(self.req(self.worker, "POST", "/api/slots", {"name":"unauthorized"}, chosen["token"])[0], 404)
        self.assertEqual(self.req(self.owner, "POST", "/api/slots", {"name":"unauthorized"}, chosen["token"])[0], 403)
        self.assertEqual(self.admin("/api/slots/revoke", {"id":chosen["id"]})[0], 200)
        self.assertEqual(self.peer("result", chosen["token"], {"lease":lease, "result":"late"})[0], 401)
        self.assertEqual(self.peer("claim", chosen["token"])[0], 401)
        manual = self.admin("/api/tasks/" + job["id"] + "/step", {
            "stepId":"execute-" + chosen["id"], "action":"manual", "result":"owner delivery"})
        self.assertEqual(manual[0], 200)
        self.assertEqual(manual[1]["task"]["status"], "complete")
        self.assertEqual(manual[1]["task"]["steps"][-1]["result"], "owner delivery")

    def test_expired_leases_recover_without_poll_and_late_receipts_do_not_overwrite_retry(self):
        seat = self.seat("peer")
        first_job = self.task([seat])
        original = self.peer("claim", seat["token"])[1]["job"]["lease"]
        with patch("workflow.time.time", return_value=time.time()+602):
            self.assertEqual(self.get_task(first_job["id"])["steps"][-1]["status"], "error")
        # A late response from the original model remains valid until the owner retries.
        payload = {"lease":original, "result":"late but accepted"}
        self.assertEqual(self.peer("result", seat["token"], payload)[0], 200)
        self.assertEqual(self.peer("result", seat["token"], payload)[0], 200)
        second_job = self.task([seat])
        stale = self.peer("claim", seat["token"])[1]["job"]["lease"]
        with patch("workflow.time.time", return_value=time.time()+602):
            self.assertEqual(self.get_task(second_job["id"])["steps"][-1]["status"], "error")
        path = "/api/tasks/" + second_job["id"] + "/step"
        self.assertEqual(self.admin(path, {"stepId":"execute-" + seat["id"], "action":"retry"})[0], 200)
        for _ in range(100):
            claimed = self.peer("claim", seat["token"])[1]["job"]
            if claimed:
                break
            time.sleep(.02)
        self.assertTrue(claimed)
        self.assertNotEqual(stale, claimed["lease"])
        self.assertEqual(self.peer("result", seat["token"], {"lease":stale,"result":"obsolete"})[0], 409)
        self.assertEqual(self.peer("result", seat["token"], {"lease":claimed["lease"],"result":"new result"})[0], 200)
        self.assertEqual(self.peer("result", seat["token"], {"lease":original,"result":"duplicate text"})[0], 200)
        self.assertEqual(self.get_task(first_job["id"])["steps"][-1]["result"], "late but accepted")
        self.assertEqual(self.get_task(second_job["id"])["steps"][-1]["result"], "new result")

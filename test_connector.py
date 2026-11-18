"""Standalone connector integration tests. Only loopback fixtures are contacted."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid

import office_connector as connector


class WorkerTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.lease = str(uuid.uuid4())
        self.token = "test-slot-private-credential"
        self.prompt = '请按原样处理 & $() "hello"'
        self.calls, self.results, self.model_calls = [], [], []
        self.claimed, self.failed_ack, self.redirect, self.large = False, False, False, False
        case = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                auth = self.headers.get("Authorization")
                case.calls.append(self.path)
                code = 200
                if self.path == "/v1/chat/completions":
                    case.model_calls.append((auth, body))
                    if case.redirect:
                        self.send_response(307)
                        self.send_header("Location", case.office + "/redirect-target")
                        self.end_headers()
                        return
                    value = {"choices":[{"message":{"content": "model reply" if not case.large else "x" * 16001}}]}
                elif auth != "Bearer " + case.token:
                    code, value = 401, {}
                elif self.path == "/api/worker/claim":
                    value = {"job": None if case.claimed else {"prompt":case.prompt, "lease":case.lease}}
                    case.claimed = True
                elif self.path == "/api/worker/result":
                    case.results.append(body)
                    if case.failed_ack:
                        self.close_connection = True  # accepted delivery, lost response
                        return
                    value = {"ok":True}
                else:
                    code, value = 404, {}
                raw = json.dumps(value).encode()
                self.send_response(code)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.office = f"http://127.0.0.1:{self.http.server_port}"
        threading.Thread(target=self.http.serve_forever, kwargs={"poll_interval": .01}, daemon=True).start()
        self.addCleanup(self.http.server_close)
        self.addCleanup(self.http.shutdown)

    def run_once(self, config):
        cfg = self.folder / "adapter.json"
        cfg.write_text(json.dumps(config), encoding="utf8")
        return subprocess.run(
            [sys.executable, str(Path(connector.__file__).resolve()), "--once", "--config", str(cfg),
             "--url", self.office, "--state-dir", str(self.folder / "journal")],
            env={**os.environ, "OFFICE_SLOT_TOKEN":self.token, "FIXTURE_MODEL_KEY":"private-model-fixture",
                 "PYTHONIOENCODING":"utf8"},
            capture_output=True, text=True, encoding="utf8", timeout=12,
        )

    def api(self):
        return {"type":"openai-compatible", "base_url": self.office + "/v1",
                "model":"fixture-only", "api_key_env":"FIXTURE_MODEL_KEY"}

    def test_cli_passes_only_stdin_and_replays_same_receipt_even_if_config_changes(self):
        script = self.folder / "fixture.py"
        counter = self.folder / "count"
        script.write_text(
            "import os,sys,pathlib\n"
            "assert 'OFFICE_SLOT_TOKEN' not in os.environ\n"
            "with pathlib.Path(sys.argv[1]).open('a') as f: f.write('x')\n"
            "sys.stdout.buffer.write(sys.stdin.buffer.read())\n", encoding="utf8")
        self.failed_ack = True
        proc = self.run_once({"type":"cli", "argv":[sys.executable, str(script), str(counter)]})
        self.assertEqual(proc.returncode, 1)
        self.failed_ack = False
        proc = self.run_once({"type":"no-longer-installed"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        expected = {"lease":self.lease, "result":self.prompt}
        self.assertEqual(self.results, [expected, expected])
        self.assertEqual(counter.read_text(), "x")
        self.assertEqual(self.calls.count("/api/worker/claim"), 1)
        self.assertNotIn(self.prompt, proc.stdout + proc.stderr)

    def test_api_uses_model_key_and_pinned_model(self):
        proc = self.run_once(self.api())
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.model_calls, [("Bearer private-model-fixture", {
            "model":"fixture-only", "messages":[{"role":"user","content":self.prompt}], "stream":False})])
        self.assertEqual(self.results, [{"lease":self.lease, "result":"model reply"}])

    def test_cli_project_cwd_is_selected_by_its_local_config(self):
        project = self.folder / "local-project"
        project.mkdir()
        (project / "context.txt").write_text("only this project", encoding="utf8")
        (project / "agent.py").write_text(
            "from pathlib import Path\nprint(Path('context.txt').read_text())", encoding="utf8")
        proc = self.run_once({"type":"cli", "argv":[sys.executable, "agent.py"], "cwd":"local-project"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.results, [{"lease":self.lease, "result":"only this project"}])
        self.assertTrue((project / "agent.py").is_file())
        self.assertEqual(self.run_once({"type":"cli", "argv":[sys.executable, "agent.py"], "cwd":"missing"}).returncode, 1)

    def test_model_redirect_is_rejected_and_error_is_generic(self):
        self.redirect = True
        self.assertEqual(self.run_once(self.api()).returncode, 0)
        self.assertNotIn("/redirect-target", self.calls)
        self.assertEqual(self.results, [{"lease":self.lease, "error":connector.MODEL_ERROR}])

    def test_oversize_model_text_and_cli_timeout(self):
        self.large = True
        self.assertEqual(self.run_once(self.api()).returncode, 0)
        self.assertEqual(self.results[-1]["error"], connector.MODEL_ERROR)
        self.claimed, self.lease = False, str(uuid.uuid4())
        self.assertEqual(self.run_once({"type":"cli", "argv":[sys.executable, "-c", "import time;time.sleep(30)"],
                                        "timeout_seconds":1}).returncode, 0)
        self.assertEqual(self.results[-1], {"lease":self.lease, "error":connector.MODEL_ERROR})

    def test_abandoned_run_is_reported_without_a_second_invocation(self):
        with connector.open_journal(self.folder / "journal", self.office, self.token) as db:
            with db:
                db.execute("INSERT INTO receipts VALUES(?,'running',NULL)", (self.lease,))
            with self.assertRaises(connector.ConnectorError):
                with connector.open_journal(self.folder / "journal", self.office, self.token):
                    pass
        self.assertEqual(self.run_once(self.api()).returncode, 0)
        self.assertEqual(self.calls, ["/api/worker/result"])
        self.assertEqual(self.results, [{"lease":self.lease, "error":connector.INTERRUPTED}])

    def test_offhost_credentials_require_tls(self):
        self.assertEqual(connector.base_url("http://[::1]:8766/"), "http://[::1]:8766")
        for url in ("http://192.168.1.2:8766", "http://public.example", "https://secret@office.example",
                    "https://office.example/?token=secret"):
            with self.subTest(url=url), self.assertRaises(connector.ConnectorError):
                connector.base_url(url)


if __name__ == "__main__":
    unittest.main()

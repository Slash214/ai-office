"""Local HTTP regression checks. Run with: python -B -m unittest test_workflow"""

import http.client
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import server
from workflow import Workflow


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.data = Path(temp.name)
        self.enterContext(patch.dict(os.environ, {"OFFICE_REPORT_TOKEN": "fixture-reporting-token"}))
        self.api = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.api.office = server.Office(self.data)
        self.origin = "http://127.0.0.1:" + str(self.api.server_port)
        threading.Thread(target=self.api.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
        self.addCleanup(self.api.server_close)
        self.addCleanup(self.api.shutdown)
        self.enabled = dict.fromkeys(server.AGENTS, True)
        self.enterContext(patch.object(server.adapters, "capabilities", side_effect=lambda: {
            a: {"ready": r, "detail": "fixture capability"} for a, r in self.enabled.items()
        }))
        self.calls = []

        def invoke(agent, prompt):
            self.calls.append((agent, prompt))
            return {"carbon": "plan result", "astra": "review\n[dot]\nwrite examples\n[argon]\nverify sources"}.get(agent, agent + " result")

        self.enterContext(patch.object(server.adapters, "run_agent", side_effect=invoke))

    def request(self, method, path, data=None, extra=None, origin=True):
        headers = {"Content-Type": "application/json"}
        if origin:
            headers["Origin"] = self.origin
        headers.update(extra or {})
        conn = http.client.HTTPConnection("127.0.0.1", self.api.server_port, timeout=3)
        try:
            conn.request(method, path, json.dumps(data).encode() if data is not None else None, headers)
            result = conn.getresponse()
            return result.status, json.loads(result.read())
        finally:
            conn.close()

    def wait(self, task_id, terminal):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            _, rows = self.request("GET", "/api/tasks")
            task = next(t for t in rows["tasks"] if t["id"] == task_id)
            if terminal(task):
                return task
            time.sleep(.01)
        self.fail("Timed out waiting for test model")

    def test_unavailable_executor_handoff_does_not_block_other_workers(self):
        self.enabled["dot"] = False
        code, data = self.request("POST", "/api/tasks", {"brief": "private brief", "workers": ["dot", "argon"]})
        self.assertEqual(code, 201)
        task = data["task"]
        path = f"/api/tasks/{task['id']}/step"
        waiting = self.wait(task["id"], lambda t:t["status"] == "handoff")
        self.assertEqual(waiting["steps"][-1]["status"], "done")
        self.assertIn("write examples", waiting["steps"][2]["prompt"])
        self.assertEqual(self.request("POST", path, {"stepId":"plan","action":"manual","result":"old plan"})[0],409)
        _, data = self.request("POST", path, {"stepId": "execute-dot", "action": "manual", "result": "delivered"})
        self.assertEqual(data["task"]["status"], "complete")
        self.assertEqual([a for a,_ in self.calls], ["carbon","astra","argon"])
        self.assertEqual(Workflow(self.data).all()[0]["steps"][2]["result"], "delivered")
        public = self.request("GET", "/api/status")[1]
        self.assertEqual({a["id"] for a in public["agents"]}, set(server.AGENTS))
        self.assertNotIn("private brief", json.dumps(public))
        self.assertNotIn("delivered", json.dumps(public))
        self.assertEqual(next(r for r in public["agents"] if r["id"] == "dot")["status"], "done")

    def test_task_board_only_sends_changed_snapshots(self):
        def snapshot(previous=None):
            connection = http.client.HTTPConnection("127.0.0.1", self.api.server_port, timeout=3)
            try:
                headers = {"If-None-Match": previous} if previous else {}
                connection.request("GET", "/api/tasks", headers=headers)
                response = connection.getresponse()
                return response.status, response.getheader("ETag"), response.read()
            finally:
                connection.close()

        status, first_tag, body = snapshot()
        self.assertEqual((status, json.loads(body)), (200, {"tasks": []}))
        self.assertTrue(first_tag)
        self.assertEqual(snapshot(first_tag), (304, first_tag, b""))
        self.enabled["carbon"] = False
        _, created = self.request("POST", "/api/tasks", {"brief": "test", "workers": ["argon"]})
        self.wait(created["task"]["id"], lambda t: t["status"] == "handoff")
        status, new_tag, body = snapshot(first_tag)
        self.assertEqual(status, 200)
        self.assertNotEqual(first_tag, new_tag)
        self.assertEqual(json.loads(body)["tasks"][0]["id"], created["task"]["id"])
        self.assertEqual(snapshot(new_tag), (304, new_tag, b""))

    def test_only_owner_can_accept_finished_work(self):
        _, created = self.request("POST", "/api/tasks", {"brief": "写一句汇报", "workers": ["argon"]})
        task_id = created["task"]["id"]
        self.wait(task_id, lambda t: t["status"] == "complete")
        path = f"/api/tasks/{task_id}/accept"
        self.assertEqual(self.request("POST", path, {}, origin=False)[0], 403)
        self.assertEqual(self.request("POST", path, {"workers":["argon"]})[0], 400)
        status, result = self.request("POST", path, {})
        self.assertEqual(status, 200)
        self.assertEqual(result["task"]["acceptedAt"], self.request("POST", path, {})[1]["task"]["acceptedAt"])

    def test_private_dot_mailbox_and_idempotent_result(self):
        self.enabled["dot"] = False
        _, created = self.request("POST", "/api/tasks", {"brief": "private dot meeting", "workers": ["dot"]})
        task_id = created["task"]["id"]
        self.wait(task_id, lambda t: t["status"] == "handoff")
        self.assertIsNone(self.request("GET", "/api/dot/connection")[1]["connectedAt"])
        self.assertEqual(self.request("GET", "/api/dot/connection", extra={"Host":"example.com"})[0], 403)
        headers = {"Authorization": "Bearer " + self.api.office.dot.token}
        self.assertEqual(self.request("POST", "/api/dot/inbox", {}, {"Authorization":"Bearer fixture-reporting-token"})[0], 401)
        self.assertEqual(self.request("POST", "/api/dot/inbox", {}, headers, origin=False)[0], 403)
        _, box = self.request("POST", "/api/dot/inbox", {}, headers)
        self.assertIn("private dot meeting", box["job"]["prompt"])
        self.assertEqual(box["job"]["taskId"], task_id)
        self.assertIsNotNone(self.request("GET", "/api/dot/connection")[1]["connectedAt"])
        reply = {"taskId": task_id, "receipt": box["job"]["receipt"], "result": "meeting delivered"}
        self.assertEqual(self.request("POST", "/api/dot/reply", dict(reply, receipt="0" * 64), headers)[0], 409)
        self.assertEqual(self.request("POST", "/api/dot/reply", reply, headers), (200, {"accepted": True}))
        self.assertEqual(self.request("POST", "/api/dot/reply", reply, headers)[0], 200)
        self.assertEqual(self.request("POST", "/api/dot/reply", dict(reply, result="replaced"), headers)[0], 409)
        self.assertEqual(self.request("POST", "/api/dot/inbox", {}, headers)[1], {"job": None})
        self.assertNotIn("meeting delivered", json.dumps(self.request("GET", "/api/status")[1]))
        self.assertEqual(self.wait(task_id, lambda t: t["status"] == "complete")["steps"][-1]["result"], "meeting delivered")

    def test_single_dispatch_handoff_and_continuation(self):
        self.enabled["astra"] = False
        code, data = self.request("POST", "/api/tasks", {"brief": "private brief", "workers": ["dot", "argon"], "autoAdvance": True})
        self.assertEqual(code, 201)
        task_id = data["task"]["id"]
        task = self.wait(task_id, lambda t: t["steps"][1]["status"] == "handoff")
        self.assertEqual(task["steps"][1]["error"], "fixture capability")
        self.assertEqual([a for a, _ in self.calls], ["carbon"])
        code, _ = self.request("POST", f"/api/tasks/{task_id}/step", {"action": "manual", "stepId": "review", "result": "[dot]\nwrite examples\n[argon]\nverify sources"})
        self.assertEqual(code, 200)
        task = self.wait(task_id, lambda t: t["status"] == "complete")
        self.assertEqual([a for a, _ in self.calls], ["carbon", "dot", "argon"])
        self.assertIn("write examples", self.calls[1][1])
        self.assertIn("verify sources", self.calls[2][1])
        self.assertEqual([s["status"] for s in task["steps"]], ["done"] * 4)

    def test_origin_and_reporter_separation(self):
        brief = {"brief": "private brief", "workers": ["dot"]}
        self.assertEqual(self.request("POST", "/api/tasks", brief, origin=False)[0], 403)
        self.assertEqual(self.request("POST", "/api/tasks", brief, {"Origin": "http://outside.example"})[0], 403)
        self.assertEqual(self.request("GET", "/api/tasks", extra={"Host":"outside.example"})[0], 403)
        self.assertEqual(self.request("GET", "/api/tasks", extra={"X-Forwarded-For":"127.0.0.1"})[0], 403)
        self.assertEqual(self.request("GET", "/api/status", extra={"Host":"outside.example"})[0], 200)
        self.assertEqual(self.request("GET", "/api/capabilities", origin=False)[0], 200)
        self.assertEqual(self.request("POST", "/api/tasks", brief, {"Content-Type":"text/plain"})[0], 415)
        report = {"id": "gpt", "status": "thinking", "collaborator": "gemini"}
        self.assertEqual(self.request("POST", "/api/report", report, origin=False)[0], 401)
        self.assertEqual(self.request("POST", "/api/report", report, {"Authorization":"Bearer fixture-reporting-token"}, origin=False)[0], 200)
        row = next(r for r in self.request("GET", "/api/status")[1]["agents"] if r["id"] == "astra")
        self.assertEqual(row["collaborator"], "carbon")

    def test_auto_chain_one_model_at_a_time(self):
        started, release = threading.Event(), threading.Event()
        original = server.adapters.run_agent.side_effect

        def invoke(agent, prompt):
            if agent == "carbon":
                started.set()
                self.assertTrue(release.wait(3))
            return original(agent, prompt)

        server.adapters.run_agent.side_effect = invoke
        data = {"brief": "research brief", "workers": ["argon", "dot", "hydrogen"], "autoAdvance": True}
        code, created = self.request("POST", "/api/tasks", data)
        self.assertEqual(code, 201)
        self.assertTrue(started.wait(2))
        try:
            other_data = {"brief":"next job","workers":["argon"],"requestId":"00000000-0000-4000-8000-000000000001"}
            code, other = self.request("POST", "/api/tasks", other_data)
            self.assertEqual(code,201)
            self.assertEqual(other["task"]["status"],"queued")
            self.assertEqual(self.request("POST","/api/tasks",other_data)[1]["task"]["id"],other["task"]["id"])
        finally:
            release.set()
        final = self.wait(created["task"]["id"], lambda t: t["status"] == "complete")
        self.wait(other["task"]["id"],lambda t:t["status"]=="complete")
        self.assertEqual([a for a, _ in self.calls], ["carbon", "astra", "argon", "dot", "hydrogen","carbon","astra","argon"])
        self.assertEqual(final["steps"][2]["status"], "done")
        self.assertIn("plan result", self.calls[1][1])

    def test_model_error_requires_explicit_retry(self):
        self.enabled["carbon"] = False
        _, created = self.request("POST", "/api/tasks", {"brief": "research", "workers": ["dot"]})
        task_id = created["task"]["id"]
        path = f"/api/tasks/{task_id}/step"
        self.wait(task_id, lambda t: t["steps"][0]["status"] == "handoff")
        self.enabled["carbon"] = True
        self.assertEqual(self.request("POST", path, {"stepId": "plan", "action": "retry"})[0], 200)
        task = self.wait(task_id, lambda t: t["status"] == "complete")
        self.assertEqual(task["steps"][0]["result"], "plan result")
        self.assertEqual([a for a, _ in self.calls], ["carbon", "astra", "dot"])

    def test_review_sends_material_problem_back_to_carbon(self):
        answers = iter(("old plan", "[revise]\nmissing tests", "updated plan", "[argon]\nverify outcome", "delivered"))

        def invoke(agent, prompt):
            self.calls.append((agent, prompt))
            return next(answers)

        server.adapters.run_agent.side_effect = invoke
        _, created = self.request("POST", "/api/tasks", {"brief": "complex task", "workers": ["argon"], "autoAdvance": True})
        task = self.wait(created["task"]["id"], lambda t: t["status"] == "complete")
        self.assertEqual([a for a, _ in self.calls], ["carbon", "astra", "carbon", "astra", "argon"])
        self.assertIn("missing tests", self.calls[2][1])
        self.assertIn("updated plan", self.calls[3][1])
        self.assertIn("missing tests", self.calls[3][1])
        self.assertIn("updated plan", self.calls[4][1])
        self.assertIn("verify outcome", self.calls[4][1])
        self.assertNotIn("old plan", self.calls[4][1])
        self.assertEqual([s["id"] for s in task["steps"]], ["plan", "review", "revision", "final-review", "execute-argon"])
        self.assertEqual(Workflow(self.data).all()[0]["steps"][2]["result"], "updated plan")

    def test_final_objection_pauses_dispatch_without_another_loop(self):
        server.adapters.run_agent.side_effect = ["first plan", "[revise]\nmissing input", "revised plan", "[revise]\nowner decision", "delivered"]
        _, created = self.request("POST", "/api/tasks", {"brief": "complex", "workers": ["argon"], "autoAdvance": True})
        task_id = created["task"]["id"]
        task = self.wait(task_id, lambda t: t["currentStep"] == "final-review" and t["steps"][3]["status"] == "error")
        self.assertEqual(task["steps"][4]["status"], "pending")
        self.assertEqual(server.adapters.run_agent.call_count, 4)
        _, response = self.request("POST", f"/api/tasks/{task_id}/step", {"stepId": "final-review", "action": "manual", "result": "[revise]\nstill blocked"})
        self.assertEqual(response["task"]["currentStep"], "final-review")
        self.assertEqual(server.adapters.run_agent.call_count, 4)
        self.request("POST", f"/api/tasks/{task_id}/step", {"stepId": "final-review", "action": "manual", "result": "[argon]\nuse approved input"})
        final = self.wait(task_id, lambda t: t["status"] == "complete")
        self.assertEqual(len(final["steps"]), 5)
        self.assertIn("still blocked", final["steps"][3]["blockedReview"])

    def test_restore_never_replays_model(self):
        self.enabled["carbon"] = False
        task = self.api.office.workflow.create({"brief": "local only", "workers": ["dot"]})
        self.wait(task["id"], lambda t:t["status"]=="handoff")
        path = self.data / "tasks" / (task["id"] + ".json")
        saved = json.loads(path.read_text(encoding="utf-8"))
        saved["steps"][0]["status"] = "running"
        saved["autoAdvance"] = True
        path.write_text(json.dumps(saved), encoding="utf-8")
        recovered = Workflow(self.data).all()[0]
        self.assertEqual(recovered["steps"][0]["status"], "error")
        self.assertEqual(self.calls, [])

    def test_existing_assigned_task_continues_after_migration(self):
        task = self.api.office.workflow.create({"brief":"existing assigned brief","workers":["argon"]})
        self.wait(task["id"],lambda t:t["status"]=="complete")
        path = self.data / "tasks" / (task["id"] + ".json")
        saved = json.loads(path.read_text(encoding="utf-8"))
        saved["autoAdvance"] = False
        saved["steps"].insert(2,dict(id="approval",agent="president",kind="approval",status="pending",result="",error="",updatedAt=None))
        saved["steps"][-1].update(status="pending",result="",updatedAt=None)
        path.write_text(json.dumps(saved),encoding="utf-8")
        self.calls.clear()
        restored = Workflow(self.data)
        deadline=time.monotonic()+2
        while restored.all()[0]["status"]!="complete" and time.monotonic()<deadline:
            time.sleep(.01)
        self.assertEqual(restored.all()[0]["status"],"complete")
        self.assertEqual([a for a,_ in self.calls],["argon"])


if __name__ == "__main__":
    unittest.main()

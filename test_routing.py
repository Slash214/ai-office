"""Automatic staffing, review and final acceptance through the normal workflow."""

import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import adapters
from workflow import NAMES, Problem, Workflow


def decision(*assignments):
    return json.dumps({"reason": "按实际交付能力分工",
                       "assignments": [{"agent": agent, "task": work} for agent, work in assignments]},
                      ensure_ascii=False)


class RoutingTest(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.caps = {a: {"ready": a != "dot", "detail": a + " connection"} for a in NAMES}
        self.enterContext(patch.object(adapters, "capabilities", side_effect=lambda: self.caps))
        self.calls = []
        self.reply = {"carbon": "明确目标和验收方法。", "astra": decision(("codex", "调整按钮并跑测试。")),
                      "codex": "完成修改，测试通过。", "hydrogen": "交付文案。", "argon": "交付分析。"}

        def invoke(agent, prompt):
            self.calls.append((agent, prompt))
            response = self.reply[agent]
            return response(prompt) if callable(response) else response

        self.enterContext(patch.object(adapters, "run_agent", side_effect=invoke))
        self.flow = Workflow(self.directory)

    def wait(self, request, status):
        end = time.monotonic() + 4
        while time.monotonic() < end:
            task = next(t for t in self.flow.all() if t["id"] == request["id"])
            if status(task):
                return task
            time.sleep(.01)
        self.fail("Timed out at " + str([(s["id"], s["status"], s["error"]) for s in task["steps"]]))

    def completed(self, request):
        return self.wait(request, lambda t: t["status"] == "complete")

    def test_automatic_ui_work_and_final_acceptance(self):
        review_started, resume = threading.Event(), threading.Event()
        def reviewer(prompt):
            review_started.set()
            self.assertTrue(resume.wait(2))
            return decision(("codex", "只调整可读性并运行测试。"))
        self.reply["astra"] = reviewer
        body = {"brief": "优化办公室 UI", "requestId": "e92bdd3e-7416-4469-b14e-bdeb99d73e55"}
        task = self.flow.create(body)
        self.assertTrue(review_started.wait(2))
        try:
            reviewing = self.flow.all()[0]
            self.assertEqual(reviewing["workers"], [])
            self.assertEqual([s["id"] for s in reviewing["steps"]], ["plan", "review"])
            with self.assertRaises(Problem) as early:
                self.flow.accept(task["id"])
            self.assertEqual(early.exception.code, 409)
        finally:
            resume.set()
        result = self.completed(task)
        self.assertEqual([agent for agent, _ in self.calls], ["carbon", "astra", "codex"])
        self.assertIn("只调整可读性并运行测试。", self.calls[-1][1])
        self.assertEqual(result["workers"], ["codex"])
        self.assertEqual(result["routingSource"], "astra")
        self.assertNotIn("acceptedAt", result)
        self.assertEqual(self.flow.create(body)["id"], result["id"])
        with self.assertRaises(Problem):
            self.flow.create(dict(body, workers=["codex"]))
        stamp = self.flow.accept(task["id"])["acceptedAt"]
        self.assertEqual(self.flow.accept(task["id"])["acceptedAt"], stamp)
        restored = Workflow(self.directory).all()[0]
        self.assertEqual(restored["acceptedAt"], stamp)
        self.assertEqual(restored["assignments"], {"codex": "只调整可读性并运行测试。"})
        self.assertEqual(len(self.calls), 3)

    def test_multiple_roles_chosen_by_real_review(self):
        self.reply["astra"] = decision(("argon", "核对措辞。"), ("hydrogen", "写文案。"))
        task = self.completed(self.flow.create({"brief":"为团队编写文案，需要分析和初稿。"}))
        self.assertEqual(task["workers"], ["argon", "hydrogen"])
        self.assertEqual([a for a,_ in self.calls], ["carbon", "astra", "argon", "hydrogen"])
        self.assertIn("你的具体任务：\n核对措辞。", self.calls[2][1])
        self.assertIn("你的具体任务：\n写文案。", self.calls[3][1])

    def test_bad_routing_is_corrected_without_requesting_approval(self):
        self.reply["astra"] = decision(("../../bad", "示例"))
        task = self.completed(self.flow.create({"brief":"优化办公室UI"}))
        self.assertEqual((task["workers"], task["routingSource"]), (["codex"], "fallback"))
        self.reply["astra"] = "普通文本，无结构化分工。"
        writing = self.completed(self.flow.create({"brief":"只给我办公室界面优化的文案建议，不用修改代码。"}))
        self.assertEqual((writing["workers"], writing["routingSource"]), (["hydrogen"], "fallback"))
        self.assertEqual([a for a,_ in self.calls].count("codex"), 1)

    def test_one_automatic_revision_before_coding(self):
        responses = iter(("[revise]\n加入测试。", decision(("codex","实现并运行测试。"))))
        self.reply["astra"] = lambda _prompt: next(responses)
        task = self.completed(self.flow.create({"brief":"优化办公室 UI"}))
        self.assertEqual([s["id"] for s in task["steps"]],
                         ["plan","review","revision","final-review","execute-codex"])
        self.assertEqual(len(self.calls), 5)

    def test_missing_coding_agent_never_marks_edits_complete(self):
        self.caps["codex"]["ready"] = False
        task = self.flow.create({"brief":"优化办公室 UI"})
        result = self.wait(task, lambda t: t["steps"][-1]["status"] == "error")
        self.assertEqual(result["currentStep"], "execute-codex")
        self.assertEqual(result["steps"][-1]["error"], "codex connection")
        self.assertEqual([a for a,_ in self.calls], ["carbon", "astra"])

    def test_owner_can_refine_a_failed_coding_step_without_replanning(self):
        self.caps["codex"]["ready"] = False
        job = self.flow.create({"brief":"优化办公室 UI"})
        self.wait(job, lambda t: t["steps"][-1]["status"] == "error")
        self.caps["codex"]["ready"] = True
        self.flow.act(job["id"], {"action":"retry","stepId":"execute-codex","feedback":"采用新的人物设计。"})
        result = self.completed(job)
        self.assertEqual(result["steps"][-1]["feedback"], "采用新的人物设计。")
        self.assertTrue(self.calls[-1][1].endswith("采用新的人物设计。"))
        self.assertEqual([a for a,_ in self.calls], ["carbon","astra","codex"])

    def test_online_external_assignment_retains_name_after_disconnect(self):
        class Seats:
            def list(self):
                return [{"id":"slot-000000000001", "name":"文稿组", "online":True},
                        {"id":"slot-000000000002", "name":"离线组", "online":False}]
        self.flow.slots = Seats()
        self.reply["astra"] = decision(("slot-000000000001", "编辑简报。"))
        result = self.wait(self.flow.create({"brief":"请协调同事撰写简报。"}), lambda t:t["status"]=="handoff")
        self.assertNotIn("离线组", self.calls[1][1])
        self.assertEqual(result["workerNames"], {"slot-000000000001":"文稿组"})
        job = self.flow.claim_slot("slot-000000000001")
        self.assertIn("编辑简报。", job["prompt"])
        self.flow.receive_slot("slot-000000000001", {"lease":job["lease"], "result":"简报已交付。"})
        self.assertEqual(self.completed(result)["workers"], ["slot-000000000001"])


if __name__ == "__main__":
    unittest.main()

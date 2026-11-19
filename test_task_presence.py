import json
from pathlib import Path
import tempfile
import time
import unittest
import uuid

from server import Office, STALE_SECONDS, iso_time
from workflow import new_step


class TaskPresence(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.office = Office(Path(directory))
        self.clock = time.time()

    def step(self, name, agent, kind, status="pending", age=0, **extra):
        step = new_step(name, agent, kind)
        if status != "pending":
            step.update(status=status, updatedAt=iso_time(self.clock - age))
        step.update(extra)
        return step

    def add(self, *steps, age=0, **extra):
        task_id = str(uuid.uuid4())
        task = dict(id=task_id, brief="private-brief", workers=[], autoAdvance=True,
                    createdAt=iso_time(self.clock - age), updatedAt=iso_time(self.clock - age),
                    steps=list(steps))
        task.update(extra)
        self.office.workflow.tasks[task_id] = task
        return task

    def roster(self):
        return {row["id"]: row for row in self.office.snapshot()["agents"]}

    def test_desktop_summary_tracks_handoff_testing_and_acceptance(self):
        flow=self.office.workflow
        task=self.add(self.step("review","astra","review","done"),
                      self.step("execute-codex","codex","execution","running"))
        one=flow.desktop_summary()
        self.assertEqual((one["running"],one["coding"],one["handoff"]["sender"]),(1,True,"astra"))
        self.assertNotIn("private-brief",json.dumps(one))
        flow.record_coder_screen(task["id"],"execute-codex","testing",{})
        self.assertEqual(flow.desktop_summary()["headline"],"Codex · 运行测试")
        self.assertFalse(flow.desktop_summary()["coding"])
        task["steps"][1]["status"]="done"
        ready=flow.desktop_summary()
        self.assertEqual((ready["running"],ready["reviews"],ready["reviewId"]),(0,1,task["id"]))
        task["acceptedAt"]=iso_time(time.time())
        self.assertEqual(flow.desktop_summary()["reviews"],0)

    def test_pet_observes_standalone_report_without_counting_an_order(self):
        self.office.store_report(dict(id="codex",status="coding",activity="code",collaborator=None))
        state=self.office.desktop_summary()
        self.assertEqual((state["headline"],state["coding"],state["running"]),("Codex · 编写代码",True,0))

    def test_new_dispatch_takes_precedence_over_review_backlog(self):
        self.add(self.step("execute-codex", "codex", "execution", "done"), age=60)
        plan = self.step("plan", "carbon", "plan", "queued")
        review = self.step("review", "astra", "review")
        task = self.add(plan, review)
        def snapshot():
            return self.office.desktop_summary()
        self.assertEqual(snapshot()["command"]["phase"], "dispatch")
        self.assertEqual(snapshot()["reviews"], 1)
        self.assertIn("呵呵大王 · 分配任务", [e["text"] for e in snapshot()["recent"]])
        plan["status"] = "running"
        self.assertIn("Carbon 规划中", snapshot()["command"]["text"])
        plan["status"] = "error"
        self.assertEqual(snapshot()["command"], dict(id=task["id"], phase="blocked",
                         text="已派单 · Carbon 规划受阻", standby="等待分工"))
        plan["status"], review["status"] = "done", "running"
        review["updatedAt"] = plan["updatedAt"]
        self.assertIn("Astra 分工中", snapshot()["command"]["text"])
        review["status"] = "done"
        self.assertEqual(snapshot()["command"]["phase"], "review")
        self.assertNotIn("private-brief", json.dumps(snapshot()))

    def test_only_owner_workstation_exposes_edit_and_stop_clears_it(self):
        task=self.add(self.step("execute-codex","codex","execution","running"))
        flow=self.office.workflow
        fields={"path":"public/ui.js","lines":["+ uniqueLocalChange()"]}
        flow.record_coder_screen(task["id"],"execute-codex","edited",fields)
        flow.record_coder_screen(task["id"],"execute-codex","testing",{})
        self.assertEqual(flow.workstation(),dict(stage="testing", **fields))
        self.assertNotIn("uniqueLocalChange",json.dumps(self.office.snapshot()))
        flow.stop(task["id"])
        self.assertIsNone(flow.workstation())

    def test_pending_roles_are_visible_without_inventing_executors(self):
        self.add(
            self.step("plan", "carbon", "plan", "running"),
            self.step("review", "astra", "review"),
            routingCandidates={"codex": "candidate only"},
        )
        rows = self.roster()
        self.assertEqual(rows["carbon"]["status"], "thinking")
        self.assertEqual(rows["carbon"]["activity"], "planning")
        self.assertEqual(rows["astra"]["status"], "assigned")
        self.assertEqual(rows["astra"]["activity"], "review")
        self.assertEqual(rows["codex"]["status"], "idle")

        self.add(
            self.step("execute-argon", "argon", "execution", "queued"),
            self.step("execute-codex", "codex", "execution"),
        )
        rows = self.roster()
        self.assertEqual(rows["argon"]["status"], "queued")
        self.assertEqual(rows["codex"]["status"], "assigned")
        self.assertNotIn("private-brief", json.dumps(rows))
        self.assertEqual(set(rows["codex"]), {"id", "status", "activity", "collaborator", "updatedAt"})

    def test_running_outranks_newer_waiting_and_survives_staleness(self):
        self.add(
            self.step("execute-codex", "codex", "execution", "running", age=STALE_SECONDS + 60),
            age=STALE_SECONDS + 60,
        )
        self.add(self.step("execute-codex", "codex", "execution", "queued"))
        self.office.store_report({"id": "codex", "status": "idle", "activity": "general", "collaborator": None})
        self.assertEqual(self.roster()["codex"]["status"], "coding")

    def test_manual_active_report_can_precede_waiting_assignment(self):
        self.add(self.step("execute-codex", "codex", "execution"))
        self.office.store_report({"id": "codex", "status": "terminal", "activity": "code", "collaborator": None})
        self.assertEqual(self.roster()["codex"]["status"], "terminal")

    def test_stopping_a_task_clears_waiting_states(self):
        task = self.add(
            self.step("plan", "carbon", "plan", "error"),
            self.step("review", "astra", "review"),
        )
        self.add(self.step("plan", "carbon", "plan", "queued"))
        self.assertEqual(self.roster()["carbon"]["status"], "error")
        self.assertEqual(self.roster()["astra"]["status"], "assigned")
        self.office.workflow.stop(task["id"])
        self.assertEqual(self.roster()["carbon"]["status"], "queued")
        self.assertEqual(self.roster()["astra"]["status"], "idle")

    def test_external_seat_reports_assignment_claim_and_delivery(self):
        guest = self.office.slots.create("private-member")
        seat = guest["id"]
        step = self.step("execute-" + seat, seat, "execution", "handoff")
        self.add(step, workerNames={seat: guest["name"]})
        self.assertEqual(self.office.snapshot()["guestSeats"][0]["status"], "queued")
        step.update(lease="private-lease", leaseUntil=self.clock + 600)
        self.assertEqual(self.office.snapshot()["guestSeats"][0]["status"], "thinking")
        step["leaseUntil"] = self.clock - 1
        self.assertEqual(self.office.snapshot()["guestSeats"][0]["status"], "error")
        step["status"] = "done"
        result = self.office.snapshot()["guestSeats"][0]
        self.assertEqual(result, dict(id=seat, online=False, status="done"))


if __name__ == "__main__":
    unittest.main()

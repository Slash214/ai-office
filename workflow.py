"""Local, durable president-to-team task dispatch."""

import copy
import json
import os
import re
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone

import adapters
import cancellation
import project_coder
import releases


NAMES = {
    "carbon": "Gemini 4 Carbon", "astra": "GPT Astra", "dot": "Codex Dot",
    "argon": "Gemini 4 Argon", "hydrogen": "Gemini 4 Hydrogen", "codex": "本机 Codex",
}
WORKERS = ("codex", "argon", "hydrogen", "dot")
ROLES = {
    "codex": "工程执行。能修改本机工作室代码、运行项目测试并交回改动记录",
    "argon": "文本执行。可分析、研究、评估方案",
    "hydrogen": "文本执行。可撰写、整理、校对内容",
    "dot": "个人 Dot 会话。适合总裁点名的沟通或会议，可能需要等待该会话上线",
}
STAGES = {"plan": "planning", "review": "reviewing", "approval": "awaiting_approval", "execution": "executing"}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Problem(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def check_text(value, name, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise Problem(400, f"{name}须为 1 至 {limit} 字的文本。")
    value = value.strip()
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise Problem(400, f"{name}含有无效字符。")
    return value


def new_step(step_id, agent, kind):
    return dict(id=step_id, agent=agent, kind=kind, status="pending", result="", error="", updatedAt=None)


def current(task):
    if task.get("stoppedAt"):
        return None
    open_steps = [step for step in task["steps"] if step["status"] != "done"]
    # Independent executors can deliver while a colleague is in an external session.
    return next((step for step in open_steps if not (
        step["kind"] == "execution" and step["status"] == "handoff"
    )), open_steps[0] if open_steps else None)


def assignment(review, agent):
    pattern = r"^\s*(?:#{1,6}\s*)?[\[【]" + re.escape(agent) + r"[\]】]\s*[:：]?\s*(.*?)(?=^\s*(?:#{1,6}\s*)?[\[【](?:codex|dot|argon|hydrogen|slot-[0-9a-f]{12})[\]】]|\Z)"
    match = re.search(pattern, review, re.M | re.S | re.I)
    return match.group(1).strip()[:2000] if match else ""


def engineering_work(brief):
    # Only a clear implementation request forces a worktree-capable executor.
    # Open-ended requests are left to Astra's actual role selection.
    if re.search(r"(?:不要|不用|无需|禁止|先不|暂不|不需要)(?:实际|直接|真的)?(?:动|修改|改|写|实现|运行)|(?:只(?:写|要|给|需)|仅(?:给|写)|提供|给出).{0,8}(?:建议|思路|方案|说明)|(?:suggestions?|proposal|advice) only|do not (?:modify|edit)", brief, re.I):
        return False
    verb = r"(?:优化|重构|修改|改进|改版|美化|修复|实现|开发|新增|调整|添加|适配|改一下|改好|implement|change|improve|optimi[sz]e|polish|fix|refactor)"
    target = r"(?:界面|样式|代码|程序|前端|后端|功能|按钮|壁纸|网页|布局|组件|(?<![a-z])ui(?![a-z])|\bcss\b|\bcode\b|application|interface|component)"
    return bool(re.search(verb + r"[^。！？\n]{0,24}" + target + "|" + target + r"[^。！？\n]{0,16}" + verb +
                          r"|(?:运行|跑|执行)(?:项目|现有|单元|回归|自动化)?测试|run (?:the |project |regression |unit )*tests", brief, re.I))


def candidate_workers(brief, slots, caps=None):
    choices = {}
    for agent in WORKERS:
        if agent == "dot" and not re.search(r"(?<![a-z])dot(?![a-z])|小呵", brief, re.I):
            continue
        if agent in ("argon", "hydrogen") and caps is not None and not caps.get(agent, {}).get("ready"):
            continue
        choices[agent] = NAMES[agent]
    for slot in slots.list() if slots else ():
        if slot["online"] or slot["name"].casefold() in brief.casefold():
            choices[slot["id"]] = slot["name"]
    return choices


def review_routing(text, candidates):
    value = text.strip()
    fence = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", value, re.I | re.S)
    if fence:
        value = fence[1]
    try:
        decision = json.loads(value)
        reason = check_text(decision["reason"], "分工理由", 2000)
        entries = decision["assignments"]
        if not isinstance(entries, list) or not 1 <= len(entries) <= len(candidates):
            return None
        assignments = {}
        for item in entries:
            agent = item["agent"]
            if not isinstance(agent, str) or agent not in candidates or agent in assignments:
                return None
            assignments[agent] = check_text(item["task"], "分工", 2000)
        return reason, assignments
    except (ValueError, TypeError, KeyError, RecursionError, Problem):
        return None


def assign_review(task, step, text):
    candidates = task["routingCandidates"]
    decision = review_routing(text, candidates)
    needs_coder = engineering_work(task["brief"])
    if decision and (not needs_coder or "codex" in decision[1]):
        reason, assignments = decision
        source = "astra"
        step["result"] = reason + "\n\n" + "\n\n".join(f"[{agent}]\n{scope}" for agent, scope in assignments.items())
    else:
        # Never turn a mistyped model id into a new command, or count a proposal as a code delivery.
        if needs_coder:
            agent = "codex"
        elif "dot" in candidates and re.search(r"聊天|会面|开会|会议|入会|对话|报到|meeting|chat", task["brief"], re.I):
            agent = "dot"
        elif named_slot := next((a for a,n in candidates.items()
                                 if a not in WORKERS and n.casefold() in task["brief"].casefold()), None):
            agent = named_slot
        else:
            # Prefer the built-in text specialists for a malformed, open-ended review.
            writing = re.search(r"文案|撰写|写作|翻译|润色|草稿|稿件|draft|copywriting", task["brief"], re.I)
            preference = ("hydrogen", "argon") if writing else ("argon", "hydrogen")
            agent = next((a for a in preference if a in candidates), None)
            if not agent:
                raise Problem(503, "复核未给出有效分工，当前没有可用的文本执行成员。请检查模型连接后重试复核。")
        reason = f"Astra 的分工未提供可用的执行清单。工作室按工种转给{candidates[agent]}。"
        scope = ("按总裁目标完成本机工作室的工程交付。仅在总裁要求实施时修改文件；仅要求检查时保留源文件。运行相关测试并报告实际结果。"
                 if agent == "codex" else "根据总裁目标、Carbon 规划与 Astra 复核意见，交付可验收的文本成果。")
        assignments, source = {agent:scope}, "fallback"
    task.update(workers=list(assignments), assignments=assignments, assignmentReason=reason, routingSource=source)
    task["workerNames"] = {agent: candidates[agent] for agent in assignments if agent not in WORKERS}
    task["steps"].extend(new_step("execute-" + agent, agent, "execution") for agent in assignments)


def prompt_for(task, step):
    names = {**NAMES, **task.get("workerNames", {})}
    worker_names = "、".join(f"{names[a]} [{a}]" for a in task["workers"])
    auto = task.get("routingMode") == "auto"
    if auto and step["kind"] in ("plan", "review"):
        worker_names = "\n".join(f"[{agent}] {name} · {ROLES.get(agent, '同事自定义执行席，根据其名字及当前需要分工')}"
                                for agent, name in task["routingCandidates"].items())
    if step["kind"] == "approval":
        return "请总裁查看 Carbon 方案及 Astra 审核分工，确认后将任务派给所选团队。"
    header = f"你是 {names[step['agent']]}。请用中文直接交付本阶段的文本成果。\n\n总裁任务：\n{task['brief']}"
    if step["id"] == "plan":
        return header + f"\n\n负责规划。提出可执行的步骤、所需输入与验收标准。可用执行成员：{worker_names}。"
    results = {item["id"]: item["result"] for item in task["steps"]}
    if step["id"] in ("revision", "final-review"):
        header += "\n\nCarbon 的初案：\n" + results["plan"] + "\n\nAstra 要求修订的意见：\n" + results["review"]
        if step["id"] == "revision":
            return header + f"\n\n请逐条回应 Astra，说明如何解决问题，交回一份完整修订方案及验收标准。执行成员：{worker_names}。"
        header += "\n\nCarbon 的完整修订方案：\n" + results["revision"]
    else:
        header += "\n\nCarbon 的方案：\n" + results.get("revision", results["plan"])
    if step["kind"] == "review":
        if auto:
            revision = ("如有实质问题，可只在首行写 [revise] 再逐条列出修订要求，Carbon 会自动修订一次。"
                        if step["id"] == "review" else
                        "这是最终复核。对常规取舍直接作决定，在分工中交代尚需验证的事项。")
            return header + "\n\n你代表总裁安排执行。选完成交付所需的最少成员，给每人一份具体、可验收的工作。" + (
                "工作室 UI、代码、集成或实际跑测试的任务由 codex 操作项目。文本建议和文案可由 argon 或 hydrogen 执行。"
                "总裁点名与个人 Dot 沟通时交给 dot。不要代替执行者声称已经完成。\n候选成员：\n" + worker_names +
                "\n" + revision + '\n正常分工只返回一个 JSON 对象。reason 填写审核与选择理由，assignments 数组中的每项'
                '包含候选成员的准确标识 agent 和具体交付内容 task。格式为 {"reason":"实际选择理由","assignments":[{"agent":"成员标识","task":"具体分工与验收标准"}]}。'
            )
        review_focus = (
            "核对修订方案和你之前提出的问题。如仍有实质阻碍，请单独在首行写 [revise]，列出需要总裁裁决的问题，流程会暂停。"
            if step["id"] == "final-review" else
            "审核上面的方案。如有实质问题需要 Carbon 重新规划，请单独在首行写 [revise]，逐条说明问题及修改要求。"
        )
        return header + "\n\n" + review_focus + (
            "若方案可执行，直接给出审核结论，并为每位执行成员划分具体交付物及验收标准。"
            "当前仍在分工阶段。请将员工报到、会议发言和任务成果留给相应执行成员实际交付。"
            f"可用成员：{worker_names}。在各成员分工前单独写一行其方括号标识，例如 [dot]。"
        )
    review = results.get("final-review", results["review"])
    header += "\n\nAstra 的审核及分工：\n" + review
    assigned = task.get("assignments", {}).get(step["agent"]) or assignment(review, step["agent"])
    responsibility = f"\n你的具体任务：\n{assigned}" if assigned else f"\n请按审核中对 {names[step['agent']]} 的分工交付。"
    latest = step.get("feedback", "")
    return (header + responsibility + "\n直接给出可供总裁使用的成果。明确仍需外部资料或环境才能验证的部分。"
            + ("\n\n总裁补充的最新交付要求（更新上方旧要求）：\n" + latest if latest else ""))


def render(task):
    result = copy.deepcopy(task)
    step = current(result)
    result["status"] = "stopped" if task.get("stoppedAt") else STAGES[step["kind"]] if step else "complete"
    if step and step["status"] in ("queued", "handoff"):
        result["status"] = step["status"]
    result["currentStep"] = step["id"] if step else None
    for item in result["steps"]:
        item.pop("dotReceipt", None)
        if item.pop("lease", None):
            item["claimed"] = True
        item.pop("leaseUntil", None)
        item.pop("receipt", None)
        item["prompt"] = prompt_for(result, item) if item is step else ""
    return result


class Workflow:
    def __init__(self, directory, slots=None, root=adapters.ROOT):
        self.data_dir = directory
        self.root = root
        self.slots = slots
        self.directory = directory / "tasks"
        self.directory.mkdir(mode=0o700, exist_ok=True)
        self.lock = threading.RLock()
        self.tasks = {}
        self.instance_id = uuid.uuid4().hex
        self.version = 0
        self.busy = None
        self.stop_event = None
        for path in self.directory.glob("*.json"):
            task = json.loads(path.read_text(encoding="utf-8"))
            if path.stem != str(uuid.UUID(task["id"])):
                raise ValueError("Invalid stored task id")
            self.tasks[task["id"]] = task
            if task.get("release") and not task.get("stoppedAt"):
                self.restore_release(task)
            step = current(task)
            if not step:
                continue
            task["autoAdvance"] = True
            if step["kind"] == "approval":
                step.update(status="done", result="总裁派单时已授权自动执行。", error="", updatedAt=now())
                step = current(task)
            if step and step["status"] == "running":
                step.update(status="error", error="上次运行在服务退出时中断。请重试或手动提交结果。", updatedAt=now())
            elif step and step["status"] == "pending":
                step.update(status="queued", updatedAt=now())
            self.save(task)
        with self.lock:
            self.schedule_next()

    def save(self, task):
        task["updatedAt"] = now()
        fd, filename = tempfile.mkstemp(prefix="task-", suffix=".tmp", dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(task, file, ensure_ascii=False)
                file.flush()
                os.fsync(file.fileno())
            os.replace(filename, self.directory / (task["id"] + ".json"))
        finally:
            if os.path.exists(filename):
                os.unlink(filename)
        self.tasks[task["id"]] = task
        self.version += 1

    def all(self):
        return self.list_if_changed(None)[1]

    def list_if_changed(self, previous):
        with self.lock:
            self.expire_slot_leases()
            tag = f'"{self.instance_id}-{self.version}"'
            if tag == previous:
                return tag, None
            return tag, [render(task) for task in sorted(self.tasks.values(), key=lambda t: (t["createdAt"], t["id"]), reverse=True)]

    def accept(self, task_id, release_id=None):
        with self.lock:
            task = self.owner_task(task_id)
            if task.get("stoppedAt") or current(task) is not None:
                raise Problem(409, "团队仍在处理，所有执行成员交付后可验收。")
            self.check_release(task, release_id)
            if not task.get("acceptedAt"):
                task = copy.deepcopy(task)
                if task.get("release"):
                    task["release"] = self.release_operation(releases.publish, task["release"]["id"])
                task["acceptedAt"] = now()
                self.save(task)
            return render(task)

    def owner_task(self, task_id):
        if task_id not in self.tasks:
            raise Problem(404, "找不到这项任务。")
        return self.tasks[task_id]

    @staticmethod
    def check_release(task, release_id):
        if (task.get("release") or {}).get("id") != release_id:
            raise Problem(409, "候选版本已经变化，请刷新工单。")

    def release_operation(self, operation, release_id):
        try:
            return operation(self.root, release_id, data_dir=self.data_dir)
        except releases.ReleaseConflict as exc:
            raise Problem(409, str(exc)) from exc
        except FileNotFoundError as exc:
            raise Problem(404, "这个候选版本已不可用。") from exc

    def restore_release(self, task):
        """Finish an owner-authorized transition interrupted by a service restart."""
        release_id = task["release"]["id"]
        try:
            info = self.release_operation(releases.inspect, release_id)
            if info["state"] == "publishing":
                info = self.release_operation(releases.publish, release_id)
            elif info["state"] == "rolling_back":
                info = self.release_operation(releases.rollback, release_id)
            if info["state"] == "published" and not task.get("acceptedAt"):
                task.update(acceptedAt=now(), release=info)
                self.save(task)
            elif info["state"] == "rolled_back" and not task.get("rolledBackAt"):
                task.update(rolledBackAt=now(), release=info)
                self.save(task)
        except (Problem, OSError, RuntimeError):
            # Keep the owner action retryable and preserve any intervening source edits.
            pass

    def preview(self, task_id, release_id):
        with self.lock:
            task = self.owner_task(task_id)
            candidate = task.get("release")
            if task.get("stoppedAt") or task.get("acceptedAt") or current(task) or not candidate:
                raise Problem(409, "此工单目前没有待验收的候选版。")
            self.check_release(task, release_id)
            info = self.release_operation(releases.inspect, candidate["id"])
            if info["state"] != "staged":
                raise Problem(409, "候选版正在处理，请刷新工单。")
            return info

    def reject(self, task_id, feedback, release_id=None):
        feedback = check_text(feedback, "返工意见", 2000)
        with self.lock:
            task = copy.deepcopy(self.owner_task(task_id))
            if task.get("acceptedAt") or task.get("stoppedAt") or current(task):
                raise Problem(409, "只有待验收的工单可以打回。")
            self.check_release(task, release_id)
            execution = [step for step in task["steps"] if step["kind"] == "execution"]
            if not execution:
                raise Problem(409, "没有可返工的执行步骤。")
            candidate = task.pop("release", None)
            step = next((step for step in execution if step["agent"] == "codex"), execution[-1])
            if candidate:
                info = self.release_operation(releases.inspect, candidate["id"])
                if info["state"] != "staged":
                    raise Problem(409, "候选版已开始发布，请完成验收后回退。")
                task["revisionBase"] = candidate["id"]
            for field in ("lease", "leaseUntil", "receipt", "dotReceipt"):
                step.pop(field, None)
            step.update(status="pending", result="", error="", feedback=feedback)
            self.enqueue(task)
            return render(task)

    def rollback(self, task_id, release_id):
        with self.lock:
            task = copy.deepcopy(self.owner_task(task_id))
            if not task.get("acceptedAt") or not task.get("release"):
                raise Problem(409, "此工单没有可回退的已发布版本。")
            self.check_release(task, release_id)
            if task["release"]["state"] != "rolled_back":
                task["release"] = self.release_operation(releases.rollback, task["release"]["id"])
                task["rolledBackAt"] = now()
                self.save(task)
            return render(task)

    def stop(self, task_id, expected_step=None):
        with self.lock:
            task = copy.deepcopy(self.owner_task(task_id))
            if task.get("stoppedAt"):
                return render(task)
            active = current(task)
            if not active:
                raise Problem(409, "任务已交付，请从验收区处理。")
            if expected_step is not None and active["id"] != expected_step:
                raise Problem(409, "任务已进入下一步，请刷新任务后再停止。")
            task["stoppedAt"] = now()
            for step in task["steps"]:
                if step["status"] != "done":
                    if step["status"] != "pending":
                        step["updatedAt"] = task["stoppedAt"]
                    step.update(status="cancelled", error="")
                    for field in ("lease", "leaseUntil", "receipt", "dotReceipt"):
                        step.pop(field, None)
            self.save(task)
            if self.busy == task_id:
                self.stop_event.set()
            self.cleanup_release((task.get("release") or {}).get("id"))
            self.cleanup_release(task.get("revisionBase"))
            return render(task)

    def notifications(self):
        with self.lock:
            self.expire_slot_leases()
            events = []
            for task in self.tasks.values():
                if task.get("stoppedAt") or task.get("acceptedAt"):
                    continue
                step = current(task)
                if step is None:
                    kind = "review"
                elif step["status"] == "error":
                    kind = "failed"
                elif step["status"] == "handoff" and step["agent"] not in task.get("workerNames", {}):
                    kind = "input"
                else:
                    continue
                stamp = step["updatedAt"] if step else task["updatedAt"]
                subject = step["id"] if step else "delivery"
                key = f'{task["id"]}:{kind}:{subject}:{stamp}'
                events.append((stamp, {"id": key, "taskId": task["id"], "kind": kind}))
            return [event for _, event in sorted(events, key=lambda item: (item[0], item[1]["id"]), reverse=True)[:50]]

    def board_updates(self):
        rows = {}
        with self.lock:
            for task in self.tasks.values():
                for step in task["steps"]:
                    stamp = step["updatedAt"]
                    agent = step["agent"]
                    if (agent not in NAMES and agent not in task.get("workerNames", {})) or not stamp or (agent in rows and stamp <= rows[agent]["updatedAt"]):
                        continue
                    status = {"running": "thinking", "done": "done", "error": "error", "handoff": "needs_input",
                              "cancelled": "idle"}.get(step["status"])
                    if agent in task.get("workerNames", {}) and step["status"] == "handoff":
                        status = "thinking" if step.get("lease") else "idle"
                    if status:
                        activity = {"plan": "planning", "review": "review", "execution": "general"}[step["kind"]]
                        peer = {"review": "carbon", "revision": "astra", "final-review": "carbon"}.get(step["id"]) if status == "thinking" else None
                        if agent == "codex":
                            activity = "code"
                            if status == "thinking":
                                status = "coding"
                        rows[agent] = dict(id=agent, status=status, updatedAt=stamp, activity=activity, collaborator=peer)
        return rows

    def schedule_next(self):
        if self.busy is not None:
            return
        queued = [t for t in self.tasks.values() if (step := current(t)) and step["status"] == "queued"]
        if queued:
            self.start(min(queued, key=lambda t: (current(t)["updatedAt"], t["createdAt"], t["id"])))

    def enqueue(self, task):
        step = current(task)
        if step and step["status"] in ("pending", "error"):
            step.update(status="queued", error="", updatedAt=now())
        self.save(task)
        self.schedule_next()

    def create(self, data):
        if type(data) is not dict or data.keys() - {"brief", "workers", "autoAdvance", "requestId"}:
            raise Problem(400, "任务字段无效。")
        brief = check_text(data.get("brief"), "任务", 6000)
        auto_route = "workers" not in data
        workers = data.get("workers", [])
        if not auto_route and (not isinstance(workers, list) or not 1 <= len(workers) <= len(WORKERS) + 12
                               or not all(isinstance(w, str) for w in workers) or len(set(workers)) != len(workers)):
            raise Problem(400, "请选择执行成员，每人选一次。")
        if type(data.get("autoAdvance", True)) is not bool:
            raise Problem(400, "自动运行选项无效。")
        task_id = data.get("requestId", str(uuid.uuid4()))
        try:
            if not isinstance(task_id, str) or str(uuid.UUID(task_id)) != task_id:
                raise ValueError()
        except ValueError:
            raise Problem(400, "任务标识无效。")
        steps = [new_step("plan", "carbon", "plan"), new_step("review", "astra", "review")]
        steps.extend(new_step("execute-" + a, a, "execution") for a in workers)
        task = dict(id=task_id, createdAt=now(), brief=brief, workers=workers, autoAdvance=True, steps=steps)
        with self.lock:
            existing = self.tasks.get(task_id)
            if existing:
                if (existing["brief"] != brief or (existing.get("routingMode") == "auto") != auto_route
                        or (not auto_route and existing["workers"] != workers)):
                    raise Problem(409, "任务标识已用于另一份简报。")
                return render(existing)
            external = {row["id"]: row["name"] for row in self.slots.list()} if self.slots else {}
            if any(w not in WORKERS and w not in external for w in workers):
                raise Problem(400, "所选成员不存在，请刷新插槽。")
            task["workerNames"] = {w:external[w] for w in workers if w in external}
            if auto_route:
                task.update(routingMode="auto", routingCandidates=candidate_workers(brief, self.slots))
            self.enqueue(task)
            return render(task)

    def start(self, task):
        step = current(task)
        step.update(status="running", error="", updatedAt=now())
        self.save(task)
        self.busy = task["id"]
        self.stop_event = threading.Event()
        threading.Thread(target=self.run, args=(task["id"], self.stop_event), daemon=True).start()

    def finish(self, task, text):
        completed = current(task)
        completed.update(status="done", error="", result=text, updatedAt=now())
        if text.splitlines()[0].strip().casefold() == "[revise]":
            if completed["id"] == "review":
                index = task["steps"].index(completed) + 1
                task["steps"][index:index] = [new_step("revision", "carbon", "plan"), new_step("final-review", "astra", "review")]
            elif completed["id"] == "final-review":
                completed.update(status="error", blockedReview=text, error="复审仍报告实质阻碍。可查看具体原因，并在具备所需条件后重试。")
                return
        if (task.get("routingMode") == "auto" and completed["kind"] == "review"
                and text.splitlines()[0].strip().casefold() != "[revise]"):
            assign_review(task, completed, text)
        step = current(task)
        if task["autoAdvance"] and step and step["kind"] == "approval":
            step.update(status="done", error="", result="总裁在创建任务时已授权按审核方案自动派发。", updatedAt=now())

    def run(self, task_id, stop_event):
        try:
            while not stop_event.is_set():
                with self.lock:
                    task = copy.deepcopy(self.tasks[task_id])
                    step = current(task)
                    if step is None:
                        return
                    agent = step["agent"]
                candidate = None
                replaced = None
                try:
                    with cancellation.capture(stop_event):
                        capabilities = adapters.capabilities()
                        if task.get("routingMode") == "auto" and step["kind"] in ("plan", "review"):
                            task["routingCandidates"] = candidate_workers(task["brief"], self.slots, capabilities)
                        cap = ({"ready": False, "detail": "等待同事的连接器领取任务。"}
                               if agent in task.get("workerNames", {}) else capabilities.get(agent, {}))
                        if cap.get("ready"):
                            with project_coder.for_review(self.data_dir, task.get("revisionBase")):
                                output = adapters.run_agent(agent, prompt_for(task, step))
                            if isinstance(output, project_coder.CodeDelivery):
                                candidate = output.release
                                output = output.text
                            self.finish(task, check_text(output, "模型结果", 16000))
                            if agent == "codex" and step["status"] == "done":
                                replaced = task.pop("revisionBase", None)
                                if candidate:
                                    task["release"] = candidate
                        else:
                            unavailable = "error" if agent == "codex" else "handoff"
                            step.update(status=unavailable, error=cap.get("detail") or "等待连接该成员。", updatedAt=now())
                except cancellation.Cancelled:
                    return
                except (RuntimeError, Problem, releases.ReleaseCapacity) as exc:
                    step.update(status="error", error=str(exc)[:1000], updatedAt=now())
                except Exception:
                    step.update(status="error", error="本机模型调用失败。请检查登录状态后重试，或手动提交结果。", updatedAt=now())
                with self.lock:
                    if stop_event.is_set():
                        self.cleanup_release(candidate["id"] if candidate else None)
                        return
                    following = current(task)
                    advance = task["autoAdvance"] and following is not None and following["status"] == "pending"
                    if advance:
                        following.update(status="running", error="", updatedAt=now())
                    self.save(task)
                    self.cleanup_release(replaced)
                    if not advance:
                        return
        except Exception:
            with self.lock:
                step = current(self.tasks[task_id])
                if step and not stop_event.is_set():
                    step.update(status="error", error="保存运行结果失败，请检查数据目录后重试。", updatedAt=now())
                    self.version += 1
        finally:
            with self.lock:
                self.busy = None
                self.stop_event = None
                self.schedule_next()

    def cleanup_release(self, release_id):
        if release_id:
            try:
                releases.discard(self.root, release_id, data_dir=self.data_dir)
            except (OSError, ValueError, releases.ReleaseConflict):
                pass

    def expire_slot_leases(self):
        # Called under the workflow lock. A disconnected worker might never poll again.
        timestamp = time.time()
        for task in self.tasks.values():
            if task["id"] == self.busy:
                continue
            expired = {s["id"] for s in task["steps"] if s["status"] == "handoff"
                       and s.get("lease") and s["leaseUntil"] <= timestamp}
            if expired:
                item = copy.deepcopy(task)
                for step in item["steps"]:
                    if step["id"] in expired:
                        step.update(status="error", error="连接器未在十分钟内交付。可等待原连接器补交，或重试此步骤。", updatedAt=now())
                self.save(item)

    def claim_slot(self, agent):
        with self.lock:
            self.expire_slot_leases()
            for task in sorted(self.tasks.values(), key=lambda t: (t["createdAt"], t["id"])):
                if task["id"] == self.busy or agent not in task.get("workerNames", {}):
                    continue
                step = next(s for s in task["steps"] if s["agent"] == agent)
                if step["status"] != "handoff":
                    continue
                item = copy.deepcopy(task)
                step = next(s for s in item["steps"] if s["agent"] == agent)
                if step.get("lease"):
                    continue
                step.update(lease=str(uuid.uuid4()), leaseUntil=time.time()+600, updatedAt=now(),
                            error="同事的连接器已领取，正在执行。")
                self.save(item)
                return {"lease": step["lease"], "prompt": prompt_for(item, step)}
        return None

    def receive_slot(self, agent, data):
        if (set(data) not in ({"lease", "result"}, {"lease", "error"})
                or not isinstance(data["lease"], str) or len(data["lease"]) != 36):
            raise Problem(400, "交付字段无效。")
        success = "result" in data
        text = check_text(data["result"], "交付结果", 16000) if success else "同事电脑上的连接器报告执行失败。"
        with self.lock:
            for task in self.tasks.values():
                if task.get("stoppedAt"):
                    continue
                step = next((s for s in task["steps"] if s["agent"] == agent and s.get("lease") == data["lease"]), None)
                if not step:
                    continue
                if step.get("receipt"):
                    return {"ok": True}
                if task["id"] == self.busy:
                    raise Problem(503, "此任务正在保存，请重试交付。")
                if step["status"] not in ("handoff", "error"):
                    raise Problem(409, "该步骤已由其他方式交付。")
                item = copy.deepcopy(task)
                updated = next(s for s in item["steps"] if s["id"] == step["id"])
                updated.update(status="done" if success else "error", result=text if success else "",
                               error="" if success else text, updatedAt=now(), receipt=True)
                following = current(item)
                if following and following["status"] == "pending":
                    self.enqueue(item)
                else:
                    self.save(item)
                return {"ok": True}
        raise Problem(409, "领取凭证已失效。")

    def act(self, task_id, data):
        if type(data) is not dict or data.keys() - {"action", "result", "agent", "stepId", "feedback", "fresh"}:
            raise Problem(400, "步骤参数无效。")
        with self.lock:
            if task_id not in self.tasks:
                raise Problem(404, "找不到这项任务。")
            task = copy.deepcopy(self.tasks[task_id])
            step = current(task)
            if not step or data.get("stepId") != step["id"] or data.get("agent", step["agent"]) != step["agent"]:
                raise Problem(409, "当前步骤已经变化，请刷新任务。")
            if "fresh" in data and (data["fresh"] is not True or data.get("action") != "retry" or step["agent"] != "codex"):
                raise Problem(400, "仅开发步骤支持从正式版本重新生成。")
            if "feedback" in data:
                if data.get("action") != "retry" or step["kind"] != "execution" or step["agent"] != "codex":
                    raise Problem(400, "补充要求适用于重试开发步骤。")
                note = check_text(data["feedback"], "补充要求", 2000)
                if step["status"] != "error" and step.get("feedback") != note:
                    raise Problem(409, "当前开发步骤正在处理，无法更改要求。")
                step["feedback"] = note
            if step["status"] in ("running", "queued"):
                if data.get("action") in ("run", "retry"):
                    return render(task)
                raise Problem(409, "任务正由团队自动处理，进度将自动更新。")
            action = data.get("action")
            if step["agent"] in task.get("workerNames", {}):
                for field in ("lease", "leaseUntil", "receipt"):
                    step.pop(field, None)
            if step["kind"] == "approval":
                if action != "approve":
                    raise Problem(400, "此步骤需要总裁确认派发。")
                self.finish(task, "总裁已确认审核方案并派发。")
            elif action == "manual":
                self.finish(task, check_text(data.get("result"), "人工交回结果", 16000))
            elif action in ("run", "retry"):
                abandoned = task.pop("revisionBase", None) if data.get("fresh") else None
                step.update(status="pending")
                self.enqueue(task)
                self.cleanup_release(abandoned)
                return render(task)
            else:
                raise Problem(400, "该操作不适用于当前步骤。")
            following = current(task)
            if task["autoAdvance"] and following and following["status"] == "pending":
                self.enqueue(task)
            else:
                self.save(task)
            return render(task)

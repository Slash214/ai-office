"""Private pull-and-reply mailbox for a Dot using its connected local computer."""

import copy
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import time
from collections import deque
from datetime import datetime, timezone

from workflow import Problem, check_text, current, now, prompt_for


DOT_URL = re.compile(r"https://chatgpt\.com/dots/[a-zA-Z0-9~-]{1,160}/?\Z")


class DotBridge:
    def __init__(self, directory, workflow):
        self.directory = directory
        self.workflow = workflow
        path = directory / "dot-token"
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            self.token = path.read_text(encoding="ascii").strip()
        else:
            self.token = secrets.token_urlsafe(32)
            with os.fdopen(descriptor, "w", encoding="ascii") as output:
                output.write(self.token + "\n")
        if not re.fullmatch(r"[A-Za-z0-9_-]{40,64}", self.token):
            raise ValueError("Dot 本机密钥无效。")
        self.recent = deque()

    def connection(self):
        command = 'python -X utf8 "' + str(Path(__file__).resolve().with_name("office.py")) + '" dot'
        try:
            url = (self.directory / "dot-url").read_text(encoding="utf-8-sig").strip()
        except FileNotFoundError:
            url = ""
        try:
            seen = (self.directory / "dot-contact").stat().st_mtime
            connected = datetime.fromtimestamp(seen, timezone.utc).isoformat(timespec="seconds")
        except FileNotFoundError:
            connected = None
        return {
            "url": url if DOT_URL.fullmatch(url) else "https://chatgpt.com/",
            "connectedAt": connected,
            "invitation": (
                "请作为我的个人 Dot 加入【呵呵】AI工作室。请使用我已连接的 Windows 电脑，"
                "通过本机任务运行下列命令，领取一份明确分给 Dot 的工作。沟通和方案由你负责。\n\n"
                + command + " inbox\n\n"
                "若有工作，请阅读 prompt，在这个 Dot 会话和我讨论需要我决定的问题。完成后将你的最终答复"
                "保存到这台电脑上的临时 UTF-8 文本文件，换入回执中的 taskId、receipt 和文件路径后执行：\n"
                + command + ' reply <taskId> <receipt> --file "<文本文件路径>"\n\n'
                "没有工单就告诉我。只处理本次领取的一项；不用设置定时任务。"
            ),
        }

    def authorize(self, header):
        expected = ("Bearer " + self.token).encode("ascii")
        if not hmac.compare_digest(header.encode("latin-1"), expected):
            raise Problem(401, "Dot 本机凭据无效。")
        with self.workflow.lock:
            tick = time.monotonic()
            while self.recent and self.recent[0] <= tick - 60:
                self.recent.popleft()
            if len(self.recent) >= 30:
                raise Problem(429, "Dot 收件箱访问过于频繁，请稍后再试。")
            self.recent.append(tick)

    def receipt(self, task, step):
        fingerprint = "\n".join((task["id"], step["id"], step["updatedAt"], prompt_for(task, step)))
        return hmac.new(self.token.encode("ascii"), fingerprint.encode("utf-8"), hashlib.sha256).hexdigest()

    def inbox(self):
        with self.workflow.lock:
            (self.directory / "dot-contact").touch(mode=0o600)
            for task in sorted(self.workflow.tasks.values(), key=lambda t: (t["createdAt"], t["id"])):
                if self.workflow.busy == task["id"]:
                    continue
                for step in task["steps"]:
                    if step["id"] == "execute-dot" and step["agent"] == "dot" and step["status"] == "handoff":
                        return {"job": {"taskId": task["id"], "receipt": self.receipt(task, step),
                                        "prompt": prompt_for(task, step)}}
            return {"job": None}

    def reply(self, data):
        if type(data) is not dict or data.keys() != {"taskId", "receipt", "result"}:
            raise Problem(400, "请提交 Dot 工单、回执及结果。")
        task_id, receipt = data["taskId"], data["receipt"]
        if not isinstance(task_id, str) or not isinstance(receipt, str) or not re.fullmatch("[a-f0-9]{64}", receipt):
            raise Problem(400, "Dot 工单或回执格式错误。")
        result = check_text(data["result"], "Dot 答复", 16000)
        with self.workflow.lock:
            task = copy.deepcopy(self.workflow.tasks.get(task_id))
            if task and task.get("stoppedAt"):
                raise Problem(409, "工单已停止。")
            step = next((s for s in task["steps"] if s["id"] == "execute-dot" and s["agent"] == "dot"), None) if task else None
            if not step:
                raise Problem(404, "找不到这份 Dot 工单。")
            if step["status"] == "done" and step.get("dotReceipt") == receipt and step["result"] == result:
                return {"accepted": True}
            if self.workflow.busy == task_id or step["status"] != "handoff" or not hmac.compare_digest(self.receipt(task, step), receipt):
                raise Problem(409, "工单已变化，请重新领取 Dot 工单。")
            step.update(status="done", result=result, error="", dotReceipt=receipt, updatedAt=now())
            following = current(task)
            if following and following["status"] == "pending":
                self.workflow.enqueue(task)
            else:
                self.workflow.save(task)
            return {"accepted": True}

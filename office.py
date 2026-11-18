"""Report public activity categories or wrap a Codex / Gemini CLI invocation."""

import argparse
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib import error, parse, request
from adapters import DOT_MANUAL, MODELS, child_env, executable


AGENTS = MODELS
ACTIVITIES = ("general", "code", "research", "review", "writing", "planning", "media")
STATUSES = ("idle", "coding", "terminal", "browsing", "thinking", "needs_input", "error", "done")
DEFAULT_URL = "http://127.0.0.1:8765"


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def report_url():
    url = os.environ.get("OFFICE_URL", DEFAULT_URL).rstrip("/")
    parts = parse.urlsplit(url)
    if parts.username is not None or parts.password is not None or parts.query or parts.fragment:
        raise ValueError("OFFICE_URL 只接受办公室的访问地址。")
    local = parts.hostname == "localhost"
    if parts.hostname and not local:
        try:
            local = ipaddress.ip_address(parts.hostname).is_loopback
        except ValueError:
            pass
    if not parts.hostname or not (parts.scheme == "https" or parts.scheme == "http" and local):
        raise ValueError("远程 OFFICE_URL 需要 HTTPS，本机地址可使用 HTTP。")
    return url + "/api/report", local


def read_token():
    token = os.environ.get("OFFICE_REPORT_TOKEN", "").strip()
    if not token:
        default_dir = Path(__file__).resolve().parent / ".office-data"
        token_path = Path(os.environ.get("OFFICE_DATA_DIR", default_dir)) / "report-token"
        try:
            token = token_path.read_text(encoding="utf-8").strip()
        except OSError:
            raise ValueError("请先启动本地服务，或配置 OFFICE_REPORT_TOKEN。") from None
    if not token or not token.isascii() or any(not 33 <= ord(c) <= 126 for c in token):
        raise ValueError("办公室上报密钥格式有误。")
    return token


def report(agent, status, activity, collaborator=None):
    """Send no task text, command arguments, model output or logs to the server."""
    try:
        url, local = report_url()
        body = {"id": agent, "status": status, "activity": activity}
        if collaborator:
            body["collaborator"] = collaborator
        req = request.Request(
            url, json.dumps(body).encode("utf-8"),
            {"Content-Type": "application/json", "Authorization": "Bearer " + read_token()},
            method="POST",
        )
        handlers = [NoRedirect()]
        if local:
            handlers.append(request.ProxyHandler({}))
        client = request.build_opener(*handlers)
        for attempt in range(2):
            try:
                with client.open(req, timeout=3):
                    return True
            except error.HTTPError as exc:
                with exc:
                    delay = exc.headers.get("Retry-After", "2")
                    if exc.code != 429 or attempt or not delay.isdecimal() or int(delay) > 3:
                        raise ValueError(f"办公室返回 HTTP {exc.code}。") from None
                    time.sleep(int(delay) + 0.05)
    except ValueError as exc:
        print(f"[office] {exc}", file=sys.stderr)
    except (OSError, error.URLError):
        print("[office] 无法连接办公室，请检查服务和 OFFICE_URL。", file=sys.stderr)
    return False


def cli_command(agent):
    if agent == "dot":
        raise ValueError(DOT_MANUAL)
    if agent in ("astra", "codex"):
        cli = executable("codex")
        if cli:
            return [*cli, "--model", MODELS[agent]]
        raise ValueError("找不到 codex，请检查 PATH 或设置 OFFICE_CODEX_BIN。")
    agy = executable("agy")
    if agy:
        return [*agy, "--model", MODELS[agent]]
    raise ValueError("找不到 agy。请设置 OFFICE_AGY_BIN，或在 Antigravity 中完成任务。")


def dot_request(args):
    """Use the local Dot mailbox. Its credential and messages never follow redirects or proxies."""
    try:
        port = int(os.environ.get("OFFICE_PORT", "8765"))
        if not 1 <= port <= 65535:
            raise ValueError("OFFICE_PORT 超出范围。")
        origin = f"http://127.0.0.1:{port}"
        directory = Path(os.environ.get("OFFICE_DATA_DIR", Path(__file__).resolve().parent / ".office-data"))
        token = (directory / "dot-token").read_text(encoding="ascii").strip()
        data = {}
        if args.operation == "reply":
            if args.file:
                with Path(args.file).open(encoding="utf-8-sig") as source:
                    answer = source.read(16001)
            else:
                answer = sys.stdin.read(16001)
            if not answer.strip() or len(answer) > 16000:
                raise ValueError("Dot 答复应为 1 至 16000 字。")
            data = {"taskId": args.task_id, "receipt": args.receipt, "result": answer}
        req = request.Request(origin + "/api/dot/" + args.operation, json.dumps(data, ensure_ascii=False).encode("utf-8"), {
            "Origin": origin, "Content-Type": "application/json", "Authorization": "Bearer " + token,
        }, method="POST")
        client = request.build_opener(request.ProxyHandler({}), NoRedirect())
        with client.open(req, timeout=10) as response:
            print(json.dumps(json.load(response), ensure_ascii=False))
        return 0
    except error.HTTPError as exc:
        with exc:
            try:
                message = json.load(exc).get("error") or f"HTTP {exc.code}"
            except (ValueError, AttributeError):
                message = f"HTTP {exc.code}"
        print(f"[office] {message}", file=sys.stderr)
    except (OSError, ValueError, error.URLError) as exc:
        print(f"[office] 无法连接本机 Dot 收件箱或读取文件：{exc}", file=sys.stderr)
    return 1


def run_cli(agent, activity, cli_args):
    try:
        command = cli_command(agent)
    except ValueError as exc:
        print(f"[office] {exc}", file=sys.stderr)
        return 127
    if any(arg in {"-m", "--model"} or arg.startswith("--model=") for arg in cli_args):
        print("[office] 工位已指定模型，请移除重复的模型选项。", file=sys.stderr)
        return 2
    try:
        proc = subprocess.Popen([*command, *cli_args], env=child_env())
    except OSError as exc:
        print(f"[office] 无法启动 {agent} ({exc.errno})。", file=sys.stderr)
        return 126
    try:
        report(agent, "terminal", activity)
        while True:
            try:
                code = proc.wait(timeout=600)
                break
            except subprocess.TimeoutExpired:
                report(agent, "terminal", activity)
    except KeyboardInterrupt:
        # The child shares the foreground console and also receives Ctrl+C.
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.terminate()
            proc.wait()
        code = 130
    report(agent, "done" if code == 0 else "error", activity)
    return code if code >= 0 else 128 - code


def main():
    parser = argparse.ArgumentParser(description="AI 工作室状态上报")
    actions = parser.add_subparsers(dest="action", required=True)
    dot = actions.add_parser("dot", help="在个人 Dot 连接的本机领取或交回工作")
    dot_actions = dot.add_subparsers(dest="operation", required=True)
    dot_actions.add_parser("inbox", help="领取最早一份等待 Dot 的工单")
    reply = dot_actions.add_parser("reply", help="提交最终答复（默认从标准输入读取）")
    reply.add_argument("task_id")
    reply.add_argument("receipt")
    reply.add_argument("--file", help="包含最终答复的 UTF-8 文本文件")
    manual = actions.add_parser("report", help="上报一条状态")
    manual.add_argument("agent", choices=AGENTS)
    manual.add_argument("status", choices=STATUSES)
    manual.add_argument("activity", choices=ACTIVITIES, nargs="?", default="general")
    manual.add_argument("--with", dest="partner", choices=AGENTS, help="实际参与协作的另一位助手")
    run = actions.add_parser("run", help="运行已有的 CLI，并报告开始与退出")
    run.add_argument("agent", choices=AGENTS)
    run.add_argument("activity", choices=ACTIVITIES)
    run.add_argument("cli_args", nargs=argparse.REMAINDER, help="-- 后填写原有 CLI 参数")
    args = parser.parse_args()
    if args.action == "dot":
        return dot_request(args)
    if args.action == "report":
        if args.partner == args.agent:
            parser.error("协作对象应是另一位助手。")
        return 0 if report(args.agent, args.status, args.activity, args.partner) else 1
    cli_args = args.cli_args
    if cli_args[:1] == ["--"]:
        cli_args = cli_args[1:]
    return run_cli(args.agent, args.activity, cli_args)


if __name__ == "__main__":
    sys.exit(main())

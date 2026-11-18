"""Standalone AI office worker. Run: python office_connector.py --config cli.json"""

import argparse
from contextlib import contextmanager, nullcontext
import getpass
import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from urllib import error, parse, request
import uuid


MAX_RESULT = 16000
MAX_PIPE_BYTES = 4 * MAX_RESULT + 512
MAX_RESPONSE_BYTES = 768 * 1024
MODEL_ERROR = "本机模型执行失败或输出超出限制。"
INTERRUPTED = "上次执行中断，交付状态不确定。"


class ConnectorError(Exception):
    """Only keep local, non-sensitive messages in console output."""


class RemoteError(ConnectorError):
    def __init__(self, status=0):
        self.status = status
        super().__init__(f"请求返回 HTTP {status}。" if status else "暂时无法取得有效响应。")


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def loopback(host):
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def base_url(value):
    if not isinstance(value, str) or not value or not all(c.isprintable() and not c.isspace() for c in value):
        raise ConnectorError("请填写有效的服务地址。")
    try:
        addr = parse.urlsplit(value)
        host = addr.hostname
        port = addr.port
    except ValueError:
        raise ConnectorError("服务地址或端口无效。") from None
    if (not host or port == 0 or addr.username is not None or addr.password is not None
            or addr.fragment or addr.query or "\\" in value
            or not (addr.scheme == "https" or (addr.scheme == "http" and loopback(host)))):
        raise ConnectorError("服务地址必须使用 HTTPS 或本机回环 HTTP，且仅包含主机、端口和路径。")
    return value.rstrip("/")


def post(url, payload, token, timeout):
    handlers = [NoRedirect()]
    if loopback(parse.urlsplit(url).hostname):
        handlers.append(request.ProxyHandler({}))
    headers = {"Content-Type": "application/json; charset=utf-8", "Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    data = json.dumps(payload, ensure_ascii=False).encode("utf8")
    req = request.Request(url, data=data, headers=headers, method="POST")
    deadline = time.monotonic() + timeout
    try:
        with request.build_opener(*handlers).open(req, timeout=timeout) as response:
            raw = bytearray()
            while True:
                if time.monotonic() >= deadline or len(raw) > MAX_RESPONSE_BYTES:
                    raise RemoteError()
                chunk = response.read1(min(65536, MAX_RESPONSE_BYTES + 1 - len(raw)))
                if not chunk:
                    break
                raw.extend(chunk)
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise RemoteError()
            return value
    except error.HTTPError as exc:
        with exc:
            raise RemoteError(exc.code) from None
    except (OSError, ValueError, EOFError, RecursionError, http.client.HTTPException):
        raise RemoteError() from None


def load_config(path):
    try:
        with open(path, "rb") as stream:
            raw = stream.read(16385)
        if len(raw) > 16384:
            raise ValueError
        cfg = json.loads(raw.decode("utf-8-sig"))
    except (OSError, ValueError, RecursionError):
        raise ConnectorError("无法读取本地 JSON 配置。") from None
    if not isinstance(cfg, dict):
        raise ConnectorError("配置必须是 JSON 对象。")
    timeout = cfg.setdefault("timeout_seconds", 150)
    if type(timeout) is not int or not 1 <= timeout <= 540:
        raise ConnectorError("timeout_seconds 必须为 1 到 540 秒。")
    if cfg.get("type") == "cli":
        argv = cfg.get("argv")
        if not isinstance(argv, list) or not argv or any(not isinstance(x, str) or "\x00" in x for x in argv) or not argv[0]:
            raise ConnectorError("CLI 配置需要固定的 argv 字符串数组。")
        binary = shutil.which(argv[0])
        if (not binary or (os.name == "nt" and Path(binary).suffix.lower() != ".exe") or
                Path(binary).stem.lower() in {"cmd", "powershell", "pwsh", "bash", "sh", "zsh", "fish"}):
            raise ConnectorError("请为 argv 配置本机已安装的模型可执行文件。")
        cfg["argv"] = [str(Path(binary).resolve()), *argv[1:]]
        if "cwd" in cfg:
            folder = cfg["cwd"]
            if not isinstance(folder, str) or not folder.strip() or "\x00" in folder:
                raise ConnectorError("cwd 必须指向本机已有的项目目录。")
            folder = (Path(path).resolve().parent / Path(folder).expanduser()).resolve()
            if not folder.is_dir():
                raise ConnectorError("找不到 cwd 指定的本地项目目录。")
            cfg["cwd"] = str(folder)
    elif cfg.get("type") == "openai-compatible":
        if "api_key" in cfg or "token" in cfg:
            raise ConnectorError("模型密钥请存入环境变量，并在配置中填写 api_key_env。")
        cfg["base_url"] = base_url(cfg.get("base_url"))
        if not isinstance(cfg.get("model"), str) or not cfg["model"].strip():
            raise ConnectorError("请填写本机配置选择的模型 ID。")
        key_name = cfg.get("api_key_env")
        if key_name is not None and (
                not isinstance(key_name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key_name)
                or key_name.upper().startswith("OFFICE_") or not os.environ.get(key_name)):
            raise ConnectorError("请设置配置中指定的模型 API 密钥环境变量。")
    else:
        raise ConnectorError("type 应为 cli 或 openai-compatible。")
    return cfg


def kill_cli(proc):
    if os.name != "nt":
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    elif proc.poll() is None:
        try:
            subprocess.run([str(Path(os.environ["SystemRoot"]) / "System32" / "taskkill.exe"),
                            "/PID", str(proc.pid), "/T", "/F"], stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=3, creationflags=subprocess.CREATE_NO_WINDOW)
        except (OSError, subprocess.TimeoutExpired):
            pass
    if proc.poll() is None:
        proc.kill()


def run_cli(cfg, prompt):
    output = bytearray()
    failure = threading.Event()
    directory = nullcontext(cfg["cwd"]) if "cwd" in cfg else tempfile.TemporaryDirectory(prefix="office-worker-")
    with directory as folder, tempfile.TemporaryFile() as source:
        source.write((prompt + "\n").encode("utf8"))
        source.seek(0)
        proc = subprocess.Popen(
            cfg["argv"], cwd=folder, stdin=source, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            bufsize=0, env={k:v for k,v in os.environ.items() if not k.upper().startswith("OFFICE_")},
            start_new_session=os.name != "nt", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

        def collect():
            try:
                while len(output) <= MAX_PIPE_BYTES:
                    chunk = proc.stdout.read(min(8192, MAX_PIPE_BYTES + 1 - len(output)))
                    if not chunk:
                        return
                    output.extend(chunk)
                failure.set()
            except OSError:
                failure.set()

        reader = threading.Thread(target=collect, daemon=True)
        reader.start()
        deadline = time.monotonic() + cfg["timeout_seconds"]
        try:
            reader.join(cfg["timeout_seconds"])
            remaining = deadline - time.monotonic()
            if reader.is_alive() or failure.is_set() or remaining <= 0 or proc.wait(timeout=remaining):
                raise ConnectorError(MODEL_ERROR)
        finally:
            if reader.is_alive() or failure.is_set() or proc.poll() is None:
                kill_cli(proc)
            proc.stdout.close()
        return output.decode("utf8")


def model_result(cfg, prompt):
    if cfg["type"] == "cli":
        value = run_cli(cfg, prompt)
    else:
        # urllib's timeout applies to individual socket operations. Bound the whole
        # turn as well, including a provider that trickles bytes or resolves slowly.
        replies = []
        def call_model():
            try:
                data = post(cfg["base_url"] + "/chat/completions", {
                    "model": cfg["model"], "messages": [{"role": "user", "content": prompt}], "stream": False,
                }, os.environ.get(cfg.get("api_key_env", "")), cfg["timeout_seconds"])
                replies.append(data["choices"][0]["message"]["content"])
            except (RemoteError, IndexError, TypeError, KeyError):
                pass
        call = threading.Thread(target=call_model, daemon=True)
        call.start()
        call.join(cfg["timeout_seconds"])
        if call.is_alive() or not replies:
            raise ConnectorError(MODEL_ERROR)
        value = replies[0]
    if not isinstance(value, str) or len(value) > MAX_RESULT:
        raise ConnectorError(MODEL_ERROR)
    value = "".join(c for c in value if c.isprintable() or c in "\n\t").strip()
    if not value:
        raise ConnectorError(MODEL_ERROR)
    return value


@contextmanager
def keep_online(office, token, interval=15):
    stopped = threading.Event()

    def heartbeat():
        while not stopped.wait(interval):
            try:
                post(office + "/api/worker/heartbeat", {}, token, 5)
            except RemoteError:
                pass

    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stopped.set()


def default_state_dir():
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "HeheAIStudio" / "connector"
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "hehe-ai-office"


@contextmanager
def open_journal(folder, office, token):
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    key = hashlib.sha256((office + "\0" + token).encode("utf8")).hexdigest()[:32]
    with (folder / (key + ".lock")).open("a+b") as lock:
        lock.seek(0, os.SEEK_END)
        if lock.tell() == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ConnectorError("同一办公插槽已有一个本地连接器在运行。") from None
        db = sqlite3.connect(folder / (key + ".sqlite3"))
        try:
            db.execute("PRAGMA secure_delete=ON")
            db.execute("CREATE TABLE IF NOT EXISTS receipts (lease TEXT PRIMARY KEY, state TEXT, body TEXT)")
            yield db
        finally:
            db.close()


def deliver(db, office, token, lease, body):
    try:
        post(office + "/api/worker/result", {"lease": lease, **body}, token, 15)
    except RemoteError as exc:
        if exc.status not in (409, 410):
            raise
    with db:
        db.execute("UPDATE receipts SET state='done', body=NULL WHERE lease=?", (lease,))


def tick(db, office, token, cfg):
    # Commit a receipt before invoking a model. After a crash an unknown model invocation
    # becomes an explicit failure; only a saved delivery is ever replayed.
    old = db.execute("SELECT lease,body FROM receipts WHERE state!='done' LIMIT 1").fetchone()
    if old:
        lease, saved = old
        deliver(db, office, token, lease, json.loads(saved) if saved else {"error": INTERRUPTED})
        return True
    # A pending delivery can still be recovered if the model was uninstalled meanwhile.
    if isinstance(cfg, Path):
        cfg = load_config(cfg)
    data = post(office + "/api/worker/claim", {}, token, 15)
    if "job" in data and data["job"] is None:
        return False
    job = data.get("job")
    if not isinstance(job, dict) or not isinstance(job.get("lease"), str):
        raise ConnectorError("服务器返回了无效的任务租约。")
    lease = job["lease"]
    try:
        if str(uuid.UUID(lease)) != lease:
            raise ValueError
    except ValueError:
        raise ConnectorError("服务器返回了无效的任务租约。") from None
    with db:
        created = db.execute("INSERT OR IGNORE INTO receipts VALUES(?,'running',NULL)", (lease,)).rowcount
    if not created:
        return False
    try:
        prompt = job.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 65000:
            raise ConnectorError(MODEL_ERROR)
        with keep_online(office, token):
            body = {"result": model_result(cfg, prompt)}
    except (ConnectorError, OSError, ValueError, TypeError, IndexError, KeyError, subprocess.SubprocessError):
        body = {"error": MODEL_ERROR}
    with db:
        db.execute("UPDATE receipts SET state='pending',body=? WHERE lease=?", (json.dumps(body, ensure_ascii=False), lease))
    deliver(db, office, token, lease, body)
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description="用本机的模型领取办公插槽任务并交回结果。")
    parser.add_argument("--url", default="http://127.0.0.1:8766", help="办公室 Worker 服务地址")
    parser.add_argument("--config", required=True, type=Path, help="本机模型 JSON 配置")
    parser.add_argument("--once", action="store_true", help="尝试领取或补交一次后退出")
    parser.add_argument("--state-dir", type=Path, default=default_state_dir(), help="本机交付记录目录")
    args = parser.parse_args(argv)
    try:
        office = base_url(args.url)
        token = os.environ.get("OFFICE_SLOT_TOKEN") or getpass.getpass("办公插槽凭据（输入隐藏）: ")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", token):
            raise ConnectorError("办公插槽凭据格式无效。")
        with open_journal(args.state_dir, office, token) as db:
            print("办公连接器已启动。", flush=True)
            while True:
                try:
                    worked = tick(db, office, token, args.config)
                except RemoteError as exc:
                    if args.once or (exc.status and exc.status < 500 and exc.status not in (408, 429)):
                        raise
                    print("连接暂不可用，稍后重试。", file=sys.stderr, flush=True)
                    time.sleep(10)
                    continue
                if worked:
                    print("本次任务交接已结束。", flush=True)
                if args.once:
                    return 0
                time.sleep(1 if worked else 5)
    except KeyboardInterrupt:
        return 0
    except ConnectorError as exc:
        print(str(exc), file=sys.stderr)
    except (EOFError, OSError, sqlite3.Error):
        print("无法打开本机凭据或交付记录。", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())

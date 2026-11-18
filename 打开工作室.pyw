"""Open the local office or launch it in the background on Windows."""

import ctypes
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

from workflow import NAMES

ROOT = Path(__file__).resolve().parent
HOST = "127.0.0.1"


def is_office_ready(port):
    # On Windows a closed loopback port can time out instead of rejecting a connection.
    with socket.socket() as probe:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            probe.bind((HOST, port))
        except OSError:
            pass
        else:
            return False
    connection = http.client.HTTPConnection(HOST, port, timeout=1)
    try:
        connection.request("GET", "/api/status")
        response = connection.getresponse()
        if response.status == 200 and (response.getheader("Server") or "").strip() == "Office":
            data = json.loads(response.read(16384))
            if {row["id"] for row in data["agents"]} == set(NAMES):
                return True
    except ConnectionRefusedError:
        return False
    except (OSError, http.client.HTTPException, UnicodeError, ValueError, TypeError, KeyError):
        pass
    finally:
        connection.close()
    raise RuntimeError(f"本机端口 {port} 正在使用，未能确认是这个工作室。请检查该端口上的程序后再试。")


def ensure_office(port):
    if is_office_ready(port):
        return
    server = ROOT / "server.py"
    if not server.is_file():
        raise RuntimeError("找不到 server.py。请将启动入口留在完整的工作室目录内。")
    executable = Path(sys.executable)
    if executable.name.lower() == "pythonw.exe":
        executable = executable.with_name("python.exe")
    process = subprocess.Popen(
        [str(executable), "-B", str(server)], cwd=ROOT,
        env={**os.environ, "OFFICE_HOST": HOST, "OFFICE_PORT": str(port)},
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            if is_office_ready(port):
                return process
        except RuntimeError:
            # The socket can be listening before saved tasks have finished loading.
            pass
        if process.poll() is not None:
            raise RuntimeError("工作室启动失败。请在工作室文件夹打开终端，运行 python -B server.py 查看原因。")
        time.sleep(0.15)
    raise RuntimeError("服务仍在启动。稍后再次双击即可重新连接，也可在本地终端查看服务状态。")


def main():
    try:
        port = int(os.environ.get("OFFICE_PORT", "8765"))
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        ctypes.windll.user32.MessageBoxW(None, "OFFICE_PORT 应为 1 到 65535 之间的端口号。", "【呵呵】AI工作室", 0x10)
        return
    url = f"http://{HOST}:{port}/"
    try:
        ensure_office(port)
        try:
            os.startfile(url)
        except OSError as exc:
            raise RuntimeError(f"工作室已经就绪。请在浏览器打开 {url}") from exc
    except (OSError, RuntimeError) as exc:
        ctypes.windll.user32.MessageBoxW(None, str(exc), "【呵呵】AI工作室", 0x10)


if __name__ == "__main__":
    if sys.argv[1:] == ["--ensure-server"]:
        # The desktop EXE owns its window and reports startup errors itself.
        try:
            ensure_office(int(os.environ.get("OFFICE_PORT", "8765")))
        except (ValueError, OSError, RuntimeError) as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(1)
    else:
        main()

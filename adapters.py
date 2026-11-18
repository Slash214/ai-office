"""Named local CLI adapters. All subprocess commands and model IDs are selected here."""

from functools import lru_cache
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import cancellation
import project_coder


ROOT = Path(__file__).resolve().parent
GOOGLE = {name: f"gemini-4-{name}-medium" for name in ("carbon", "argon", "hydrogen")}
MODELS = {**GOOGLE, "astra": "gpt-6.2-astra", "codex": project_coder.MODEL, "dot": None}
DOT_MANUAL = "等待你的个人 Dot 领取工单。在 Dot 会话使用入驻指令，答复会回到任务台。"
NO_TOOLS = (
    "shell_tool", "unified_exec", "apps", "plugins", "hooks", "browser_use",
    "in_app_browser", "computer_use", "image_generation", "view_image",
    "code_mode", "multi_agent", "multi_agent_v2", "goals",
)
AGY_SETTINGS = {
    "toolPermission": "strict", "allowNonWorkspaceAccess": False, "enableTerminalSandbox": True,
    "permissions": {"deny": ["command(*)", "unsandboxed(*)", "read_file(*)", "write_file(*)",
                             "read_url(*)", "execute_url(*)", "mcp(*)"]},
}


@lru_cache(maxsize=12)
def desktop_version(path, modified):
    version = metadata([str(path)], "--version", timeout=3).strip()
    match = re.fullmatch(r"codex-cli (\d+)\.(\d+)\.(\d+)(?:-([\w.-]+))?(?:\+[\w.-]+)?", version)
    if not match:
        return ()
    major, minor, patch, prerelease = match.groups()
    # Stable releases take precedence over prereleases of the same version.
    parts = tuple((0, int(part)) if part.isdigit() else (1, part)
                  for part in (prerelease or "").split("."))
    return int(major), int(minor), int(patch), not prerelease, parts


def installed_windows_cli(name):
    local = os.environ.get("LOCALAPPDATA")
    if os.name != "nt" or not local:
        return None
    if name == "agy":
        path = Path(local) / "agy" / "bin" / "agy.exe"
        return path if path.is_file() else None
    base = Path(local) / "OpenAI" / "Codex" / "bin"
    builds = []
    for path in base.glob("*/codex.exe"):
        if re.fullmatch(r"[0-9a-f]{16}", path.parent.name, re.I):
            try:
                version = desktop_version(path, path.stat().st_mtime_ns)
            except OSError:
                continue
            if version:
                builds.append((version, path))
    return max(builds)[1] if builds else None


def executable(name):
    override = os.environ.get("OFFICE_" + name.upper() + "_BIN")
    suffix = ".exe" if os.name == "nt" else ""
    bundled = ROOT / ".office-tools" / (name + suffix)
    found = override or shutil.which(name) or installed_windows_cli(name) or bundled
    path = Path(found).expanduser().resolve()
    if not path.is_file():
        return None
    if os.name != "nt" or path.suffix.lower() == ".exe":
        return [str(path)]

    # Windows npm shims are batch files. Invoke the package's actual JS entry
    # so user prompt characters never go through cmd.exe.
    package = {"codex": "@openai/codex"}.get(name)
    if package is None:
        return None
    prefix = path.parent
    modules = prefix.parent if prefix.name.lower() == ".bin" else prefix / "node_modules"
    package_dir = modules / package
    try:
        manifest = json.loads((package_dir / "package.json").read_text(encoding="utf-8"))
        entry = manifest["bin"]
        if isinstance(entry, dict):
            entry = entry[name]
        script = (package_dir / entry).resolve()
        if manifest["name"] != package or not script.is_file() or not script.is_relative_to(package_dir.resolve()):
            return None
    except (KeyError, TypeError, ValueError, OSError):
        return None
    node = str(prefix / "node.exe") if (prefix / "node.exe").is_file() else shutil.which("node.exe")
    return [node, str(script)] if node else None


def child_env():
    return {k: v for k, v in os.environ.items() if not k.upper().startswith("OFFICE_")}


def metadata(exe, *args, timeout=8):
    """Query CLI metadata without a prompt. Never return a raw error to the page."""
    if not exe:
        return ""
    try:
        p = cancellation.run(
            [*exe, *args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, timeout=timeout, env=child_env(), cwd=ROOT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return p.stdout.decode("utf-8", "replace") if p.returncode == 0 else ""


@lru_cache(maxsize=1)
def _capabilities(bucket):
    codex = executable("codex")
    signed_in = any(line.lower().startswith("logged in") for line in metadata(codex, "login", "status").splitlines())
    catalog = set()
    if signed_in:
        try:
            rows = json.loads(metadata(codex, "debug", "models")).get("models", [])
            catalog = {item.get("slug") for item in rows if isinstance(item, dict)}
        except (ValueError, AttributeError):
            pass
    astra = MODELS["astra"] in catalog
    items = {
        "codex": {"ready": project_coder.MODEL in catalog and bool(shutil.which("node")), "detail":
                  "本机 Codex · " + project_coder.MODEL + " · 工作室源码开发与沙箱测试"
                  if project_coder.MODEL in catalog and shutil.which("node") else
                  "请安装 Node.js，并登录包含 " + project_coder.MODEL + " 的本机 Codex CLI。"},
        "astra": {"ready": astra, "detail": (
            MODELS["astra"] + " · Codex CLI" if astra else
            "请在本机运行 codex login 并确认模型目录包含 gpt-6.2-astra。"
        )},
        "dot": {"ready": False, "detail": DOT_MANUAL},
    }
    agy = executable("agy")
    catalog_text = metadata(agy, "models") if agy else ""
    available = set(re.findall(r"(?<![\w.-])gemini-4-[\w-]+(?![\w.-])", catalog_text.lower()))
    session_settings = "--settings " in metadata(agy, "--help") if agy else False
    for agent, model in GOOGLE.items():
        listed = model in available
        ready = bool(agy and listed and session_settings)
        detail = model + " · Antigravity CLI"
        if not agy:
            detail = "未找到 agy。可在 Antigravity 中选择该模型，执行后回填。"
        elif not listed:
            detail = "请登录 agy 并用 agy models 核对当前账户的 " + model + "。"
        elif not session_settings:
            detail = "请更新 agy 以支持 --settings 会话级工具限制，或在桌面回填结果。"
        items[agent] = {"ready": ready, "detail": detail}
    return items


def capabilities():
    return _capabilities(int(time.monotonic() // 60))


def run_agent(agent_id, prompt):
    cancellation.checkpoint()
    info = capabilities().get(agent_id)
    if not info or not info["ready"]:
        raise RuntimeError(info["detail"] if info else "未知成员。")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 65000:
        raise RuntimeError("任务正文为空或超过 65000 个字符。")
    name = "codex" if agent_id in ("astra", "codex") else "agy"
    cli = executable(name)
    if not cli:
        raise RuntimeError(f"找不到 {name}。")
    if agent_id == "codex":
        return project_coder.run(cli, ROOT, prompt)
    with tempfile.TemporaryDirectory(prefix="office-turn-") as workdir:
        if name == "codex":
            disable = [arg for feature in NO_TOOLS for arg in ("--disable", feature)]
            output = Path(workdir) / "answer.txt"
            argv = [*cli, "--no-daemon", "-a", "never", *disable, "exec",
                    "--ignore-user-config", "--ignore-rules", "--ephemeral", "--skip-git-repo-check",
                    "--sandbox", "read-only", "-c", 'web_search="disabled"', "-m", MODELS[agent_id],
                    "--output-last-message", str(output), "-"]
            payload = prompt
        else:
            argv = [*cli, "--model", MODELS[agent_id], "--settings", json.dumps(AGY_SETTINGS), "--sandbox",
                    "--disable-slash-commands", "--print-timeout", "175s",
                    "--input-format", "stream-json", "--output-format", "stream-json"]
            payload = json.dumps({"event": "user", "message": {"content": prompt}}) + "\n"
        try:
            with tempfile.TemporaryFile() as transcript:
                result = cancellation.run(
                    argv, input=payload.encode("utf-8"), cwd=workdir, env=child_env(),
                    stdout=transcript if name == "agy" else subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, timeout=180,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                if result.returncode:
                    raise RuntimeError(f"{name} 未成功完成（退出码 {result.returncode}）。请检查登录、模型权限和额度。")
                if name == "codex":
                    if not output.is_file() or output.stat().st_size > 262144:
                        raise RuntimeError("Codex 未返回可用的最终文本。")
                    answer = output.read_text(encoding="utf-8").strip()
                else:
                    if transcript.tell() > 8 * 1024 * 1024:
                        raise RuntimeError("Antigravity 返回的数据超出上限。")
                    transcript.seek(0)
                    answer = agy_answer(transcript, MODELS[agent_id])
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"{name} 超过三分钟未返回，可在本地会话继续。") from None
        except (OSError, ValueError, AttributeError):
            raise RuntimeError(f"无法从 {name} 读取有效结果。") from None
    if not isinstance(answer, str) or not answer.strip():
        raise RuntimeError(f"{name} 没有返回最终文本。")
    return answer.strip()


def agy_answer(transcript, expected):
    answer = ""
    for line in transcript:
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get("event") == "init":
            actual = event.get("init", {}).get("model")
            if actual and actual not in {expected, expected.removesuffix("-medium")}:
                raise RuntimeError("Antigravity 选择的模型与当前工位不一致。")
        if event.get("event") == "result":
            turn = event.get("result", {})
            if turn.get("status") != "SUCCESS":
                raise RuntimeError("Antigravity 未能完成任务，请检查模型权限和额度。")
            answer = turn.get("response", "")
    return answer

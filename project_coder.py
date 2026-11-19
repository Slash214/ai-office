"""Run a local Codex engineering turn against a staged copy of this office."""

import hashlib
import json
import os
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import re
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import cancellation


MODEL = "gpt-6.2-sol"
_REVIEW = ContextVar("office_code_review", default=None)


@dataclass(frozen=True)
class CodeDelivery:
    text: str
    release: dict


@contextmanager
def for_review(data_dir, previous=None, on_progress=None):
    token = _REVIEW.set((data_dir, previous, on_progress))
    try:
        yield
    finally:
        _REVIEW.reset(token)


def progress(stage, **fields):
    context = _REVIEW.get()
    if context and context[2]:
        context[2](stage, fields)


def changed_excerpt(old, new):
    """Sample the first actual difference, including pure deletions."""
    before, after = old.splitlines(), new.splitlines()
    first = 0
    while first < min(len(before), len(after)) and before[first] == after[first]:
        first += 1
    end_old, end_new = len(before), len(after)
    while end_old > first and end_new > first and before[end_old-1] == after[end_new-1]:
        end_old -= 1
        end_new -= 1
    rows = after[first:min(first+5, end_new)] or before[first:min(first+5, end_old)]
    sign = '+' if end_new > first else '−'
    # The screen only carries a short local excerpt, never prompts or raw CLI logs.
    sensitive = r'(?i)(?:password|passwd|secret|credential|api[_-]?key|token|authorization|private.key|sk-[\w-]{12,}|gh[pousr]_|bearer\s|://[^/\s]+@)'
    return [sign + ' ' + ('•••' if re.search(sensitive, row) else
                          ''.join(ch for ch in row[:110] if ch.isprintable() or ch == '\t'))
            for row in rows]
PUBLISH_LOCK = threading.Lock()
SOURCE_DIRS = {"public", "native", "connectors"}
SOURCE_TYPES = {".py", ".pyw", ".js", ".mjs", ".css", ".html", ".md", ".json", ".svg",
                ".cs", ".manifest", ".ps1", ".cmd", ".png", ".jpg", ".webp", ".gif", ".ico", ".txt"}
INPUT_DIRS = {Path("public/vendor"), Path("native/webview2")}
EXCLUDE_FEATURES = ("shell_tool", "unified_exec", "view_image", "apps", "plugins", "hooks", "browser_use", "in_app_browser", "computer_use",
                    "image_generation", "multi_agent", "multi_agent_v2", "goals", "code_mode")
INSTRUCTIONS = """你是这座 AI 工作室的本机 Codex 开发员工。你通过宿主的文件编辑接口修改工作室。
根据总裁目标、Carbon 规划和 Astra 分工，给出真正可应用的修改。使用编辑接口，无需调用系统工具。
action=read 时，只列出还需要读取的源文件（每次最多8个）。宿主会附上新文件，并尽量保留先前源码。当前消息已有足够源码时，直接使用 action=deliver。
action=deliver 时，在 edits 中给出所有修改。对指名的单个小文件（尤其是 SVG、头像或样式模块），优先用一条整文件替换：将该文件标题提供的 office-sha256: 后附完整 64 位哈希的整串照抄到 before，after 填最终完整源码，不含标题、Markdown 围栏、说明或省略号。
需要局部修改时使用原文替换。path 是相对文件名；before 是该文件中唯一匹配的原文，after 是替换后的原文；
新建文件时 before 为空、after 为完整内容。只要求检查或跑测试可以交付空 edits 并说明原因。
严格保留缩进，尽量只替换必要的小片段，不要给出仅供参考的代码。保留现有测试和未涉及的行为。
summary 用中文概述改动与验收方式。宿主会实际应用、执行测试并发布通过的文件。
"""


def is_link(path):
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def files(root):
    """The manifest contains source and checked-in dependencies, never private state."""
    result = {}
    for parent, dirs, names in os.walk(root, followlinks=False):
        folder = Path(parent)
        rel = folder.relative_to(root)
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("__pycache__", "node_modules")
                   and (rel.parts or d in SOURCE_DIRS)]
        for d in dirs:
            if is_link(folder / d):
                raise RuntimeError("工程中存在目录链接，请使用普通源文件。")
        for name in names:
            path = folder / name
            if name.startswith(".") or (path.suffix.lower() not in SOURCE_TYPES and rel not in INPUT_DIRS):
                continue
            if not rel.parts and path.suffix.lower() not in (".py", ".pyw", ".mjs", ".md"):
                continue
            info = path.lstat()
            if is_link(path) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise RuntimeError("工程中存在非普通源文件。")
            if info.st_size > 16*1024*1024 or len(result) >= 2048:
                raise RuntimeError("单个工程文件或文件数量超出工作副本上限。")
            result[rel / name] = hashlib.sha256(path.read_bytes()).digest()
    return result


def copy_source(root, dest, manifest):
    for relative in manifest:
        target = dest / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / relative, target)
    if files(dest) != manifest:
        raise RuntimeError("复制期间源文件发生变化，请重试。")


def process_env(scratch):
    safe = {"path","pathext","systemroot","windir","comspec","systemdrive","userprofile","username",
            "localappdata","appdata","programdata","programfiles","programfiles(x86)","commonprogramfiles",
            "home","lang","lc_all","codex_home","https_proxy","http_proxy","no_proxy","ssl_cert_file"}
    env = {k:v for k,v in os.environ.items() if k.lower() in safe}
    return dict(env, TMP=str(scratch), TEMP=str(scratch), TMPDIR=str(scratch), PYTHONUTF8="1",
                PYTHONDONTWRITEBYTECODE="1", NO_COLOR="1")


def execute(args, work, env, timeout, payload=None):
    with tempfile.TemporaryFile() as log:
        try:
            run = cancellation.run(args, cwd=work, env=env,
                                 input=payload.encode("utf8") if payload is not None else b"",
                                 stdout=log, stderr=subprocess.STDOUT, timeout=timeout,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            raise RuntimeError("Codex 或测试超时。未发布本次修改。") from None
        log.seek(max(0,log.tell()-4096))
        return run.returncode, log.read().decode("utf8","replace").strip()


EDIT_SCHEMA = {"type":"object","additionalProperties":False,"required":["action","reads","edits","summary"],
               "properties":{"action":{"type":"string","enum":["read","deliver"]},
                             "reads":{"type":"array","items":{"type":"string"}},
                             "edits":{"type":"array","items":{"type":"object","additionalProperties":False,
                                     "required":["path","before","after"],"properties":{
                                         key:{"type":"string"} for key in ("path","before","after")}}},
                             "summary":{"type":"string"}}}


def apply_edits(work, edits):
    updates = {}
    if not isinstance(edits,list) or len(edits)>100:
        raise ValueError("编辑列表格式不正确")
    for edit in edits:
        name, old, new = (edit[k] for k in ("path","before","after"))
        if not all(isinstance(s,str) for s in (name,old,new)) or len(name)>240 or len(old)+len(new)>400000:
            raise ValueError("编辑内容或文件名不符合格式")
        from pathlib import PurePosixPath
        p=PurePosixPath(name)
        if (not p.parts or p.is_absolute() or "\\" in name or ":" in name or p.as_posix()!=name or
                any(part.startswith(".") or part.endswith((" ",".")) or Path(part).is_reserved() for part in p.parts)
                or p.suffix.lower() not in SOURCE_TYPES or (len(p.parts)>1 and p.parts[0] not in SOURCE_DIRS)
                or (len(p.parts)==1 and p.suffix.lower() not in (".py",".pyw",".mjs",".md"))
                or any(part in Path(name).parents for part in INPUT_DIRS)):
            raise ValueError("文件不在可编辑的工作室源码中")
        target=work.joinpath(*p.parts)
        exists = target in updates or target.exists()
        if target in updates:
            content=updates[target]
        elif exists:
            content=target.read_bytes()
        else:
            content=b""
        old_raw=old.replace("\r\n","\n").encode()
        new_raw=new.replace("\r\n","\n").encode()
        if b"\r\n" in content:
            old_raw=old_raw.replace(b"\n",b"\r\n")
            new_raw=new_raw.replace(b"\n",b"\r\n")
        if old.startswith("office-sha256:"):
            digest = old.removeprefix("office-sha256:")
            if not exists or not re.fullmatch(r"[a-fA-F0-9]{64}", digest) or hashlib.sha256(content).hexdigest()!=digest.lower():
                raise ValueError("整文件 SHA256 校验未匹配 "+name+"。请使用最新文件标题里的完整校验串。")
            updates[target] = new_raw
            continue
        if (old_raw and content.count(old_raw)!=1) or (not old_raw and exists and content):
            count = content.count(old_raw) if old_raw else 0
            raise ValueError(f"{name} 的 before 匹配到 {count} 处。请直接使用文件标题的校验串和完整源码。")
        updates[target] = content.replace(old_raw,new_raw,1) if old_raw else new_raw
    for path,data in updates.items():
        old = path.read_bytes() if path.is_file() else b""
        replace_file(path,data)
        if old != data:
            relative = path.relative_to(work).as_posix()
            lines = []
            if path.suffix.lower() in {".py", ".pyw", ".js", ".mjs", ".cs", ".css", ".html", ".svg"}:
                lines = changed_excerpt(old.decode("utf8", "replace"), data.decode("utf8", "replace"))
            progress("edited", path=relative, lines=lines)


def code(cli, root, work, env, node, prompt):
    scratch=work/".scratch"
    answer=scratch/"answer.json"
    schema=scratch/"edit-schema.json"
    schema.write_text(json.dumps(EDIT_SCHEMA),encoding="utf8")
    disable = [arg for feature in EXCLUDE_FEATURES for arg in ("--disable",feature)]
    args = [*cli, "--no-daemon", "-a", "never", *disable, "exec", "--ignore-user-config", "--ignore-rules",
            "--ephemeral","--skip-git-repo-check","--sandbox","read-only",
            "-c",'web_search="disabled"', "-c",'model_reasoning_effort="medium"',
            "-m", MODEL, "--output-schema",str(schema),"-o", str(answer), "-"]
    manifest=files(work)
    paths={p.as_posix():p for p in manifest if p.suffix.lower() not in (".png",".jpg",".webp",".gif",".ico")
           and not any(part in p.parents for part in INPUT_DIRS)}
    header=INSTRUCTIONS+"\n总裁的任务和团队分工\n"+prompt+"\n源码索引\n"+"\n".join(sorted(paths))
    # Start with explicitly named or small, clearly relevant source. The model can ask for any indexed file.
    named=[k for k in paths if k in prompt]
    requested=list(dict.fromkeys(named+[k for k in paths if len(paths[k].stem)>3 and paths[k].stem.lower() in prompt.lower()]))[:8]
    retained = []
    # A small ES module's caller supplies the public API and roster context in the first turn.
    if len(named)==1 and paths[named[0]].suffix==".js":
        module=paths[named[0]]
        for name, relative in paths.items():
            if relative.parent!=module.parent or relative.suffix!=".js" or name in requested:
                continue
            caller=work/relative
            if caller.stat().st_size<=32768 and any(quote+"./"+module.name+quote in caller.read_text("utf8") for quote in ("'",'"')):
                retained.append(name)
                if len(retained)==2: break
    note=""
    last_issue=""
    for turn in range(6):
        if turn==5:
            note+="\n这是最后一轮。若已取得所需源码请直接 deliver；小文件可用标题的 SHA256 整体替换。"
        context=[]
        visible=[]
        remaining=500000-len(header)-len(note)-1
        if remaining<0:
            raise RuntimeError("所选源码超过单次上下文容量，请拆分本次开发任务。")
        # Each Codex call is ephemeral. Keep previous reads in its actual packet, newest first.
        for name in dict.fromkeys([*requested, *retained]):
            if len(visible)==8:
                break
            digest=manifest[paths[name]].hex()
            content="\n文件 "+name+"\n整文件校验串 office-sha256:"+digest+"\n源码开始\n"+(work/paths[name]).read_text("utf8")
            if len(content)>remaining:
                if name in requested:
                    raise RuntimeError("所选源码超过单次上下文容量，请拆分本次开发任务。")
                continue
            remaining-=len(content)
            visible.append(name)
            context.append(content)
        packet=header+"\n"+"".join(context)+note
        progress("reading" if visible else "planning", path=visible[0] if visible else "", lines=[])
        answer.unlink(missing_ok=True)
        status,_=execute(args,scratch,env,600,packet)
        if status or not answer.is_file() or answer.stat().st_size>768000:
            raise RuntimeError(f"本机 Codex 未交付结构化响应（退出码 {status}），正式源码保持原状。")
        try:
            message=json.loads(answer.read_text("utf8"))
            if message["action"]=="read":
                names=message["reads"]
                if not isinstance(names,list) or not 1<=len(names)<=8 or any(n not in paths for n in names):
                    raise ValueError("只可选择索引内的 1 至 8 个源码文件")
                requested=list(dict.fromkeys(names))
                retained=visible
                note="" if any(name not in visible for name in requested) else (
                    "\n你刚请求的文件已在本条消息的「文件」段内，请直接使用所附原文交付，或只请求缺少的文件。")
                continue
            if message["action"]!="deliver": raise ValueError("未知操作")
            apply_edits(work,message["edits"])
            return str(message["summary"])[:7000]
        except (ValueError,TypeError,KeyError,UnicodeError) as exc:
            last_issue=str(exc)[:350]
            note="\n上次编辑未应用。请修正后重新交付全部编辑。原因："+last_issue
    message="Codex 在六轮源码读取及编辑内未生成可应用的结果。"
    raise RuntimeError(message+(" 最近一次校验错误："+last_issue if last_issue else ""))


# The supervisor supplies this harness on the command line, outside the candidate source.
# All Python imports, JavaScript tests and candidate subprocesses execute inside Codex's OS sandbox.
CHECKS = """import os,pathlib,subprocess,sys
root=pathlib.Path.cwd()
node=sys.argv[1]
for path in sorted([*root.glob('*.py'), *root.glob('*.pyw')]):
    compile(path.read_bytes(), str(path),'exec')
print('Python syntax OK',flush=True)
for path in sorted((root/'public').rglob('*.js')):
    if 'vendor' not in path.parts: subprocess.run([node,'--check',str(path)],check=True)
print('JavaScript syntax OK',flush=True)
suite=[p.name for p in sorted(root.glob('test_*.py'))]
if not suite: sys.exit('Missing Python tests')
subprocess.run([sys.executable,'-B','-m','unittest','-q',*suite],check=True)
js=[p.name for p in sorted(root.glob('test_*.mjs'))]
if not js: sys.exit('Missing Node tests')
subprocess.run([node,'--test',*js],check=True)
"""


def verify(cli, root, work, env, node):
    args = [*cli, "sandbox", "-C", str(work), "-P", ":workspace"]
    if os.name=="nt":
        args+=["-c",'windows.sandbox="elevated"']
    args += ["--", sys.executable, "-I", "-B", "-c", CHECKS, node]
    status, output = execute(args, work, env, 300)
    if status:
        # The owner needs a concrete reason, never model prompts or environment variables.
        lines = [s.strip() for s in output.splitlines() if s.strip()]
        reasons = [s for s in lines if s.startswith(("Error:", "windows sandbox failed", "FAIL:", "ERROR:", "AssertionError", "PermissionError", "ModuleNotFoundError", "FileNotFoundError"))]
        detail = (reasons[0] if reasons else (lines[-1] if lines else "未收到测试输出"))[:220]
        raise RuntimeError(f"隔离验证失败（退出码 {status}），未发布修改。{detail}")
    lines = [s for s in output.splitlines() if s.startswith(("Ran ", "ℹ tests ", "# tests ", "ℹ pass ", "# pass "))]
    return "Python 语法、JavaScript 语法、Python unittest、Node 测试均通过（退出码 0）。" + "\n" + "\n".join(lines)


def replace_file(target, data):
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".office-change-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name,target)
    finally:
        Path(name).unlink(missing_ok=True)


def publish(root, candidate, before, after):
    changed = sorted(key for key in before.keys() | after.keys() if before.get(key) != after.get(key))
    if any(any(part in p.parents for part in INPUT_DIRS) for p in changed):
        raise RuntimeError("候选版本修改了随附的第三方依赖。未发布修改。")
    with PUBLISH_LOCK:
        if files(root) != before:
            raise RuntimeError("生成或测试过程中正式源码已有新修改。本次候选版本未覆盖，请重新执行。")
        applied = []
        try:
            for rel in changed:
                path = root / rel
                original = path.read_bytes() if rel in before else None
                data = (candidate / rel).read_bytes() if rel in after else None
                if data is None:
                    path.unlink()
                else:
                    replace_file(path,data)
                applied.append((rel,original))
        except OSError:
            for rel,original in reversed(applied):
                if original is None:
                    (root/rel).unlink(missing_ok=True)
                else:
                    replace_file(root/rel,original)
            raise RuntimeError("发布失败，已回滚本次文件修改。") from None
    return changed


def run(cli, root, prompt):
    root = Path(root).resolve()
    node = shutil.which("node")
    if not node:
        raise RuntimeError("找不到 Node.js，无法运行工作室的 JavaScript 验证。")
    with tempfile.TemporaryDirectory(prefix="office-code-",ignore_cleanup_errors=True) as temp:
        work = Path(temp).resolve() / "project"
        work.mkdir()
        scratch = work / ".scratch"
        scratch.mkdir()
        env = process_env(scratch)
        review = _REVIEW.get()
        before = files(root)
        copy_source(root,work,before)
        if review and review[1]:
            from releases import seed
            seed(root, review[1], work, data_dir=review[0])
        answer = code(cli,root,work,env,node,prompt)
        after = files(work)
        if not set(p for p in before if p.name.startswith("test_")) <= set(after):
            raise RuntimeError("候选版本移除了现有回归测试。未发布修改。")
        # A coworker can finish unrelated assets while the model is generating.
        # Verify our patch against that new snapshot before publishing anything.
        live = files(root)
        if live != before:
            changed = [p for p in before.keys() | after.keys() if before.get(p) != after.get(p)]
            if any(live.get(p) != before.get(p) for p in changed):
                raise RuntimeError("开发目标的正式源码已有新修改。请重新执行。")
            merged = work.parent / "merged"
            merged.mkdir()
            copy_source(root, merged, live)
            for path in changed:
                if path in after:
                    replace_file(merged / path, (work / path).read_bytes())
                else:
                    (merged / path).unlink()
            work = merged
            scratch = work / ".scratch"
            scratch.mkdir()
            env = process_env(scratch)
            before, after = live, files(work)
        progress("testing")
        record = verify(cli,root,work,env,node)
        if files(work) != after:
            raise RuntimeError("测试改变了待发布源码。未发布修改。")
        cancellation.checkpoint()
        changed = sorted(p for p in before.keys() | after.keys() if before.get(p) != after.get(p))
        release = None
        if review and changed:
            from releases import stage
            release = stage(root, work, before, after, data_dir=review[0])
        elif not review:
            changed = publish(root, work, before, after)
        report = [("新增" if p not in before else "删除" if p not in after else "修改")+"  "+p.as_posix() for p in changed]
        text = ("代码变更\n"+("\n".join(report) if report else "没有源文件差异。")+
                "\n\n验证记录\n"+record+"\n\nCodex 交付说明\n"+answer)[:16000]
        return CodeDelivery(text, release) if release else text

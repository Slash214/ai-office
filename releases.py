"""Persist verified office candidates and apply recoverable source transactions."""

from contextlib import contextmanager
from datetime import datetime, timezone
import difflib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
from uuid import uuid4

from project_coder import INPUT_DIRS, PUBLISH_LOCK, files, is_link, replace_file


MAX_RELEASE_BYTES = 64 * 1024 * 1024
MAX_STORE_BYTES = 256 * 1024 * 1024
RELEASE_ID = re.compile(r"[0-9a-f]{32}")


class ReleaseConflict(RuntimeError):
    """Live source no longer matches the release's expected inputs."""


class ReleaseCapacity(ValueError):
    """The release would exceed the private storage budget."""


def _store(root, data_dir):
    root = Path(root).resolve()
    directory = (Path(data_dir) if data_dir is not None else root / ".office-data").resolve()
    store = (directory / "releases").resolve()
    public = (root / "public").resolve()
    if store == public or public in store.parents:
        raise ValueError("候选版本必须保存在私有目录中。")
    return root, store


def _json(path, value):
    replace_file(path, json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    _sync_directory(path.parent)


def _sync_directory(directory):
    if os.name != "nt":
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


@contextmanager
def _locked(store, *, create=False):
    with PUBLISH_LOCK:
        if create:
            store.mkdir(mode=0o700, parents=True, exist_ok=True)
        with (store / ".lock").open("a+b") as lock:
            if os.name == "nt":
                import msvcrt

                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            yield


def _relative(name):
    path = PurePosixPath(name)
    if (not path.parts or path.is_absolute() or path.as_posix() != name or "\\" in name
            or ":" in name or any(part.startswith(".") or part.endswith((" ", "."))
                                   or Path(part).is_reserved() for part in path.parts)):
        raise ValueError("候选版本包含无效的文件路径。")
    return Path(*path.parts)


def _content(root, relative):
    target = root / relative
    for directory in reversed(relative.parents[:-1]):
        path = root / directory
        try:
            if is_link(path):
                raise ReleaseConflict("源码路径包含链接，版本操作已停止。")
        except FileNotFoundError:
            return None
        if not path.is_dir():
            raise ReleaseConflict("源码目录已被替换，版本操作已停止。")
    try:
        info = target.lstat()
    except FileNotFoundError:
        return None
    if is_link(target) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ReleaseConflict("源码路径已指向非普通文件，版本操作已停止。")
    if info.st_size > 16 * 1024 * 1024:
        raise ReleaseConflict("源码文件超出工作副本上限。")
    return target.read_bytes()


def _digest(data):
    return None if data is None else hashlib.sha256(data).hexdigest()


def _directory(store, release_id):
    if not isinstance(release_id, str) or not RELEASE_ID.fullmatch(release_id):
        raise FileNotFoundError("找不到候选版本。")
    folder = store / release_id
    if not folder.is_dir():
        raise FileNotFoundError("找不到候选版本。")
    return folder


def _read(folder):
    manifest = json.loads((folder / "manifest.json").read_text("utf-8"))
    state = json.loads((folder / "state.json").read_text("utf-8"))["state"]
    return manifest, state


def _metadata(manifest, state):
    return {
        "id": manifest["id"],
        "state": state,
        "created_at": manifest["created_at"],
        "changes": [{"path": name, "kind": "added" if old is None else "deleted" if new is None else "modified"}
                    for name, old, new in manifest["changes"]],
    }


def stage(root, candidate, before, after, *, data_dir=None):
    """Store the verified public snapshot and patch without changing live source."""
    root, store = _store(root, data_dir)
    candidate = Path(candidate).resolve()
    changed = sorted(p for p in before.keys() | after.keys() if before.get(p) != after.get(p))
    if not changed:
        raise ValueError("候选版本没有源文件变更。")
    if any(any(part in p.parents for part in INPUT_DIRS) for p in changed):
        raise ValueError("候选版本修改了随附的第三方依赖。")
    manifest = {
        "id": uuid4().hex,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "baseline": {p.as_posix(): digest.hex() for p, digest in before.items()},
        "changes": [[p.as_posix(), before[p].hex() if p in before else None,
                     after[p].hex() if p in after else None] for p in changed],
        "public": {p.relative_to("public").as_posix(): digest.hex() for p, digest in after.items()
                   if p.parts[0] == "public"},
    }
    with _locked(store, create=True):
        for orphan in store.glob(".staging-*"):
            if orphan.is_dir() and not is_link(orphan):
                shutil.rmtree(orphan)
        used = sum(path.stat().st_size for path in store.rglob("*") if path.is_file())
        size = 0
        with tempfile.TemporaryDirectory(prefix=".staging-", dir=store) as temp:
            folder = Path(temp)
            (folder / "blobs").mkdir()

            def save(source, name, expected):
                if expected is None:
                    return
                nonlocal size
                data = _content(source, _relative(name))
                if _digest(data) != expected:
                    raise ReleaseConflict("保存候选版本期间源文件发生变化，请重新执行。")
                target = folder / "blobs" / expected
                if not target.exists():
                    size += len(data)
                    if size > MAX_RELEASE_BYTES or used + size > MAX_STORE_BYTES:
                        raise ReleaseCapacity("候选版本存储空间不足。")
                    replace_file(target, data)

            for name, old, new in manifest["changes"]:
                save(root, name, old)
                save(candidate, name, new)
            for name, digest in manifest["public"].items():
                save(candidate, "public/" + name, digest)
            _sync_directory(folder / "blobs")
            _json(folder / "manifest.json", manifest)
            _json(folder / "state.json", {"state": "staged"})
            if used + size + sum(p.stat().st_size for p in folder.glob("*.json")) > MAX_STORE_BYTES:
                raise ReleaseCapacity("候选版本存储空间不足。")
            folder.rename(store / manifest["id"])
            _sync_directory(store)
    return _metadata(manifest, "staged")


def inspect(root, release_id, *, data_dir=None):
    _, store = _store(root, data_dir)
    return _metadata(*_read(_directory(store, release_id)))


def preview(root, release_id, relative, *, data_dir=None):
    """Read one asset from the release's immutable public snapshot."""
    _, store = _store(root, data_dir)
    folder = _directory(store, release_id)
    manifest, _ = _read(folder)
    digest = manifest["public"].get(relative)
    if digest is None:
        raise FileNotFoundError("找不到预览文件。")
    return _blob(folder, digest)


def diff(root, release_id, *, data_dir=None):
    """Return a bounded, plain-text diff of the release's actual source changes."""
    _, store = _store(root, data_dir)
    folder = _directory(store, release_id)
    manifest, _ = _read(folder)
    chunks = []
    remaining = 80000
    for name, old, new in manifest["changes"]:
        try:
            before = (_blob(folder, old) or b"").decode("utf-8").splitlines()
            after = (_blob(folder, new) or b"").decode("utf-8").splitlines()
            lines = difflib.unified_diff(before, after, f"当前版/{name}", f"候选版/{name}", lineterm="")
            for line in lines:
                remaining -= len(line) + 1
                if remaining < 0:
                    return "\n".join(chunks) + "\n… 已达到文本预览上限。"
                chunks.append(line)
        except UnicodeDecodeError:
            chunks.append(f"{name} · 二进制文件已变更")
            remaining -= len(chunks[-1]) + 1
    return "\n".join(chunks)


def _blob(folder, digest):
    if digest is None:
        return None
    try:
        data = (folder / "blobs" / digest).read_bytes()
    except FileNotFoundError:
        if not folder.is_dir():
            raise
        raise RuntimeError("候选版本文件丢失。") from None
    if _digest(data) != digest:
        raise RuntimeError("候选版本文件损坏。")
    return data


def _write(root, relative, expected, data):
    path = root / relative
    if _digest(_content(root, relative)) != expected:
        raise ReleaseConflict(f"源码已有新修改，版本操作已停止。{relative.as_posix()}")
    if data is None:
        path.unlink()
    else:
        replace_file(path, data)
    _sync_directory(path.parent)


def seed(root, release_id, destination, *, data_dir=None):
    """Apply a staged candidate's patch to a fresh, private engineering copy."""
    root, store = _store(root, data_dir)
    destination = Path(destination).resolve()
    if (destination == root or destination in root.parents or root in destination.parents
            or destination == store or store in destination.parents):
        raise ValueError("修改候选版本需要独立的工作副本。")
    with _locked(store):
        folder = _directory(store, release_id)
        manifest, state = _read(folder)
        if state != "staged":
            raise ReleaseConflict("只能修改待验收的候选版本。")
        plan = []
        for name, old, new in manifest["changes"]:
            relative = _relative(name)
            if _digest(_content(root, relative)) != old or _digest(_content(destination, relative)) != old:
                raise ReleaseConflict(f"正式源码已有新修改，无法继续修改候选版本。{name}")
            plan.append((relative, old, _blob(folder, new)))
        for relative, expected, data in plan:
            _write(destination, relative, expected, data)
    return _metadata(manifest, state)


def discard(root, release_id, *, data_dir=None):
    """Free private storage for a candidate that has no live effects."""
    _, store = _store(root, data_dir)
    with _locked(store):
        folder = _directory(store, release_id)
        manifest, state = _read(folder)
        if state not in {"staged", "rolled_back"}:
            raise ReleaseConflict("只能清理未发布或已撤回的候选版本。")
        detached = folder.rename(store / (".staging-" + release_id))
        _sync_directory(store)
        shutil.rmtree(detached)
    return _metadata(manifest, "discarded")


def _transition(root, release_id, data_dir, reverse):
    root, store = _store(root, data_dir)
    pending, done = ("rolling_back", "rolled_back") if reverse else ("publishing", "published")
    allowed = {"published", "publishing", "rolling_back"} if reverse else {"staged", "publishing"}
    with _locked(store):
        folder = _directory(store, release_id)
        manifest, state = _read(folder)
        if state == done:
            return _metadata(manifest, state)
        if state not in allowed:
            raise ReleaseConflict("当前版本状态不允许此操作。")
        if state == "staged":
            live = {p.as_posix(): digest.hex() for p, digest in files(root).items()}
            if live != manifest["baseline"]:
                raise ReleaseConflict("正式源码已偏离验证基线，请重新生成候选版本。")
        mixed = state in {"publishing", "rolling_back"}
        plan = []
        for name, old, new in manifest["changes"]:
            relative = _relative(name)
            source, target = (new, old) if reverse else (old, new)
            current = _digest(_content(root, relative))
            if current != source and (not mixed or current != target):
                raise ReleaseConflict(f"正式源码已有新修改，版本操作已停止。{name}")
            if current != target:
                plan.append((relative, current, _blob(folder, target)))
        _json(folder / "state.json", {"state": pending})
        for relative, expected, data in plan:
            _write(root, relative, expected, data)
        for name, old, new in manifest["changes"]:
            if _digest(_content(root, _relative(name))) != (old if reverse else new):
                raise ReleaseConflict(f"版本操作期间正式源码已有新修改。{name}")
        _json(folder / "state.json", {"state": done})
        return _metadata(manifest, done)


def publish(root, release_id, *, data_dir=None):
    return _transition(root, release_id, data_dir, reverse=False)


def rollback(root, release_id, *, data_dir=None):
    return _transition(root, release_id, data_dir, reverse=True)

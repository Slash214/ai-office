"""Task-local stop signals and ownership of CLI subprocess trees."""

from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
import os
import signal
import subprocess
import tempfile
import time


_stop_event = ContextVar("office_stop_event", default=None)
_POLL_INTERVAL = 0.05


class Cancelled(RuntimeError):
    """The owner of the task asked it to stop."""


@contextmanager
def capture(stop_event):
    token = _stop_event.set(stop_event)
    try:
        checkpoint()
        yield
    finally:
        _stop_event.reset(token)


def checkpoint():
    event = _stop_event.get()
    if event is not None and event.is_set():
        raise Cancelled("任务已停止。")


def run(args, *, input=None, timeout, **kwargs):
    """Run a CLI and own all descendants for the lifetime of the call."""
    checkpoint()
    # A child may stall before reading its prompt. A file keeps the caller
    # responsive even when the prompt exceeds the Windows pipe buffer.
    with tempfile.TemporaryFile() if input is not None else nullcontext() as prompt:
        if prompt is not None:
            prompt.write(input)
            prompt.seek(0)
            kwargs["stdin"] = prompt

        job = _WindowsJob() if os.name == "nt" else None
        if job is not None:
            kwargs["creationflags"] = kwargs.get("creationflags", 0) | 0x00000004  # CREATE_SUSPENDED
        else:
            kwargs["start_new_session"] = True
        process = None
        assigned = False
        deadline = time.monotonic() + timeout
        try:
            checkpoint()
            process = subprocess.Popen(args, **kwargs)
            if job is not None:
                job.attach(process)
                assigned = True
                checkpoint()
                job.resume(process.pid)
            while True:
                checkpoint()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(args, timeout)
                try:
                    stdout, stderr = process.communicate(timeout=min(_POLL_INTERVAL, remaining))
                except subprocess.TimeoutExpired:
                    continue
                checkpoint()
                return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
        finally:
            try:
                if job is not None:
                    job.close(assigned)
                elif process is not None:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
            finally:
                if process is not None:
                    # If Windows Job assignment failed, the process is still suspended.
                    if job is not None and not assigned:
                        process.kill()
                    process.wait()
                    for pipe in (process.stdout, process.stderr):
                        if pipe is not None:
                            pipe.close()


if os.name == "nt":
    import ctypes as ct
    from ctypes import wintypes as win

    class _BasicLimits(ct.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ct.c_longlong),
            ("PerJobUserTimeLimit", ct.c_longlong),
            ("LimitFlags", win.DWORD),
            ("MinimumWorkingSetSize", ct.c_size_t),
            ("MaximumWorkingSetSize", ct.c_size_t),
            ("ActiveProcessLimit", win.DWORD),
            ("Affinity", ct.c_size_t),
            ("PriorityClass", win.DWORD),
            ("SchedulingClass", win.DWORD),
        ]

    class _ExtendedLimits(ct.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimits),
            ("IoInfo", ct.c_ulonglong * 6),
            ("ProcessMemoryLimit", ct.c_size_t),
            ("JobMemoryLimit", ct.c_size_t),
            ("PeakProcessMemoryUsed", ct.c_size_t),
            ("PeakJobMemoryUsed", ct.c_size_t),
        ]

    class _Accounting(ct.Structure):
        _fields_ = [
            ("Times", ct.c_longlong * 4),
            ("TotalPageFaultCount", win.DWORD),
            ("TotalProcesses", win.DWORD),
            ("ActiveProcesses", win.DWORD),
            ("TotalTerminatedProcesses", win.DWORD),
        ]

    class _ThreadEntry(ct.Structure):
        _fields_ = [
            ("dwSize", win.DWORD),
            ("cntUsage", win.DWORD),
            ("th32ThreadID", win.DWORD),
            ("th32OwnerProcessID", win.DWORD),
            ("tpBasePri", win.LONG),
            ("tpDeltaPri", win.LONG),
            ("dwFlags", win.DWORD),
        ]

    _kernel = ct.WinDLL("kernel32", use_last_error=True)

    def _windows_function(name, result, *args):
        function = getattr(_kernel, name)
        function.restype = result
        function.argtypes = args
        return function

    _create_job = _windows_function("CreateJobObjectW", win.HANDLE, win.LPVOID, win.LPCWSTR)
    _set_job_info = _windows_function("SetInformationJobObject", win.BOOL,
                                      win.HANDLE, ct.c_int, win.LPVOID, win.DWORD)
    _assign_job = _windows_function("AssignProcessToJobObject", win.BOOL, win.HANDLE, win.HANDLE)
    _terminate_job = _windows_function("TerminateJobObject", win.BOOL, win.HANDLE, win.UINT)
    _query_job = _windows_function("QueryInformationJobObject", win.BOOL,
                                   win.HANDLE, ct.c_int, win.LPVOID, win.DWORD, win.LPVOID)
    _close_handle = _windows_function("CloseHandle", win.BOOL, win.HANDLE)
    _snapshot = _windows_function("CreateToolhelp32Snapshot", win.HANDLE, win.DWORD, win.DWORD)
    _first_thread = _windows_function("Thread32First", win.BOOL, win.HANDLE, ct.POINTER(_ThreadEntry))
    _next_thread = _windows_function("Thread32Next", win.BOOL, win.HANDLE, ct.POINTER(_ThreadEntry))
    _open_thread = _windows_function("OpenThread", win.HANDLE, win.DWORD, win.BOOL, win.DWORD)
    _resume_thread = _windows_function("ResumeThread", win.DWORD, win.HANDLE)

    class _WindowsJob:
        def __init__(self):
            self.handle = _create_job(None, None)
            if not self.handle:
                raise ct.WinError(ct.get_last_error())
            limits = _ExtendedLimits()
            limits.BasicLimitInformation.LimitFlags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not _set_job_info(self.handle, 9, ct.byref(limits), ct.sizeof(limits)):
                error = ct.WinError(ct.get_last_error())
                self.close()
                raise error

        def attach(self, process):
            if not _assign_job(self.handle, int(process._handle)):
                raise ct.WinError(ct.get_last_error())

        def resume(self, pid):
            # Popen retains the process handle, but closes the initial thread
            # handle. The suspended child still only has its initial thread.
            snapshot = _snapshot(0x00000004, 0)  # TH32CS_SNAPTHREAD
            if snapshot == ct.c_void_p(-1).value:
                raise ct.WinError(ct.get_last_error())
            try:
                entry = _ThreadEntry(dwSize=ct.sizeof(_ThreadEntry))
                found = _first_thread(snapshot, ct.byref(entry))
                while found:
                    if entry.th32OwnerProcessID == pid:
                        self._resume(entry.th32ThreadID)
                        return
                    entry.dwSize = ct.sizeof(_ThreadEntry)
                    found = _next_thread(snapshot, ct.byref(entry))
                raise ct.WinError(ct.get_last_error())
            finally:
                _close_handle(snapshot)

        @staticmethod
        def _resume(thread_id):
            thread = _open_thread(0x0002, False, thread_id)  # THREAD_SUSPEND_RESUME
            if not thread:
                raise ct.WinError(ct.get_last_error())
            try:
                if _resume_thread(thread) == 0xffffffff:
                    raise ct.WinError(ct.get_last_error())
            finally:
                _close_handle(thread)

        def close(self, assigned=False):
            try:
                if assigned and _terminate_job(self.handle, 1):
                    # Let descendants release temporary files before the caller
                    # reads the CLI output or removes its scratch directory.
                    accounting = _Accounting()
                    deadline = time.monotonic() + 2
                    while (time.monotonic() < deadline
                           and _query_job(self.handle, 1, ct.byref(accounting), ct.sizeof(accounting), None)
                           and accounting.ActiveProcesses):
                        time.sleep(0.01)
            finally:
                _close_handle(self.handle)

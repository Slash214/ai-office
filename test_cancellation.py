import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import cancellation


class ProcessCancellation(unittest.TestCase):
    def test_already_stopped_task_launches_nothing(self):
        stop = threading.Event()
        with cancellation.capture(stop), patch.object(subprocess, "Popen") as start:
            stop.set()
            with self.assertRaises(cancellation.Cancelled):
                cancellation.run([sys.executable], timeout=1)
        start.assert_not_called()

    def test_captures_output_and_delivers_stdin(self):
        result = cancellation.run(
            [sys.executable, "-c", "import sys; print(len(sys.stdin.buffer.read()))"],
            input=b"x" * 65000, stdout=subprocess.PIPE, timeout=5,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), b"65000")

    def test_timeout_keeps_timeout_exception(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            cancellation.run(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                stdout=subprocess.PIPE, timeout=0.2,
            )

    @unittest.skipUnless(os.name == "nt", "Windows process handle assertion")
    def test_stops_child_and_grandchild(self):
        import _winapi

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            ready, release, escaped = (root / name for name in ("ready", "release", "escaped"))
            child = (
                "import os,sys,time; from pathlib import Path\n"
                "ready, release, escaped = map(Path, sys.argv[1:])\n"
                "pidfile = ready.with_suffix('.tmp')\n"
                "pidfile.write_text(str(os.getpid()))\n"
                "pidfile.replace(ready)\n"
                "while not release.exists(): time.sleep(0.01)\n"
                "escaped.touch()\n"
            )
            parent = "import subprocess,sys; subprocess.run([sys.executable, '-c', *sys.argv[1:]], check=True)"
            results = queue.Queue()
            stop = threading.Event()

            def worker():
                try:
                    with cancellation.capture(stop):
                        result = cancellation.run(
                            [sys.executable, "-c", parent, child, str(ready), str(release), str(escaped)],
                            input=b"x" * 65000, stdout=subprocess.PIPE, timeout=10,
                        )
                except Exception as error:
                    result = error
                results.put(result)

            thread = threading.Thread(target=worker)
            thread.start()
            try:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline and not ready.exists() and thread.is_alive():
                    time.sleep(0.01)
                self.assertTrue(ready.exists(), "fixture grandchild never started")
                handle = _winapi.OpenProcess(_winapi.SYNCHRONIZE, False, int(ready.read_text()))
                try:
                    stop.set()
                    self.assertIsInstance(results.get(timeout=2), cancellation.Cancelled)
                    self.assertEqual(_winapi.WaitForSingleObject(handle, 0), _winapi.WAIT_OBJECT_0)
                    self.assertFalse(escaped.exists())
                finally:
                    _winapi.CloseHandle(handle)
            finally:
                stop.set()
                release.touch()
                thread.join(timeout=10)
                self.assertFalse(thread.is_alive())

import io
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

import adapters


class AntigravityErrors(unittest.TestCase):
    def test_retries_confirmed_pre_turn_database_collision(self):
        attempts = []
        def run(args, **kwargs):
            log = Path(args[args.index("--log-file")+1])
            self.assertFalse(log.exists())
            attempts.append(1)
            if len(attempts)==1:
                log.write_text("database was initialized by another opener\nPrint mode: failed to start conversation")
                kwargs["stdout"].write(b"previous failed startup\n")
                return subprocess.CompletedProcess(args, 1)
            kwargs["stdout"].write(b'{"event":"result","result":{"status":"SUCCESS","response":"ok"}}\n')
            return subprocess.CompletedProcess(args, 0)
        with (patch.object(adapters, "capabilities", return_value={"carbon":{"ready":True}}),
              patch.object(adapters, "executable", return_value=["agy"]),
              patch.object(adapters.time, "sleep"),
              patch.object(adapters.cancellation, "run", side_effect=run)):
            self.assertEqual(adapters.run_agent("carbon","plan"),"ok")
        self.assertEqual(len(attempts),2)

    def test_hydrogen_receives_text_handoff_with_original_task_content(self):
        task = "按分工撰写全文，将内容交给下一位"

        def succeed_cli(args, **kwargs):
            payload = json.loads(kwargs["input"])
            self.assertEqual(payload["message"]["content"], adapters.AGY_TEXT_HANDOFF + task)
            self.assertIn("--sandbox", args)
            kwargs["stdout"].write(b'{"event":"result","result":{"status":"SUCCESS","response":"draft"}}\n')
            return subprocess.CompletedProcess(args, 0)

        with (
            patch.object(adapters, "capabilities", return_value={"hydrogen": {"ready": True}}),
            patch.object(adapters, "executable", return_value=["agy"]),
            patch.object(adapters.cancellation, "run", side_effect=succeed_cli),
        ):
            self.assertEqual(adapters.run_agent("hydrogen", task), "draft")

    def test_nonzero_cli_exit_distinguishes_network_from_quota(self):
        private = "private-account@example.test"

        def fail_cli(args, **kwargs):
            kwargs["stderr"].write(f"ECONNRESET account={private}".encode())
            return subprocess.CompletedProcess(args, 1)

        with (
            patch.object(adapters, "capabilities", return_value={"carbon": {"ready": True}}),
            patch.object(adapters, "executable", return_value=["agy"]),
            patch.object(adapters.cancellation, "run", side_effect=fail_cli),
        ):
            with self.assertRaisesRegex(RuntimeError, "检查网络") as context:
                adapters.run_agent("carbon", "fixture prompt")
        self.assertNotIn(private, str(context.exception))
        self.assertNotIn("配额", str(context.exception))

    def test_structured_error_classification(self):
        cases = [
            ({"code": 401}, "重新登录"),
            ({"code": 403}, "模型访问权限"),
            ({"code": 429}, "限流或配额"),
            ({"status": "SERVICE_UNAVAILABLE"}, "服务暂时繁忙"),
            ({"message": "Unknown option --input-format"}, "调用参数不兼容"),
        ]
        for error, expected in cases:
            with self.subTest(error=error):
                event = {"event": "result", "result": {"status": "ERROR", "error": error}}
                transcript = io.BytesIO(json.dumps(event).encode())
                with self.assertRaisesRegex(RuntimeError, expected):
                    adapters.agy_answer(transcript, adapters.GOOGLE["carbon"])

    def test_unrecognized_error_hides_provider_payload(self):
        stdout = json.dumps({"event": "result", "result": {"status": "ERROR", "error": "private-response"}})
        message = adapters.agy_failure("private-stderr", stdout, 1)
        self.assertIn("退出码 1", message)
        self.assertNotIn("配额", message)
        self.assertNotIn("private", message)

    def test_step_error_is_classified_without_reading_generated_content(self):
        update = {"event": "step_update", "step_update": {"state": {
            "error": {"code": 503}, "content": "private model output",
        }}}
        message = adapters.agy_failure("", json.dumps(update), 1)
        self.assertIn("服务暂时繁忙", message)
        self.assertNotIn("private", message)
        update["step_update"]["state"] = {"content": "quota exceeded"}
        ordinary_update = adapters.agy_failure("", json.dumps(update), 1)
        self.assertNotIn("配额", ordinary_update)

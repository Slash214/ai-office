import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import project_coder as coder


class ProjectCoding(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        (self.root / "public").mkdir()
        self.css = self.root / "public" / "office.css"
        self.css.write_text("body{}",encoding="utf8")
        private = self.root / ".office-data"
        private.mkdir()
        (private / "token").write_text("private-test-value")

    def apply(self, edit, check):
        with patch.object(coder, "code", side_effect=edit), patch.object(coder, "verify", side_effect=check), \
                 patch.object(coder.shutil, "which", return_value="node"):
            return coder.run(["unused"],self.root,"测试用例")

    def edit(self, cli, root, work, env, node, prompt):
        self.assertFalse((work/".office-data").exists())
        (work / "public" / "office.css").write_text("body{color:navy}",encoding="utf8")
        return "完成"

    def test_only_verified_source_is_published(self):
        def check(cli, root, work, env, node):
            self.assertEqual(self.css.read_text(),"body{}")
            self.assertIn("navy",(work/"public"/"office.css").read_text())
            return "验证通过"
        report = self.apply(self.edit,check)
        self.assertIn("public/office.css",report)
        self.assertIn("验证通过",report)
        self.assertIn("navy",self.css.read_text())

    def test_failed_verification_keeps_live_code(self):
        with self.assertRaisesRegex(RuntimeError,"测试未通过"):
            self.apply(self.edit,RuntimeError("测试未通过"))
        self.assertEqual(self.css.read_text(),"body{}")

    def test_concurrent_live_edit_survives(self):
        def check(*args):
            self.css.write_text("body{color:green}")
            return "ok"
        with self.assertRaisesRegex(RuntimeError,"正式源码已有新修改"):
            self.apply(self.edit,check)
        self.assertIn("green",self.css.read_text())

    def test_unrelated_new_art_is_included_in_final_validation(self):
        def edit(cli, root, work, env, node, prompt):
            self.edit(cli, root, work, env, node, prompt)
            (root / "public" / "crew.js").write_text("export const crew = 6;")
            return "UI ready"

        def verify(cli, root, work, env, node):
            self.assertTrue((work / "public" / "crew.js").exists())
            self.assertIn("navy", (work / "public" / "office.css").read_text())
            return "verified"

        result = self.apply(edit, verify)
        self.assertIn("public/office.css", result)
        self.assertNotIn("public/crew.js", result)

    def test_verification_cannot_modify_files_being_published(self):
        def check(cli, root, work, env, node):
            (work/"public"/"office.css").write_text("different")
            return "ok"
        with self.assertRaisesRegex(RuntimeError,"测试改变了"):
            self.apply(self.edit,check)
        self.assertEqual(self.css.read_text(),"body{}")

    def test_zero_diff_still_requires_verification(self):
        report = self.apply(lambda *args: "已完成检查", lambda *args:"已真实运行测试")
        self.assertIn("没有源文件差异",report)
        self.assertIn("已真实运行测试",report)

    def test_file_write_failure_restores_prior_files(self):
        (self.root/"public"/"other.css").write_text("initial")
        write = coder.replace_file
        def fail_second(path, data):
            if path.name == "other.css": raise OSError("fixture")
            write(path,data)
        def edit(cli,root,work,env,node,prompt):
            for p in (work/"public").glob("*.css"):
                p.write_text("updated")
            return "ok"
        with patch.object(coder,"replace_file",side_effect=fail_second), self.assertRaisesRegex(RuntimeError,"已回滚"):
            self.apply(edit,lambda *args:"ok")
        self.assertEqual(self.css.read_text(),"body{}")
        self.assertEqual((self.root/"public"/"other.css").read_text(),"initial")

    def editing_packets(self, prompt, reads):
        (self.root/".scratch").mkdir()
        requests=iter(reads)
        packets=[]
        def local_reply(args,scratch,env,timeout,payload):
            packets.append(payload)
            names=next(requests,None)
            response={"action":"deliver" if names is None else "read","reads":names or [],"edits":[],"summary":"ok"}
            (scratch/"answer.json").write_text(json.dumps(response),encoding="utf8")
            return 0,""
        with patch.object(coder,"execute",side_effect=local_reply):
            self.assertEqual(coder.code(["unused"],self.root,self.root,{},"node",prompt),"ok")
        return packets

    def test_consecutive_reads_keep_prior_files_and_explain_duplicates(self):
        (self.root/"public"/"one.js").write_text("const firstFile=1;")
        (self.root/"public"/"two.js").write_text("const secondFile=2;")
        packets=self.editing_packets("public/office.css",[["public/one.js"],["public/two.js"],["public/one.js"]])
        self.assertEqual(len(packets),4)
        self.assertIn("body{}",packets[1])
        for packet in packets[2:]:
            self.assertEqual(packet.count("body{}"),1)
            self.assertEqual(packet.count("const firstFile=1;"),1)
            self.assertEqual(packet.count("const secondFile=2;"),1)
        self.assertIn("你刚请求的文件已在",packets[-1])

    def test_new_reads_take_precedence_under_existing_size_and_file_limits(self):
        old=[f"public/part{i}.js" for i in range(8)]
        for i,name in enumerate(old):
            (self.root/name).write_text(f"const member{i}=true;")
        big="x"*497000
        (self.root/"public"/"large.js").write_text(big)
        (self.root/"public"/"other.js").write_text("z"*5000)
        packets=self.editing_packets("run checks",[old,["public/large.js"],["public/other.js"]])
        self.assertEqual(packets[2].count("\n文件 "),8)
        self.assertIn(big,packets[2])
        self.assertNotIn(big,packets[3])
        self.assertIn("z"*5000,packets[3])
        self.assertTrue(all(len(packet)<=500000 for packet in packets))

    def test_hash_replace_preserves_line_endings_and_allows_followup_fragment(self):
        self.css.write_bytes(b"one\r\ntwo\r\n")
        token="office-sha256:"+hashlib.sha256(self.css.read_bytes()).hexdigest()
        coder.apply_edits(self.root,[{"path":"public/office.css","before":token,"after":"a\nb\n"},
                                     {"path":"public/office.css","before":"b","after":"second"}])
        self.assertEqual(self.css.read_bytes(),b"a\r\nsecond\r\n")

    def test_hash_mismatch_rolls_back_entire_batch(self):
        original=self.css.read_bytes()
        token="office-sha256:"+hashlib.sha256(original).hexdigest()
        for wrong in ("office-sha256:12", "office-sha256:" + "0"*64):
            with self.assertRaisesRegex(ValueError,"SHA256"):
                coder.apply_edits(self.root,[
                    {"path":"public/office.css","before":token,"after":"changed"},
                    {"path":"public/office.css","before":wrong,"after":"invalid"}])
        self.assertEqual(self.css.read_bytes(),original)

    def test_monitor_samples_successful_edits_only(self):
        events = []
        with coder.for_review(self.root, on_progress=lambda stage, fields: events.append((stage, fields))):
            with self.assertRaises(ValueError):
                coder.apply_edits(self.root,[{"path":"public/office.css","before":"unknown","after":"bad"}])
            self.assertEqual(events, [])
            coder.apply_edits(self.root,[{"path":"public/office.css","before":"body{}","after":"body{}\nmain{}\napi_key = 'private'"}])
        self.assertEqual(events,[("edited",{"path":"public/office.css","lines":["+ main{}", "+ •••"]})])
        self.assertEqual(coder.changed_excerpt("one\ntwo\nthree","one\nthree"),["− two"])

    def test_named_module_includes_its_verified_digest_and_small_importer(self):
        target=self.root/"public"/"face.js"
        target.write_bytes(b"export const face = 1;\r\n")
        (self.root/"public"/"main.js").write_text("import {face} from './face.js';")
        packet=self.editing_packets("Update public/face.js",[])[0]
        self.assertIn("office-sha256:"+hashlib.sha256(target.read_bytes()).hexdigest(),packet)
        self.assertIn("import {face} from './face.js';",packet)

    def test_final_error_identifies_unmatched_source_file(self):
        (self.root/".scratch").mkdir()
        def bad_reply(args,scratch,env,timeout,payload):
            data={"action":"deliver","reads":[],"edits":[{"path":"public/office.css","before":"missing","after":"replacement"}],"summary":"ok"}
            (scratch/"answer.json").write_text(json.dumps(data),encoding="utf8")
            return 0,""
        with patch.object(coder,"execute",side_effect=bad_reply), self.assertRaisesRegex(RuntimeError,"public/office.css 的 before 匹配到 0"):
            coder.code(["unused"],self.root,self.root,{},"node","run checks")

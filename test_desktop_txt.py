import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import desktop_txt
from workflow import Workflow, new_step, now


class DesktopDelivery(unittest.TestCase):
    def test_html_execution_saves_the_page_before_acceptance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            desk = root/"Desktop"
            desk.mkdir()
            flow = Workflow(root)
            task = dict(id=str(uuid.uuid4()), createdAt=now(), brief="在桌面创建一个html页面",
                        workers=["codex"],steps=[new_step("execute-codex","codex","execution")],
                        autoAdvance=True,desktopHtml=True)
            doc = "<!doctype html><html><body>离线展示</body></html>"
            self.assertTrue(desktop_txt.requested_html(task["brief"]))
            with patch.object(desktop_txt,"directory",return_value=desk):
                flow.finish(task,"作品\n```html\n"+doc+"\n```")
                flow.save(task)
                self.assertEqual((desk/task["textDelivery"]["filename"]).read_text("utf8"), doc)
                self.assertFalse(task.get("acceptedAt"))
                flow.export_text(task["id"])
                self.assertEqual(len(list(desk.iterdir())),1)
            with self.assertRaises(ValueError):
                desktop_txt.html_document("已生成")

    def test_text_completion_saves_before_review_and_preserves_collisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            desktop=root/"Desktop"
            desktop.mkdir()
            old=desktop/"月报.txt"
            old.write_text("原有文件",encoding="utf8")
            flow=Workflow(root)
            task=dict(id=str(uuid.uuid4()),createdAt=now(),brief="在桌面生成月报 TXT",workers=["hydrogen"],
                      steps=[new_step("execute-hydrogen","hydrogen","execution")],autoAdvance=True,desktopTxt=True)
            task["steps"][0].update(status="done",updatedAt=now(),result="文件名：月报.txt\n第一行\n第二行")
            with patch.object(desktop_txt,"directory",return_value=desktop):
                flow.save(task)
                self.assertEqual(task["textDelivery"]["filename"],"月报 (2).txt")
                self.assertFalse(task.get("acceptedAt"))
                self.assertEqual((desktop/"月报 (2).txt").read_text("utf8"),"第一行\n第二行")
                self.assertEqual(old.read_text("utf8"),"原有文件")
                flow.export_text(task["id"])
                self.assertEqual(len(list(desktop.iterdir())),2)

    def test_desktop_path_is_host_selected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            d=root/"desktop"
            d.mkdir()
            file=desktop_txt.write("../escape.txt",b"safe",d)
            self.assertTrue((d/file["filename"]).exists())
            self.assertFalse((root/"escape.txt").exists())
        self.assertFalse(desktop_txt.requested("不要写到桌面 txt"))
        self.assertTrue(desktop_txt.requested("在我的桌面创建个txt写个漫剧"))

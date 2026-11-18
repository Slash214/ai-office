from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from project_coder import files
import releases


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "live"
        self.candidate = self.base / "candidate"
        self.data = self.base / "private"
        (self.root / "public").mkdir(parents=True)
        self.write(self.root, "public/index.html", "old page")
        self.write(self.root, "public/style.css", "unchanged stylesheet")
        self.write(self.root, "public/obsolete.js", "old script")
        self.write(self.root, "server.py", "old server")
        shutil.copytree(self.root, self.candidate)
        self.write(self.candidate, "public/index.html", "new page")
        self.write(self.candidate, "public/new.js", "new script")
        self.write(self.candidate, "server.py", "new server")
        (self.candidate / "public/obsolete.js").unlink()
        self.release = releases.stage(self.root, self.candidate, files(self.root), files(self.candidate),
                                      data_dir=self.data)
        self.release_id = self.release["id"]

    def write(self, root, name, value):
        (root / name).write_text(value, encoding="utf-8")

    def invoke(self, operation, *args):
        return operation(self.root, self.release_id, *args, data_dir=self.data)

    def test_preview_is_immutable_and_uses_only_the_candidate_public_manifest(self):
        self.assertEqual(self.release["state"], "staged")
        self.assertEqual(self.release["changes"], [
            {"path": "public/index.html", "kind": "modified"},
            {"path": "public/new.js", "kind": "added"},
            {"path": "public/obsolete.js", "kind": "deleted"},
            {"path": "server.py", "kind": "modified"},
        ])
        shutil.rmtree(self.candidate)
        self.write(self.root, "public/style.css", "later stylesheet")
        self.assertEqual(self.invoke(releases.inspect), self.release)
        self.assertEqual(self.invoke(releases.preview, "index.html"), b"new page")
        self.assertEqual(self.invoke(releases.preview, "style.css"), b"unchanged stylesheet")
        for name in ("../server.py", "server.py", "obsolete.js"):
            with self.subTest(name=name), self.assertRaises(FileNotFoundError):
                self.invoke(releases.preview, name)
        self.assertEqual((self.root / "public/index.html").read_bytes(), b"old page")
        with self.assertRaises(FileNotFoundError):
            releases.inspect(self.root, "../state.json", data_dir=self.data)

    def test_publish_requires_the_exact_tested_baseline(self):
        self.write(self.root, "public/style.css", "independent update")
        with self.assertRaises(releases.ReleaseConflict):
            self.invoke(releases.publish)
        self.assertEqual(self.invoke(releases.inspect), self.release)
        self.assertEqual((self.root / "public/index.html").read_bytes(), b"old page")

    def test_publish_and_rollback_are_idempotent_and_preserve_unrelated_edits(self):
        published = self.invoke(releases.publish)
        self.assertEqual(published["state"], "published")
        self.assertEqual(self.invoke(releases.publish), published)
        self.assertEqual(files(self.root), files(self.candidate))
        self.write(self.root, "public/style.css", "later stylesheet")
        rolled_back = self.invoke(releases.rollback)
        self.assertEqual(rolled_back["state"], "rolled_back")
        self.assertEqual(self.invoke(releases.rollback), rolled_back)
        self.assertEqual((self.root / "public/index.html").read_bytes(), b"old page")
        self.assertEqual((self.root / "public/style.css").read_bytes(), b"later stylesheet")
        self.assertEqual((self.root / "server.py").read_bytes(), b"old server")
        self.assertEqual((self.root / "public/obsolete.js").read_bytes(), b"old script")
        self.assertFalse((self.root / "public/new.js").exists())

    def test_rollback_conflict_preflights_all_changes_before_writing(self):
        self.invoke(releases.publish)
        self.write(self.root, "server.py", "later server changes")
        baseline = files(self.root)
        with self.assertRaises(releases.ReleaseConflict):
            self.invoke(releases.rollback)
        self.assertEqual(files(self.root), baseline)
        self.assertEqual(self.invoke(releases.inspect)["state"], "published")

    def interrupt_second_write(self, operation, pending):
        real_write = releases._write

        def interrupt(root, relative, expected, data):
            if relative.name == "new.js":
                raise OSError("simulated interruption")
            real_write(root, relative, expected, data)

        with patch.object(releases, "_write", side_effect=interrupt), self.assertRaises(OSError):
            self.invoke(operation)
        self.assertEqual(self.invoke(releases.inspect)["state"], pending)

    def test_interrupted_publish_can_resume_and_preserves_independent_edits(self):
        self.interrupt_second_write(releases.publish, "publishing")
        self.assertEqual((self.root / "public/index.html").read_bytes(), b"new page")
        self.assertFalse((self.root / "public/new.js").exists())
        self.write(self.root, "public/style.css", "later stylesheet")
        self.assertEqual(self.invoke(releases.publish)["state"], "published")
        self.assertEqual((self.root / "public/new.js").read_bytes(), b"new script")
        self.assertEqual((self.root / "public/style.css").read_bytes(), b"later stylesheet")

    def test_interrupted_publish_can_be_rolled_back(self):
        baseline = files(self.root)
        self.interrupt_second_write(releases.publish, "publishing")
        self.assertEqual(self.invoke(releases.rollback)["state"], "rolled_back")
        self.assertEqual(files(self.root), baseline)

    def test_interrupted_rollback_can_resume(self):
        baseline = files(self.root)
        self.invoke(releases.publish)
        self.interrupt_second_write(releases.rollback, "rolling_back")
        self.assertEqual(self.invoke(releases.rollback)["state"], "rolled_back")
        self.assertEqual(files(self.root), baseline)

    def test_revision_seeds_candidate_on_top_of_a_fresh_copy(self):
        self.write(self.root, "public/style.css", "new unrelated change")
        revision = self.base / "revision"
        shutil.copytree(self.root, revision)
        self.assertEqual(self.invoke(releases.seed, revision), self.release)
        self.assertEqual((revision / "public/index.html").read_bytes(), b"new page")
        self.assertEqual((revision / "public/style.css").read_bytes(), b"new unrelated change")
        self.assertFalse((revision / "public/obsolete.js").exists())
        self.assertEqual((self.root / "public/index.html").read_bytes(), b"old page")
        self.assertEqual(self.invoke(releases.discard)["state"], "discarded")
        with self.assertRaises(FileNotFoundError):
            self.invoke(releases.inspect)

    def test_revision_rejects_touched_conflicts_before_overlaying(self):
        self.write(self.root, "server.py", "new overlapping change")
        revision = self.base / "revision"
        shutil.copytree(self.root, revision)
        with self.assertRaises(releases.ReleaseConflict):
            self.invoke(releases.seed, revision)
        self.assertEqual(files(revision), files(self.root))

    def test_capacity_failure_leaves_no_record_or_live_changes(self):
        with patch.object(releases, "MAX_RELEASE_BYTES", 1), self.assertRaises(releases.ReleaseCapacity):
            releases.stage(self.root, self.candidate, files(self.root), files(self.candidate), data_dir=self.data)
        self.assertEqual(len(list((self.data / "releases").glob("[!.]*"))), 1)
        self.assertEqual((self.root / "public/index.html").read_bytes(), b"old page")


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
import subprocess
from pathlib import Path
from unittest.mock import patch

from umbra.tools import ToolRunner, parse_text_tools, strip_tool_tags
from umbra.gitrepo import list_files


class ToolSafetyTests(unittest.TestCase):
    def test_text_calls_keep_model_order_and_optional_grep_path(self):
        calls = parse_text_tools('<run>echo first</run><grep pattern="first"/><read path="x.txt"/>')
        self.assertEqual([call["name"] for call in calls], ["run", "grep", "read"])
        self.assertEqual(calls[1]["arguments"], {"pattern": "first", "path": "."})

    def test_edit_cannot_escape_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            root.mkdir()
            runner = ToolRunner(root, root)
            outside = Path(directory) / "outside.txt"
            with self.assertRaisesRegex(RuntimeError, "outside the git repository"):
                runner.edit(str(outside), "unsafe")
            with self.assertRaisesRegex(RuntimeError, "outside the git repository"):
                runner.apply_edit(str(outside), "unsafe")
            self.assertFalse(outside.exists())

    def test_preview_rejects_changed_file_and_backup_is_unique(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "code.py"
            target.write_text("original", encoding="utf-8")
            runner = ToolRunner(root, root)
            with patch("umbra.tools.backup_dir", return_value=root / "backups"):
                (root / "backups").mkdir()
                preview = runner.edit("code.py", "updated")
                target.write_text("other change", encoding="utf-8")
                with self.assertRaisesRegex(RuntimeError, "changed since preview"):
                    runner.apply_edit("code.py", "updated", expected_old=preview["old"],
                                      expected_exists=preview["existed"])
                self.assertEqual(target.read_text(encoding="utf-8"), "other change")
                first = runner.apply_edit("code.py", "updated", expected_old="other change",
                                          expected_exists=True)
                second = runner.apply_edit("code.py", "again", expected_old="updated",
                                           expected_exists=True)
                self.assertNotEqual(first, second)
                self.assertEqual(Path(first).read_text(encoding="utf-8"), "other change")
                self.assertEqual(Path(second).read_text(encoding="utf-8"), "updated")

    def test_file_discovery_stays_in_selected_subdirectory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            selected = root / "selected"
            selected.mkdir()
            (selected / "one.py").write_text("one", encoding="utf-8")
            (root / "other.py").write_text("other", encoding="utf-8")
            self.assertEqual(list_files(root, selected), [(selected / "one.py").resolve()])

    def test_read_grep_ls_stay_inside_repo_when_gated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            root.mkdir()
            (root / "code.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
            outside_dir = Path(directory) / "elsewhere"
            outside_dir.mkdir()
            (outside_dir / "secret.txt").write_text("s3cret", encoding="utf-8")
            runner = ToolRunner(root, root)
            self.assertIn("outside the working area", runner.read(str(outside_dir / "secret.txt")))
            self.assertIn("outside the working area", runner.grep("s3cret", str(outside_dir)))
            self.assertIn("outside the working area", runner.ls(str(outside_dir)))
            self.assertIn("def foo", runner.read("code.py"))
            self.assertEqual(runner.ls(".").strip(), "code.py")

    def test_read_uses_workdir_when_no_repo_present(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "inner.txt").write_text("hello", encoding="utf-8")
            runner = ToolRunner(None, root)
            self.assertIn("hello", runner.read("inner.txt"))
            self.assertIn("outside the working area",
                          runner.read(str(root.parent / "outside.txt")))

    def test_yolo_mode_removes_read_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root.parent / "elsewhere.txt"
            outside.write_text("free read", encoding="utf-8")
            runner = ToolRunner(None, root, require_git=False)
            self.assertIn("free read", runner.read(str(outside)))

    def test_strip_tool_tags_keeps_prose(self):
        text = ('Here is the change.\n<read path="a.py"/>\n'
                '<edit path="b.py">NEW BODY</edit>\n<run>git status</run>\nDone.')
        out = strip_tool_tags(text)
        self.assertIn("Here is the change.", out)
        self.assertIn("Done.", out)
        self.assertNotIn("<read", out)
        self.assertNotIn("<edit", out)
        self.assertNotIn("NEW BODY", out)
        self.assertNotIn("<run", out)


if __name__ == "__main__":
    unittest.main()

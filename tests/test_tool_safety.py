import tempfile
import unittest
import subprocess
from pathlib import Path
from unittest.mock import patch

from umbra.tools import ToolRunner, parse_text_tools
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


if __name__ == "__main__":
    unittest.main()

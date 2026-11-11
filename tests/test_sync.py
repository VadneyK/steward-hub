import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import Hub  # noqa: E402


class Sync(unittest.TestCase):
    def setUp(self):
        self.hub = Hub()
        self.home = Path(tempfile.mkdtemp()) / ".claude"
        self.home.mkdir()
        (self.home / "CLAUDE.md").write_text("# my own lines\nkeep me\n")
        (self.home / "settings.json").write_text(json.dumps({"hooks": {"Stop": []}, "model": "x"}))

    def tearDown(self):
        self.hub.close()

    def sync(self, *args):
        env = dict(os.environ, CLAUDE_HOME=str(self.home), STEWARD_HUB=str(self.hub.a))
        return subprocess.run([sys.executable, str(self.hub.a / "tools/sync.py"), *args],
                              capture_output=True, text=True, env=env)

    def test_dry_run_writes_nothing(self):
        r = self.sync("--dry-run")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse((self.home / "skills").exists())

    def test_install_merge_conflict(self):
        r = self.sync()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        md = (self.home / "CLAUDE.md").read_text()
        self.assertIn("keep me", md)
        self.assertIn("STEWARD BEGIN", md)
        self.assertTrue((self.home / "skills/hub-commit/SKILL.md").exists())
        self.assertTrue((self.home / "hooks/steward/outbound-gate.py").exists())
        s = json.loads((self.home / "settings.json").read_text())
        self.assertEqual(s["model"], "x")
        self.assertIn("PreToolUse", s["hooks"])
        self.assertEqual((self.home / "steward/hub").read_text().strip(), str(self.hub.a))
        r = self.sync()
        self.assertIn("0 added, 0 updated", r.stdout)
        s2 = json.loads((self.home / "settings.json").read_text())
        self.assertEqual(s, s2)
        skill = self.home / "skills/hub-commit/SKILL.md"
        skill.write_text("local edit\n")
        (self.hub.a / "shared/skills/hub-commit/SKILL.md").write_text("new shared\n")
        r = self.sync()
        self.assertEqual(r.returncode, 1)
        self.assertIn("CONFLICT", r.stdout)
        self.assertEqual(skill.read_text(), "local edit\n")
        self.assertTrue(Path(str(skill) + ".from-shared").exists())


if __name__ == "__main__":
    unittest.main()

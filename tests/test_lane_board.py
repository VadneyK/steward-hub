import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import Hub, git  # noqa: E402


class LaneBoard(unittest.TestCase):
    def setUp(self):
        self.hub = Hub()

    def tearDown(self):
        self.hub.close()

    def test_lane_claim_refused_on_other_machine(self):
        h = self.hub
        r = h.run(h.a, "a", "lane.py", "taxes", "working", "--what", "gather forms", "--next", "w2")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        st = json.loads((h.a / "status.json").read_text())
        self.assertEqual(st["lanes"][0]["state"], "working")
        r = h.run(h.b, "b", "lane.py", "taxes", "working")
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        r = h.run(h.a, "a", "lane.py", "taxes", "done")
        self.assertIn("released", r.stdout)

    def test_private_lane(self):
        h = self.hub
        r = h.run(h.a, "a", "lane.py", "health", "working", "--private", "--no-lock")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = h.run(h.a, "a", "lane.py", "health", "--what", "secret")
        self.assertEqual(r.returncode, 64)
        st = json.loads((h.a / "status.json").read_text())
        self.assertEqual(st["lanes"][0]["what"], "private")

    def test_board_add_fold_dupes(self):
        h = self.hub
        body = h.root / "body.txt"
        body.write_text("To: ada@example.com\nSubject: hello\n\nhi ada\n")
        r = h.run(h.a, "a", "board.py", "add", "mail", "--kind", "send", "--title", "say hi", "--body", str(body))
        self.assertEqual(r.stdout.strip(), "mail-1", r.stderr)
        r = h.run(h.a, "a", "board.py", "add", "jobs", "--kind", "decide", "--title", "pick a role", "--p", "p1")
        self.assertEqual(r.stdout.strip(), "jobs-1")
        r = h.run(h.a, "a", "board.py", "fold")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        board = (h.a / "board" / "BOARD.md").read_text()
        self.assertLess(board.index("jobs-1"), board.index("mail-1"))
        self.assertIn("FOLDED", (h.a / "handoffs/board-inbox/mail.md").read_text())
        h.run(h.a, "a", "board.py", "add", "other", "--kind", "send", "--title", "again", "--body", str(body))
        r = h.run(h.a, "a", "board.py", "fold")
        self.assertEqual(r.returncode, 1)
        self.assertIn("duplicate", r.stdout)
        h.run(h.a, "a", "board.py", "answer", "jobs-1", "A")
        self.assertIn("ANSWERED", (h.a / "handoffs/board-inbox/jobs.md").read_text())
        h.run(h.a, "a", "board.py", "done", "other-1", "--ref", "merged")
        r = h.run(h.a, "a", "board.py", "fold")
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_hub_push_and_banned_char(self):
        h = self.hub
        f = h.a / "lanes" / "note.md"
        f.write_text("plain text\n")
        r = h.run(h.a, "a", "hub_push.sh", "-m", "note", "lanes/note.md")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        f.write_text("bad " + chr(0x2014) + " dash\n")
        r = h.run(h.a, "a", "hub_push.sh", "-m", "note2", "lanes/note.md")
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        # a push race: b commits after a, so hub_push must rebase and still push
        (h.b / "lanes" / "b.md").write_text("from b\n")
        git(h.b, "pull", "-q")
        g = h.a / "lanes" / "a2.md"
        g.write_text("from a\n")
        self.assertEqual(h.run(h.a, "a", "hub_push.sh", "-m", "a2", "lanes/a2.md").returncode, 0)
        r = h.run(h.b, "b", "hub_push.sh", "-m", "b", "lanes/b.md")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        log = git(h.b, "log", "--oneline", "-3")
        self.assertIn("a2", log)


if __name__ == "__main__":
    unittest.main()

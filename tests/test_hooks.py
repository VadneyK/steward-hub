import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
HOOKS = KIT / "hooks"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import Hub  # noqa: E402


def run(hook, data, *args, **env):
    e = dict(os.environ)
    e.update(env)
    return subprocess.run([sys.executable, str(HOOKS / hook), *args], input=json.dumps(data),
                          capture_output=True, text=True, env=e)


class Outbound(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hub = Hub()
        cls.env = {"STEWARD_HUB": str(cls.hub.a), "STEWARD_MACHINE": "a"}

    @classmethod
    def tearDownClass(cls):
        cls.hub.close()

    def test_send_asks(self):
        r = run("outbound-gate.py", {"tool_name": "mcp__mail__send_message",
                                     "tool_input": {"to": "ada@example.com", "body": "hi"}}, **self.env)
        out = json.loads(r.stdout)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "ask")

    def test_app_tools_exempt(self):
        r = run("outbound-gate.py", {"tool_name": "mcp__ccd_session__send_message", "tool_input": {}}, **self.env)
        self.assertEqual(r.stdout.strip(), "")

    def test_banned_char_blocks(self):
        r = run("outbound-gate.py", {"tool_name": "mcp__mail__create_draft",
                                     "tool_input": {"body": "a " + chr(0x2014) + " b"}}, **self.env)
        self.assertEqual(r.returncode, 2)
        r = run("outbound-gate.py", {"tool_name": "Bash",
                                     "tool_input": {"command": "git commit -m 'x %s y'" % chr(0x2014)}}, **self.env)
        self.assertEqual(r.returncode, 2)
        r = run("outbound-gate.py", {"tool_name": "Bash", "tool_input": {"command": "git commit -m ok"}}, **self.env)
        self.assertEqual(r.returncode, 0)

    def test_stop(self):
        r = run("outbound-gate.py", {"last_assistant_message": "a %s b" % chr(0x2014)}, "--stop", **self.env)
        self.assertEqual(r.returncode, 2)
        r = run("outbound-gate.py", {"last_assistant_message": "fine"}, "--stop", **self.env)
        self.assertEqual(r.returncode, 0)

    def test_lock_note_in_ask(self):
        h = self.hub
        h.run(h.b, "b", "lock.py", "acquire", "person:zed@example.com", "--session", "x")
        subprocess.run(["git", "fetch", "-q", "origin"], cwd=h.a, check=True)
        r = run("outbound-gate.py", {"tool_name": "mcp__mail__send_message",
                                     "tool_input": {"to": "zed@example.com", "body": "hi"}}, **self.env)
        self.assertIn("HUB LOCK", r.stdout)


class Ship(unittest.TestCase):
    def test_ship_guard(self):
        with tempfile.TemporaryDirectory() as d:
            lst = Path(d) / "ship.txt"
            lst.write_text("me/app\n")
            env = {"STEWARD_SHIP_REPOS": str(lst)}
            r = run("ship-guard.py", {"tool_input": {"command": "gh pr merge 3 --repo me/app"}}, **env)
            self.assertEqual(r.returncode, 2)
            r = run("ship-guard.py", {"tool_input": {"command": "gh pr merge 3 --repo me/other"}}, **env)
            self.assertEqual(r.returncode, 0)
            r = run("ship-guard.py", {"tool_input": {"command": "make ship"}}, **env)
            self.assertEqual(r.returncode, 0)


class Browser(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.env = {"HOME": self.home}

    def decision(self, data):
        r = run("no-browser-guard.py", data, **self.env)
        return json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"] if r.stdout.strip() else "allow"

    def test_rules(self):
        self.assertEqual(self.decision({"tool_name": "mcp__claude-in-chrome__navigate",
                                        "tool_input": {"url": "https://example.com"}}), "deny")
        self.assertEqual(self.decision({"tool_name": "mcp__Claude_Browser__navigate",
                                        "tool_input": {"url": "http://localhost:3000"}}), "allow")
        self.assertEqual(self.decision({"tool_name": "mcp__Claude_Browser__tabs_close", "tool_input": {}}), "allow")
        self.assertEqual(self.decision({"tool_name": "Bash", "tool_input": {"command": "open https://x.com"}}), "deny")
        self.assertEqual(self.decision({"tool_name": "Bash", "tool_input": {"command": "touch ~/.claude/browser-ok"}}), "deny")
        self.assertEqual(self.decision({"tool_name": "Bash", "tool_input": {"command": "ls"}}), "allow")
        Path(self.home, ".claude").mkdir()
        Path(self.home, ".claude", "browser-ok").touch()
        self.assertEqual(self.decision({"tool_name": "mcp__claude-in-chrome__navigate",
                                        "tool_input": {"url": "https://example.com"}}), "allow")


class LoopGuard(unittest.TestCase):
    def transcript(self, records):
        f = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
        for r in records:
            f.write(json.dumps(r) + "\n")
        f.close()
        return f.name

    def user(self, text):
        return {"type": "user", "message": {"role": "user", "content": text}}

    def wake(self, stop=False):
        return {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "ScheduleWakeup", "input": {"stop": True} if stop else {"delaySeconds": 1200}}]}}

    def test_blocks_live_loop_without_wakeup(self):
        t = self.transcript([self.user("<command-name>/loop</command-name> do lane"), self.wake(),
                             self.user("<command-name>/loop</command-name> do lane")])
        r = run("lane-loop-guard.py", {"transcript_path": t})
        self.assertIn("block", r.stdout)

    def test_allows_with_wakeup_or_plain_session(self):
        t = self.transcript([self.user("<command-name>/loop</command-name> x"), self.wake()])
        self.assertEqual(run("lane-loop-guard.py", {"transcript_path": t}).stdout.strip(), "")
        t = self.transcript([self.user("hello")])
        self.assertEqual(run("lane-loop-guard.py", {"transcript_path": t}).stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()

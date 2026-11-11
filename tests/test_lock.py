import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import lock  # noqa: E402
from helpers import Hub  # noqa: E402


class Pure(unittest.TestCase):
    def test_keys(self):
        self.assertEqual(lock.normalize_key("person:Ada Example <Ada@Example.com>"), "person:ada@example.com")
        self.assertEqual(lock.normalize_key("person: Ada  Example"), "person:ada-example")
        self.assertEqual(lock.normalize_key("thread:ABC123"), "thread:mail:abc123")
        self.assertEqual(lock.normalize_key("artifact:AbC"), "artifact:AbC")
        self.assertEqual(lock.normalize_key("lane:Job Search"), "lane:job-search")
        with self.assertRaises(ValueError):
            lock.normalize_key("nokind")

    def test_lock_path_unique_and_safe(self):
        a, b = lock.lock_path("person:ada@example.com"), lock.lock_path("person:ADA@example.com".lower() + "x")
        self.assertNotEqual(a, b)
        self.assertTrue(a.startswith("locks/") and a.endswith(".json"))

    def test_idem(self):
        self.assertEqual(lock.idem_key("a@example.com", "Hi", "Body  text"), lock.idem_key("A@example.com", "hi", "body text"))
        self.assertNotEqual(lock.idem_key("a@example.com", "Hi", "one"), lock.idem_key("a@example.com", "Hi", "two"))

    def test_ttl(self):
        self.assertEqual(lock.parse_ttl("2h"), 7200)
        self.assertEqual(lock.parse_ttl("90m"), 5400)
        for bad in ("5s", "8d", "soon"):
            with self.assertRaises(ValueError):
                lock.parse_ttl(bad)

    def test_acquire_rules(self):
        l1, why = lock.decide_acquire(None, "lane:x", "a", "s1", 3600, "", 1000)
        self.assertEqual(l1["token"], 1)
        l2, why = lock.decide_acquire(l1, "lane:x", "b", "s2", 3600, "", 2000)
        self.assertIsNone(l2)
        self.assertIn("held", why)
        renew, _ = lock.decide_acquire(l1, "lane:x", "a", "s1", 3600, "", 2000)
        self.assertEqual(renew["token"], 1)
        late = 1000 + 3600 + lock.GRACE + 1
        take, _ = lock.decide_acquire(l1, "lane:x", "b", "s2", 3600, "", late)
        self.assertEqual(take["token"], 2)
        self.assertEqual(take["previous"]["state"], "expired")

    def test_owner_change(self):
        l1, _ = lock.decide_acquire(None, "lane:x", "a", "s1", 3600, "", 1000)
        none, why = lock.decide_owner_change(l1, "b", "s2", None, 1100, "release")
        self.assertIsNone(none)
        stale, why = lock.decide_owner_change(l1, "a", "s1", 9, 1100, "release")
        self.assertIn("not current", why)
        rel, _ = lock.decide_owner_change(l1, "a", "s1", 1, 1100, "release")
        self.assertEqual(rel["state"], "released")
        f, why = lock.decide_owner_change(l1, "b", "s2", None, 1100, "release", force=True)
        self.assertIn("reason", why)


class WithGit(unittest.TestCase):
    def setUp(self):
        self.hub = Hub()

    def tearDown(self):
        self.hub.close()

    def test_two_machines_one_winner(self):
        h = self.hub
        r = h.run(h.a, "a", "lock.py", "acquire", "person:ada@example.com", "--session", "mail")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = h.run(h.b, "b", "lock.py", "acquire", "person:ada@example.com", "--session", "mail")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("held by a/mail", r.stdout)
        r = h.run(h.b, "b", "lock.py", "release", "person:ada@example.com", "--session", "mail")
        self.assertEqual(r.returncode, 3)
        r = h.run(h.a, "a", "lock.py", "release", "person:ada@example.com", "--session", "mail")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = h.run(h.b, "b", "lock.py", "acquire", "person:ada@example.com", "--session", "mail")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("token 2", r.stdout)

    def test_expiry_takeover(self):
        h = self.hub
        h.run(h.a, "a", "lock.py", "acquire", "lane:tax", "--session", "s", "--ttl", "1m", STEWARD_NOW=1000)
        r = h.run(h.b, "b", "lock.py", "acquire", "lane:tax", "--session", "s", STEWARD_NOW=1000 + 60 + lock.GRACE + 5)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("token 2", r.stdout)

    def test_preflight_and_ledger(self):
        h = self.hub
        r = h.run(h.a, "a", "lock.py", "preflight", "person:bo@example.com", "--action", "send")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = h.run(h.a, "a", "lock.py", "record", "person:bo@example.com", "--action", "send", "--ref", "m1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = h.run(h.b, "b", "lock.py", "preflight", "person:bo@example.com", "--action", "send")
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("ALREADY SEND", r.stdout)
        h.run(h.a, "a", "lock.py", "acquire", "person:cy@example.com", "--session", "x")
        r = h.run(h.b, "b", "lock.py", "preflight", "person:cy@example.com", "--action", "send")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)

    def test_list(self):
        h = self.hub
        h.run(h.a, "a", "lock.py", "acquire", "doc:Abc", "--session", "x", "--note", "editing")
        r = h.run(h.b, "b", "lock.py", "list")
        self.assertIn("doc:Abc", r.stdout)
        self.assertIn("editing", r.stdout)


if __name__ == "__main__":
    unittest.main()

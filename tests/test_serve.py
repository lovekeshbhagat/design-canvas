"""The local review helper against real git repos: security checks, save, End review, Get latest.
Each test builds a bare remote and clones with their own git identity. Run: python3 -m unittest discover tests"""

from __future__ import annotations

import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
import build  # noqa: E402
import reviews  # noqa: E402
import serve  # noqa: E402
from tokens import Design  # noqa: E402

SAMPLE = ROOT / "examples" / "acme-habits"


def git(cwd, *args):
    p = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    return p.stdout.strip()


class Helper(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.env = dict(os.environ)
        (self.tmp / "gitconfig").write_text("[init]\n\tdefaultBranch = main\n", encoding="utf-8")
        os.environ.update(GIT_CONFIG_GLOBAL=str(self.tmp / "gitconfig"), GIT_CONFIG_NOSYSTEM="1")
        git(self.tmp, "init", "-q", "--bare", "-b", "main", "remote.git")
        seed = self.tmp / "seed"
        seed.mkdir()
        git(seed, "init", "-q", "-b", "main")
        git(seed, "config", "user.name", "Seed")
        git(seed, "config", "user.email", "seed@example.com")
        shutil.copytree(SAMPLE, seed / "design-canvas", ignore=shutil.ignore_patterns("out", "reviews"))
        (seed / ".gitignore").write_text("design-canvas/out/\n", encoding="utf-8")
        git(seed, "add", "-A")
        git(seed, "commit", "-qm", "seed")
        git(seed, "remote", "add", "origin", str(self.tmp / "remote.git"))
        git(seed, "push", "-q", "-u", "origin", "main")
        self.sam = self.clone("sam", "Sam")
        self.servers = []

    def tearDown(self):
        for s in self.servers:
            s.shutdown()
            s.server_close()
        os.environ.clear()
        os.environ.update(self.env)
        shutil.rmtree(self.tmp)

    def clone(self, name, person):
        git(self.tmp, "clone", "-q", "remote.git", name)
        git(self.tmp / name, "config", "user.name", person)
        git(self.tmp / name, "config", "user.email", f"{name}@example.com")
        return self.tmp / name

    def start(self, repo):
        d = Design(repo / "design-canvas")
        server, helper = serve.start(d, d.root, 0, False, None, build.build_all, build.script_json)
        self.servers.append(server)
        return helper

    def call(self, helper, method, path, body=None, headers=None, host=None):
        c = http.client.HTTPConnection("127.0.0.1", helper.port, timeout=30)
        h = {"Host": host or f"127.0.0.1:{helper.port}"}
        h.update(headers or {})
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            h.setdefault("Content-Type", "application/json")
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        raw = r.read()
        c.close()
        try:
            return r.status, json.loads(raw)
        except ValueError:
            return r.status, raw.decode("utf-8", "replace")

    def api(self, helper, path, body=None):
        hdr = {"X-DC-Token": helper.token}
        if body is not None:
            hdr["Origin"] = f"http://127.0.0.1:{helper.port}"
        return self.call(helper, "POST" if body is not None else "GET", "/api/" + path, body, hdr)

    def comment(self, helper, body="Make it bigger"):
        t = reviews.now()
        return {"id": f"{helper.me['slug']}-abc123", "screen": "today", "anchor": {"dc": "add-button"}, "tokens": {},
                "body": body, "author": "whoever", "created": t, "modified": t}

    # ------------------------------------------------------------------
    def test_security_checks(self):
        h = self.start(self.sam)
        tok = {"X-DC-Token": h.token}
        good_origin = {"Origin": f"http://127.0.0.1:{h.port}"}
        self.assertEqual(self.call(h, "GET", "/api/state")[0], 403, "no token")
        self.assertEqual(self.call(h, "GET", "/api/state", headers=tok)[0], 200)
        self.assertEqual(self.call(h, "GET", "/api/state", headers=tok, host=f"localhost:{h.port}")[0], 200)
        self.assertEqual(self.call(h, "GET", "/api/state", headers=tok, host=f"evil.example:{h.port}")[0], 403, "DNS rebinding")
        self.assertEqual(self.call(h, "GET", "/canvas.html", host="evil.example")[0], 403)
        self.assertEqual(self.call(h, "GET", "/api/state", headers={**tok, "Origin": "http://evil.example"})[0], 403)
        self.assertEqual(self.call(h, "POST", "/api/end-review", {}, tok)[0], 403, "POST needs an Origin")
        self.assertEqual(self.call(h, "POST", "/api/end-review", {}, {**tok, "Origin": f"http://127.1:{h.port}"})[0], 403)
        self.assertEqual(self.call(h, "POST", "/api/end-review", {}, {"X-DC-Token": "guess", **good_origin})[0], 403)
        self.assertEqual(self.call(h, "POST", "/api/save", None, {**tok, **good_origin, "Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.call(h, "OPTIONS", "/api/save", None, {"Origin": "http://evil.example"})[0], 405)
        status, page = self.call(h, "GET", "/canvas.html")
        self.assertEqual(status, 200)
        self.assertIn(h.token, page)
        self.assertNotIn(h.token, self.call(h, "GET", "/guide.html")[1])
        self.assertNotIn(h.token, (self.sam / "design-canvas" / "out" / "canvas.html").read_text(encoding="utf-8"))

    def test_save_writes_only_your_own_file(self):
        h = self.start(self.sam)
        status, r = self.api(h, "save", {"comments": [self.comment(h)], "updates": []})
        self.assertEqual((status, r["ok"]), (200, True))
        files = sorted(p.name for p in (self.sam / "design-canvas" / "reviews").iterdir())
        self.assertEqual(files, [f"{h.me['slug']}.json"])
        saved = json.loads((self.sam / "design-canvas" / "reviews" / files[0]).read_text(encoding="utf-8"))
        self.assertEqual(saved["comments"][0]["author"], "Sam", "author is set by the helper, not the page")
        bad = self.comment(h)
        bad["id"] = "alex-0000-abc123"
        self.assertEqual(self.api(h, "save", {"comments": [bad], "updates": []})[0], 400)

    def test_end_review_commits_only_the_review_file_and_pushes(self):
        h = self.start(self.sam)
        theme = self.sam / "design-canvas" / "app" / "src" / "theme.ts"
        theme.write_text(theme.read_text(encoding="utf-8") + "// unrelated work\n", encoding="utf-8")
        git(self.sam, "add", str(theme))
        self.api(h, "save", {"comments": [self.comment(h)], "updates": []})
        status, r = self.api(h, "end-review", {})
        self.assertTrue(r["ok"], r)
        files = git(self.tmp / "remote.git", "show", "--name-only", "--format=", "main").splitlines()
        self.assertEqual(files, [f"design-canvas/reviews/{h.me['slug']}.json"])
        self.assertIn("M  design-canvas/app/src/theme.ts", git(self.sam, "status", "--short"), "other staged work is untouched")
        self.assertEqual(self.api(h, "end-review", {})[1]["message"], "Nothing new to send: your review is already pushed.")

    def test_remote_moved_with_other_changes_explains_then_combines_once_clean(self):
        h = self.start(self.sam)
        alex = self.clone("alex", "Alex")
        (alex / "NOTES.md").write_text("alex was here\n", encoding="utf-8")
        git(alex, "add", "NOTES.md")
        git(alex, "commit", "-qm", "alex")
        git(alex, "push", "-q")
        theme = self.sam / "design-canvas" / "app" / "src" / "theme.ts"
        theme.write_text(theme.read_text(encoding="utf-8") + "// unrelated work\n", encoding="utf-8")
        self.api(h, "save", {"comments": [self.comment(h)], "updates": []})
        r = self.api(h, "end-review", {})[1]
        self.assertFalse(r["ok"])
        self.assertIn("Someone else pushed first", r["message"])
        self.assertIn("committed on this computer", r["message"])
        git(self.sam, "checkout", "--", str(theme))
        r = self.api(h, "end-review", {})[1]
        self.assertTrue(r["ok"], r)
        self.assertIn("combined", r["message"])
        log = git(self.tmp / "remote.git", "log", "--format=%an", "main").splitlines()
        self.assertEqual(log[:2], ["Sam", "Alex"], "rebased on top, nothing force-pushed")

    def test_get_latest_fast_forwards_and_rebuilds(self):
        h = self.start(self.sam)
        alex = self.clone("alex", "Alex")
        me = reviews.identity(alex / "design-canvas")
        reviews.save_mine(alex / "design-canvas", me, [{**self.comment(h), "id": f"{me['slug']}-zz9988"}], [], "Acme Habits")
        git(alex, "add", "-A")
        git(alex, "commit", "-qm", "alex review")
        git(alex, "push", "-q")
        r = self.api(h, "get-latest", {})[1]
        self.assertTrue(r["ok"], r)
        self.assertIn("1 new commit", r["message"])
        self.assertIn(f"{me['slug']}-zz9988", (self.sam / "design-canvas" / "out" / "canvas.html").read_text(encoding="utf-8"))
        self.assertEqual(self.api(h, "get-latest", {})[1]["message"], "You're up to date.")

    def test_not_a_git_repo_offers_the_file_instead(self):
        plain = self.tmp / "plain"
        shutil.copytree(SAMPLE, plain / "design-canvas", ignore=shutil.ignore_patterns("out", "reviews"))
        d = Design(plain / "design-canvas")
        server, h = serve.start(d, d.root, 0, False, "Sam", build.build_all, build.script_json)
        self.servers.append(server)
        r = self.api(h, "end-review", {})[1]
        self.assertFalse(r["ok"])
        self.assertIn("Download review file", r["message"])


if __name__ == "__main__":
    unittest.main()

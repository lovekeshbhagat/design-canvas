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
import unicodedata
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

    def test_end_review_wont_push_other_unpushed_commits(self):
        h = self.start(self.sam)
        (self.sam / "NOTES.md").write_text("draft\n", encoding="utf-8")
        git(self.sam, "add", "NOTES.md")
        git(self.sam, "commit", "-qm", "local work")
        before = git(self.tmp / "remote.git", "rev-parse", "main")
        self.api(h, "save", {"comments": [self.comment(h)], "updates": []})
        r = self.api(h, "end-review", {})[1]
        self.assertFalse(r["ok"])
        self.assertIn("NOTES.md", r["message"])
        self.assertEqual(git(self.tmp / "remote.git", "rev-parse", "main"), before, "nothing was pushed")
        self.assertIn(f"?? design-canvas/reviews/{h.me['slug']}.json", git(self.sam, "status", "--porcelain", "-uall"),
                      "the review file wasn't committed either")
        git(self.sam, "push", "-q")
        r = self.api(h, "end-review", {})[1]
        self.assertTrue(r["ok"], r)
        files = git(self.tmp / "remote.git", "show", "--name-only", "--format=", "main").splitlines()
        self.assertEqual(files, [f"design-canvas/reviews/{h.me['slug']}.json"])

    def test_push_settings_cannot_widen_or_force_end_review(self):
        alex = self.clone("alex", "Alex")
        git(alex, "switch", "-q", "-c", "side")
        (alex / "SIDE.md").write_text("alex's branch\n", encoding="utf-8")
        git(alex, "add", "SIDE.md")
        git(alex, "commit", "-qm", "alex side")
        git(alex, "push", "-q", "origin", "side")
        alex_side = git(alex, "rev-parse", "HEAD")
        git(self.sam, "fetch", "-q")
        git(self.sam, "switch", "-q", "-c", "side", "main")  # diverges from the remote's side: pushing it needs a force
        (self.sam / "SIDE.md").write_text("sam's other work\n", encoding="utf-8")
        git(self.sam, "add", "SIDE.md")
        git(self.sam, "commit", "-qm", "sam side")
        git(self.sam, "switch", "-q", "main")
        git(self.sam, "tag", "-a", "v9", "-m", "a local tag")
        git(self.sam, "config", "push.default", "matching")
        git(self.sam, "config", "push.followTags", "true")
        git(self.sam, "config", "remote.origin.push", "+refs/heads/*:refs/heads/*")
        h = self.start(self.sam)
        self.api(h, "save", {"comments": [self.comment(h)], "updates": []})
        r = self.api(h, "end-review", {})[1]
        self.assertTrue(r["ok"], r)
        remote = self.tmp / "remote.git"
        self.assertEqual(git(remote, "rev-parse", "side"), alex_side, "another branch was neither pushed nor forced")
        self.assertEqual(git(remote, "tag"), "", "no tags were pushed")
        self.assertEqual(git(remote, "show", "--name-only", "--format=", "main").splitlines(), [f"design-canvas/reviews/{h.me['slug']}.json"])

    def test_unpushed_merge_commit_that_adds_a_file_is_caught(self):
        h = self.start(self.sam)
        git(self.sam, "switch", "-q", "-c", "x")
        self.api(h, "save", {"comments": [self.comment(h)], "updates": []})
        rel = f"design-canvas/reviews/{h.me['slug']}.json"
        git(self.sam, "add", "--", rel)
        git(self.sam, "commit", "-qm", "review only")
        git(self.sam, "switch", "-q", "main")
        git(self.sam, "merge", "-q", "--no-ff", "--no-commit", "x")
        (self.sam / "EXTRA.md").write_text("slipped into the merge\n", encoding="utf-8")
        git(self.sam, "add", "EXTRA.md")
        git(self.sam, "commit", "-qm", "merge x")
        before = git(self.tmp / "remote.git", "rev-parse", "main")
        r = self.api(h, "end-review", {})[1]
        self.assertFalse(r["ok"])
        self.assertIn("is a merge", r["message"])
        self.assertEqual(git(self.tmp / "remote.git", "rev-parse", "main"), before)

    def test_retry_works_in_a_folder_with_an_accent(self):
        git(self.sam, "mv", "design-canvas", "café")
        git(self.sam, "commit", "-qm", "rename")
        git(self.sam, "push", "-q")
        d = Design(self.sam / "café")
        server, h = serve.start(d, d.root, 0, False, None, build.build_all, build.script_json)
        self.servers.append(server)
        self.api(h, "save", {"comments": [self.comment(h)], "updates": []})
        rel = f"café/reviews/{h.me['slug']}.json"
        git(self.sam, "add", "--", rel)
        git(self.sam, "commit", "-qm", "review committed, but its push failed")  # what End review leaves after a failed push
        r = self.api(h, "end-review", {})[1]
        self.assertTrue(r["ok"], r)
        self.assertEqual(git(self.tmp / "remote.git", "show", "-z", "--name-only", "--format=", "main").strip("\0\n"), rel)

    def refused(self, h, why):
        before = git(self.tmp / "remote.git", "rev-parse", "main")
        self.api(h, "save", {"comments": [self.comment(h)], "updates": []})
        r = self.api(h, "end-review", {})[1]
        self.assertFalse(r["ok"], r)
        self.assertIn(why, r["message"])
        self.assertEqual(git(self.tmp / "remote.git", "rev-parse", "main"), before, "nothing was pushed")
        return r

    def test_a_commit_pushed_only_to_another_remote_is_not_sent(self):
        git(self.tmp, "init", "-q", "--bare", "private.git")
        git(self.sam, "remote", "add", "private", str(self.tmp / "private.git"))
        (self.sam / "NOTES.md").write_text("only for the private remote\n", encoding="utf-8")
        git(self.sam, "add", "NOTES.md")
        git(self.sam, "commit", "-qm", "private work")
        git(self.sam, "push", "-q", "private", "main")
        git(self.sam, "switch", "-q", "-c", "review/sam")  # no upstream: what the protected-branch advice leads to
        self.refused(self.start(self.sam), "NOTES.md")
        self.assertEqual(git(self.tmp / "remote.git", "branch", "--list", "review/sam"), "")

    def test_a_rewound_remote_branch_is_not_filled_back_in(self):
        alex = self.clone("alex", "Alex")
        (alex / "OOPS.md").write_text("pushed by mistake\n", encoding="utf-8")
        git(alex, "add", "OOPS.md")
        git(alex, "commit", "-qm", "oops")
        git(alex, "push", "-q")
        git(self.sam, "pull", "-q")
        git(alex, "reset", "-q", "--hard", "HEAD~1")
        git(alex, "push", "-q", "-f")  # the remote drops the commit; Sam's origin/main still has it
        self.refused(self.start(self.sam), "OOPS.md")

    def test_a_replace_ref_cannot_hide_a_commit(self):
        (self.sam / "NOTES.md").write_text("hidden\n", encoding="utf-8")
        git(self.sam, "add", "NOTES.md")
        git(self.sam, "commit", "-qm", "hidden work")
        git(self.sam, "replace", "HEAD", "origin/main")
        self.refused(self.start(self.sam), "NOTES.md")

    def test_an_empty_commit_is_not_sent(self):
        git(self.sam, "commit", "-q", "--allow-empty", "-m", "empty")
        self.refused(self.start(self.sam), "changes nothing")

    def test_a_remote_that_pushes_elsewhere_is_refused(self):
        git(self.tmp, "init", "-q", "--bare", "other.git")
        git(self.sam, "config", "remote.origin.pushurl", str(self.tmp / "other.git"))
        self.refused(self.start(self.sam), "pushes somewhere other")
        self.assertEqual(git(self.tmp / "other.git", "branch"), "")

    @unittest.skipIf(os.name == "nt", "shell hook")
    def test_a_commit_made_by_a_hook_is_not_sent(self):
        hook = self.sam / ".git" / "hooks" / "post-commit"
        hook.write_text("#!/bin/sh\necho sneaky > SNEAKY.md\ngit add SNEAKY.md\n"
                        "git -c core.hooksPath=/dev/null commit -q -m sneaky\n", encoding="utf-8")
        hook.chmod(0o755)
        self.refused(self.start(self.sam), "SNEAKY.md")

    def feature_merged_into_sams_main(self):
        alex = self.clone("alex", "Alex")
        git(alex, "switch", "-q", "-c", "feature/redesign")
        (alex / "UNREVIEWED.md").write_text("not reviewed yet\n", encoding="utf-8")
        git(alex, "add", "UNREVIEWED.md")
        git(alex, "commit", "-qm", "unreviewed")
        git(alex, "push", "-q", "origin", "feature/redesign")
        git(self.sam, "fetch", "-q")
        git(self.sam, "merge", "-q", "--ff-only", "origin/feature/redesign")
        return alex

    def test_another_branchs_commit_is_not_sent_to_this_branch(self):
        self.feature_merged_into_sams_main()
        head = git(self.sam, "rev-parse", "HEAD")
        self.refused(self.start(self.sam), "UNREVIEWED.md")
        self.assertEqual(git(self.sam, "rev-parse", "HEAD"), head, "nothing committed or rebased")

    def test_another_branchs_commit_is_not_rebased_when_the_remote_moved(self):
        alex = self.feature_merged_into_sams_main()
        git(alex, "switch", "-q", "main")
        (alex / "NEWS.md").write_text("pushed to main\n", encoding="utf-8")
        git(alex, "add", "NEWS.md")
        git(alex, "commit", "-qm", "news")
        git(alex, "push", "-q")
        head = git(self.sam, "rev-parse", "HEAD")
        self.refused(self.start(self.sam), "UNREVIEWED.md")
        self.assertEqual(git(self.sam, "rev-parse", "HEAD"), head, "nothing committed or rebased")

    def test_a_rewind_during_the_push_does_not_rebase_other_commits(self):
        alex = self.clone("alex", "Alex")
        (alex / "OOPS.md").write_text("will be dropped\n", encoding="utf-8")
        git(alex, "add", "OOPS.md")
        git(alex, "commit", "-qm", "oops")
        git(alex, "push", "-q")
        oops = git(alex, "rev-parse", "HEAD")
        git(self.sam, "pull", "-q")
        h = self.start(self.sam)
        real_push = h._push

        def push_after_a_rewind(*a, **kw):  # someone rewinds main between the check and the push
            h._push = real_push
            git(alex, "reset", "-q", "--hard", "HEAD~1")
            (alex / "NEWS.md").write_text("new\n", encoding="utf-8")
            git(alex, "add", "NEWS.md")
            git(alex, "commit", "-qm", "news")
            git(alex, "push", "-q", "-f")
            return real_push(*a, **kw)

        h._push = push_after_a_rewind
        self.api(h, "save", {"comments": [self.comment(h)], "updates": []})
        r = self.api(h, "end-review", {})[1]
        self.assertFalse(r["ok"], r)
        self.assertIn("Nothing was combined or pushed", r["message"])
        self.assertIn("OOPS.md", r["message"])
        self.assertEqual(git(self.sam, "rev-parse", "HEAD~1"), oops, "Sam's review commit still sits on the original commit: nothing was rebased")
        self.assertNotIn("OOPS.md", git(self.tmp / "remote.git", "show", "--name-only", "--format=", "main"))

    def test_a_lookalike_unicode_path_is_another_file(self):
        git(self.sam, "mv", "design-canvas", "caf\u00e9")
        git(self.sam, "commit", "-qm", "rename")
        git(self.sam, "push", "-q")
        git(self.sam, "config", "core.precomposeunicode", "false")
        d = Design(self.sam / "caf\u00e9")
        server, h = serve.start(d, d.root, 0, False, None, build.build_all, build.script_json)
        self.servers.append(server)
        self.api(h, "save", {"comments": [self.comment(h)], "updates": []})
        rel = f"caf\u00e9/reviews/{h.me['slug']}.json"
        blob = git(self.sam, "hash-object", "-w", "--", rel)
        twin = unicodedata.normalize("NFD", rel)
        git(self.sam, "update-index", "--add", "--cacheinfo", f"100644,{blob},{twin}")
        git(self.sam, "commit", "-qm", "a look-alike path")
        before = git(self.tmp / "remote.git", "rev-parse", "main")
        r = self.api(h, "end-review", {})[1]
        self.assertFalse(r["ok"], r)
        self.assertEqual(git(self.tmp / "remote.git", "rev-parse", "main"), before)

    def test_a_submodule_change_is_caught_even_with_ignore_all(self):
        seed_sha = git(self.sam, "rev-parse", "HEAD")
        (self.sam / ".gitmodules").write_text('[submodule "vendor/lib"]\n\tpath = vendor/lib\n\turl = ./lib.git\n'
                                              "\tignore = all\n", encoding="utf-8")
        git(self.sam, "add", ".gitmodules")
        git(self.sam, "update-index", "--add", "--cacheinfo", f"160000,{seed_sha},vendor/lib")
        git(self.sam, "commit", "-qm", "add a submodule")
        git(self.sam, "push", "-q")
        h = self.start(self.sam)
        self.api(h, "save", {"comments": [self.comment(h)], "updates": []})
        git(self.sam, "add", "--", f"design-canvas/reviews/{h.me['slug']}.json")
        git(self.sam, "update-index", "--cacheinfo", f"160000,{'1' * 40},vendor/lib")
        git(self.sam, "commit", "-qm", "wip")  # the review file and a submodule move in one commit
        before = git(self.tmp / "remote.git", "rev-parse", "main")
        r = self.api(h, "end-review", {})[1]
        self.assertFalse(r["ok"], r)
        self.assertIn("vendor/lib", r["message"])
        self.assertEqual(git(self.tmp / "remote.git", "rev-parse", "main"), before)

    def test_a_grafts_file_is_refused(self):
        (self.sam / ".git" / "info").mkdir(exist_ok=True)
        (self.sam / ".git" / "info" / "grafts").write_text("", encoding="utf-8")
        self.refused(self.start(self.sam), "grafts")

    def test_a_folder_name_with_glob_characters_is_taken_literally(self):
        git(self.sam, "mv", "design-canvas", "ui[1]")
        git(self.sam, "commit", "-qm", "rename")
        git(self.sam, "push", "-q")
        d = Design(self.sam / "ui[1]")
        server, h = serve.start(d, d.root, 0, False, None, build.build_all, build.script_json)
        self.servers.append(server)
        decoy = self.sam / "ui1" / "reviews" / f"{h.me['slug']}.json"
        decoy.parent.mkdir(parents=True)
        decoy.write_text("{}", encoding="utf-8")  # matches ui[1]/... if the path were read as a glob
        self.api(h, "save", {"comments": [self.comment(h)], "updates": []})
        r = self.api(h, "end-review", {})[1]
        self.assertTrue(r["ok"], r)
        self.assertEqual(git(self.tmp / "remote.git", "show", "--name-only", "--format=", "main").splitlines(),
                         [f"ui[1]/reviews/{h.me['slug']}.json"])

    def test_get_latest_never_stashes_or_rebases(self):
        for name, settings in (("s1", {"pull.rebase": "true", "rebase.autoStash": "true"}),
                               ("s2", {"pull.rebase": "false", "merge.autoStash": "true"})):
            with self.subTest(settings=settings):
                me = self.clone(name, "Sam")
                for k, v in settings.items():
                    git(me, "config", k, v)
                alex = self.clone(name + "-alex", "Alex")
                theme_a = alex / "design-canvas" / "app" / "src" / "theme.ts"
                theme_a.write_text(theme_a.read_text(encoding="utf-8") + "// alex\n", encoding="utf-8")
                git(alex, "commit", "-qam", "alex theme")
                git(alex, "push", "-q")
                theme = me / "design-canvas" / "app" / "src" / "theme.ts"
                theme.write_text(theme.read_text(encoding="utf-8") + "// my unsaved edit\n", encoding="utf-8")
                r = self.api(self.start(me), "get-latest", {})[1]
                self.assertFalse(r["ok"], r)
                self.assertIn("Commit or stash them first", r["message"])
                self.assertEqual(git(me, "stash", "list"), "", "nothing was stashed")
                self.assertIn("// my unsaved edit", theme.read_text(encoding="utf-8"))

    def test_a_new_review_is_sent_when_git_hides_untracked_files(self):
        git(self.sam, "config", "status.showUntrackedFiles", "no")
        h = self.start(self.sam)
        self.api(h, "save", {"comments": [self.comment(h)], "updates": []})
        r = self.api(h, "end-review", {})[1]
        self.assertTrue(r["ok"], r)
        self.assertNotIn("already pushed", r["message"])
        self.assertEqual(git(self.tmp / "remote.git", "show", "--name-only", "--format=", "main").splitlines(),
                         [f"design-canvas/reviews/{h.me['slug']}.json"])

    def test_an_ignored_review_file_is_reported_not_called_sent(self):
        (self.sam / ".git" / "info").mkdir(exist_ok=True)
        (self.sam / ".git" / "info" / "exclude").write_text("*.json\n", encoding="utf-8")
        r = self.refused(self.start(self.sam), "ignored by git")
        self.assertNotIn("already pushed", r["message"])

    def test_ssh_always_runs_in_batch_mode(self):
        git(self.sam, "config", "core.sshCommand", "ssh -i ~/.ssh/other_key")
        self.assertEqual(self.start(self.sam).ssh, "ssh -i ~/.ssh/other_key -o BatchMode=yes")
        git(self.sam, "config", "--unset", "core.sshCommand")
        self.assertEqual(self.start(self.sam).ssh, "ssh -o BatchMode=yes")
        os.environ["GIT_SSH_COMMAND"] = "ssh -F /dev/null"
        self.assertEqual(self.start(self.sam).ssh, "ssh -F /dev/null -o BatchMode=yes")

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

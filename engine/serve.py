"""The local review helper: `python3 engine/build.py <design-dir> --serve`.

Runs on one person's own computer (127.0.0.1 only). It serves the built pages, saves that
person's comments into their own review file, and turns two buttons into git:
  End review   commit only their review file (no hooks, no signing) and push
  Get latest   pull --ff-only and rebuild the pages
Git is what shares reviews between people; there is no shared server.

Security, because this helper can commit and push:
  - bound to 127.0.0.1; the Host header must be exactly 127.0.0.1:<port> or localhost:<port>
  - every /api request needs the per-run token (X-DC-Token, constant-time compare);
    POSTs also need an exact Origin match; no CORS headers are ever sent
  - the API takes no paths and no commands; JSON bodies of at most 1 MB
  - the token is never logged; git never prompts (no terminal, no askpass, ssh BatchMode)
  - commits only the person's own review file, never force-pushes, never rewrites history
  - refuses to push when the branch has other unpushed commits that change other files
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import reviews

MAX_BODY = 1_000_000
LOCK = threading.Lock()


def _say(msg: str) -> str:
    """git output, made safe to show in the page."""
    return reviews.clean(msg, 600, multiline=True).strip()


class Helper:
    def __init__(self, d, root: Path, port: int, web: bool, me: dict, build_all, script_json):
        self.d, self.root, self.port, self.web, self.me = d, root, port, web, me
        self.build_all, self.script_json = build_all, script_json
        self.out = d.dir / "out"
        self.token = secrets.token_urlsafe(32)
        self.hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        self.origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
        top = self._run(["git", "-C", str(d.dir), "rev-parse", "--show-toplevel"], cwd=None)
        self.repo = Path(top.stdout.strip()).resolve() if top and top.returncode == 0 and top.stdout.strip() else None
        self.last_save = 0.0

    # ---------------------------------------------------------- git
    def _env(self):
        env = dict(os.environ)
        env.update(GIT_TERMINAL_PROMPT="0", GIT_ASKPASS="design-canvas-no-askpass", SSH_ASKPASS="design-canvas-no-askpass",
                   GCM_INTERACTIVE="never", LC_ALL="C")
        if "GIT_SSH_COMMAND" not in env:
            p = self._run(["git", "config", "core.sshCommand"], cwd=self.repo, env=None) if getattr(self, "repo", None) else None
            if not (p and p.stdout.strip()):
                env["GIT_SSH_COMMAND"] = "ssh -o BatchMode=yes"
        return env

    @staticmethod
    def _run(cmd, cwd=None, env=None, timeout=60):
        try:
            return subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=env, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=timeout)
        except (OSError, subprocess.SubprocessError):
            return None

    def git(self, *args, timeout=60):
        p = self._run(["git", *args], cwd=self.repo, env=self._env(), timeout=timeout)
        if p is None:
            return subprocess.CompletedProcess(args, 1, "", "git did not finish (timed out or could not start)")
        return p

    def my_rel(self) -> str | None:
        if not self.repo:
            return None
        return reviews.my_file(self.d.dir, self.me).resolve().relative_to(self.repo).as_posix()

    def git_state(self) -> dict:
        if not self.repo:
            return {"repo": False, "why": "This folder is not in a git repository, so reviews can't be sent with git. Use Download review file."}
        st = {"repo": True}
        br = self.git("symbolic-ref", "--short", "-q", "HEAD")
        st["branch"] = br.stdout.strip() if br.returncode == 0 else None
        st["detached"] = br.returncode != 0
        up = self.git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
        st["upstream"] = up.stdout.strip() if up.returncode == 0 else None
        st["remotes"] = [r for r in self.git("remote").stdout.split() if r]
        st["ahead"] = st["behind"] = 0
        if st["upstream"]:
            lr = self.git("rev-list", "--left-right", "--count", "HEAD...@{u}").stdout.split()
            if len(lr) == 2:
                st["ahead"], st["behind"] = int(lr[0]), int(lr[1])
        rel = self.my_rel()
        st["file"] = rel
        st["unsent"] = bool(rel and self.git("status", "--porcelain", "--", rel).stdout.strip())
        gd = self.git("rev-parse", "--git-dir").stdout.strip()
        gdir = (self.repo / gd) if gd and not os.path.isabs(gd) else Path(gd or ".")
        st["busy"] = any((gdir / x).exists() for x in ("rebase-merge", "rebase-apply", "MERGE_HEAD", "CHERRY_PICK_HEAD"))
        return st

    # ---------------------------------------------------------- actions
    def state(self) -> dict:
        raw_c, raw_u, files, errors = reviews.load_raw(self.d.dir)
        _, unique = reviews.merge(raw_c, raw_u)
        try:
            mine_c, mine_u = reviews.read_mine(self.d.dir, self.me)
        except reviews.ReviewError:
            mine_c, mine_u = [], []
        return {"ok": True, "me": self.me, "git": self.git_state(), "comments": [reviews.public(c) for c in raw_c],
                "updates": unique, "mine": {"comments": [reviews.public(c) for c in mine_c], "updates": mine_u}, "skipped": errors}

    def save(self, body: dict) -> dict:
        now = time.monotonic()
        if now - self.last_save < 0.3:
            time.sleep(0.3)  # gentle cap on runaway autosave
        with LOCK:
            f = reviews.save_mine(self.d.dir, self.me, body.get("comments", []), body.get("updates", []), self.d.name)
            self.last_save = time.monotonic()
        return {"ok": True, "file": f.name, "git": self.git_state()}

    def _unpushed_paths(self, st: dict) -> set:
        """Every file changed by the commits a push would send now (paths from the repo root)."""
        rng = ["@{u}..HEAD"] if st["upstream"] else ["HEAD", "--not", "--remotes"]
        out = self.git("log", "--format=", "--name-only", "--no-renames", *rng).stdout
        return {line.strip() for line in out.splitlines() if line.strip()}

    def _precheck(self, need_upstream: bool):
        st = self.git_state()
        if not st["repo"]:
            return st, st["why"]
        if st["detached"]:
            return st, "This copy isn't on a branch (detached HEAD). Switch to a branch, then try again."
        if st["busy"]:
            return st, "git is in the middle of a merge or rebase in this copy. Finish or abort it first."
        if not st["remotes"]:
            return st, "This copy has no remote to push to. Use Download review file instead."
        if need_upstream and not st["upstream"]:
            return st, f"The branch {st['branch']} isn't tracking a remote branch yet. Push it once with git, then try again."
        return st, None

    def end_review(self) -> dict:
        with LOCK:
            st, problem = self._precheck(need_upstream=False)
            if problem:
                return {"ok": False, "message": problem, "git": st}
            rel = st["file"]
            if not (self.repo / rel).exists():
                return {"ok": False, "message": "You haven't written anything yet.", "git": st}
            other = sorted(self._unpushed_paths(st) - {rel})
            if other:
                more = f" and {len(other) - 1} more" if len(other) > 1 else ""
                return {"ok": False, "message": "End review only sends your review file, but this branch also has commits that "
                        f"aren't pushed yet and change other files ({_say(other[0])}{more}). Push those yourself first, or review "
                        "on a fresh branch, then press End review again.", "git": st}
            committed = False
            if st["unsent"]:
                c, u = reviews.read_mine(self.d.dir, self.me)
                msg = f"design-canvas: review by {self.me['name']} ({len(c)} comments, {len(u)} updates)"
                add = self.git("add", "--", rel)
                cm = self.git("-c", "commit.gpgsign=false", "commit", "--no-verify", "--only", "-m", msg, "--", rel) if add.returncode == 0 else add
                if cm.returncode != 0:
                    return {"ok": False, "message": "Couldn't commit your review file: " + _say(cm.stderr or cm.stdout), "git": self.git_state()}
                committed = True
            elif st["upstream"] and st["ahead"] == 0:
                return {"ok": True, "message": "Nothing new to send: your review is already pushed.", "git": st}
            push = self.git("push", timeout=120) if st["upstream"] else self.git("push", "-u", st["remotes"][0] if "origin" not in st["remotes"] else "origin", "HEAD", timeout=120)
            if push.returncode == 0:
                return {"ok": True, "message": f"Review sent: pushed to {self.git_state()['upstream'] or 'the remote'}.", "git": self.git_state()}
            err = (push.stderr or push.stdout).lower()
            kept = " Your comments are saved and committed on this computer." if committed or not st["unsent"] else ""
            if "protected" in err or "denied" in err or "declined" in err or "pre-receive hook" in err:
                return {"ok": False, "message": "The remote refused this branch (it may be protected). Switch to a review branch "
                        "(git switch -c review/your-name), press End review again, then open a pull request." + kept, "git": self.git_state()}
            if "authentication" in err or "could not read" in err or "permission" in err or "terminal prompts disabled" in err or "publickey" in err:
                return {"ok": False, "message": "git couldn't sign in to the remote from here. Push once from a terminal "
                        "(or set up your git credentials), then try again." + kept, "git": self.git_state()}
            if "non-fast-forward" in err or "fetch first" in err or "rejected" in err:
                if self.git("status", "--porcelain", "--untracked-files=no").stdout.strip():
                    return {"ok": False, "message": "Someone else pushed first, and this copy has other changes, so I won't combine "
                            "them automatically. Put your other changes aside (git stash), press End review again to combine your "
                            "review with theirs, then bring your changes back (git stash pop)." + kept, "git": self.git_state()}
                pull = self.git("pull", "--rebase", "--no-autostash", timeout=120)
                if pull.returncode != 0:
                    self.git("rebase", "--abort")
                    return {"ok": False, "message": "Someone else pushed first, and their changes couldn't be combined with yours "
                            "automatically. Ask your developer to pull and push." + kept, "git": self.git_state()}
                again = self.git("push", timeout=120)
                if again.returncode == 0:
                    self._rebuild()
                    return {"ok": True, "message": "Review sent (combined with newer changes from the remote first).", "reload": True, "git": self.git_state()}
                return {"ok": False, "message": "Push failed after getting the latest changes: " + _say(again.stderr) + kept, "git": self.git_state()}
            return {"ok": False, "message": "Push failed: " + _say(push.stderr or push.stdout) + kept, "git": self.git_state()}

    def get_latest(self) -> dict:
        with LOCK:
            st, problem = self._precheck(need_upstream=True)
            if problem:
                return {"ok": False, "message": problem, "git": st}
            before = self.git("rev-parse", "HEAD").stdout.strip()
            pull = self.git("pull", "--ff-only", timeout=120)
            if pull.returncode != 0:
                err = (pull.stderr or pull.stdout).lower()
                if "would be overwritten" in err or "your local changes" in err:
                    msg = "Your copy has unsaved changes in files that the latest version also changed. Commit or stash them first."
                elif "not possible to fast-forward" in err or "diverg" in err:
                    msg = ("Your copy and the remote have both moved on. Press End review: it sends your review and combines "
                           "it with theirs (it needs your other changes committed or stashed first).")
                else:
                    msg = "Couldn't get the latest: " + _say(pull.stderr or pull.stdout)
                return {"ok": False, "message": msg, "git": self.git_state()}
            after = self.git("rev-parse", "HEAD").stdout.strip()
            n = int(self.git("rev-list", "--count", f"{before}..{after}").stdout.strip() or 0) if before and after and before != after else 0
            self._rebuild()
            return {"ok": True, "message": "You're up to date." if n == 0 else f"Got {n} new commit{'s' if n != 1 else ''}; the pages are rebuilt.",
                    "reload": n > 0, "git": self.git_state()}

    def _rebuild(self):
        self.build_all(self.d, self.root, self.out, self.web)


def make_handler(helper: Helper):
    class Handler(SimpleHTTPRequestHandler):
        server_version = "design-canvas"
        sys_version = ""

        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(helper.out), **kw)

        def log_message(self, fmt, *args):  # never log URLs, headers or the token
            pass

        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            super().end_headers()

        def _json(self, code: int, obj: dict):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _host_ok(self) -> bool:
            if self.headers.get("Host") not in helper.hosts:
                self._json(403, {"ok": False, "message": "wrong host"})
                return False
            return True

        def _api_ok(self, post: bool) -> bool:
            origin = self.headers.get("Origin")
            if (post and origin not in helper.origins) or (origin is not None and origin not in helper.origins):
                self._json(403, {"ok": False, "message": "wrong origin"})
                return False
            if not secrets.compare_digest(self.headers.get("X-DC-Token", ""), helper.token):
                self._json(403, {"ok": False, "message": "missing or wrong token"})
                return False
            return True

        def do_GET(self):
            if not self._host_ok():
                return
            path = self.path.split("?", 1)[0]
            if path.startswith("/api/"):
                if not self._api_ok(post=False):
                    return
                if path == "/api/state":
                    return self._json(200, helper.state())
                return self._json(404, {"ok": False, "message": "not found"})
            if path in ("/", "/index.html"):
                self.send_response(302)
                self.send_header("Location", "/canvas.html")
                return self.end_headers()
            if path == "/canvas.html":
                f = helper.out / "canvas.html"
                if not f.exists():
                    return self._json(404, {"ok": False, "message": "canvas not built"})
                inject = "<script>window.DC_SERVE = " + helper.script_json({"token": helper.token, "me": helper.me}) + ";</script>"
                html = f.read_text(encoding="utf-8").replace("</head>", inject + "\n</head>", 1).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html)))
                self.end_headers()
                return self.wfile.write(html)
            return super().do_GET()

        def do_HEAD(self):
            if self._host_ok():
                super().do_HEAD()

        def list_directory(self, path):
            self.send_error(404)
            return None

        def do_POST(self):
            if not self._host_ok() or not self._api_ok(post=True):
                return
            if "application/json" not in (self.headers.get("Content-Type") or ""):
                return self._json(415, {"ok": False, "message": "send JSON"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = -1
            if not 0 <= n <= MAX_BODY:
                return self._json(413, {"ok": False, "message": "too large"})
            try:
                body = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            except (ValueError, UnicodeDecodeError):
                return self._json(400, {"ok": False, "message": "bad JSON"})
            if not isinstance(body, dict):
                return self._json(400, {"ok": False, "message": "bad JSON"})
            try:
                path = self.path.split("?", 1)[0]
                if path == "/api/save":
                    return self._json(200, helper.save(body))
                if path == "/api/end-review":
                    return self._json(200, helper.end_review())
                if path == "/api/get-latest":
                    return self._json(200, helper.get_latest())
                return self._json(404, {"ok": False, "message": "not found"})
            except reviews.ReviewError as e:
                return self._json(400, {"ok": False, "message": str(e)})

        def _no(self):
            self._json(405, {"ok": False, "message": "not allowed"})

        do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _no

    return Handler


def start(d, root: Path, port: int, web: bool, as_name, build_all, script_json):
    """Build, then start the helper in a background thread. Returns (server, helper). Used by run() and tests."""
    me = reviews.identity(d.dir, as_name)
    helper = Helper(d, root, port, web, me, build_all, script_json)
    helper._rebuild()
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(helper))
    helper.port = server.server_address[1]
    helper.hosts = {f"127.0.0.1:{helper.port}", f"localhost:{helper.port}"}
    helper.origins = {f"http://127.0.0.1:{helper.port}", f"http://localhost:{helper.port}"}
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, helper


def run(d, root: Path, port: int, web: bool, as_name, build_all, script_json) -> int:
    try:
        server, helper = start(d, root, port, web, as_name, build_all, script_json)
    except reviews.ReviewError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"error: could not use port {port} ({e.strerror}); try --port 8766", file=sys.stderr)
        return 2
    url = f"http://127.0.0.1:{helper.port}/canvas.html"
    print(f"design-canvas review helper for {helper.me['name']}: {url}")
    print("Only this computer can open it. " + ("End review commits and pushes your review file." if helper.repo else
          "Not a git repository: use Download review file to send your review."))
    print("Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        server.shutdown()
        print("stopped")
    return 0

"""design-canvas screens: the screen inventory and coverage, reference screenshots, app images,
the "screen may be out of date" check (git) and one-frame shots (headless Chrome).

Python 3.9+ standard library only. Every path that comes from a design folder goes through
reviews.safe_rel. git and Chrome run as subprocesses with fixed arguments, a timeout and no shell.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import reviews

IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
               ".gif": "image/gif", ".svg": "image/svg+xml"}
SCREENSHOT_TYPES = {k: v for k, v in IMAGE_TYPES.items() if k != ".svg"}
BIG_PAGE = 1024 * 1024  # warn when embedded images add more than this to canvas.html
ID = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")
ASSET_MACRO = re.compile(r"\{\{asset:([^{}\s]+)\}\}")
LEFTOVER_MACRO = re.compile(r"\{\{\s*(?:icon|asset|>)[^{}]*\}\}")


# ---------------------------------------------------------------- source paths
def split_sources(value) -> list:
    """A frame's `source`: one path, a comma-separated list, or a JSON list. Each may end in #Symbol."""
    if not value:
        return []
    items = value if isinstance(value, list) else str(value).split(",")
    return [str(s).strip() for s in items if str(s).strip()]


def source_path(src: str) -> str:
    """'Views/Home.swift#SettingsSheet' -> 'Views/Home.swift'."""
    return src.split("#", 1)[0].strip()


def check_sources(root: Path, sources: list, where: str) -> tuple[list, list]:
    """Keep the sources that are safe paths inside the app root. Returns (kept, problems)."""
    kept, problems = [], []
    for src in sources:
        path = source_path(src)
        hint = " (name a type or view inside a file as path#Symbol)" if "(" in path else ""
        if not reviews.safe_rel(root, path):
            problems.append(f"{where}: source must be a relative path inside the app root ({root}){hint}")
            continue
        if root.is_dir() and not (root / path).exists():
            problems.append(f"{where}: source {path} not found under the app root{hint}")
        kept.append(src)
    return kept, problems


# ---------------------------------------------------------------- inventory and coverage
def load_inventory(cdir: Path, root: Path) -> tuple[list | None, list]:
    """canvas/screens.json: every screen and state the app has, drawn or not.
    Returns (entries or None when there is no inventory, problems)."""
    f = cdir / "screens.json"
    if not f.exists():
        return None, []
    try:
        raw = json.loads(f.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return None, [f"canvas/screens.json: invalid JSON ({e})"]
    items = raw.get("screens") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return None, ["canvas/screens.json: give a \"screens\" list"]
    entries, problems, seen = [], [], set()
    for i, it in enumerate(items):
        if not isinstance(it, dict) or not isinstance(it.get("id"), str) or not ID.match(it["id"]):
            problems.append(f"canvas/screens.json: screens[{i}] needs an id (letters, digits, - _ .), the frame file name when drawn")
            continue
        sid = it["id"]
        if sid in seen:
            problems.append(f"canvas/screens.json: id '{sid}' is listed twice")
            continue
        seen.add(sid)
        sources, probs = check_sources(root, split_sources(it.get("source")), f"canvas/screens.json: {sid}")
        problems += probs
        e = {"id": sid, "name": str(it.get("name") or sid)}
        if it.get("state"):
            e["state"] = str(it["state"])
        if sources:
            e["source"] = ", ".join(sources)
        if it.get("page"):
            e["page"] = str(it["page"])
        entries.append(e)
    return entries, problems


def coverage(entries: list | None, drawn: list) -> dict | None:
    """drawn: the ids of the frames on the canvas. Listed = the inventory plus anything drawn but not listed."""
    if entries is None:
        return None
    listed = {e["id"] for e in entries}
    drawn_set = set(drawn)
    missing = [e for e in entries if e["id"] not in drawn_set]
    return {"drawn": len(drawn_set), "listed": len(drawn_set) + len(missing), "missing": missing,
            "unlisted": [i for i in dict.fromkeys(drawn) if i not in listed]}


def label(e: dict) -> str:
    return e["name"] + (f" ({e['state']})" if e.get("state") and e["state"].lower() != "default" else "")


def coverage_lines(cov: dict | None) -> list:
    if not cov:
        return []
    names = [label(e) for e in cov["missing"]]
    more = f" and {len(names) - 10} more" if len(names) > 10 else ""
    lines = [f"canvas: {cov['drawn']} of {cov['listed']} screens drawn" + (f" · not drawn: {', '.join(names[:10])}{more}" if names else "")]
    if cov["unlisted"]:
        lines.append(f"canvas: {len(cov['unlisted'])} drawn screen(s) not in canvas/screens.json: {', '.join(cov['unlisted'])}")
    return lines


# ---------------------------------------------------------------- images: references and app assets
def data_uri(path: Path) -> str:
    mime = IMAGE_TYPES[path.suffix.lower()]
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def reference(design_dir: Path, rel: str, where: str) -> tuple[str | None, int, list]:
    """A frame's `reference`: a real screenshot of the app, inside the design folder. Returns (data URI, bytes, problems)."""
    if not reviews.safe_rel(design_dir, rel):
        return None, 0, [f"{where}: reference must be a relative path inside the design folder"]
    f = design_dir / rel
    if f.suffix.lower() not in SCREENSHOT_TYPES:
        return None, 0, [f"{where}: reference must be a .png, .jpg, .webp or .gif image"]
    if not f.is_file():
        return None, 0, [f"{where}: reference {rel} not found in the design folder"]
    uri = data_uri(f)
    return uri, len(uri), []


def expand_assets(text: str, assets_dir: Path, where: str, problems: list, sizes: dict) -> str:
    """{{asset:logo.png}} -> a data URI of design-canvas/assets/logo.png (for src="…" or url(…))."""
    def sub(m):
        rel = m.group(1)
        f = assets_dir / rel
        if not reviews.safe_rel(assets_dir, rel) or f.suffix.lower() not in IMAGE_TYPES:
            problems.append(f"{where}: asset {rel} must be an image (.png .jpg .webp .gif .svg) inside assets/")
            return ""
        if not f.is_file():
            problems.append(f"{where}: asset {rel} not found in assets/")
            return ""
        uri = data_uri(f)
        sizes[rel] = sizes.get(rel, 0) + len(uri)
        return uri
    return ASSET_MACRO.sub(sub, text)


def leftover_macros(text: str, where: str) -> list:
    return [f"{where}: {m.group(0)} was not understood (see spec/CANVAS.md)" for m in LEFTOVER_MACRO.finditer(text)]


def size_warning(refs_bytes: int, asset_sizes: dict) -> list:
    total = refs_bytes + sum(asset_sizes.values())
    if total <= BIG_PAGE:
        return []
    return [f"reference screenshots and assets add {total / BIG_PAGE:.1f} MB to canvas.html; "
            "save screenshots at 1x as .jpg or .webp to keep the page small enough to share"]


# ---------------------------------------------------------------- git: screens that may be out of date
def _git(cwd: Path, *args: str, timeout: float = 15) -> str | None:
    try:
        p = subprocess.run(["git", "--literal-pathspecs", "-c", "core.quotepath=off", *args], cwd=str(cwd),
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return p.stdout if p.returncode == 0 else None


def _repo_top(d: Path, cache: dict) -> Path | None:
    """The nearest folder at or above d that holds a .git entry (a repo, worktree or submodule)."""
    seen = []
    for p in (d, *d.parents):
        if p in cache:
            top = cache[p]
            break
        seen.append(p)
        if (p / ".git").exists():
            top = p
            break
    else:
        top = None
    for p in seen:
        cache[p] = top
    return top


def commit_times(paths: list) -> dict:
    """{absolute path: unix time of the newest commit that touched it}. Files that git doesn't
    know (no repo, untracked, no history) are left out. Never raises."""
    by_top: dict = {}
    tops: dict = {}
    for p in {Path(x).resolve() for x in paths}:
        top = _repo_top(p.parent, tops)
        if top is None:
            continue
        try:
            rel = p.relative_to(top).as_posix()
        except ValueError:
            continue
        by_top.setdefault(top, {})[rel] = p
    times: dict = {}
    for top, rels in by_top.items():
        out = _git(top, "log", "--format=%x01%ct", "--name-only", "--", *sorted(rels))
        if out is None:
            continue
        t = None
        for line in out.splitlines():
            if line.startswith("\x01"):
                try:
                    t = int(line[1:].strip())
                except ValueError:
                    t = None
            elif line and t is not None and line in rels and rels[line] not in times:
                times[rels[line]] = t
    return times


def outdated(frames: dict, root: Path) -> list:
    """frames: {screen id: (frame file, [source, ...])}. A screen may be out of date when one of its
    source files has a newer commit than its frame file."""
    paths = []
    for frame_file, sources in frames.values():
        paths.append(frame_file)
        paths += [root / source_path(s) for s in sources]
    if not paths:
        return []
    times = commit_times(paths)
    found = []
    for sid, (frame_file, sources) in frames.items():
        ft = times.get(Path(frame_file).resolve())
        if ft is None:
            continue
        newer = [source_path(s) for s in sources if times.get((root / source_path(s)).resolve(), 0) > ft]
        if newer:
            found.append({"screen": sid, "sources": newer,
                          "message": f"screen '{sid}' may be out of date: {', '.join(newer)} changed after the frame"})
    return found


# ---------------------------------------------------------------- headless Chrome
def find_chrome() -> str | None:
    """CHROME_PATH, then the standard install paths, then chrome/chromium on PATH."""
    env = os.environ.get("CHROME_PATH")
    if env:
        return env if Path(env).is_file() else None
    cands = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
             "/Applications/Chromium.app/Contents/MacOS/Chromium",
             "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
             str(Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome")]
    for var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(var)
        if base:
            cands += [os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"),
                      os.path.join(base, "Chromium", "Application", "chrome.exe"),
                      os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe")]
    for c in cands:
        if Path(c).is_file():
            return c
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome", "microsoft-edge"):
        found = shutil.which(name)
        if found:
            return found
    return None


def no_chrome_message() -> str:
    env = os.environ.get("CHROME_PATH")
    if env:
        return f"CHROME_PATH is set, but there is no browser at {env}"
    return ("no Chrome, Chromium or Edge found. Install one, or set CHROME_PATH to its program file "
            "(for example the 'Google Chrome' file inside Google Chrome.app/Contents/MacOS)")


def chrome(browser: str, profile: Path, page: Path, w: int, h: int, scale: float, extra: list, timeout: float = 90):
    args = [browser, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
            "--no-default-browser-check", "--disable-extensions", f"--user-data-dir={profile}",
            f"--window-size={int(w)},{int(h)}", f"--force-device-scale-factor={scale:g}",
            "--virtual-time-budget=5000", *extra, page.as_uri()]
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, stdin=subprocess.DEVNULL)


def png_size(path: Path) -> tuple[int, int] | None:
    head = path.read_bytes()[:24] if path.is_file() else b""
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")

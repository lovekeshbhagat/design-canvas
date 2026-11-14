"""Canvas tests: the screen inventory and coverage, reference screenshots, app images, system icons,
several sources per screen, screens that may be out of date (git), inspect data, --shoot, and the
canvas in a real browser when one is installed. Every screen here is made up, in a temp folder.
Run from the repo root:  python3 -m unittest discover tests"""

from __future__ import annotations

import base64
import html
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
import build  # noqa: E402
import screens  # noqa: E402
from tokens import Design  # noqa: E402

# a 1x1 PNG, standing in for a screenshot of the app
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")
SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10"/></svg>'


def frame(title, source=None, body='<div class="sc-body"><span data-dc="title">Hello</span></div>', **meta):
    head = [f"title: {title}"] + ([f"source: {source}"] if source else []) + [f"{k}: {v}" for k, v in meta.items()]
    return "<!--\n" + "\n".join(head) + "\n-->\n" + body + "\n"


class Canvas(unittest.TestCase):
    """A made-up app in tmp/app with its design folder in tmp/app/design-canvas."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.app = self.tmp / "app"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make(self, frames: dict, files: dict | None = None, design: dict | None = None, inventory=None) -> Design:
        """frames: {"page/id": frame text}. files: extra files under the app root."""
        dd = self.app / "design-canvas"
        base = {"version": 1, "app": {"name": "Sample", "root": ".."}, "roles": {"background": "bg", "text": "text"},
                "colors": {"bg": {"value": "#FFFFFF", "derived": "test"}, "text": {"value": "#111111", "derived": "test"}},
                "icons": {"items": {"check": {"svg": '<path d="m5 12 5 5 9-10"/>'}}}}
        base.update(design or {})
        all_files = {"src/Home.swift": "struct Home {}\n", "src/Other.swift": "struct Other {}\n", **(files or {})}
        pages: dict = {}
        for key, text in frames.items():
            page, fid = key.split("/")
            pages.setdefault(page, []).append(fid)
            all_files[f"design-canvas/canvas/frames/{page}/{fid}.html"] = text
        for i, (page, ids) in enumerate(pages.items()):
            all_files[f"design-canvas/canvas/pages/{i + 1:02d}-{page}.json"] = json.dumps(
                {"id": page, "title": page.title(), "rows": [{"title": "Main", "frames": ids}]})
        if inventory is not None:
            all_files["design-canvas/canvas/screens.json"] = inventory if isinstance(inventory, str) else json.dumps({"screens": inventory})
        all_files["design-canvas/design.json"] = json.dumps(base)
        for rel, text in all_files.items():
            f = self.app / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(text, bytes):
                f.write_bytes(text)
            else:
                f.write_text(text, encoding="utf-8")
        d = Design(dd)
        self.assertEqual(d.errors, [])
        return d

    def build(self, d: Design):
        out = d.dir / "out"
        summary, lines = build.build_all(d, d.root, out, web=False)
        canvas = (out / "canvas.html").read_text(encoding="utf-8") if (out / "canvas.html").exists() else ""
        guide = (out / "guide.html").read_text(encoding="utf-8")
        return summary, lines, canvas, guide

    def cli(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = build.main([str(self.app / "design-canvas"), *args, "--json"])
        return code, json.loads(buf.getvalue())


class Coverage(Canvas):
    def test_inventory_reports_screens_not_drawn(self):
        d = self.make({"home/home": frame("Home", "src/Home.swift"), "home/home-empty": frame("Home", "src/Home.swift", state="Empty"),
                       "other/other": frame("Other", "src/Other.swift")},
                      inventory=[{"id": "home", "name": "Home", "source": "src/Home.swift", "page": "home"},
                                 {"id": "home-empty", "name": "Home", "state": "Empty", "source": "src/Home.swift"},
                                 {"id": "other", "name": "Other"},
                                 {"id": "settings", "name": "Settings", "source": "src/Other.swift#Settings", "page": "other"},
                                 {"id": "home-error", "name": "Home", "state": "Error", "page": "home"}])
        summary, lines, canvas, guide = self.build(d)
        cov = summary["coverage"]
        self.assertEqual((cov["drawn"], cov["listed"], cov["unlisted"]), (3, 5, []))
        self.assertEqual([m["id"] for m in cov["missing"]], ["settings", "home-error"])
        self.assertEqual(cov["missing"][0], {"id": "settings", "name": "Settings", "source": "src/Other.swift#Settings", "page": "other"})
        self.assertIn("canvas: 3 of 5 screens drawn · not drawn: Settings, Home (Error)", lines)
        self.assertTrue(lines[0].startswith("built "), "the coverage line comes after the built line")
        self.assertIn("Canvas · 3 of 5 drawn", canvas)
        self.assertIn("2 screens not drawn yet", canvas)
        self.assertIn('<p class="cv-todo">Not drawn yet: Home (Error)</p>', canvas)
        self.assertIn("See 3 of 5 screens on the canvas", guide)
        self.assertIn("2 more are listed but not drawn yet.", guide)

    def test_no_inventory_works_as_before(self):
        d = self.make({"home/home": frame("Home", "src/Home.swift"), "home/other": frame("Other", "src/Other.swift")})
        summary, lines, canvas, guide = self.build(d)
        self.assertIsNone(summary["coverage"])
        self.assertFalse(any(ln.startswith("canvas:") for ln in lines))
        self.assertIn("Canvas · 2 screens", canvas)
        self.assertNotIn("not drawn yet", canvas)
        self.assertIn("See all 2 screens on the canvas", guide)

    def test_everything_drawn(self):
        d = self.make({"home/home": frame("Home", "src/Home.swift")}, inventory=[{"id": "home", "name": "Home"}])
        summary, lines, canvas, guide = self.build(d)
        self.assertIn("canvas: 1 of 1 screens drawn", lines)
        self.assertIn("See the screen on the canvas", guide)
        self.assertNotIn("not drawn yet", canvas)

    def test_drawn_screens_missing_from_the_inventory_still_count(self):
        d = self.make({"home/home": frame("Home"), "home/extra": frame("Extra")},
                      inventory=[{"id": "home", "name": "Home"}, {"id": "later", "name": "Later"}])
        summary, lines, _, _ = self.build(d)
        self.assertEqual((summary["coverage"]["drawn"], summary["coverage"]["listed"]), (2, 3))
        self.assertEqual(summary["coverage"]["unlisted"], ["extra"])
        self.assertIn("canvas: 1 drawn screen(s) not in canvas/screens.json: extra", lines)

    def test_inventory_problems_fail_validate(self):
        d = self.make({"home/home": frame("Home")},
                      inventory=[{"id": "home"}, {"id": "home"}, {"name": "No id"}, {"id": "bad id!"},
                                 {"id": "outside", "source": "../secret.swift"}, {"id": "gone", "source": "src/Gone.swift"}])
        code, out = self.cli("--validate")
        self.assertEqual(code, 1)
        text = "\n".join(out["missing"])
        self.assertIn("id 'home' is listed twice", text)
        self.assertIn("screens[2] needs an id", text)
        self.assertIn("screens[3] needs an id", text)
        self.assertIn("outside: source must be a relative path inside the app root", text)
        self.assertIn("gone: source src/Gone.swift not found", text)
        self.assertEqual(d.errors, [])

    def test_inventory_invalid_json(self):
        self.make({"home/home": frame("Home")}, inventory="{nope")
        code, out = self.cli("--validate")
        self.assertEqual(code, 1)
        self.assertIn("canvas/screens.json: invalid JSON", out["missing"][0])

    def test_inventory_without_pages(self):
        d = self.make({}, inventory=[{"id": "home", "name": "Home"}])
        summary, lines, canvas, _ = self.build(d)
        self.assertEqual(canvas, "")
        self.assertEqual((summary["coverage"]["drawn"], summary["coverage"]["listed"]), (0, 1))

    def test_cta_wording(self):
        cov = {"drawn": 5, "listed": 12, "missing": [{}] * 7, "unlisted": []}
        self.assertIn("See 5 of 12 screens on the canvas", build.canvas_cta(5, cov))
        self.assertIn("7 more are listed but not drawn yet.", build.canvas_cta(5, cov))
        self.assertIn("See all 6 screens on the canvas", build.canvas_cta(6, None))
        self.assertIn("See all 6 screens on the canvas", build.canvas_cta(6, {**cov, "missing": []}))
        self.assertEqual(build.canvas_cta(0, cov), "")


class References(Canvas):
    def test_reference_is_embedded_with_a_compare_toggle(self):
        d = self.make({"home/home": frame("Home", reference="refs/home.png"), "home/other": frame("Other")},
                      files={"design-canvas/refs/home.png": PNG})
        summary, _, canvas, _ = self.build(d)
        self.assertEqual(summary["missing"], [])
        data = json.loads(re.search(r"window\.CANVAS = (.*);\n", canvas).group(1))
        self.assertEqual(list(data["refs"]), ["home"])
        self.assertEqual(data["refs"]["home"]["path"], "refs/home.png")
        self.assertTrue(data["refs"]["home"]["src"].startswith("data:image/png;base64,"))
        self.assertEqual(canvas.count('class="cv-ref"'), 1, "only the frame with a reference gets the toggle")
        self.assertIn('<div class="cv-pair">', canvas)
        for label in ("Drawing", "Side by side", "Overlay", 'aria-label="Screenshot opacity"'):
            self.assertIn(label, canvas)

    def test_reference_paths_are_checked(self):
        for ref, msg in (("../outside.png", "reference must be a relative path inside the design folder"),
                         ("/etc/hosts", "reference must be a relative path inside the design folder"),
                         ("refs/notes.txt", "reference must be a .png, .jpg, .webp or .gif image"),
                         ("refs/gone.png", "reference refs/gone.png not found")):
            with self.subTest(ref):
                d = self.make({"home/home": frame("Home", reference=ref)}, files={"outside.png": PNG, "design-canvas/refs/notes.txt": "x"})
                summary, _, canvas, _ = self.build(d)
                self.assertTrue(any(msg in m for m in summary["missing"]), summary["missing"])
                self.assertNotIn('class="cv-ref"', canvas)

    def test_big_images_warn(self):
        d = self.make({"home/home": frame("Home", reference="refs/home.png")}, files={"design-canvas/refs/home.png": PNG})
        with mock.patch.object(screens, "BIG_PAGE", 10):
            summary, lines, _, _ = self.build(d)
        self.assertEqual(len(summary["canvasWarnings"]), 1)
        self.assertIn("to keep the page small enough to share", summary["canvasWarnings"][0])
        self.assertTrue(any(ln.startswith("warning: reference screenshots and assets add") for ln in lines))
        summary, _, _, _ = self.build(d)
        self.assertEqual(summary["canvasWarnings"], [])


class Assets(Canvas):
    def test_asset_macro_inlines_the_image(self):
        body = '<div class="sc-body"><img src="{{asset:logo.svg}}" alt="Logo"><i style="background-image:url(\'{{asset:art/qr.png}}\')"></i></div>'
        d = self.make({"home/home": frame("Home", body=body)}, files={"design-canvas/assets/logo.svg": SVG, "design-canvas/assets/art/qr.png": PNG})
        summary, _, canvas, _ = self.build(d)
        self.assertEqual(summary["missing"], [])
        self.assertIn('<img src="data:image/svg+xml;base64,', canvas)
        self.assertIn("url('data:image/png;base64,", canvas)
        self.assertNotIn("{{asset:", canvas)

    def test_asset_paths_stay_inside_assets(self):
        for name, msg in (("../design.json", "must be an image"), ("../../src/Home.swift", "must be an image"),
                          ("../refs/x.png", "must be an image"), ("nope.png", "asset nope.png not found in assets/")):
            with self.subTest(name):
                d = self.make({"home/home": frame("Home", body='<img src="{{asset:' + name + '}}">')},
                              files={"design-canvas/refs/x.png": PNG, "design-canvas/assets/ok.png": PNG})
                summary, _, canvas, _ = self.build(d)
                self.assertTrue(any(msg in m for m in summary["missing"]), summary["missing"])
                self.assertIn('<img src="">', canvas)


class SystemIcons(Canvas):
    def test_system_icon_is_a_labelled_placeholder(self):
        icons = {"items": {"check": {"svg": '<path d="m5 12 5 5 9-10"/>'}, "settings": {"system": "sf-symbols", "name": "gearshape"},
                           "chevron.right": {"system": "sf-symbols"}}}
        body = '<div class="sc-body">{{icon:settings}} {{icon:chevron.right:16}} {{icon:check}}</div>'
        d = self.make({"home/home": frame("Home", body=body)}, design={"icons": icons})
        summary, _, canvas, guide = self.build(d)
        self.assertEqual(summary["missing"], [])
        self.assertIn('<svg class="ic ic-sys" aria-hidden="true" data-icon="sf-symbols: gearshape"><title>sf-symbols: gearshape</title><use href="#i-settings"/></svg>', canvas)
        self.assertIn('data-icon="sf-symbols: chevron.right" style="width:16px;height:16px"', canvas)
        self.assertIn('<svg class="ic" aria-hidden="true"><use href="#i-check"/></svg>', canvas)
        sprite = d.sprite()
        self.assertIn('<symbol id="i-settings" viewBox="0 0 24 24"><rect', sprite)
        self.assertIn("stroke-dasharray", sprite)
        self.assertIn("<code>sf-symbols: gearshape</code>", guide)
        self.assertIn("2 system icons (sf-symbols) are drawn as a dashed placeholder", guide)

    def test_icon_needs_svg_or_system(self):
        dd = self.app / "design-canvas"
        self.make({"home/home": frame("Home")})
        raw = json.loads((dd / "design.json").read_text(encoding="utf-8"))
        raw["icons"]["items"]["broken"] = {"name": "gearshape"}
        (dd / "design.json").write_text(json.dumps(raw), encoding="utf-8")
        self.assertTrue(any("icons.items.broken: give svg" in e for e in Design(dd).errors))

    def test_unknown_icons_and_macros_are_reported(self):
        body = '<div class="sc-body">{{icon:nope}} {{icon:sf:gearshape}} {{asset: spaced.png}}</div>'
        d = self.make({"home/home": frame("Home", body=body)})
        summary, _, _, _ = self.build(d)
        text = "\n".join(summary["missing"])
        self.assertIn("frames/home/home.html: icon 'nope' is not in design.json icons", text)
        self.assertIn("{{icon:sf:gearshape}} was not understood", text)
        self.assertIn("{{asset: spaced.png}} was not understood", text)


class Sources(Canvas):
    def test_several_sources_and_symbols(self):
        d = self.make({"home/home": frame("Home", "src/Home.swift, src/Other.swift#SettingsSheet")})
        summary, _, canvas, _ = self.build(d)
        self.assertEqual(summary["missing"], [])
        _, _, _, scr = build.build_canvas(d, d.root)
        self.assertEqual(scr["home"]["source"], "src/Home.swift, src/Other.swift#SettingsSheet")
        self.assertEqual(scr["home"]["sources"], ["src/Home.swift", "src/Other.swift#SettingsSheet"])
        self.assertIn("<code>src/Home.swift, src/Other.swift#SettingsSheet</code>", canvas)

    def test_each_source_is_checked(self):
        d = self.make({"home/home": frame("Home", "src/Home.swift, ../outside.swift, src/Home.swift (SettingsSheet)")})
        summary, _, _, _ = self.build(d)
        text = "\n".join(summary["missing"])
        self.assertIn("source must be a relative path inside the app root", text)
        self.assertIn("source src/Home.swift (SettingsSheet) not found under the app root (name a type or view inside a file as path#Symbol)", text)
        _, _, _, scr = build.build_canvas(d, d.root)
        self.assertNotIn("outside", scr["home"]["source"])

    def test_split_sources(self):
        self.assertEqual(screens.split_sources("a.swift , b.swift#X,"), ["a.swift", "b.swift#X"])
        self.assertEqual(screens.split_sources(["a.swift", " b.swift "]), ["a.swift", "b.swift"])
        self.assertEqual(screens.split_sources(None), [])
        self.assertEqual(screens.source_path("Views/Home.swift#Sheet"), "Views/Home.swift")


class InspectData(unittest.TestCase):
    def test_grouping_rules_are_read(self):
        css = ("@import url(x.css);\n@layer base, app;\n.a { color: red; }\n"
               "@supports (display: grid) { .b { gap: var(--s-md); } @media (min-width: 400px) { .c { margin: 0; } } }\n"
               "@layer app { .d { padding: 4px; } }\n@container card (min-width: 200px) { .e { color: blue; } }\n"
               "@media (prefers-color-scheme: dark) { @supports (color: red) { .f { color: white; } } }\n"
               "@font-face { font-family: X; src: url(x.woff2); }\n@keyframes spin { from { opacity: 0; } to { opacity: 1; } }\n")
        rules = {r["s"]: r for r in build.parse_css(css)}
        self.assertEqual(sorted(rules), [".a", ".b", ".c", ".d", ".e", ".f"])
        self.assertIsNone(rules[".b"]["m"])
        self.assertEqual(rules[".c"]["m"], "(min-width: 400px)")
        self.assertEqual(rules[".f"]["m"], "(prefers-color-scheme: dark)")

    def test_long_values_are_shortened(self):
        art = "data:image/png;base64," + "A" * 5000
        css = (f'.x {{ background-image: url("{art}"); }}\n.y {{ background: url({art}) no-repeat, var(--c-bg); }}\n'
               f".z {{ mask: url('data:image/svg+xml;utf8,<svg xmlns=\"http://www.w3.org/2000/svg\"/>'); }}\n"
               f".w {{ box-shadow: {', '.join(['0 0 1px red'] * 40)}; }}")
        rules = {r["s"]: r["d"][0][1] for r in build.parse_css(css)}
        self.assertEqual(rules[".x"], "url(data:…)")
        self.assertEqual(rules[".y"], "url(data:…) no-repeat, var(--c-bg)")
        self.assertEqual(rules[".z"], "url(data:…)")
        self.assertEqual(len(rules[".w"]), 201)
        self.assertTrue(rules[".w"].endswith("…"))


class Outdated(Canvas):
    """Screens whose source has a newer commit than the frame, in a temp repo with its own git identity."""

    def setUp(self):
        super().setUp()
        self.env = dict(os.environ)
        (self.tmp / "gitconfig").write_text("[init]\n\tdefaultBranch = main\n", encoding="utf-8")
        os.environ.update(GIT_CONFIG_GLOBAL=str(self.tmp / "gitconfig"), GIT_CONFIG_NOSYSTEM="1")

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.env)
        super().tearDown()

    def git(self, *args, when=None):
        env = dict(os.environ)
        if when:
            env.update(GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when)
        p = subprocess.run(["git", *args], cwd=str(self.app), capture_output=True, text=True, encoding="utf-8", env=env)
        self.assertEqual(p.returncode, 0, p.stderr)

    def commit(self, when):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "change", when=when)

    @unittest.skipUnless(shutil.which("git"), "git is not installed")
    def test_source_changed_after_the_frame(self):
        d = self.make({"home/home": frame("Home", "src/Home.swift"), "home/other": frame("Other", "src/Other.swift"),
                       "home/sheet": frame("Sheet", "src/Other.swift, src/Home.swift#SettingsSheet"), "home/new": frame("New", "src/Other.swift")})
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Sample Tester")
        self.git("config", "user.email", "tester@example.com")
        (self.app / "design-canvas" / "canvas" / "frames" / "home" / "new.html").unlink()
        self.commit("2026-01-01T10:00:00+00:00")
        (self.app / "src" / "Home.swift").write_text("struct Home { let changed = true }\n", encoding="utf-8")
        self.commit("2026-01-02T10:00:00+00:00")
        (self.app / "design-canvas" / "canvas" / "frames" / "home" / "new.html").write_text(frame("New", "src/Other.swift"), encoding="utf-8")
        summary, lines, canvas, _ = self.build(d)
        self.assertEqual([o["screen"] for o in summary["outdated"]], ["home", "sheet"])
        self.assertEqual(summary["outdated"][0]["message"], "screen 'home' may be out of date: src/Home.swift changed after the frame")
        self.assertEqual(summary["outdated"][1]["sources"], ["src/Home.swift"])
        self.assertIn("warning: screen 'home' may be out of date: src/Home.swift changed after the frame", lines)
        self.assertEqual(canvas.count('class="cv-stale"'), 2)
        self.assertNotIn("<!--stale:", canvas)
        # redrawing the frame (a newer commit) clears it
        f = self.app / "design-canvas" / "canvas" / "frames" / "home" / "home.html"
        f.write_text(f.read_text(encoding="utf-8") + "<!-- redrawn -->\n", encoding="utf-8")
        self.commit("2026-01-03T10:00:00+00:00")
        summary, _, _, _ = self.build(d)
        self.assertEqual([o["screen"] for o in summary["outdated"]], ["sheet"])

    def test_no_repo_or_no_git_is_quiet(self):
        d = self.make({"home/home": frame("Home", "src/Home.swift")})
        summary, _, canvas, _ = self.build(d)
        self.assertEqual(summary["outdated"], [])
        self.assertNotIn('class="cv-stale"', canvas)
        with mock.patch.object(screens.subprocess, "run", side_effect=FileNotFoundError("git")):
            (self.app / ".git").mkdir()
            summary, _, _, _ = self.build(d)
        self.assertEqual(summary["outdated"], [])
        with mock.patch.object(screens.subprocess, "run", side_effect=subprocess.TimeoutExpired("git", 15)):
            self.assertEqual(screens.commit_times([self.app / "src" / "Home.swift"]), {})


class Shoot(Canvas):
    def test_unknown_screen(self):
        self.make({"home/home": frame("Home"), "home/home-empty": frame("Home")})
        code, out = self.cli("--shoot", "home-emty")
        self.assertEqual(code, 2)
        self.assertEqual(out["error"], "no screen 'home-emty' on the canvas pages; did you mean home-empty, home?")
        code, out = self.cli("--shoot", "settings")
        self.assertEqual(out["error"], "no screen 'settings' on the canvas pages")

    def test_unknown_theme_and_scale(self):
        self.make({"home/home": frame("Home")})
        code, out = self.cli("--shoot", "home", "--theme", "nope")
        self.assertEqual((code, out["error"]), (2, "unknown theme 'nope'; themes: default"))
        code, out = self.cli("--shoot", "home", "--scale", "9")
        self.assertEqual((code, out["error"]), (2, "--scale must be between 0.5 and 4"))

    def test_no_browser(self):
        self.make({"home/home": frame("Home")})
        with mock.patch.dict(os.environ), mock.patch.object(screens, "find_chrome", return_value=None):
            os.environ.pop("CHROME_PATH", None)
            code, out = self.cli("--shoot", "home")
        self.assertEqual(code, 2)
        self.assertIn("no Chrome, Chromium or Edge found", out["error"])
        self.assertIn("CHROME_PATH", out["error"])

    def test_chrome_path_that_is_not_there(self):
        self.make({"home/home": frame("Home")})
        missing = str(self.tmp / "no-browser-here")
        with mock.patch.dict(os.environ, {"CHROME_PATH": missing}):
            self.assertIsNone(screens.find_chrome())
            code, out = self.cli("--shoot", "home")
        self.assertEqual((code, out["error"]), (2, f"CHROME_PATH is set, but there is no browser at {missing}"))

    def test_render(self):
        if not screens.find_chrome():
            self.skipTest("no Chrome or Chromium on this computer")
        tall = '<div class="sc-body"><div style="height:1500px">Long</div></div>'
        self.make({"home/home": frame("Home"), "home/long": frame("Long", body=tall, height="auto")},
                  design={"app": {"name": "Sample", "root": "..", "frame": {"device": "phone", "width": 390, "height": 844}}})
        out = self.tmp / "shot.png"
        code, res = self.cli("--shoot", "home", "--out", str(out), "--scale", "2")
        self.assertEqual(code, 0, res)
        self.assertEqual(screens.png_size(out), (780, 1688))
        code, res = self.cli("--shoot", "long")
        self.assertEqual(code, 0, res)
        self.assertEqual(Path(res["file"]).resolve(), (self.app / "design-canvas" / "out" / "shots" / "long.png").resolve())
        self.assertGreater(res["height"], 1500)
        self.assertEqual(screens.png_size(Path(res["file"])), (390, res["height"]))


class InBrowser(Canvas):
    """The built canvas in headless Chrome: the status bar, fit zoom and Inspect under a decoration layer."""

    def test_status_bar_fit_and_inspect(self):
        browser = screens.find_chrome()
        if not browser:
            self.skipTest("no Chrome or Chromium on this computer")
        body = ('<div class="sc-body" style="background:#ddeeff"><span class="save" data-dc="save">Save</span></div>'
                '<div class="vignette"></div><div class="glow" aria-hidden="true"></div>')
        d = self.make({"home/home": frame("Home", body=body)},
                      files={"design-canvas/canvas/css/home.css": ".home-x{}\n.vignette, .glow { position: absolute; inset: 0; z-index: 25; }\n"})
        self.build(d)
        probe = """<script>setTimeout(() => {
          const fig = document.querySelector('.cv-frame[data-id="home"]'), dev = fig.querySelector('.dev')
          const k = dev.getBoundingClientRect().width / dev.offsetWidth, top = dev.getBoundingClientRect().top
          const save = fig.querySelector('[data-dc=save]'), body = fig.querySelector('.sc-body')
          const zoom = parseFloat(document.getElementById('zpct').textContent)
          document.getElementById('zfit').click()
          const fitZoom = parseFloat(document.getElementById('zpct').textContent)
          document.body.classList.add('dc-inspecting')
          const r = save.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2
          const picked = DC_INSPECT.pickable(document.elementFromPoint(x, y), x, y)
          document.body.setAttribute('data-result', JSON.stringify({
            bar: dev.querySelector('.dev-sb').getBoundingClientRect().height / k,
            content: (save.getBoundingClientRect().top - top) / k,
            bodyTop: (body.getBoundingClientRect().top - top) / k,
            zoom, fitZoom, picked: picked && picked.dataset.dc }))
        }, 800)</script></body>"""
        page = d.dir / "out" / "probe.html"
        page.write_text((d.dir / "out" / "canvas.html").read_text(encoding="utf-8").replace("</body>", probe), encoding="utf-8")
        p = screens.chrome(browser, self.tmp / "profile", page, 2600, 1700, 1, ["--dump-dom"])
        m = re.search(r'data-result="([^"]*)"', p.stdout or "")
        self.assertIsNotNone(m, p.stderr[-500:])
        res = json.loads(html.unescape(m.group(1)))
        self.assertEqual(res["bar"], 47, "the status bar is exactly 47 px")
        self.assertEqual(res["content"], 47, "content starts right under the status bar")
        self.assertEqual(res["bodyTop"], 0, "the first sc-body's background runs under the status bar")
        self.assertLessEqual(res["zoom"], 100, "fit never zooms past 100% on load")
        self.assertLessEqual(res["fitZoom"], 100, "or with the Fit button")
        self.assertEqual(res["picked"], "save", "Inspect picks the element under a bare overlay, not the overlay")


if __name__ == "__main__":
    unittest.main()

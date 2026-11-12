"""Output honesty tests: no invented values, no false contrast warnings, nothing that clips.

Run from the repo root:  python3 -m unittest discover tests
"""

from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
import build  # noqa: E402
from tokens import Design, kebab  # noqa: E402

SAMPLE = ROOT / "examples" / "acme-habits"
THREE = [{"id": "light", "label": "Light"}, {"id": "dark", "label": "Dark", "scheme": "dark"}, {"id": "dim", "label": "Dim", "scheme": "dark"}]


class Base(unittest.TestCase):
    """Each test writes a made-up design to tmp/design (and app files to tmp/app)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def write(self, design: dict, files: dict | None = None) -> Path:
        d = self.tmp / "design"
        d.mkdir(parents=True, exist_ok=True)
        (self.tmp / "app").mkdir(exist_ok=True)
        for rel, text in (files or {}).items():
            f = d / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(text, encoding="utf-8")
        base = {"version": 1, "app": {"name": "Acme Test", "root": "../app"}, "roles": {"background": "bg", "text": "text"},
                "colors": {"bg": {"value": "#FFFFFF", "derived": "test"}, "text": {"value": "#111111", "derived": "test"}}}
        for k, v in design.items():
            base[k] = {**base[k], **v} if isinstance(v, dict) and isinstance(base.get(k), dict) else v
        (d / "design.json").write_text(json.dumps(base), encoding="utf-8")
        return d

    def design(self, design: dict, files: dict | None = None) -> Design:
        return Design(self.write(design, files))

    def run_cli(self, *args) -> tuple[int, str]:
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = build.main([str(a) for a in args])
        return code, buf.getvalue()


# ---------------------------------------------------------------- 1. line heights
class LineHeight(Base):
    TYPE = {"fonts": {"body": {"family": "Inter", "load": "system"}},
            "type": {"body": {"font": "body", "size": 17}, "caption": {"font": "body", "size": 12, "lineHeight": 16},
                     "title": {"font": "body", "size": 20, "lineHeightRatio": 1.25}}}

    def test_a_missing_line_height_is_not_invented(self):
        d = self.design(self.TYPE)
        self.assertEqual(d.errors, [])
        self.assertIsNone(d.line_height(d.type["body"]))
        css = d.css()
        self.assertIn("--t-body: 400 17px/normal Inter;", css)
        self.assertIn("--t-caption: 400 12px/16px Inter;", css)
        self.assertIn("--t-title: 400 20px/25px Inter;", css)
        md = d.markdown()
        self.assertIn("| `body` | 17 / platform default |", md)
        self.assertIn("| `caption` | 12 / 16 |", md)
        guide = build.view_type(d)
        self.assertIn("17/<span", guide)
        self.assertIn(">auto</span>", guide)
        for text in (css, md, guide):
            self.assertNotIn("22.1", text, "17 x 1.3 must not appear anywhere")

    def test_dtcg_marks_the_default_line_height(self):
        d = self.design(self.TYPE)
        t = d.dtcg()["type"]
        self.assertEqual(t["body"]["$value"]["lineHeight"], 1.2)
        self.assertEqual(t["body"]["$extensions"], {"dev.design-canvas": {"lineHeight": "platform default"}})
        self.assertEqual(t["caption"]["$value"]["lineHeight"], round(16 / 12, 3))
        self.assertNotIn("$extensions", t["caption"])
        self.assertEqual(t["title"]["$value"]["lineHeight"], 1.25)
        self.assertIsNone(d.inspect_data()["type"]["body"]["lh"])


# ---------------------------------------------------------------- 2. missing theme values
class ThemeValues(Base):
    def test_a_theme_left_out_warns(self):
        d = self.design({"themes": THREE, "colors": {
            "accent": {"value": {"light": "#3B5BFD", "dark": "#6F86FF"}},
            "same": "#123456",
            "full": {"value": {"light": "#000000", "dark": "#111111", "dim": "#222222"}}}})
        self.assertEqual(d.errors, [])
        self.assertEqual(d.warnings, ["colors.accent has no value for the 'dim' theme; using 'light'"])
        self.assertEqual(d.colors["accent"]["values"]["dim"], "#3B5BFD")

    def test_a_single_value_never_warns(self):
        d = self.design({"themes": THREE, "colors": {"same": "#123456", "meta": {"value": "#654321", "doc": "x"}}})
        self.assertEqual(d.warnings, [])

    def test_validate_and_build_print_it(self):
        path = self.write({"themes": THREE, "colors": {"accent": {"value": {"light": "#3B5BFD"}, "derived": "test"}}})
        code, out = self.run_cli(path, "--validate", "--json")
        self.assertEqual(code, 0)
        self.assertIn("colors.accent has no value for the 'dark' theme; using 'light'", json.loads(out)["warnings"])
        code, out = self.run_cli(path)
        self.assertIn("warning: colors.accent has no value for the 'dim' theme; using 'light'", out)

    def test_on_per_theme_left_out_warns(self):
        d = self.design({"themes": THREE, "colors": {"card": "#EEEEEE", "label": {"value": "#222222", "on": {"light": "card"}}}})
        self.assertEqual(d.errors, [])
        self.assertIn("colors.label.on has no value for the 'dark' theme; using 'light'", d.warnings)


# ---------------------------------------------------------------- 3 + A. contrast on the real pair
class Contrast(Base):
    BUTTON = {"roles": {"accent": "accent", "onAccent": "onPine"},
              "colors": {"accent": "#8FD3C1", "pine": "#0B6E5F", "onPine": {"value": "#FFFFFF", "doc": "Button labels"}}}

    def test_without_on_the_old_pair_is_used(self):
        d = self.design(self.BUTTON)
        self.assertEqual(d.fills("onPine", "default"), ["accent"])
        self.assertTrue(any("`onPine` on `accent`" in p for p in d.contrast_problems()))

    def test_on_names_the_real_fill(self):
        design = json.loads(json.dumps(self.BUTTON))
        design["colors"]["onPine"]["on"] = "pine"
        d = self.design(design)
        self.assertEqual(d.errors, [])
        self.assertEqual(d.contrast_problems(), [], "white on the pine fill is fine; the tint is not where it is read")
        self.assertEqual([f for f, _ in d.pairs("onPine")], ["pine"])

    def test_on_a_list_checks_every_fill(self):
        d = self.design({"colors": {"sun": "#FFE7A3", "sky": "#CFE8FF", "navy": "#14213D",
                                    "badgeText": {"value": "#102A43", "on": ["sun", "sky", "navy"]}}})
        self.assertEqual([f for f, _ in d.pairs("badgeText")], ["sun", "sky", "navy"])
        probs = d.contrast_problems()
        self.assertEqual(len(probs), 1)
        self.assertIn("`badgeText` on `navy`", probs[0])

    def test_on_per_theme(self):
        d = self.design({"themes": THREE[:2], "colors": {"card": {"value": {"light": "#FFFFFF", "dark": "#1A1A1A"}},
                                                         "pine": "#0B6E5F",
                                                         "label": {"value": {"light": "#111111", "dark": "#FFFFFF"},
                                                                   "on": {"light": "card", "dark": ["card", "pine"]}}}})
        self.assertEqual(d.errors, [])
        self.assertEqual(d.fills("label", "light"), ["card"])
        self.assertEqual(d.fills("label", "dark"), ["card", "pine"])
        self.assertEqual(dict(d.pairs("label"))["pine"].keys(), {"dark"})

    def test_on_names_are_validated(self):
        d = self.design({"colors": {"label": {"value": "#111111", "on": "nope"}}})
        self.assertIn("colors.label.on: 'nope' is not a colour token", d.errors)
        d = self.design({"colors": {"label": {"value": "#111111", "on": 12}}})
        self.assertTrue(any(e.startswith("colors.label.on: give a colour token name") for e in d.errors))
        d = self.design({"colors": {"label": {"value": "#111111", "on": {"sepia": "bg"}}}})
        self.assertTrue(any("unknown theme(s) sepia" in e for e in d.errors))
        code, out = self.run_cli(self.write({"colors": {"label": {"value": "#111111", "on": ["bg", "nope"]}}}), "--validate")
        self.assertEqual(code, 1)
        self.assertIn("error: colors.label.on: 'nope' is not a colour token", out)

    def test_ink_backdrop_is_not_text(self):
        d = self.design({"themes": THREE, "roles": {"background": "ink", "text": "chalk"},
                         "colors": {"ink": {"value": {"light": "#0E1116", "dark": "#000000", "dim": "#202733"}},
                                    "chalk": {"value": {"light": "#FFFFFF", "dark": "#F2F2F2", "dim": "#E0E0E0"}}}})
        self.assertFalse(d.is_texty("ink"))
        self.assertEqual([p for p in d.contrast_problems() if "ink` on `ink" in p], [])
        self.assertNotIn("ink", d.text_colors())

    def test_which_names_count_as_text(self):
        names = {"primaryText": "#111111", "labelSecondary": "#111111", "onSurface": "#111111", "on_brand": "#111111",
                 "fg": "#111111", "foregroundMuted": "#111111", "ink": "#111111", "inkSoft": "#111111", "online": "#111111",
                 "textFieldBg": "#EEEEEE", "contentBackground": "#EEEEEE", "labelFill": "#EEEEEE", "content": "#111111",
                 "grouped": {"value": "#111111", "group": "Text"}, "optedOut": {"value": "#111111", "group": "Text", "text": False},
                 "optedIn": {"value": "#111111", "text": True}}
        d = self.design({"colors": names})
        texty = {k for k in names if d.is_texty(k)}
        self.assertEqual(texty, {"primaryText", "labelSecondary", "onSurface", "on_brand", "fg", "foregroundMuted", "grouped", "optedIn"})

    def test_text_flag_must_be_a_boolean(self):
        d = self.design({"colors": {"x": {"value": "#111111", "text": "yes"}}})
        self.assertIn("colors.x.text: use true or false", d.errors)

    def test_cards_show_a_ratio_only_for_text(self):
        d = self.design({"colors": {"sun": "#FFE7A3", "badgeText": {"value": "#102A43", "on": ["sun"]}}})
        html = build.view_colors(d)
        sun = html.split("<b>sun</b>")[1].split("</figure>")[0]
        ink = html.split("<b>badgeText</b>")[1].split("</figure>")[0]
        self.assertNotIn("ratio", sun, "a pastel fill is never read as text")
        self.assertIn("on sun</span>", ink)
        self.assertNotIn("on bg", ink)
        bg = html.split("<b>bg</b>")[1].split("</figure>")[0]
        self.assertNotIn("ratio", bg)

    def test_many_themes_show_the_range(self):
        themes = [{"id": f"t{i}"} for i in range(5)]
        d = self.design({"themes": themes, "colors": {"bg": {"value": {f"t{i}": "#FFFFFF" for i in range(5)}},
                                                      "text": {"value": {"t0": "#111111", "t1": "#222222", "t2": "#333333", "t3": "#444444", "t4": "#555555"}}}})
        html = build.ratio_html(d, "text")
        self.assertEqual(html.count('class="ratio'), 1)
        self.assertIn("(t4) to ", html)
        self.assertIn('title="t0 ', html)


# ---------------------------------------------------------------- 4. contrast issues are listed
class ContrastListing(Base):
    LOW = {"colors": {"faint": {"value": "#BBBBBB", "group": "Text", "derived": "test"}}}

    def test_build_lists_each_issue(self):
        code, out = self.run_cli(self.write(self.LOW))
        self.assertEqual(code, 0)
        self.assertIn("contrast issues: 1", out)
        self.assertIn("CONTRAST: faint on bg is 1.92:1 in the default theme (text needs 4.5:1)", out)
        code, out = self.run_cli(self.write(self.LOW), "--json")
        self.assertEqual(json.loads(out)["contrastIssues"], ["faint on bg is 1.92:1 in the default theme (text needs 4.5:1)"])

    def test_validate_reports_them(self):
        path = self.write(self.LOW)
        code, out = self.run_cli(path, "--validate", "--json")
        self.assertEqual(code, 0, "low contrast is reported, not an error")
        self.assertEqual(json.loads(out)["contrastIssues"], ["faint on bg is 1.92:1 in the default theme (text needs 4.5:1)"])
        code, out = self.run_cli(path, "--validate")
        self.assertIn("CONTRAST: faint on bg is 1.92:1", out)
        code, out = self.run_cli(self.write({}), "--validate", "--json")
        self.assertEqual(json.loads(out)["contrastIssues"], [])


# ---------------------------------------------------------------- 5. guide UI at scale
class GuideUI(Base):
    def test_two_or_three_short_themes_keep_the_buttons(self):
        d = self.design({"themes": THREE})
        html = build.theme_buttons(d)
        self.assertIn('class="themes"', html)
        self.assertEqual(html.count("data-set-theme="), 3)
        self.assertNotIn("<select", html)

    def test_many_or_long_themes_get_a_menu(self):
        labels = ["Light", "Dark", "Paper White", "Deep Ocean", "High Contrast", "Forest Night", "Sunset Glow"]
        d = self.design({"themes": [{"id": f"t{i}", "label": lab} for i, lab in enumerate(labels)]})
        html = build.theme_buttons(d)
        self.assertIn("<select data-theme-select", html)
        self.assertEqual(html.count("<option"), 7)
        self.assertNotIn("data-set-theme", html)
        d = self.design({"themes": [{"id": "day", "label": "Daylight Reading"}, {"id": "night", "label": "Midnight Reading"}]})
        self.assertIn("<select", build.theme_buttons(d), "two long names would clip in the rail")
        js = (ROOT / "engine" / "assets" / "guide.js").read_text(encoding="utf-8")
        self.assertIn("[data-theme-select]", js)

    def test_src_lists_wrap_and_fold(self):
        self.assertIn(">src/theme.ts:6, 20</span>", build.src_html("src/theme.ts:6, src/theme.ts:20"))
        long = ", ".join(f"Sources/Theme/Palette{i}.swift:{i + 3}" for i in range(6))
        html = build.src_html(long)
        self.assertTrue(html.startswith('<details class="src">'))
        self.assertIn(">6 files</summary>", html)
        self.assertEqual(html.count("<li>"), 6)
        self.assertIn("Sources/Theme/Palette5.swift:8", html)
        one = build.src_html(", ".join(f"Sources/Theme.swift:{i}" for i in range(10, 30)))
        self.assertIn("20 lines in Theme.swift", one)
        self.assertEqual(build.src_html(None), "")
        css = (ROOT / "engine" / "assets" / "guide.css").read_text(encoding="utf-8")
        self.assertIn(".src {", css)

    def test_one_value_for_every_theme_is_shown_once(self):
        d = self.design({"themes": THREE, "colors": {"brand": "#0B6E5F"}})
        card = build.view_colors(d).split("<b>brand</b>")[1].split("</figure>")[0]
        self.assertIn("<code>#0B6E5F</code>", card)
        self.assertNotIn("dim #0B6E5F", card)

    def test_used_in_is_hidden_when_there_is_nothing_to_show(self):
        self.assertEqual(build.lineage_html(None, "Button"), "")
        self.assertEqual(build.lineage_html({}, "Button"), "")
        self.assertIn("no imports found", build.lineage_html({"Chip": ["src/a.tsx"]}, "Button"))
        self.assertIn("Used in 1 file", build.lineage_html({"Button": ["src/a.tsx"]}, "Button"))
        path = self.write({"app": {"name": "Acme Swift", "root": "../app", "platform": "ios"}},
                          {"guides/02-atoms.md": "# Atoms\n\n### Button [atom]\n\n::: lineage Button\n"})
        self.run_cli(path)
        guide = (path / "out" / "guide.html").read_text(encoding="utf-8")
        self.assertNotIn("Used in", guide)
        self.assertNotIn("Usage not scanned", guide)


# ---------------------------------------------------------------- B. partials in the guide
class GuidePartials(Base):
    def test_specimens_and_html_lines_expand_partials(self):
        path = self.write({}, {
            "canvas/partials/badge.html": '<div class="p-badge">{{left}}</div>',
            "specimens/count.html": "{{> badge left=7}}",
            "guides/02-atoms.md": ("# Atoms\n\n### Badge [atom]\n\n::: specimen\n{{> badge left=12}}\n:::\n\n::: specimen count\n\n"
                                   "```\n{{> badge left=99}}\n```\n\nUse `{{> badge left=98}}` in a sentence.\n\n"
                                   "## Bare\n\n{{> badge left=3}}\n\n{{> nope}}\n"),
        })
        code, out = self.run_cli(path)
        guide = (path / "out" / "guide.html").read_text(encoding="utf-8")
        for n in (12, 7, 3):
            self.assertIn(f'<div class="p-badge">{n}</div>', guide)
        self.assertIn("{{&gt; badge left=99}}", guide, "a code sample keeps the partial as text")
        self.assertNotIn('<div class="p-badge">98</div>', guide)
        self.assertIn("missing: canvas/partials/nope.html (used in the guide)", out)


# ---------------------------------------------------------------- C. undefined token variables
class UndefinedVars(Base):
    def test_typos_are_named_with_file_line_and_a_guess(self):
        path = self.write({"colors": {"tag3": "#7A9E2C"}, "spacing": {"md": 12},
                           "fonts": {"body": {"family": "Inter"}}, "type": {"body": {"font": "body", "size": 16, "lineHeight": 22}}}, {
            "parts.css": ".p-a { color: var(--c-text); }\n.p-tag { background: var(--c-tag-3); }\n.p-b { --c-local: red; color: var(--c-local); }\n",
            "canvas/frames/home/home.html": '<div style="padding: var(--s-mdd)">\n<i style="font: var(--t-bodyy)"></i>\n<i style="gap: var(--s-mdd)"></i></div>',
            "guides/01-tokens.md": "# Tokens\n\n::: specimen\n<div style=\"color: var(--role-text); margin: var(--gutter)\"></div>\n:::\n",
        })
        warns = build.undefined_vars(Design(path))
        self.assertIn("parts.css:2: var(--c-tag-3) is not defined in design.json (did you mean --c-tag3?)", warns)
        self.assertIn("canvas/frames/home/home.html:1: var(--s-mdd) is not defined in design.json, used 2 times (did you mean --s-md?)", warns)
        self.assertIn("canvas/frames/home/home.html:2: var(--t-bodyy) is not defined in design.json (did you mean --t-body?)", warns)
        self.assertEqual(len(warns), 3, "defined, local and role variables are fine")
        code, out = self.run_cli(path, "--validate", "--json")
        self.assertEqual(code, 0)
        self.assertIn("parts.css:2: var(--c-tag-3) is not defined in design.json (did you mean --c-tag3?)", json.loads(out)["warnings"])
        code, out = self.run_cli(path)
        self.assertIn("warning: parts.css:2: var(--c-tag-3) is not defined in design.json (did you mean --c-tag3?)", out)


# ---------------------------------------------------------------- D. how token names become CSS variables
class CssNames(Base):
    def test_kebab_adds_no_hyphen_before_a_digit(self):
        self.assertEqual(kebab("tag0"), "tag0")
        self.assertEqual(kebab("tag_0"), "tag-0")
        self.assertEqual(kebab("onPrimary"), "on-primary")
        d = self.design({"colors": {"tag0": "#7A9E2C"}})
        self.assertIn("--c-tag0: #7A9E2C;", d.css())


# ---------------------------------------------------------------- the sample stays clean
class SampleOutput(unittest.TestCase):
    def test_sample_has_no_warnings_or_contrast_issues(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(build.main([str(SAMPLE), "--validate", "--json"]), 0)
        res = json.loads(buf.getvalue())
        self.assertEqual((res["warnings"], res["contrastIssues"]), ([], []))
        d = Design(SAMPLE)
        self.assertEqual([f for f, _ in d.pairs("primary")], ["bg", "surface"])
        self.assertNotIn("success", d.text_colors())


if __name__ == "__main__":
    unittest.main()

"""Engine tests. Run from the repo root:  python3 -m unittest discover tests"""

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
from tokens import Design, contrast, parse_color  # noqa: E402

SAMPLE = ROOT / "examples" / "acme-habits"


def make(tmp: Path, design: dict, files: dict[str, str]) -> Design:
    """Write a design.json in tmp/design and app files under tmp/app."""
    (tmp / "design").mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        f = tmp / "app" / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    base = {"version": 1, "app": {"name": "Test", "root": "../app"}, "roles": {"background": "bg", "text": "text"},
            "colors": {"bg": {"value": "#FFFFFF", "derived": "test"}, "text": {"value": "#111111", "derived": "test"}}}
    for k, v in design.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            base[k] = {**base[k], **v}
        else:
            base[k] = v
    (tmp / "design" / "design.json").write_text(json.dumps(base), encoding="utf-8")
    return Design(tmp / "design")


class DriftCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def check(self, design, files):
        d = make(self.tmp, design, files)
        self.assertEqual(d.errors, [])
        return d.check()

    def test_typescript_object(self):
        src = "export const colors = {\n  primary: '#3B5BFD',\n}\nexport const space = { sm: 8, md: 12, lg: 16 }\n"
        ok = self.check({"colors": {"primary": {"value": "#3B5BFD", "src": "theme.ts:2"}},
                         "spacing": {"md": {"value": 12, "src": "theme.ts:4"}}}, {"theme.ts": src})
        self.assertEqual((ok[0], ok[1], ok[3]), ([], 2, []))
        bad = self.check({"spacing": {"md": {"value": 14, "src": "theme.ts:4"}}}, {"theme.ts": src})
        self.assertEqual(len(bad[0]), 1, "md: 12 in code but 14 in design.json must drift, even though 14 is nowhere and 16 is close")

    def test_number_owned_by_another_token_is_not_a_match(self):
        src = "export const space = { md: 12, lg: 16 }\nexport const type = { caption: { fontSize: 14 } }\n"
        bad = self.check({"spacing": {"md": {"value": 14, "src": "theme.ts:1"}}}, {"theme.ts": src})
        self.assertEqual(len(bad[0]), 1)

    def test_unsourced_tokens_are_reported(self):
        res = self.check({"colors": {"made_up": "#123456"}, "spacing": {"huge": 99}}, {"x.ts": ""})
        self.assertEqual(sorted(res[3]), ["colors.made_up", "spacing.huge"])

    def test_ios_colorset_json(self):
        hexy = '{"colors":[{"color":{"color-space":"srgb","components":{"alpha":"1.000","blue":"0xFD","green":"0x5B","red":"0x3B"}},"idiom":"universal"}]}'
        floaty = '{"colors":[{"color":{"components":{"alpha":"1.000","blue":"0.992","green":"0.357","red":"0.231"}}}]}'
        for name, text in (("hex", hexy), ("float", floaty)):
            with self.subTest(name):
                res = self.check({"colors": {"primary": {"value": "#3B5BFD", "src": "Assets.xcassets/primary.colorset/Contents.json"}}},
                                 {"Assets.xcassets/primary.colorset/Contents.json": text})
                self.assertEqual(res[0], [])
        bad = self.check({"colors": {"primary": {"value": "#3B5BFE", "src": "Assets.xcassets/primary.colorset/Contents.json"}}},
                         {"Assets.xcassets/primary.colorset/Contents.json": hexy})
        self.assertEqual(len(bad[0]), 0, "within 1/255 counts as the same colour")
        bad = self.check({"colors": {"primary": {"value": "#2F4FE8", "src": "Assets.xcassets/primary.colorset/Contents.json"}}},
                         {"Assets.xcassets/primary.colorset/Contents.json": hexy})
        self.assertEqual(len(bad[0]), 1)

    def test_swiftui_and_uikit(self):
        src = ("extension Color {\n  static let primary = Color(red: 0.231, green: 0.357, blue: 0.992)\n}\n"
               "let accent = UIColor(red: 59/255, green: 91/255, blue: 253/255, alpha: 1)\n"
               "enum Space { static let md: CGFloat = 12 }\n")
        res = self.check({"colors": {"primary": {"value": "#3B5BFD", "src": "Theme.swift:2"}, "accent": {"value": "#3B5BFD", "src": "Theme.swift:4"}},
                          "spacing": {"md": {"value": 12, "src": "Theme.swift:5"}}}, {"Theme.swift": src})
        self.assertEqual((res[0], res[1]), ([], 3))
        bad = self.check({"spacing": {"md": {"value": 16, "src": "Theme.swift:5"}}}, {"Theme.swift": src})
        self.assertEqual(len(bad[0]), 1)

    def test_android_xml(self):
        colors = '<resources>\n  <color name="primary">#FF3B5BFD</color>\n  <color name="text">#FF111111</color>\n</resources>\n'
        dimens = '<resources>\n  <dimen name="md">12dp</dimen>\n  <dimen name="lg">16dp</dimen>\n</resources>\n'
        res = self.check({"colors": {"primary": {"value": "#3B5BFD", "src": "res/values/colors.xml:2"}},
                          "spacing": {"md": {"value": 12, "src": "res/values/dimens.xml:2"}}},
                         {"res/values/colors.xml": colors, "res/values/dimens.xml": dimens})
        self.assertEqual((res[0], res[1]), ([], 2))
        bad = self.check({"spacing": {"md": {"value": 16, "src": "res/values/dimens.xml:2"}}},
                         {"res/values/dimens.xml": dimens})
        self.assertEqual(len(bad[0]), 1)

    def test_flutter_and_compose(self):
        dart = "class AppColors {\n  static const primary = Color(0xFF3B5BFD);\n  static const double md = 12;\n}\n"
        kt = "val Primary = Color(0xFF3B5BFD)\nval Md = 12.dp\n"
        res = self.check({"colors": {"primary": {"value": "#3B5BFD", "src": "colors.dart:2"}}, "spacing": {"md": {"value": 12, "src": "colors.dart:3"}}},
                         {"colors.dart": dart})
        self.assertEqual((res[0], res[1]), ([], 2))
        res = self.check({"colors": {"primary": {"value": "#3B5BFD", "src": "Color.kt:1"}}, "spacing": {"md": {"value": 12, "src": "Color.kt:2"}}},
                         {"Color.kt": kt})
        self.assertEqual((res[0], res[1]), ([], 2))

    def test_css_custom_properties(self):
        css = ":root {\n  --color-primary: #3b5bfd;\n  --color-on-primary: #ffffff;\n  --space-md: 12px;\n}\n"
        res = self.check({"colors": {"primary": {"value": "#3B5BFD", "code": "--color-primary", "src": "app.css:2"}},
                          "spacing": {"md": {"value": 12, "code": "--space-md", "src": "app.css:4"}}}, {"app.css": css})
        self.assertEqual((res[0], res[1]), ([], 2))
        bad = self.check({"colors": {"primary": {"value": "#FFFFFF", "code": "--color-primary", "src": "app.css:2"}}}, {"app.css": css})
        self.assertEqual(len(bad[0]), 1, "#ffffff sits on the next line (on-primary) but is not --color-primary")

    def test_src_outside_the_app_root_is_refused(self):
        for bad in ("/etc/hosts:1", "../outside.ts:1"):
            res = self.check({"colors": {"primary": {"value": "#3B5BFD", "src": bad}}}, {"x.ts": ""})
            self.assertIn("inside the app root", res[0][0])

    def test_missing_source_file(self):
        res = self.check({"colors": {"primary": {"value": "#3B5BFD", "src": "nope.ts:3"}}}, {"x.ts": ""})
        self.assertIn("source file not found", res[0][0])


class Format(unittest.TestCase):
    def test_colours(self):
        self.assertEqual(parse_color("#fff"), (255, 255, 255, 1.0))
        self.assertEqual(parse_color("rgba(0, 0, 0, 0.5)"), (0, 0, 0, 0.5))
        self.assertEqual(contrast(parse_color("#000000"), parse_color("#FFFFFF")), 21.0)

    def test_validation_errors(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            d = make(tmp, {"roles": {"background": "bg", "text": "missing"}, "type": {"x": {"font": "nofont", "size": 12}}}, {})
            self.assertTrue(any("roles.text" in e for e in d.errors))
            self.assertTrue(any("type.x" in e for e in d.errors))
        finally:
            shutil.rmtree(tmp)


class Sample(unittest.TestCase):
    def test_sample_builds_and_passes_check(self):
        out = Path(tempfile.mkdtemp())
        try:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(build.main([str(SAMPLE), "--check"]), 0)
                self.assertEqual(build.main([str(SAMPLE), "--out", str(out)]), 0)
            for f in ("guide.html", "canvas.html", "tokens.json", "tokens.dark.json", "tokens.md"):
                self.assertTrue((out / f).exists(), f)
            tokens = json.loads((out / "tokens.json").read_text(encoding="utf-8"))
            self.assertEqual(tokens["color"]["primary"]["$value"]["hex"], "#3b5bfd")
            self.assertNotIn("missing frames", (out / "canvas.html").read_text(encoding="utf-8"))
        finally:
            shutil.rmtree(out)


if __name__ == "__main__":
    unittest.main()

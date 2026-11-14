"""Drift check tests: Swift/SwiftUI forms, exact src lines, every field the guide shows, the derived share,
per-theme code/src and native units. Run from the repo root:  python3 -m unittest discover tests"""

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
import mcp_server  # noqa: E402
from tokens import Design  # noqa: E402

SAMPLE = ROOT / "examples" / "acme-habits"


def make(tmp: Path, design: dict, files: dict) -> Design:
    """Write a design.json in tmp/design and app files under tmp/app."""
    (tmp / "design").mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        f = tmp / "app" / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    base = {"version": 1, "app": {"name": "Sample", "root": "../app"}, "roles": {"background": "bg", "text": "text"},
            "colors": {"bg": {"value": "#FFFFFF", "derived": "test"}, "text": {"value": "#111111", "derived": "test"}}}
    for k, v in design.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            base[k] = {**base[k], **v}
        else:
            base[k] = v
    (tmp / "design" / "design.json").write_text(json.dumps(base), encoding="utf-8")
    return Design(tmp / "design")


def cli(args):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = build.main([str(a) for a in args])
    return code, buf.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def check(self, design, files):
        d = make(self.tmp, design, files)
        self.assertEqual(d.errors, [])
        return d.check()

    def ok(self, design, files, msg=None):
        res = self.check(design, files)
        self.assertEqual((res[0], res[3]), ([], []), msg)
        return res

    def drifts(self, design, files, msg=None):
        res = self.check(design, files)
        self.assertEqual(len(res[0]), 1, msg)
        self.assertRegex(res[0][0], r"not found (where it is defined|on its src line|in the file)", "a real drift, not a missing file")
        return res


def color(value, src, **kw):
    return {"colors": {"brand": {"value": value, "src": src, **kw}}}


class BareHex(Base):
    swift = ('extension Color {\n  static let teal = Color(hex: "1F7A8C")\n  static let amber = Color(hex: "D98E04")\n}\n'
             'let palette = [\n  "1F7A8C",\n  "D98E04",\n]\n')

    def test_quoted_hex_without_prefix(self):
        files = {"Palette.swift": self.swift}
        self.ok({"colors": {"teal": {"value": "#1F7A8C", "src": "Palette.swift:2"},
                            "amber": {"value": "#D98E04", "src": "Palette.swift:3"},
                            "chart2": {"value": "#D98E04", "src": "Palette.swift:7"}}}, files)
        self.drifts(color("#1F7A8D", "Palette.swift:2", code="Color.teal"), files)

    def test_json_config_and_eight_digits(self):
        cfg = '{\n  "brand": "d98e04",\n  "overlay": \'FF1F7A8C\'\n}\n'
        self.ok({"colors": {"brand": {"value": "#D98E04", "src": "theme.json:2"},
                            "overlay": {"value": "#1F7A8C", "src": "theme.json:3"}}}, {"theme.json": cfg})

    def test_unquoted_numbers_are_not_colours(self):
        self.drifts(color("#123456", "Ids.swift:1"), {"Ids.swift": "static let brand = 123456\n"}, "a bare number is not a colour")


class Components(Base):
    def test_fractions_mixed_with_plain_ones(self):
        src = "static let brand = UIColor(red: 0x33 / 255, green: 0x66 / 255, blue: 1, alpha: 1)\n"
        self.ok(color("#3366FF", "Theme.swift:1"), {"Theme.swift": src}, "blue: 1 next to x/255 values means full strength")
        self.drifts(color("#3366F0", "Theme.swift:1"), {"Theme.swift": src})

    def test_other_component_forms_still_work(self):
        cases = {
            "colorset 0-255": '{"color":{"components":{"alpha":"1.000","blue":"1","green":"91","red":"59"}}}',
            "colorset hex": '{"color":{"components":{"alpha":"1.000","blue":"0x01","green":"0x5B","red":"0x3B"}}}',
            "SwiftUI 0-1": "static let brand = Color(red: 0.231, green: 0.357, blue: 0.004)",
            "UIColor cast": "static let brand = UIColor(red: CGFloat(0x3B) / 255, green: CGFloat(0x5B) / 255, blue: CGFloat(0x01) / 255, alpha: 1)",
        }
        for name, text in cases.items():
            with self.subTest(name):
                self.ok(color("#3B5B01", "c.txt:1"), {"c.txt": text + "\n"})


class ExactLines(Base):
    def test_unnamed_colour_given_the_hex_from_the_line_above(self):
        swift = 'let chartColors = [\n  Color(hex: "#1F7A8C"),\n  Color(hex: "#D98E04"),\n]\n'
        self.drifts({"colors": {"chart2": {"value": "#1F7A8C", "src": "Chart.swift:3"}}}, {"Chart.swift": swift})
        self.ok({"colors": {"chart2": {"value": "#D98E04", "src": "Chart.swift:3"}}}, {"Chart.swift": swift})

    def test_another_hex_two_lines_away(self):
        swift = 'enum Tint {\n  static let a = Color(hex: "#AA3355")\n  static let b = Color(hex: "#22CC88")\n  static let c = Color(hex: "#3B5BFD")\n}\n'
        self.drifts({"colors": {"accent": {"value": "#3B5BFD", "src": "Tint.swift:2"}}}, {"Tint.swift": swift})

    def test_a_named_definition_that_moved_is_still_found(self):
        ts = "// header\n// header\nexport const colors = {\n  primary: '#3B5BFD',\n  onPrimary: '#FFFFFF',\n}\n"
        self.ok({"colors": {"primary": {"value": "#3B5BFD", "src": "theme.ts:2"}}}, {"theme.ts": ts}, "src is 2 lines off; the name is found")

    def test_shadow_blur_is_not_the_y(self):
        swift = "static let card = ShadowStyle(color: .black.opacity(0.2), radius: 10, x: 0, y: 14)\n"
        self.drifts({"shadows": {"card": {"x": 0, "y": 14, "blur": 14, "color": "#000000", "opacity": 0.2, "src": "S.swift:1"}}},
                    {"S.swift": swift}, "blur 14 is the y, not the radius")

    def test_case_list_defines_every_name(self):
        swift = ("extension Font.TextStyle {\n  var size: CGFloat {\n    switch self {\n    case .largeTitle: return 34\n"
                 "    case .headline, .body: return 18\n    case .caption: return 12\n    @unknown default: return 17\n    }\n  }\n}\n")
        files = {"Type.swift": swift}
        font = {"fonts": {"sys": {"family": "-apple-system", "load": "system", "derived": "system font"}}}
        self.drifts({**font, "type": {"headline": {"font": "sys", "size": 17, "src": "Type.swift:5"}}}, files,
                    "17 two lines below belongs to @unknown default")
        self.ok({**font, "type": {"headline": {"font": "sys", "size": 18, "src": "Type.swift:5"},
                                  "body": {"font": "sys", "size": 18, "src": "Type.swift:5"}}}, files)

    def test_token_named_like_a_view_modifier(self):
        swift = ("enum Motion {\n  static let sheet = Animation.spring(response: 0.35, dampingFraction: 0.8)\n}\n"
                 "struct Root: View {\n  var body: some View {\n    Text(\"Hi\").sheet(isPresented: $show) { Detail() }\n  }\n}\n")
        files = {"Motion.swift": swift}
        self.ok({"motion": {"springs": {"sheet": {"response": 0.35, "dampingFraction": 0.8, "src": "Motion.swift:2"}}}}, files)
        self.drifts({"motion": {"springs": {"sheet": {"response": 0.5, "dampingFraction": 0.8, "src": "Motion.swift:2"}}}}, files)
        other = swift.replace("static let sheet =", "static let sheetSpring =")
        self.ok({"motion": {"springs": {"sheet": {"response": 0.35, "dampingFraction": 0.8, "src": "Motion.swift:2"}}}},
                {"Motion.swift": other}, "the src line has no `sheet`: it is checked itself; .sheet( is a call, not a definition")
        self.drifts({"motion": {"springs": {"sheet": {"response": 0.5, "dampingFraction": 0.8, "src": "Motion.swift:2"}}}},
                    {"Motion.swift": other})

    def test_src_line_that_states_nothing_does_not_hide_drift(self):
        swift = ("enum Motion {\n  static let sheet = Animation.spring(response: 0.35, dampingFraction: 0.86)\n"
                 "  static let pop = Animation.spring(duration: 0.4, bounce: 0.25)\n}\n")
        files = {"Motion.swift": swift}
        self.drifts({"motion": {"springs": {"sheet": {"response": 0.35, "dampingFraction": 0.8, "src": "Motion.swift:3"}}}}, files,
                    "src is one line off (pop); sheet's own definition says 0.86")
        self.ok({"motion": {"springs": {"sheet": {"response": 0.35, "dampingFraction": 0.86, "src": "Motion.swift:3"}}}}, files)

    def test_comments_are_not_values(self):
        ts = "export const space = {\n  gutter: 20, // was 24\n}\n"
        self.drifts({"spacing": {"gutter": {"value": 24, "src": "space.ts:2"}}}, {"space.ts": ts})

    def test_src_line_past_the_end(self):
        res = self.check(color("#3B5BFD", "x.ts:40"), {"x.ts": "export const a = 1\n"})
        self.assertIn("past the end", res[0][0])


class Shadows(Base):
    swift = "static let card = ShadowStyle(color: .black.opacity(0.28), radius: 12, x: 0, y: 6)\n"

    def shadow(self, **kw):
        base = {"x": 0, "y": 6, "radius": 12, "color": "#000000", "opacity": 0.28, "src": "S.swift:1"}
        base.update(kw)
        return {"shadows": {"card": {k: v for k, v in base.items() if v is not None}}}

    def test_swiftui_shadow_every_field(self):
        files = {"S.swift": self.swift}
        self.ok(self.shadow(), files)
        for bad in ({"opacity": 0.2}, {"x": 2}, {"y": 4}, {"radius": 6}, {"color": "#FFFFFF"}):
            with self.subTest(bad):
                self.drifts(self.shadow(**bad), files)

    def test_other_opacity_forms(self):
        for code in ("static let card = Shadow(color: Color.black.opacity(0.28), radius: 12, x: 0, y: 6)",
                     "static let card = Shadow(color: .black, opacity: 0.28, radius: 12, x: 0, y: 6)",
                     "card: { shadowColor: 'rgba(0, 0, 0, 0.28)', shadowRadius: 12, shadowOffset: { width: 0, height: 6 } },"):
            with self.subTest(code):
                self.ok(self.shadow(), {"S.swift": code + "\n"})

    def test_css_shadow_by_position(self):
        css = ":root {\n  --shadow-card: 0 2px 8px 1px rgba(0, 0, 0, 0.12);\n}\n"
        good = {"x": 0, "y": 2, "blur": 8, "spread": 1, "color": "#000000", "opacity": 0.12, "code": "--shadow-card", "src": "app.css:2"}
        self.ok({"shadows": {"card": good}}, {"app.css": css})
        for bad in ({"spread": 0}, {"blur": 2}, {"opacity": 0.2}):
            with self.subTest(bad):
                self.drifts({"shadows": {"card": {**good, **bad}}}, {"app.css": css})

    def test_fields_the_code_does_not_state_are_listed(self):
        res = self.ok({"shadows": {"soft": {"y": 2, "blur": 8, "color": "#000000", "opacity": 0.33, "src": "S.swift:1"}}},
                      {"S.swift": "static let soft = ShadowStyle(blur: 8, y: 2)\n"})
        self.assertEqual(res.not_checked, ["shadows.soft colour", "shadows.soft opacity"])

    def test_blur_written_as_twice_a_swift_radius(self):
        res = self.drifts({"shadows": {"card": {"x": 0, "y": 6, "blur": 24, "color": "#000000", "opacity": 0.28, "src": "S.swift:1"}}},
                          {"S.swift": self.swift})
        self.assertIn("give it as radius", res[0][0])


class Weights(Base):
    def weight(self, w):
        return {"fonts": {"f": {"family": "Inter", "weight": w, "derived": "t"}},
                "type": {"headline": {"font": "f", "size": 17, "src": "T.txt:1"}}}

    def test_weight_forms(self):
        cases = {
            "numeric": "headline: { fontSize: 17, fontWeight: 600 },",
            "css string": "headline: { fontSize: 17, fontWeight: '600' },",
            "css property": ".headline { font-size: 17px; font-weight: 600; }",
            "swift": "static let headline = Font.system(size: 17, weight: .semibold)",
            "swift chained": "static let headline = Font.system(size: 17).weight(.semibold)",
            "Font.Weight": "static let headline = UIFont.systemFont(ofSize: 17, weight: UIFont.Weight.semibold)",
            "compose": "val Headline = TextStyle(fontSize = 17.sp, fontWeight = FontWeight.SemiBold)",
            "flutter": "static const headline = TextStyle(fontSize: 17, fontWeight: FontWeight.w600);",
            "font file name": "headline: { fontFamily: 'Inter_600SemiBold', fontSize: 17 },",
        }
        for name, text in cases.items():
            with self.subTest(name):
                files = {"T.txt": text + "\n"}
                res = self.ok(self.weight(600), files)
                self.assertEqual(res.not_checked, [])
                self.drifts(self.weight(700), files)

    def test_bold_call(self):
        self.ok(self.weight(700), {"T.txt": "static let headline = Font.system(size: 17).bold()\n"})

    def test_no_weight_written_is_listed(self):
        design = self.weight(600)
        design["type"]["headline"]["lineHeight"] = 22
        res = self.ok(design, {"T.txt": "    case .headline: return 17\n"})
        self.assertEqual(res.not_checked, ["type.headline line height", "type.headline weight"])

    def test_line_height_and_letter_spacing_use_their_labels(self):
        ts = "export const type = {\n  title: { fontSize: 22, lineHeight: 28, letterSpacing: -0.2 },\n}\n"
        good = {"fonts": {"f": {"family": "Inter", "derived": "t"}}, "type": {"title": {"font": "f", "size": 22, "lineHeight": 28, "letterSpacing": -0.2, "src": "type.ts:2"}}}
        self.ok(good, {"type.ts": ts})
        bad = json.loads(json.dumps(good))
        bad["type"]["title"]["size"] = 28
        self.drifts(bad, {"type.ts": ts}, "28 is the line height, not the size")
        bad["type"]["title"].update(size=22, letterSpacing=-0.5)
        self.drifts(bad, {"type.ts": ts})


class DerivedShare(Base):
    def write(self):
        make(self.tmp, {"colors": {"brand": {"value": "#3B5BFD", "src": "theme.ts:1"},
                                   "tint": {"value": "#22CC88", "derived": "mixed from brand; copied from Theme.swift:12"}}},
             {"theme.ts": "export const brand = '#3B5BFD'\n"})
        return self.tmp / "design"

    def test_check_text_json_and_cap(self):
        d = self.write()
        code, out = cli([d, "--check"])
        self.assertEqual(code, 0)
        self.assertIn("drift check: 1 ok, 0 drifted, 0 without src, 3 derived (75% not checked)", out)
        self.assertIn("could be checked: colors.tint (its note names Theme.swift:12)", out)
        code, out = cli([d, "--check", "--json"])
        data = json.loads(out)
        self.assertEqual((data["derivedShare"], len(data["derived"]), data["couldBeChecked"]), (0.75, 3, ["colors.tint (its note names Theme.swift:12)"]))
        code, out = cli([d, "--check", "--max-derived", "50"])
        self.assertEqual(code, 1)
        self.assertIn("over --max-derived 50%", out)
        code, out = cli([d, "--check", "--max-derived", "80", "--json"])
        self.assertEqual((code, json.loads(out)["ok"], json.loads(out)["overMaxDerived"]), (0, True, False))

    def test_build_summary_and_guide(self):
        d = self.write()
        make(self.tmp, {"colors": {"brand": {"value": "#3B5BFD", "src": "theme.ts:1"}},
                        "fonts": {"f": {"family": "Inter", "weight": 600, "src": "theme.ts:2"}}},
             {"theme.ts": "export const brand = '#3B5BFD'\nexport const f = 'Inter'\n"})
        code, out = cli([d, "--out", self.tmp / "out"])
        self.assertIn("derived: 2 (50%)", out)
        guide = (self.tmp / "out" / "guide.html").read_text(encoding="utf-8")
        self.assertIn("Not checked, because the code does not state them: fonts.f weight", guide)
        code, out = cli([d, "--out", self.tmp / "out", "--json"])
        data = json.loads(out)
        self.assertEqual((data["derivedShare"], data["notChecked"]), (0.5, ["fonts.f weight"]))
        code, out = cli([d, "--check"])
        self.assertIn("not checked: fonts.f weight", out)

    def test_mcp_check_takes_a_cap(self):
        d = self.write()
        mcp_server.ROOT = self.tmp.resolve()
        try:
            data = mcp_server.call_tool("design_canvas_check", {"dir": "design", "maxDerived": 10})["structuredContent"]
            self.assertEqual((data["ok"], data["overMaxDerived"], data["exitCode"]), (False, True, 1))
            with self.assertRaises(mcp_server.InputError):
                mcp_server.call_tool("design_canvas_check", {"dir": "design", "maxDerived": "ten"})
        finally:
            del mcp_server.ROOT


class PerTheme(Base):
    swift = ('enum Palette {\n  static let sand = Color(hex: "E8E2D0")\n  static let charcoal = Color(hex: "2A2A2A")\n'
             '  static let slate = Color(hex: "0F1720")\n}\n')
    themes = [{"id": "light"}, {"id": "dark"}]

    def token(self, dark):
        return {"themes": self.themes, "colors": {"bg": {
            "value": {"light": "#E8E2D0", "dark": dark}, "code": {"light": "Palette.sand", "dark": "Palette.slate"},
            "src": {"light": "Palette.swift:2", "dark": "Palette.swift:4"}}}}

    def test_each_theme_against_its_own_name_and_line(self):
        files = {"Palette.swift": self.swift}
        self.ok(self.token("#0F1720"), files)
        res = self.drifts(self.token("#2A2A2A"), files, "#2A2A2A is charcoal, not slate")
        self.assertIn("(dark)", res[0][0])

    def test_code_only_per_theme(self):
        files = {"Palette.swift": self.swift}
        design = {"themes": self.themes, "colors": {"bg": {
            "value": {"light": "#E8E2D0", "dark": "#0F1720"}, "code": {"light": "Palette.sand", "dark": "Palette.slate"},
            "src": "Palette.swift:2, Palette.swift:4"}}}
        self.ok(design, files)

    def test_unknown_theme_is_an_error(self):
        d = make(self.tmp, {"themes": self.themes, "colors": {"bg": {"value": "#FFFFFF", "src": {"light": "a:1", "sepia": "a:2"}}}}, {})
        self.assertTrue(any("unknown theme(s) sepia" in e for e in d.errors), d.errors)

    def test_guide_shows_both_names(self):
        make(self.tmp, self.token("#0F1720"), {"Palette.swift": self.swift})
        cli([self.tmp / "design", "--out", self.tmp / "out"])
        self.assertIn("light: Palette.sand · dark: Palette.slate", (self.tmp / "out" / "guide.html").read_text(encoding="utf-8"))


class NativeUnits(Base):
    def test_durations_in_seconds(self):
        swift = "enum Motion {\n  static let fast = Animation.easeOut(duration: 0.25)\n  static let slow: Double = 0.3\n}\n"
        files = {"Motion.swift": swift}
        self.ok({"motion": {"durations": {"fast": {"value": 250, "src": "Motion.swift:2"}, "slow": {"value": 300, "src": "Motion.swift:3"}}}}, files)
        self.drifts({"motion": {"durations": {"fast": {"value": 300, "src": "Motion.swift:2"}}}}, files)

    def test_shadow_radius(self):
        d = make(self.tmp, {"shadows": {"card": {"x": 0, "y": 4, "radius": 8, "color": "#000000", "opacity": 0.2, "src": "S.swift:1"}}},
                 {"S.swift": "static let card = ShadowStyle(color: .black.opacity(0.2), radius: 8, x: 0, y: 4)\n"})
        res = d.check()
        self.assertEqual((res[0], res[1]), ([], 1))
        self.assertIn("--sh-card: 0px 4px 16px 0px rgba(0, 0, 0, 0.2);", d.css())
        self.assertEqual(d.dtcg()["shadow"]["card"]["$value"]["blur"], {"value": 16, "unit": "px"})
        self.drifts({"shadows": {"card": {"x": 0, "y": 4, "radius": 6, "color": "#000000", "opacity": 0.2, "src": "S.swift:1"}}},
                    {"S.swift": "static let card = ShadowStyle(color: .black.opacity(0.2), radius: 8, x: 0, y: 4)\n"})

    def test_swiftui_springs(self):
        swift = ("enum Motion {\n  static let snappy = Animation.spring(response: 0.2, dampingFraction: 0.7)\n"
                 "  static let bouncy = Animation.spring(duration: 0.5, bounce: 0.3)\n}\n")
        files = {"Motion.swift": swift}
        d = make(self.tmp, {"motion": {"springs": {"snappy": {"response": 0.2, "dampingFraction": 0.7, "src": "Motion.swift:2"},
                                                   "bouncy": {"duration": 0.5, "bounce": 0.3, "src": "Motion.swift:3"}}}}, files)
        self.assertEqual(d.errors, [])
        res = d.check()
        self.assertEqual((res[0], res[1]), ([], 2))
        springs = d.dtcg()["$extensions"]["dev.design-canvas"]["springs"]
        self.assertEqual((springs["snappy"]["stiffness"], springs["snappy"]["damping"]), (986.96, 43.98))
        self.assertEqual((springs["bouncy"]["stiffness"], springs["bouncy"]["damping"]), (157.91, 17.59))
        self.assertEqual(springs["snappy"]["response"], 0.2)
        self.drifts({"motion": {"springs": {"snappy": {"response": 0.25, "dampingFraction": 0.7, "src": "Motion.swift:2"}}}}, files)
        self.drifts({"motion": {"springs": {"bouncy": {"duration": 0.5, "bounce": 0.2, "src": "Motion.swift:3"}}}}, files)

    def test_springs_compared_across_forms(self):
        swift = ("static let sheet = Animation.spring(response: 0.35, dampingFraction: 0.8)\n"
                 "static let pop = Animation.interpolatingSpring(stiffness: 322.27, damping: 28.72)\n")
        files = {"Motion.swift": swift}
        self.ok({"motion": {"springs": {"sheet": {"stiffness": 322.27, "damping": 28.72, "src": "Motion.swift:1"},
                                        "pop": {"response": 0.35, "dampingFraction": 0.8, "src": "Motion.swift:2"}}}}, files)
        self.drifts({"motion": {"springs": {"sheet": {"stiffness": 322.27, "damping": 30, "src": "Motion.swift:1"}}}}, files)
        self.drifts({"motion": {"springs": {"pop": {"response": 0.5, "dampingFraction": 0.8, "src": "Motion.swift:2"}}}}, files)

    def test_bad_spring_values_are_errors(self):
        d = make(self.tmp, {"motion": {"springs": {"a": {"response": 0}, "b": {"bounce": -1}, "c": {"dampingFraction": "x"}}}}, {})
        self.assertEqual(len(d.errors), 3, d.errors)

    def test_schema_lists_the_new_fields(self):
        schema = json.loads((ROOT / "spec" / "design.schema.json").read_text(encoding="utf-8"))
        shadow = schema["properties"]["shadows"]["additionalProperties"]["allOf"][1]["properties"]
        spring = schema["properties"]["motion"]["properties"]["springs"]["additionalProperties"]["allOf"][1]["properties"]
        self.assertIn("radius", shadow)
        self.assertTrue({"response", "dampingFraction", "bounce", "duration"} <= set(spring))
        for field in ("code", "src"):
            ref = schema["$defs"]["meta"]["properties"][field]["$ref"].split("/")[-1]
            self.assertEqual([x["type"] for x in schema["$defs"][ref]["oneOf"]], ["string", "object"])


class Compose(Base):
    kt = ("object AppColors {\n    val Primary = Color(0xFF3B5BFD)\n    val Scrim = Color(0x73000000)\n}\n"
          "object AppType {\n    val Title = TextStyle(fontSize = 22.sp, lineHeight = 28.sp, fontWeight = FontWeight.SemiBold, letterSpacing = (-0.2).sp)\n}\n"
          "object AppMotion {\n    val Quick = tween<Float>(durationMillis = 150)\n    val Bouncy = spring<Float>(dampingRatio = 0.6f, stiffness = 380f)\n}\n")
    good = {"colors": {"primary": {"value": "#3B5BFD", "code": "AppColors.Primary", "src": "Theme.kt:2"},
                       "scrim": {"value": "rgba(0, 0, 0, 0.45)", "code": "AppColors.Scrim", "src": "Theme.kt:3"}},
            "fonts": {"semi": {"family": "Inter", "weight": 600, "derived": "t"}},
            "type": {"title": {"font": "semi", "size": 22, "lineHeight": 28, "letterSpacing": -0.2, "code": "AppType.Title", "src": "Theme.kt:6"}},
            "motion": {"durations": {"quick": {"value": 150, "code": "AppMotion.Quick", "src": "Theme.kt:9"}},
                       "springs": {"bouncy": {"dampingFraction": 0.6, "stiffness": 380, "code": "AppMotion.Bouncy", "src": "Theme.kt:10"}}}}

    def test_compose_theme(self):
        res = self.ok(self.good, {"Theme.kt": self.kt})
        self.assertEqual((res[1], res.not_checked), (5, []))

    def test_compose_planted_values(self):
        plants = [("colors", "scrim", {"value": "rgba(0, 0, 0, 0.6)"}), ("type", "title", {"letterSpacing": -0.5}),
                  ("type", "title", {"lineHeight": 22}), ("fonts", "semi", {"weight": 700})]
        for group, key, change in plants:
            with self.subTest(f"{group}.{key} {change}"):
                design = json.loads(json.dumps(self.good))
                design[group][key].update(change)
                self.drifts(design, {"Theme.kt": self.kt})
        design = json.loads(json.dumps(self.good))
        design["motion"]["springs"]["bouncy"]["stiffness"] = 300
        self.drifts(design, {"Theme.kt": self.kt})


class AliasesAndRenames(Base):
    """A semantic token that points at a palette entry, re-pointed or renamed while the colours stay the same."""
    palette = "export const palette = {\n  indigo4: '#748FFC',\n  indigo3: '#91A7FF',\n}\n"
    swift = ('enum Palette {\n  static let sand = Color(hex: "E8E2D0")\n  static let slate = Color(hex: "0F1720")\n'
             '  static let graphite = Color(hex: "495057")\n}\n')
    themes = [{"id": "light"}, {"id": "dark"}]

    def fails(self, design, files, pattern):
        res = self.check(design, files)
        self.assertEqual(len(res[0]), 1, res[0])
        self.assertRegex(res[0][0], pattern)
        return res

    def accent(self, src="theme.ts:3", **kw):
        return {"colors": {"accent": {"value": "#748FFC", "src": src, **kw}}}

    def theme(self, ref):
        return "import { palette } from './palette'\nexport const dark = {\n  accent: " + ref + ",\n}\n"

    def test_alias_is_followed_into_the_palette_file(self):
        self.ok(self.accent(), {"palette.ts": self.palette, "theme.ts": self.theme("palette.indigo4")})
        res = self.drifts(self.accent(), {"palette.ts": self.palette, "theme.ts": self.theme("palette.indigo3")})
        self.assertIn("via palette.indigo3", res[0][0])

    def test_alias_with_no_definition_says_so(self):
        res = self.drifts(self.accent(), {"theme.ts": self.theme("shades.indigo4")})
        self.assertIn("shades.indigo4, whose definition was not found", res[0][0])

    def test_nested_palette_entry(self):
        pal = "export const colors = {\n  blue: { 400: '#4C6EF5', 300: '#748FFC' },\n  green: { 300: '#8CE99A' },\n}\n"
        self.ok(self.accent(), {"palette.ts": pal, "theme.ts": self.theme("colors.blue[300]")})
        self.drifts(self.accent(), {"palette.ts": pal, "theme.ts": self.theme("colors.green[300]")})

    def test_swift_light_and_dark_alias(self):
        theme = "extension Color {\n  static let surface = Color(light: Palette.sand, dark: Palette.{dark})\n}\n"
        design = {"themes": self.themes, "colors": {"surface": {"value": {"light": "#E8E2D0", "dark": "#0F1720"},
                                                                "src": "Theme.swift:2"}}}
        self.ok(design, {"Palette.swift": self.swift, "Theme.swift": theme.replace("{dark}", "slate")})
        res = self.drifts(design, {"Palette.swift": self.swift, "Theme.swift": theme.replace("{dark}", "graphite")})
        self.assertIn("#0f1720", res[0][0].lower())

    def test_repointed_alias_when_src_is_the_palette_entry(self):
        theme = "extension Color {\n  static let surface = Color(light: Palette.sand, dark: Palette.{dark})\n}\n"
        design = {"themes": self.themes, "colors": {"surface": {
            "value": {"light": "#E8E2D0", "dark": "#0F1720"}, "code": {"light": "Palette.sand", "dark": "Palette.slate"},
            "src": {"light": "Palette.swift:2", "dark": "Palette.swift:3"}}}}
        self.ok(design, {"Palette.swift": self.swift, "Theme.swift": theme.replace("{dark}", "slate")})
        self.fails(design, {"Palette.swift": self.swift, "Theme.swift": theme.replace("{dark}", "graphite")},
                   r"`surface` now refers to Palette\.sand, Palette\.graphite \(Theme\.swift:2\), not `Palette\.slate`")

    def test_src_lists_the_alias_line_and_the_palette_line(self):
        files = {"theme.ts": "const palette = {\n  indigo4: '#748FFC',\n  indigo3: '#91A7FF' }\nexport const dark = {\n"
                             "  accent: palette.indigo4,\n}\n"}
        self.ok(self.accent("theme.ts:5, theme.ts:2"), files)
        files["theme.ts"] = files["theme.ts"].replace("accent: palette.indigo4", "accent: palette.indigo3")
        self.fails(self.accent("theme.ts:5, theme.ts:2"), files,
                   r"now refers to palette\.indigo3, but its src line \(theme\.ts:2\) defines `indigo4`")

    def test_src_at_the_palette_entry_without_a_code_name(self):
        near = "const palette = {\n  indigo4: '#748FFC',\n  indigo3: '#91A7FF' }\nexport const dark = {\n  accent: palette.indigo4,\n}\n"
        far = {"palette.ts": self.palette, "theme.ts": self.theme("palette.indigo4")}
        for code in (None, "theme.accent"):
            kw = {"code": code} if code else {}
            self.ok(self.accent("theme.ts:2", **kw), {"theme.ts": near}, f"near, {code}")
            self.fails(self.accent("theme.ts:2", **kw), {"theme.ts": near.replace("palette.indigo4", "palette.indigo3")},
                       r"now refers to palette\.indigo3, but its src line \(theme\.ts:2\) defines `indigo4`")
            self.ok(self.accent("palette.ts:2", **kw), far, f"other file, {code}")
            self.fails(self.accent("palette.ts:2", **kw), {**far, "theme.ts": self.theme("palette.indigo3")},
                       r"`accent` now refers to palette\.indigo3 \(theme\.ts:3\), but its src line \(palette\.ts:2\) defines `indigo4`")

    def test_renamed_token_fails_even_with_the_same_colour(self):
        files = {"theme.ts": "export const dark = {\n  bg: '#0E0F12',\n  brand: '#748FFC',\n}\n"}
        self.fails(self.accent("theme.ts:3", code="theme.accent"), files,
                   r"its src line now defines `brand`, not `accent` \(theme\.ts:3\)")

    def test_names_that_are_the_same_token_are_not_renames(self):
        css = ":root {\n  --c-accent: #748FFC;\n}\n"
        self.ok(self.accent("theme.css:2"), {"theme.css": css})
        tw = "module.exports = { theme: { colors: {\n  accent: {\n    DEFAULT: '#748FFC',\n  },\n} } }\n"
        self.ok(self.accent("tailwind.config.js:3"), {"tailwind.config.js": tw})
        self.ok(self.accent("Colors.kt:2"), {"Colors.kt": "object AppColors {\n  val Accent = Color(0xFF748FFC)\n}\n"})


class Sample(unittest.TestCase):
    def test_sample_has_no_drift_and_nothing_unchecked(self):
        res = Design(SAMPLE).check()
        self.assertEqual((res[0], res[3], res.not_checked), ([], [], []))


if __name__ == "__main__":
    unittest.main()

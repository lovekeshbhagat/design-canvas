"""Read design.json and turn it into CSS variables, design tokens (DTCG), Markdown,
token tables for the guide, contrast numbers and the drift check.

Python 3.9+ standard library only.
"""

from __future__ import annotations

import html
import json
import math
import re
from functools import lru_cache
from pathlib import Path

from reviews import safe_rel

ROLES = ["background", "surface", "surface2", "text", "textMuted", "accent", "onAccent", "border", "danger", "scrim"]
ROLE_VAR = {"background": "bg", "surface": "surface", "surface2": "surface-2", "text": "text", "textMuted": "muted",
            "accent": "accent", "onAccent": "on-accent", "border": "border", "danger": "danger", "scrim": "scrim"}
ROLE_FALLBACK = {
    "surface": "var(--role-bg)",
    "surface2": "var(--role-surface)",
    "textMuted": "color-mix(in srgb, var(--role-text) 60%, transparent)",
    "accent": "var(--role-text)",
    "onAccent": "var(--role-bg)",
    "border": "color-mix(in srgb, var(--role-text) 15%, transparent)",
    "danger": "#D93025",
    "scrim": "rgba(0, 0, 0, 0.5)",
}
# Words in a colour token's name that mark it as text, and words that mark it as a fill even when
# a text word is there too ("textFieldBg"). Ambiguous words such as "ink" or "content" are left out:
# apps use them for backgrounds as often as for text. Say it with `on` or `text` in design.json instead.
TEXT_WORDS = {"text", "label", "foreground", "fg"}
FILL_WORDS = {"bg", "background", "fill", "surface", "border", "stroke", "divider", "separator", "shadow",
              "scrim", "overlay", "backdrop", "selection", "highlight"}
FILL_ROLES = ("background", "surface", "surface2", "border", "scrim")
TEXT_ROLES = ("text", "textMuted", "onAccent")
DEFAULT_LINE_RATIO = 1.2  # stands in for "the platform default" where a format needs a number (DTCG)


def esc(s) -> str:
    return html.escape(str(s))


def kebab(name: str) -> str:
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "-", str(name))
    s = re.sub(r"[^A-Za-z0-9]+", "-", s)
    return s.strip("-").lower()


def num(v) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:g}"


# ---------------------------------------------------------------- colour maths
def parse_color(v: str):
    """'#rgb' | '#rrggbb' | '#rrggbbaa' | 'rgb(a)(...)' | 'transparent' -> (r, g, b, a)"""
    s = v.strip().lower()
    if s == "transparent":
        return (0, 0, 0, 0.0)
    if s.startswith("#"):
        h = s[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        if len(h) not in (6, 8) or not re.fullmatch(r"[0-9a-f]+", h):
            raise ValueError(f"bad hex colour {v!r}")
        a = int(h[6:8], 16) / 255 if len(h) == 8 else 1.0
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), round(a, 4))
    m = re.fullmatch(r"rgba?\(([^)]*)\)", s.replace(" ", ""))
    if m:
        parts = re.split(r"[,/]", m.group(1))
        r, g, b = (int(round(float(x))) for x in parts[:3])
        a = float(parts[3].rstrip("%")) / (100 if parts[3].endswith("%") else 1) if len(parts) > 3 else 1.0
        return (r, g, b, a)
    raise ValueError(f"unsupported colour {v!r} (use hex or rgba())")


def to_hex(rgba) -> str:
    return "#%02x%02x%02x" % tuple(rgba[:3])


def luminance(rgb) -> float:
    def ch(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(c) for c in rgb[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def over(fg, bg):
    """Composite a possibly transparent colour over an opaque background."""
    a = fg[3]
    return tuple(round(fg[i] * a + bg[i] * (1 - a)) for i in range(3)) + (1.0,)


def contrast(fg, bg) -> float:
    bg = over(bg, (255, 255, 255, 1.0)) if bg[3] < 1 else bg
    fg = over(fg, bg)
    a, b = luminance(fg), luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return round((hi + 0.05) / (lo + 0.05), 2)


# ---------------------------------------------------------------- loading
class Design:
    def __init__(self, design_dir: Path):
        self.dir = Path(design_dir).resolve()
        self.path = self.dir / "design.json"
        if not self.path.exists():
            raise SystemExit(f"design-canvas: no design.json in {self.dir}")
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise SystemExit(f"design-canvas: design.json is not valid JSON: {e}")
        self.raw = raw
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.app = raw.get("app") or {}
        self.name = self.app.get("name", "App")
        frame = self.app.get("frame") or {}
        self.frame = {"device": frame.get("device", "phone"), "width": frame.get("width", 390), "height": frame.get("height", 844)}
        self.root = (self.dir / self.app.get("root", "..")).resolve()
        self.themes = raw.get("themes") or [{"id": "default", "label": "Default"}]
        self.theme_ids = [t["id"] for t in self.themes]
        self.default = self.theme_ids[0]
        self.colors = self._colors(raw.get("colors") or {})
        self._read_on()
        self.roles = raw.get("roles") or {}
        self.fonts = raw.get("fonts") or {}
        self.type = {k: dict(v) for k, v in (raw.get("type") or {}).items()}
        self.spacing = self._numbers(raw.get("spacing") or {}, "spacing")
        self.radii = self._numbers(raw.get("radii") or {}, "radii")
        self.shadows = self._shadows(raw.get("shadows") or {})
        motion = raw.get("motion") or {}
        self.durations = self._numbers(motion.get("durations") or {}, "durations")
        self.easings = {k: (v if isinstance(v, dict) else {"value": v}) for k, v in (motion.get("easings") or {}).items()}
        self.springs = self._springs(motion.get("springs") or {})
        self.icons = raw.get("icons") or {"items": {}}
        self.components = raw.get("components") or {}
        self._validate()
        for t in self.themes:
            if not t.get("scheme"):
                t["scheme"] = self.scheme_of(t["id"])
            t.setdefault("label", t["id"].title())

    # -- normalisers
    def _colors(self, raw):
        out = {}
        for k, v in raw.items():
            meta = dict(v) if isinstance(v, dict) and "value" in v else {"value": v}
            val = meta["value"]
            per = dict(val) if isinstance(val, dict) else {t: val for t in self.theme_ids}
            unknown = [t for t in per if t not in self.theme_ids]
            if unknown:
                self.errors.append(f"colors.{k}: unknown theme(s) {', '.join(unknown)}")
            if self.default not in per:
                self.errors.append(f"colors.{k}: needs a value for the default theme '{self.default}'")
                continue
            for t in self.theme_ids:
                if t not in per:
                    self.warnings.append(f"colors.{k} has no value for the '{t}' theme; using '{self.default}'")
                per.setdefault(t, per[self.default])
            parsed = {}
            for t, s in per.items():
                try:
                    parsed[t] = parse_color(s)
                except (ValueError, TypeError) as e:
                    self.errors.append(f"colors.{k} ({t}): {e}")
            meta["values"] = per
            meta["rgba"] = parsed
            out[k] = meta
        return out

    def _read_on(self):
        """`on`: the fill(s) a colour is read on. A name, a list of names, or one of those per theme.
        Stored per theme as a list under `_on`."""
        def names(x):
            if isinstance(x, str) and x:
                return [x]
            if isinstance(x, list) and x and all(isinstance(n, str) and n for n in x):
                return list(x)
            return None

        for k, meta in self.colors.items():
            if "text" in meta and not isinstance(meta["text"], bool):
                self.errors.append(f"colors.{k}.text: use true or false")
            on = meta.get("on")
            if on is None:
                continue
            raw = dict(on) if isinstance(on, dict) else {t: on for t in self.theme_ids}
            unknown = [t for t in raw if t not in self.theme_ids]
            if unknown:
                self.errors.append(f"colors.{k}.on: unknown theme(s) {', '.join(unknown)}")
            if not raw or self.default not in raw:
                self.errors.append(f"colors.{k}.on: needs a value for the default theme '{self.default}'")
                continue
            per = {}
            for t in self.theme_ids:
                if t not in raw:
                    self.warnings.append(f"colors.{k}.on has no value for the '{t}' theme; using '{self.default}'")
                got = names(raw.get(t, raw[self.default]))
                if got is None:
                    self.errors.append(f"colors.{k}.on: give a colour token name, a list of names, or one of those per theme")
                    per = None
                    break
                per[t] = got
            if per is None:
                continue
            for n in sorted({n for v in per.values() for n in v}):
                if n not in self.colors:
                    self.errors.append(f"colors.{k}.on: '{n}' is not a colour token")
            meta["_on"] = per

    def _numbers(self, raw, where):
        out = {}
        for k, v in raw.items():
            meta = dict(v) if isinstance(v, dict) else {"value": v}
            if not isinstance(meta.get("value"), (int, float)):
                self.errors.append(f"{where}.{k}: value must be a number")
                continue
            out[k] = meta
        return out

    def _shadows(self, raw):
        """A shadow may give `radius` (SwiftUI/UIKit write a radius about half the CSS blur): blur = 2 x radius."""
        out = {}
        for k, v in raw.items():
            meta = dict(v) if isinstance(v, dict) else {}
            r = meta.get("radius")
            if r is not None and not isinstance(r, (int, float)):
                self.errors.append(f"shadows.{k}: radius must be a number")
            elif r is not None and "blur" not in meta:
                meta["blur"] = r * 2
            out[k] = meta
        return out

    def _springs(self, raw):
        """SwiftUI-style springs (response + dampingFraction, or duration + bounce, in seconds) also get the
        stiffness and damping that CSS, DTCG and previews use: stiffness = (2pi / response)^2 x mass,
        damping = 4pi x dampingFraction x mass / response. mass defaults to 1."""
        out = {}
        for k, v in raw.items():
            meta = dict(v) if isinstance(v, dict) else {}
            fields = ("damping", "stiffness", "mass", "response", "dampingFraction", "duration", "bounce")
            bad = [f for f in fields if f in meta and not isinstance(meta[f], (int, float))]
            if bad:
                self.errors.append(f"springs.{k}: {', '.join(bad)} must be a number")
                out[k] = meta
                continue
            mass = meta.get("mass", 1)
            response = frac = None
            if "response" in meta or "dampingFraction" in meta:
                response, frac = meta.get("response", 0.5), meta.get("dampingFraction", 0.825)  # SwiftUI's defaults
            elif "duration" in meta or "bounce" in meta:
                response, bounce = meta.get("duration", 0.5), meta.get("bounce", 0)
                if not -1 < bounce <= 1:
                    self.errors.append(f"springs.{k}: bounce must be above -1 and at most 1")
                    out[k] = meta
                    continue
                frac = 1 - bounce if bounce >= 0 else 1 / (1 + bounce)
            if response is not None:
                if response <= 0 or frac < 0:
                    self.errors.append(f"springs.{k}: response (or duration) must be above 0 and dampingFraction 0 or more")
                else:
                    meta.setdefault("stiffness", round((2 * math.pi / response) ** 2 * mass, 2))
                    meta.setdefault("damping", round(4 * math.pi * frac * mass / response, 2))
            out[k] = meta
        return out

    def _validate(self):
        if self.raw.get("version") != 1:
            self.errors.append("version must be 1")
        if not self.app.get("name"):
            self.errors.append("app.name is required")
        if len(set(self.theme_ids)) != len(self.theme_ids):
            self.errors.append("themes: ids must be unique")
        for r in ("background", "text"):
            if r not in self.roles:
                self.errors.append(f"roles.{r} is required")
        for r, tok in self.roles.items():
            if r not in ROLES:
                self.errors.append(f"roles.{r}: unknown role (use {', '.join(ROLES)})")
            elif tok not in self.colors:
                self.errors.append(f"roles.{r}: '{tok}' is not a colour token")
        for k, v in self.type.items():
            if v.get("font") not in self.fonts:
                self.errors.append(f"type.{k}: font '{v.get('font')}' is not a key in fonts")
            if not isinstance(v.get("size"), (int, float)):
                self.errors.append(f"type.{k}: size must be a number")
        for k, v in self.shadows.items():
            c = v.get("color", "#000000")
            if c not in self.colors:
                try:
                    parse_color(c)
                except ValueError as e:
                    self.errors.append(f"shadows.{k}: {e}")
        for k, v in (self.icons.get("items") or {}).items():
            if not isinstance(v, dict) or not (isinstance(v.get("svg"), str) or isinstance(v.get("system"), str)):
                self.errors.append(f"icons.items.{k}: give svg (the icon's shapes) or, for an operating-system icon, system and name")
                continue
            if "<svg" in v.get("svg", ""):
                self.errors.append(f"icons.items.{k}: give only the inner shapes, without the <svg> wrapper")
            if re.search(r"<script|on\w+\s*=", v.get("svg", ""), re.I):
                self.errors.append(f"icons.items.{k}: scripts and event handlers are not allowed")
        if self.frame["device"] not in ("phone", "browser", "none"):
            self.errors.append("app.frame.device must be phone, browser or none")
        self._validate_sources()

    def _validate_sources(self):
        """`code` and `src` are strings, or objects with one string per theme id."""
        groups = (("colors", self.colors), ("fonts", self.fonts), ("type", self.type), ("spacing", self.spacing), ("radii", self.radii),
                  ("shadows", self.shadows), ("durations", self.durations), ("easings", self.easings), ("springs", self.springs))
        for where, items in groups:
            for k, v in items.items():
                for field in ("code", "src"):
                    val = v.get(field) if isinstance(v, dict) else None
                    if val is None or isinstance(val, str):
                        continue
                    if not isinstance(val, dict) or not val or not all(isinstance(x, str) for x in val.values()):
                        self.errors.append(f"{where}.{k}: {field} must be a string, or an object with one string per theme")
                        continue
                    unknown = [t for t in val if t not in self.theme_ids]
                    if unknown:
                        self.errors.append(f"{where}.{k}: {field} names unknown theme(s) {', '.join(unknown)}")

    # -- helpers
    @staticmethod
    def code_text(code) -> str:
        """A token's `code` for display: per-theme objects become 'light: A · dark: B'."""
        if isinstance(code, dict):
            return " · ".join(f"{t}: {c}" for t, c in code.items())
        return str(code or "")

    def role_token(self, role):
        return self.roles.get(role)

    def color_in(self, token, theme):
        return self.colors[token]["rgba"].get(theme) if token in self.colors else None

    def scheme_of(self, theme):
        bg = self.color_in(self.roles.get("background"), theme)
        return "dark" if bg and luminance(bg) < 0.4 else "light"

    def type_font(self, k):
        v = self.type[k]
        f = self.fonts.get(v.get("font"), {})
        return f

    def body_type(self):
        """The type token used for running text on stages and screens."""
        for k in self.type:
            if k.lower() in ("body", "bodymedium", "body-md", "bodym", "text", "default", "base", "regular"):
                return k
        if not self.type:
            return None
        return min(self.type, key=lambda k: abs(self.type[k]["size"] - 16))

    def font_stack(self, f):
        fam = f.get("family", "system-ui")
        if f.get("load") == "system" or "," in fam:
            return fam
        generic = "Georgia, serif" if re.search(r"serif", fam, re.I) and not re.search(r"sans", fam, re.I) else "system-ui, -apple-system, 'Segoe UI', sans-serif"
        return f"'{fam}', {generic}"

    def line_height(self, v):
        """The line height in px as the code sets it, or None when the code leaves it to the platform."""
        if "lineHeight" in v:
            return v["lineHeight"]
        if "lineHeightRatio" in v:
            return round(v["size"] * v["lineHeightRatio"], 2)
        return None

    def shadow_rgba(self, v):
        c = v.get("color", "#000000")
        rgba = self.color_in(c, self.default) if c in self.colors else parse_color(c)
        a = v.get("opacity", rgba[3])
        return f"rgba({rgba[0]}, {rgba[1]}, {rgba[2]}, {num(a)})"

    def count(self):
        return (len(self.colors) + len(self.type) + len(self.spacing) + len(self.radii) + len(self.shadows)
                + len(self.durations) + len(self.easings) + len(self.springs))

    # ------------------------------------------------------------ data for the page's inspect panel
    def inspect_data(self) -> dict:
        """CSS variable -> token, plus values per theme for naming computed styles."""
        v = {}
        for k in self.colors:
            v[f"--c-{kebab(k)}"] = f"colors.{k}"
        for k in self.fonts:
            v[f"--f-{kebab(k)}"] = f"fonts.{k}"
        for k in self.type:
            v[f"--t-{kebab(k)}"] = f"type.{k}"
            v[f"--ls-{kebab(k)}"] = f"type.{k}.letterSpacing"
        for group, items, pre in (("spacing", self.spacing, "s"), ("radii", self.radii, "r"), ("durations", self.durations, "d")):
            for k in items:
                v[f"--{pre}-{kebab(k)}"] = f"{group}.{k}"
        for k in self.shadows:
            v[f"--sh-{kebab(k)}"] = f"shadows.{k}"
        for k in self.easings:
            v[f"--e-{kebab(k)}"] = f"easings.{k}"
        for r in ROLES:
            v[f"--role-{ROLE_VAR[r]}"] = f"roles.{r}"
        body = self.body_type()
        if body:
            v["--t-default"] = f"type.{body}"
        gut = next((k for k in self.spacing if k.lower() in ("gutter", "screen", "page", "screenpadding", "screen-padding")), None)
        if gut:
            v["--gutter"] = f"spacing.{gut}"
        colors = {t: {k: list(c["rgba"][t]) for k, c in self.colors.items()} for t in self.theme_ids}
        type_ = {}
        for k, t in self.type.items():
            f = self.type_font(k)
            type_[k] = {"size": t["size"], "lh": self.line_height(t), "family": f.get("family", ""), "weight": f.get("weight", 400)}
        return {
            "vars": v, "roles": {r: tok for r, tok in self.roles.items()}, "themes": self.theme_ids, "defaultTheme": self.default,
            "colors": colors, "type": type_,
            "spacing": {k: x["value"] for k, x in self.spacing.items()}, "radii": {k: x["value"] for k, x in self.radii.items()},
        }

    def known_tokens(self) -> set:
        out = {f"colors.{k}" for k in self.colors} | {f"type.{k}" for k in self.type} | {f"fonts.{k}" for k in self.fonts}
        out |= {f"spacing.{k}" for k in self.spacing} | {f"radii.{k}" for k in self.radii} | {f"shadows.{k}" for k in self.shadows}
        out |= {f"durations.{k}" for k in self.durations} | {f"roles.{r}" for r in self.roles}
        return out

    # ------------------------------------------------------------ CSS
    def css(self) -> str:
        root = []
        for k, f in self.fonts.items():
            root.append(f"  --f-{kebab(k)}: {self.font_stack(f)};")
        for k, v in self.type.items():
            f = self.type_font(k)
            style = "italic " if f.get("style") == "italic" else ""
            lh = self.line_height(v)
            root.append(f"  --t-{kebab(k)}: {style}{f.get('weight', 400)} {num(v['size'])}px/{num(lh) + 'px' if lh is not None else 'normal'} {self.font_stack(f)};")
            root.append(f"  --ls-{kebab(k)}: {num(v.get('letterSpacing', 0))}px;")
        for k, v in self.spacing.items():
            root.append(f"  --s-{kebab(k)}: {num(v['value'])}px;")
        for k, v in self.radii.items():
            root.append(f"  --r-{kebab(k)}: {num(v['value'])}px;")
        for k, v in self.shadows.items():
            root.append(f"  --sh-{kebab(k)}: {num(v.get('x', 0))}px {num(v.get('y', 0))}px {num(v.get('blur', 0))}px {num(v.get('spread', 0))}px {self.shadow_rgba(v)};")
        for k, v in self.durations.items():
            root.append(f"  --d-{kebab(k)}: {num(v['value'])}ms;")
        for k, v in self.easings.items():
            root.append(f"  --e-{kebab(k)}: {v['value']};")
        body = self.body_type()
        root.append(f"  --t-default: {'var(--t-' + kebab(body) + ')' if body else '400 16px/1.4 system-ui, sans-serif'};")
        gut = next((k for k in self.spacing if k.lower() in ("gutter", "screen", "page", "screenpadding", "screen-padding")), None)
        root.append(f"  --gutter: {'var(--s-' + kebab(gut) + ')' if gut else '16px'};")
        blocks = [":root {\n" + "\n".join(root) + "\n}"]
        for i, t in enumerate(self.themes):
            sel = f':root, [data-theme="{t["id"]}"]' if i == 0 else f'[data-theme="{t["id"]}"]'
            lines = [f"  color-scheme: {t['scheme']};"]
            for k, c in self.colors.items():
                lines.append(f"  --c-{kebab(k)}: {c['values'][t['id']]};")
            for r in ROLES:
                tok = self.roles.get(r)
                lines.append(f"  --role-{ROLE_VAR[r]}: {'var(--c-' + kebab(tok) + ')' if tok else ROLE_FALLBACK[r]};")
            blocks.append(f"{sel} {{\n" + "\n".join(lines) + "\n}")
        return "\n".join(blocks)

    def font_links(self) -> str:
        google = {}
        out = []
        for f in self.fonts.values():
            if f.get("load") == "google":
                g = google.setdefault(f["family"], set())
                g.add((1 if f.get("style") == "italic" else 0, int(f.get("weight", 400))))
            elif f.get("load") == "url" and f.get("url"):
                out.append(f"@font-face {{ font-family: '{esc(f['family'])}'; src: url('{esc(f['url'])}'); font-weight: {f.get('weight', 400)}; font-style: {f.get('style', 'normal')}; font-display: swap; }}")
        link = ""
        if google:
            fams = "&".join("family=" + fam.replace(" ", "+") + ":ital,wght@" + ";".join(f"{i},{w}" for i, w in sorted(v)) for fam, v in sorted(google.items()))
            link = ('<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
                    f'<link rel="stylesheet" href="https://fonts.googleapis.com/css2?{fams}&display=swap">')
        return link, "\n".join(out)

    # ------------------------------------------------------------ icons
    def icon_css(self) -> str:
        style = self.icons.get("style", "stroke")
        if style == "fill":
            return ".ic { fill: currentColor; stroke: none; }"
        return f".ic {{ fill: none; stroke: currentColor; stroke-width: {num(self.icons.get('strokeWidth', 2))}; stroke-linecap: round; stroke-linejoin: round; }}"

    def sprite(self) -> str:
        base_style = self.icons.get("style", "stroke")
        vb = self.icons.get("viewBox", "0 0 24 24")
        out = []
        for k, v in (self.icons.get("items") or {}).items():
            if not isinstance(v, dict) or not isinstance(v.get("svg"), str):
                # a system icon (SF Symbols, Material Symbols…): a neutral dashed placeholder, never its artwork
                out.append(f'<symbol id="i-{esc(k)}" viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="5" fill="currentColor" '
                           'fill-opacity="0.12" stroke="currentColor" stroke-width="1.5" stroke-dasharray="3 2.4"/>'
                           '<circle cx="12" cy="12" r="2.4" fill="currentColor" stroke="none"/></symbol>')
                continue
            inner = v["svg"]
            st = v.get("style", base_style)
            if st != base_style or "strokeWidth" in v:
                if st == "fill":
                    inner = f'<g fill="currentColor" stroke="none">{inner}</g>'
                else:
                    inner = f'<g fill="none" stroke="currentColor" stroke-width="{num(v.get("strokeWidth", self.icons.get("strokeWidth", 2)))}" stroke-linecap="round" stroke-linejoin="round">{inner}</g>'
            out.append(f'<symbol id="i-{esc(k)}" viewBox="{esc(v.get("viewBox", vb))}">{inner}</symbol>')
        return '<svg class="sprite" aria-hidden="true">' + "".join(out) + "</svg>"

    # ------------------------------------------------------------ design tokens (DTCG 2025.10)
    def dtcg(self, theme=None) -> dict:
        theme = theme or self.default

        def color(rgba, doc=""):
            val = {"colorSpace": "srgb", "components": [round(c / 255, 4) for c in rgba[:3]], "hex": to_hex(rgba)}
            if rgba[3] != 1:
                val["alpha"] = rgba[3]
            o = {"$type": "color", "$value": val}
            if doc:
                o["$description"] = doc
            return o

        def dim(n, unit="px"):
            return {"value": n, "unit": unit}

        def d(meta):
            return {"$description": meta["doc"]} if meta.get("doc") else {}

        out = {"$description": f"{self.name} design tokens ({theme} theme). Generated by design-canvas from design.json; do not edit by hand."}
        out["color"] = {k: color(c["rgba"][theme], c.get("doc", "")) for k, c in self.colors.items() if theme in c["rgba"]}
        if theme != self.default:
            return out
        if self.fonts:
            out["font"] = {k: {"$type": "fontFamily", "$value": [f.get("family", "system-ui")]} for k, f in self.fonts.items()}
        if self.type:
            out["type"] = {}
            for k, v in self.type.items():
                f = self.type_font(k)
                lh = self.line_height(v)
                # DTCG typography needs a lineHeight number. When the code sets none, write the usual
                # default and say so in $extensions, so no tool takes it for a value from the app.
                out["type"][k] = {"$type": "typography", "$value": {
                    "fontFamily": f.get("family", "system-ui"), "fontWeight": f.get("weight", 400), "fontSize": dim(v["size"]),
                    "lineHeight": round(lh / v["size"], 3) if lh is not None else DEFAULT_LINE_RATIO,
                    "letterSpacing": dim(v.get("letterSpacing", 0))}, **d(v)}
                if lh is None:
                    out["type"][k]["$extensions"] = {"dev.design-canvas": {"lineHeight": "platform default"}}
        if self.spacing:
            out["space"] = {k: {"$type": "dimension", "$value": dim(v["value"]), **d(v)} for k, v in self.spacing.items()}
        if self.radii:
            out["radius"] = {k: {"$type": "dimension", "$value": dim(v["value"]), **d(v)} for k, v in self.radii.items()}
        if self.shadows:
            out["shadow"] = {}
            for k, v in self.shadows.items():
                c = v.get("color", "#000000")
                rgba = self.color_in(c, theme) if c in self.colors else parse_color(c)
                rgba = rgba[:3] + (v.get("opacity", rgba[3]),)
                out["shadow"][k] = {"$type": "shadow", "$value": {"color": color(rgba)["$value"], "offsetX": dim(v.get("x", 0)), "offsetY": dim(v.get("y", 0)),
                                                                   "blur": dim(v.get("blur", 0)), "spread": dim(v.get("spread", 0))}, **d(v)}
        if self.durations:
            out["duration"] = {k: {"$type": "duration", "$value": dim(v["value"], "ms"), **d(v)} for k, v in self.durations.items()}
        eas = {}
        for k, v in self.easings.items():
            m = re.fullmatch(r"cubic-bezier\(([^)]*)\)", v["value"].replace(" ", ""))
            if m:
                eas[k] = {"$type": "cubicBezier", "$value": [float(x) for x in m.group(1).split(",")], **d(v)}
        if eas:
            out["easing"] = eas
        if self.springs:
            fields = ("damping", "stiffness", "mass", "response", "dampingFraction", "duration", "bounce")
            out["$extensions"] = {"dev.design-canvas": {"springs": {k: {x: v[x] for x in fields if x in v} for k, v in self.springs.items()}}}
        return out

    # ------------------------------------------------------------ contrast
    def partner(self, token):
        """The colour a token is read on: its pair for 'onX' tokens, else the background."""
        if token == self.roles.get("onAccent") and self.roles.get("accent"):
            return self.roles["accent"]
        m = re.match(r"^on[-_]?([A-Za-z0-9].*)$", token)
        if m:
            base = m.group(1)
            for cand in (base, base[:1].lower() + base[1:], kebab(base)):
                if cand in self.colors:
                    return cand
        return self.roles.get("background")

    def fills(self, token, theme):
        """The colour tokens `token` is read on in `theme`: its `on` list, else its partner."""
        on = self.colors[token].get("_on")
        names = on[theme] if on else [self.partner(token)]
        return [n for n in names if n and n != token]

    def pairs(self, token):
        """[(fill, {theme: ratio})]: the contrast of `token` on each colour it is read on."""
        out: dict[str, dict] = {}
        for t in self.theme_ids:
            fg = self.color_in(token, t)
            for f in self.fills(token, t):
                bg = self.color_in(f, t)
                if fg and bg:
                    out.setdefault(f, {})[t] = contrast(fg, bg)
        return list(out.items())

    def ratios(self, token):
        """{theme: ratio} on the first colour this token is read on."""
        p = self.pairs(token)
        return p[0][1] if p else {}

    def is_texty(self, token):
        """Is this colour used for text? From `text` in design.json, then `on`, then the roles, then
        the name or group (only clearly textual words count)."""
        meta = self.colors[token]
        if isinstance(meta.get("text"), bool):
            return meta["text"]
        if meta.get("on") is not None:
            return True
        roles = {r: self.roles.get(r) for r in TEXT_ROLES + FILL_ROLES}
        if token in (roles[r] for r in TEXT_ROLES):
            return True
        if token in (roles[r] for r in FILL_ROLES):
            return False
        words = kebab(token).split("-")
        if len(words) > 1 and words[0] == "on":  # onPrimary, on-surface, on_accent
            return True
        for w in (words, kebab(meta.get("group") or "").split("-")):
            if TEXT_WORDS & set(w) and not FILL_WORDS & set(w):
                return True
        return False

    def text_colors(self):
        return [k for k in self.colors if self.is_texty(k)]

    def contrast_problems(self):
        out = []
        for k in self.text_colors():
            for on, rs in self.pairs(k):
                for t, r in rs.items():
                    if r < 4.5:
                        out.append(f"`{k}` on `{on}` is {r}:1 in the {t} theme (text needs 4.5:1)")
        return out

    # ------------------------------------------------------------ drift check
    def check(self, root: Path | None = None):
        """Compare every token with the code its `src` points at.

        Returns a DriftResult. It unpacks like the old tuple (drifted, ok_count, derived, unsourced):
        `unsourced` lists tokens that have neither a `src` nor a `derived` note. It also carries
        `not_checked` (fields the code does not state, such as "type.title weight"), `could_check`
        (derived tokens whose note names a file:line), `total` and `derived_share`.

        Where a value is looked for: each comma part of `src` is one `path:line` (or a whole file).
        If the src line defines the token's name, only that definition counts. If not, the src line
        itself is tried first, then the nearest definition of the name within 8 lines (code moves).
        Other numbers or colours nearby never count.
        """
        root = Path(root or self.root)
        problems, ok, skipped, unsourced, not_checked, could = [], 0, [], [], [], []
        total = 0
        cache: dict = {}

        def read(path):
            if path not in cache:
                try:
                    cache[path] = (root / path).read_text(encoding="utf-8", errors="replace").splitlines()
                except OSError:
                    cache[path] = None
            return cache[path]

        siblings_cache, spans_cache, defs_cache = {}, {}, {}

        def defs_in(path, lines, name):
            """[(line index, match)] for every definition of `name` in a file."""
            if (path, name) not in defs_cache:
                rx = _defn(name)
                defs_cache[(path, name)] = [(i, m) for i, text in enumerate(lines) for m in [rx.search(_code_part(text))] if m]
            return defs_cache[(path, name)]

        def siblings(path):
            """Files next to `path` with the same extension (where a palette usually lives)."""
            if path not in siblings_cache:
                here = root / path
                try:
                    files = sorted(f for f in here.parent.iterdir()
                                   if f.is_file() and f.suffix == here.suffix and f.name != here.name and f.stat().st_size < 400_000)
                    siblings_cache[path] = [f.relative_to(root).as_posix() for f in files[:60]]
                except (OSError, ValueError):
                    siblings_cache[path] = []
            return siblings_cache[path]

        def spans(path, lines, name):
            """(first, last) line of every definition of a container `name` in a file."""
            if (path, name) not in spans_cache:
                rx, out = _parent_rx(name), []
                for i, text in enumerate(lines):
                    m = rx.search(_code_part(text))
                    if m:
                        out.append((i, _extend(lines, i, m, max_lines=5000).last))
                spans_cache[(path, name)] = out
            return spans_cache[(path, name)]

        def resolve(segs, path, paths, skip):
            """-> (path, Look) for the one definition a reference points at: in the same file, then the token's
            other src files, then files next to it. None when there is none, or more than one."""
            last, parent = segs[-1], (segs[-2] if len(segs) > 1 else None)
            seen = set()
            for tier in ([path], paths, siblings(path)):
                found = []
                for p in tier:
                    if p in seen or not safe_rel(root, p):
                        continue
                    seen.add(p)
                    lines = read(p)
                    if not lines:
                        continue
                    hits = [(i, m) for i, m in defs_in(p, lines, last) if (p, i) not in skip]
                    if hits and parent:
                        sp = spans(p, lines, parent)
                        inside = [(i, m) for i, m in hits if any(a <= i <= b for a, b in sp)]
                        hits = inside or ([] if sp else hits)
                    found += [(p, lines, i, m) for i, m in hits]
                if len(found) == 1:
                    p, lines, i, m = found[0]
                    return p, _extend(lines, i, m)
                if found:
                    return None
            return None

        def follow(look, path, paths, skip=frozenset(), depth=0):
            """`look` plus the definitions its references point at, so an alias (`primary: palette.blue300`)
            is checked against the colour it really resolves to."""
            if look.how == "file" or depth > 3:
                return look
            skip = skip | {(path, k) for k in range(look.first, look.last + 1)}
            extra, refs, missing = [], [], []
            for shown, segs in _refs_in(look.value if look.how == "defined" else look.text):
                hit = resolve(segs, path, paths, skip)
                if hit:
                    refs.append(shown)
                    extra.append(follow(hit[1], hit[0], paths, skip, depth + 1))
                elif segs[0] not in _PLATFORM_ROOTS:
                    missing.append(shown)
            if not extra and not missing:
                return look
            joined = _Look.join([look] + extra)
            joined.how, joined.refs, joined.missing = look.how, refs + joined.refs, missing + joined.missing
            return joined

        def ref_names(refs):
            return {segs[-1] for r in refs for _, segs in _refs_in(r)[:1]}

        def token_refs(key, paths, listed=()):
            """[(reference, "file:line")] written in the token's own definitions (`primary: palette.blue300`), in its src
            files and the files next to them."""
            out = []
            for p in dict.fromkeys(paths + [x for q in paths for x in siblings(q)]):
                lines = read(p) if safe_rel(root, p) else None
                for i, m in defs_in(p, lines, str(key)) if lines else []:
                    if (p, i) not in listed:
                        out += [(shown, f"{p}:{i + 1}") for shown, _ in _refs_in(_extend(lines, i, m).value)]
            return out

        def repointed(key, code, paths):
            """`code` names a palette entry (`palette.blue300`), but the token's own definition (`primary: …`, in a
            src file or a file next to one) now refers to another entry of that palette. -> a message, or None."""
            chains = [segs for c in (code if isinstance(code, list) else [code]) if isinstance(c, str)
                      for _, segs in _refs_in(c) if len(segs) > 1 and segs[-1].lower() != str(key).lower()]
            if not chains:
                return None
            files = list(dict.fromkeys(paths + [x for p in paths for x in siblings(p)]))
            for segs in chains:
                parent, last, seen, where = segs[-2], segs[-1], [], None
                for p in files:
                    lines = read(p) if safe_rel(root, p) else None
                    for i, m in defs_in(p, lines, str(key)) if lines else []:
                        for shown, rs in _refs_in(_extend(lines, i, m).value):
                            if len(rs) > 1 and rs[-2] == parent:
                                if rs[-1] == last:
                                    break
                                seen.append(shown)
                                where = where or f"{p}:{i + 1}"
                        else:
                            continue
                        seen = None  # found the reference `code` names: not re-pointed
                        break
                    if seen is None:
                        break
                if seen:
                    return (f"`{key}` now refers to {', '.join(dict.fromkeys(seen))} ({where}), not `{'.'.join(segs)}`. "
                            f"Re-pointed? Update the value, `code` and `src`.")
            return None

        def lookups(src, names, key=None, code=None, own_names=()):
            """-> ([Look, ...], error): the texts to test, best first. Each joins one piece per src part."""
            options, pending = [], []
            parts = [s.strip() for s in src.split(",") if s.strip()]
            paths = [re.match(r"(.+?)(?::(\d+))?$", x).group(1).strip() for x in parts]
            listed = {(mm.group(1).strip(), int(mm.group(2)) - 1) for mm in (re.match(r"(.+?):(\d+)$", x) for x in parts) if mm}
            for part in parts:
                m = re.match(r"(.+?)(?::(\d+))?$", part)
                path, line = m.group(1).strip(), m.group(2)
                if not safe_rel(root, path):
                    return None, f"src must be a relative path inside the app root: {path}"
                lines = read(path)
                if lines is None:
                    return None, f"source file not found: {path}"
                if not line:
                    whole = "\n".join(lines)
                    found = _definitions(lines, range(len(lines)), names)
                    options.append([follow(found, path, paths) if found else _Look(whole, whole, "file")])
                    continue
                i = int(line) - 1
                if not 0 <= i < len(lines):
                    return None, f"line {line} is past the end of {path} ({len(lines)} lines)"
                own = _definitions(lines, [i], names)
                if own:
                    options.append([follow(own, path, paths)])
                    continue
                near = _definitions(lines, [k for k in range(max(0, i - 8), min(len(lines), i + 9)) if (path, k) not in listed],
                                    names, nearest=i)  # a definition src lists is checked on its own line
                other = _defines_other(lines[i], list(names) + list(own_names), self.theme_ids)
                if other and not near:
                    pending.append((other, f"{path}:{line}"))
                elif other:  # src is a palette entry and the token's own definition is close by
                    via = follow(near, path, paths).refs
                    if via and other not in ref_names(via):
                        return None, (f"`{names[0]}` now refers to {', '.join(dict.fromkeys(via))}, but its src line "
                                      f"({path}:{line}) defines `{other}`. Re-pointed? Update the value, `code` and `src`.")
                options.append([follow(_src_line(lines, i), path, paths)] + ([follow(near, path, paths)] if near else []))
            refs = [r for o in options for x in o for r in x.refs + x.missing]
            for other, where in pending:
                if other in ref_names(refs):
                    continue  # the palette entry the token's own definition points at
                if not refs and key is not None:
                    found = token_refs(key, paths, listed)
                    if other in ref_names([r for r, _ in found]):
                        continue
                    if found:
                        return None, (f"`{key}` now refers to {', '.join(dict.fromkeys(r for r, _ in found))} ({found[0][1]}), "
                                      f"but its src line ({where}) defines `{other}`. Re-pointed? Update the value, `code` and `src`.")
                if refs:
                    return None, (f"`{names[0]}` now refers to {', '.join(dict.fromkeys(refs))}, but its src line ({where}) "
                                  f"defines `{other}`. Re-pointed? Update the value, `code` and `src`.")
                return None, (f"its src line now defines `{other}`, not `{names[0]}` ({where}). "
                              f"Renamed? Update the token's `code` and name. Moved? Update `src`.")
            if key is not None:
                moved = repointed(key, code, paths)
                if moved:
                    return None, moved
            looks = [_Look.join([o[0] for o in options])]
            if any(len(o) > 1 for o in options):
                looks.append(_Look.join([o[-1] for o in options]))
            return looks, None

        def run(label, key, meta, tests):
            """tests: [(field, shown value, fn(look), theme)]. fn returns True (matches), None (the code
            does not state it), or False / a hint string (drift)."""
            nonlocal ok, total
            total += 1
            if meta.get("derived"):
                skipped.append(f"{label}: {meta['derived']}")
                m = _SRC_IN_NOTE.search(str(meta["derived"]))
                if m:
                    could.append(f"{label} (its note names {m.group(0)})")
                return
            if not meta.get("src"):
                unsourced.append(label)
                return
            per_theme = isinstance(meta.get("src"), dict) or isinstance(meta.get("code"), dict)
            codes = meta.get("code")
            codes = list(codes.values()) if isinstance(codes, dict) else [codes]
            all_names = [n for c in codes for n in _names_for(key, c)]  # every theme's name for this token
            failed, unknown = [], []
            for theme in dict.fromkeys(t[3] for t in tests) or [None]:
                src = self._pick(meta.get("src"), theme)
                code = self._pick(meta.get("code"), theme, join=False)
                looks, err = lookups(src, _names_for(key, code), key, code, all_names)
                if err:
                    problems.append(f"`{label}`: {err}")
                    return
                group = [t for t in tests if t[3] == theme]
                tried = []
                for look in looks:
                    res = [(f, shown, fn(look)) for f, shown, fn, _ in group]
                    bad = [(f, shown, r) for f, shown, r in res if r is False or isinstance(r, str)]
                    tried.append((look, bad, [f for f, _, r in res if r is None], sum(r is True for _, _, r in res)))
                # A look that matches wins (fewest unstated fields first). Else the last one that says anything
                # (a definition of the name before the bare src line), so a src line that states nothing never hides drift.
                good = [x for x in tried if not x[1] and x[3]]
                said = [x for x in tried if x[1] or x[3]]
                look, bad, none, _ = min(good, key=lambda x: len(x[2])) if good else (said or tried)[-1]
                tag = f" ({theme})" if theme and per_theme else ""
                if bad:
                    where = {"defined": "where it is defined", "line": "on its src line", "file": "in the file"}[look.how]
                    what = ", ".join(f"{f} {shown}" + (f" ({r})" if isinstance(r, str) else "") for f, shown, r in bad)
                    via = f", via {', '.join(dict.fromkeys(look.refs))}" if look.refs else ""
                    lost = (f"; it refers to {', '.join(dict.fromkeys(look.missing))}, whose definition was not found "
                            f"(add that file to src)") if look.missing else ""
                    failed.append(f"{what} not found {where}{tag} ({src}{via}){lost}")
                unknown += [f"{label} {f}{tag}" for f in none]
            if failed:
                problems.append(f"`{label}`: " + "; ".join(failed))
            else:
                ok += 1
            not_checked.extend(u for u in dict.fromkeys(unknown) if u not in not_checked)

        def number_test(names, wants):
            def fn(look):
                direct = _direct_values(look.text, names)
                if direct:
                    return any(_close(v, w) for v in direct for w in wants)
                return any(_has_number(look.text, w) for w in wants)
            return fn

        for k, c in self.colors.items():
            per_theme = isinstance(c.get("src"), dict) or isinstance(c.get("code"), dict)
            pairs = [(t, c["rgba"][t]) for t in self.theme_ids if t in c["rgba"]] if per_theme else \
                [(None, v) for v in {to_hex(v) + f"@{v[3]}": v for v in c["rgba"].values()}.values()]
            tests = []
            for theme, v in pairs:
                tests.append(("colour", to_hex(v), lambda L, v=v: _has_color(L.text, v), theme))
                tests.append(("alpha", num(v[3]), lambda L, a=v[3]: _alpha_test(L.text, a), theme))
            run(f"colors.{k}", k, c, tests)
        for k, v in self.type.items():
            names = _names_for(k, self._pick(v.get("code"), None, join=False))
            tests = [("size", num(v["size"]), lambda L, n=v["size"], nm=names: _type_number(L, "size", n, nm, strict=True), None)]
            for field, shown in (("lineHeight", "line height"), ("lineHeightRatio", "line height ratio"), ("letterSpacing", "letter spacing")):
                if isinstance(v.get(field), (int, float)):
                    tests.append((shown, num(v[field]), lambda L, n=v[field], f=field: _type_number(L, f, n, [], strict=False), None))
            weight = (self.fonts.get(v.get("font")) or {}).get("weight")
            if isinstance(weight, (int, float)):
                tests.append(("weight", num(weight), lambda L, w=weight: _weight_test(L, w), None))
            run(f"type.{k}", k, v, tests)
        for group, items in (("spacing", self.spacing), ("radii", self.radii), ("durations", self.durations)):
            for k, v in items.items():
                names = _names_for(k, self._pick(v.get("code"), None, join=False))
                wants = [v["value"]] + ([v["value"] / 1000] if group == "durations" else [])  # seconds in SwiftUI/Android code
                run(f"{group}.{k}", k, v, [("value", num(v["value"]), number_test(names, wants), None)])
        raw_shadows = self.raw.get("shadows") if isinstance(self.raw.get("shadows"), dict) else {}
        for k, v in self.shadows.items():
            written = raw_shadows.get(k) if isinstance(raw_shadows.get(k), dict) else {}
            fields = ["x", "y"] + (["blur"] if "blur" in written or "radius" not in written else []) + ["spread"]
            fields += [f for f in ("radius", "elevation") if f in written]
            tests = [(f, num(v.get(f, 0)), lambda L, f=f, n=v.get(f, 0), r="radius" in written: _shadow_number(L.text, f, n, r), None)
                     for f in fields if isinstance(v.get(f, 0), (int, float))]
            c = v.get("color", "#000000")
            rgba = self.color_in(c, self.default) if c in self.colors else _parse_or_none(c)
            if rgba:
                cnames = _names_for(c, self._pick(self.colors[c].get("code"), None, join=False)) if c in self.colors else []
                alpha = v.get("opacity", rgba[3])
                tests.append(("colour", c if c in self.colors else to_hex(rgba), lambda L, x=rgba, nm=cnames: _shadow_color(L.text, x, nm), None))
                tests.append(("opacity", num(alpha), lambda L, a=alpha: _alpha_test(L.text, a), None))
            run(f"shadows.{k}", k, v, tests)
        raw_springs = (self.raw.get("motion") or {}).get("springs") if isinstance(self.raw.get("motion"), dict) else {}
        raw_springs = raw_springs if isinstance(raw_springs, dict) else {}
        for k, v in self.springs.items():
            written = raw_springs.get(k) if isinstance(raw_springs.get(k), dict) else {}
            run(f"springs.{k}", k, v, [(f, num(written[f]), lambda L, f=f, n=written[f]: _spring_number(L.text, f, n), None)
                                        for f in _SPRING_LABELS if isinstance(written.get(f), (int, float))])
        for k, v in self.easings.items():
            nums = re.findall(r"-?\d*\.?\d+", v.get("value", ""))
            run(f"easings.{k}", k, v, [("value", v.get("value"), lambda L, ns=nums: all(_has_number(L.text, float(n)) for n in ns), None)])
        for k, f in self.fonts.items():
            fam = f.get("family", "")
            tests = [("family", fam, lambda L, s=fam: re.search(re.escape(s).replace(r"\ ", r"[\s_-]?"), L.text, re.I) is not None, None)]
            if isinstance(f.get("weight"), (int, float)):
                tests.append(("weight", num(f["weight"]), lambda L, w=f["weight"]: _weight_test(L, w), None))
            run(f"fonts.{k}", k, f, tests)
        return DriftResult(problems, ok, skipped, unsourced, not_checked, could, total)

    def _pick(self, value, theme, join=True):
        """One theme's `src` or `code` from a per-theme object. theme None: every theme's, joined with ', '
        for src (join=True) or as a list for code names."""
        if not isinstance(value, dict):
            return value
        if theme is None:
            vals = list(dict.fromkeys(value.values()))
            return ", ".join(vals) if join else vals
        if theme in value:
            return value[theme]
        return value.get(self.default) or next(iter(value.values()), None)

    # ------------------------------------------------------------ "Used in" lists
    def usage(self, root: Path | None = None) -> dict[str, list[str]]:
        mods = self.components.get("importFrom") or []
        if not mods:
            return {}
        root = Path(root or self.root)
        scan = self.components.get("scan") or ["src"]
        ignore = self.components.get("ignore") or []
        imp = re.compile(r"import\s+(?:type\s+)?(?:(\w+)\s*,?\s*)?(?:\{([^}]*)\})?\s*from\s*['\"]([^'\"]+)['\"]", re.S)
        out: dict[str, set] = {}
        for base in scan:
            d = root / base
            if not d.is_dir():
                continue
            for f in sorted(d.rglob("*")):
                if f.suffix not in (".ts", ".tsx", ".js", ".jsx", ".mjs") or "node_modules" in f.parts:
                    continue
                rel = f.relative_to(root).as_posix()
                if any(rel.startswith(i) for i in ignore) or re.search(r"\.(test|spec|stories)\.", rel):
                    continue
                text = f.read_text(encoding="utf-8", errors="ignore")
                for default, names, mod in imp.findall(text):
                    if mod.startswith("."):
                        target = (f.parent / mod).resolve()
                        try:
                            mod_rel = target.relative_to(root).as_posix()
                        except ValueError:
                            continue
                        hit = any(mod_rel == m or mod_rel.startswith(m.rstrip("/") + "/") for m in mods if not m.startswith("@"))
                    else:
                        hit = any(mod == m or mod.startswith(m.rstrip("/") + "/") for m in mods)
                    if not hit:
                        continue
                    for n in ([default] if default else []) + (names.split(",") if names else []):
                        n = re.sub(r"^\s*type\s+", "", n).split(" as ")[0].strip()
                        if n and n[0].isupper():
                            out.setdefault(n, set()).add(rel)
        return {k: sorted(v) for k, v in out.items()}

    # ------------------------------------------------------------ Markdown
    def markdown(self, drift_items=None) -> str:
        t_ids = self.theme_ids
        out = [f"# {self.name} tokens", "", "Generated by design-canvas from `design.json`. Do not edit; change the code, update design.json, rebuild.", ""]
        out += ["## Colour", "", "| Token | " + " | ".join(t_ids) + " | Use |", "| --- | " + " | ".join("---" for _ in t_ids) + " | --- |"]
        for k, c in self.colors.items():
            out.append(f"| `{k}` | " + " | ".join(f"`{c['values'][t]}`" for t in t_ids) + f" | {c.get('doc', '')} |")
        if self.type:
            out += ["", "## Type", "", "| Style | Size / line | Face | Use |", "| --- | --- | --- | --- |"]
            for k, v in self.type.items():
                f = self.type_font(k)
                lh = self.line_height(v)
                out.append(f"| `{k}` | {num(v['size'])} / {num(lh) if lh is not None else 'platform default'} | {f.get('family')} {f.get('weight', 400)}{' italic' if f.get('style') == 'italic' else ''} | {v.get('doc', '')} |")
        for title, items, unit in (("Spacing", self.spacing, "px"), ("Radius", self.radii, "px"), ("Duration", self.durations, "ms")):
            if items:
                out += ["", f"## {title}", "", "| Token | Value | Use |", "| --- | --- | --- |"]
                out += [f"| `{k}` | {num(v['value'])} {unit} | {v.get('doc', '')} |" for k, v in items.items()]
        if self.shadows:
            out += ["", "## Shadow", "", "| Token | x / y / blur / spread | Colour | Use |", "| --- | --- | --- | --- |"]
            for k, v in self.shadows.items():
                out.append(f"| `{k}` | {num(v.get('x', 0))} / {num(v.get('y', 0))} / {num(v.get('blur', 0))} / {num(v.get('spread', 0))} | {self.shadow_rgba(v)} | {v.get('doc', '')} |")
        if drift_items is not None:
            out += ["", "## Drift check", ""] + ([f"- {d}" for d in drift_items] or ["Every token with a `src` still matches the code."])
        return "\n".join(out) + "\n"


# ---------------------------------------------------------------- drift check helpers
class DriftResult(tuple):
    """What Design.check() returns. Unpacks like a tuple (drifted, ok_count, derived, unsourced) and adds
    not_checked (fields the code does not state), could_check (derived tokens whose note names a file:line),
    total (tokens looked at) and derived_share (0-1)."""

    def __new__(cls, problems, ok, derived, unsourced, not_checked=(), could_check=(), total=0):
        self = tuple.__new__(cls, (problems, ok, derived, unsourced))
        self.not_checked = list(not_checked)
        self.could_check = list(could_check)
        self.total = total
        self.derived_share = round(len(derived) / total, 4) if total else 0.0
        return self


class _Look:
    """Text a token's values are looked for in. how: 'defined' (a definition of its name), 'line' (the src
    line itself) or 'file' (a whole file). value is the text after the defining key."""

    def __init__(self, text, value, how, first=0, last=0, refs=(), missing=()):
        self.text, self.value, self.how, self.first, self.last = text, value, how, first, last
        self.refs, self.missing = list(refs), list(missing)  # references followed / not found

    @staticmethod
    def join(looks):
        how = "defined" if any(x.how == "defined" for x in looks) else looks[0].how
        return _Look("\n".join(x.text for x in looks), "\n".join(x.value for x in looks), how, looks[0].first, looks[0].last,
                     [r for x in looks for r in x.refs], [r for x in looks for r in x.missing])


_NUM = r"-?(?:\d+(?:\.\d*)?|\.\d+)"
_SRC_IN_NOTE = re.compile(r"[\w./-]+\.[A-Za-z]\w*:\d+")


def _close(a, b) -> bool:
    return abs(a - b) <= 1e-6 * max(1.0, abs(b))


def _has_number(text, n) -> bool:
    s = num(n)
    if "." in s:
        body = re.escape(s).replace(r"0\.", r"0?\.", 1) + "0*"  # .25 as well as 0.25, and 0.250
    else:
        body = re.escape(s) + r"(?:\.0+)?"
    return re.search(rf"(?<![\w.]){body}(?!\d|\.\d)", text) is not None


def _key_rx(name):
    """A definition of `name`: `name: …`, `name = …`, `name(…`, `"name": …`, `name -> …`, and Swift/Kotlin
    `.name: …` or `case .headline, .body: …`. A call such as `.sheet(` is not a definition."""
    n = re.escape(name)
    return (rf"(?:(?<![\w$.-])['\"]?{n}['\"]?\s*(?:[:(]|=(?!=)|->)"
            rf"|(?<=\.){n}(?:\s*,\s*\.[A-Za-z_]\w*)*\s*(?::|=(?!=)|->))")


@lru_cache(maxsize=None)
def _defn(name):
    # also Android/XML resources: <color name="primary">…
    return re.compile(rf"{_key_rx(name)}|\bname\s*=\s*['\"]{re.escape(name)}['\"]", re.I)


def _names_for(key, code):
    """Names the token may be defined under, most specific first. `code` is a string or a list of them."""
    codes = [c.strip() for c in (code if isinstance(code, list) else [code]) if isinstance(c, str) and c.strip()]
    out = []
    for c in codes:
        bare = c.replace("var(", "").split(")")[0].strip()
        if bare.startswith("--"):
            out.append(bare)  # a CSS custom property
        else:
            segs = [x for x in re.split(r"[.\[\]'\"\s/()]+", c) if x]  # getColor('on-primary') -> on-primary
            if segs:
                out.append(segs[-1])
    out.append(key)
    for c in codes:
        words = [x for x in re.split(r"[.\[\]'\"\s/()-]+", c) if x]
        if words:
            out.append(words[-1])  # looser: only the last word
    return [n for i, n in enumerate(out) if n and n not in out[:i]]


@lru_cache(maxsize=65536)
def _code_part(line):
    """The line without a trailing // comment (quotes respected)."""
    quote, k = None, 0
    while k < len(line):
        ch = line[k]
        if quote:
            if ch == "\\":
                k += 1
            elif ch == quote:
                quote = None
        elif ch in "'\"`":
            quote = ch
        elif line.startswith("//", k):
            return line[:k]
        k += 1
    return line


def _scan(line, col, depth, stop_at_comma):
    """Read line[col:] until a ',' or ';' at depth 0 (when stop_at_comma), a bracket closing past depth 0,
    a // comment or the line end. Returns (text, depth, stopped)."""
    quote, k = None, col
    while k < len(line):
        ch = line[k]
        if quote:
            if ch == "\\":
                k += 1
            elif ch == quote:
                quote = None
        elif ch in "'\"`":
            quote = ch
        elif line.startswith("//", k):
            return line[col:k], depth, False
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth < 0:
                return line[col:k], depth, True
        elif ch in ",;" and depth == 0 and stop_at_comma:
            return line[col:k], depth, True
        k += 1
    return line[col:], depth, False


def _extend(lines, i, m, how="defined", max_lines=16):
    """The definition matched by m on lines[i]: its key, then its value up to the next key (a ',' or ';' at
    depth 0), the bracket that closes it, or a line end with nothing left open."""
    key = lines[i][m.start():m.end()]
    depth = 1 if key.rstrip().endswith("(") else 0
    pieces, j, col = [], i, m.end()
    while True:
        text, depth, stopped = _scan(lines[j], col, depth, how == "defined")
        pieces.append(text)
        if stopped or depth <= 0 or j + 1 >= len(lines) or j - i >= max_lines:
            break
        j, col = j + 1, 0
    value = "\n".join(pieces)
    return _Look(key + value, value, how, i, j)


def _src_line(lines, i):
    """The src line itself (without comments), plus the rest of a bracket it opens."""
    start = len(lines[i]) - len(lines[i].lstrip())
    return _extend(lines, i, re.compile("").match(lines[i], start), how="line")


def _definitions(lines, idxs, names, nearest=None):
    """The definition of the most specific of `names` among lines[idxs], as a Look. With `nearest` (a line
    index), only the definition closest to it; without, every definition, joined."""
    idxs = list(idxs)
    for n in names:
        rx = _defn(n)
        found = []
        for i in idxs:
            m = rx.search(_code_part(lines[i]))
            if m:
                found.append(_extend(lines, i, m))
        if not found:
            continue
        if nearest is None:
            return _Look.join(found)

        def dist(f):
            return 0 if f.first <= nearest <= f.last else min(abs(f.first - nearest), abs(f.last - nearest))
        return min(found, key=lambda f: (dist(f), f.first))
    return None


# -- references (aliases) and renames
# `palette.blue300`, `Palette.slate`, `colors.blue[300]`, `theme?.surface`; never a call such as `Animation.spring(`.
_REF_CHAIN = re.compile(r"(?<![\w$.#@'\"-])([A-Za-z_$][\w$]*)((?:\s*\??\.\s*[A-Za-z_$][\w$]*|\[\s*['\"]?[\w-]+['\"]?\s*\])+)(?![\w$(]|\s*\()")
_REF_VAR = re.compile(r"var\(\s*(--[\w-]+)")  # CSS var(--blue-300)
_REF_RES = re.compile(r"@(?:color|dimen)/([\w.]+)")  # Android @color/blue_300
_STRING = re.compile(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|`(?:\\.|[^`\\])*`")
# Roots that name the platform, not the app: a missing definition there is not worth a hint.
_PLATFORM_ROOTS = {"Color", "UIColor", "NSColor", "Colors", "SwiftUI", "Animation", "Font", "Math", "Number", "String",
                   "CGFloat", "Double", "Float", "Int", "Platform", "StyleSheet", "Dimensions", "this", "self", "Self"}


def _refs_in(value):
    """References written in a definition's value, as (shown, [segments]), in order."""
    code = "\n".join(_code_part(line) for line in value.split("\n"))
    out = [(f"var({m.group(1)})", [m.group(1)]) for m in _REF_VAR.finditer(code)]
    out += [(m.group(0), [m.group(1)]) for m in _REF_RES.finditer(code)]
    for m in _REF_CHAIN.finditer(_STRING.sub('""', code)):
        segs = [x for x in re.split(r"[\s?.\[\]'\"]+", m.group(0)) if x]
        out.append((re.sub(r"\s+", "", m.group(0)), segs))
    return [r for i, r in enumerate(out) if r[0] not in [x[0] for x in out[:i]]]


@lru_cache(maxsize=None)
def _parent_rx(name):
    """A definition of a container: `palette = {`, `palette: {`, `enum Palette {`, `object Palette {`."""
    n = re.escape(name)
    return re.compile(rf"{_key_rx(name)}|\b(?:enum|struct|class|object|extension|namespace|interface)\s+{n}\b")


# The start of a line that defines a name: `brand: …`, `static let brand = …`, `val Brand: Color = …`,
# `--c-brand: …`, `"brand": …`, `$brand: …`, `case .brand:`. Group 1 is the name.
_DEF_START = re.compile(
    r"^\s*(?:(?:export|public|private|internal|fileprivate|open|final|static|override|readonly|const|let|var|val|"
    r"lateinit|late|@\w+(?:\([^)]*\))?)\s+)*(?:case\s+\.?)?(?:[A-Z][\w<>?]*\s+(?=[A-Za-z_$][\w$-]*\s*[:=]))?"
    r"['\"]?(--[\w-]+|\$?[A-Za-z_][\w$-]*)['\"]?\s*(?::(?!:)|=(?!=)|->)")
_XML_NAME = re.compile(r"<\s*\w+[^>]*\bname\s*=\s*['\"]([\w.-]+)['\"]")
# Keys that hold a part of a value rather than name a token.
_FIELD_KEYS = {
    "default", "light", "dark", "any", "value", "values", "base", "main", "color", "colour", "colors", "red", "green",
    "blue", "alpha", "components", "hex", "rgb", "rgba", "srgb", "x", "y", "width", "height", "opacity", "radius",
    "size", "weight", "family", "fontfamily", "fontsize", "fontweight", "lineheight", "letterspacing", "duration",
    "damping", "stiffness", "mass", "response", "dampingfraction", "bounce", "offset", "blur", "spread", "elevation",
    "shadowcolor", "shadowoffset", "shadowopacity", "shadowradius", "dx", "dy", "type", "style", "name", "src", "doc",
}


def _words(name):
    """`--c-onPrimary` -> ['c', 'on', 'primary']."""
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name.lstrip("-$"))
    return [w.lower() for w in re.split(r"[\s_.\-]+", name) if w]


def _within(small, big):
    return bool(small) and any(big[k:k + len(small)] == small for k in range(len(big) - len(small) + 1))


def _defines_other(line, names, skip=()):
    """The name `line` defines when it is a different token from every one of `names`, else None.
    `onPrimary` vs `primary` or `--c-primary` vs `primary` count as the same token; parts of a value
    (`DEFAULT`, `red`, `500`, a theme id) never count."""
    code = _code_part(line)
    m = _DEF_START.match(code) or _XML_NAME.search(code)
    if not m:
        return None
    other = m.group(1)
    w = _words(other)
    if (not w or len(other.lstrip("-$")) < 2 or other.lower() in _FIELD_KEYS or "".join(w) in _FIELD_KEYS
            or other.lower() in {s.lower() for s in skip}):
        return None
    for n in names:
        nw = _words(n)
        if _within(nw, w) or _within(w, nw):
            return None
    return other


def _direct_values(text, names):
    """Numbers written right after a definition of one of `names` (`md: 12`, `case .body: return 17`)."""
    out = []
    for n in names:
        for m in re.finditer(_key_rx(n) + rf"\s*(?:return\s+)?['\"]?\s*({_NUM})(?![xX\d])", text, re.I):
            out.append(float(m.group(1)))
    return out


def _label_rx(labels):
    return rf"(?<![\w$-])['\"]?(?:{'|'.join(labels)})['\"]?\s*(?:[:=(]|->)"


def _has_label(text, labels) -> bool:
    return re.search(_label_rx(labels), text, re.I) is not None


def _labelled(text, labels):
    """Numbers written right after one of `labels` (regex pieces): `x: 0`, `radius = 8`, `.opacity(0.2)`,
    `"blur": "8px"`, `shadowRadius: CGFloat(8)`, XML `name="android:textSize">17sp`."""
    alt = "|".join(labels)
    vals = [float(m.group(1)) for m in re.finditer(
        _label_rx(labels) + rf"\s*\(?\s*(?:(?:CGFloat|Double|Float|Int)\(\s*)?['\"]?\s*({_NUM})(?![xX\d])", text, re.I)]
    vals += [float(m.group(1)) for m in re.finditer(rf"name\s*=\s*['\"](?:android:)?(?:{alt})['\"]\s*>\s*({_NUM})", text, re.I)]
    return vals


# -- colours
_HEX_PREFIXED = re.compile(r"(?:#|0x)([0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})(?![0-9a-fA-F])")
_HEX_QUOTED = re.compile(r"(?<=['\"])([0-9a-fA-F]{8}|[0-9a-fA-F]{6})(?=['\"])")  # Color(hex: "1F7A8C"), palette arrays, JSON
_COMPONENT = re.compile(r"['\"]?\b(red|green|blue)['\"]?\s*[:=]\s*['\"]?(?:(?:CGFloat|Double|Float)\(\s*)?"
                        r"(0x[0-9a-fA-F]{1,2}|\d*\.\d+|\d+)\s*\)?(\s*/\s*255(?:\.0+)?)?", re.I)
_NAMED = re.compile(r"(?<![\w$-])(?:(?:UI|NS)?Colou?rs?\.|\.)?(black|white)(?![\w$-])(?!\s*:)", re.I)
_GREY = re.compile(rf"(?<![\w$-])white\s*:\s*({_NUM})", re.I)  # UIColor(white: 0, alpha: 0.2)
_CLEAR = re.compile(r"(?<![\w$-])(?:(?:UI|NS)?Colou?rs?\.|\.)?(clear|transparent)(?![\w$-])", re.I)


def _hexes(text):
    """Every hex colour as RRGGBB (and its alpha, 0-1 or None). 8 digits may be RRGGBBAA or AARRGGBB, so both."""
    out = []
    for rx in (_HEX_PREFIXED, _HEX_QUOTED):
        for m in rx.finditer(text):
            h = m.group(1).lower()
            if len(h) == 3:
                out.append(("".join(c * 2 for c in h), None))
            elif len(h) == 6:
                out.append((h, None))
            else:
                out += [(h[:6], int(h[6:], 16) / 255), (h[2:], int(h[:2], 16) / 255)]
    return out


def _component_values(cur):
    """red/green/blue as 0-255. Hex and x/255 are already 0-255. A plain number at most 1 is a 0-1 value when
    all three are at most 1 (SwiftUI Color(red: 1, green: 0, blue: 0)), when it has a decimal point, or when
    another component is written as x/255 (UIColor(red: 0x33 / 255, green: 0x66 / 255, blue: 1)).
    Otherwise it is 0-255 (a .colorset's "red": "59")."""
    frac = any(o for _, o in cur.values())
    plain = all(not o and not v.lower().startswith("0x") for v, o in cur.values())
    unit = plain and all(float(v) <= 1.0 for v, _ in cur.values())
    out = {}
    for k, (v, o) in cur.items():
        if v.lower().startswith("0x"):
            out[k] = int(v, 16)
        elif not o and float(v) <= 1.0 and (unit or frac or "." in v):
            out[k] = float(v) * 255
        else:
            out[k] = float(v)
    return out


def _components(text):
    """Every (r, g, b) written as named red/green/blue components."""
    found, cur = [], {}
    for m in _COMPONENT.finditer(text):
        key = m.group(1).lower()
        if key in cur:
            cur = {}
        cur[key] = (m.group(2), bool(m.group(3)))
        if len(cur) == 3:
            c = _component_values(cur)
            found.append((c["red"], c["green"], c["blue"]))
            cur = {}
    return found


def _named(text):
    out = [(0, 0, 0) if m.group(1).lower() == "black" else (255, 255, 255) for m in _NAMED.finditer(text)]
    for m in _GREY.finditer(text):
        g = float(m.group(1))
        g = g * 255 if g <= 1 else g
        out.append((g, g, g))
    return out


def _has_color(text, rgba) -> bool:
    want = to_hex(rgba)[1:]
    if want in {h for h, _ in _hexes(text)}:
        return True
    r, g, b = rgba[:3]
    if re.search(rf"(?<!\d){r}\D{{1,6}}{g}\D{{1,6}}{b}(?!\d)", text):
        return True
    # iOS .colorset JSON ("red" : "0x3B" / "0.231" / "59"), SwiftUI Color(red: 0.231, ...), UIColor(red: 59/255, ...),
    # and named black / white
    return any(all(abs(x - y) <= 1 for x, y in zip(c, (r, g, b))) for c in _components(text) + _named(text))


def _colors_in(text) -> bool:
    """Is any colour written here at all?"""
    return bool(_hexes(text) or re.search(r"(?:rgba?|hsla?)\(", text, re.I) or _components(text) or _named(text) or _CLEAR.search(text))


def _alphas_in(text):
    vals = _labelled(text, ["alpha", "opacity", "shadowOpacity", "withAlphaComponent"])
    for m in re.finditer(r"(?:rgba?|hsla?)\(([^)]*)\)", text, re.I):
        parts = [p for p in re.split(r"[\s,/]+", m.group(1).strip()) if p]
        if len(parts) >= 4:
            try:
                vals.append(float(parts[3][:-1]) / 100 if parts[3].endswith("%") else float(parts[3]))
            except ValueError:
                pass
    vals += [a for _, a in _hexes(text) if a is not None]
    if _CLEAR.search(text):
        vals.append(0.0)
    return vals


def _alpha_test(text, a):
    """True when an alpha written here matches; when none is written, True for an opaque colour, else None."""
    vals = _alphas_in(text)
    if vals:
        return any(abs(v - a) <= 0.006 for v in vals)
    return True if a >= 0.999 else None


def _parse_or_none(c):
    try:
        return parse_color(c)
    except (ValueError, TypeError, AttributeError):
        return None


# -- shadows
_SHADOW_LABELS = {
    "x": ["x", "dx", "offset[-_]?x", "shadowOffsetX", "width"],
    "y": ["y", "dy", "offset[-_]?y", "shadowOffsetY", "height"],
    "blur": ["blur", "blurRadius", "blur[-_]radius", "shadowBlur"],
    "radius": ["radius", "shadowRadius"],
    "spread": ["spread", "spreadRadius", "spread[-_]radius"],
    "elevation": ["elevation", "shadowElevation"],
}
_SHADOW_OTHER = ["opacity", "shadowOpacity", "color", "shadowColor", "shadowOffset", "offset"]
_OFFSET_CALL = re.compile(rf"(?<![\w.])(?:Dp)?Offset\(\s*({_NUM})(?:\.dp|f|px)?\s*,\s*({_NUM})", re.I)
_LENGTH = rf"{_NUM}(?:px|pt|dp|rem|em)?"


def _css_shadow_lengths(text):
    """The lengths of CSS-style shadows: '0 2px 8px 0 rgba(...)' -> [[0, 2, 8, 0]]."""
    t = re.sub(r"(?:rgba?|hsla?|color-mix|var|calc)\([^)]*\)", " ", text, flags=re.I)
    return [[float(x) for x in re.findall(_NUM, m.group(1))]
            for m in re.finditer(rf"(?<![\w.#-])({_LENGTH}(?:\s+{_LENGTH}){{1,3}})(?![\w.%])", t)]


def _shadow_number(text, field, n, has_radius):
    """One shadow length, matched against its own label (x:, y:, radius:, blur, offsetX, shadowOffset's
    width/height, shadowRadius…), else its place in a CSS shadow, never any number on the line."""
    vals = _labelled(text, _SHADOW_LABELS[field])
    if not vals and field in ("x", "y"):
        vals = [float(m.group(1 if field == "x" else 2)) for m in _OFFSET_CALL.finditer(text)]
    css = _css_shadow_lengths(text)
    place = {"x": 0, "y": 1, "blur": 2, "spread": 3}.get(field)
    if not vals and place is not None and css:
        vals = [seq[place] if len(seq) > place else 0.0 for seq in css]
    if not vals and field == "blur" and not has_radius:
        radius = _labelled(text, _SHADOW_LABELS["radius"])  # React Native's shadowRadius is the CSS blur
        if radius:
            if any(_close(v, n) for v in radius):
                return True
            if any(_close(v * 2, n) for v in radius):
                return f"the code writes radius {num(radius[0])}; give it as radius"
            return False
    if not vals and field == "radius":
        vals = [v / 2 for v in (_labelled(text, _SHADOW_LABELS["blur"]) or [s[2] if len(s) > 2 else 0.0 for s in css])]
    if vals:
        return any(_close(v, n) for v in vals)
    if n == 0 and field in ("x", "y", "blur", "spread"):
        return True  # not written means 0
    if css or _OFFSET_CALL.search(text) or any(_has_label(text, labels) for labels in list(_SHADOW_LABELS.values()) + [_SHADOW_OTHER]):
        return None  # the code writes its shadow, but not this field
    return _has_number(text, n)


def _shadow_color(text, rgba, names):
    if _has_color(text, rgba):
        return True
    if any(re.search(rf"(?<![\w$-]){re.escape(n)}(?![\w$-])", text) for n in names):
        return True  # the colour token, by name
    return False if _colors_in(text) else None


# -- springs
_SPRING_LABELS = {
    "damping": ["damping"], "stiffness": ["stiffness"], "mass": ["mass"], "response": ["response"],
    "dampingFraction": ["dampingFraction", "dampingRatio", "damping_ratio", "usingSpringWithDamping"],
    "duration": ["duration", "withDuration"], "bounce": ["bounce", "extraBounce"],
}


def _spring_converted(text):
    """The code's spring in the other form: stiffness and damping from response + dampingFraction (or
    duration + bounce), and response + dampingFraction from stiffness + damping."""
    def first(field):
        vals = _labelled(text, _SPRING_LABELS[field])
        return vals[0] if vals else None
    mass = first("mass") or 1
    response, frac, out = first("response"), first("dampingFraction"), {}
    if response is not None or frac is not None:
        response, frac = response if response is not None else 0.5, frac if frac is not None else 0.825
    elif first("duration") is not None or first("bounce") is not None:
        response, bounce = first("duration") or 0.5, first("bounce") or 0
        frac = 1 - bounce if bounce >= 0 else (1 / (1 + bounce) if bounce > -1 else None)
    if response and response > 0 and frac is not None:
        out["stiffness"] = (2 * math.pi / response) ** 2 * mass
        out["damping"] = 4 * math.pi * frac * mass / response
    k, c = first("stiffness"), first("damping")
    if k and k > 0 and mass > 0:
        out["response"] = 2 * math.pi / math.sqrt(k / mass)
        if c is not None:
            out["dampingFraction"] = c / (2 * math.sqrt(k * mass))
    return out


def _spring_number(text, field, n):
    vals = _labelled(text, _SPRING_LABELS[field])
    if vals:
        return any(_close(v, n) for v in vals)
    if (field == "mass" and n == 1) or (field == "bounce" and n == 0):
        return True  # the default
    conv = _spring_converted(text).get(field)
    if conv is not None:
        return abs(conv - n) <= 0.01 * abs(n) + 0.005  # design.json may hold a rounded conversion
    if any(_has_label(text, labels) for labels in _SPRING_LABELS.values()):
        return None
    return _has_number(text, n)


# -- type
_TYPE_LABELS = {
    "size": ["font[-_]?size", "size", "ofSize", "pointSize", "textSize"],
    "lineHeight": ["line[-_]?height", "minimumLineHeight", "maximumLineHeight"],
    "lineHeightRatio": ["line[-_]?height", "height", "lineHeightMultiple", "lineHeightMultiplier", "lineSpacingMultiplier"],
    "letterSpacing": ["letter[-_]?spacing", "tracking", "kerning", "kern"],
}
_FONT_SHORTHAND = re.compile(rf"(?<![\w.])({_NUM})(?:px|pt|sp|rem)\s*/\s*({_NUM})")  # CSS font: 600 17px/22px Inter


def _type_number(look, field, n, names, strict):
    """size / lineHeight / lineHeightRatio / letterSpacing against its own label. strict: drift when it is not
    found (size); otherwise None when the code does not state it."""
    t = look.text
    vals = _labelled(t, _TYPE_LABELS[field])
    if field in ("size", "lineHeight"):
        vals += [float(m.group(1 if field == "size" else 2)) for m in _FONT_SHORTHAND.finditer(t)]
    if not vals and names:
        vals = _direct_values(t, names)
    if vals:
        return any(_close(v, n) for v in vals)
    if _has_number(t, n) or (field == "letterSpacing" and n == 0):
        return True
    return False if strict else None


_WEIGHT_NAMES = {"thin": {100, 200}, "hairline": {100}, "ultralight": {100, 200}, "extralight": {200}, "light": {300},
                 "regular": {400}, "normal": {400}, "book": {400}, "medium": {500}, "semibold": {600}, "demibold": {600},
                 "bold": {700}, "extrabold": {800}, "ultrabold": {800}, "heavy": {800, 900}, "black": {900}}
_WEIGHT_LABEL = re.compile(r"(?<![\w$-])['\"]?(?:font[-_]?)?weight['\"]?\s*(?:[:=(]|->)\s*['\"]?\s*\.?(?:[A-Za-z]+\.)*"
                           r"([A-Za-z]*[1-9]00|[A-Za-z]+(?:[-_][A-Za-z]+)?)", re.I)
_WEIGHT_TYPE = re.compile(r"(?<![\w$])(?:Font)?Weight\.([A-Za-z]*[1-9]00|[A-Za-z]+)", re.I)  # Font.Weight.bold, FontWeight.W600
_WEIGHT_WORD = re.compile(r"(?<![a-z])(thin|hairline|ultra[-_]?light|extra[-_]?light|light|regular|book|medium|semi[-_]?bold|"
                          r"demi[-_]?bold|extra[-_]?bold|ultra[-_]?bold|bold|heavy|black)(?![a-z])", re.I)


def _weight_of(word):
    w = re.sub(r"[-_\s]", "", word).lower()
    m = re.fullmatch(r"w?([1-9]00)", w)
    return {int(m.group(1))} if m else _WEIGHT_NAMES.get(w)


def _weights_in(look):
    """Font weights written in a definition, as sets of numbers. Labelled ones first (fontWeight: '600',
    weight: .semibold, Font.Weight.bold, .bold()); else weight words in font names (Inter_600SemiBold,
    fontFamily.medium). 'light' and 'black' count in font names only, since they also name themes and colours."""
    found = [w for rx in (_WEIGHT_LABEL, _WEIGHT_TYPE) for w in (_weight_of(m.group(1)) for m in rx.finditer(look.text)) if w]
    if re.search(r"\.bold\(\s*\)", look.text):
        found.append({700})
    if found:
        return found
    quoted = " ".join(m.group(2) for m in re.finditer(r"(['\"])(.*?)\1", look.value))
    outside = re.sub(r"(['\"]).*?\1", " ", look.value)
    for text, skip in ((quoted, ()), (outside, ("light", "black"))):
        for m in _WEIGHT_WORD.finditer(text):
            word = re.sub(r"[-_]", "", m.group(1)).lower()
            if word not in skip:
                found.append(_WEIGHT_NAMES[word])
    return found


def _weight_test(look, want):
    found = _weights_in(look)
    if not found:
        return None
    return any(int(want) in s for s in found)

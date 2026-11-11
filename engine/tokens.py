"""Read design.json and turn it into CSS variables, design tokens (DTCG), Markdown,
token tables for the guide, contrast numbers and the drift check.

Python 3.9+ standard library only.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

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
TEXTY = re.compile(r"(^|[^a-z])(text|fg|foreground|label|ink|on[A-Z_-]|content)", re.I)


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
        self.roles = raw.get("roles") or {}
        self.fonts = raw.get("fonts") or {}
        self.type = {k: dict(v) for k, v in (raw.get("type") or {}).items()}
        self.spacing = self._numbers(raw.get("spacing") or {}, "spacing")
        self.radii = self._numbers(raw.get("radii") or {}, "radii")
        self.shadows = {k: dict(v) for k, v in (raw.get("shadows") or {}).items()}
        motion = raw.get("motion") or {}
        self.durations = self._numbers(motion.get("durations") or {}, "durations")
        self.easings = {k: (v if isinstance(v, dict) else {"value": v}) for k, v in (motion.get("easings") or {}).items()}
        self.springs = {k: dict(v) for k, v in (motion.get("springs") or {}).items()}
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

    def _numbers(self, raw, where):
        out = {}
        for k, v in raw.items():
            meta = dict(v) if isinstance(v, dict) else {"value": v}
            if not isinstance(meta.get("value"), (int, float)):
                self.errors.append(f"{where}.{k}: value must be a number")
                continue
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
            if "<svg" in v.get("svg", ""):
                self.errors.append(f"icons.items.{k}: give only the inner shapes, without the <svg> wrapper")
            if re.search(r"<script|on\w+\s*=", v.get("svg", ""), re.I):
                self.errors.append(f"icons.items.{k}: scripts and event handlers are not allowed")
        if self.frame["device"] not in ("phone", "browser", "none"):
            self.errors.append("app.frame.device must be phone, browser or none")

    # -- helpers
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
        if "lineHeight" in v:
            return v["lineHeight"]
        if "lineHeightRatio" in v:
            return round(v["size"] * v["lineHeightRatio"], 2)
        return round(v["size"] * 1.3, 2)

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
            root.append(f"  --t-{kebab(k)}: {style}{f.get('weight', 400)} {num(v['size'])}px/{num(self.line_height(v))}px {self.font_stack(f)};")
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
                out["type"][k] = {"$type": "typography", "$value": {
                    "fontFamily": f.get("family", "system-ui"), "fontWeight": f.get("weight", 400), "fontSize": dim(v["size"]),
                    "lineHeight": round(self.line_height(v) / v["size"], 3), "letterSpacing": dim(v.get("letterSpacing", 0))}, **d(v)}
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
            out["$extensions"] = {"dev.design-canvas": {"springs": {k: {x: v[x] for x in ("damping", "stiffness", "mass") if x in v} for k, v in self.springs.items()}}}
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

    def ratios(self, token):
        """{theme: ratio against the colour this token is read on} for one colour token."""
        bgk = self.partner(token)
        out = {}
        for t in self.theme_ids:
            fg, bg = self.color_in(token, t), self.color_in(bgk, t)
            if fg and bg:
                out[t] = contrast(fg, bg)
        return out

    def is_texty(self, token):
        return token in (self.roles.get("text"), self.roles.get("textMuted")) or bool(TEXTY.search(token)) or "text" in (self.colors[token].get("group", "").lower())

    def contrast_problems(self):
        out = []
        for k in self.colors:
            if not self.is_texty(k):
                continue
            on = self.partner(k)
            for t, r in self.ratios(k).items():
                if r < 4.5:
                    out.append(f"`{k}` on `{on}` is {r}:1 in the {t} theme (text needs 4.5:1)")
        return out

    # ------------------------------------------------------------ drift check
    def check(self, root: Path | None = None):
        """Compare every token with the code its `src` points at.

        Returns (drifted, ok_count, derived, unsourced): `unsourced` lists tokens
        that have neither a `src` nor a `derived` note, so they could not be checked.
        """
        root = Path(root or self.root)
        problems, ok, skipped, unsourced = [], 0, [], []
        cache: dict[str, list[str]] = {}

        def window(src):
            texts = []
            for part in [s.strip() for s in src.split(",") if s.strip()]:
                m = re.match(r"(.+?)(?::(\d+))?$", part)
                path, line = m.group(1), m.group(2)
                f = (root / path)
                if path not in cache:
                    try:
                        cache[path] = f.read_text(encoding="utf-8", errors="replace").splitlines()
                    except OSError:
                        cache[path] = None
                lines = cache[path]
                if lines is None:
                    return None, f"source file not found: {path}"
                if line:
                    n = int(line)
                    texts.append("\n".join(lines[max(0, n - 9): n + 8]))
                else:
                    texts.append("\n".join(lines))
            return "\n".join(texts), None

        def has_number(text, n):
            s = num(n)
            return re.search(rf"(?<![\w.]){re.escape(s)}(?:\.0+)?(?![\d])", text) is not None

        def has_color(text, rgba):
            want = to_hex(rgba)[1:]
            found = set()
            for m in re.finditer(r"(?:#|0x)([0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})(?![0-9a-fA-F])", text):
                h = m.group(1).lower()
                if len(h) == 3:
                    found.add("".join(c * 2 for c in h))
                elif len(h) == 6:
                    found.add(h)
                else:
                    found.update((h[:6], h[2:]))  # RRGGBBAA or AARRGGBB
            if want in found:
                return True
            r, g, b = rgba[:3]
            if re.search(rf"(?<!\d){r}\D{{1,6}}{g}\D{{1,6}}{b}(?!\d)", text):
                return True
            # Named components: iOS .colorset JSON ("red" : "0x3B" / "0.231" / "59"),
            # SwiftUI Color(red: 0.231, ...), UIColor(red: 59/255, ...).
            cur = {}
            for m in re.finditer(r"['\"]?\b(red|green|blue)['\"]?\s*[:=]\s*['\"]?(0x[0-9a-fA-F]{1,2}|\d*\.\d+|\d+)(\s*/\s*255(?:\.0+)?)?", text, re.I):
                key, raw, over255 = m.group(1).lower(), m.group(2), m.group(3)
                if raw.lower().startswith("0x"):
                    val = int(raw, 16)
                elif "." in raw and not over255 and float(raw) <= 1.0:
                    val = float(raw) * 255
                else:
                    val = float(raw)
                if key in cur:
                    cur = {}
                cur[key] = val
                if len(cur) == 3 and all(abs(cur[k] - want_v) <= 1 for k, want_v in (("red", r), ("green", g), ("blue", b))):
                    return True
            return False

        def names_for(key, meta):
            out = [key]
            code = (meta.get("code") or "").strip()
            if code.startswith("--"):
                out.append(code.split(")")[0].replace("var(", ""))  # a CSS custom property
            if code:
                last = [x for x in re.split(r"[.\[\]'\"\s/-]+", code) if x]
                if last and last[-1] not in out:
                    out.append(last[-1])
            return out

        def key_rx(name):
            """`name: …`, `name = …`, `name(…`, `"name": …` (any case)."""
            return rf"(?<![\w$-])['\"]?{re.escape(name)}['\"]?\s*[:=(]"

        def defn(name):
            # also Android/XML resources: <color name="primary">…
            return re.compile(rf"{key_rx(name)}|\bname\s*=\s*['\"]{re.escape(name)}['\"]", re.I)

        def block_for(text, names):
            """The lines that define one of `names` (plus the rest of a multi-line object)."""
            lines = text.split("\n")
            keep = []
            for i, l in enumerate(lines):
                for n in names:
                    m = defn(n).search(l)
                    if not m:
                        continue
                    seg = [l[m.start():]]
                    depth = seg[0].count("{") + seg[0].count("(") - seg[0].count("}") - seg[0].count(")")
                    j = i
                    while depth > 0 and j + 1 < len(lines) and j - i < 12:
                        j += 1
                        seg.append(lines[j])
                        depth += lines[j].count("{") + lines[j].count("(") - lines[j].count("}") - lines[j].count(")")
                    keep.append("\n".join(seg))
                    break
            return "\n".join(keep) if keep else None

        def number_for(text, block, names, n):
            if block is None:
                return has_number(text, n)
            s = re.escape(num(n))
            direct = [nm for nm in names if re.search(key_rx(nm) + r"\s*['\"]?-?\d", block, re.I)]
            if direct:
                return any(re.search(key_rx(nm) + rf"\s*['\"]?{s}(?:\.0+)?(?![\d])", block, re.I) for nm in direct)
            return has_number(block, n)

        def run(label, key, meta, tests):
            nonlocal ok
            if meta.get("derived"):
                skipped.append(f"{label}: {meta['derived']}")
                return
            if not meta.get("src"):
                unsourced.append(label)
                return
            text, err = window(meta["src"])
            if err:
                problems.append(f"`{label}`: {err}")
                return
            block = block_for(text, names_for(key, meta))
            missing = [what for what, test in tests if not test(text, block)]
            if missing:
                problems.append(f"`{label}`: {', '.join(missing)} not found " + ("where it is defined" if block else "near") + f" ({meta['src']})")
            else:
                ok += 1

        for k, c in self.colors.items():
            vals = {to_hex(v) + (f"@{v[3]}" if v[3] != 1 else ""): v for v in c["rgba"].values()}
            run(f"colors.{k}", k, c, [(f"colour {h}", (lambda t, b, v=v: has_color(b if b is not None else t, v))) for h, v in vals.items()])
        for k, v in self.type.items():
            tests = [(f"size {num(v['size'])}", lambda t, b, n=v["size"]: has_number(b if b is not None else t, n))]
            if "lineHeight" in v:
                tests.append((f"line height {num(v['lineHeight'])}", lambda t, b, n=v["lineHeight"]: has_number(b if b is not None else t, n)))
            run(f"type.{k}", k, v, tests)
        for group, items in (("spacing", self.spacing), ("radii", self.radii), ("durations", self.durations)):
            for k, v in items.items():
                names = names_for(k, v)
                run(f"{group}.{k}", k, v, [(f"value {num(v['value'])}", lambda t, b, n=v["value"], nm=names: number_for(t, b, nm, n))])
        for k, v in self.shadows.items():
            run(f"shadows.{k}", k, v, [(f"{x} {num(v[x])}", lambda t, b, n=v[x]: has_number(b if b is not None else t, n)) for x in ("y", "blur") if x in v])
        for k, v in self.springs.items():
            run(f"springs.{k}", k, v, [(f"{x} {num(v[x])}", lambda t, b, n=v[x]: has_number(b if b is not None else t, n)) for x in ("damping", "stiffness") if x in v])
        for k, v in self.easings.items():
            nums = re.findall(r"-?\d*\.?\d+", v.get("value", ""))
            run(f"easings.{k}", k, v, [(f"value {v.get('value')}", lambda t, b, ns=nums: all(has_number(b if b is not None else t, float(n)) for n in ns))])
        for k, f in self.fonts.items():
            fam = f.get("family", "")
            run(f"fonts.{k}", k, f, [(f"family {fam}", lambda t, b, s=fam: re.search(re.escape(s).replace(r"\ ", r"[\s_-]?"), t, re.I) is not None)])
        return problems, ok, skipped, unsourced

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
                out.append(f"| `{k}` | {num(v['size'])} / {num(self.line_height(v))} | {f.get('family')} {f.get('weight', 400)}{' italic' if f.get('style') == 'italic' else ''} | {v.get('doc', '')} |")
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

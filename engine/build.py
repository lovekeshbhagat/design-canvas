#!/usr/bin/env python3
"""design-canvas: build a living design guide and a screen canvas from design.json.

  python3 engine/build.py <design-dir>              build out/guide.html, out/canvas.html, out/tokens.*
  python3 engine/build.py <design-dir> --check      drift check: exit 1 if a token no longer matches its source
  python3 engine/build.py <design-dir> --check --max-derived 10   also exit 1 when over 10% of tokens are derived
  python3 engine/build.py <design-dir> --validate   check design.json and the canvas files only
  python3 engine/build.py <design-dir> --shoot <screen-id> [--theme <id>] [--out shot.png]
                                                    render one screen to a PNG with headless Chrome

<design-dir> holds design.json and, optionally:
  guides/*.md                    chapters (see engine/markdown.py for the syntax)
  specimens/*.html               specimen snippets used by `::: specimen <name>`
  parts.css                      the app's component styles for specimens and screens
  canvas/pages/*.json            board pages, canvas/frames/<page>/<frame>.html screens,
  canvas/css/*.css, canvas/partials/*.html
  canvas/screens.json            every screen the app has, drawn or not (coverage)
  assets/                        the app's own images for screens ({{asset:logo.png}})

Python 3.9+ standard library only.
"""

from __future__ import annotations

import argparse
import difflib
import os
import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import reviews  # noqa: E402
import screens as screens_mod  # noqa: E402
from markdown import Doc, front_matter, slug  # noqa: E402
from tokens import Design, esc, kebab, num, to_hex  # noqa: E402

ASSETS = HERE / "assets"
PART_WORDS = re.compile(r"atom|molecule|organism|template|page|component|pattern", re.I)


# ---------------------------------------------------------------- token views
def swatch_cell(rgba) -> str:
    return f"rgba({rgba[0]},{rgba[1]},{rgba[2]},{num(rgba[3])})"


def src_html(src) -> str:
    """Where a token is defined. Lines in the same file are merged ("theme.ts:6, 20"); a list that
    is still long folds into "N files", with the full list on hover and on click."""
    if isinstance(src, dict):  # per-theme src: {"light": "a.swift:3", "dark": "a.swift:9"}
        src = ", ".join(str(v) for v in src.values() if v)
    if not src:
        return ""
    by: dict[str, list] = {}
    for part in [s.strip() for s in str(src).split(",") if s.strip()]:
        m = re.match(r"(.+?)(?::(\d+))?$", part)
        by.setdefault(m.group(1), []).append(m.group(2))
    entries = [f + (":" + ", ".join(n for n in lines if n) if any(lines) else "") for f, lines in by.items()]
    short = ", ".join(entries)
    if len(entries) <= 2 and len(short) <= 60:
        return f'<span class="src" title="Defined in {esc(short)}">{esc(short)}</span>'
    if len(by) > 1:
        label = f"{len(by)} files"
    else:
        path, lines = next(iter(by.items()))
        label = f"{len(lines)} lines in {esc(path.rsplit('/', 1)[-1])}"
    items = "".join(f"<li>{esc(e)}</li>" for e in entries)
    return f'<details class="src"><summary title="{esc(chr(10).join(entries))}">{label}</summary><ul>{items}</ul></details>'


def ratio_html(d: Design, k: str) -> str:
    """The contrast of a text colour on each colour it is read on. Nothing for colours not used as text."""
    if not d.is_texty(k):
        return ""
    out = []
    for fill, rs in d.pairs(k):
        low = " low" if any(r < 4.5 for r in rs.values()) else ""
        if len(rs) > 3:  # many themes: the range, with every theme on hover
            lo, hi = min(rs.values()), max(rs.values())
            worst = min(rs, key=rs.get)
            title = " · ".join(f"{t} {r}:1" for t, r in rs.items())
            txt = f"{lo}:1 ({esc(worst)}) to {hi}:1" if lo != hi else f"{lo}:1"
            out.append(f'<span class="ratio{low}" title="{esc(title)}">{txt} on {esc(fill)}</span>')
        else:
            multi = len(d.theme_ids) > 1
            txt = " · ".join(f"{r}:1" + (f" {esc(t)}" if multi else "") for t, r in rs.items())
            out.append(f'<span class="ratio{low}">{txt} on {esc(fill)}</span>')
    return "".join(out)


def view_colors(d: Design) -> str:
    groups: dict[str, list] = {}
    for k, c in d.colors.items():
        groups.setdefault(c.get("group") or "Colours", []).append((k, c))
    multi = len(d.theme_ids) > 1
    out = []
    for g, items in groups.items():
        if len(groups) > 1:
            out.append(f'<h4 class="sw-group">{esc(g)}</h4>')
        cells = []
        for k, c in items:
            per = ""
            varies = multi and len(set(c["values"].values())) > 1  # one value for every theme: show it once
            if varies:
                per = '<span class="per">' + "".join(
                    f'<i title="{esc(t)}: {esc(c["values"][t])}" style="background:{swatch_cell(c["rgba"][t])}"></i>' for t in d.theme_ids) + "</span>"
            vals = " · ".join(f"{esc(t)} {esc(c['values'][t])}" for t in d.theme_ids) if varies else esc(c["values"][d.default])
            cells.append(
                f'<figure class="swatch"><div class="chip" style="background:var(--c-{kebab(k)})">{per}</div>'
                f'<figcaption><b>{esc(k)}</b><code>{vals}</code>'
                + (f'<code class="code">{esc(d.code_text(c["code"]))}</code>' if c.get("code") else "")
                + ratio_html(d, k)
                + src_html(c.get("src"))
                + (f'<span class="derived">derived: {esc(c["derived"])}</span>' if c.get("derived") else "")
                + (f'<span class="doc">{esc(c["doc"])}</span>' if c.get("doc") else "")
                + "</figcaption></figure>")
        out.append('<div class="swatches">' + "".join(cells) + "</div>")
    return "".join(out)


def view_roles(d: Design) -> str:
    rows = []
    from tokens import ROLES
    for r in ROLES:
        tok = d.roles.get(r)
        chips = "".join(f'<i title="{esc(t)}" style="background:{swatch_cell(d.colors[tok]["rgba"][t])}"></i>' for t in d.theme_ids) if tok else ""
        cell = f"<code>{esc(tok)}</code>" if tok else '<span class="doc">fallback</span>'
        rows.append(f'<tr><td><code>{esc(r)}</code></td><td>{cell}</td><td><span class="per inline">{chips}</span></td></tr>')
    return '<div class="table"><table><thead><tr><th>Role</th><th>Token</th><th>' + " · ".join(esc(t) for t in d.theme_ids) + "</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"


def view_type(d: Design) -> str:
    rows = []
    for k, v in d.type.items():
        f = d.type_font(k)
        big = v["size"] >= 24
        sample = v.get("sample") or ("Design that ships" if big else "The quick brown fox jumps over the lazy dog")
        tt = f";text-transform:{v['textTransform']}" if v.get("textTransform") else ""
        lh = d.line_height(v)
        lh_txt = num(lh) if lh is not None else '<span title="The code sets no line height, so the platform default is used.">auto</span>'
        rows.append(
            f'<div class="type-row"><div class="type-meta"><b>{esc(k)}</b>'
            f'<code>{num(v["size"])}/{lh_txt} · {f.get("weight", 400)}{" italic" if f.get("style") == "italic" else ""}'
            f'{" · " + num(v["letterSpacing"]) + " ls" if v.get("letterSpacing") else ""}</code>'
            + (f'<code class="code">{esc(d.code_text(v["code"]))}</code>' if v.get("code") else "")
            + (f'<span class="doc">{esc(v["doc"])}</span>' if v.get("doc") else "")
            + src_html(v.get("src"))
            + f'</div><div class="type-sample" style="font:var(--t-{kebab(k)});letter-spacing:var(--ls-{kebab(k)}){tt}">{esc(sample)}</div></div>')
    return '<div class="type-scale">' + "".join(rows) + "</div>" + view_fonts(d)


def view_fonts(d: Design) -> str:
    if not d.fonts:
        return ""
    items = "".join(
        f'<li><code>{esc(k)}</code> <span style="font-family:var(--f-{kebab(k)});font-weight:{f.get("weight", 400)};font-style:{f.get("style", "normal")}">{esc(f.get("family"))} {f.get("weight", 400)}{" italic" if f.get("style") == "italic" else ""}</span>'
        f'{" <span class=doc>" + esc(f["doc"]) + "</span>" if f.get("doc") else ""}</li>' for k, f in d.fonts.items())
    return f'<ul class="families">{items}</ul>'


def view_spacing(d: Design) -> str:
    bars = "".join(
        f'<div class="space-row"><code>{esc(k)}</code><span class="bar" style="width:{min(v["value"], 480)}px"></span><code>{num(v["value"])}px</code>'
        f'<span class="doc">{esc(v.get("doc", ""))}{src_html(v.get("src"))}</span></div>' for k, v in d.spacing.items())
    return f'<div class="spaces">{bars}</div>' if bars else '<p class="note">No spacing tokens.</p>'


def view_radii(d: Design) -> str:
    cells = "".join(
        f'<figure class="radius"><div class="rbox" style="border-radius:{min(v["value"], 60)}px"></div>'
        f'<figcaption><b>{esc(k)}</b><code>{num(v["value"])}px</code><span class="doc">{esc(v.get("doc", ""))}</span>{src_html(v.get("src"))}</figcaption></figure>'
        for k, v in d.radii.items())
    return f'<div class="radii">{cells}</div>' if cells else '<p class="note">No radius tokens.</p>'


def view_shadows(d: Design) -> str:
    cells = "".join(
        f'<figure class="shadow"><div class="sbox" style="box-shadow:var(--sh-{kebab(k)})"></div>'
        f'<figcaption><b>{esc(k)}</b><code>{num(v.get("x", 0))} {num(v.get("y", 0))} {num(v.get("blur", 0))} {num(v.get("spread", 0))} · {d.shadow_rgba(v)}'
        f'{" · elev " + num(v["elevation"]) if "elevation" in v else ""}</code><span class="doc">{esc(v.get("doc", ""))}</span>{src_html(v.get("src"))}</figcaption></figure>'
        for k, v in d.shadows.items())
    return f'<div class="shadows">{cells}</div>' if cells else '<p class="note">No shadow tokens.</p>'


def view_motion(d: Design) -> str:
    rows = "".join(
        f'<div class="motion-row"><code>{esc(k)}</code><span class="track"><span class="dot" style="animation-duration:{num(v["value"] * 4)}ms"></span></span>'
        f'<code>{num(v["value"])} ms</code><span class="doc">{esc(v.get("doc", ""))}{src_html(v.get("src"))}</span></div>' for k, v in d.durations.items())
    rows += "".join(
        f'<div class="motion-row"><code>{esc(k)}</code><span class="track"><span class="dot" style="animation-duration:1600ms;animation-timing-function:{esc(v["value"])}"></span></span>'
        f'<code>easing</code><span class="doc">{esc(v["value"])} {esc(v.get("doc", ""))}{src_html(v.get("src"))}</span></div>' for k, v in d.easings.items())
    rows += "".join(
        f'<div class="motion-row"><code>{esc(k)}</code><code>' + " · ".join(f"{x} {num(v[x])}" for x in ("response", "dampingFraction", "duration", "bounce", "damping", "stiffness", "mass") if x in v)
        + f'</code><code>spring</code><span class="doc">{esc(v.get("doc", ""))}{src_html(v.get("src"))}</span></div>' for k, v in d.springs.items())
    if not rows:
        return '<p class="note">No motion tokens.</p>'
    return f'<div class="motion">{rows}</div><p class="note">Duration dots run at 4× the token so the difference is visible.</p>'


def view_icons(d: Design) -> str:
    items = d.icons.get("items") or {}
    system = system_icons(d)

    def code(k, v):
        text = system.get(k) or v.get("source")
        return f"<br><code>{esc(text)}</code>" if text else ""
    cells = "".join(
        f'<figure class="icon"><svg class="ic" aria-hidden="true"><use href="#i-{esc(k)}"/></svg><figcaption>{esc(k)}'
        f'{code(k, v)}</figcaption></figure>' for k, v in items.items())
    sets = ", ".join(sorted({v.split(":")[0] for v in system.values()}))
    many = len(system) != 1
    note = (f'<p class="note">{len(system)} system icon{"s" if many else ""} ({esc(sets)}) {"are" if many else "is"} drawn as a dashed placeholder: '
            "the app gets them from the operating system, so their artwork is not copied here. "
            "The name under each one is the symbol to look up.</p>") if system else ""
    return f'<div class="icons">{cells}</div>{note}' if cells else '<p class="note">No icons.</p>'


def view_contrast(d: Design) -> str:
    probs = d.contrast_problems()
    texts = d.text_colors()
    which = ('<p class="note">Checked as text: ' + ", ".join(f"<code>{esc(k)}</code>" for k in texts) + ".</p>") if texts else ""
    if not probs:
        return '<p class="ok">Every text colour reaches 4.5:1 on the colour it is read on, in every theme.</p>' + which
    return '<ul class="drift">' + "".join(f"<li>{inline_code(p)}</li>" for p in probs) + "</ul>" + which


def inline_code(s: str) -> str:
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", esc(s).replace("&#x27;", "'"))


def view_drift(d: Design, result) -> str:
    if result is None:
        return f'<p class="note">The app code was not found at <code>{esc(d.app.get("root", ".."))}</code>, so the drift check did not run.</p>'
    problems, ok, skipped, unsourced = result
    clean = not problems and not unsourced
    head = f'<p class="{"ok" if clean else "note"}">{ok} token{"s" if ok != 1 else ""} checked against the code{": all match." if not problems else "."}</p>'
    body = ('<ul class="drift">' + "".join(f"<li>{inline_code(p)}</li>" for p in problems) + "</ul>") if problems else ""
    if unsourced:
        body += '<ul class="drift">' + "".join(f"<li><code>{esc(u)}</code> has no <code>src</code>, so it was not checked</li>" for u in unsourced) + "</ul>"
    not_checked, could = getattr(result, "not_checked", []), getattr(result, "could_check", [])
    if not_checked:
        body += '<p class="note">Not checked, because the code does not state them: ' + ", ".join(esc(n) for n in not_checked) + "</p>"
    if skipped:
        body += (f'<p class="note">Derived in code, so not checked ({len(skipped)}, {pct(getattr(result, "derived_share", 0))} of tokens): '
                 + "; ".join(esc(s) for s in skipped) + "</p>")
    if could:
        body += '<p class="note">Marked derived, but the note names a source line, so it could be checked: ' + ", ".join(esc(c) for c in could) + "</p>"
    return head + body


def pct(share) -> str:
    """0.095 -> '10%'; a share above 0 that rounds to 0 -> '<1%'."""
    return "<1%" if 0 < share < 0.005 else f"{round(share * 100)}%"


def lineage_html(usage, name: str) -> str:
    if not usage:  # app code not found, or no JS/TS imports to read (e.g. Swift, Kotlin): nothing to show
        return ""
    files = usage.get(name, [])
    if not files:
        return '<p class="lineage none"><b>Used in:</b> no imports found.</p>'
    by: dict[str, list[str]] = {}
    for f in files:
        parts = f.split("/")
        by.setdefault("/".join(parts[:2]) if len(parts) > 2 else parts[0], []).append(f)
    chips = "".join(f'<li title="{esc(chr(10).join(v))}"><span>{esc(k)}</span><b>{len(v)}</b></li>' for k, v in sorted(by.items(), key=lambda kv: -len(kv[1])))
    return f'<div class="lineage"><p><b>Used in {len(files)} file{"s" if len(files) != 1 else ""}</b></p><ul>{chips}</ul></div>'


# ---------------------------------------------------------------- shared bits
ICON_MACRO = re.compile(r"\{\{icon:([\w.-]+)(?::(\d+))?\}\}")


def system_icons(d: Design) -> dict:
    """{icon key: 'sf-symbols: gearshape'} for icons drawn as labelled placeholders (system icon sets)."""
    return {k: f'{v["system"]}: {v.get("name") or k}' for k, v in (d.icons.get("items") or {}).items()
            if isinstance(v, dict) and v.get("system")}


def expand_icons(s: str, system: dict | None = None) -> str:
    def sub(m):
        size = f' style="width:{m.group(2)}px;height:{m.group(2)}px"' if m.group(2) else ""
        name = (system or {}).get(m.group(1))
        if name:
            return (f'<svg class="ic ic-sys" aria-hidden="true" data-icon="{esc(name)}"{size}>'
                    f'<title>{esc(name)}</title><use href="#i-{m.group(1)}"/></svg>')
        return f'<svg class="ic" aria-hidden="true"{size}><use href="#i-{m.group(1)}"/></svg>'
    return ICON_MACRO.sub(sub, s)


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.exists() else ""


def script_json(obj) -> str:
    """JSON that is safe inside a <script> element: no '<' can close it or open a comment."""
    return json.dumps(obj, ensure_ascii=False).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


GROUPING_RULES = ("@supports", "@layer", "@container")
DATA_URL = re.compile(r"""url\(\s*(?:"data:[^"]*"|'data:[^']*'|data:[^)]*)\s*\)""", re.I)


def short_value(v: str) -> str:
    """Keep inspect data small: data: URIs become a marker, and very long values are cut."""
    v = DATA_URL.sub("url(data:…)", v)
    return v if len(v) <= 200 else v[:200] + "…"


def parse_css(text: str, media: str | None = None) -> list:
    """Split simple CSS into [{s: selector, m: media, d: [[prop, value, important]]}] for the inspect panel.
    Rules inside @media keep their media query; rules inside @supports, @layer and @container are read as if always on."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    out, i, n = [], 0, len(text)
    while i < n:
        j = text.find("{", i)
        if j < 0:
            break
        prelude = text[i:j].strip()
        if ";" in prelude:  # statement at-rules before this block (@import …; @layer a, b;)
            prelude = prelude.rsplit(";", 1)[1].strip()
        depth, k = 1, j + 1
        while k < n and depth:
            depth += {"{": 1, "}": -1}.get(text[k], 0)
            k += 1
        body = text[j + 1:k - 1]
        low = prelude.lower()
        if low.startswith("@media"):
            out += parse_css(body, prelude[6:].strip())
        elif low.startswith(GROUPING_RULES):
            out += parse_css(body, media)
        elif prelude and not prelude.startswith("@"):
            decls = []
            for part in re.split(r";(?![^(]*\))", body):
                if ":" not in part:
                    continue
                prop, val = part.split(":", 1)
                val = val.strip()
                imp = val.endswith("!important")
                decls.append([prop.strip().lower(), short_value(val[:-10].strip() if imp else val), imp])
            if decls:
                out.append({"s": " ".join(prelude.split()), "m": media, "d": decls})
        i = k
    return out


def page_shell(name: str, d: Design, web_fonts: bool = True, **parts) -> str:
    links, faces = d.font_links()
    page = read(ASSETS / name)
    parts.setdefault("FONT_LINKS", links if web_fonts else "")
    parts.setdefault("FONT_FACES", faces)
    parts.setdefault("APP", esc(d.name))
    parts.setdefault("BUILT", date.today().isoformat())
    for k, v in parts.items():
        page = page.replace("{{" + k + "}}", str(v))
    return page


def theme_buttons(d: Design) -> str:
    """Two or three short theme names: a row of buttons. More themes, or longer names: a menu."""
    if len(d.themes) < 2:
        return ""
    if len(d.themes) <= 3 and sum(len(t["label"]) for t in d.themes) <= 18:
        return '<div class="themes" role="group" aria-label="Theme">' + "".join(
            f'<button type="button" data-set-theme="{esc(t["id"])}" data-scheme="{esc(t["scheme"])}">{esc(t["label"])}</button>' for t in d.themes) + "</div>"
    return ('<label class="theme-pick"><span>Theme</span><select data-theme-select aria-label="Theme">' + "".join(
        f'<option value="{esc(t["id"])}">{esc(t["label"])}</option>' for t in d.themes) + "</select></label>")


# ---------------------------------------------------------------- guide
def canvas_cta(n_screens: int, coverage: dict | None = None) -> str:
    """The highlighted link from the guide's home to the screen canvas.
    coverage (from canvas/screens.json) turns the title into "See 6 of 37 screens on the canvas"."""
    if not n_screens:
        return ""
    todo = len(coverage["missing"]) if coverage else 0
    if todo:
        title = f"See {coverage['drawn']} of {coverage['listed']} screens on the canvas"
    else:
        title = f"See all {n_screens} screens on the canvas" if n_screens > 1 else "See the screen on the canvas"
    more = f" {todo} more {'is' if todo == 1 else 'are'} listed but not drawn yet." if todo else ""
    return (
        '<a class="cta" href="canvas.html">'
        '<span class="cta-art" aria-hidden="true"><i></i><i></i><i></i><em></em></span>'
        f'<span class="cta-text"><small>Screen canvas</small><b>{title}</b>'
        f'<span>Pan and zoom around the app. Press Inspect, then pick any part to see its real tokens and leave a comment.{more}</span></span>'
        '<span class="cta-go">Open the canvas<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 10h11M11 5l5 5-5 5"/></svg></span>'
        "</a>"
    )


def guide_sections(d: Design, sections: list, missing: list) -> str:
    """The rendered chapters with canvas partials ({{> name k=v}}) and icons expanded, as on the canvas.
    Partials only expand where raw HTML is kept: specimens and HTML lines, not code samples."""
    text = "\n".join(sections)
    pdir = d.dir / "canvas" / "partials"
    for name in sorted({m[0] for m in PARTIAL.findall(text)}):
        if not (pdir / f"{name}.html").exists():
            missing.append(f"canvas/partials/{name}.html (used in the guide)")
    return expand_icons(expand_partials(text, pdir))


def build_guide(d: Design, drift_result, usage, n_screens: int, web_fonts: bool = True, coverage: dict | None = None):
    views = {
        "colors": view_colors(d), "roles": view_roles(d), "type": view_type(d), "fonts": view_fonts(d),
        "spacing": view_spacing(d), "radii": view_radii(d), "shadows": view_shadows(d), "motion": view_motion(d),
        "icons": view_icons(d), "contrast": view_contrast(d), "drift": view_drift(d, drift_result),
    }
    doc = Doc(views, lambda n: lineage_html(usage, n), d.dir / "specimens")
    chapters = sorted((d.dir / "guides").glob("*.md"))
    sections, nav, ladder = [], [], [("tokens", "Tokens", d.count())]
    if not chapters:
        md = "# Tokens\n\n## Colour\n\n::: tokens colors\n\n## Roles\n\n::: tokens roles\n\n## Type\n\n::: tokens type\n\n## Spacing\n\n::: tokens spacing\n\n## Radius\n\n::: tokens radii\n\n## Shadow\n\n::: tokens shadows\n\n## Motion\n\n::: tokens motion\n\n## Icons\n\n::: tokens icons\n\n## Contrast\n\n::: tokens contrast\n\n## Drift check\n\n::: tokens drift\n"
        chapters = [("00-tokens", md)]
    else:
        chapters = [(f.stem, f.read_text(encoding="utf-8")) for f in chapters]
    for stem, md in chapters:
        meta = front_matter(md)
        h1 = re.search(r"^#\s+(.+)$", md, re.M)
        title = meta.get("title") or (h1.group(1).strip() if h1 else stem)
        label = meta.get("label") or re.sub(r"<[^>]+>|[*`]", "", title)
        sid = slug(meta.get("id") or re.sub(r"^\d+[-_]", "", stem))
        parts = meta.get("parts", "").lower() == "true" if "parts" in meta else bool(PART_WORDS.search(stem))
        before = len(doc.toc)
        body = doc.render(md, parts)
        n_parts = sum(1 for lvl, *_ in doc.toc[before:] if lvl == 3)
        sections.append(f'<section class="chapter{" parts" if parts else ""}" id="{sid}">{body}</section>')
        nav.append((meta.get("group", "Guide"), sid, label, n_parts if parts else None))
        if parts and n_parts:
            ladder.append((sid, label, n_parts))
    groups: dict[str, list] = {}
    for g, sid, label, n in nav:
        groups.setdefault(g, []).append((sid, label, n))
    nav_html = "".join(
        f'<div class="nav-group"><span class="nav-label">{esc(g)}</span>'
        + "".join(f'<a href="#{sid}">{esc(label)}{f" <small>{n}</small>" if n else ""}</a>' for sid, label, n in items)
        + "</div>" for g, items in groups.items())
    if n_screens:
        nav_html += f'<div class="nav-group"><span class="nav-label">Canvas</span><a href="canvas.html">All screens <small>{n_screens}</small></a></div>'
    ladder_html = "".join(f'<li><a href="#{h}"><b>{n}</b><span>{esc(lbl)}</span></a></li>' for h, lbl, n in ladder)
    page = page_shell(
        "guide.html", d, web_fonts,
        TITLE=f"{esc(d.name)} design guide",
        DESCRIPTION=esc(d.app.get("description", f"The {d.name} design system, read from the code.")),
        CSS_VARS=d.css(), CSS=read(ASSETS / "guide.css") + "\n" + d.icon_css() + "\n" + read(d.dir / "parts.css"),
        JS=read(ASSETS / "guide.js"), NAV=nav_html, SPRITE=d.sprite(), SECTIONS=guide_sections(d, sections, doc.missing),
        LADDER=ladder_html, LADDER_N=str(len(ladder)), CANVAS_CTA=canvas_cta(n_screens, coverage),
        THEMES=theme_buttons(d), LEDE=esc(d.app.get("description", "")),
        PLATFORM=esc(d.app.get("platform", "app")), DEFAULT_THEME=esc(d.default), DEFAULT_SCHEME=esc(d.themes[0]["scheme"]),
        INITIAL=esc(d.name[:1].upper()), SCHEMES=script_json({t["id"]: t["scheme"] for t in d.themes}),
    )
    return page, doc.missing


# ---------------------------------------------------------------- canvas
STATUS = (
    '<div class="dev-sb"><span>9:41</span><span class="r">'
    '<svg viewBox="0 0 18 12"><rect x="0" y="8" width="3" height="4" rx="1"/><rect x="5" y="5.5" width="3" height="6.5" rx="1"/>'
    '<rect x="10" y="3" width="3" height="9" rx="1"/><rect x="15" y="0" width="3" height="12" rx="1"/></svg>'
    '<svg viewBox="0 0 16 12"><path d="M8 2.2c2.4 0 4.6.9 6.3 2.5l1.2-1.3A10.8 10.8 0 0 0 8 .4 10.8 10.8 0 0 0 .5 3.4l1.2 1.3A9 9 0 0 1 8 2.2Zm0 3.6c1.5 0 2.9.6 4 1.6l1.2-1.3A7.4 7.4 0 0 0 8 4a7.4 7.4 0 0 0-5.2 2.1L4 7.4a5.7 5.7 0 0 1 4-1.6Zm0 3.6c.6 0 1.2.2 1.6.6L8 11.6 6.4 10c.4-.4 1-.6 1.6-.6Z"/></svg>'
    '<svg viewBox="0 0 27 12"><rect x="0.5" y="0.5" width="23" height="11" rx="3.5" fill="none" stroke="currentColor" opacity="0.4"/>'
    '<rect x="2" y="2" width="18" height="8" rx="2"/><rect x="24.5" y="4" width="1.8" height="4" rx="0.9" opacity="0.4"/></svg>'
    "</span></div>"
)
PARTIAL = re.compile(r"\{\{>\s*([\w-]+)((?:\s+[\w-]+=(?:\"[^\"]*\"|[^\s}]+))*)\s*\}\}")


def expand_partials(text: str, partials_dir: Path, depth=0) -> str:
    def sub(m):
        f = partials_dir / f"{m.group(1)}.html"
        if not f.exists():
            return f'<div class="missing">missing partial {esc(m.group(1))}</div>'
        body = f.read_text(encoding="utf-8")
        args = dict((k, v.strip('"')) for k, v in re.findall(r"([\w-]+)=(\"[^\"]*\"|[^\s}]+)", m.group(2) or ""))
        body = re.sub(r"\{\{(\w[\w-]*)\}\}", lambda mm: esc(args.get(mm.group(1), "")), body)
        return expand_partials(body, partials_dir, depth + 1) if depth < 3 else body
    return PARTIAL.sub(sub, text)


def read_frame(cdir: Path, page: str, fid: str, d: Design | None = None, problems: list | None = None, sizes: dict | None = None):
    """(front matter, markup) of one screen, with partials, icons and (given d) assets expanded.
    With d, problems collects unknown icons, missing assets and macros that were not understood."""
    f = cdir / "frames" / page / f"{fid}.html"
    if not f.exists():
        return None, f'<div class="missing">missing frames/{esc(page)}/{esc(fid)}.html</div>'
    text = f.read_text(encoding="utf-8")
    meta = front_matter(text)
    text = re.sub(r"^\s*<!--.*?-->", "", text, count=1, flags=re.S)
    text = expand_partials(text, cdir / "partials")
    if d is None:
        return meta, expand_icons(text)
    where = f"frames/{page}/{fid}.html"
    probs = problems if problems is not None else []
    text = screens_mod.expand_assets(text, d.dir / "assets", where, probs, sizes if sizes is not None else {})
    known = d.icons.get("items") or {}
    probs += [f"{where}: icon '{n}' is not in design.json icons" for n in sorted({m.group(1) for m in ICON_MACRO.finditer(text)} - set(known))]
    text = expand_icons(text, system_icons(d))
    probs += screens_mod.leftover_macros(text, where)
    return meta, text


def device(d: Design, meta: dict, page: dict, body: str, theme: str | None = None) -> tuple[str, int]:
    kind = meta.get("device") or page.get("device") or d.frame["device"]
    w = int(meta.get("width") or page.get("width") or d.frame["width"])
    h = meta.get("height") or page.get("height") or d.frame["height"]
    tall = str(h) == "auto"
    theme = theme or meta.get("theme") or page.get("theme")
    attrs = f' data-theme="{esc(theme)}"' if theme else ""
    if meta.get("statusbar") == "light":
        attrs += ' data-statusbar="light"'
    style = f'width:{w}px;{"min-height" if tall else "height"}:{d.frame["height"] if tall else int(h)}px'
    if kind == "phone":
        inner = f'{STATUS}<div class="dev-island"></div><div class="sc">{body}</div><div class="dev-home"></div>'
    elif kind == "browser":
        inner = f'<div class="dev-bar"><i></i><i></i><i></i><span>{esc(meta.get("url", ""))}</span></div><div class="sc">{body}</div>'
    else:
        inner = f'<div class="sc">{body}</div>'
    return f'<div class="dev dev-{kind}{" tall" if tall else ""}"{attrs} style="{style}">{inner}</div>', w


def frame_css(d: Design) -> str:
    """Everything a screen needs: device chrome, icons, the app's parts and the page styles."""
    return "\n".join([read(ASSETS / "frame.css"), d.icon_css(), read(d.dir / "parts.css"),
                      *[read(p) for p in sorted((d.dir / "canvas" / "css").glob("*.css"))]])


REF_UI = ('<div class="cv-ref" role="group" aria-label="Compare with a screenshot of the app"><span class="cv-ref-modes">'
          '<button type="button" data-ref="off" aria-pressed="true">Drawing</button>'
          '<button type="button" data-ref="side" aria-pressed="false">Side by side</button>'
          '<button type="button" data-ref="over" aria-pressed="false">Overlay</button></span>'
          '<input type="range" min="0" max="100" value="50" aria-label="Screenshot opacity" title="Screenshot opacity" hidden></div>')


def coverage_panel(cov: dict | None, pages: dict) -> str:
    """The side panel's 'not drawn yet' list (canvas/screens.json), grouped by canvas page."""
    if not cov or not cov["missing"]:
        return ""
    groups: dict[str, list] = {}
    for e in cov["missing"]:
        groups.setdefault(pages.get(e["page"], e["page"]) if e.get("page") else "", []).append(e)
    if "" in groups and len(groups) > 1:
        groups["No page yet"] = groups.pop("")
    body = "".join(
        (f'<div class="grp">{esc(g)}</div>' if g else "") + "<ul>" + "".join(
            f'<li><b>{esc(e["name"])}</b>' + (f'<span>{esc(e["state"])}</span>' if e.get("state") else "")
            + (f'<code>{esc(e["source"])}</code>' if e.get("source") else "") + "</li>" for e in items) + "</ul>"
        for g, items in groups.items())
    n = len(cov["missing"])
    return f'<details class="todo" open><summary>{n} screen{"s" if n != 1 else ""} not drawn yet</summary>{body}</details>'


def build_canvas(d: Design, root: Path | None = None, review_data=None, web_fonts: bool = True, report: dict | None = None):
    """Returns (html or None, number of screens, problems, screens {id: {title, page, source}}).
    review_data: (comments, updates) as read from reviews/ (the page merges them itself).
    report: pass a dict to also get "coverage" (canvas/screens.json), "outdated" (screens whose source
    has a newer git commit than the frame; this runs git) and "warnings"."""
    cdir = d.dir / "canvas"
    pages = sorted((cdir / "pages").glob("*.json"))
    root = Path(root or d.root)
    inventory, inv_problems = screens_mod.load_inventory(cdir, root)
    if report is not None:
        report.update(coverage=screens_mod.coverage(inventory, []), outdated=[], warnings=[])
    if not pages:
        return None, 0, inv_problems, {}
    app_css = frame_css(d)
    css = "\n".join([read(ASSETS / "canvas.css"), app_css, read(ASSETS / "review.css")])
    pages_html, nav, chips, data_pages, missing = [], [], [], [], list(inv_problems)
    screens: dict[str, dict] = {}
    drawn, refs, asset_sizes, git_frames, page_titles = [], {}, {}, {}, {}
    refs_bytes = 0
    n_frames = 0
    for pf in pages:
        try:
            page = json.loads(pf.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            missing.append(f"{pf.name}: invalid JSON ({e})")
            continue
        pid = page.get("id") or re.sub(r"^\d+[-_]", "", pf.stem)
        rows_html, rows_data = [], []
        for row in page.get("rows", []):
            frames_html, frames_data = [], []
            for fid in row.get("frames", []):
                where = f"frames/{pid}/{fid}.html"
                meta, body = read_frame(cdir, pid, fid, d, missing, asset_sizes)
                exists = meta is not None
                if not exists:
                    missing.append(where)
                    meta = {"title": fid, "state": "missing"}
                else:
                    drawn.append(fid)
                listed = screens_mod.split_sources(meta.get("source"))
                sources, probs = screens_mod.check_sources(root, listed, where)
                missing += probs
                if sources and exists:
                    git_frames[fid] = (cdir / "frames" / pid / f"{fid}.html", sources)
                if fid in screens:
                    missing.append(f"screen id '{fid}' is used on two pages; comments can't tell them apart")
                screens[fid] = {"title": meta.get("title", fid), "state": meta.get("state", "Default"), "page": pid,
                                "source": ", ".join(sources) or None}
                if len(sources) > 1:
                    screens[fid]["sources"] = sources
                dev, w = device(d, meta, page, body)
                ref = None
                if meta.get("reference"):
                    ref, nbytes, probs = screens_mod.reference(d.dir, meta["reference"], where)
                    missing += probs
                    if ref:
                        refs[fid] = {"src": ref, "path": meta["reference"]}
                        refs_bytes += nbytes
                state = meta.get("state", "Default")
                note = meta.get("note", "")
                frames_html.append(
                    f'<figure class="cv-frame" data-id="{esc(fid)}" style="width:{w}px">'
                    f'<figcaption class="cv-label"><b>{esc(meta.get("title", fid))}</b>'
                    f'<span class="st{" default" if state.lower() == "default" else ""}">{esc(state)}</span>'
                    + (f'<code>{esc(", ".join(listed))}</code>' if listed else "")
                    + f"<!--stale:{esc(fid)}-->" + (REF_UI if ref else "")
                    + "</figcaption>" + (f'<div class="cv-pair">{dev}</div>' if ref else dev)
                    + (f'<p class="note">{esc(note)}</p>' if note else "") + "</figure>")
                frames_data.append({"id": fid, "title": meta.get("title", fid), "state": state})
            n_frames += len(frames_data)
            rows_html.append(
                f'<div class="cv-row"{" data-flow" if row.get("flow") else ""}><div class="cv-row-head"><h2>{esc(row.get("title", ""))}</h2>'
                + (f'<p>{esc(row["note"])}</p>' if row.get("note") else "") + f'</div><div class="cv-row-frames">{"".join(frames_html)}</div></div>')
            rows_data.append({"title": row.get("title", ""), "frames": frames_data})
        title = page.get("title", pid)
        page_titles[pid] = title
        pages_html.append(
            f'<section class="cv-page" data-page="{esc(pid)}" hidden><header class="cv-head"><span class="eyebrow">Page {esc(page.get("order", len(pages_html) + 1))}</span>'
            f'<h1>{esc(title)}</h1><p>{esc(page.get("blurb", ""))}</p><!--todo:{esc(pid)}--></header>{"".join(rows_html)}</section>')
        count = sum(len(r["frames"]) for r in rows_data)
        nav.append(f'<button type="button" data-goto="{esc(pid)}">{esc(title)}<small>{count}</small></button>')
        chips.append(f'<button type="button" data-goto="{esc(pid)}">{esc(title)}</button>')
        data_pages.append({"id": pid, "title": title, "rows": rows_data, "links": page.get("links", [])})
    cov = screens_mod.coverage(inventory, drawn)
    board = "".join(pages_html)
    for pid in page_titles:  # each page lists its own screens that are not drawn yet
        todo = [e for e in (cov["missing"] if cov else []) if e.get("page") == pid]
        names = ", ".join(screens_mod.label(e) for e in todo)
        board = board.replace(f"<!--todo:{esc(pid)}-->", f'<p class="cv-todo">Not drawn yet: {esc(names)}</p>' if todo else "")
    stale = screens_mod.outdated(git_frames, root) if report is not None else []
    for o in stale:
        board = board.replace(f"<!--stale:{esc(o['screen'])}-->", f'<span class="cv-stale" title="{esc(o["message"])}">May be out of date</span>')
    board = re.sub(r"<!--stale:[^>]*-->", "", board)
    if report is not None:
        report.update(coverage=cov, outdated=stale, warnings=screens_mod.size_warning(refs_bytes, asset_sizes))
    raw_comments, raw_updates = review_data or ([], [])
    dc = {"app": d.name, "built": reviews.now(), **d.inspect_data(), "rules": parse_css(app_css), "screens": screens,
          "comments": [reviews.public(c) for c in raw_comments], "updates": list(raw_updates)}
    page = page_shell(
        "canvas.html", d, web_fonts,
        TITLE=f"{esc(d.name)} screens", CSS_VARS=d.css(), CSS=css, SPRITE=d.sprite(),
        PAGES_NAV="".join(nav), PAGES_CHIPS="".join(chips), PAGES=board,
        DATA=script_json({"pages": data_pages, "refs": refs}), DC=script_json(dc),
        JS="\n".join(read(ASSETS / n) for n in ("canvas.js", "inspect.js", "review.js")),
        N_LABEL=f"{cov['drawn']} of {cov['listed']} drawn" if cov and cov["missing"] else f"{n_frames} screens",
        COVERAGE=coverage_panel(cov, page_titles),
        DEFAULT_THEME=esc(d.default), INITIAL=esc(d.name[:1].upper()),
    )
    return page, n_frames, missing, screens


# ---------------------------------------------------------------- build everything
def plain(msg: str) -> str:
    return msg.replace("`", "")


TOKEN_VAR = re.compile(r"var\(\s*(--(?:c|f|t|ls|s|r|sh|d|e|role)-[\w-]+)")
DEFINED_VAR = re.compile(r"(--[\w-]+)\s*:")


def undefined_vars(d: Design) -> list:
    """Token variables (var(--c-…), --t-…, --s-…) used in parts.css, the guide or the canvas files that
    design.json does not define. They render nothing, so each is a warning with the closest real name."""
    files = [d.dir / "parts.css"]
    for pattern in ("guides/*.md", "specimens/*.html", "canvas/css/*.css", "canvas/partials/*.html", "canvas/frames/*/*.html"):
        files += sorted(d.dir.glob(pattern))
    texts = {f: f.read_text(encoding="utf-8", errors="replace") for f in files if f.is_file()}
    defined = set(DEFINED_VAR.findall(d.css()))
    for text in texts.values():  # a file may set its own variable with a token prefix
        defined.update(DEFINED_VAR.findall(text))

    def squash(name):
        return re.sub(r"[-_]", "", name.lower())

    flat = {}
    for n in sorted(defined):
        flat.setdefault(squash(n), n)
    out = []
    for f, text in texts.items():
        seen: dict[str, list] = {}
        for i, line in enumerate(text.splitlines(), 1):
            for name in TOKEN_VAR.findall(line):
                if name not in defined:
                    seen.setdefault(name, []).append(i)
        for name, at in seen.items():
            prefix = name.split("-")[2]
            guess = flat.get(squash(name)) or next(iter(difflib.get_close_matches(
                name, [n for n in defined if n.split("-")[2:3] == [prefix]], n=1, cutoff=0.6)), None)
            times = f", used {len(at)} times" if len(at) > 1 else ""
            hint = f" (did you mean {guess}?)" if guess else ""
            out.append(f"{f.relative_to(d.dir).as_posix()}:{at[0]}: var({name}) is not defined in design.json{times}{hint}")
    return out


def build_all(d: Design, root: Path, out: Path, web: bool = True) -> tuple[dict, list]:
    """Write guide, canvas and tokens to `out`. Returns (summary for --json, text lines)."""
    raw_c, raw_u, review_files, review_errors = reviews.load_raw(d.dir)
    merged, unique_u = reviews.merge(raw_c, raw_u)
    drift_result = d.check(root) if root.is_dir() else None
    usage = d.usage(root) if root.is_dir() else None
    report: dict = {}
    canvas, n_frames, missing, _ = build_canvas(d, root, (raw_c, unique_u), web, report)
    guide, guide_missing = build_guide(d, drift_result, usage, n_frames, web, report.get("coverage"))
    out.mkdir(parents=True, exist_ok=True)
    (out / "guide.html").write_text(guide, encoding="utf-8")
    if canvas:
        (out / "canvas.html").write_text(canvas, encoding="utf-8")
    (out / "tokens.json").write_text(json.dumps(d.dtcg(), indent=2) + "\n", encoding="utf-8")
    for t in d.theme_ids[1:]:
        (out / f"tokens.{t}.json").write_text(json.dumps(d.dtcg(t), indent=2) + "\n", encoding="utf-8")
    (out / "tokens.md").write_text(d.markdown(drift_result[0] if drift_result else None), encoding="utf-8")
    drift_n = (f"{len(drift_result[0])}, without src: {len(drift_result[3])}, derived: {len(drift_result[2])} ({pct(drift_result.derived_share)})"
               if drift_result else "not run")
    c = reviews.counts(merged)
    files = ["guide.html"] + (["canvas.html"] if canvas else []) + ["tokens.json"] + [f"tokens.{t}.json" for t in d.theme_ids[1:]] + ["tokens.md"]
    lines = [f"built {out}/guide.html ({len(guide) // 1024} KB)" + (f", canvas.html ({len(canvas) // 1024} KB, {n_frames} screens)" if canvas else "")
             + f" · {d.count()} tokens · drift: {drift_n} · contrast issues: {len(d.contrast_problems())}"]
    if merged or review_errors:
        lines.append(f"reviews: {c['open']} need a fix, {c['ready'] + c['question']} to check, "
                     f"{c['resolved'] + c['wontfix']} closed, from {len(review_files)} file(s)")
    lines += [f"missing: {m}" for m in missing + guide_missing] + [f"review: {e}" for e in review_errors]
    lines += [f"CONTRAST: {plain(p)}" for p in d.contrast_problems()]
    warnings = d.warnings + undefined_vars(d)
    summary = {
        "ok": True, "out": str(out), "files": files, "screens": n_frames, "tokens": d.count(),
        "drift": [plain(p) for p in drift_result[0]] if drift_result else None,
        "unsourced": drift_result[3] if drift_result else None,
        "derived": drift_result[2] if drift_result else None,
        "derivedShare": drift_result.derived_share if drift_result else None,
        "notChecked": drift_result.not_checked if drift_result else None,
        "couldBeChecked": drift_result.could_check if drift_result else None,
        "contrastIssues": [plain(p) for p in d.contrast_problems()], "reviews": c,
        "missing": missing + guide_missing, "reviewErrors": review_errors, "warnings": warnings,
    }
    # canvas coverage (canvas/screens.json), screens that may be out of date, big embedded images
    summary.update(coverage=report.get("coverage"), outdated=report.get("outdated", []), canvasWarnings=report.get("warnings", []))
    lines[1:1] = screens_mod.coverage_lines(report.get("coverage")) + [f"warning: {o['message']}" for o in report.get("outdated", [])] \
        + [f"warning: {w}" for w in report.get("warnings", [])]
    return summary, [f"warning: {w}" for w in warnings] + lines


# ---------------------------------------------------------------- one screen as a PNG (headless Chrome)
SHOT_CSS = """
html, body { margin: 0; background: transparent; }
.sprite { position: absolute; width: 0; height: 0; overflow: hidden; }
.dev { border-radius: 0 !important; box-shadow: none !important; }
"""
MEASURE = ("<script>addEventListener('load', () => (document.fonts ? document.fonts.ready : Promise.resolve()).then(() => {"
           "document.title = 'H' + Math.ceil(document.querySelector('.dev').getBoundingClientRect().height) }))</script>")


def find_screen(d: Design, fid: str):
    """(page id, page) of the canvas page that shows screen `fid`, or (None, [every screen id])."""
    ids = []
    for pf in sorted((d.dir / "canvas" / "pages").glob("*.json")):
        try:
            page = json.loads(pf.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for row in page.get("rows", []):
            for x in row.get("frames", []):
                if x == fid:
                    return page.get("id") or re.sub(r"^\d+[-_]", "", pf.stem), page
                ids.append(x)
    return None, ids


def shoot(d: Design, fid: str, theme: str | None = None, out: Path | None = None, scale: float = 1, web: bool = True):
    """Render one screen to a PNG at its own frame size. Returns (summary for --json, text lines, exit code)."""
    def fail(msg):
        return {"ok": False, "error": msg}, [f"error: {msg}"], 2
    pid, page = find_screen(d, fid)
    if pid is None:
        close = difflib.get_close_matches(fid, page, 3)
        return fail(f"no screen '{fid}' on the canvas pages" + (f"; did you mean {', '.join(close)}?" if close else ""))
    if theme and theme not in d.theme_ids:
        return fail(f"unknown theme '{theme}'; themes: {', '.join(d.theme_ids)}")
    if not 0.5 <= scale <= 4:
        return fail("--scale must be between 0.5 and 4")
    problems: list = []
    meta, body = read_frame(d.dir / "canvas", pid, fid, d, problems, {})
    if meta is None:
        return fail(f"frames/{pid}/{fid}.html not found")
    browser = screens_mod.find_chrome()
    if not browser:
        return fail(screens_mod.no_chrome_message())
    dev, w = device(d, meta, page, body, theme)
    h = meta.get("height") or page.get("height") or d.frame["height"]
    links, faces = d.font_links()
    doc = (f'<!doctype html><html lang="en" data-theme="{esc(d.default)}"><head><meta charset="utf-8">{links if web else ""}'
           f"<style>{faces}\n{d.css()}\n{frame_css(d)}\n{SHOT_CSS}</style></head><body>{d.sprite()}{dev}{MEASURE}</body></html>")
    out = Path(out) if out else d.dir / "out" / "shots" / f"{fid}{'.' + theme if theme else ''}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    tmp = Path(tempfile.mkdtemp(prefix="design-canvas-shot-"))
    try:
        page_file = tmp / "shot.html"
        page_file.write_text(doc, encoding="utf-8")
        if str(h) == "auto":  # a full scroll capture: measure the height first
            p = screens_mod.chrome(browser, tmp / "profile", page_file, w, d.frame["height"], 1, ["--dump-dom"])
            m = re.search(r"<title>H(\d+)</title>", p.stdout or "")
            h = int(m.group(1)) if m else d.frame["height"]
        screens_mod.chrome(browser, tmp / "profile", page_file, w, int(h), scale, [f"--screenshot={out}"])
    except subprocess.TimeoutExpired:
        return fail(f"{browser} took too long to render the screen")
    except OSError as e:
        return fail(f"could not run {browser}: {e}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    size = screens_mod.png_size(out)
    if not size:
        return fail(f"{browser} did not write a PNG to {out}")
    summary = {"ok": True, "file": str(out), "screen": fid, "page": pid,
               "theme": theme or meta.get("theme") or page.get("theme") or d.default,
               "width": w, "height": int(h), "scale": scale, "pixels": list(size), "missing": problems}
    return summary, [f"missing: {m}" for m in problems] + [f"shot {out} ({size[0]} x {size[1]} px, screen '{fid}' at {scale:g}x)"], 0


# ---------------------------------------------------------------- CLI
def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to a legacy code page
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="Build a design guide + screen canvas from design.json")
    ap.add_argument("dir", help="folder that holds design.json")
    ap.add_argument("--check", action="store_true", help="drift check only; exit 1 on drift")
    ap.add_argument("--max-derived", type=float, metavar="PERCENT",
                    help="with --check: also exit 1 when more than PERCENT %% of tokens are marked derived (not checked)")
    ap.add_argument("--validate", action="store_true", help="validate design.json and canvas files only")
    ap.add_argument("--root", help="app repo root (default: app.root in design.json, else '..')")
    ap.add_argument("--out", help="output folder (default: <dir>/out); with --shoot, the PNG file (default: <dir>/out/shots/<id>.png)")
    ap.add_argument("--no-web-fonts", action="store_true", help="don't load fonts from Google Fonts (fully offline pages)")
    ap.add_argument("--reviews", action="store_true", help="list review comments that need a fix, for a coding agent")
    ap.add_argument("--resolve", metavar="ID", help="record what you did about one review comment")
    ap.add_argument("--status", default="ready", help="with --resolve: " + " | ".join(reviews.DEV_STATUSES) + " (default ready)")
    ap.add_argument("--note", default="", help="with --resolve: one line on what changed, the question, or why not")
    ap.add_argument("--as", dest="as_name", metavar="NAME", help="your name for review files (default: git user.name)")
    ap.add_argument("--serve", action="store_true", help="run the local review helper (this computer only)")
    ap.add_argument("--port", type=int, default=8765, help="with --serve: port on 127.0.0.1 (default 8765)")
    ap.add_argument("--shoot", metavar="SCREEN", help="render one screen to a PNG with headless Chrome (CHROME_PATH or a standard install)")
    ap.add_argument("--theme", help="with --shoot: the theme id to render in (default: the screen's own)")
    ap.add_argument("--scale", type=float, default=1, help="with --shoot: pixels per point, e.g. 3 to match a 3x phone screenshot (default 1)")
    ap.add_argument("--json", action="store_true", help="print machine-readable JSON instead of text")
    a = ap.parse_args(argv)
    if a.max_derived is not None and (not a.check or not 0 <= a.max_derived <= 100):
        ap.error("--max-derived takes a percent from 0 to 100 and works with --check")

    def emit(obj, text_lines, code):
        if a.json:
            print(json.dumps(obj, indent=2, ensure_ascii=False))
        else:
            for ln in text_lines:
                print(ln)
        return code

    d = Design(Path(a.dir))
    root = Path(a.root).resolve() if a.root else d.root
    if d.errors:
        return emit({"ok": False, "errors": d.errors, "warnings": d.warnings},
                    [f"warning: {w}" for w in d.warnings] + [f"error: {e}" for e in d.errors] + [f"design.json: {len(d.errors)} error(s)"], 1)
    if a.check:
        if not root.is_dir():
            return emit({"ok": False, "error": f"app root not found: {root}"}, [f"app root not found: {root}"], 2)
        result = d.check(root)
        problems, ok, skipped, unsourced = result
        share = result.derived_share
        over = a.max_derived is not None and share * 100 > a.max_derived
        lines = [f"DRIFT: {plain(p)}" for p in problems] + [f"NO SRC: {u} (add a src, or mark it derived)" for u in unsourced]
        if over:
            lines.append(f"DERIVED: {pct(share)} of tokens are derived, over --max-derived {num(a.max_derived)}%. "
                         "Point their src at the line that defines them; keep derived for values the code computes")
        if result.not_checked:
            lines.append("not checked: " + ", ".join(result.not_checked))
        if result.could_check:
            lines.append("could be checked: " + ", ".join(result.could_check))
        lines.append(f"drift check: {ok} ok, {len(problems)} drifted, {len(unsourced)} without src, {len(skipped)} derived ({pct(share)} not checked)"
                     + (f", {len(result.not_checked)} field(s) not checked" if result.not_checked else ""))
        summary = {"ok": not problems and not unsourced and not over, "checked": ok, "drift": [plain(p) for p in problems],
                   "unsourced": unsourced, "derived": skipped, "derivedShare": share, "notChecked": result.not_checked,
                   "couldBeChecked": result.could_check}
        if a.max_derived is not None:
            summary["maxDerived"] = a.max_derived
            summary["overMaxDerived"] = over
        return emit(summary, lines, 1 if problems or unsourced or over else 0)
    if a.resolve:
        try:
            me = reviews.identity(d.dir, a.as_name)
            msg = reviews.resolve(d.dir, a.resolve, a.status, a.note, me, via="mcp" if os.environ.get("DESIGN_CANVAS_VIA") == "mcp" else "cli")
        except reviews.ReviewError as e:
            return emit({"ok": False, "error": str(e)}, [f"error: {e}"], 2)
        return emit({"ok": True, "result": msg}, [msg], 0)
    if a.serve:
        import serve
        return serve.run(d, root, a.port, not a.no_web_fonts, a.as_name, build_all, script_json)
    if a.shoot:
        return emit(*shoot(d, a.shoot, a.theme, Path(a.out).resolve() if a.out else None, a.scale, not a.no_web_fonts))
    comments, review_files, review_errors = reviews.load(d.dir)
    if a.reviews:
        _, _, _, screens = build_canvas(d, root)
        if a.json:
            return emit(reviews.report_json(comments, screens, d.known_tokens(), review_files, review_errors), [], 0)
        print(reviews.report(comments, screens, d.known_tokens(), review_files, review_errors))
        return 0
    if a.validate:
        _, _, missing, _ = build_canvas(d, root)
        summary = f"design.json ok ({d.count()} tokens, {len(d.themes)} theme(s), {len(d.icons.get('items') or {})} icons)"
        warnings, contrast = d.warnings + undefined_vars(d), [plain(p) for p in d.contrast_problems()]
        return emit({"ok": not missing, "tokens": d.count(), "themes": len(d.themes), "icons": len(d.icons.get("items") or {}),
                     "missing": missing, "reviewErrors": review_errors, "warnings": warnings, "contrastIssues": contrast},
                    [f"warning: {w}" for w in warnings] + [f"review: {e}" for e in review_errors] + [f"missing: {m}" for m in missing]
                    + [f"CONTRAST: {p}" for p in contrast] + [summary],
                    1 if missing else 0)
    out = Path(a.out).resolve() if a.out else d.dir / "out"
    summary, lines = build_all(d, root, out, not a.no_web_fonts)
    return emit(summary, lines, 0)


if __name__ == "__main__":
    sys.exit(main())

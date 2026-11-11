#!/usr/bin/env python3
"""design-canvas: build a living design guide and a screen canvas from design.json.

  python3 engine/build.py <design-dir>              build out/guide.html, out/canvas.html, out/tokens.*
  python3 engine/build.py <design-dir> --check      drift check: exit 1 if a token no longer matches its source
  python3 engine/build.py <design-dir> --validate   check design.json and the canvas files only

<design-dir> holds design.json and, optionally:
  guides/*.md                    chapters (see engine/markdown.py for the syntax)
  specimens/*.html               specimen snippets used by `::: specimen <name>`
  parts.css                      the app's component styles for specimens and screens
  canvas/pages/*.json            board pages, canvas/frames/<page>/<frame>.html screens,
  canvas/css/*.css, canvas/partials/*.html

Python 3.9+ standard library only.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import reviews  # noqa: E402
from markdown import Doc, front_matter, slug  # noqa: E402
from tokens import Design, esc, kebab, num, to_hex  # noqa: E402

ASSETS = HERE / "assets"
PART_WORDS = re.compile(r"atom|molecule|organism|template|page|component|pattern", re.I)


# ---------------------------------------------------------------- token views
def swatch_cell(rgba) -> str:
    return f"rgba({rgba[0]},{rgba[1]},{rgba[2]},{num(rgba[3])})"


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
            bg_like = k in {d.roles.get(r) for r in ("background", "surface", "surface2", "scrim", "border")} or "background" in (c.get("group") or "").lower()
            ratios = {} if bg_like else d.ratios(k)
            per = ""
            if multi:
                per = '<span class="per">' + "".join(
                    f'<i title="{esc(t)}: {esc(c["values"][t])}" style="background:{swatch_cell(c["rgba"][t])}"></i>' for t in d.theme_ids) + "</span>"
            vals = " · ".join(f"{esc(t)} {esc(c['values'][t])}" for t in d.theme_ids) if multi else esc(c["values"][d.default])
            rat = " · ".join(f"{r}:1" + (f" {esc(t)}" if multi else "") for t, r in ratios.items())
            warn = d.is_texty(k) and any(r < 4.5 for r in ratios.values())
            cells.append(
                f'<figure class="swatch"><div class="chip" style="background:var(--c-{kebab(k)})">{per}</div>'
                f'<figcaption><b>{esc(k)}</b><code>{vals}</code>'
                + (f'<code class="code">{esc(c["code"])}</code>' if c.get("code") else "")
                + (f'<span class="ratio{" low" if warn else ""}">{rat} on {esc(d.partner(k))}</span>' if rat else "")
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
        rows.append(
            f'<div class="type-row"><div class="type-meta"><b>{esc(k)}</b>'
            f'<code>{num(v["size"])}/{num(d.line_height(v))} · {f.get("weight", 400)}{" italic" if f.get("style") == "italic" else ""}'
            f'{" · " + num(v["letterSpacing"]) + " ls" if v.get("letterSpacing") else ""}</code>'
            + (f'<code class="code">{esc(v["code"])}</code>' if v.get("code") else "")
            + (f'<span class="doc">{esc(v["doc"])}</span>' if v.get("doc") else "")
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
        f'<span class="doc">{esc(v.get("doc", ""))}</span></div>' for k, v in d.spacing.items())
    return f'<div class="spaces">{bars}</div>' if bars else '<p class="note">No spacing tokens.</p>'


def view_radii(d: Design) -> str:
    cells = "".join(
        f'<figure class="radius"><div class="rbox" style="border-radius:{min(v["value"], 60)}px"></div>'
        f'<figcaption><b>{esc(k)}</b><code>{num(v["value"])}px</code><span class="doc">{esc(v.get("doc", ""))}</span></figcaption></figure>'
        for k, v in d.radii.items())
    return f'<div class="radii">{cells}</div>' if cells else '<p class="note">No radius tokens.</p>'


def view_shadows(d: Design) -> str:
    cells = "".join(
        f'<figure class="shadow"><div class="sbox" style="box-shadow:var(--sh-{kebab(k)})"></div>'
        f'<figcaption><b>{esc(k)}</b><code>{num(v.get("x", 0))} {num(v.get("y", 0))} {num(v.get("blur", 0))} {num(v.get("spread", 0))} · {d.shadow_rgba(v)}'
        f'{" · elev " + num(v["elevation"]) if "elevation" in v else ""}</code><span class="doc">{esc(v.get("doc", ""))}</span></figcaption></figure>'
        for k, v in d.shadows.items())
    return f'<div class="shadows">{cells}</div>' if cells else '<p class="note">No shadow tokens.</p>'


def view_motion(d: Design) -> str:
    rows = "".join(
        f'<div class="motion-row"><code>{esc(k)}</code><span class="track"><span class="dot" style="animation-duration:{num(v["value"] * 4)}ms"></span></span>'
        f'<code>{num(v["value"])} ms</code><span class="doc">{esc(v.get("doc", ""))}</span></div>' for k, v in d.durations.items())
    rows += "".join(
        f'<div class="motion-row"><code>{esc(k)}</code><span class="track"><span class="dot" style="animation-duration:1600ms;animation-timing-function:{esc(v["value"])}"></span></span>'
        f'<code>easing</code><span class="doc">{esc(v["value"])} {esc(v.get("doc", ""))}</span></div>' for k, v in d.easings.items())
    rows += "".join(
        f'<div class="motion-row"><code>{esc(k)}</code><code>' + " · ".join(f"{x} {num(v[x])}" for x in ("damping", "stiffness", "mass") if x in v)
        + f'</code><code>spring</code><span class="doc">{esc(v.get("doc", ""))}</span></div>' for k, v in d.springs.items())
    if not rows:
        return '<p class="note">No motion tokens.</p>'
    return f'<div class="motion">{rows}</div><p class="note">Duration dots run at 4× the token so the difference is visible.</p>'


def view_icons(d: Design) -> str:
    items = d.icons.get("items") or {}
    cells = "".join(
        f'<figure class="icon"><svg class="ic" aria-hidden="true"><use href="#i-{esc(k)}"/></svg><figcaption>{esc(k)}'
        f'{"<code>" + esc(v["source"]) + "</code>" if v.get("source") else ""}</figcaption></figure>' for k, v in items.items())
    return f'<div class="icons">{cells}</div>' if cells else '<p class="note">No icons.</p>'


def view_contrast(d: Design) -> str:
    probs = d.contrast_problems()
    if not probs:
        return '<p class="ok">Every text colour reaches 4.5:1 on the colour it is read on, in every theme.</p>'
    return '<ul class="drift">' + "".join(f"<li>{inline_code(p)}</li>" for p in probs) + "</ul>"


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
    if skipped:
        body += '<p class="note">Derived in code, so not checked: ' + "; ".join(esc(s) for s in skipped) + "</p>"
    return head + body


def lineage_html(usage, name: str) -> str:
    if usage is None:
        return '<p class="lineage none">Usage not scanned (app code not found).</p>'
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
ICON_MACRO = re.compile(r"\{\{icon:([\w-]+)(?::(\d+))?\}\}")


def expand_icons(s: str) -> str:
    def sub(m):
        size = f' style="width:{m.group(2)}px;height:{m.group(2)}px"' if m.group(2) else ""
        return f'<svg class="ic" aria-hidden="true"{size}><use href="#i-{m.group(1)}"/></svg>'
    return ICON_MACRO.sub(sub, s)


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.exists() else ""


def script_json(obj) -> str:
    """JSON that is safe inside a <script> element: no '<' can close it or open a comment."""
    return json.dumps(obj, ensure_ascii=False).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def parse_css(text: str, media: str | None = None) -> list:
    """Split simple CSS into [{s: selector, m: media, d: [[prop, value, important]]}] for the inspect panel."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    out, i, n = [], 0, len(text)
    while i < n:
        j = text.find("{", i)
        if j < 0:
            break
        prelude = text[i:j].strip()
        depth, k = 1, j + 1
        while k < n and depth:
            depth += {"{": 1, "}": -1}.get(text[k], 0)
            k += 1
        body = text[j + 1:k - 1]
        if prelude.startswith("@media"):
            out += parse_css(body, prelude[6:].strip())
        elif prelude and not prelude.startswith("@"):
            decls = []
            for part in re.split(r";(?![^(]*\))", body):
                if ":" not in part:
                    continue
                prop, val = part.split(":", 1)
                val = val.strip()
                imp = val.endswith("!important")
                decls.append([prop.strip().lower(), val[:-10].strip() if imp else val, imp])
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
    if len(d.themes) < 2:
        return ""
    return '<div class="themes" role="group" aria-label="Theme">' + "".join(
        f'<button type="button" data-set-theme="{esc(t["id"])}" data-scheme="{esc(t["scheme"])}">{esc(t["label"])}</button>' for t in d.themes) + "</div>"


# ---------------------------------------------------------------- guide
def build_guide(d: Design, drift_result, usage, n_screens: int, web_fonts: bool = True):
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
    if n_screens:
        ladder.append(("canvas.html", "Screens", n_screens))
    groups: dict[str, list] = {}
    for g, sid, label, n in nav:
        groups.setdefault(g, []).append((sid, label, n))
    nav_html = "".join(
        f'<div class="nav-group"><span class="nav-label">{esc(g)}</span>'
        + "".join(f'<a href="#{sid}">{esc(label)}{f" <small>{n}</small>" if n else ""}</a>' for sid, label, n in items)
        + "</div>" for g, items in groups.items())
    if n_screens:
        nav_html += f'<div class="nav-group"><span class="nav-label">Canvas</span><a href="canvas.html">All screens <small>{n_screens}</small></a></div>'
    ladder_html = "".join(f'<li><a href="{"#" + h if not h.endswith(".html") else h}"><b>{n}</b><span>{esc(lbl)}</span></a></li>' for h, lbl, n in ladder)
    page = page_shell(
        "guide.html", d, web_fonts,
        TITLE=f"{esc(d.name)} design guide",
        DESCRIPTION=esc(d.app.get("description", f"The {d.name} design system, read from the code.")),
        CSS_VARS=d.css(), CSS=read(ASSETS / "guide.css") + "\n" + d.icon_css() + "\n" + read(d.dir / "parts.css"),
        JS=read(ASSETS / "guide.js"), NAV=nav_html, SPRITE=d.sprite(), SECTIONS=expand_icons("\n".join(sections)),
        LADDER=ladder_html, LADDER_N=str(len(ladder)), THEMES=theme_buttons(d), LEDE=esc(d.app.get("description", "")),
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


def read_frame(cdir: Path, page: str, fid: str):
    f = cdir / "frames" / page / f"{fid}.html"
    if not f.exists():
        return None, f'<div class="missing">missing frames/{esc(page)}/{esc(fid)}.html</div>'
    text = f.read_text(encoding="utf-8")
    meta = front_matter(text)
    text = re.sub(r"^\s*<!--.*?-->", "", text, count=1, flags=re.S)
    text = expand_icons(expand_partials(text, cdir / "partials"))
    return meta, text


def device(d: Design, meta: dict, page: dict, body: str) -> tuple[str, int]:
    kind = meta.get("device") or page.get("device") or d.frame["device"]
    w = int(meta.get("width") or page.get("width") or d.frame["width"])
    h = meta.get("height") or page.get("height") or d.frame["height"]
    tall = str(h) == "auto"
    theme = meta.get("theme") or page.get("theme")
    attrs = f' data-theme="{esc(theme)}"' if theme else ""
    style = f'width:{w}px;{"min-height" if tall else "height"}:{d.frame["height"] if tall else int(h)}px'
    if kind == "phone":
        inner = f'{STATUS}<div class="dev-island"></div><div class="sc">{body}</div><div class="dev-home"></div>'
    elif kind == "browser":
        inner = f'<div class="dev-bar"><i></i><i></i><i></i><span>{esc(meta.get("url", ""))}</span></div><div class="sc">{body}</div>'
    else:
        inner = f'<div class="sc">{body}</div>'
    return f'<div class="dev dev-{kind}{" tall" if tall else ""}"{attrs} style="{style}">{inner}</div>', w


def build_canvas(d: Design, root: Path | None = None, comments=None, web_fonts: bool = True):
    """Returns (html or None, number of screens, problems, screens {id: {title, page, source}})."""
    cdir = d.dir / "canvas"
    pages = sorted((cdir / "pages").glob("*.json"))
    if not pages:
        return None, 0, [], {}
    root = Path(root or d.root)
    app_css = "\n".join([read(ASSETS / "frame.css"), d.icon_css(), read(d.dir / "parts.css"),
                         *[read(p) for p in sorted((cdir / "css").glob("*.css"))]])
    css = "\n".join([read(ASSETS / "canvas.css"), app_css, read(ASSETS / "review.css")])
    pages_html, nav, chips, data_pages, missing = [], [], [], [], []
    screens: dict[str, dict] = {}
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
                meta, body = read_frame(cdir, pid, fid)
                if meta is None:
                    missing.append(f"frames/{pid}/{fid}.html")
                    meta = {"title": fid, "state": "missing"}
                src = meta.get("source") or None
                if src and not reviews.safe_rel(root, src):
                    missing.append(f"frames/{pid}/{fid}.html: source must be a relative path inside the app root ({root})")
                    src = None
                elif src and root.is_dir() and not (root / src).exists():
                    missing.append(f"frames/{pid}/{fid}.html: source {src} not found under the app root")
                if fid in screens:
                    missing.append(f"screen id '{fid}' is used on two pages; comments can't tell them apart")
                screens[fid] = {"title": meta.get("title", fid), "state": meta.get("state", "Default"), "page": pid, "source": src}
                dev, w = device(d, meta, page, body)
                state = meta.get("state", "Default")
                note = meta.get("note", "")
                frames_html.append(
                    f'<figure class="cv-frame" data-id="{esc(fid)}" style="width:{w}px">'
                    f'<figcaption class="cv-label"><b>{esc(meta.get("title", fid))}</b>'
                    f'<span class="st{" default" if state.lower() == "default" else ""}">{esc(state)}</span>'
                    + (f'<code>{esc(meta["source"])}</code>' if meta.get("source") else "")
                    + f"</figcaption>{dev}" + (f'<p class="note">{esc(note)}</p>' if note else "") + "</figure>")
                frames_data.append({"id": fid, "title": meta.get("title", fid), "state": state})
            n_frames += len(frames_data)
            rows_html.append(
                f'<div class="cv-row"{" data-flow" if row.get("flow") else ""}><div class="cv-row-head"><h2>{esc(row.get("title", ""))}</h2>'
                + (f'<p>{esc(row["note"])}</p>' if row.get("note") else "") + f'</div><div class="cv-row-frames">{"".join(frames_html)}</div></div>')
            rows_data.append({"title": row.get("title", ""), "frames": frames_data})
        title = page.get("title", pid)
        pages_html.append(
            f'<section class="cv-page" data-page="{esc(pid)}" hidden><header class="cv-head"><span class="eyebrow">Page {esc(page.get("order", len(pages_html) + 1))}</span>'
            f'<h1>{esc(title)}</h1><p>{esc(page.get("blurb", ""))}</p></header>{"".join(rows_html)}</section>')
        count = sum(len(r["frames"]) for r in rows_data)
        nav.append(f'<button type="button" data-goto="{esc(pid)}">{esc(title)}<small>{count}</small></button>')
        chips.append(f'<button type="button" data-goto="{esc(pid)}">{esc(title)}</button>')
        data_pages.append({"id": pid, "title": title, "rows": rows_data, "links": page.get("links", [])})
    dc = {"app": d.name, "built": reviews.now(), **d.inspect_data(), "rules": parse_css(app_css),
          "screens": screens, "comments": [reviews.public(c) for c in (comments or [])]}
    page = page_shell(
        "canvas.html", d, web_fonts,
        TITLE=f"{esc(d.name)} screens", CSS_VARS=d.css(), CSS=css, SPRITE=d.sprite(),
        PAGES_NAV="".join(nav), PAGES_CHIPS="".join(chips), PAGES="".join(pages_html),
        DATA=script_json({"pages": data_pages}), DC=script_json(dc),
        JS=read(ASSETS / "canvas.js") + "\n" + read(ASSETS / "review.js"), N_FRAMES=str(n_frames),
        DEFAULT_THEME=esc(d.default), INITIAL=esc(d.name[:1].upper()),
    )
    return page, n_frames, missing, screens


# ---------------------------------------------------------------- CLI
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build a design guide + screen canvas from design.json")
    ap.add_argument("dir", help="folder that holds design.json")
    ap.add_argument("--check", action="store_true", help="drift check only; exit 1 on drift")
    ap.add_argument("--validate", action="store_true", help="validate design.json and canvas files only")
    ap.add_argument("--root", help="app repo root (default: app.root in design.json, else '..')")
    ap.add_argument("--out", help="output folder (default: <dir>/out)")
    ap.add_argument("--no-web-fonts", action="store_true", help="don't load fonts from Google Fonts (fully offline pages)")
    ap.add_argument("--reviews", action="store_true", help="list open review comments for a coding agent")
    ap.add_argument("--resolve", metavar="ID", help="set the status of one review comment")
    ap.add_argument("--status", default="resolved", help="with --resolve: " + " | ".join(reviews.STATUSES))
    ap.add_argument("--note", default="", help="with --resolve: one line on what changed (or why not)")
    a = ap.parse_args(argv)
    d = Design(Path(a.dir))
    root = Path(a.root).resolve() if a.root else d.root
    for w in d.warnings:
        print("warning:", w)
    if d.errors:
        for e in d.errors:
            print("error:", e)
        print(f"design.json: {len(d.errors)} error(s)")
        return 1
    if a.check:
        if not root.is_dir():
            print(f"app root not found: {root}")
            return 2
        problems, ok, skipped, unsourced = d.check(root)
        for p in problems:
            print("DRIFT:", p.replace("`", ""))
        for u in unsourced:
            print("NO SRC:", u, "(add a src, or mark it derived)")
        print(f"drift check: {ok} ok, {len(problems)} drifted, {len(unsourced)} without src, {len(skipped)} derived (not checkable)")
        return 1 if problems or unsourced else 0
    if a.resolve:
        print(reviews.resolve(d.dir, a.resolve, a.status, a.note))
        return 0
    comments, review_files, review_errors = reviews.load(d.dir)
    if a.reviews:
        _, _, _, screens = build_canvas(d, root)
        print(reviews.report(comments, screens, d.known_tokens(), review_files, review_errors))
        return 0
    if a.validate:
        _, _, missing, _ = build_canvas(d, root, comments)
        for e in review_errors:
            print("review:", e)
        for m in missing:
            print("missing:", m)
        print(f"design.json ok ({d.count()} tokens, {len(d.themes)} theme(s), {len(d.icons.get('items') or {})} icons)")
        return 1 if missing else 0
    drift_result = d.check(root) if root.is_dir() else None
    usage = d.usage(root) if root.is_dir() else None
    web = not a.no_web_fonts
    canvas, n_frames, missing, _ = build_canvas(d, root, comments, web)
    guide, guide_missing = build_guide(d, drift_result, usage, n_frames, web)
    out = Path(a.out).resolve() if a.out else d.dir / "out"
    out.mkdir(parents=True, exist_ok=True)
    (out / "guide.html").write_text(guide, encoding="utf-8")
    if canvas:
        (out / "canvas.html").write_text(canvas, encoding="utf-8")
    (out / "tokens.json").write_text(json.dumps(d.dtcg(), indent=2) + "\n", encoding="utf-8")
    for t in d.theme_ids[1:]:
        (out / f"tokens.{t}.json").write_text(json.dumps(d.dtcg(t), indent=2) + "\n", encoding="utf-8")
    (out / "tokens.md").write_text(d.markdown(drift_result[0] if drift_result else None), encoding="utf-8")
    drift_n = f"{len(drift_result[0])}, without src: {len(drift_result[3])}" if drift_result else "not run"
    print(f"built {out}/guide.html ({len(guide) // 1024} KB)" + (f", canvas.html ({len(canvas) // 1024} KB, {n_frames} screens)" if canvas else "")
          + f" · {d.count()} tokens · drift: {drift_n} · contrast issues: {len(d.contrast_problems())}")
    if comments or review_errors:
        c = reviews.counts(comments)
        print(f"reviews: {c['open'] + c['question'] + c['reopened']} open, {c['resolved'] + c['wontfix']} closed, from {len(review_files)} file(s)")
    for m in missing + guide_missing:
        print("missing:", m)
    for e in review_errors:
        print("review:", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())

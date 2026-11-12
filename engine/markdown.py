"""The small Markdown dialect the guide chapters are written in.

Plain Markdown (headings, paragraphs, lists, tables, code, quotes, links,
bold/italic) plus three blocks:

  ::: specimen            raw HTML drawn on a stage (ends with a line ':::')
  ::: specimen <name>     the file specimens/<name>.html
  ::: tokens <view>       a generated view: colors, type, fonts, spacing, radii,
                          shadows, motion, icons, roles, contrast, drift
  ::: lineage <Name>      the files that import component <Name>

In "parts" chapters every `### Name [level]` heading opens a part card: the
specimens go on the left, the rest of the section on the right.

Specimens and HTML lines can use the canvas shortcuts: `{{icon:name}}` and
`{{> partial key=value}}` (a file in canvas/partials/). A partial in a code
sample or a sentence stays as text.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

LEVELS = ("atom", "molecule", "organism", "template", "page", "component", "pattern", "utility")
TAG = re.compile(r"</?[a-zA-Z][^>]*>")


def inline(s: str) -> str:
    codes: list[str] = []

    def keep_code(m):
        codes.append(f"<code>{html.escape(m.group(1))}</code>")
        return f"\x00{len(codes) - 1}\x00"

    s = re.sub(r"`([^`]+)`", keep_code, s)
    tags: list[str] = []

    def keep_tag(m):
        tags.append(m.group(0))
        return f"\x01{len(tags) - 1}\x01"

    s = TAG.sub(keep_tag, s)
    s = html.escape(s, quote=False)
    s = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", lambda m: f'<a href="{html.escape(m.group(2))}">{m.group(1)}</a>', s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\w*])\*([^*\s][^*]*?)\*(?![\w*])", r"<em>\1</em>", s)
    s = re.sub(r"(?<![\w_])_([^_\s][^_]*?)_(?![\w_])", r"<em>\1</em>", s)
    s = re.sub(r"\x01(\d+)\x01", lambda m: tags[int(m.group(1))], s)
    s = re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], s)
    return s


def plain(s: str) -> str:
    return re.sub(r"<[^>]+>|[*`_]", "", s)


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", plain(s).lower()).strip("-")


def render_list(items: list[tuple[int, bool, str]]) -> str:
    base = items[0][0]
    out: list[str] = []
    stack: list[str] = []
    for ind, numbered, txt in items:
        depth = 0 if ind <= base else 1
        tag = "ol" if numbered else "ul"
        while len(stack) > depth + 1:
            out.append(f"</li></{stack.pop()}>")
        if len(stack) < depth + 1:
            out.append(f"<{tag}>")
            stack.append(tag)
        else:
            out.append("</li>")
        out.append(f"<li>{inline(txt)}")
    while stack:
        out.append(f"</li></{stack.pop()}>")
    return "".join(out)


class Doc:
    def __init__(self, views, lineage, specimens_dir: Path):
        """views: name -> html; lineage: callable(name) -> html."""
        self.views = views
        self.lineage = lineage
        self.specimens = specimens_dir
        self.toc: list[tuple[int, str, str]] = []
        self.ids: set[str] = set()
        self.missing: list[str] = []

    def uid(self, base: str) -> str:
        hid, n = base or "section", 2
        while hid in self.ids:
            hid, n = f"{base}-{n}", n + 1
        self.ids.add(hid)
        return hid

    def render(self, md: str, parts: bool) -> str:
        lines = md.split("\n")
        out: list[str] = []
        state = {"in_part": False, "spec": [], "body": []}

        def emit(x: str):
            (state["body"] if state["in_part"] else out).append(x)

        def stage(x: str):
            (state["spec"] if state["in_part"] else out).append(x)

        def close_part():
            if state["in_part"]:
                specimen = "".join(state["spec"]) or '<div class="stage empty"><span>No visual: behaviour only</span></div>'
                out.append(f'<div class="part-visual">{specimen}</div><div class="part-spec">{"".join(state["body"])}</div></article>')
            state.update(in_part=False, spec=[], body=[])

        i = 0
        while i < len(lines):
            ln = lines[i]
            if not ln.strip() or re.match(r"^\s*<!--.*-->\s*$", ln):
                i += 1
                continue
            if ln.lstrip().startswith("<!--"):
                while i < len(lines) and "-->" not in lines[i]:
                    i += 1
                i += 1
                continue
            m = re.match(r"^(#{1,4})\s+(.*?)\s*(\{#([\w-]+)\})?\s*$", ln)
            if m:
                level, text = len(m.group(1)), m.group(2)
                if parts and level <= 3:
                    close_part()
                if parts and level == 3:
                    lv = re.search(r"\[(" + "|".join(LEVELS) + r")\]", text)
                    badge = ""
                    if lv:
                        text = text.replace(lv.group(0), "").strip()
                        badge = f'<span class="lvl lvl-{lv.group(1)}">{lv.group(1)}</span>'
                    hid = self.uid(m.group(4) or slug(text))
                    out.append(f'<article class="part" id="{hid}"><header class="part-head"><h3>{inline(text)}</h3>{badge}</header>')
                    state["in_part"] = True
                    self.toc.append((3, hid, plain(text)))
                else:
                    hid = self.uid(m.group(4) or slug(text))
                    emit(f'<h{level} id="{hid}">{inline(text)}</h{level}>')
                    if level <= 2:
                        self.toc.append((level, hid, plain(text)))
                i += 1
                continue
            if re.match(r"^:::\s*specimen\s*$", ln):
                j = i + 1
                while j < len(lines) and not re.match(r"^:::\s*$", lines[j]):
                    j += 1
                stage("\n".join(lines[i + 1: j]))
                i = j + 1
                continue
            m = re.match(r"^:::\s*(specimen|tokens|lineage)\s+(\S+)", ln)
            if m:
                kind, arg = m.groups()
                if kind == "lineage":
                    emit(self.lineage(arg))
                elif kind == "specimen":
                    f = self.specimens / f"{arg}.html"
                    if f.exists():
                        stage(f.read_text(encoding="utf-8"))
                    else:
                        self.missing.append(f"specimens/{arg}.html")
                        stage(f'<div class="stage empty"><span>missing specimen {html.escape(arg)}</span></div>')
                else:
                    if arg not in self.views:
                        self.missing.append(f"tokens view '{arg}'")
                    emit(self.views.get(arg, f'<p class="flag">unknown tokens view {html.escape(arg)}</p>'))
                i += 1
                continue
            if ln.startswith("```"):
                j = i + 1
                while j < len(lines) and not lines[j].startswith("```"):
                    j += 1
                emit("<pre><code>" + html.escape("\n".join(lines[i + 1: j])) + "</code></pre>")
                i = j + 1
                continue
            if re.match(r"^\s*\|", ln) and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{3,}", lines[i + 1]):
                head = [c.strip() for c in ln.strip().strip("|").split("|")]
                j, rows = i + 2, []
                while j < len(lines) and lines[j].strip().startswith("|"):
                    rows.append([c.strip() for c in lines[j].strip().strip("|").split("|")])
                    j += 1
                t = "<thead><tr>" + "".join(f"<th>{inline(h)}</th>" for h in head) + "</tr></thead><tbody>"
                t += "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in rows) + "</tbody>"
                emit(f'<div class="table"><table>{t}</table></div>')
                i = j
                continue
            if ln.startswith(">"):
                j, buf = i, []
                while j < len(lines) and lines[j].startswith(">"):
                    buf.append(lines[j][1:].strip())
                    j += 1
                txt = " ".join(buf)
                cls = "callout decision" if re.match(r"\*\*(Decision|Rule|Do)\b", txt) else "callout"
                emit(f'<aside class="{cls}"><p>{inline(txt)}</p></aside>')
                i = j
                continue
            if re.match(r"^---+\s*$", ln):
                emit("<hr>")
                i += 1
                continue
            if re.match(r"^\s*([-*]|\d+\.)\s+", ln):
                j, items = i, []
                while j < len(lines) and lines[j].strip():
                    mm = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)", lines[j])
                    if mm:
                        items.append((len(mm.group(1)), mm.group(2)[0].isdigit(), mm.group(3)))
                    elif items:
                        ind, numbered, txt = items[-1]
                        items[-1] = (ind, numbered, txt + " " + lines[j].strip())
                    j += 1
                emit(render_list(items))
                i = j
                continue
            if ln.lstrip().startswith(("<", "{{>")):
                j, buf = i, []
                while j < len(lines) and lines[j].strip():
                    buf.append(lines[j])
                    j += 1
                emit("\n".join(buf))
                i = j
                continue
            j, buf = i, []
            while j < len(lines) and lines[j].strip() and not re.match(r"^(#{1,4}\s|:::|```|>|\s*([-*]|\d+\.)\s|\s*\|)", lines[j]):
                buf.append(lines[j].strip())
                j += 1
            emit(f"<p>{inline(' '.join(buf))}</p>")
            i = j
        close_part()
        return "\n".join(out)


def front_matter(md: str) -> dict:
    """Optional '<!-- key: value -->' block at the top of a chapter."""
    m = re.match(r"\s*<!--(.*?)-->", md, re.S)
    meta = {}
    if m:
        for line in m.group(1).strip().splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip().lower()] = v.strip()
    return meta

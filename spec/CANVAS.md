# Canvas: how to draw a screen

The canvas puts every screen of an app on one pan-and-zoom board, grouped into pages (one per app area). Each screen sits in a device frame and is drawn in plain HTML and CSS with the app's own tokens. `python3 engine/build.py <design-dir>` builds `out/canvas.html`.

## Files

| File | What it is |
| --- | --- |
| `canvas/pages/NN-<page>.json` | One board page: title, blurb, rows of screen ids, optional links. |
| `canvas/frames/<page>/<screen>.html` | One screen: only the markup **inside** the device. |
| `canvas/css/<page>.css` | Styles for that page's screens. Class prefix `<page>-`. |
| `canvas/partials/<name>.html` | Pieces shared by many screens (tab bar, header). |
| `parts.css` | The app's component styles, shared with the guide's specimens. Reuse them. |
| `engine/assets/frame.css` | Device chrome and the `sc-*` layout helpers (read it). |

## Page JSON

```json
{
  "id": "today",
  "order": 1,
  "title": "Today",
  "blurb": "One sentence on what this area of the app is.",
  "theme": "light",
  "rows": [
    { "title": "Check off habits", "note": "optional", "flow": true, "frames": ["today", "today-done"] }
  ],
  "links": [["today", "add-habit", "+ New"]]
}
```

- `flow: true` draws arrows between neighbouring screens in the row.
- `links` draws a dashed arrow between any two screens, with an optional label.
- `theme` (optional) sets the theme for the whole page. A screen can override it.

## Screen file

```html
<!--
title: Today
state: Default
source: src/screens/TodayScreen.tsx
theme: dark
height: 844
note: Optional sentence shown under the screen.
-->
<div class="sc-body sc-pad">…</div>
{{> tabbar active=today}}
```

| Field | Meaning |
| --- | --- |
| `title` | The screen's name. |
| `state` | `Default` for the normal filled screen; otherwise name it: `Loading`, `Empty`, `Error`, `Sheet open`, … |
| `source` | The file that renders it, as a path from the app root (the same root as `src` in design.json). Review comments use it to find the code to change. |
| `theme` | Optional; a theme id from design.json. |
| `device`, `width`, `height` | Optional overrides of `app.frame`. `height: auto` shows a full scroll capture. |
| `url` | For `browser` frames: the address shown in the window bar. |

Give every element a designer might comment on a stable id: `data-dc="habit-1"`, unique within the screen (`header`, `primary-button`, `habit-1`, `tabbar`…). Keep the same id when you redraw the screen, so review comments stay pinned to the right element.

Shortcuts inside a screen:
- `{{icon:name}}` or `{{icon:name:20}}` draws an icon from design.json at an optional size.
- `{{> partial key=value}}` inserts `canvas/partials/partial.html`, with every `{{key}}` in it replaced. A tab bar marks its active tab with `data-active="{{active}}"`; style it in `parts.css`.

## Helpers (engine/assets/frame.css)

- Layout: `sc-body` (the scrolling area), `sc-pad` (screen gutter), `sc-safe` (bottom safe area), `sc-row`, `sc-col`, `sc-grow`, `sc-center`, `sc-hr`, `sc-trunc`, `sc-spinner`.
- Overlays: draw the screen underneath inside `sc-under`, then `sc-scrim`, then a `sc-sheet` (with `sc-handle`) or a dialog inside `sc-dialog-wrap`. iOS page-sheet modals: `sc-modal` > `sc-modal-card`.
- Placeholders: `ph-photo`, `ph-image`, `ph-thumb`, `ph-avatar`. They are abstract on purpose.

## Rules

1. **Read the real screen code first**: the screen file and every component it renders. Draw what the code draws: the order of regions, sizes converted to px (Tailwind `p-4` = 16 px; React Native numbers are already px), the variants and props passed, icon names and sizes.
2. **Copy strings verbatim** from the code. Fill dynamic values with realistic made-up content.
3. **Tokens only:** colours are `var(--c-<token>)` or `var(--role-*)`, type is `font: var(--t-<style>)` plus `letter-spacing: var(--ls-<style>)`, then `var(--s-*)`, `var(--r-*)`, `var(--sh-*)`. Where the code itself hardcodes a raw value, use that same raw value: the canvas shows the app as it is, drift included.
4. **No real people or photos.** Use the placeholders. Names, handles and content are invented. No real logos except the app's own, and only if its licence allows.
5. **States:** draw the default state of every screen, then a separate screen for each state that looks different: loading, empty, error, validation error, a sheet or dialog opened from it.
6. Keep each screen self-contained: no scripts. Classes in a page CSS file start with the page id.
7. Keep `data-dc` ids stable across redraws (see above).

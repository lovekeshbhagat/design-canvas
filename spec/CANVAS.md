# Canvas: how to draw a screen

The canvas puts every screen of an app on one pan-and-zoom board, grouped into pages (one per app area). Each screen sits in a device frame and is drawn in plain HTML and CSS with the app's own tokens. `python3 engine/build.py <design-dir>` builds `out/canvas.html`.

## Files

| File | What it is |
| --- | --- |
| `canvas/screens.json` | Every screen and state the app has, drawn or not. The build reports coverage from it. |
| `canvas/pages/NN-<page>.json` | One board page: title, blurb, rows of screen ids, optional links. |
| `canvas/frames/<page>/<screen>.html` | One screen: only the markup **inside** the device. |
| `canvas/css/<page>.css` | Styles for that page's screens. Class prefix `<page>-`. |
| `canvas/partials/<name>.html` | Pieces shared by many screens (tab bar, header). |
| `parts.css` | The app's component styles, shared with the guide's specimens. Reuse them. |
| `refs/` | Real screenshots of the app, one per screen (`reference`). Keep them in the app's repo only. |
| `assets/` | The app's own images that screens show: logo, QR code, illustration (`{{asset:…}}`). |
| `engine/assets/frame.css` | Device chrome and the `sc-*` layout helpers (read it). |

## Screen list (canvas/screens.json)

List every screen and every state that looks different **before** you draw, from the app's navigation, routes or view files. A screen that is listed but has no frame yet shows as "not drawn yet".

```json
{
  "screens": [
    { "id": "today", "name": "Today", "source": "src/screens/TodayScreen.tsx", "page": "today" },
    { "id": "today-empty", "name": "Today", "state": "Empty", "source": "src/screens/TodayScreen.tsx", "page": "today" },
    { "id": "settings", "name": "Settings", "source": "Views/SettingsView.swift" }
  ]
}
```

| Field | Meaning |
| --- | --- |
| `id` | Required. The screen id: the frame's file name once it is drawn (`frames/<page>/<id>.html`). |
| `name` | The screen's name. |
| `state` | Optional; as in the screen file (`Empty`, `Error`, `Sheet open`…). Leave it out for the default state. |
| `source` | The file (or files) that render it. Same rules as in the screen file. |
| `page` | Optional; the canvas page it belongs on. Its page header then lists it while it is not drawn. |

The build prints `canvas: 6 of 37 screens drawn · not drawn: …` and puts `"coverage": {"drawn", "listed", "missing", "unlisted"}` in `--json`. The canvas side panel lists the screens not drawn yet, and the guide's home says "See 6 of 37 screens on the canvas". A screen that is drawn but not listed still counts, and is named in `unlisted` so you can add it. Without `screens.json` everything works as before.

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
source: src/screens/TodayScreen.tsx, src/components/HabitSheet.tsx#HabitSheet
reference: refs/today.png
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
| `source` | The file that renders it, as a path from the app root (the same root as `src` in design.json). Several files: separate them with commas. To name a type or view inside a file, add `#Symbol`: `Views/Home.swift#SettingsSheet`. Review comments use it to find the code to change. |
| `reference` | Optional; a real screenshot of this screen, as a path inside the design folder (`refs/today.png`). Any size: it is scaled to the frame's width. `.png`, `.jpg`, `.webp` or `.gif`. |
| `theme` | Optional; a theme id from design.json. |
| `statusbar` | Optional; `light` draws the status bar and home indicator in white, for a dark top on a light-theme screen. |
| `device`, `width`, `height` | Optional overrides of `app.frame`. `height: auto` shows a full scroll capture. |
| `url` | For `browser` frames: the address shown in the window bar. |

Give every element a designer might comment on a stable id: `data-dc="habit-1"`, unique within the screen (`header`, `primary-button`, `habit-1`, `tabbar`…). Keep the same id when you redraw the screen, so review comments stay pinned to the right element.

Shortcuts inside a screen:
- `{{icon:name}}` or `{{icon:name:20}}` draws an icon from design.json at an optional size. Names may contain dots (`chevron.right`).
- `{{asset:logo.png}}` becomes the image `assets/logo.png`, embedded in the page, for `<img src="{{asset:logo.png}}" alt="…">` or `background-image: url('{{asset:qr.png}}')`. The path stays inside `assets/`. Use it for the app's own images only, and keep them small.
- `{{> partial key=value}}` inserts `canvas/partials/partial.html`, with every `{{key}}` in it replaced. A tab bar marks its active tab with `data-active="{{active}}"`; style it in `parts.css`.

The build reports an icon that is not in design.json and any `{{icon:…}}`, `{{asset:…}}` or `{{> …}}` it could not read.

**System icons.** SF Symbols, Material Symbols and other icon sets that come with the operating system can't be copied into the guide. List them in design.json with `system` and `name` instead of `svg` (see DESIGN_JSON.md). `{{icon:name}}` then draws a neutral dashed square of the same size. The symbol's name shows when you hover it, in Inspect, and under the icon in the guide's icon list.

## The phone frame

The default phone frame is 390 × 844 px. The status bar is 47 px tall and is drawn **over** the top of the screen, like on a real phone:

- A screen's content starts **47 px** from the top of the frame (the safe area). You don't need to add anything for this.
- Backgrounds can run up under the status bar: the first `sc-body` of a screen does this by itself. Put `sc-bleed` on a header or image that is the first element of the screen to do the same. Their content still starts below the bar.
- The home indicator sits over the bottom 34 px; `sc-safe` adds that much bottom padding.
- `sc-under`, `sc-scrim`, `sc-modal` and `sc-dialog-wrap` cover the whole screen, status bar area included, as the operating system does.

## Compare with the real app

A drawing can look right and still be wrong: a size off by 30% is easy to miss by eye. Compare each screen with a real screenshot.

1. Capture the screen in the running app (simulator, emulator, browser, a preview or demo mode), or take it from the repo's store screenshots. Save it in `refs/` and set `reference` on the frame.
2. Build. The frame gets a **Drawing / Side by side / Overlay** switch. Overlay lays the screenshot on top of the drawing with an opacity slider, so any size or position that is off shows at once.
3. To get the drawing as an image, run `python3 engine/build.py <design-dir> --shoot <screen-id> [--theme <id>] [--scale 3] [--out shot.png]`. It renders that one screen at its frame size with headless Chrome, Chromium or Edge (set `CHROME_PATH` if yours is somewhere else). The default file is `out/shots/<id>.png`.

Reference screenshots are embedded in `out/canvas.html` as data, so the canvas stays one file that works from a disk, from the review helper and as an attachment. The build warns when screenshots and assets add more than 1 MB: save them at 1x as `.jpg` or `.webp`. Screenshots of a real app can show private data; keep them in the app's own repo.

## Screens that may be out of date

When the design folder is in a git repo, the build compares each screen's `source` files with its frame file. If a source file has a newer commit than the frame, it warns: `screen 'home' may be out of date: Views/Home.swift changed after the frame`, lists it under `"outdated"` in `--json`, and marks the frame "May be out of date" on the canvas. Redraw the screen (or check it and commit the frame) to clear it. Without git, or for files without history, the check is skipped.

## Helpers (engine/assets/frame.css)

- Layout: `sc-body` (the scrolling area), `sc-pad` (screen gutter), `sc-safe` (bottom safe area), `sc-bleed` (run a background under the status bar), `sc-row`, `sc-col`, `sc-grow`, `sc-center`, `sc-hr`, `sc-trunc`, `sc-spinner`.
- Overlays: draw the screen underneath inside `sc-under`, then `sc-scrim`, then a `sc-sheet` (with `sc-handle`) or a dialog inside `sc-dialog-wrap`. iOS page-sheet modals: `sc-modal` > `sc-modal-card`.
- Placeholders: `ph-photo`, `ph-image`, `ph-thumb`, `ph-avatar`. They are abstract on purpose.
- Decoration (a vignette, grain, a glow) that lies over the screen: mark it `aria-hidden="true"` or give it `pointer-events: none`, so Inspect picks what is under it.

## Rules

1. **Read the real screen code first**: the screen file and every component it renders. Draw what the code draws: the order of regions, sizes converted to px (Tailwind `p-4` = 16 px; React Native numbers are already px), the variants and props passed, icon names and sizes.
2. **Copy strings verbatim** from the code. Fill dynamic values with realistic made-up content.
3. **Tokens only:** colours are `var(--c-<token>)` or `var(--role-*)`, type is `font: var(--t-<style>)` plus `letter-spacing: var(--ls-<style>)`, then `var(--s-*)`, `var(--r-*)`, `var(--sh-*)`. Where the code itself hardcodes a raw value, use that same raw value: the canvas shows the app as it is, drift included.
4. **No real people or photos.** Use the placeholders. Names, handles and content are invented. No real logos except the app's own, and only if its licence allows.
5. **States:** draw the default state of every screen, then a separate screen for each state that looks different: loading, empty, error, validation error, a sheet or dialog opened from it.
6. Keep each screen self-contained: no scripts. Classes in a page CSS file start with the page id.
7. Keep `data-dc` ids stable across redraws (see above).
8. **Every screen in screens.json.** Never stop at a few without saying so: what is not drawn stays listed.

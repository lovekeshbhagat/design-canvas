# design.json

`design.json` is one app's design system in a single standard file. An agent writes it by reading the app's code. The engine builds the guide, canvas and token files from this file alone, so that part works for any platform. It only goes back to the code for the drift check (each token's `src` line) and the "Used in" lists (JS/TS imports). See the README for which code formats the drift check understands.

Machine-readable schema: [`design.schema.json`](design.schema.json). Validate with `python3 engine/build.py <dir> --validate`.

## Top level

| Key | Required | What it holds |
| --- | --- | --- |
| `version` | yes | Always `1`. |
| `app` | yes | Name, description, platform, the default screen frame, and where the app code is. |
| `themes` | no | The app's themes (light, dark, dim…). Leave it out for a single-theme app. |
| `roles` | yes | Which colour token plays each standard role (background, text, accent…). |
| `colors` | yes | Colour tokens. |
| `fonts`, `type` | no | Font faces and the type scale. |
| `spacing`, `radii`, `shadows`, `motion` | no | The other token groups. Leave out what the app doesn't have. |
| `icons` | no | The app's icon set, as SVG shapes. |
| `components` | no | Where the app's shared components are imported from (for "Used in" lists). |

## Every token

A token is either a bare value (`"md": 12`, `"bg": "#FFFFFF"`) or an object:

| Field | Meaning |
| --- | --- |
| `value` | The value. For colours, a hex or `rgba()` string, or one per theme: `{"light": "#fff", "dark": "#000"}`. |
| `doc` | One line on what it's for, ideally the comment written next to it in the code. |
| `group` | Optional heading it is listed under in the guide (`Background`, `Text`, `Brand`…). |
| `code` | How the app's code refers to it (`colors.bg`, `bg-surface`, `Theme.surface`). |
| `src` | Where the value is defined: `path/from/app/root.ts:12`. The drift check reads this. |
| `derived` | Set this when the value is computed by code (a generated dark theme, a scale function) instead of written literally. Say how it is computed. The drift check skips it and the guide marks it. |

## app

```json
"app": {
  "name": "Acme Habits",
  "description": "One sentence on what the app is.",
  "platform": "react-native",
  "root": "..",
  "frame": { "device": "phone", "width": 390, "height": 844 }
}
```

- `platform`: `react-native`, `ios`, `android`, `flutter`, `web` or `other`.
- `root`: the app's repo root, relative to the folder that holds `design.json`. Used by `--check` and the "Used in" lists. Default `..`.
- `frame.device`: `phone` (status bar, island, home indicator), `browser` (window bar) or `none`. `width` and `height` are in points / CSS px.

## themes

```json
"themes": [
  { "id": "light", "label": "Light", "scheme": "light" },
  { "id": "dark", "label": "Dark", "scheme": "dark" }
]
```

The first theme is the default. A colour with a single value uses it in every theme. A colour with per-theme values must give one for the default theme; other themes fall back to it.

## roles

The guide and the screen frames style themselves through these roles, so they work for any naming scheme. Each maps to a colour token name.

| Role | Used for | Fallback if missing |
| --- | --- | --- |
| `background` | screen background | **required** |
| `text` | main text | **required** |
| `surface` | cards, sheets | `background` |
| `surface2` | raised or pressed surface | `surface` |
| `textMuted` | secondary text | `text` at 60% |
| `accent` | primary actions, focus | `text` |
| `onAccent` | text on `accent` | `background` |
| `border` | hairlines | `text` at 15% |
| `danger` | errors | `#D93025` |
| `scrim` | dimming under sheets | `rgba(0,0,0,0.5)` |

## fonts and type

```json
"fonts": {
  "regular": { "family": "Inter", "weight": 400, "load": "google" },
  "semibold": { "family": "Inter", "weight": 600, "load": "google" }
},
"type": {
  "title": { "font": "semibold", "size": 22, "lineHeight": 28, "letterSpacing": -0.2, "doc": "Screen titles", "code": "typography.title", "src": "src/theme/type.ts:8" }
}
```

- `load`: `google` (loaded from Google Fonts), `url` (give `url` to a .woff2), or `system` (not loaded; name a system stack in `family`, e.g. `-apple-system, system-ui`).
- `type.*.font` names a key in `fonts`. `lineHeight` is in px; give `lineHeight` as a ratio only if the code does, as `"lineHeightRatio": 1.3`.
- Optional `sample` on a type token sets the text shown for it.

## spacing, radii

```json
"spacing": { "xs": 4, "sm": 8, "md": 12, "gutter": { "value": 20, "doc": "Screen side padding" } },
"radii": { "sm": 6, "card": { "value": 16, "doc": "Cards and sheets" }, "pill": 999 }
```

## shadows

```json
"shadows": {
  "card": { "x": 0, "y": 2, "blur": 8, "spread": 0, "color": "#000000", "opacity": 0.12, "elevation": 2, "doc": "Resting cards" }
}
```

`elevation` is optional (Android). `color` may be a colour token name.

## motion

```json
"motion": {
  "durations": { "fast": { "value": 150, "doc": "Taps and toggles" } },
  "easings": { "standard": { "value": "cubic-bezier(0.2, 0, 0, 1)" } },
  "springs": { "gentle": { "damping": 18, "stiffness": 180, "mass": 1 } }
}
```

## icons

```json
"icons": {
  "set": "lucide",
  "style": "stroke",
  "strokeWidth": 2,
  "viewBox": "0 0 24 24",
  "items": {
    "home": { "svg": "<path d=\"M3 10 12 3l9 7v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1Z\"/>", "source": "lucide:house" }
  }
}
```

- `items` key = the name the app uses. `svg` = the inner shapes of the icon (no `<svg>` wrapper), copied from the icon package or the app's own SVG files.
- `style`: `stroke` (outline icons such as Lucide, Feather) or `fill` (Material, SF-style filled). An item can override `style`, `strokeWidth` and `viewBox`.
- Only list icons the app really registers or imports.

## components

```json
"components": { "importFrom": ["@/components/ui", "src/components/ui"], "scan": ["src"], "ignore": ["src/components/ui/preview/"] }
```

The engine scans the files under `scan` for imports from these modules. Each `::: lineage Name` block in the guide then lists the files that use `Name`. JavaScript and TypeScript imports only, for now.

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
| `src` | Where the value is defined: `path/from/app/root.ts:12`. Give one line per value, comma-separated (`theme.ts:6, theme.ts:20`). The drift check reads this. |
| `derived` | Only for a value the code computes (a generated dark theme, a scale function) instead of writing it. Say how it is computed. The drift check skips it and the guide marks it. Never use it to silence drift: the check reports the share of derived tokens, and CI can cap it. |

**One token, two names.** When each theme's value comes from its own constant (`Palette.sand` in light, `Palette.slate` in dark), give `code` and `src` as objects keyed by theme id. Each theme's value is then checked against its own name and line:

```json
"bg": {
  "value": { "light": "#F4EFE6", "dark": "#121212" },
  "code": { "light": "Palette.sand", "dark": "Palette.slate" },
  "src": { "light": "Sources/Palette.swift:4", "dark": "Sources/Palette.swift:9" }
}
```

A theme missing from `code` or `src` uses the default theme's entry. The plain string forms still work.

**What the drift check (`--check`) compares.**
- **Where it looks.** If the `src` line defines the token's name (or its `code` name), only that definition counts. Otherwise it tries the `src` line itself, then the nearest definition of the name within 8 lines (code moves). Other values nearby never count, and neither do comments.
  - A Swift `case .headline, .body: 18` defines both names.
  - A call such as `.sheet(isPresented:)` is not a definition.
- **What it compares.** Every field the guide shows:
  - colour and alpha
  - type size, line height, letter spacing, and the weight of the type's font
  - every shadow field: x, y, blur or radius, spread, colour, opacity and elevation
  - spring fields, durations and easings

  Each value is matched against its own label (`x:`, `radius:`, `shadowOpacity`, `fontWeight`…), never against any number on the line.
- **Not checked.** A field the code does not state (a weight on a system text style, a shadow with no colour) is listed as `not checked: type.headline weight, …`. It does not fail the check.
- **The derived share.** `--check` reports how many tokens are `derived`, and their share. `--check --max-derived 10` fails when more than 10% of tokens are derived. A derived token whose note names a `file:line` is listed as "could be checked".

Each token becomes a CSS variable named after the token in kebab case: `colors.onPrimary` is `var(--c-on-primary)`, `colors.tag_3` is `--c-tag-3`, but `colors.tag3` is `--c-tag3` (no hyphen before a digit). The prefixes are `--c-` colours, `--f-` fonts, `--t-` and `--ls-` type, `--s-` spacing, `--r-` radii, `--sh-` shadows, `--d-` durations, `--e-` easings and `--role-` roles. The build warns about any of these that parts.css, the guide or the canvas uses but design.json doesn't define.

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

The first theme is the default. A colour with a single value uses it in every theme. A colour with per-theme values must give one for the default theme. A theme it leaves out falls back to the default theme's value, with a warning (`colors.X has no value for the 'dark' theme; using 'light'`), so give every theme or use a single value.

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

## Text colours and contrast

The guide checks that text colours reach 4.5:1 on the colour they are read on. A colour counts as text when it plays the `text`, `textMuted` or `onAccent` role, has `on`, is named `onX`, or has the word `text`, `label`, `foreground` or `fg` in its name or group without a fill word (`bg`, `background`, `fill`, `surface`, `border`…). Words like `ink` or `content` don't count: apps use them for backgrounds too. Colours that aren't text get no contrast number.

| Field | Meaning |
| --- | --- |
| `on` | The fill(s) the colour is read on: a colour token name, a list of names, or one of those per theme (`{"light": "pine", "dark": ["pine", "card"]}`). Contrast is checked on each. Without it, `onX` is read on `X`, `onAccent` on `accent`, and every other text colour on `background`. |
| `text` | `true` or `false`, when the name or role gets it wrong: `true` checks the colour on `background` (or its `on`), `false` skips it. |

```json
"onPine": { "value": "#FFFFFF", "on": "pine", "doc": "Labels on pine buttons" },
"badgeText": { "value": "#102A43", "on": ["sun", "sky"], "doc": "Numbers on status badges" }
```

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
- Leave both out when the code sets no line height (SwiftUI and UIKit text styles often don't). The guide and tokens.md then say "auto" / "platform default", and the CSS uses `normal`. DTCG needs a number, so tokens.json writes `1.2` and marks it with `"$extensions": {"dev.design-canvas": {"lineHeight": "platform default"}}`.
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

**Radius instead of blur.** SwiftUI and UIKit write a shadow `radius` (`.shadow(radius: 8)`, `layer.shadowRadius`), which is about half the CSS blur. For that code, give `radius` as written and leave out `blur`:

```json
"card": { "x": 0, "y": 4, "radius": 8, "color": "#000000", "opacity": 0.2, "src": "Sources/Theme.swift:31" }
```

The drift check compares `radius` with the code. The CSS variable and the DTCG tokens use blur = 2 × radius. If you give `blur` and the code writes a radius, `blur` must equal that radius (React Native's `shadowRadius` is the CSS blur).

## motion

```json
"motion": {
  "durations": { "fast": { "value": 150, "doc": "Taps and toggles" } },
  "easings": { "standard": { "value": "cubic-bezier(0.2, 0, 0, 1)" } },
  "springs": { "gentle": { "damping": 18, "stiffness": 180, "mass": 1 } }
}
```

- `durations` are in milliseconds. SwiftUI and Android code often write seconds (`.easeOut(duration: 0.25)`); the drift check also accepts the value / 1000 there.
- A spring is written the way the code writes it:
  - `damping`, `stiffness`, `mass` (CSS, React Native, Compose `stiffness`)
  - `response` and `dampingFraction` (SwiftUI `.spring(response: 0.3, dampingFraction: 0.8)`)
  - `duration` and `bounce` (SwiftUI `.spring(duration: 0.5, bounce: 0.3)`), both in seconds like the code.

  For the SwiftUI forms, the engine works out what CSS, DTCG and previews need. `mass` defaults to 1:
  - stiffness = (2π / response)² × mass
  - damping = 4π × dampingFraction × mass / response
  - `duration` is used as `response`, and dampingFraction = 1 − bounce (or 1 / (1 + bounce) when bounce is below 0).

  Left out, `response` is 0.5 and `dampingFraction` 0.825, as in SwiftUI.

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

**System icons.** Icons the operating system draws (SF Symbols, Material Symbols, Segoe Fluent…) can't be copied from a package, and their licence doesn't allow it. Give `system` (the icon set) and `name` (the symbol's name, if it differs from the key) instead of `svg`:

```json
"items": {
  "settings": { "system": "sf-symbols", "name": "gearshape" },
  "chevron.right": { "system": "sf-symbols" }
}
```

Screens and specimens draw them as a neutral dashed square at the icon's size. On the canvas, the symbol's name shows when you hover the icon or inspect it. The guide's icon list shows `sf-symbols: gearshape` under each one, so a designer can look it up.

## components

```json
"components": { "importFrom": ["@/components/ui", "src/components/ui"], "scan": ["src"], "ignore": ["src/components/ui/preview/"] }
```

The engine scans the files under `scan` for imports from these modules. Each `::: lineage Name` block in the guide then lists the files that use `Name`. JavaScript and TypeScript imports only, for now: when there are none to read (a Swift or Kotlin app), the block shows nothing.

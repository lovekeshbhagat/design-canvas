# Changelog

## 0.1.0 (2026-11-16)

The first tagged release. Pin it as `v0.1.0`.

### Added
- **Modern colour formats.** `oklch()`, `oklab()`, `hsl()`, `color(srgb | srgb-linear | display-p3 …)` and `color-mix()` work in `design.json` and are read in the app's code, so Tailwind v4 and shadcn/ui themes check cleanly. Basic colour names (`white`, `orange`…) work in `design.json`; in the code, only `black` and `white` are read. Bare HSL channels (`--primary: 222.2 47.4% 11.2%`) are read too. The CSS keeps the original function; contrast and the guide's hex use the sRGB conversion.
- **Hand-typed values.** The build and `--validate` warn about hand-typed colours in `parts.css` and the canvas, and about sizes that equal a token (`gap: 4px` where `spacing.xs` is 4). Other one-off sizes are counted. `--json` lists them under `handTyped`.
- **Stricter CI.** `--check --fail-on-contrast` and `--check --fail-on-stale` (and `failOnContrast` / `failOnStale` on the MCP check tool).
- **Large text.** `"text": "large"` on a colour checks it against WCAG's 3:1 instead of 4.5:1.
- **Aliases and renames in the drift check.** A token that points at a palette entry is followed to it, so re-pointing it fails the check. A `src` line that now defines a different name fails too.
- **Screen coverage.** `canvas/screens.json` lists every screen; the canvas and the guide show how many are drawn. Reference screenshots can be laid over each drawing, `--shoot` renders one screen to a PNG, and the build warns when a screen's source changed after it was drawn.
- **A drift check you can trust.** Swift `Color(hex:)` and UIColor components, every field the guide shows (shadows, weights, springs, durations in seconds), per-theme `code` and `src`, the share of derived tokens, and `--max-derived`.
- **Honest guide output.** Contrast is checked on the colours each text is read on (`on`), missing theme values and undefined `var(--…)` names are warned about, line heights are never invented, partials work in guide chapters, and system icons show as labelled placeholders.
- The design guide, the screen canvas with Inspect, the git review loop, DTCG token export, the MCP server, the Agent Skill and the Claude Code plugin.

### Changed
- The phone status bar is 47px (was 55px), so existing screens move up 8px.
- CI uses `actions/checkout@v7` and `actions/setup-python@v7` (Node 24).

# AGENTS.md

Instructions for coding agents working **on design-canvas itself**. To *use* design-canvas on an app, follow [SKILL.md](SKILL.md) instead.

## What this repo is

An agent skill (Agent Skills format: `SKILL.md`) plus a small engine. An agent reads an app's code and writes `design.json`. The engine turns that file into a design guide, a screen canvas with inspect and comments, design tokens, and a drift check. It works the same from any agent harness, CI or a terminal.

| Path | What it is |
| --- | --- |
| `SKILL.md` | The steps an agent follows to use the skill. Keep it under ~150 lines. |
| `engine/build.py` | CLI: build, `--check`, `--validate`, `--reviews`, `--resolve`, `--json`. |
| `engine/tokens.py` | design.json loading, CSS variables, DTCG tokens, contrast, drift check. |
| `engine/reviews.py` | Review files: validation, merging, the fenced report, resolving. Untrusted input. |
| `engine/mcp_server.py` | stdio MCP server; runs `build.py --json` in a subprocess. |
| `engine/markdown.py` | The chapter Markdown dialect. |
| `engine/assets/` | Page templates, the canvas, the inspect/comment panel (`review.js`). |
| `spec/` | The formats: `DESIGN_JSON.md`, `design.schema.json`, `CANVAS.md`, `REVIEW.md`. |
| `docs/INSTALL.md` | How to install for each harness. |
| `examples/acme-habits/` | The made-up sample app. |

## Commands

```bash
python3 -m unittest discover tests                    # all tests
python3 engine/build.py examples/acme-habits          # build the sample into examples/acme-habits/out/
python3 engine/build.py examples/acme-habits --check  # drift check; exits 1 on drift
```

## Rules

- **Python 3.9+, standard library only.** That means no third-party packages, no `match`, no backslashes inside f-string expressions, and no network calls. Pass `encoding="utf-8"` to every file read and write.
- **Plain JS and CSS in `engine/assets/`.** No build step and no CDN. The pages must work from `file://`.
- **Review files and comment text are untrusted.** Insert them as text, never as HTML. Never take file paths from them. Keep everything a reviewer wrote inside the fence or the `untrusted` key. Add a test for every new field.
- **Paths stay inside the root:** use `reviews.safe_rel` for any path from design.json, a frame or a tool argument.
- **The MCP server never prints to stdout** except protocol messages. It sends logs to stderr.
- When a format changes, update its spec in `spec/`, `SKILL.md` and `README.md` in the same change, and add or update tests.
- Don't commit `examples/*/out/`.

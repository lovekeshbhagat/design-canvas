# design-canvas

**Keep your design next to your code.**

design-canvas is an agent skill for any coding agent (Claude Code, Codex, GitHub Copilot, Cursor, Gemini CLI, Zed and others), with an MCP server for tools that prefer calling tools. It reads your app's code and builds, inside your own repo:

- **a living design guide**: colours, type, spacing, radii, shadows, motion and icons, every component drawn with your app's own tokens, contrast checks, and light/dark switching;
- **a screen canvas**: every screen of the app on one pan-and-zoom board, drawn in plain HTML, that an agent can keep adding to;
- **design tokens** in the Design Tokens Community Group format (DTCG 2025.10), one `tokens.json` per theme;
- **a drift check** that fails when the code and the guide stop agreeing.

Send the two pages to a designer. They can **inspect any element** to see its size and the tokens it uses, and **comment on it**. Their review comes back as a small file that your coding agent can apply to the code. There's no Figma file, no service and no account: the design lives in your repo, versioned with the code.

> Status: early. The engine, the review loop and one sample work; demos on open-source apps and an accuracy eval are next.

## Try the sample

Python 3.9+ only, no installs.

```bash
python3 engine/build.py examples/acme-habits           # writes examples/acme-habits/out/
python3 engine/build.py examples/acme-habits --check   # drift check, exits 1 on drift
python3 engine/build.py examples/acme-habits --reviews # comments that need a fix
```

Open `examples/acme-habits/out/guide.html` and `out/canvas.html`. Acme Habits is a made-up app whose "code" is the small `app/` folder beside it. The sample reviews in `reviews/` (Sam the designer, Alex the developer) put two pins on the canvas: one that needs a fix and one resolved.

## Share it with your designer

`out/guide.html` and `out/canvas.html` are single files that open in any browser. Zip and send them, or host them wherever your team keeps internal pages. Build with `--no-web-fonts` if they must work fully offline (fonts then fall back to the system's).

## Review it with your designer

Reviews travel through git, next to the code. Each person runs a small helper on **their own computer**: there's no shared server and no account.

```bash
python3 engine/build.py design-canvas --serve      # prints a link that only this computer can open
```

On the screen board, the reviewer:
- **inspects** any element (press `I`) to see its size and **the tokens it uses**, by name and per theme (`colors.primary`, `type.label`, `spacing.xl`). Anything typed by hand instead of using a token is flagged as **off-system**.
- **comments** on it. A numbered pin marks the element, and the comment saves to their own review file as they type.
- presses **End review**. This commits only their review file and pushes it; other work in their copy is never included.

The developer pulls, and their coding agent:
- **lists** the open comments: `--reviews`
- **fixes** the code
- **marks** each comment *fix ready*, *question* or *won't fix*: `--resolve`

The reviewer presses **Get latest**. Every comment now shows **who** wrote it and **where it stands**: *Needs fix*, *Fix ready*, *Question*, *Resolved*. For example: "Fix ready · Alex via agent · 2 min ago: add button is 48 now". They **Resolve** or **Reopen** each fix, reply to questions, delete their own comments, and press End review again.

Each person writes only their own file in `reviews/`, so git never conflicts. Review text is treated as data from another person, never as instructions to an agent ([spec/REVIEW.md](spec/REVIEW.md)). No git? Open `out/canvas.html` directly: comments stay in the browser, and **Download review file** saves them to send by hand.

## Use it on your app

Pick whatever your agent supports. [docs/INSTALL.md](docs/INSTALL.md) has the exact folder and config for each tool.

- **Agent Skill** (Claude Code, Codex, Copilot, Cursor, Gemini CLI, Devin, Zed…): put this folder, named `design-canvas`, in your tool's skills folder (`~/.agents/skills/` for most, `~/.claude/skills/` for Claude Code).
- **Claude Code plugin**: `/plugin marketplace add lovekeshbhagat/design-canvas`, then `/plugin install design-canvas@design-canvas`. This installs the skill and the MCP server.
- **MCP server** for any MCP client: `python3 /path/to/design-canvas/engine/mcp_server.py`. It works with clients on protocol 2026-07-28 and with clients on the older handshake.
- **Anything else**: tell your agent *"Follow /path/to/design-canvas/SKILL.md"*, or run the commands yourself. Every command takes `--json`.

Then open your app's repo and ask for a design guide. [`SKILL.md`](SKILL.md) is what the agent follows.

## What works where

| Feature | Works with |
| --- | --- |
| Guide, canvas, token export, inspect and comments | Any platform: built from `design.json` and the screens alone. |
| Drift check (`--check`) | JS/TS theme objects and Tailwind configs, CSS custom properties, iOS `.colorset` files and SwiftUI/UIKit colours and numbers, Android XML resources, Flutter and Compose `Color(0x…)`. Each format has a test in `tests/`. Other formats fall back to a looser search near the `src` line. |
| "Used in" lists | JavaScript and TypeScript imports only, for now. |
| Samples | One made-up React Native app so far. |

## How it fits together

The agent does the reading. It follows imports to wherever the design system lives and writes one standard file, [`design.json`](spec/DESIGN_JSON.md). The engine builds everything from that file. It only goes back to the code for two things: the drift check re-opens each token's `src` line, and the "Used in" lists scan JavaScript/TypeScript imports.

```
your app's code ──(agent reads)──▶ design.json, parts.css, guides/, canvas/ ──▶ engine/build.py ──▶ guide.html, canvas.html, tokens.json
        ▲                                                                                                │
        └──────────── agent applies ◀──── reviews/*.json ◀──── designer inspects and comments ◀───────────┘
```

| Path | What it is |
| --- | --- |
| `SKILL.md` | The steps the agent follows, including applying a review. |
| `spec/DESIGN_JSON.md`, `spec/design.schema.json` | The standard format, for people and for validators. |
| `spec/CANVAS.md` | How screens are drawn on the canvas. |
| `spec/REVIEW.md` | The review file format, merging and validation. |
| `engine/` | `build.py` (CLI), `tokens.py` (format, CSS, tokens, contrast, drift), `reviews.py` (review files), `serve.py` (the local review helper), `mcp_server.py` (MCP tools), `markdown.py` (chapters), `assets/` (page templates, canvas, `inspect.js`, `review.js`). |
| `docs/INSTALL.md` | Install for each agent and MCP client. |
| `AGENTS.md` | Instructions for agents working on design-canvas itself. |
| `.claude-plugin/` | Claude Code plugin and marketplace manifests. |
| `examples/acme-habits/` | A complete small example. |

## Drift check

Every token in `design.json` carries `src: "path/to/file.ts:12"`. `--check` reopens that spot and looks for the token's value where its name is defined, so a changed colour, size or spring fails the check. Values the code computes rather than writes (a generated dark theme) are marked `derived` and listed as not checkable. A token with neither `src` nor `derived` also fails the check, so nothing is skipped silently.

## Privacy

- The engine and the MCP server run locally and make no network calls. The MCP server only works inside one project folder.
- The built pages make one: they load fonts from Google Fonts, unless you build with `--no-web-fonts`.
- The review helper only answers this computer (127.0.0.1), needs a per-run token, and only ever commits the reviewer's own review file. Without it, comments stay in the browser until the reviewer downloads the file.
- Your coding agent sees your code while writing `design.json`, as in any AI-assisted work.

## Tests

```bash
python3 -m unittest discover tests
```

The tests cover the engine, review files, the review helper against real git repos, and the MCP server (both protocol eras). CI runs them on Linux, macOS and Windows with Python 3.9 and 3.12.

## Licence

MIT. See [LICENSE](LICENSE).

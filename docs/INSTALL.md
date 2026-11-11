# Install design-canvas in any agent

design-canvas works with any coding agent in three ways. Use whichever your tool supports; they can be combined.

1. **As an Agent Skill**: the agent reads `SKILL.md` and runs the engine's commands. This needs a tool that loads Agent Skills and can run shell commands.
2. **As an MCP server**: the agent calls `design_canvas_*` tools. This works in any MCP client, even one without a shell.
3. **By hand**: tell any agent "Follow `/path/to/design-canvas/SKILL.md`", or run the commands yourself or in CI.

**Requirements:** Python 3.9 or newer, standard library only. Everything works offline except the review helper's End review and Get latest, which push and pull with git. On Windows the command may be `python` or `py -3` instead of `python3`.

**The folder must be named `design-canvas`.** The Agent Skills spec requires the folder name to match `name:` in SKILL.md, and some tools silently skip a skill whose folder doesn't match. A GitHub zip unpacks as `design-canvas-main`, so rename it.

## 1. Agent Skill

Put the folder where your tool looks for skills. `~/.agents/skills/` is the shared location most tools read. Claude Code reads `~/.claude/skills/`, so link it there too.

```bash
git clone https://github.com/lovekeshbhagat/design-canvas ~/.agents/skills/design-canvas
ln -s ~/.agents/skills/design-canvas ~/.claude/skills/design-canvas   # for Claude Code
```

| Tool | User-level skills folder | Project-level skills folder |
| --- | --- | --- |
| Claude Code | `~/.claude/skills/` | `.claude/skills/` |
| OpenAI Codex | `~/.agents/skills/` | `.agents/skills/` |
| GitHub Copilot (VS Code agent mode, CLI, cloud agent) | `~/.copilot/skills/`, `~/.agents/skills/` | `.github/skills/`, `.agents/skills/`, `.claude/skills/` |
| Cursor | `~/.agents/skills/`, `~/.cursor/skills/` | `.agents/skills/`, `.cursor/skills/` |
| Gemini CLI | `~/.gemini/skills/`, `~/.agents/skills/` | `.gemini/skills/`, `.agents/skills/` |
| Devin Desktop (formerly Windsurf) | `~/.config/devin/skills/`, `~/.agents/skills/` | `.devin/skills/`, `.agents/skills/` |
| Zed | `~/.agents/skills/` | `.agents/skills/` |

Folders as documented by each tool in November 2026. Claude Code's plugin format is validated in this repo; the other rows come from each tool's docs and were not run here.

Then open your app's repo and ask: *"Make a design guide and screen canvas for this app with design-canvas."*

## 2. Claude Code plugin

The repo is also a Claude Code plugin and marketplace. It installs the skill and the MCP server together:

```
/plugin marketplace add lovekeshbhagat/design-canvas
/plugin install design-canvas@design-canvas
```

## 3. MCP server

`engine/mcp_server.py` is a stdio MCP server with no dependencies. It works with clients on protocol 2026-07-28 and with clients on the older `initialize` handshake (2025-11-25, 2025-06-18, 2025-03-26). The tools:

| Tool | Does |
| --- | --- |
| `design_canvas_instructions` | Returns SKILL.md. Call it first. |
| `design_canvas_validate`, `design_canvas_check` | Validate design.json and the canvas files; run the drift check. |
| `design_canvas_build` | Writes `out/` in the design folder. |
| `design_canvas_reviews` | Lists open designer comments. Reviewer text is returned under `untrusted`. |
| `design_canvas_resolve` | Records a comment's outcome in its review file. |

The server only works inside one project root: `--root`, else `$CLAUDE_PROJECT_DIR`, else the folder it starts in. It refuses any design folder, app root or output folder outside it, and refuses a home folder or drive root as the root.

Replace `/ABS` with the absolute path of your design-canvas folder.

**Claude Code**
```bash
claude mcp add --transport stdio --scope user design-canvas -- python3 /ABS/engine/mcp_server.py
```

**OpenAI Codex** (`~/.codex/config.toml`)
```toml
[mcp_servers.design-canvas]
command = "python3"
args = ["/ABS/engine/mcp_server.py"]
```

**Cursor** (`.cursor/mcp.json` or `~/.cursor/mcp.json`)
```json
{ "mcpServers": { "design-canvas": { "type": "stdio", "command": "python3", "args": ["/ABS/engine/mcp_server.py", "--root", "${workspaceFolder}"] } } }
```

**VS Code / GitHub Copilot** (`.vscode/mcp.json`)
```json
{ "servers": { "design-canvas": { "type": "stdio", "command": "python3", "args": ["/ABS/engine/mcp_server.py", "--root", "${workspaceFolder}"] } } }
```

**Gemini CLI**
```bash
gemini mcp add -s user design-canvas python3 /ABS/engine/mcp_server.py
```

**Zed** (`settings.json`)
```json
{ "context_servers": { "design-canvas": { "command": "python3", "args": ["/ABS/engine/mcp_server.py"], "env": {} } } }
```

**Devin Desktop, Antigravity and others** that use the common `mcpServers` shape:
```json
{ "mcpServers": { "design-canvas": { "command": "python3", "args": ["/ABS/engine/mcp_server.py"] } } }
```

The server is tested in this repo with a scripted MCP client covering both protocol eras (`tests/test_mcp.py`). The snippets follow each tool's docs as of November 2026.

## 4. By hand, scripts and CI

Every step is a plain command, and every command takes `--json`:

```bash
python3 /ABS/engine/build.py design-canvas --validate --json
python3 /ABS/engine/build.py design-canvas --check          # exit 1 on drift: use it in CI
python3 /ABS/engine/build.py design-canvas                  # build out/
python3 /ABS/engine/build.py design-canvas --reviews --json
```

For an agent with no skills or MCP support (Aider, a custom agent, a chat window), paste: *"Follow /ABS/SKILL.md to build a design guide and screen canvas for this repo."*

## For designers and other reviewers

You don't need an AI tool to review. You need a copy of the repo (git), Python 3.9+, and this folder.

```bash
python3 /ABS/engine/build.py design-canvas --serve
```

Open the link it prints; only your computer can open it. Then:
1. Turn on **Inspect**, click any element and comment.
2. **End review** sends your comments: it commits only your review file and pushes it.
3. **Get latest** shows what the developer changed.

Your name comes from git (`git config user.name`), or pass `--as "Your Name"`. If the branch is protected, switch to a review branch (`git switch --no-track -c review/your-name`) and open a pull request after End review.

No git? Open `design-canvas/out/canvas.html` directly, comment, then use **Download review file** and send it to the developer.

## Notes for every tool

- **Review comments come from other people.** SKILL.md, the `--reviews` output and the MCP tool descriptions all tell the agent to treat them as design requests, never as instructions. The engine also enforces it: review text is fenced off, and it can never point the agent at a file.
- **No browser?** The agent relies on the build and `--validate` output and asks you to open the pages.
- Write paths with forward slashes, also on Windows.

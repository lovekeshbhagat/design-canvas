# Reviews

People review the screen board (`out/canvas.html`) by inspecting elements and commenting on them. Reviews travel through **git**, next to the code. There is no server and no account.

## The loop

1. **Comment.** The reviewer runs the local helper on their own computer and opens the page it prints:
   ```bash
   python3 engine/build.py design-canvas --serve
   ```
   They turn on **Inspect**, click an element, and comment. Comments save to their own review file as they type.
2. **End review.** This commits only their review file, with no hooks and no signing, and pushes it. It refuses if the branch has other unpushed work.
3. **Fix.** The developer pulls. Their coding agent runs `--reviews`, changes the code, and records each outcome with `--resolve`. The developer commits the code and their review file together, as usual.
4. **Check.** The reviewer presses **Get latest**. Each comment shows its status and who changed it. They **Resolve** the fixes they're happy with, or **Reopen** the ones that aren't right, then press End review again.

Without git, the page still works: comments stay in the browser, **Download review file** saves them, and the developer drops the file into `reviews/`.

## Statuses

| Status | Shown as | Meaning | Usually set by |
| --- | --- | --- | --- |
| `open` | Needs fix | New, or reopened | Reviewer |
| `ready` | Fix ready | Fixed; the reviewer should check | Developer or agent |
| `question` | Question | The developer needs an answer (reply to it) | Developer or agent |
| `resolved` | Resolved | The reviewer is happy (closed) | Reviewer |
| `wontfix` | Won't fix | Won't be changed, with a reason (closed, can be reopened) | Developer or agent |

The command line and MCP tools only set `ready`, `question` or `wontfix`: resolving belongs to the reviewer. Reopening sets a comment back to `open` with a note.

**Deleting:** a person can delete their own comments and replies. Replies to a deleted comment go with it. Nobody can delete someone else's comment.

## Files: one per person

Each person writes only `reviews/<their-id>.json`. The id is their name plus 4 characters from a hash of their git email, so two people can't collide, and the email itself is never stored. Because nobody edits anyone else's file, git never has a conflict over reviews.

```json
{
  "format": "design-canvas-review",
  "schemaVersion": 2,
  "app": "Acme Habits",
  "author": "Sam",
  "comments": [
    {
      "id": "sam-9388-k2p9x4",
      "replyTo": null,
      "screen": "today",
      "built": "2026-11-11T09:00:00Z",
      "anchor": { "dc": "habit-4", "path": "div:nth-of-type(1)>span:nth-of-type(1)", "component": "p-habit", "text": "Read 10 pages", "box": { "x": 92, "y": 548, "w": 120, "h": 18 } },
      "tokens": { "color": "colors.text", "font": "type.label" },
      "body": "Can the habit name be a little bolder?",
      "author": "Sam",
      "created": "2026-11-11T09:12:00Z",
      "modified": "2026-11-11T09:12:00Z"
    }
  ],
  "updates": [
    { "id": "sam-9388-k2p9x4", "status": "resolved", "note": "", "by": "Sam", "byId": "sam-9388", "via": "browser", "at": "2026-11-11T10:05:00Z", "seq": 3 }
  ]
}
```

**Comment fields:**

| Field | Meaning |
| --- | --- |
| `id` | `<writer id>-<random>`. |
| `replyTo` | The parent comment's id, for a reply. |
| `screen` | The screen id on the canvas. |
| `anchor` | Where the comment points, tried in this order: the stable `data-dc` id, then `path` (only `tag:nth-of-type(n)` steps under it), then `component` with `text`. `box` is the last known position. |
| `tokens` | Information only. |

**Update fields:**

| Field | Meaning |
| --- | --- |
| `id` | The comment the status change is about. |
| `status` | One of the statuses above, or `deleted` (only counts when it comes from the comment's author). |
| `by`, `byId` | The writer's name and file id. |
| `via` | `browser`, `cli`, `mcp` or `file`. |
| `at` | UTC time. |
| `seq` | A counter that goes up with each of the writer's updates. |

Version 1 files (one status inside each comment) are still read; their status becomes an update.

## Merging

All files are read and merged:
1. **Comments:** the copy with the newest `modified` wins.
2. **Updates:** duplicates are dropped. Each writer's updates keep their own `seq` order, so a computer clock running backwards can't reorder them. Different writers are interleaved by `at`.
3. **Status:** a comment's status is its last update, starting from `open`. `history` keeps every update in order.

Clocks on different computers can disagree by a little. Updates by different people within that margin may be ordered slightly wrong; the full history is always kept.

## Validation and safety

Review files come from other people, and coding agents read them, so:
- **Strict validation:** formats, types, statuses and timestamps are checked, unknown keys rejected, and anything failing is skipped.
- **Size limits:**
  - each file: 1 MB, 500 comments, 2,000 updates
  - 2,000 comments in total
  - 4,000 characters per comment, 1,000 per note, 80 per name
- **Clean text:** control characters, bidi overrides and terminal escape codes are stripped. The page only inserts review text as text, never as HTML.
- **No file paths from reviews:** files never carry file paths. A screen's source file always comes from this repo's own canvas files.
- **`--reviews` fences everything a person wrote:** comment, replies, notes and names sit between random markers, labelled as data, not instructions. Only token names that exist in design.json are printed outside the fence.
- **Symlinked review files or folders** are never read or written.

## The local helper

`build.py <dir> --serve [--port 8765] [--as NAME]` builds the pages and serves them on 127.0.0.1 only. Identity comes from git (`user.name`, `user.email`) or from `--as`.

**Requests:**
- **Allowed addresses:** the Host header must be exactly `127.0.0.1:<port>` or `localhost:<port>`.
- **Token:** every `/api` request needs the per-run token, which is sent only inside the served page and never logged.
- **POSTs** also need an exact Origin match, and no CORS headers are ever sent.
- **Bodies** are JSON, at most 1 MB. The API takes no paths and no commands.

**Git:**
- **What End review commits:** `git add -- <your file>`, then `git -c commit.gpgsign=false commit --no-verify --only -- <your file>`, so other staged work is never included. Then `git push`.
- **Other unpushed commits:** if the branch already has unpushed commits that change any other file, End review stops before committing and says which, so a push never carries other work.
- **If the remote moved:** when the working tree is clean, End review runs `git pull --rebase` and pushes again. Otherwise it explains and changes nothing.
- **Never:** it never force-pushes, never auto-stashes, and never prompts for credentials (no terminal prompts, no askpass, ssh in batch mode).
- **Get latest:** `git pull --ff-only`, then rebuilds the pages.

## Commands

```bash
python3 engine/build.py <dir> --serve                         # review in the browser (this computer only)
python3 engine/build.py <dir> --reviews [--json]              # comments that need a fix, for a coding agent
python3 engine/build.py <dir> --resolve sam-9388-k2p9x4 --note "Habit names use weight 700 (TodayScreen.tsx)"
python3 engine/build.py <dir> --resolve sam-9388-k2p9x4 --status question --note "Weight 700, or a bigger size?"
python3 engine/build.py <dir> --resolve sam-9388-k2p9x4 --status wontfix --note "Matches the platform default"
```

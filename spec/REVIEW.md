# Review files

A designer opens `out/canvas.html`, turns on **Inspect**, clicks an element, and comments on it. Comments stay in their browser until they press **Send review**, which downloads one JSON file. They send it to the developer, who drops it into `<design-dir>/reviews/`. The next build shows each comment as a numbered pin, and a coding agent can apply the open ones.

There is no server and no account. A review only goes where someone sends the file.

## Format

```json
{
  "format": "design-canvas-review",
  "schemaVersion": 1,
  "app": "Acme Habits",
  "exported": "2026-11-11T09:30:00Z",
  "author": "Sam",
  "comments": [
    {
      "id": "sam-k2p9x4",
      "replyTo": null,
      "screen": "today",
      "built": "2026-11-11T09:00:00Z",
      "anchor": {
        "dc": "habit-4",
        "path": "div:nth-of-type(1)>span:nth-of-type(1)",
        "component": "p-habit",
        "text": "Read 10 pages",
        "box": { "x": 92, "y": 548, "w": 120, "h": 18 }
      },
      "tokens": { "color": "colors.text", "font": "type.label" },
      "body": "Can the habit name be a little bolder than the streak line?",
      "author": "Sam",
      "status": "open",
      "created": "2026-11-11T09:12:00Z",
      "modified": "2026-11-11T09:12:00Z",
      "resolvedAt": null,
      "resolution": "Optional: what the developer changed, or why not."
    }
  ]
}
```

| Field | Meaning |
| --- | --- |
| `id` | `<author-slug>-<random>`: lowercase letters, digits, `-`, `_`; 3–64 characters. Unique across reviewers. |
| `replyTo` | The `id` of the comment this replies to, or `null`. |
| `screen` | The screen id from the canvas (`canvas/frames/<page>/<screen>.html`). |
| `built` | When the page the comment was made on was built. |
| `anchor` | Where on the screen. Found in this order: the stable `data-dc` id, then `path` (only `tag:nth-of-type(n)` steps under it), then `component` + `text`; `box` is the last-known position. |
| `tokens` | The tokens the element used, as shown in the inspect panel. Information only. |
| `status` | `open`, `question`, `reopened` (still to do), or `resolved`, `wontfix` (closed). |
| `created`, `modified`, `resolvedAt` | UTC timestamps, `YYYY-MM-DDTHH:MM:SSZ`. |
| `author` | Typed by the reviewer. Self-reported; never used to decide what is allowed. |

Review files never carry file paths. Each screen's source file comes from this repo's own canvas files.

## Merging

All files in `reviews/` and the reviewer's browser are merged by `id`:
1. The record with the newest `modified` wins.
2. A closed comment (`resolved`, `wontfix`) is only reopened by a newer record whose status is `reopened`, so an old copy can't undo a fix.
3. Comments are listed by `created`, then `id`.

## Validation

The engine (`engine/reviews.py`) and the page apply the same limits, and drop anything that fails:
- `format` and `schemaVersion` must match, and unknown keys are rejected.
- Fields must have the right types; statuses and timestamps are checked.
- Size limits: 1 MB per file, 500 comments per file, 2,000 in total, 4,000 characters per comment, 80 per name.
- Control characters, bidi overrides and terminal escape codes are stripped.
- Symlinked review files are not read.
- In the page, review text is only ever inserted as text, never as HTML.

## Commands

```bash
python3 engine/build.py <dir> --reviews                       # open comments, for a coding agent
python3 engine/build.py <dir> --resolve sam-k2p9x4 --note "Habit names use weight 700 now (TodayScreen.tsx)"
python3 engine/build.py <dir> --resolve sam-k2p9x4 --status question --note "Bolder than 600, or bigger?"
```

`--reviews` prints each comment's text between random markers and labels it as data from a reviewer, not instructions.

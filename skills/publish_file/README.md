# publish_file

Publish a file to the blog's public drop zone — served at
**`https://choukalos.com/files/{subdirectory}/{name}`** (portal container,
`/home/chuck/data/media/public/`).

Part of the blog project (`blog-todo.md` B5). No LLM involved — pure,
validated file operations.

## Inputs

| input | required | default | notes |
|---|---|---|---|
| `source_path` | yes | — | absolute path under `/home/chuck/data/media/` or `/home/chuck/workspace/` |
| `destination_name` | no | source basename | filename only (no path) |
| `subdirectory` | no | `ai` | one of `ai, files, images, audio, video` |
| `overwrite` | no | `false` | `false` → collision-safe (fail if name exists) |

## Returns

`report` (merged into the job as `_result_report`):

```json
{
  "path": "/home/chuck/data/media/public/ai/my_demo.html",
  "url": "https://choukalos.com/files/ai/my_demo.html",
  "size_bytes": 12345,
  "sha256": "…",
  "destination_name": "my_demo.html",
  "subdirectory": "ai"
}
```

## Security

- Source must be a **regular file** (no symlinks, FIFOs, sockets, devices)
  **under an approved root** — `..` traversal and absolute escapes rejected.
- Destination is always under `public/`; names are sanitized (no path
  separators, no leading dot, ≤150 chars).
- **Size cap 500MB** (`PUBLISH_FILE_MAX_BYTES` env).
- **Atomic write**: temp file + `os.replace`; world-readable (644),
  never executable.
- sha256 computed during the copy.

## Usage

```bash
curl -s -X POST http://192.168.4.54:8091/skills/publish_file \
  -H "X-Api-Key: $SIRI_API_KEY" -H 'Content-Type: application/json' \
  -d '{"params": {"source_path": "/home/chuck/data/media/generated/pipeline/smoke_test/keyframe.png",
       "destination_name": "banana_keyframe.png", "subdirectory": "images"}}'
```
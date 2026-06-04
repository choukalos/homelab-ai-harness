# filetools — Local Workspace File Access Tools

Constrained file system operations scoped to a configurable `WORKSPACE` directory tree. All paths are **relative to the workspace root** — path traversal outside the workspace is blocked with `403 Forbidden`.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `WORKSPACE` | `/home/chuck/workspace` | Root directory the harness is allowed to access |

The workspace is mounted into the container via the compose file volume.

## Endpoints

All endpoints are under `/files` and require `HARNESS_API_KEY` authentication.

---

### `POST /files/ls` — List Directory Contents

List files and directories within the workspace.

**Request body:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `path` | `str` | `""` (root) | Relative path within workspace |
| `recursive` | `bool` | `false` | Walk subdirectories |
| `max_depth` | `int` | `3` | Max depth for recursive listing (1–10) |
| `include_hidden` | `bool` | `false` | Show dotfiles/dirs |

```jsonc
{
  "path": "code/my-project",
  "recursive": true,
  "max_depth": 2
}
```

**Response:**

```jsonc
{
  "path": "code/my-project",
  "entries": [
    { "name": "src", "path": "code/my-project/src", "is_dir": true },
    { "name": "main.py", "path": "code/my-project/main.py", "is_dir": false, "size": 42 }
  ]
}
```

---

### `POST /files/search` — Search Files

Search by filename pattern (glob) or text content (grep-like).

**Request body:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `path` | `str` | `""` (root) | Directory to search within |
| `pattern` | `str` | `""` | Filename glob pattern (`*`, `?`) |
| `content` | `str` | `""` | Text to grep for in file contents |
| `case_sensitive` | `bool` | `false` | Case-sensitive matching |
| `max_results` | `int` | `50` | Cap on results (1–200) |
| `extensions` | `str[]` | `null` | Filter by extensions, e.g. `[".py"]` |

```jsonc
{
  "pattern": "*.py",
  "extensions": [".py"],
  "max_results": 20
}
```

Or content search:

```jsonc
{
  "content": "def handle_request",
  "extensions": [".py"],
  "max_results": 10
}
```

**Response:**

```jsonc
{
  "results": [
    { "path": "src/handler.py", "match_type": "content", "line_number": 42, "preview": "def handle_request(req):" }
  ],
  "total": 1
}
```

---

### `POST /files/read` — Read a File

Read a text file with optional line-range slicing.

**Request body:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `path` | `str` | _(required)_ | Relative path to the file |
| `start_line` | `int` | `null` | Start reading from 1-indexed line |
| `max_lines` | `int` | `null` | Max lines to return (max 5000) |

```jsonc
{
  "path": "code/my-project/main.py",
  "start_line": 10,
  "max_lines": 30
}
```

**Response:**

```jsonc
{
  "path": "code/my-project/main.py",
  "content": "line 10...\nline 11...\n",
  "lines": 30
}
```

---

### `POST /files/write` — Create or Overwrite a File

Write a full file. Creates parent directories if they don't exist.

**Request body:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `path` | `str` | _(required)_ | Relative path (file will be created) |
| `content` | `str` | _(required)_ | Full file contents |
| `create_dirs` | `bool` | `true` | Create parent directories |

```jsonc
{
  "path": "code/my-project/tests/test_main.py",
  "content": "import pytest\n\ndef test_foo():\n    assert True"
}
```

---

### `POST /files/update` — Patch File via String Replacement

Replace exact text within an existing file. The old text must match exactly. This is the primary fine-grained editing tool.

**Request body:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `path` | `str` | _(required)_ | Relative path to the file |
| `old_text` | `str` | _(required)_ | Exact text to find and replace |
| `new_text` | `str` | _(required)_ | Replacement text |

```jsonc
{
  "path": "code/my-project/main.py",
  "old_text": "def main():\n    print(\"hello\")",
  "new_text": "def main():\n    print(\"hello, world\")\n    return 0"
}
```

---

### `POST /files/delete` — Delete File or Directory

**Request body:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `path` | `str` | _(required)_ | Relative path |
| `recursive` | `bool` | `false` | Required for directory deletion |

> **Security:** Deleting the workspace root itself is always blocked (403).

---

### `POST /files/diff` — Compare Two Files

Generate a unified diff between two files in the workspace.

**Request body:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `path_a` | `str` | _(required)_ | First file |
| `path_b` | `str` | _(required)_ | Second file |
| `unified` | `bool` | `true` | Unified diff format |

---

### `POST /files/patch` — Apply a Unified Diff Patch

Apply a unified diff (as generated by `diff` or external `diff` tools) to a file. Creates a `.bak` backup automatically.

**Request body:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `path` | `str` | _(required)_ | Target file to patch |
| `patch` | `str` | _(required)_ | Unified diff text |
| `backup` | `bool` | `true` | Create `.bak` backup |

---

## Notes for Future Workflow Integration

When building LLM-driven workflows (e.g., agent loops, research pipelines, code generation) that need workspace file access, here's how these endpoints map to typical agent capability patterns:

### Read-Modify-Write Pattern (code editing, config updates)

1. **`/files/read`** — Read the current file (use `start_line` + `max_lines` to avoid token bloat on large files)
2. **LLM step** — LLM decides what changes to make
3. **`/files/update`** — Apply targeted replacements via `old_text` / `new_text`
4. **Verify** — Re-`/files/read` to confirm changes took effect

This is safer than full `/files/write` because you preserve the rest of the file. If the LLM needs to rewrite the entire file, `/files/write` is available.

### Discovery Pattern (finding relevant files)

1. **`/files/ls`** (recursive) — Map the workspace structure
2. **`/files/search`** (pattern) — Find files by name (e.g., `*.py`, `Dockerfile*`)
3. **`/files/search`** (content) — Grep for specific strings/functions/classes across the codebase
4. Feed discovered file paths back to the LLM for the next step

### Diff/Patch Pattern (change management)

1. **`/files/read`** two versions (or `/files/diff`)
2. Generate or review a unified diff string
3. **`/files/patch`** to apply it — useful when the LLM generates patch output directly

### Token Budget Tips

- Large files: always use `start_line` + `max_lines` on `/files/read` instead of pulling the whole thing
- `/files/search` has a configurable `max_results` (default 50, max 200) to keep responses bounded
- Consider streaming the LLM's "read then decide" pattern: read a section, ask the LLM if it needs more, continue reading in chunks
- `/files/update` is the most LLM-friendly editing primitive — the LLM only needs to output the exact strings to replace

### Typical Agent Loop Pseudocode

```
while not done:
    observation = tool_call()          # ls, search, read, diff, etc.
    decision = llm(observe + plan)     # "what next?"
    tool_call(decision.action)         # update, write, patch, etc.
```

Each `/files/*` endpoint is a single JSON POST — easy to wrap in a tool definition for any LLM framework (tool-calling, ReAct, function-calling, etc.).

### Security Notes

- All paths are sandboxed to `WORKSPACE` — `../` traversal is detected and returns 403
- Workspace root deletion is blocked
- All endpoints require `HARNESS_API_KEY` auth
- Volume mount is `:rw` — if you want read-only access for certain workflows, mount as `:ro` (write/update/delete/patch will fail naturally)

#!/usr/bin/env python3
"""mcp-verify.py — verify every MCP tool exposed via the LiteLLM proxy.

Runs a safe test call against each MCP tool (read-only tools get a real
call; write/costly tools are skipped or tested via intentional error
paths) and prints a per-tool status table.

Usage:
  scripts/mcp-verify.py                          # run the full matrix
  scripts/mcp-verify.py list                     # print tool names + schemas
  scripts/mcp-verify.py call TOOL '<json-args>'  # call one tool

Exit code: 0 if no transport failures, 1 if any tool failed to respond.

Requires LITELLM_MASTER_KEY in the repo .env (or the LITELLM_MASTER_KEY
env var). LiteLLM proxy must be running on localhost:4000.
"""
import json
import os
import queue
import shutil
import sys
import threading
import time
import urllib.request

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE = os.environ.get("LITELLM_BASE", "http://localhost:4000")
ENV_FILE = os.environ.get(
    "HOMELAB_ENV",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 ".env"))


def load_key():
    if os.environ.get("LITELLM_MASTER_KEY"):
        return os.environ["LITELLM_MASTER_KEY"]
    try:
        with open(ENV_FILE) as f:
            for line in f:
                if line.startswith("LITELLM_MASTER_KEY="):
                    return line.split("=", 1)[1].strip()
    except OSError:
        pass
    raise SystemExit(
        f"LITELLM_MASTER_KEY not found in env or {ENV_FILE}")


KEY = load_key()

# ---------------------------------------------------------------------------
# MCP-over-SSE plumbing (LiteLLM /mcp endpoint)
# ---------------------------------------------------------------------------

events = queue.Queue()
msg_path = None


def sse_reader():
    req = urllib.request.Request(
        f"{BASE}/mcp/sse",
        headers={"Authorization": f"Bearer {KEY}",
                 "Accept": "text/event-stream"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            event_type = None
            data_lines = []
            for raw in resp:
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                if line.startswith("event:"):
                    event_type = line[6:].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[5:].strip())
                elif line == "":
                    if event_type:
                        events.put((event_type, "\n".join(data_lines)))
                    event_type, data_lines = None, []
    except Exception as e:
        events.put(("__error__", str(e)))


def post(payload):
    req = urllib.request.Request(
        f"{BASE}{msg_path}",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {KEY}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return resp.status


def wait_message(want_id, timeout=180):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            etype, data = events.get(timeout=1)
        except queue.Empty:
            continue
        if etype == "__error__":
            raise RuntimeError(f"SSE stream error: {data}")
        if etype != "message":
            continue
        try:
            msg = json.loads(data)
        except json.JSONDecodeError:
            continue
        if msg.get("id") == want_id:
            return msg
    raise TimeoutError(f"no response for id={want_id}")


def setup():
    global msg_path
    t = threading.Thread(target=sse_reader, daemon=True)
    t.start()
    while True:
        etype, data = events.get(timeout=30)
        if etype == "__error__":
            raise RuntimeError(f"SSE error: {data}")
        if etype == "endpoint":
            msg_path = data
            break
    post({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "mcp-verify", "version": "1.0"},
        },
    })
    wait_message(1)
    post({"jsonrpc": "2.0", "method": "notifications/initialized"})


def call_tool(name, args, rid=100, timeout=180):
    post({"jsonrpc": "2.0", "id": rid, "method": "tools/call",
          "params": {"name": name, "arguments": args}})
    return wait_message(rid, timeout=timeout)


def summarize(res):
    if "error" in res:
        return {"isError": True,
                "head": f"RPC ERROR: {json.dumps(res['error'])[:200]}"}
    out = res.get("result", {})
    content = out.get("content", [])
    text = "".join(c.get("text", "") for c in content
                   if c.get("type") == "text")
    return {"isError": bool(out.get("isError")),
            "chars": len(text), "head": text[:200]}


# ---------------------------------------------------------------------------
# Test matrix
# ---------------------------------------------------------------------------
# (tool, args, note) — note explains expected outcome / why
MATRIX = [
    # --- mcp_search ---
    ("mcp_search-search_web", {"query": "docker compose", "max_results": 2}, ""),
    ("mcp_search-search_recent", {"query": "docker", "days": 7, "max_results": 2}, ""),
    ("mcp_search-search_news", {"query": "docker", "max_results": 2}, ""),

    # --- mcp_filesystem_readonly ---
    ("mcp_filesystem_readonly-list_directory",
     {"path": "/home/chuck/workspace"}, ""),
    ("mcp_filesystem_readonly-read_file",
     {"path": "/home/chuck/workspace/code/invest-hub/README.md"}, ""),
    ("mcp_filesystem_readonly-search_files",
     {"pattern": "**/*.md",
      "path": "/home/chuck/data/media/gtm_strategies"}, ""),

    # --- mcp_skills ---
    ("mcp_skills-list_skills", {}, ""),
    ("mcp_skills-get_skill_job",
     {"job_id": "does-not-exist-verify-plumbing"}, "expect clean error"),

    # --- mcp_crawl ---
    ("mcp_crawl-crawl_page",
     {"url": "https://example.com", "max_chars": 200}, ""),

    # --- mcp_vision ---
    ("mcp_vision-vision_probe", {}, "self-test (1x1 png, cap detection)"),
    ("mcp_vision-vision_cleanup", {}, "dry (only deletes >7d old)"),
    ("mcp_vision-vision_analyze_image",
     {"source": "https://example.com/missing.png", "prompt": "describe"},
     "expect clean error (bad source)"),
    ("mcp_vision-vision_extract_frames",
     {"source": "https://example.com/missing.mp4"},
     "expect clean error (bad source)"),
    ("mcp_vision-vision_analyze_video",
     {"source": "https://example.com/missing.mp4"},
     "expect clean error (bad source)"),

    # --- mcp_media (cheap reads only; generation skipped) ---
    ("mcp_media-media_list_voices", {}, ""),
    ("mcp_media-media_info", {"path": "/nonexistent/probe.mp4"},
     "expect clean error (bad path)"),
    ("mcp_media-media_job_result",
     {"job_id": "does-not-exist-verify-plumbing"}, "expect clean error"),

    # --- mcp_filesystem (scratch write + cleanup) ---
    ("mcp_filesystem-list_directory", {"path": "/home/chuck/workspace"}, ""),
    ("mcp_filesystem-write_file",
     {"path": "/home/chuck/workspace/.mcp_verify_write.txt",
      "content": "mcp verify ok\n"}, "scratch write"),
    ("mcp_filesystem-read_file",
     {"path": "/home/chuck/workspace/.mcp_verify_write.txt"},
     "read back scratch"),
    ("mcp_filesystem-create_directory",
     {"path": "/home/chuck/workspace/.mcp_verify_dir"}, "scratch dir"),
    ("mcp_filesystem-delete_file",
     {"path": "/home/chuck/workspace/.mcp_verify_write.txt"},
     "cleanup scratch"),

    # --- mcp_mysql ---
    ("mcp_mysql-list_databases", {}, ""),
    ("mcp_mysql-run_query",
     {"database": "information_schema", "sql": "SELECT 1 AS ok"}, ""),
    ("mcp_mysql-schema_overview", {"database": "information_schema"},
     "hardened: skips unreadable tables with notes"),
    ("mcp_mysql-explain_sql",
     {"database": "information_schema",
      "natural_language": "count the databases"}, "LLM->SQL, read-only"),
    ("mcp_mysql-nl_to_sql_then_run",
     {"database": "information_schema",
      "question": "how many databases are there?"}, "LLM->SQL, read-only"),

    # --- mcp_memory ---
    ("mcp_memory-memory_list", {}, ""),
    ("mcp_memory-memory_search", {"query": "homelab", "top_k": 2}, ""),

    # --- mcp_knowledge (reads + dry-run forget) ---
    ("mcp_knowledge-kb_overview", {}, ""),
    ("mcp_knowledge-kb_list_documents", {}, ""),
    ("mcp_knowledge-kb_search", {"query": "homelab", "top_k": 2}, ""),
    ("mcp_knowledge-kb_recent_changes", {}, ""),
    ("mcp_knowledge-kb_digest_list", {}, ""),
    ("mcp_knowledge-kb_forget",
     {"query": "zzz-nonexistent-fact-verify-plumbing"},
     "dry-run (confirm=false)"),

    # --- mcp_homelab_status ---
    ("mcp_homelab_status-docker_ps", {}, ""),
    ("mcp_homelab_status-system_info", {}, ""),
    ("mcp_homelab_status-service_status", {"service_name": "crawl4ai"}, ""),
    ("mcp_homelab_status-container_logs",
     {"service_name": "crawl4ai", "tail": 3}, ""),
]

# Tools deliberately NOT invoked (cost / destructive / long-running)
SKIPS = [
    ("mcp_skills-run_skill", "executes a real skill job (can be long/heavy)"),
    ("mcp_media-media_storyboard", "LLM generation (cost)"),
    ("mcp_media-media_generate_image", "image generation (cost)"),
    ("mcp_media-media_edit_image", "image generation (cost)"),
    ("mcp_media-media_generate_shot", "video generation (minutes)"),
    ("mcp_media-media_text_to_speech", "TTS generation (cost)"),
    ("mcp_media-media_add_voice", "writes a voice profile"),
    ("mcp_media-media_delete_voice", "destructive"),
    ("mcp_media-media_generate_music", "music generation (cost)"),
    ("mcp_media-media_sfx", "video + generation (cost)"),
    ("mcp_media-media_upscale_video", "long GPU job"),
    ("mcp_media-media_assemble", "long GPU job"),
    ("mcp_media-media_job_result", "needs a real job_id"),
    ("mcp_media-media_fetch", "downloads from GPU host (side effect)"),
    ("mcp_media-media_trim", "GPU render job"),
    ("mcp_media-media_freeze", "GPU render job"),
    ("mcp_media-media_caption", "GPU render job"),
    ("mcp_media-media_upload", "uploads to GPU host (side effect)"),
    ("mcp_media-media_download", "downloads to GPU host (side effect)"),
    ("mcp_media-media_put", "uploads staging file (side effect)"),
    ("mcp_media-media_pull", "pulls from GPU host (side effect)"),
    ("mcp_mysql-list_tables", "covered by schema_overview"),
    ("mcp_mysql-describe_table", "covered by schema_overview"),
    ("mcp_mysql-foreign_keys", "covered by schema_overview"),
    ("mcp_mysql-list_indexes", "covered by schema_overview"),
    ("mcp_mysql-sample_table", "covered by schema_overview"),
    ("mcp_mysql-run_query_to_csv", "writes a CSV; same path as run_query"),
    ("mcp_knowledge-kb_get_document",
     "needs a real source id; kb_list_documents verifies the index"),
    ("mcp_knowledge-kb_add_fact", "writes to the family KB"),
    ("mcp_knowledge-kb_ingest_file", "writes to the family KB"),
    ("mcp_knowledge-kb_delete_document", "destructive on family KB"),
    ("mcp_knowledge-kb_correct", "modifies the family KB"),
    ("mcp_knowledge-kb_backup", "writes a timestamped snapshot (heavy)"),
    ("mcp_knowledge-kb_digest", "LLM digest job"),
    ("mcp_knowledge-kb_get_pages", "needs a real source + page range"),
    ("mcp_knowledge-kb_digest_store", "writes a digest"),
    ("mcp_knowledge-kb_digest_get",
     "needs a real slug; kb_digest_list verifies the store"),
]


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_list():
    setup()
    post({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    tl = wait_message(2)
    for t in tl["result"]["tools"]:
        sch = t.get("inputSchema", {})
        print(json.dumps({
            "name": t["name"],
            "required": sch.get("required", []),
            "properties": {k: v.get("type", v)
                           for k, v in sch.get("properties", {}).items()},
        }))
    return 0


def cmd_call(name, args):
    setup()
    res = call_tool(name, args)
    print(json.dumps(summarize(res), indent=2, default=str)[:2500])
    return 0


def cmd_matrix():
    setup()
    results = []
    rid = 100
    for tool, args, note in MATRIX:
        rid += 1
        t0 = time.time()
        try:
            s = summarize(call_tool(tool, args, rid=rid))
            status = "ERR " if s["isError"] else "OK  "
            detail = s["head"][:110].replace("\n", " ")
        except Exception as e:
            status = "FAIL"
            detail = f"{type(e).__name__}: {e}"[:110]
        line = (f"{status} {tool:48s} {time.time()-t0:5.1f}s  "
                f"{note}  {detail}")
        print(line, flush=True)
        results.append((status, tool, detail))

    # best-effort scratch cleanup (delete_file can't remove dirs)
    shutil.rmtree("/home/chuck/workspace/.mcp_verify_dir", ignore_errors=True)

    ok = sum(1 for r in results if r[0] == "OK  ")
    err = sum(1 for r in results if r[0] == "ERR ")
    fail = sum(1 for r in results if r[0] == "FAIL")
    print(f"\n=== {ok} OK, {err} tool-errors, {fail} transport-failures, "
          f"{len(SKIPS)} skipped ===")
    if fail:
        print("FAILURES:")
        for r in results:
            if r[0] == "FAIL":
                print(f"  {r[1]}: {r[2]}")
    return 1 if fail else 0


def main():
    if len(sys.argv) > 1:
        if sys.argv[1] == "list":
            return cmd_list()
        if sys.argv[1] == "call" and len(sys.argv) >= 3:
            args = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
            return cmd_call(sys.argv[2], args)
        raise SystemExit(
            "usage: mcp-verify.py [list | call TOOL '<json-args>']")
    return cmd_matrix()


if __name__ == "__main__":
    sys.exit(main())
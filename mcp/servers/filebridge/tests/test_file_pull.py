"""file_pull via the MCP face (P12-B) — all 4 source types, D13, caps."""

from __future__ import annotations

import os

from conftest import call_tool, rpc


# ---------------------------------------------------------------------------
# MCP face: discovery
# ---------------------------------------------------------------------------


async def test_tools_list(full_stub):
    res = await rpc(full_stub.client, "tools/list", {}, _id=1)
    assert "result" in res, res
    names = {t["name"] for t in res["result"]["tools"]}
    assert {"file_pull", "file_push", "file_work_areas",
            "file_targets"} <= names


async def test_initialize(full_stub):
    res = await rpc(full_stub.client, "initialize", {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    }, _id=1)
    assert res["result"]["serverInfo"]["name"] == "mcp_filebridge"


async def test_file_work_areas(full_stub):
    out = await call_tool(full_stub.client, "file_work_areas", {})
    areas = {a["name"]: a for a in out["work_areas"]}
    assert set(areas) == {"media_staging", "pipeline_fetch", "siri_outputs",
                          "nas_media_store", "matrix_pipeline"}
    assert areas["siri_outputs"]["remote_write"] is False
    assert areas["siri_outputs"]["writable"] is False
    assert areas["nas_media_store"]["automount"] is True
    assert areas["nas_media_store"]["shared_output"] is True
    assert areas["matrix_pipeline"]["api"] == full_stub.url
    assert "path" not in areas["matrix_pipeline"]


async def test_file_targets(full_stub):
    out = await call_tool(full_stub.client, "file_targets", {})
    targets = {t["name"]: t for t in out["publish_targets"]}
    assert set(targets) == {"blog", "nas"}
    assert targets["blog"]["root"] == str(full_stub.media_root / "public")
    assert targets["blog"]["subdirs"] == ["ai", "images", "audio", "video",
                                          "tabs"]
    assert targets["blog"]["size_cap_mb"] == 100
    assert targets["nas"]["root"] == str(full_stub.naspub)
    assert targets["nas"]["url_base"] == ""


# ---------------------------------------------------------------------------
# file_pull — the 4 source types
# ---------------------------------------------------------------------------


async def test_pull_url(full_stub):
    """source = arbitrary http URL (decision 2a parity)."""
    out = await call_tool(full_stub.client, "file_pull", {
        "source": f"{full_stub.url}/raw/hello.mp4",
        "work_area": "media_staging"})
    assert "error" not in out, out
    p = full_stub.staging / "hello.mp4"
    assert out["local_path"] == str(p)
    assert p.read_bytes() == bytes(range(256)) * 2
    assert out["size_bytes"] == 512
    assert out["source_type"] == "url"


async def test_pull_pipeline_token(full_stub):
    """source = bare Matrix /dl token -> relayed from Matrix (LAN)."""
    out = await call_tool(full_stub.client, "file_pull", {
        "source": "goodtoken", "work_area": "pipeline_fetch"})
    assert "error" not in out, out
    p = full_stub.fetch / "out.mp4"  # name from Content-Disposition
    assert out["local_path"] == str(p)
    assert p.read_bytes() == bytes(range(256)) * 4
    assert out["source_type"] == "pipeline_token"


async def test_pull_pipeline_path_relative(full_stub):
    """source = relative media_jobs path -> Matrix /files (LAN). /files is
    relative to the pipeline's job dir, so media_jobs/job123/out.mp4 ->
    /files/job123/out.mp4 (Matrix convention)."""
    full_stub.stub.files["job123/out.mp4"] = b"PIPE-FILE-BYTES"
    out = await call_tool(full_stub.client, "file_pull", {
        "source": "media_jobs/job123/out.mp4", "work_area": "pipeline_fetch"})
    assert "error" not in out, out
    assert out["local_path"] == str(full_stub.fetch / "out.mp4")
    assert (full_stub.fetch / "out.mp4").read_bytes() == b"PIPE-FILE-BYTES"
    assert out["source_type"] == "pipeline_path"


async def test_pull_pipeline_path_absolute(full_stub):
    full_stub.stub.files["job123/out.mp4"] = b"PIPE-FILE-BYTES"
    out = await call_tool(full_stub.client, "file_pull", {
        "source": "/home/chuck/data/comfyui/run/media_jobs/job123/out.mp4",
        "work_area": "pipeline_fetch"})
    assert "error" not in out, out
    assert out["local_path"] == str(full_stub.fetch / "out.mp4")


async def test_pull_work_area_path(full_stub):
    """source = a path under a registered work area -> local copy."""
    out = await call_tool(full_stub.client, "file_pull", {
        "source": str(full_stub.staging / "staged.mp4"),
        "work_area": "nas_media_store"})
    assert "error" not in out, out
    assert out["local_path"] == str(full_stub.nas / "staged.mp4")
    assert (full_stub.nas / "staged.mp4").read_bytes() \
        == b"STAGED-FILE-CONTENT"
    assert out["source_type"] == "work_area_path"


async def test_pull_collision_suffix_never_overwrite(full_stub):
    await call_tool(full_stub.client, "file_pull", {
        "source": f"{full_stub.url}/raw/hello.mp4",
        "work_area": "media_staging"})
    first = full_stub.staging / "hello.mp4"
    original = first.read_bytes()
    out = await call_tool(full_stub.client, "file_pull", {
        "source": f"{full_stub.url}/raw/hello.mp4",
        "work_area": "media_staging"})
    assert out["local_path"] == str(full_stub.staging / "hello_2.mp4")
    assert first.read_bytes() == original  # untouched
    assert (full_stub.staging / "hello_2.mp4").read_bytes() == original


# ---------------------------------------------------------------------------
# guards
# ---------------------------------------------------------------------------


async def test_pull_d13_dest_rejected(full_stub):
    out = await call_tool(full_stub.client, "file_pull", {
        "source": str(full_stub.staging / "staged.mp4"),
        "work_area": "siri_outputs"})
    assert "error" in out
    assert "D13" in out["error"]


async def test_pull_unknown_dest(full_stub):
    out = await call_tool(full_stub.client, "file_pull", {
        "source": str(full_stub.staging / "staged.mp4"),
        "work_area": "nope"})
    assert "error" in out and "unknown work area" in out["error"]


async def test_pull_api_area_dest_rejected(full_stub):
    out = await call_tool(full_stub.client, "file_pull", {
        "source": str(full_stub.staging / "staged.mp4"),
        "work_area": "matrix_pipeline"})
    assert "error" in out and "API area" in out["error"]


async def test_pull_source_outside_areas_default_deny(full_stub, tmp_path):
    stray = tmp_path / "stray.mp4"
    stray.write_bytes(b"STRAY")
    out = await call_tool(full_stub.client, "file_pull", {
        "source": str(stray), "work_area": "media_staging"})
    assert "error" in out  # not a URL/token/media_jobs path; not under an area


async def test_pull_missing_work_area_file(full_stub):
    out = await call_tool(full_stub.client, "file_pull", {
        "source": str(full_stub.staging / "missing.mp4"),
        "work_area": "nas_media_store"})
    assert "error" in out and "not found" in out["error"]


async def test_pull_bad_pipeline_token_404(full_stub):
    out = await call_tool(full_stub.client, "file_pull", {
        "source": "badtoken", "work_area": "pipeline_fetch"})
    assert "error" in out and "HTTP 404" in out["error"]


async def test_pull_audit_log_one_line_json(full_stub, caplog):
    import logging

    with caplog.at_level(logging.INFO, logger="filebridge.fileops"):
        await call_tool(full_stub.client, "file_pull", {
            "source": str(full_stub.staging / "staged.mp4"),
            "work_area": "nas_media_store"})
    lines = [r.message for r in caplog.records
             if r.message.startswith("{") and '"event"' in r.message]
    assert lines, "no one-line JSON audit entry"
    import json
    entry = json.loads(lines[-1])
    assert entry["event"] == "file_pull"
    assert entry["status"] == "ok"
    assert entry["work_area"] == "nas_media_store"
    assert "ts" in entry

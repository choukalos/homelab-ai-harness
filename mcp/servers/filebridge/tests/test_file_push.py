"""file_push via the MCP face (P12-B) — work area / matrix / client(1b) /
publish targets; D13 + source_roots guards."""

from __future__ import annotations

import hashlib

from conftest import call_tool


# ---------------------------------------------------------------------------
# destination = work area
# ---------------------------------------------------------------------------


async def test_push_work_area(full_stub):
    out = await call_tool(full_stub.client, "file_push", {
        "file": str(full_stub.staging / "staged.mp4"),
        "destination": "nas_media_store"})
    assert "error" not in out, out
    assert out["local_path"] == str(full_stub.nas / "staged.mp4")
    assert (full_stub.nas / "staged.mp4").read_bytes() \
        == b"STAGED-FILE-CONTENT"
    assert out["size_bytes"] == len(b"STAGED-FILE-CONTENT")


# ---------------------------------------------------------------------------
# destination = matrix_pipeline
# ---------------------------------------------------------------------------


async def test_push_matrix(full_stub):
    out = await call_tool(full_stub.client, "file_push", {
        "file": str(full_stub.staging / "staged.mp4"),
        "destination": "matrix_pipeline"})
    assert "error" not in out, out
    assert out["path"].startswith("media_jobs/uploads/")
    assert out["location"] == "gpu_host"
    # the stub actually received a multipart with the file bytes
    up = full_stub.stub.uploads[-1]
    assert up["headers"].get("X-Api-Key") is None  # stripped
    assert b"STAGED-FILE-CONTENT" in up["body"]
    assert b'filename="staged.mp4"' in up["body"]


# ---------------------------------------------------------------------------
# destination = client (1b signed token)
# ---------------------------------------------------------------------------


async def test_push_client_mints_serving_token(full_stub):
    out = await call_tool(full_stub.client, "file_push", {
        "file": str(full_stub.staging / "staged.mp4"),
        "destination": "client"})
    assert "error" not in out, out
    assert out["url"].startswith(
        "https://siri.choukalos.com/media/files/dl/")
    assert out["url"].endswith("/" + out["token"])
    assert out["ttl_hours"] == 24
    # the minted token serves the file through Face 1 (the 1b route)
    path = "/media/files" + out["url"].rsplit("/media/files", 1)[-1]
    r = await full_stub.client.get(path)
    assert r.status_code == 200
    assert r.content == b"STAGED-FILE-CONTENT"


async def test_push_client_custom_ttl(full_stub):
    out = await call_tool(full_stub.client, "file_push", {
        "file": str(full_stub.staging / "staged.mp4"),
        "destination": "client", "ttl_hours": 2})
    assert "error" not in out, out
    assert out["ttl_hours"] == 2


async def test_push_client_ttl_clamp(full_stub):
    for bad in (0.5, 500):
        out = await call_tool(full_stub.client, "file_push", {
            "file": str(full_stub.staging / "staged.mp4"),
            "destination": "client", "ttl_hours": bad})
        assert "error" in out, out


async def test_push_client_siri_file_rejected_d13(full_stub):
    """No public tokens for siri_outputs files — all callers (D13)."""
    f = full_stub.siri / "q_a.txt"
    f.write_bytes(b"SIRI-PRIVATE")
    out = await call_tool(full_stub.client, "file_push", {
        "file": str(f), "destination": "client"})
    assert "error" in out
    assert "D13" in out["error"]


# ---------------------------------------------------------------------------
# destination = publish target (blog / nas)
# ---------------------------------------------------------------------------


async def test_push_publish_blog(full_stub):
    out = await call_tool(full_stub.client, "file_push", {
        "file": str(full_stub.staging / "staged.mp4"),
        "destination": "blog"})
    assert "error" not in out, out
    rep = out["report"]
    assert rep["path"] == str(full_stub.media_root / "public" / "ai" /
                              "staged.mp4")
    assert rep["url"] == "https://choukalos.com/files/ai/staged.mp4"
    assert rep["sha256"] == hashlib.sha256(b"STAGED-FILE-CONTENT").hexdigest()
    assert (full_stub.media_root / "public" / "ai" /
            "staged.mp4").read_bytes() == b"STAGED-FILE-CONTENT"


async def test_push_publish_blog_subdirectory(full_stub):
    out = await call_tool(full_stub.client, "file_push", {
        "file": str(full_stub.staging / "staged.mp4"),
        "destination": "blog", "subdirectory": "images"})
    assert "error" not in out, out
    assert out["report"]["url"].endswith("/files/images/staged.mp4")


async def test_push_publish_duplicate(full_stub):
    await call_tool(full_stub.client, "file_push", {
        "file": str(full_stub.staging / "staged.mp4"),
        "destination": "blog"})
    out = await call_tool(full_stub.client, "file_push", {
        "file": str(full_stub.staging / "staged.mp4"),
        "destination": "blog"})
    assert "error" not in out, out
    assert out["report"]["duplicate"] is True


async def test_push_publish_conflict_different_content(full_stub):
    await call_tool(full_stub.client, "file_push", {
        "file": str(full_stub.staging / "staged.mp4"),
        "destination": "blog"})
    (full_stub.staging / "staged.mp4").write_bytes(b"DIFFERENT-CONTENT")
    out = await call_tool(full_stub.client, "file_push", {
        "file": str(full_stub.staging / "staged.mp4"),
        "destination": "blog"})
    assert "error" in out and "different content" in out["error"]


async def test_push_publish_bad_subdir(full_stub):
    out = await call_tool(full_stub.client, "file_push", {
        "file": str(full_stub.staging / "staged.mp4"),
        "destination": "blog", "subdirectory": "nope"})
    assert "error" in out and "not allowed for this target" in out["error"]
    out = await call_tool(full_stub.client, "file_push", {
        "file": str(full_stub.staging / "staged.mp4"),
        "destination": "blog", "subdirectory": "files"})
    assert "error" in out and "'files' is not a valid subdirectory" \
        in out["error"]


async def test_push_publish_nas(full_stub):
    out = await call_tool(full_stub.client, "file_push", {
        "file": str(full_stub.staging / "staged.mp4"),
        "destination": "nas"})
    assert "error" not in out, out
    assert out["report"]["path"] == str(full_stub.naspub / "staged.mp4")
    assert out["report"]["url"] in (None, "")  # nas target is not public
    assert (full_stub.naspub / "staged.mp4").read_bytes() \
        == b"STAGED-FILE-CONTENT"


async def test_push_publish_source_roots_reject(full_stub):
    """A file under a work area that is NOT in blog's source_roots
    (nas_media_store) -> rejected (default-deny beyond the work-area
    check)."""
    f = full_stub.nas / "from_nas.mp4"
    f.write_bytes(b"NAS-FILE")
    out = await call_tool(full_stub.client, "file_push", {
        "file": str(f), "destination": "blog"})
    assert "error" in out and "source_roots" in out["error"]


# ---------------------------------------------------------------------------
# guards
# ---------------------------------------------------------------------------


async def test_push_d13_dest_rejected(full_stub):
    out = await call_tool(full_stub.client, "file_push", {
        "file": str(full_stub.staging / "staged.mp4"),
        "destination": "siri_outputs"})
    assert "error" in out and "D13" in out["error"]


async def test_push_unknown_destination(full_stub):
    out = await call_tool(full_stub.client, "file_push", {
        "file": str(full_stub.staging / "staged.mp4"),
        "destination": "nope"})
    assert "error" in out and "unknown destination" in out["error"]


async def test_push_file_not_under_area_default_deny(full_stub, tmp_path):
    stray = tmp_path / "stray.mp4"
    stray.write_bytes(b"STRAY")
    out = await call_tool(full_stub.client, "file_push", {
        "file": str(stray), "destination": "nas_media_store"})
    assert "error" in out and "not under a registered work area" \
        in out["error"]


async def test_push_missing_file(full_stub):
    out = await call_tool(full_stub.client, "file_push", {
        "file": str(full_stub.staging / "missing.mp4"),
        "destination": "nas_media_store"})
    assert "error" in out and "not found" in out["error"]

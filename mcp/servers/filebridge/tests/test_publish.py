"""P12-C — the publish engine (extracted + parameterized), the
file_publish MCP tool, and the POST /publish endpoint (ai-net only).

Ports the original skills/publish_file/test_skill.py cases to the engine
(subdir enum, 'files' ban, idempotent republish, overwrite force flag)
plus parameterization (blog + nas), the adapter protocol check, and the
two call surfaces (MCP tool + HTTP endpoint).
"""

from __future__ import annotations

import hashlib
import logging

import publish_engine as pe
from conftest import call_tool

BLOG_SUBDIRS = ["ai", "images", "audio", "video", "tabs"]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Engine — blog target (exact publish-file behavior preserved)
# ---------------------------------------------------------------------------


def test_engine_publish_new_blog(full_stub):
    src = full_stub.staging / "staged.mp4"
    out = pe.publish(full_stub.doc, "blog", src)
    assert "error" not in out
    assert "published" in out["summary"]
    rep = out["report"]
    assert rep["path"] == str(full_stub.media_root / "public" / "ai" /
                              "staged.mp4")
    assert rep["url"] == "https://choukalos.com/files/ai/staged.mp4"
    assert rep["sha256"] == _sha256(b"STAGED-FILE-CONTENT")
    assert rep["size_bytes"] == len(b"STAGED-FILE-CONTENT")
    assert rep["destination_name"] == "staged.mp4"
    assert rep["subdirectory"] == "ai"
    assert rep.get("duplicate") is not True
    dest = full_stub.media_root / "public" / "ai" / "staged.mp4"
    assert dest.read_bytes() == b"STAGED-FILE-CONTENT"
    assert oct(dest.stat().st_mode & 0o777) == "0o644"  # world-readable
    assert out["artifact_path"] == str(dest)


def test_engine_default_subdir_is_ai(full_stub):
    """subdirectory='' -> the target's default ('ai' for blog)."""
    src = full_stub.staging / "staged.mp4"
    out = pe.publish(full_stub.doc, "blog", src, subdirectory="")
    assert out["report"]["subdirectory"] == "ai"
    assert out["report"]["url"].endswith("/files/ai/staged.mp4")


def test_engine_duplicate_identical_content_is_noop_success(full_stub):
    src = full_stub.staging / "staged.mp4"
    r1 = pe.publish(full_stub.doc, "blog", src)
    dest = full_stub.media_root / "public" / "ai" / "staged.mp4"
    mtime_before = dest.stat().st_mtime_ns
    r2 = pe.publish(full_stub.doc, "blog", src)
    assert "error" not in r2
    assert r2["report"]["duplicate"] is True
    assert "already published" in r2["summary"].lower()
    assert "no-op" in r2["summary"].lower()
    assert dest.stat().st_mtime_ns == mtime_before  # no re-copy
    assert r2["report"]["sha256"] == _sha256(b"STAGED-FILE-CONTENT")


def test_engine_different_content_fails_without_overwrite(full_stub):
    src = full_stub.staging / "staged.mp4"
    r1 = pe.publish(full_stub.doc, "blog", src)
    src.write_bytes(b"DIFFERENT-CONTENT")
    try:
        pe.publish(full_stub.doc, "blog", src)
        raise AssertionError("changed content must fail")
    except pe.PublishError as e:
        assert "different content" in str(e)
        assert "overwrite=true" in str(e)
    dest = full_stub.media_root / "public" / "ai" / "staged.mp4"
    assert dest.read_bytes() == b"STAGED-FILE-CONTENT"  # old preserved


def test_engine_overwrite_is_the_force_flag(full_stub):
    src = full_stub.staging / "staged.mp4"
    r1 = pe.publish(full_stub.doc, "blog", src)
    dest = full_stub.media_root / "public" / "ai" / "staged.mp4"
    # overwrite=true with IDENTICAL content still replaces (bypasses the
    # dedup no-op) — the force flag must always win.
    r2 = pe.publish(full_stub.doc, "blog", src, overwrite=True)
    assert "error" not in r2
    assert r2["report"].get("duplicate") is not True
    # overwrite=true with CHANGED content replaces the file.
    src.write_bytes(b"replaced content")
    r3 = pe.publish(full_stub.doc, "blog", src, overwrite=True)
    assert "error" not in r3
    assert dest.read_bytes() == b"replaced content"
    assert r1["artifact_path"] == str(dest)


def test_engine_same_source_different_destination_is_not_duplicate(
        full_stub):
    src = full_stub.staging / "staged.mp4"
    r1 = pe.publish(full_stub.doc, "blog", src, destination_name="one.mp4",
                    subdirectory="ai")
    r2 = pe.publish(full_stub.doc, "blog", src, destination_name="two.mp4",
                    subdirectory="images")
    assert "error" not in r1 and "error" not in r2
    assert r2["report"].get("duplicate") is not True
    assert r1["artifact_path"] != r2["artifact_path"]


def test_engine_files_subdir_banned(full_stub):
    try:
        pe.publish(full_stub.doc, "blog",
                   full_stub.staging / "staged.mp4", subdirectory="files")
        raise AssertionError("'files' must be rejected")
    except pe.PublishError as e:
        assert "'files' is not a valid subdirectory" in str(e)
        assert "files/files" in str(e)  # explains WHY (kaelen incident)


def test_engine_invalid_subdir_lists_valid_set(full_stub):
    try:
        pe.publish(full_stub.doc, "blog",
                   full_stub.staging / "staged.mp4", subdirectory="bogus")
        raise AssertionError("invalid subdir must be rejected")
    except pe.PublishError as e:
        assert "not allowed for this target" in str(e)
        assert all(s in str(e) for s in BLOG_SUBDIRS)


# ---------------------------------------------------------------------------
# Engine — source validation (default-deny)
# ---------------------------------------------------------------------------


def test_engine_source_roots_reject(full_stub):
    """A file under a work area that is NOT in blog's source_roots
    (nas_media_store) -> rejected."""
    f = full_stub.nas / "from_nas.mp4"
    f.write_bytes(b"NAS-FILE")
    try:
        pe.publish(full_stub.doc, "blog", f)
        raise AssertionError("outside source_roots must be rejected")
    except pe.PublishError as e:
        assert "source_roots" in str(e)


def test_engine_symlink_rejected(full_stub):
    link = full_stub.staging / "link.mp4"
    link.symlink_to(full_stub.staging / "staged.mp4")
    try:
        pe.publish(full_stub.doc, "blog", link)
        raise AssertionError("symlink must be rejected")
    except pe.PublishError as e:
        assert "symlink" in str(e)


def test_engine_non_absolute_rejected(full_stub):
    try:
        pe.publish(full_stub.doc, "blog", "staged.mp4")
        raise AssertionError("relative path must be rejected")
    except pe.PublishError as e:
        assert "must be absolute" in str(e)


def test_engine_missing_file_rejected(full_stub):
    try:
        pe.publish(full_stub.doc, "blog",
                   full_stub.staging / "missing.mp4")
        raise AssertionError("missing file must be rejected")
    except pe.PublishError as e:
        assert "not a regular file" in str(e)


def test_engine_unknown_target(full_stub):
    try:
        pe.publish(full_stub.doc, "nope", full_stub.staging / "staged.mp4")
        raise AssertionError("unknown target must be rejected")
    except pe.PublishError as e:
        assert "unknown publish target" in str(e)


def test_engine_size_cap(tmp_path):
    """Parameterized cap: a target with a tiny cap rejects bigger files."""
    root = tmp_path / "pub"
    root.mkdir()
    srcdir = tmp_path / "src"
    srcdir.mkdir()
    src = srcdir / "big.bin"
    src.write_bytes(b"x" * 2000)
    t = pe.LocalFSTarget("tiny", {
        "root": str(root), "subdirs": ["ai"], "default_subdir": "ai",
        "url_base": "", "source_roots": [str(srcdir)], "size_cap_mb": 0.001,
    })
    try:
        t.publish(src, "ai", "", False)
        raise AssertionError("over-cap file must be rejected")
    except pe.PublishError as e:
        assert "exceeds" in str(e) and "cap" in str(e)


def test_engine_destination_name_validation(tmp_path):
    root = tmp_path / "pub"
    root.mkdir()
    srcdir = tmp_path / "src"
    srcdir.mkdir()
    src = srcdir / "ok.mp4"
    src.write_bytes(b"DATA")
    t = pe.LocalFSTarget("t", {
        "root": str(root), "subdirs": ["ai"], "default_subdir": "ai",
        "url_base": "", "source_roots": [str(srcdir)], "size_cap_mb": 500,
    })
    bad_names = {
        "a/b.txt": "path separators",
        ".hidden": "must not start with '.' or '-'",
        "-dash": "must not start with '.' or '-'",
        "x" * 151: "1..150",
        "bad name.txt": "may contain only letters",
    }
    for name, needle in bad_names.items():
        try:
            t.publish(src, "ai", name, False)
            raise AssertionError(f"{name!r} must be rejected")
        except pe.PublishError as e:
            assert needle in str(e), (name, str(e))
    # A valid custom name is used verbatim.
    out = t.publish(src, "ai", "renamed.mp4", False)
    assert out["report"]["destination_name"] == "renamed.mp4"
    assert out["report"]["path"] == str(root / "ai" / "renamed.mp4")


# ---------------------------------------------------------------------------
# Engine — nas target (flat, not public) + adapter protocol
# ---------------------------------------------------------------------------


def test_engine_nas_flat_not_public(full_stub):
    out = pe.publish(full_stub.doc, "nas", full_stub.staging / "staged.mp4")
    assert "error" not in out
    rep = out["report"]
    assert rep["path"] == str(full_stub.naspub / "staged.mp4")
    assert rep["subdirectory"] == ""
    assert rep["url"] is None  # not public
    assert (full_stub.naspub / "staged.mp4").read_bytes() \
        == b"STAGED-FILE-CONTENT"
    # A subdirectory on a flat target is rejected.
    try:
        pe.publish(full_stub.doc, "nas",
                   full_stub.staging / "staged.mp4", subdirectory="ai")
        raise AssertionError("flat target must reject subdirs")
    except pe.PublishError as e:
        assert "flat" in str(e)


def test_adapter_protocol():
    """LocalFSTarget satisfies the PublishTarget protocol (D14); a bare
    object does not."""
    cfg = {"root": "/tmp/whatever", "subdirs": ["ai"],
           "default_subdir": "ai", "url_base": "", "source_roots": ["/tmp"],
           "size_cap_mb": 500}
    assert isinstance(pe.LocalFSTarget("x", cfg), pe.PublishTarget)
    class NotATarget:
        pass
    assert not isinstance(NotATarget(), pe.PublishTarget)


# ---------------------------------------------------------------------------
# file_publish MCP tool
# ---------------------------------------------------------------------------


async def test_file_publish_blog(full_stub):
    out = await call_tool(full_stub.client, "file_publish", {
        "file": str(full_stub.staging / "staged.mp4"), "target": "blog"})
    assert "error" not in out, out
    assert out["report"]["url"] == \
        "https://choukalos.com/files/ai/staged.mp4"
    assert out["report"]["sha256"] == _sha256(b"STAGED-FILE-CONTENT")
    assert out["report"]["size_bytes"] == len(b"STAGED-FILE-CONTENT")


async def test_file_publish_nas(full_stub):
    out = await call_tool(full_stub.client, "file_publish", {
        "file": str(full_stub.staging / "staged.mp4"), "target": "nas"})
    assert "error" not in out, out
    assert out["report"]["path"] == str(full_stub.naspub / "staged.mp4")
    assert out["report"]["url"] is None


async def test_file_publish_duplicate_and_overwrite(full_stub):
    out = await call_tool(full_stub.client, "file_publish", {
        "file": str(full_stub.staging / "staged.mp4"), "target": "blog"})
    assert "error" not in out, out
    out2 = await call_tool(full_stub.client, "file_publish", {
        "file": str(full_stub.staging / "staged.mp4"), "target": "blog"})
    assert out2["report"]["duplicate"] is True
    (full_stub.staging / "staged.mp4").write_bytes(b"CHANGED-AGAIN")
    out3 = await call_tool(full_stub.client, "file_publish", {
        "file": str(full_stub.staging / "staged.mp4"), "target": "blog",
        "overwrite": True})
    assert "error" not in out3, out3
    assert out3["report"].get("duplicate") is not True
    assert (full_stub.media_root / "public" / "ai" /
            "staged.mp4").read_bytes() == b"CHANGED-AGAIN"


async def test_file_publish_errors(full_stub):
    out = await call_tool(full_stub.client, "file_publish", {
        "file": str(full_stub.staging / "staged.mp4"), "target": "nope"})
    assert "error" in out and "unknown publish target" in out["error"]
    out = await call_tool(full_stub.client, "file_publish", {
        "file": str(full_stub.staging / "staged.mp4"), "target": "blog",
        "subdirectory": "files"})
    assert "error" in out and "files/files" in out["error"]


async def test_file_publish_in_tools_list(full_stub):
    from conftest import rpc
    res = await rpc(full_stub.client, "tools/list", {}, _id=1)
    names = {t["name"] for t in res["result"]["tools"]}
    assert "file_publish" in names


# ---------------------------------------------------------------------------
# POST /publish endpoint (ai-net only — not routed publicly)
# ---------------------------------------------------------------------------


async def test_post_publish_ok(full_stub):
    r = await full_stub.client.post("/publish", json={
        "source_path": str(full_stub.staging / "staged.mp4"),
        "target": "blog"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["report"]["url"] == \
        "https://choukalos.com/files/ai/staged.mp4"
    assert out["report"]["sha256"] == _sha256(b"STAGED-FILE-CONTENT")
    assert (full_stub.media_root / "public" / "ai" /
            "staged.mp4").read_bytes() == b"STAGED-FILE-CONTENT"


async def test_post_publish_duplicate(full_stub):
    await full_stub.client.post("/publish", json={
        "source_path": str(full_stub.staging / "staged.mp4"),
        "target": "blog"})
    r = await full_stub.client.post("/publish", json={
        "source_path": str(full_stub.staging / "staged.mp4"),
        "target": "blog"})
    assert r.status_code == 200
    assert r.json()["report"]["duplicate"] is True


async def test_post_publish_errors_400(full_stub):
    r = await full_stub.client.post("/publish", json={
        "source_path": str(full_stub.staging / "staged.mp4"),
        "target": "nope"})
    assert r.status_code == 400
    assert "unknown publish target" in r.json()["error"]
    r = await full_stub.client.post("/publish", json={"target": "blog"})
    assert r.status_code == 400
    assert "source_path and target are required" in r.json()["error"]
    r = await full_stub.client.post(
        "/publish", content=b"not json",
        headers={"Content-Type": "application/json"})
    assert r.status_code == 400
    assert "invalid JSON body" in r.json()["error"]


async def test_post_publish_audit_log_one_line_json(full_stub, caplog):
    with caplog.at_level(logging.INFO, logger="filebridge.fileops"):
        r = await full_stub.client.post("/publish", json={
            "source_path": str(full_stub.staging / "staged.mp4"),
            "target": "nas"})
    assert r.status_code == 200
    lines = [rec.message for rec in caplog.records
             if rec.message.startswith("{") and '"event"' in rec.message]
    assert lines, "no one-line JSON audit entry"
    import json
    entry = json.loads(lines[-1])
    assert entry["event"] == "publish"
    assert entry["status"] == "ok"
    assert entry["target"] == "nas"
    assert "ts" in entry

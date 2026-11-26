"""Policy allowlist + traversal for GET /media/files/{path} (12.4)."""

import httpx


async def test_allowlisted_subdir_200(stub):
    r = await stub.client.get("/media/files/generated/abc.png")
    assert r.status_code == 200
    assert r.content == b"GEN-FILE-CONTENT-0123456789"


async def test_allowlisted_subdirs_all_200(stub):
    for p in ("generated/abc.png", "images/photo.jpg",
              "demos/demo.html", "presentations/deck.pptx"):
        r = await stub.client.get(f"/media/files/{p}")
        assert r.status_code == 200, p


async def test_range_passthrough_206(stub):
    r = await stub.client.get("/media/files/generated/abc.png",
                              headers={"Range": "bytes=0-9"})
    assert r.status_code == 206
    assert r.content == b"GEN-FILE-C"
    assert r.headers["content-range"] == "bytes 0-9/27"


async def test_siri_outputs_404(stub):
    r = await stub.client.get("/media/files/siri_outputs/siri_output_2026-01-01T00-00-00_weather.txt")
    assert r.status_code == 404


async def test_non_allowlisted_subdirs_404(stub):
    for sub in ("research_reports", "investment_briefs", "homelab_reports",
                "code_reviews", "public"):
        r = await stub.client.get(f"/media/files/{sub}/x")
        assert r.status_code == 404, sub


async def test_public_dropzone_404(stub):
    # public/ is served via choukalos.com/files/ (portal), never /media/files
    r = await stub.client.get("/media/files/public/video/x.mp4")
    assert r.status_code == 404


async def test_traversal_404(stub):
    for p in ("../etc/passwd", "..%2Fetc%2Fpasswd", "generated/../../etc/passwd",
              "..", "%2e%2e%2fetc%2fpasswd"):
        r = await stub.client.get(f"/media/files/{p}")
        assert r.status_code == 404, p


async def test_directory_404(stub):
    r = await stub.client.get("/media/files/generated")
    assert r.status_code == 404
    r = await stub.client.get("/media/files/generated/")
    assert r.status_code == 404


async def test_missing_file_404(stub):
    r = await stub.client.get("/media/files/generated/nope.png")
    assert r.status_code == 404


async def test_root_only_404(stub):
    r = await stub.client.get("/media/files/")
    assert r.status_code == 404

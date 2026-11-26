"""DL relay: header/Range/status passthrough, byte-identical streaming."""

import httpx


async def test_dl_200_byte_identical(stub):
    r = await stub.client.get("/dl/goodtoken")
    assert r.status_code == 200
    assert r.content == bytes(range(256)) * 4  # byte-identical to upstream
    # header passthrough
    assert r.headers["content-type"] == "video/mp4"
    assert r.headers["content-disposition"] == 'attachment; filename="out.mp4"'
    assert r.headers["accept-ranges"] == "bytes"
    assert int(r.headers["content-length"]) == 1024


async def test_dl_range_206_passthrough(stub):
    r = await stub.client.get("/dl/goodtoken", headers={"Range": "bytes=0-99"})
    assert r.status_code == 206
    assert r.content == bytes(range(256))[:100]
    assert r.headers["content-range"] == "bytes 0-99/1024"
    assert r.headers["accept-ranges"] == "bytes"


async def test_dl_bad_token_404_passthrough(stub):
    r = await stub.client.get("/dl/badtoken")
    assert r.status_code == 404
    assert r.content == b'{"error":"unknown token"}'


async def test_dl_upstream_unreachable_502(stub, monkeypatch):
    import app as appmod
    monkeypatch.setattr(appmod, "MEDIA_PIPELINE_URL", "http://127.0.0.1:1")
    r = await stub.client.get("/dl/goodtoken")
    assert r.status_code == 502


async def test_health_pipeline_reachable(stub):
    r = await stub.client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["pipeline_reachable"] is True
    assert body["public_allow"] == ["demos", "generated", "images", "presentations"]


async def test_health_pipeline_down_503(stub, monkeypatch):
    import app as appmod
    monkeypatch.setattr(appmod, "MEDIA_PIPELINE_URL", "http://127.0.0.1:1")
    r = await stub.client.get("/health")
    assert r.status_code == 503
    assert r.json()["pipeline_reachable"] is False

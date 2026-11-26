"""Upload relay: cap enforcement + X-Api-Key stripping + Matrix 413 passthrough."""

import httpx

CT = 'multipart/form-data; boundary="BOUND123"'
SMALL_BODY = b"file-bytes" * 1000  # ~11 KB


def _mp(body: bytes, filename: str = "x.bin") -> bytes:
    return (
        f"--BOUND123\r\nContent-Disposition: form-data; name=\"file\"; "
        f"filename=\"{filename}\"\r\nContent-Type: application/octet-stream\r\n\r\n"
        f"{body.decode()}\r\n--BOUND123--\r\n"
    ).encode()


async def test_small_upload_200_passthrough(stub):
    body = _mp(SMALL_BODY)
    r = await stub.client.post("/upload", content=body,
                               headers={"Content-Type": CT,
                                        "X-Api-Key": "sk-secret-family-key"})
    assert r.status_code == 200
    assert len(stub.uploads) == 1
    up = stub.uploads[0]
    assert up["path"] == "/upload"
    assert up["body"] == body  # multipart body (incl. boundary) relayed verbatim
    hdrs = {k.lower(): v for k, v in up["headers"].items()}
    assert hdrs["content-type"] == CT


async def test_x_api_key_stripped_upstream(stub):
    await stub.client.post("/upload", content=_mp(SMALL_BODY),
                           headers={"Content-Type": CT, "X-Api-Key": "sk-secret"})
    up = stub.uploads[0]
    assert "x-api-key" not in {k.lower() for k in up["headers"]}


async def test_content_length_over_cap_413_before_body(stub_small_cap):
    big = b"A" * (2 * 1024 * 1024)  # 2 MiB > 1 MiB cap
    r = await stub_small_cap.client.post("/upload", content=big,
                                         headers={"Content-Type": CT})
    assert r.status_code == 413
    assert stub_small_cap.uploads == []  # Matrix never sees the body


async def test_chunked_over_cap_413(stub_small_cap):
    # Chunked transfer (no Content-Length): cap trips mid-stream.
    async def gen():
        for _ in range(4):
            yield b"B" * (1024 * 1024)  # 4 MiB total > 1 MiB cap

    r = await stub_small_cap.client.post("/upload", content=gen(),
                                         headers={"Content-Type": CT})
    assert r.status_code == 413
    assert stub_small_cap.uploads == []  # aborted before forwarding


async def test_under_cap_chunked_ok(stub_small_cap):
    async def gen():
        yield SMALL_BODY
        yield b"tail"

    r = await stub_small_cap.client.post("/upload", content=gen(),
                                         headers={"Content-Type": CT})
    assert r.status_code == 200
    assert len(stub_small_cap.uploads) == 1
    assert stub_small_cap.uploads[0]["body"] == SMALL_BODY + b"tail"


async def test_matrix_413_passthrough(stub):
    stub.upload_status = 413
    stub.upload_body = b'{"error":"upload too large"}'
    r = await stub.client.post("/upload", content=_mp(SMALL_BODY),
                               headers={"Content-Type": CT})
    assert r.status_code == 413
    assert r.content == b'{"error":"upload too large"}'

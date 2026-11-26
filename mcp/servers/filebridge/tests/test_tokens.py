"""1b signed tokens — mint/serve/expiry/path-binding + route precedence."""

from __future__ import annotations

import app as appmod
import tokens as tokmod


async def test_mint_serve_sha256(full_stub):
    """A minted token serves the exact file (200 + byte-identical) at
    /media/files/dl/{token} — the route that the catch-all would 404."""
    token, _ = appmod.TOKENS.mint(str(full_stub.media_root / "generated" /
                                        "abc.png"))
    r = await full_stub.client.get(f"/media/files/dl/{token}")
    assert r.status_code == 200
    assert r.content == b"GEN-FILE-CONTENT-0123456789"
    # Range support (FileResponse native)
    r2 = await full_stub.client.get(f"/media/files/dl/{token}",
                                    headers={"Range": "bytes=0-4"})
    assert r2.status_code == 206
    assert r2.content == b"GEN-F"


async def test_bad_token_404_not_403(full_stub):
    r = await full_stub.client.get(
        "/media/files/dl/" + "0" * 32)
    assert r.status_code == 404
    assert r.json() == {"error": "Not Found"}


async def test_expired_token_404(full_stub, monkeypatch):
    clock = [1_000_000.0]
    store = tokmod.TokenStore(now=lambda: clock[0])
    token, expires = store.mint(str(full_stub.media_root / "generated" /
                                      "abc.png"), ttl_hours=1)
    assert expires == clock[0] + 3600.0
    monkeypatch.setattr(appmod, "TOKENS", store)
    r = await full_stub.client.get(f"/media/files/dl/{token}")
    assert r.status_code == 200  # live before expiry
    clock[0] += 3601
    r = await full_stub.client.get(f"/media/files/dl/{token}")
    assert r.status_code == 404  # expired
    assert store.lookup(token) is None


async def test_path_binding(full_stub):
    """Each token is bound to its exact path: token-A serves A, token-B
    serves B; deleting the file 404s the token."""
    a = full_stub.media_root / "generated" / "abc.png"
    b = full_stub.media_root / "images" / "photo.jpg"
    ta, _ = appmod.TOKENS.mint(str(a))
    tb, _ = appmod.TOKENS.mint(str(b))
    assert (await full_stub.client.get(f"/media/files/dl/{ta}")).content \
        == b"GEN-FILE-CONTENT-0123456789"
    assert (await full_stub.client.get(f"/media/files/dl/{tb}")).content \
        == b"IMG-FILE-CONTENT"
    a.unlink()
    assert (await full_stub.client.get(f"/media/files/dl/{ta}")).status_code \
        == 404
    # B's token still works (independent binding)
    assert (await full_stub.client.get(f"/media/files/dl/{tb}")).status_code \
        == 200


async def test_route_precedence_over_catchall(full_stub):
    """/media/files/dl/{token} is NOT swallowed by the
    /media/files/{filepath:path} catch-all (which would 404: 'dl' is not
    allowlisted)."""
    token, _ = appmod.TOKENS.mint(str(full_stub.media_root / "generated" /
                                        "abc.png"))
    r = await full_stub.client.get(f"/media/files/dl/{token}")
    assert r.status_code == 200, "token route lost to the catch-all"
    # And the catch-all still governs everything else under /media/files
    assert (await full_stub.client.get(
        "/media/files/generated/abc.png")).status_code == 200
    assert (await full_stub.client.get(
        "/media/files/siri_outputs/x.txt")).status_code == 404


def test_ttl_clamp():
    assert tokmod.clamp_ttl(24) == 24.0
    assert tokmod.clamp_ttl("1.5") == 1.5
    for bad in (0, 0.5, 169, -3):
        try:
            tokmod.clamp_ttl(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"clamp_ttl({bad}) did not raise")


def test_public_url():
    assert tokmod.public_url("abc123") == \
        "https://siri.choukalos.com/media/files/dl/abc123"
    assert tokmod.public_url("abc123", "https://x.example/files/") == \
        "https://x.example/files/dl/abc123"

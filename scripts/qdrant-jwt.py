#!/usr/bin/env python3
"""Generate Qdrant JWT RBAC access tokens (HS256, signed with the admin key).

Qdrant OSS >= 1.9 supports granular access via JWTs when
``QDRANT__SERVICE__JWT_RBAC=true`` is set on the server. Tokens are signed
with the admin ``api_key`` (``QDRANT__SERVICE__API_KEY``) and carry an
``access`` claim with per-collection read/write scoping:

    {"access": [{"collection": "mem0_memories", "access": "rw"}]}

Access levels: "r" (read-only) or "rw" (read-write), per collection.
A global level is also possible: {"access": "r"} / {"access": "m"}.

Stdlib only (no PyJWT dependency) — HS256 is a simple HMAC-SHA256.

Usage:
    # From .env (recommended):
    QDRANT_ADMIN_API_KEY=$(grep '^QDRANT_ADMIN_API_KEY=' .env | cut -d= -f2) \
        python3 scripts/qdrant-jwt.py --collection mem0_memories --access rw \
            --sub skill-runner

    # Explicit secret:
    python3 scripts/qdrant-jwt.py --secret <admin-key> \
        --collection mem0_memories --access rw --sub skill-runner

Output: the JWT on stdout (one line).

Notes:
- Tokens are validated OFFLINE by Qdrant (signature + claims) — no network
  round-trip per request.
- No ``exp`` => the token does not expire. For long-running service
  credentials this is intentional; rotate by regenerating (the admin key
  is the root of trust). Passing --exp adds an expiry (unix seconds).
- The ``sub`` claim shows up in Qdrant audit logs (when audit logging is
  enabled) to identify the token holder.
- If the admin api_key is rotated, ALL existing JWTs become invalid and
  must be regenerated.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
import time


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def make_jwt(
    secret: str,
    claims: dict,
    exp: int | None = None,
) -> str:
    """Sign an HS256 JWT with ``secret``."""
    header = {"alg": "HS256", "typ": "JWT"}
    payload = dict(claims)
    if exp is not None:
        payload["exp"] = exp
    signing_input = (
        _b64url(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + _b64url(json.dumps(payload, separators=(",", ":")).encode())
    )
    sig = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    return signing_input + "." + _b64url(sig)


def main() -> int:
    p = argparse.ArgumentParser(description="Generate a Qdrant JWT RBAC token.")
    p.add_argument(
        "--secret",
        default=os.environ.get("QDRANT_ADMIN_API_KEY", ""),
        help="Admin API key (default: $QDRANT_ADMIN_API_KEY).",
    )
    p.add_argument(
        "--collection",
        action="append",
        default=[],
        help="Collection scope, e.g. --collection mem0_memories --access rw. "
        "Repeatable for multiple collections.",
    )
    p.add_argument(
        "--access",
        action="append",
        default=[],
        choices=["r", "rw"],
        help="Access level for each --collection (r | rw). Must pair 1:1 "
        "with --collection in order.",
    )
    p.add_argument(
        "--global-access",
        choices=["r", "m"],
        default=None,
        help="Global access level instead of per-collection scopes.",
    )
    p.add_argument("--sub", default="qdrant-jwt", help="Subject (audit-log identity).")
    p.add_argument(
        "--exp",
        type=int,
        default=None,
        help="Expiry as unix seconds (default: no expiry).",
    )
    p.add_argument(
        "--exp-days",
        type=float,
        default=None,
        help="Expiry as days from now (alternative to --exp).",
    )
    args = p.parse_args()

    if not args.secret:
        print(
            "error: no admin key (--secret or QDRANT_ADMIN_API_KEY env)",
            file=sys.stderr,
        )
        return 2

    if args.exp is not None and args.exp_days is not None:
        print("error: use only one of --exp / --exp-days", file=sys.stderr)
        return 2
    exp = args.exp
    if args.exp_days is not None:
        exp = int(time.time() + args.exp_days * 86400)

    claims: dict = {"sub": args.sub}
    if args.global_access:
        claims["access"] = args.global_access
    else:
        if len(args.collection) != len(args.access):
            print(
                "error: --collection and --access must pair 1:1 "
                f"({len(args.collection)} vs {len(args.access)})",
                file=sys.stderr,
            )
            return 2
        if not args.collection:
            print(
                "error: provide --collection/--access pairs or --global-access",
                file=sys.stderr,
            )
            return 2
        claims["access"] = [
            {"collection": c, "access": a} for c, a in zip(args.collection, args.access)
        ]

    print(make_jwt(args.secret, claims, exp=exp))
    return 0


if __name__ == "__main__":
    sys.exit(main())
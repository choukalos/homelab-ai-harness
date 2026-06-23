from typing import Optional

from fastapi import Header, HTTPException

from knowledge.family_kb.config import HARNESS_API_KEY


def require_auth(authorization: Optional[str] = Header(default=None)) -> None:
    if not HARNESS_API_KEY:
        return

    if authorization != f"Bearer {HARNESS_API_KEY}":
        raise HTTPException(status_code=401, detail="Unauthorized")



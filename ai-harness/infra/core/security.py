from typing import Optional

from fastapi import Header, HTTPException

from infra.core.config import HARNESS_API_KEY, SIRI_API_KEY


def _check_key(
    expected_key: str,
    authorization: Optional[str],
    x_api_key: Optional[str],
) -> None:
    if not expected_key:
        raise HTTPException(status_code=500, detail="API key is not configured")

    if x_api_key == expected_key:
        return

    if authorization == f"Bearer {expected_key}":
        return

    raise HTTPException(status_code=401, detail="Unauthorized")


def require_harness_auth(
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
) -> None:
    _check_key(HARNESS_API_KEY, authorization, x_api_key)


def require_siri_auth(
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
) -> None:
    _check_key(SIRI_API_KEY, authorization, x_api_key)


# Backwards-compatible alias for existing routers
def require_auth(
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
) -> None:
    require_harness_auth(authorization=authorization, x_api_key=x_api_key)

    

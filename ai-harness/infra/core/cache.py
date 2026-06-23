import hashlib
import json
from typing import Any

import redis

from infra.core.config import REDIS_URL

cache = redis.from_url(REDIS_URL, decode_responses=True)


def cache_key(prefix: str, payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True)
    return f"{prefix}:{hashlib.sha256(raw.encode()).hexdigest()}"


def get_json(key: str) -> dict[str, Any] | None:
    cached = cache.get(key)
    if not cached:
        return None
    return json.loads(cached)


def set_json(key: str, value: dict[str, Any], ttl_seconds: int = 1800) -> None:
    cache.setex(key, ttl_seconds, json.dumps(value))


import httpx
from fastapi import HTTPException

from infra.core.config import HARNESS_MODEL, LITELLM_API_KEY, LITELLM_BASE_URL


def litellm_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if LITELLM_API_KEY:
        headers["Authorization"] = f"Bearer {LITELLM_API_KEY}"
    return headers


# ------ async version used by FastAPI endpoints --------

async def chat_completion(
    client: httpx.AsyncClient,
    prompt: str,
    temperature: float = 0.2,
    timeout: float = 90.0,
) -> str:
    try:
        r = await client.post(
            f"{LITELLM_BASE_URL}/chat/completions",
            headers=litellm_headers(),
            json={
                "model": HARNESS_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
            },
            timeout=timeout,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=502,
            detail={
                "service": "litellm",
                "status_code": e.response.status_code,
                "body": e.response.text[:1000],
            },
        )

    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail={"service": "litellm", "error": str(e)},
        )


# ------ sync version used inside Celery workers --------

from typing import Any

def chat_completion_sync(
    messages: list[dict[str, str]],
    model: str | None = None,
    max_tokens: int | None = None,
    temperature: float = 0.2,
    timeout: float = 300.0,
) -> str:
    """Synchronous LiteLLM call — used inside Celery tasks.

    Parameters
    ----------
    messages:
        OpenAI-style message list.
    model:
        Optional model override (defaults to HARNESS_MODEL env var).
    max_tokens:
        Optional max_tokens override.
    """
    payload: dict[str, Any] = {
        "model": model or HARNESS_MODEL,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    with httpx.Client(timeout=timeout) as client:
        r = client.post(
            f"{LITELLM_BASE_URL}/chat/completions",
            headers=litellm_headers(),
            json=payload,
        )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


async def chat_completion_async(
    messages: list[dict[str, str]],
    model: str | None = None,
    max_tokens: int | None = None,
    temperature: float = 0.2,
    timeout: float = 300.0,
) -> str:
    """Async LiteLLM call — used inside async FastAPI endpoints.

    Non-blocking version of chat_completion_sync. Uses httpx.AsyncClient
    to avoid blocking the uvicorn event loop.
    """
    payload: dict[str, Any] = {
        "model": model or HARNESS_MODEL,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(
            f"{LITELLM_BASE_URL}/chat/completions",
            headers=litellm_headers(),
            json=payload,
        )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


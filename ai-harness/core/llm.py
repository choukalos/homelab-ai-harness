import httpx
from fastapi import HTTPException

from core.config import HARNESS_MODEL, LITELLM_API_KEY, LITELLM_BASE_URL


def litellm_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if LITELLM_API_KEY:
        headers["Authorization"] = f"Bearer {LITELLM_API_KEY}"
    return headers


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


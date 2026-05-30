import httpx

from core.llm import chat_completion
from media.comfy_client import ComfyClient
from media.schemas import ImageRequest
from pm_demo.service import generate_demo_html
from siri.schemas import SiriChatRequest, SiriChatResponse
from web_search.service import run_research_brief


def _shorten_for_voice(text: str, max_len: int = 700) -> str:
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[:max_len].rsplit(" ", 1)[0] + "..."


def _detect_intent(req: SiriChatRequest) -> str:
    text = req.text.lower().strip()

    if req.intent and req.intent != "chat":
        return req.intent

    if text.startswith("research ") or "research brief" in text:
        return "research"

    if text.startswith("generate image") or text.startswith("make an image") or text.startswith("draw "):
        return "image"

    if "html demo" in text or "one page demo" in text or "prototype" in text:
        return "demo"

    return "chat"

async def _handle_chat(req: SiriChatRequest) -> SiriChatResponse:
    prompt = (
        "You are a concise Siri and CarPlay assistant. "
        "Answer clearly. Keep voice responses short unless asked for detail.\n\n"
        f"User: {req.text}"
    )

    async with httpx.AsyncClient(timeout=90.0) as client:
        answer = await chat_completion(
            client=client,
            prompt=prompt,
            temperature=0.2,
        )

    return SiriChatResponse(
        speak=_shorten_for_voice(answer),
        display=answer,
        session_id=req.session_id,
    )


async def _handle_research(req: SiriChatRequest) -> SiriChatResponse:
    topic = req.text.removeprefix("research ").strip()

    async with httpx.AsyncClient(timeout=120.0) as client:
        result = await run_research_brief(
            client=client,
            topic=topic,
            max_queries=3,
            results_per_query=5,
        )

    brief = result.get("brief") or result.get("summary") or str(result)

    return SiriChatResponse(
        speak=_shorten_for_voice(brief),
        display=brief,
        session_id=req.session_id,
        links=result.get("sources", []),
        data=result,
    )


async def _handle_image(req: SiriChatRequest) -> SiriChatResponse:
    prompt = (
        req.text
        .removeprefix("generate image")
        .removeprefix("make an image")
        .removeprefix("draw")
        .strip()
    )

    comfy = ComfyClient()
    result = comfy.generate_image(
        ImageRequest(
            prompt=prompt,
        )
    )

    media = []
    if result.url:
        media.append(
            {
                "type": "image",
                "url": result.url,
            }
        )

    return SiriChatResponse(
        speak="I generated the image.",
        display="Image generated.",
        session_id=req.session_id,
        media=media,
        data=result.model_dump() if hasattr(result, "model_dump") else dict(result),
    )


async def _handle_demo(req: SiriChatRequest) -> SiriChatResponse:
    result = await generate_demo_html(
        title="Siri Demo",
        prompt=req.text,
        model=req.model,
        save_name=None,
    )

    links = []
    if result.url:
        links.append(
            {
                "title": "Open HTML demo",
                "url": result.url,
            }
        )

    return SiriChatResponse(
        speak="I created the one page demo.",
        display=f"Demo created: {result.url}",
        session_id=req.session_id,
        links=links,
        data=result.model_dump() if hasattr(result, "model_dump") else dict(result),
    )


async def handle_siri_chat(req: SiriChatRequest) -> SiriChatResponse:
    intent = _detect_intent(req)

    if intent == "research":
        return await _handle_research(req)

    if intent == "image":
        return await _handle_image(req)

    if intent in {"demo", "html_demo", "pm_demo"}:
        return await _handle_demo(req)

    return await _handle_chat(req)



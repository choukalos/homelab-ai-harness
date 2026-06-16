import httpx

from core.config import PUBLIC_BASE_URL
from core.llm import chat_completion
from media.comfy_client import ComfyClient
from media.schemas import ImageRequest
from pm_demo.service import generate_demo_html
from siri.schemas import SiriChatRequest, SiriChatResponse
from web_search.service import run_research_brief


# Rewrite internal media URLs to public-facing URLs for Siri responses
def _rewrite_to_public_urls(media_url: str) -> str:
    """Replace internal base URL with public base URL in media URLs."""
    from core.config import INTERNAL_BASE_URL
    internal = INTERNAL_BASE_URL.rstrip("/")
    public = PUBLIC_BASE_URL.rstrip("/")
    if internal and media_url.startswith(internal):
        return media_url.replace(internal, public, 1)
    return media_url


def _shorten_for_voice(text: str, max_len: int = 700) -> str:
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[:max_len].rsplit(" ", 1)[0] + "..."


def _detect_intent(req: SiriChatRequest) -> str:
    text = req.text.lower().strip()

    if req.intent and req.intent != "chat":
        return req.intent

    if text.startswith("deep research ") or "deep research" in text:
        return "deep_research"

    if text.startswith("research ") or "research brief" in text:
        return "research"

    if text.startswith("generate image") or text.startswith("make an image") or text.startswith("draw "):
        return "image"

    # Demo listing/discovery (check BEFORE create demo)
    if any(p in text for p in ["list demo", "show demo", "what demo", "my demos", "demo list", "demos we"]):
        return "list_demos"
    if any(p in text for p in ["find demo", "demo about", "demo for", "search demo"]):
        return "find_demo"

    # Demo creation
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


async def _handle_deep_research(req: SiriChatRequest) -> SiriChatResponse:
    """Run the deep-research agent (Deep Agents with MySQL checkpointing)."""
    from core.config import INTERNAL_BASE_URL

    query = req.text.removeprefix("deep research ").strip()

    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            r = await client.post(
                f"{INTERNAL_BASE_URL.rstrip('/')}/workflows/deep-research/run",
                headers={"Content-Type": "application/json", "X-API-Key": req.session_id or ""},
                json={"query": query},
            )
            r.raise_for_status()
            data = r.json()

        answer = data.get("answer", "Research completed.")
        sources = data.get("sources", [])

        links = []
        for s in sources:
            url = s.get("url", s.get("tool_result", ""))
            if url:
                title = s.get("title", s.get("source", "Source"))
                links.append({"title": str(title)[:80], "url": url})

        return SiriChatResponse(
            speak=_shorten_for_voice(answer),
            display=answer,
            session_id=req.session_id,
            links=links[:10],
            data=data,
        )
    except Exception as exc:
        return SiriChatResponse(
            speak="I had trouble running the deep research. Please try again.",
            display=f"Deep research error: {exc}",
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
    for f in result.get("files", []):
        public_url = _rewrite_to_public_urls(f.get("url", ""))
        media.append({
            "type": "image",
            "url": public_url,
        })

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
    if result.get("url"):
        public_demo_url = _rewrite_to_public_urls(result["url"])
        links.append(
            {
                "title": "Open HTML demo",
                "url": public_demo_url,
            }
        )

    return SiriChatResponse(
        speak="I created the one page demo.",
        display=f"Demo created: {public_demo_url}",
        session_id=req.session_id,
        links=links,
        data=result.model_dump() if hasattr(result, "model_dump") else dict(result),
    )


async def _handle_create_demo_workflow(req: SiriChatRequest) -> SiriChatResponse:
    """Kick off the full async demo workflow via POST /demos/create.

    Siri cannot wait 2-5 minutes for the pipeline, so we dispatch
    the job and return immediately with the run ID.  The user can
    follow up with 'list my demos' once it completes.
    """
    from core.config import INTERNAL_BASE_URL

    # Pull title + prompt from the voice text; use LLM if needed
    # For now we use the raw text as the prompt and derive a short title
    text = req.text.strip()
    # Strip common prefixes
    for prefix in ["create a demo", "create demo", "build a demo",
                   "build demo", "generate a demo", "make a demo"]:
        if text.lower().startswith(prefix):
            text = text[len(prefix):].strip()
            break

    # If there's no explicit title, use the first ~10 words
    words = text.split()
    title = " ".join(words[:10]) if words else "Siri Demo"
    # Capitalize title
    title = title[0].upper() + title[1:] if title else "Siri Demo"

    payload = {"title": title, "prompt": text}
    if req.model:
        payload["model"] = req.model

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"{INTERNAL_BASE_URL.rstrip('/')}/demos/create",
                headers={"Content-Type": "application/json",
                         "X-API-Key": req.session_id or ""},
                json=payload,
            )
            r.raise_for_status()
            data = r.json()

        run_id = data.get("run_id", "")
        steps = data.get("steps_count", 8)

        return SiriChatResponse(
            speak=(
                f"I've started building your demo. "
                f"It will take a couple minutes. "
                f"Ask me to list your demos when it's done."
            ),
            display=(
                f"Demo workflow started!\n"
                f"Title: {data.get('title', title)}\n"
                f"Run ID: {run_id}\n"
                f"Steps: {steps}\n\n"
                f"This pipeline researches, designs, and builds your demo.\n"
                f"Typical completion time: 2-5 minutes.\n"
                f"Follow up with: 'list my demos'"
            ),
            session_id=req.session_id,
            data={"run_id": run_id, "title": data.get("title", title)},
        )
    except Exception as exc:
        return SiriChatResponse(
            speak="I had trouble starting the demo build. Please try again.",
            display=f"Error starting demo workflow: {exc}",
            session_id=req.session_id,
        )


async def _handle_list_demos(req: SiriChatRequest) -> SiriChatResponse:
    """Return list of all created demos with PUBLIC URLs."""
    from pathlib import Path
    from core.config import MEDIA_OUTPUT_DIR
    import json as _j

    demos_root = Path(MEDIA_OUTPUT_DIR) / "demos"
    demos = []

    if demos_root.exists():
        for slug_dir in sorted(demos_root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if not slug_dir.is_dir():
                continue
            meta_file = slug_dir / "metadata.json"
            if meta_file.exists():
                try:
                    meta = _j.loads(meta_file.read_text())
                    demos.append(meta)
                except Exception:
                    pass

    if not demos:
        return SiriChatResponse(
            speak="There are no demos yet. Ask me to create one!",
            display="No demos found.",
            session_id=req.session_id,
        )

    lines = [f"I have {len(demos)} demo(s):"]
    for d in demos[:10]:
        title = d.get("title", "Untitled")
        public_url = d.get("public_url", "")
        lines.append(f"- {title}: {public_url}")

    display = "\n".join(lines)
    speak = f"I found {len(demos)} demos. " + "\n".join(
        f"{d.get('title', '')}" for d in demos[:5]
    )

    return SiriChatResponse(
        speak=_shorten_for_voice(speak),
        display=display,
        session_id=req.session_id,
        links=[{"title": d.get("title", ""), "url": d.get("public_url", "")}
               for d in demos[:10]],
    )


async def _handle_find_demo(req: SiriChatRequest) -> SiriChatResponse:
    """Search for demos by query and return matches with PUBLIC URLs."""
    from pathlib import Path
    from core.config import MEDIA_OUTPUT_DIR
    import json as _j

    # Extract the search query from the request text
    text = req.text.lower()
    query = req.text
    for prefix in ["find demo about", "find demo for", "demo about", "demo for",
                   "search demo for", "search demo about", "demo"]:
        if text.startswith(prefix):
            query = req.text[len(prefix):].strip()
            break

    demos_root = Path(MEDIA_OUTPUT_DIR) / "demos"
    matches = []
    query_lower = query.lower()

    if demos_root.exists():
        for slug_dir in sorted(demos_root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if not slug_dir.is_dir():
                continue
            meta_file = slug_dir / "metadata.json"
            if meta_file.exists():
                try:
                    meta = _j.loads(meta_file.read_text())
                    title = meta.get("title", "").lower()
                    desc = meta.get("description", "").lower()
                    tags = " ".join(meta.get("tags", [])).lower()
                    combined = f"{title} {desc} {tags}"
                    if any(term in combined for term in query_lower.split()):
                        matches.append(meta)
                except Exception:
                    pass

    if not matches:
        return SiriChatResponse(
            speak=f"No demos found matching '{query}'.",
            display=f"No demos found matching '{query}'.\n\nTry 'list my demos' to see all available demos.",
            session_id=req.session_id,
        )

    lines = [f"Found {len(matches)} demo(s) matching '{query}':"]
    for d in matches:
        title = d.get("title", "Untitled")
        public_url = d.get("public_url", "")
        lines.append(f"- {title}: {public_url}")

    display = "\n".join(lines)
    speak = f"I found {len(matches)} demos matching '{query}'."

    return SiriChatResponse(
        speak=_shorten_for_voice(speak),
        display=display,
        session_id=req.session_id,
        links=[{"title": d.get("title", ""), "url": d.get("public_url", "")}
               for d in matches],
    )


async def handle_siri_chat(req: SiriChatRequest) -> SiriChatResponse:
    intent = _detect_intent(req)

    if intent == "deep_research":
        return await _handle_deep_research(req)

    if intent == "research":
        return await _handle_research(req)

    if intent == "image":
        return await _handle_image(req)

    if intent == "list_demos":
        return await _handle_list_demos(req)

    if intent == "find_demo":
        return await _handle_find_demo(req)

    if intent in {"demo", "html_demo", "pm_demo"}:
        return await _handle_demo(req)

    return await _handle_chat(req)



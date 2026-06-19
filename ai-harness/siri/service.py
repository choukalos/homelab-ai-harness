import re
import httpx
from datetime import datetime

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

    # Presentation creation (check BEFORE listing to avoid misrouting)
    if any(p in text for p in ["create a presentation", "create presentation",
                               "make a presentation", "build a presentation",
                               "build presentation", "generate a presentation"]):
        return "create_presentation"

    # Presentation listing / finding
    if any(p in text for p in ["list presentation", "show presentation",
                               "my presentations", "presentation list",
                               "presentations we"]):
        return "list_presentations"
    if any(p in text for p in ["find presentation", "presentation about",
                               "presentation for", "search presentation"]):
        return "find_presentation"

    # Demo creation (check BEFORE listing to avoid misrouting "build a demo")
    if any(p in text for p in ["create a demo", "create demo", "build a demo",
                               "build demo", "generate a demo", "make a demo"]):
        return "create_demo"

    # Demo quality query: "how well does X demo work?" / "demo quality"
    if any(p in text for p in ["how well does", "how well is", "demo quality",
                               "demo score", "how does the demo", "demo rating"]):
        return "demo_quality"

    # Demo complexity query: "how complex is X demo?" / "research insights for X"
    if any(p in text for p in ["how complex is", "demo complexity",
                               "research insights", "demo insights",
                               "complexity of", "mvp features"]):
        return "demo_complexity"

    # Demo listing/discovery
    if any(p in text for p in ["list demo", "show demo", "what demo", "my demos", "demo list", "demos we"]):
        return "list_demos"
    if any(p in text for p in ["find demo", "demo about", "demo for", "search demo"]):
        return "find_demo"

    # Simple one-page demo (instant, no research pipeline)
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
    from core.config import HARNESS_API_KEY, INTERNAL_BASE_URL

    query = req.text.removeprefix("deep research ").strip()

    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            r = await client.post(
                f"{INTERNAL_BASE_URL.rstrip('/')}/workflows/deep-research/run",
                headers={"Content-Type": "application/json", "X-API-Key": HARNESS_API_KEY},
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
    """Kick off the full demo pipeline via POST /demos/run using fire-and-forget.

    Siri cannot wait 2-5 minutes for the pipeline, so we dispatch
    the request as a background task and return immediately. The user can
    follow up with 'list my demos' once it completes.

    Same pattern as deep_research for Siri integration.
    """
    import asyncio
    import logging
    from core.config import HARNESS_API_KEY, INTERNAL_BASE_URL

    logger = logging.getLogger("siri.service")

    # Pull title + prompt from the voice text
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

    async def _run_demo():
        try:
            async with httpx.AsyncClient(timeout=600.0) as client:
                r = await client.post(
                    f"{INTERNAL_BASE_URL.rstrip('/')}/demos/run",
                    headers={"Content-Type": "application/json",
                             "X-API-Key": HARNESS_API_KEY},
                    json=payload,
                )
                r.raise_for_status()
                data = r.json()
                logger.info("Demo workflow completed: title=%s, slug=%s",
                           data.get("title", title), data.get("slug", ""))
        except Exception as exc:
            logger.error("Demo workflow background task failed: %s", exc)

    # Fire-and-forget: dispatch the request as a background task
    asyncio.create_task(_run_demo())

    return SiriChatResponse(
        speak=(
            "I've started building your demo. "
            "It will take a couple minutes. "
            "Ask me to list your demos when it's done."
        ),
        display=(
            f"Demo build started!\n"
            f"Title: {title}\n\n"
            f"The pipeline will research, design, and build your demo.\n"
            f"Typical completion time: 2-5 minutes.\n"
            f"Follow up with: 'list my demos'"
        ),
        session_id=req.session_id,
        data={"title": title},
    )


def _scan_all_demos() -> list[dict]:
    """Scan demos dir for both workflow subdirs (metadata.json) and flat .html files."""
    from pathlib import Path
    from core.config import MEDIA_OUTPUT_DIR
    import json as _j

    demos_root = Path(MEDIA_OUTPUT_DIR) / "demos"
    demos = []

    if not demos_root.exists():
        return demos

    for entry in sorted(demos_root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if entry.is_dir():
            # Workflow demo: subdirectory with metadata.json
            meta_file = entry / "metadata.json"
            if meta_file.exists():
                try:
                    demos.append(_j.loads(meta_file.read_text()))
                except Exception:
                    pass
        elif entry.is_file() and entry.suffix == ".html":
            # Simple one-click demo: flat HTML file — build lightweight metadata
            filename = entry.name
            name_base = filename.rsplit("-", 1)[0] if "-" in filename[:-5] else filename[:-5]
            title = name_base.replace("-", " ").title()
            demos.append({
                "title": title,
                "slug": name_base.replace(" ", "-").lower(),
                "description": f"One-click demo: {title}",
                "tags": ["simple"],
                "filename": filename,
                "local_url": f"{PUBLIC_BASE_URL.rstrip('/')}/media/files/demos/{filename}",
                "public_url": f"{PUBLIC_BASE_URL.rstrip('/')}/media/files/demos/{filename}",
                "created_at": datetime.fromtimestamp(entry.stat().st_mtime).isoformat(),
            })

    return demos


async def _handle_demo_complexity(req: SiriChatRequest) -> SiriChatResponse:
    """Answer questions about demo complexity and research insights.

    Siri can answer: 'how complex is the X demo?', 'what were the research insights for X?',
    'mvp features for X', etc.

    Uses metadata.json fields: complexity_score, complexity_breakdown, discovery_notes.
    """
    # Extract demo name from the query
    text = req.text.lower()
    query = req.text
    for prefix in ["how complex is", "demo complexity", "research insights for",
                   "demo insights for", "complexity of", "mvp features for",
                   "mvp features", "research insights"]:
        if text.startswith(prefix) or f" {prefix} " in text:
            query = re.sub(
                rf"^(.*\s)?(?:{prefix})\s*",
                "",
                req.text,
                flags=re.IGNORECASE,
            ).strip()
            break

    all_demos = _scan_all_demos()

    # Find matching demos
    query_lower = query.lower()
    matches = []
    for d in all_demos:
        title = d.get("title", "").lower()
        desc = d.get("description", "").lower()
        tags = " ".join(d.get("tags", [])).lower()
        combined = f"{title} {desc} {tags}"
        if any(term in combined for term in query_lower.split()):
            matches.append(d)

    if not matches:
        # List all demos with complexity scores as fallback
        scored = [d for d in all_demos if d.get("complexity_score", 0) > 0]
        if scored:
            lines = ["I don't have complexity data for that specific demo, but here are your demos with complexity scores:"]
            for d in scored[:10]:
                title = d.get("title", "Untitled")
                score = d.get("complexity_score", "N/A")
                effort = d.get("complexity_breakdown", {}).get("estimated_build_effort", "")
                line = f"- {title}: complexity {score}/10"
                if effort:
                    line += f", effort: {effort}"
                lines.append(line)
            return SiriChatResponse(
                speak=_shorten_for_voice("\n".join(lines)),
                display="\n".join(lines),
                session_id=req.session_id,
            )
        return SiriChatResponse(
            speak=f"No demo complexity data found matching '{query}'.",
            display=f"No demo complexity data found matching '{query}'.\n\nTry 'list my demos' to see all available demos.",
            session_id=req.session_id,
        )

    lines = [f"Demo complexity report ({len(matches)} matching):"]
    for d in matches:
        title = d.get("title", "Untitled")
        complexity = d.get("complexity_score", "N/A")

        detail_lines = [f"\n### {title}"]
        detail_lines.append(f"- **Complexity Score**: {complexity}/10")

        breakdown = d.get("complexity_breakdown", {})
        if breakdown:
            screen_count = breakdown.get("screen_count", "N/A")
            interactive = breakdown.get("interactive_elements", "N/A")
            mocked = breakdown.get("mocked_features", "N/A")
            effort = breakdown.get("estimated_build_effort", "")
            detail_lines.append(f"- **Screens**: {screen_count}")
            detail_lines.append(f"- **Interactive elements**: {interactive}")
            detail_lines.append(f"- **Mocked features**: {mocked}")
            if effort:
                detail_lines.append(f"- **Estimated build effort**: {effort}")

        discovery = d.get("discovery_notes", {})
        if discovery:
            mvp = discovery.get("mvp_features", [])
            nice = discovery.get("nice_to_have", [])
            insights = discovery.get("research_insights", [])
            if mvp:
                detail_lines.append(f"- **MVP features** ({len(mvp)}): {', '.join(mvp[:5])}")
            if nice:
                detail_lines.append(f"- **Nice to have** ({len(nice)}): {', '.join(nice[:5])}")
            if insights:
                detail_lines.append(f"- **Research insights** ({len(insights)}): {', '.join(insights[:3])}")

        lines.extend(detail_lines)

    display = "\n".join(lines)
    speak_lines = [f"Complexity report:"]
    for d in matches:
        title = d.get("title", "Untitled")
        complexity = d.get("complexity_score", "N/A")
        effort = d.get("complexity_breakdown", {}).get("estimated_build_effort", "")
        speak_lines.append(f"{title}: complexity {complexity}/10{f', {effort}' if effort else ''}")

    return SiriChatResponse(
        speak=_shorten_for_voice("\n".join(speak_lines)),
        display=display,
        session_id=req.session_id,
    )


async def _handle_demo_quality(req: SiriChatRequest) -> SiriChatResponse:
    """Answer questions about demo quality using verification metadata.

    Siri can answer: 'how well does the X demo work?', 'what's the demo score?',
    'demo quality report for X', etc.

    Uses metadata.json fields: code_quality_score, mocked_features,
    functional_areas, verification_issues.
    """
    # Extract demo name from the query
    text = req.text.lower()
    # Strip common prefixes to find the demo name
    query = req.text
    for prefix in ["how well does", "how well is", "demo quality",
                   "demo score for", "how does the demo", "demo rating for",
                   "demo quality for", "demo score"]:
        if text.startswith(prefix) or f" {prefix} " in text:
            query = re.sub(
                rf"^(.*\s)?(?:{prefix})\s*",
                "",
                req.text,
                flags=re.IGNORECASE,
            ).strip()
            break

    all_demos = _scan_all_demos()

    # Find matching demos
    query_lower = query.lower()
    matches = []
    for d in all_demos:
        title = d.get("title", "").lower()
        desc = d.get("description", "").lower()
        tags = " " .join(d.get("tags", [])).lower()
        combined = f"{title} {desc} {tags}"
        if any(term in combined for term in query_lower.split()):
            matches.append(d)

    if not matches:
        # If no match, list all demos with quality scores as fallback
        scored = [d for d in all_demos if d.get("code_quality_score", 0) > 0]
        if scored:
            lines = ["I don't have quality data for that specific demo, but here are your demos with quality scores:"]
            for d in scored[:10]:
                title = d.get("title", "Untitled")
                score = d.get("code_quality_score", "N/A")
                lines.append(f"- {title}: quality score {score}/10")
            return SiriChatResponse(
                speak=_shorten_for_voice("\n".join(lines)),
                display="\n".join(lines),
                session_id=req.session_id,
            )
        return SiriChatResponse(
            speak=f"No demo quality data found matching '{query}'.",
            display=f"No demo quality data found matching '{query}'.\n\nTry 'list my demos' to see all available demos.",
            session_id=req.session_id,
        )

    lines = [f"Demo quality report ({len(matches)} matching):"]
    for d in matches:
        title = d.get("title", "Untitled")
        score = d.get("code_quality_score", "N/A")
        issues = d.get("verification_issues", [])
        mocked = d.get("mocked_features", [])
        functional = d.get("functional_areas", [])

        detail_lines = [f"\n### {title}"]
        detail_lines.append(f"- **Quality Score**: {score}/10")

        if mocked:
            mock_descs = [m.get("feature", "") if isinstance(m, dict) else str(m) for m in mocked[:5]]
            detail_lines.append(f"- **Mocked features** ({len(mocked)}): {', '.join(mock_descs)}")

        if functional:
            detail_lines.append(f"- **Verified interactions** ({len(functional)}): {', '.join(functional[:5])}")

        if issues:
            detail_lines.append(f"- **Issues** ({len(issues)}): {'; '.join(issues[:5])}")
        else:
            detail_lines.append("- **Issues**: None")

        level3 = d.get("level3_patterns", {})
        if level3:
            present = [k.replace("_", " ") for k, v in level3.items() if v]
            missing = [k.replace("_", " ") for k, v in level3.items() if not v]
            detail_lines.append(f"- **Level 3 mock behavior**: {', '.join(present) if present else 'None'}")
            if missing:
                detail_lines.append(f"  Missing: {', '.join(missing)}")

        # Add complexity info to the display
        complexity = d.get("complexity_score", "N/A")
        if complexity != "N/A" and complexity > 0:
            detail_lines.append(f"- **Complexity Score**: {complexity}/10")
        complexity_bd = d.get("complexity_breakdown", {})
        if complexity_bd:
            effort = complexity_bd.get("estimated_build_effort", "")
            if effort:
                detail_lines.append(f"- **Estimated build effort**: {effort}")

        discovery = d.get("discovery_notes", {})
        if discovery:
            mvp = discovery.get("mvp_features", [])
            nice = discovery.get("nice_to_have", [])
            insights = discovery.get("research_insights", [])
            if mvp:
                detail_lines.append(f"- **MVP features** ({len(mvp)}): {', '.join(mvp[:5])}")
            if nice:
                detail_lines.append(f"- **Nice to have** ({len(nice)}): {', '.join(nice[:5])}")
            if insights:
                detail_lines.append(f"- **Research insights** ({len(insights)}): {', '.join(insights[:3])}")

        lines.extend(detail_lines)

    display = "\n".join(lines)
    speak_lines = [f"Quality report:"]
    for d in matches:
        title = d.get("title", "Untitled")
        score = d.get("code_quality_score", "N/A")
        complexity = d.get("complexity_score", "")
        parts = [f"{title}: score {score} out of 10"]
        if complexity and complexity != "N/A" and complexity > 0:
            parts.append(f"complexity {complexity}")
        speak_lines.append(" ".join(parts))

    return SiriChatResponse(
        speak=_shorten_for_voice("\n".join(speak_lines)),
        display=display,
        session_id=req.session_id,
    )


async def _handle_create_presentation(req: SiriChatRequest) -> SiriChatResponse:
    """Kick off presentation generation via POST /presentation/generate/async.

    Siri cannot wait 3-5 minutes for the pipeline, so we dispatch
    the request as a background Celery task and return immediately.
    The user can follow up with 'list my presentations' once it completes.

    Same fire-and-forget pattern as _handle_create_demo_workflow.
    """
    import asyncio
    import logging
    from core.config import HARNESS_API_KEY, INTERNAL_BASE_URL

    logger = logging.getLogger("siri.service")

    # Pull title + content from the voice text
    text = req.text.strip()
    # Strip common prefixes
    for prefix in ["create a presentation", "create presentation",
                   "make a presentation", "build a presentation",
                   "build presentation", "generate a presentation"]:
        if text.lower().startswith(prefix):
            text = text[len(prefix):].strip()
            break

    # If there's "about" or "on", use that as the topic
    topic = text
    if " about " in text:
        topic = text.split(" about ", 1)[1].strip()
    elif " on " in text:
        topic = text.split(" on ", 1)[1].strip()

    # Derive title from first ~10 words
    words = topic.split()
    title = " ".join(words[:10]) if words else "Presentation"
    title = title[0].upper() + title[1:] if title else "Presentation"

    payload: dict = {
        "title": title,
        "content": topic,
    }
    if req.model:
        payload["model"] = req.model

    async def _run_presentation():
        try:
            async with httpx.AsyncClient(timeout=600.0) as client:
                r = await client.post(
                    f"{INTERNAL_BASE_URL.rstrip('/')}/presentation/generate/async",
                    headers={"Content-Type": "application/json",
                             "X-API-Key": HARNESS_API_KEY},
                    json=payload,
                )
                r.raise_for_status()
                data = r.json()
                logger.info(
                    "Presentation task dispatched: title=%s, task_id=%s",
                    title,
                    data.get("task_id", ""),
                )
        except Exception as exc:
            logger.error("Presentation task dispatch failed: %s", exc)

    # Fire-and-forget: dispatch the request as a background task
    asyncio.create_task(_run_presentation())

    return SiriChatResponse(
        speak=(
            "I've started creating your presentation. "
            "It will take a few minutes. "
            "Ask me to list your presentations when it's done."
        ),
        display=(
            f"Presentation generation started!\n"
            f"Title: {title}\n\n"
            f"The pipeline will research, design, and build your presentation.\n"
            f"Typical completion time: 3-5 minutes.\n"
            f"Follow up with: 'list my presentations'"
        ),
        session_id=req.session_id,
        data={"title": title},
    )


async def _handle_list_presentations(req: SiriChatRequest) -> SiriChatResponse:
    """Return list of all created presentations with URLs."""
    from core.config import HARNESS_API_KEY, INTERNAL_BASE_URL

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(
                f"{INTERNAL_BASE_URL.rstrip('/')}/presentation/list",
                headers={"X-API-Key": HARNESS_API_KEY},
            )
            r.raise_for_status()
            data = r.json()
    except Exception as exc:
        return SiriChatResponse(
            speak="I had trouble listing presentations. Please try again.",
            display=f"Presentation listing error: {exc}",
            session_id=req.session_id,
        )

    presentations = data.get("presentations", [])

    if not presentations:
        return SiriChatResponse(
            speak="There are no presentations yet. Ask me to create one!",
            display="No presentations found.",
            session_id=req.session_id,
        )

    lines = [f"I have {len(presentations)} presentation(s):"]
    links = []
    for p in presentations[:10]:
        title = p.get("title", "Untitled")
        version = p.get("version", "")
        download_url = p.get("download_url", "")
        lines.append(f"- {title} (v{version}): {download_url}")
        if download_url:
            links.append({"title": title, "url": download_url})

    display = "\n".join(lines)
    speak = f"I found {len(presentations)} presentations. " + "\n".join(
        f"{p.get('title', '')} v{p.get('version', '')}"
        for p in presentations[:5]
    )

    return SiriChatResponse(
        speak=_shorten_for_voice(speak),
        display=display,
        session_id=req.session_id,
        links=links,
    )


async def _handle_find_presentation(req: SiriChatRequest) -> SiriChatResponse:
    """Search for presentations by query and return matches with URLs."""
    from core.config import HARNESS_API_KEY, INTERNAL_BASE_URL

    # Extract the search query from the request text
    text = req.text.lower()
    query = req.text
    for prefix in ["find presentation about", "find presentation for",
                   "presentation about", "presentation for",
                   "search presentation for", "search presentation about"]:
        if text.startswith(prefix):
            query = req.text[len(prefix):].strip()
            break

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(
                f"{INTERNAL_BASE_URL.rstrip('/')}/presentation/search",
                params={"title": query},
                headers={"X-API-Key": HARNESS_API_KEY},
            )
            r.raise_for_status()
            data = r.json()
    except Exception as exc:
        return SiriChatResponse(
            speak=f"I had trouble searching presentations. Please try again.",
            display=f"Presentation search error: {exc}",
            session_id=req.session_id,
        )

    presentations = data.get("presentations", [])

    if not presentations:
        return SiriChatResponse(
            speak=f"No presentations found matching '{query}'.",
            display=f"No presentations found matching '{query}'.\n\nTry 'list my presentations' to see all available presentations.",
            session_id=req.session_id,
        )

    lines = [f"Found {len(presentations)} presentation(s) matching '{query}':"]
    links = []
    for p in presentations[:10]:
        title = p.get("title", "Untitled")
        version = p.get("version", "")
        download_url = p.get("download_url", "")
        lines.append(f"- {title} (v{version}): {download_url}")
        if download_url:
            links.append({"title": title, "url": download_url})

    display = "\n".join(lines)
    speak = f"I found {len(presentations)} presentations matching '{query}'."

    return SiriChatResponse(
        speak=_shorten_for_voice(speak),
        display=display,
        session_id=req.session_id,
        links=links,
    )


async def _handle_list_demos(req: SiriChatRequest) -> SiriChatResponse:
    """Return list of all created demos with PUBLIC URLs."""
    demos = _scan_all_demos()

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
    # Extract the search query from the request text
    text = req.text.lower()
    query = req.text
    for prefix in ["find demo about", "find demo for", "demo about", "demo for",
                   "search demo for", "search demo about", "demo"]:
        if text.startswith(prefix):
            query = req.text[len(prefix):].strip()
            break

    all_demos = _scan_all_demos()
    query_lower = query.lower()

    matches = []
    for d in all_demos:
        title = d.get("title", "").lower()
        desc = d.get("description", "").lower()
        tags = " ".join(d.get("tags", [])).lower()
        combined = f"{title} {desc} {tags}"
        if any(term in combined for term in query_lower.split()):
            matches.append(d)

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

    if intent == "create_presentation":
        return await _handle_create_presentation(req)

    if intent == "list_presentations":
        return await _handle_list_presentations(req)

    if intent == "find_presentation":
        return await _handle_find_presentation(req)

    if intent == "deep_research":
        return await _handle_deep_research(req)

    if intent == "research":
        return await _handle_research(req)

    if intent == "image":
        return await _handle_image(req)

    if intent == "create_demo":
        return await _handle_create_demo_workflow(req)

    if intent == "list_demos":
        return await _handle_list_demos(req)

    if intent == "find_demo":
        return await _handle_find_demo(req)

    if intent == "demo_quality":
        return await _handle_demo_quality(req)

    if intent == "demo_complexity":
        return await _handle_demo_complexity(req)

    if intent in {"demo", "html_demo", "pm_demo"}:
        return await _handle_demo(req)

    return await _handle_chat(req)



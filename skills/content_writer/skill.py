#!/usr/bin/env python3
"""
content_writer skill — multi-format content generation.

Purpose:
  Given a topic (and optional brand voice / platform / tone), produce
  publish-ready content in one or more formats:
    - social  : Twitter/X thread, LinkedIn post, short-form caption
    - blog    : full blog post (hook -> context -> 3-5 sections -> CTA)
    - video   : video script + visual seeds (shot list)
    - all     : all of the above

  Optionally grounds the content in real research via mcp_search.

  Design adapted from langchain-ai/deepagents `deploy-content-writer` and
  `content-builder-agent`:
    - brand voice guidance
    - per-format skill prompts (blog-post, social-media, video)

Workflow:
  1. Validate inputs; normalize format/platform/tone/brand.
  2. (Optional) Research grounding via mcp_search (search_web) for the topic.
  3. Generate content per requested format via LiteLLM chat completion.
  4. Save the content as a Markdown artifact.
  5. Return summary, full content, and artifact path.

Constraints:
  - Max runtime: 300 seconds.
  - Read-only: no writes outside the artifact dir.
  - All MCP calls go through LiteLLM — never direct MCP server access.
  - Output format: Markdown.
  - Artifacts saved to /home/chuck/data/media/content/

See skill.yml for the full manifest and README.md for usage.
"""

import json
import logging
import os
import re
import signal
import threading
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ARTIFACT_DIR = Path(
    os.environ.get("CONTENT_WRITER_ARTIFACT_DIR", "/home/chuck/data/media/content")
)
MAX_RUNTIME_SECS = int(os.environ.get("CONTENT_WRITER_MAX_RUNTIME", "300"))

LITELLM_BASE_URL = os.environ.get("LITELLM_BASE_URL", "http://localhost:4000")
LITELLM_API_KEY = os.environ.get("LITELLM_API_KEY", "")
MODEL_ALIAS = os.environ.get("CONTENT_WRITER_MODEL_ALIAS", "matrix-coder")

VALID_FORMATS = {"social", "blog", "video", "all"}
DEFAULT_PLATFORMS = {
    "social": ["Twitter/X", "LinkedIn"],
    "blog": ["blog"],
    "video": ["YouTube"],
}

logger = logging.getLogger("skill.content_writer")

# ---------------------------------------------------------------------------
# Timeout enforcement
# ---------------------------------------------------------------------------


class TimeoutError(Exception):
    """Raised when the skill exceeds its maximum runtime."""


def _timeout_handler(signum, frame):
    raise TimeoutError(f"content_writer exceeded {MAX_RUNTIME_SECS}s max runtime")


def _install_timeout():
    if sys.platform != "win32" and threading.main_thread() is threading.current_thread():
        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(MAX_RUNTIME_SECS)


def _cancel_timeout():
    if sys.platform != "win32" and threading.main_thread() is threading.current_thread():
        signal.alarm(0)


# ---------------------------------------------------------------------------
# LiteLLM client abstraction
# ---------------------------------------------------------------------------


class _SyncLiteLLMClient:
    """Synchronous LiteLLM client for standalone/CLI use."""

    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None) -> None:
        self.base_url = (base_url or LITELLM_BASE_URL).rstrip("/")
        self.api_key = api_key or LITELLM_API_KEY

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def chat_completion(self, model: str, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
        import urllib.request
        import urllib.error

        payload: dict[str, Any] = {"model": model, "messages": messages}
        payload.update(kwargs)
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=data, headers=self._headers(), method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=240) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
            raise RuntimeError(f"LiteLLM HTTP error {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Cannot reach LiteLLM at {self.base_url}: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid JSON from LiteLLM: {exc}") from exc

    def mcp_call(self, tool_name: str, arguments: dict[str, Any],
                 server_id: Optional[str] = None, **kwargs: Any) -> dict[str, Any]:
        import urllib.request
        import urllib.error

        payload: dict[str, Any] = {"name": tool_name, "arguments": arguments}
        if server_id:
            payload["server_id"] = server_id
        payload.update(kwargs)
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/mcp-rest/tools/call",
            data=data, headers=self._headers(), method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            logger.warning("MCP tool call via LiteLLM failed (%s): %s", tool_name, body)
            return {}
        except urllib.error.URLError as exc:
            logger.warning("Cannot reach LiteLLM for MCP tool %s: %s", tool_name, exc)
            return {}
        except json.JSONDecodeError as exc:
            logger.warning("Invalid JSON from LiteLLM MCP call: %s", exc)
            return {}


class _SyncAsyncWrapper:
    """Wraps an async LiteLLMClient from the runner so skill code can call it sync."""

    def __init__(self, async_client):
        self._client = async_client
        self.base_url = getattr(async_client, "base_url", LITELLM_BASE_URL)

    def chat_completion(self, model, messages, **kwargs):
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self._client.chat_completion(model, messages, **kwargs))
        finally:
            loop.close()

    def mcp_call(self, tool_name, arguments, server_id=None, **kwargs):
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                self._client.mcp_call(tool_name, arguments, server_id=server_id, **kwargs)
            )
        finally:
            loop.close()


def _resolve_litellm_client(litellm_client=None) -> Any:
    if litellm_client is None:
        return _SyncLiteLLMClient()
    if hasattr(litellm_client, "chat_completion") and hasattr(litellm_client, "mcp_call"):
        import inspect
        if inspect.iscoroutinefunction(litellm_client.chat_completion):
            return _SyncAsyncWrapper(litellm_client)
        return litellm_client
    return _SyncLiteLLMClient()


# ---------------------------------------------------------------------------
# Robust MCP result extraction
# ---------------------------------------------------------------------------


def _extract_results(result: Any) -> list[dict]:
    """
    Normalize an MCP tool response into a list of result dicts.

    Handles the response shapes returned by the skill-runner's LiteLLMClient
    and the /mcp-rest gateway:
      - {"structuredContent": {"result": [...]}}  (mcp-rest gateway, primary)
      - {"structuredContent": [...]}               (mcp-rest gateway, list)
      - {"result": {"results": [...]}}             (structuredContent variant)
      - {"result": [...]}                          (structured list)
      - {"results": [...]}
      - {"content": [{"type": "text", "text": "<json>"}]}  (content-only)
      - {"output": [{"type": "text", "text": "<json>"}]}
    """
    if not result:
        return []

    # 0. mcp-rest gateway: structuredContent (primary shape)
    sc = result.get("structuredContent")
    if isinstance(sc, list):
        return [r for r in sc if isinstance(r, dict)]
    if isinstance(sc, dict):
        for key in ("result", "results", "data", "items", "matches"):
            if isinstance(sc.get(key), list):
                return [r for r in sc[key] if isinstance(r, dict)]
        if any(k in sc for k in ("title", "url", "snippet", "ticker", "name")):
            return [sc]

    # 1. structured "result" key
    res = result.get("result")
    if isinstance(res, list):
        return [r for r in res if isinstance(r, dict)]
    if isinstance(res, dict):
        for key in ("results", "data", "items", "matches"):
            if isinstance(res.get(key), list):
                return [r for r in res[key] if isinstance(r, dict)]
        return [res]

    # 2. top-level list keys
    for key in ("results", "data", "items", "matches"):
        if isinstance(result.get(key), list):
            return [r for r in result[key] if isinstance(r, dict)]

    # 3. content-only: parse the first text item as JSON (content OR output)
    for key in ("content", "output"):
        output = result.get(key)
        if isinstance(output, list):
            for item in output:
                if isinstance(item, dict) and item.get("type") == "text":
                    text = item.get("text", "")
                    try:
                        parsed = json.loads(text)
                    except (json.JSONDecodeError, TypeError):
                        continue
                    if isinstance(parsed, list):
                        return [r for r in parsed if isinstance(r, dict)]
                    if isinstance(parsed, dict):
                        for k in ("result", "results", "data", "items", "matches"):
                            if isinstance(parsed.get(k), list):
                                return [r for r in parsed[k] if isinstance(r, dict)]
                        return [parsed]
    return []


def _search(client: Any, query: str, max_results: int = 5) -> list[dict]:
    """Run a web search via mcp_search and return normalized result dicts."""
    result = client.mcp_call("search_web", {"query": query, "max_results": max_results},
                             server_id="mcp_search")
    items = _extract_results(result)
    logger.info("search_web returned %d results for: %s", len(items), query[:80])
    return items[:max_results]


# ---------------------------------------------------------------------------
# Format / platform normalization
# ---------------------------------------------------------------------------


def _normalize_format(fmt: str) -> list[str]:
    """Return the list of content formats to generate."""
    fmt = (fmt or "all").strip().lower()
    if fmt == "all":
        return ["social", "blog", "video"]
    if fmt in VALID_FORMATS:
        return [fmt]
    # allow comma-separated
    parts = [p.strip().lower() for p in fmt.split(",") if p.strip()]
    valid = [p for p in parts if p in VALID_FORMATS]
    return valid or ["all"]


def _normalize_platforms(fmt: list[str], platform: Optional[str]) -> dict[str, list[str]]:
    """Return a mapping of format -> list of platforms to target."""
    result: dict[str, list[str]] = {}
    for f in fmt:
        if platform and platform.strip():
            result[f] = [p.strip() for p in platform.split(",") if p.strip()]
        else:
            result[f] = DEFAULT_PLATFORMS.get(f, ["generic"])
    return result


# ---------------------------------------------------------------------------
# LLM prompts per format
# ---------------------------------------------------------------------------

BASE_SYSTEM = textwrap.dedent("""\
    You are a professional content writer. You produce clear, engaging,
    publish-ready content in Markdown. You adapt to the requested platform,
    tone, and brand voice. You never invent statistics without a source;
    when research is provided you ground claims in it and cite source titles
    inline in parentheses. Output ONLY the requested content in Markdown —
    no preamble, no JSON wrapper.
""")


def _social_prompt(platforms: list[str], tone: str, brand: str) -> str:
    return textwrap.dedent(f"""\
        Produce social media content for these platforms: {', '.join(platforms)}.
        Tone: {tone}. Brand voice: {brand}.

        For EACH platform, output a clearly labeled section:

        ### {{platform}}
        - The post, formatted for that platform (e.g. a 5-7 tweet thread for
          Twitter/X with each tweet on its own line prefixed by a number; a
          120-180 word post for LinkedIn; a punchy 1-2 sentence caption for
          short-form).
        - 3-5 relevant hashtags on the final line.

        Rules:
        - Hook in the first line.
        - Specific, concrete, no fluff.
        - Match each platform's native style and length conventions.
        - Output ONLY the Markdown content.
    """)


def _blog_prompt(platforms: list[str], tone: str, brand: str) -> str:
    return textwrap.dedent(f"""\
        Write a full blog post. Tone: {tone}. Brand voice: {brand}.

        Structure (use these exact Markdown headings):
        # {{title}}
        - A compelling title (H1).

        ## Hook
        - 1-2 sentences that grab attention (a surprising fact, question, or
          bold claim).

        ## Context
        - 2-4 sentences of background: why this matters now.

        ## Section 1-3 (or more)
        - 3-5 substantive sections, each with an H2 heading and 2-4 paragraphs.
          Build the argument, use examples, be concrete.

        ## Key Takeaways
        - 3-5 bullet points summarizing the value.

        ## Call to Action
        - 1-2 sentences directing the reader to a next step.

        Rules:
        - 600-1000 words total.
        - Ground claims in the provided research where possible; cite inline.
        - Active voice, short sentences where possible.
        - Output ONLY the Markdown blog post.
    """)


def _video_prompt(platforms: list[str], tone: str, brand: str) -> str:
    return textwrap.dedent(f"""\
        Write a video script PLUS visual seeds (a shot list for a video
        generator). Tone: {tone}. Brand voice: {brand}. Target platform:
        {', '.join(platforms)}.

        Output these Markdown sections:

        ## Video Concept
        - 2-3 sentence high-level concept and target length.

        ## Script
        - A table with columns: | # | Timecode | Narration (VO) | On-screen text |
        - 8-12 beats covering the full video. Timecodes in MM:SS format.

        ## Visual Seeds
        - A numbered list of 8-12 visual prompts (one per beat), each a
          self-contained image-generation prompt describing the scene,
          subject, style, lighting, and camera angle. These will be fed to an
          image/video model.

        Rules:
        - Narration should be spoken naturally (no stage directions in the VO).
        - Visual seeds must be concrete and visual (no abstract concepts).
        - Keep the whole video under 2 minutes.
        - Output ONLY the Markdown.
    """)


PROMPT_BUILDERS = {
    "social": _social_prompt,
    "blog": _blog_prompt,
    "video": _video_prompt,
}


# ---------------------------------------------------------------------------
# Research formatting
# ---------------------------------------------------------------------------


def _format_research(research: list[dict], max_items: int = 20) -> str:
    if not research:
        return (
            "(No external research provided. Rely on your knowledge and avoid "
            "inventing specific statistics.)"
        )
    lines = []
    seen: set[str] = set()
    for item in research[:max_items]:
        url = (item.get("url") or "").strip()
        if url and url in seen:
            continue
        seen.add(url)
        title = (item.get("title") or "Untitled").strip()
        snippet = (item.get("snippet") or item.get("content") or "").strip()
        line = f"- **{title}**"
        if snippet:
            one = snippet.split("\n")[0].strip()
            if len(one) > 220:
                one = one[:217] + "…"
            line += f" — {one}"
        if url:
            line += f" ({url})"
        lines.append(line)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def _generate_section(client: Any, fmt: str, topic: str, platforms: list[str],
                      tone: str, brand: str, research: list[dict],
                      research_enabled: bool) -> str:
    """Generate one content format via LLM."""
    builder = PROMPT_BUILDERS[fmt]
    system = BASE_SYSTEM + "\n" + builder(platforms, tone, brand)

    research_block = ""
    if research_enabled and research:
        research_block = f"\n# Research Findings\n{_format_research(research)}\n"

    user_content = (
        f"# Topic\n{topic}\n"
        f"{research_block}\n"
        f"Produce the {fmt} content now. Output ONLY the Markdown."
    )

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]

    result = client.chat_completion(
        MODEL_ALIAS,
        messages,
        max_tokens=6000,
        temperature=0.7,
        stream=False,
    )

    choices = result.get("choices", [])
    if not choices:
        return f"## {fmt}\n\n*(No content generated — LLM returned no content.)*\n"
    content = (choices[0].get("message") or {}).get("content")
    if not content:
        return f"## {fmt}\n\n*(No content generated — LLM returned empty content.)*\n"
    return content.strip()


# ---------------------------------------------------------------------------
# Artifact generation
# ---------------------------------------------------------------------------


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9\-]+", "-", value).strip("-").lower()
    return slug[:60] or "content"


def _write_artifact(report: str, slug: str) -> Optional[str]:
    try:
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
        filename = f"content_{ts}_{slug}.md"
        path = ARTIFACT_DIR / filename
        path.write_text(report, encoding="utf-8")
        logger.info("Artifact written: %s", path)
        return str(path)
    except OSError as exc:
        logger.error("Could not write artifact: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


def run(params: dict[str, Any], job, litellm_client=None) -> dict[str, Any]:
    """
    Execute the content_writer skill.

    Args:
        params: Skill parameters (prompt, format, platform, tone, brand,
                research).
        job: The runner Job object for logging.
        litellm_client: Optional LiteLLM client from the runner.

    Returns:
        Dict with 'summary', 'content', 'artifact_path', 'formats',
        'research_count', 'model_alias'.
    """
    client = _resolve_litellm_client(litellm_client)

    # Validate inputs
    topic = str(params.get("prompt") or "").strip()
    if not topic:
        if hasattr(job, "add_log"):
            job.add_log("Validation failed: missing 'prompt' (topic)")
        return {"error": "Missing required 'prompt' parameter (topic)"}

    fmt = _normalize_format(str(params.get("format") or "all"))
    platform = str(params.get("platform") or "").strip() or None
    tone = str(params.get("tone") or "professional, clear, engaging").strip()
    brand = str(params.get("brand") or "neutral, helpful, credible").strip()
    research_enabled = bool(params.get("research", True))

    platforms_map = _normalize_platforms(fmt, platform)

    if hasattr(job, "add_log"):
        job.add_log(f"Executing content_writer: formats={fmt} tone='{tone}'")
        job.add_log(f"Model alias: {MODEL_ALIAS}")
        job.add_log(f"Max runtime: {MAX_RUNTIME_SECS}s")
        job.add_log(f"LiteLLM: {client.base_url}")
        job.add_log(f"Research: {'enabled' if research_enabled else 'disabled'}")

    _install_timeout()

    try:
        # Phase 1: Optional research grounding
        research: list[dict] = []
        if research_enabled:
            if hasattr(job, "add_log"):
                job.add_log("Phase 1: research grounding via mcp_search...")
            research.extend(_search(client, topic, max_results=5))
            research.extend(_search(client, f"{topic} best practices", max_results=5))
            # dedupe by URL
            seen: set[str] = set()
            unique: list[dict] = []
            for item in research:
                url = (item.get("url") or "").lower().strip().rstrip("/")
                if not url or url in seen:
                    continue
                seen.add(url)
                unique.append(item)
            research = unique
            if hasattr(job, "add_log"):
                job.add_log(f"Phase 1 complete: {len(research)} unique research items")

        # Phase 2: Generate content per format
        if hasattr(job, "add_log"):
            job.add_log(f"Phase 2: generating content for {len(fmt)} format(s)...")

        sections: list[str] = []
        for f in fmt:
            plats = platforms_map.get(f, ["generic"])
            if hasattr(job, "add_log"):
                job.add_log(f"  generating {f} (platforms: {', '.join(plats)})")
            section = _generate_section(
                client, f, topic, plats, tone, brand, research, research_enabled
            )
            sections.append(section)

        # Assemble the full content document
        header = (
            f"# Content Pack — {topic[:80]}\n\n"
            f"> Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} · "
            f"Model: {MODEL_ALIAS} · Formats: {', '.join(fmt)} · "
            f"Tone: {tone} · Research sources: {len(research)}\n\n"
        )
        body = "\n\n---\n\n".join(sections)
        full_content = header + body

        if hasattr(job, "add_log"):
            job.add_log(f"Content generated ({len(full_content)} chars)")

        # Phase 3: Save artifact
        artifact_path = _write_artifact(full_content, _slugify(topic))
        if hasattr(job, "add_log"):
            job.add_log(f"Artifact saved: {artifact_path or '(inline only)'}")

        # Summary: first few non-empty lines
        summary_lines = [ln for ln in full_content.strip().split("\n") if ln.strip()][:5]
        summary = " ".join(summary_lines).strip()

        return {
            "summary": summary,
            "content": full_content,
            "artifact_path": artifact_path,
            "formats": fmt,
            "platforms": platforms_map,
            "research_count": len(research),
            "model_alias": MODEL_ALIAS,
        }

    except TimeoutError as exc:
        msg = str(exc)
        if hasattr(job, "add_log"):
            job.add_log(f"Timeout: {msg}")
        return {
            "summary": f"Content generation timed out after {MAX_RUNTIME_SECS}s.",
            "error": msg,
            "model_alias": MODEL_ALIAS,
        }

    except RuntimeError as exc:
        msg = str(exc)
        if hasattr(job, "add_log"):
            job.add_log(f"Runtime error: {msg}")
        return {"summary": f"Content generation failed: {msg}", "error": msg, "model_alias": MODEL_ALIAS}

    except Exception as exc:
        msg = f"Unexpected error: {exc}"
        if hasattr(job, "add_log"):
            job.add_log(msg)
        return {"summary": f"Content generation failed: {msg}", "error": msg, "model_alias": MODEL_ALIAS}

    finally:
        _cancel_timeout()


# ---------------------------------------------------------------------------
# CLI entrypoint (for standalone testing)
# ---------------------------------------------------------------------------


class _MockJob:
    """Dummy job object for standalone testing."""

    def __init__(self):
        self.logs: list[str] = []

    def add_log(self, msg: str) -> None:
        self.logs.append(msg)
        print(f"  [LOG] {msg}")


def main():
    """Standalone test entrypoint."""
    import argparse

    parser = argparse.ArgumentParser(description="content_writer standalone test")
    parser.add_argument("--prompt", required=True, help="Topic to write about")
    parser.add_argument("--format", default="all",
                        help="Format: social|blog|video|all (or comma-separated, e.g. 'social,video')")
    parser.add_argument("--platform", default=None, help="Comma-separated platforms")
    parser.add_argument("--tone", default="professional, clear, engaging", help="Tone of voice")
    parser.add_argument("--brand", default="neutral, helpful, credible", help="Brand voice")
    parser.add_argument("--no-research", action="store_true", help="Skip research grounding")
    parser.add_argument("--dry-run", action="store_true", help="Print params without calling services")
    parser.add_argument("--base-url", default=None, help=f"LiteLLM base URL (default: {LITELLM_BASE_URL})")
    parser.add_argument("--api-key", default=None, help="LiteLLM API key")
    args = parser.parse_args()

    if args.dry_run:
        fmt = _normalize_format(args.format)
        print("=== DRY RUN ===")
        print(f"  Topic: {args.prompt}")
        print(f"  Formats: {fmt}")
        print(f"  Platforms: {_normalize_platforms(fmt, args.platform)}")
        print(f"  Tone: {args.tone}")
        print(f"  Brand: {args.brand}")
        print(f"  Research: {'disabled' if args.no_research else 'enabled'}")
        print(f"  Model: {MODEL_ALIAS}")
        print(f"  Max runtime: {MAX_RUNTIME_SECS}s")
        print(f"  Artifact dir: {ARTIFACT_DIR}")
        print(f"  LiteLLM: {LITELLM_BASE_URL}")
        return

    client = _SyncLiteLLMClient(base_url=args.base_url or LITELLM_BASE_URL,
                                api_key=args.api_key or LITELLM_API_KEY)
    params = {
        "prompt": args.prompt,
        "format": args.format,
        "platform": args.platform,
        "tone": args.tone,
        "brand": args.brand,
        "research": not args.no_research,
    }
    result = run(params, _MockJob(), litellm_client=client)

    print("\n--- content_writer response ---")
    print(f"Summary: {result.get('summary', 'N/A')[:300]}")
    print(f"Formats: {result.get('formats', [])}")
    print(f"Research items: {result.get('research_count', 0)}")
    if result.get("artifact_path"):
        print(f"Artifact: {result['artifact_path']}")
    if result.get("error"):
        print(f"Error: {result['error']}")
    print(f"Content length: {len(result.get('content', ''))} chars")


if __name__ == "__main__":
    main()
"""
Presentation service — Presenton API client + metadata persistence.

This module provides the `PresentonClient` for talking to the Presenton
container, plus helpers for saving/scanning presentation metadata on disk.

Session 1 covers the client skeleton and metadata I/O.
Session 2 adds the AI outline generation + research orchestration.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx

from core.config import (
    INTERNAL_BASE_URL,
    PUBLIC_BASE_URL,
    PRESENTON_AUTH_PASSWORD,
    PRESENTON_AUTH_USERNAME,
    PRESENTON_BASE_URL,
)
from presentation.prompts import (
    OUTLINE_GENERATION_PROMPT,
    TITLE_GENERATION_PROMPT,
)
from presentation.schemas import (
    OutlineRequest,
    OutlineResponse,
    PresentationMetadata,
    PresentationRequest,
    PresentationResponse,
)

logger = logging.getLogger(__name__)

# Storage directory for generated presentations (inside container)
_PRESENTATIONS_DIR = Path("/data/media/presentations")
_PRESENTATIONS_DIR.mkdir(parents=True, exist_ok=True)


# ---------- Presenton API client -------------------------------------------

class PresentonClient:
    """HTTP client for the Presenton API.

    Presenton's /api/v1/ routes use HTTP Basic auth (username:password).
    The /generate endpoint blocks until the full generation + export is done
    and returns {presentation_id, path, edit_path} where `path` is the
    relative path to the exported file.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        timeout: float = 300.0,
    ):
        self._base_url = (base_url or PRESENTON_BASE_URL).rstrip("/")
        self._username = username or PRESENTON_AUTH_USERNAME
        self._password = password or PRESENTON_AUTH_PASSWORD
        self._timeout = timeout
        self._generation_timeout = 900.0  # Presenton generation+export can take 5-15 min
        self._session: Optional[httpx.Client] = None

    # -- session management --------------------------------------------------

    def _get_session(self) -> httpx.Client:
        """Return an httpx client configured with HTTP Basic auth."""
        if self._session is None:
            self._session = httpx.Client(
                base_url=self._base_url,
                timeout=self._timeout,
                auth=httpx.BasicAuth(self._username, self._password),
                follow_redirects=True,
            )
        return self._session

    # -- presentation generation ---------------------------------------------

    def _build_payload(
        self,
        content: str,
        *,
        n_slides: int = 8,
        template: str = "general",
        tone: str = "default",
        verbosity: str = "standard",
        language: str = "English",
        export_as: str = "pptx",
        parent_id: Optional[str] = None,
        instructions: Optional[str] = None,
        include_table_of_contents: bool = False,
        include_title_slide: bool = True,
    ) -> dict[str, Any]:
        """Build the standard Presenton generation payload."""
        payload: dict[str, Any] = {
            "content": content,
            "n_slides": n_slides,
            "template": template,
            "tone": tone,
            "verbosity": verbosity,
            "language": language,
            "export_as": export_as,
            "include_table_of_contents": include_table_of_contents,
            "include_title_slide": include_title_slide,
        }
        if instructions:
            payload["instructions"] = instructions
        if parent_id:
            payload["parent_id"] = parent_id
        return payload

    def generate_presentation(
        self,
        content: str,
        *,
        n_slides: int = 8,
        template: str = "general",
        tone: str = "default",
        verbosity: str = "standard",
        language: str = "English",
        export_as: str = "pptx",
        version: Optional[int] = None,
        parent_id: Optional[str] = None,
        instructions: Optional[str] = None,
        include_table_of_contents: bool = False,
        include_title_slide: bool = True,
    ) -> dict[str, Any]:
        """
        Blocking call to Presenton's /generate endpoint.

        Presenton holds the connection open until the full generation +
        export is done (can take 5-15 min), then returns
        {presentation_id, path, edit_path}.

        Used by the sync /generate endpoint and OpenWebUI integration.
        """
        payload = self._build_payload(
            content=content,
            n_slides=n_slides,
            template=template,
            tone=tone,
            verbosity=verbosity,
            language=language,
            export_as=export_as,
            parent_id=parent_id,
            instructions=instructions,
            include_table_of_contents=include_table_of_contents,
            include_title_slide=include_title_slide,
        )

        session = self._get_session()
        resp = session.post(
            "/api/v1/ppt/presentation/generate",
            json=payload,
            timeout=self._generation_timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def generate_presentation_async(
        self,
        content: str,
        *,
        n_slides: int = 8,
        template: str = "general",
        tone: str = "default",
        verbosity: str = "standard",
        language: str = "English",
        export_as: str = "pptx",
        parent_id: Optional[str] = None,
        instructions: Optional[str] = None,
        include_table_of_contents: bool = False,
        include_title_slide: bool = True,
    ) -> dict[str, Any]:
        """
        Non-blocking: submit via /generate-async then poll until done.

        Returns the same dict shape as generate_presentation()
        ({presentation_id, path, edit_path, slide_count, …}).

        Used by Celery workers so we never hold a single HTTP connection
        open for 10-20 minutes (which would kill the worker under Docker).
        """
        payload = self._build_payload(
            content=content,
            n_slides=n_slides,
            template=template,
            tone=tone,
            verbosity=verbosity,
            language=language,
            export_as=export_as,
            parent_id=parent_id,
            instructions=instructions,
            include_table_of_contents=include_table_of_contents,
            include_title_slide=include_title_slide,
        )

        task_resp = self.submit_presentation_async(payload)
        task_id = task_resp.get("id") or task_resp.get("task_id")
        if not task_id:
            raise RuntimeError(
                f"Presenton async submit returned no id: {task_resp!r}"
            )
        logger.info("Presenton async task submitted: task_id=%s", task_id)
        return self.wait_for_presentation_task(task_id)

    def submit_presentation_async(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Submit a generation job asynchronously.

        Calls Presenton's /generate/async which queues the job and returns
        {\"id\": \"task-...\", \"status\": \"pending\", \"message\": \"Queued...\"}.
        """
        session = self._get_session()
        resp = session.post(
            "/api/v1/ppt/presentation/generate/async",
            json=payload,
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()

    def get_task_status(self, task_id: str) -> dict[str, Any]:
        """Poll the status of an async generation task.

        Returns {\"id\", \"status\", \"message\", \"data\"}.
        When status is \"completed\", \"data\" contains
        {presentation_id, path, edit_path}.
        """
        session = self._get_session()
        resp = session.get(
            f"/api/v1/ppt/presentation/status/{task_id}",
            timeout=15.0,
        )
        resp.raise_for_status()
        return resp.json()

    def wait_for_presentation_task(
        self, task_id: str, *, poll_interval: float = 5.0
    ) -> dict[str, Any]:
        """Poll an async task until it completes, returning the final result.

        Returns the same dict shape as /generate:
        {presentation_id, path, edit_path}.
        """
        import time as _time

        for _attempt in range(int(self._generation_timeout / poll_interval) + 1):
            status_resp = self.get_task_status(task_id)
            status = status_resp.get("status", "").lower()

            if status == "completed":
                result = status_resp.get("data")
                if not result:
                    raise RuntimeError(
                        f"Presenton task {task_id} completed but data is empty"
                    )
                logger.info(
                    "Presenton async task %s completed", task_id
                )
                return result

            if status == "error":
                error = (
                    status_resp.get("error")
                    or status_resp.get("message")
                    or "Unknown error"
                )
                raise RuntimeError(
                    f"Presenton task {task_id} failed: {error}"
                )

            logger.info(
                "Presenton task %s in progress (%s), polling in %.0fs…",
                task_id, status_resp.get("message", status), poll_interval,
            )
            _time.sleep(poll_interval)

        raise RuntimeError(
            f"Presenton task {task_id} timed out after {self._generation_timeout:.0f}s"
        )

    def get_presentation(self, presentation_id: str) -> dict[str, Any]:
        """Fetch presentation details from Presenton by ID."""
        session = self._get_session()
        resp = session.get(
            f"/api/v1/ppt/presentation/{presentation_id}",
        )
        resp.raise_for_status()
        return resp.json()

    def download_presentation(self, export_path: str) -> bytes:
        """Download the presentation file using the path from the generate response.

        `export_path` is the `path` field from the /generate response,
        e.g. '/app_data/exports/foo.pptx'.
        """
        session = self._get_session()
        resp = session.get(
            export_path,  # already starts with /
        )
        resp.raise_for_status()
        return resp.content

    # -- cleanup -------------------------------------------------------------

    def close(self):
        if self._session is not None:
            self._session.close()
            self._session = None


# ---------- filename / path helpers ----------------------------------------

def _generate_filename(title: str, version: int, export_as: str = "pptx") -> str:
    """Generate a deterministic filename: {slug}-v{version}.{ext}."""
    slug = _slugify(title)
    return f"{slug}-v{version}.{export_as}"


def _slugify(text: str) -> str:
    """Convert text to a URL-friendly slug."""
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[-\s]+", "-", slug)
    slug = slug.strip("-")
    return slug or "presentation"


def _metadata_filename(filename: str) -> str:
    """Convert a presentation filename to its companion metadata filename."""
    base = filename.rsplit(".", 1)[0]  # remove extension
    return f"{base}.metadata.json"


# ---------- metadata persistence -------------------------------------------

def _save_metadata(metadata: PresentationMetadata) -> str:
    """Write metadata.json alongside the presentation file.

    Returns the path to the written metadata file.
    """
    dest = _PRESENTATIONS_DIR / _metadata_filename(metadata.filename)
    dest.write_text(json.dumps(metadata.model_dump(), indent=2), encoding="utf-8")
    logger.info("Saved metadata to %s", dest)
    return str(dest)


def _scan_presentations() -> list[PresentationMetadata]:
    """Scan /data/media/presentations/ for metadata.json files."""
    results = []
    for path in _PRESENTATIONS_DIR.glob("*.metadata.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            results.append(PresentationMetadata(**data))
        except Exception as exc:
            logger.warning("Failed to read metadata %s: %s", path, exc)
    # Sort newest first
    results.sort(key=lambda m: m.created_at, reverse=True)
    return results


def _find_presentation_by_title(title: str) -> list[PresentationMetadata]:
    """Find all presentations matching a title (fuzzy match on slug)."""
    target_slug = _slugify(title)
    return [
        m for m in _scan_presentations()
        if target_slug in _slugify(m.title)
    ]


def _resolve_parent(parent_id: str) -> Optional[PresentationMetadata]:
    """Fetch the parent presentation's metadata by Presenton ID.

    Returns None if the parent is not found.
    """
    return get_presentation(parent_id)


def _find_latest_version(title: str) -> Optional[PresentationMetadata]:
    """Find the highest version number for a given presentation title."""
    matches = _find_presentation_by_title(title)
    if not matches:
        return None
    return max(matches, key=lambda m: m.version)


def _next_version(title: str) -> int:
    """Return the next version number for a given title."""
    latest = _find_latest_version(title)
    return (latest.version + 1) if latest else 1


# ---------- research / KB helpers (Session 2) -----------------------------

def _do_research(topic: str) -> tuple[str, list[dict]]:
    """Run deep research on the topic via the internal deep_research endpoint.

    Returns (research_text, sources) where sources is a list of dicts.
    """
    from core.config import INTERNAL_BASE_URL
    import httpx as _httpx

    logger.info("Running deep research for topic: %s", topic)
    try:
        with _httpx.Client(timeout=180.0) as client:
            r = client.post(
                f"{INTERNAL_BASE_URL.rstrip('/')}/workflows/deep-research/run",
                headers={"Content-Type": "application/json"},
                json={"query": topic},
            )
            r.raise_for_status()
            data = r.json()

        answer = data.get("answer", "")
        sources = data.get("sources", [])
        logger.info("Deep research completed: %d sources", len(sources))
        return answer, sources
    except Exception as exc:
        logger.warning("Deep research failed (continuing without it): %s", exc)
        return "", []


def _search_kb(topic: str, limit: int = 5) -> tuple[str, list[dict]]:
    """Search the family knowledge base for relevant content on the topic.

    Returns (combined_text, results) where results is a list of hit dicts.
    """
    from family_kb.schemas import SearchRequest
    from family_kb.service import search_kb as kb_search

    logger.info("Searching family KB for topic: %s", topic)
    try:
        result = kb_search(SearchRequest(query=topic, limit=limit))
        hits = result.get("results", [])
        # Combine hit texts into a single context block
        combined = "\n\n".join(
            f"--- Source: {h.get('source', 'unknown')} ---\n{h.get('text', '')}"
            for h in hits
        )
        sources = [
            {"source": h.get("source"), "score": h.get("score")}
            for h in hits
        ]
        logger.info("KB search returned %d hits", len(hits))
        return combined, sources
    except Exception as exc:
        logger.warning("KB search failed (continuing without it): %s", exc)
        return "", []


# ---------- outline generation (Session 2) --------------------------------

def _generate_outline(
    topic: str,
    *,
    title: str,
    n_slides: int = 8,
    tone: str = "default",
    verbosity: str = "standard",
    language: str = "English",
    instructions: str | None = None,
    research_context: str = "",
    kb_context: str = "",
) -> str:
    """Use the LLM to generate a markdown outline for a presentation.

    Returns the raw outline markdown text.
    """
    from core.llm import chat_completion_sync

    # Merge research + KB context into one block
    context_parts = []
    if research_context:
        context_parts.append(f"Research findings:\n{research_context}")
    if kb_context:
        context_parts.append(f"Knowledge base excerpts:\n{kb_context}")
    context_block = "\n\n".join(context_parts) if context_parts else ""

    # Build instructions block
    instr_parts = [f"Generate approximately {n_slides} content slides."]
    if instructions:
        instr_parts.append(instructions)
    instructions_block = "\n".join(instr_parts) if instr_parts else ""

    prompt = OUTLINE_GENERATION_PROMPT.format(
        topic=topic,
        title=title,
        instructions=instructions_block,
        research_context=context_block,
        n_slides=n_slides,
        tone=tone,
        verbosity=verbosity,
        language=language,
        include_table_of_contents=False,
    )

    logger.info("Generating outline via LLM for: %s", topic)
    outline = chat_completion_sync(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=4096,
        timeout=120.0,
    )
    logger.info("Outline generated (%d chars)", len(outline))
    return outline


def _count_outline_slides(outline: str) -> int:
    """Estimate the number of slides from the outline markdown."""
    import re as _re
    # Count ## N. headings
    matches = _re.findall(r"^##\s+\d+\.\s+", outline, _re.MULTILINE)
    return len(matches) if matches else 8  # fallback to default


# ---------- public service functions (Session 2) --------------------------

def generate_outline(
    client: PresentonClient,
    req: OutlineRequest,
) -> OutlineResponse:
    """Standalone outline generation (for the collaborative flow).

    Optionally runs research and/or KB search first, then generates
    an outline via the LLM.
    """
    # Gather context
    sources: list[dict] = []
    research_context = ""
    kb_context = ""

    if req.research:
        research_context, research_sources = _do_research(req.topic)
        sources.extend(research_sources)

    if req.kb_search:
        kb_context, kb_sources = _search_kb(req.topic)
        sources.extend(kb_sources)

    # If there's an existing outline, we refine it; otherwise generate fresh
    topic = req.topic
    if req.existing_outline:
        # Use the existing outline as the base topic context
        topic = f"Refine the following outline:\n\n{req.existing_outline}"

    # Generate the outline via LLM
    outline = _generate_outline(
        topic=topic,
        title=req.topic,
        n_slides=8,  # default for outline-only; caller picks n_slides at generate time
        tone="default",
        instructions=req.instructions,
        research_context=research_context,
        kb_context=kb_context,
    )

    # Extract a title from the outline (first # heading)
    import re as _re
    title_match = _re.search(r"^#\s+(.+)$", outline, _re.MULTILINE)
    title = title_match.group(1).strip() if title_match else req.topic

    slide_count = _count_outline_slides(outline)

    return OutlineResponse(
        outline=outline,
        title=title,
        slide_count=slide_count,
        sources=sources,
    )


def _run_generation_pipeline(
    client: PresentonClient,
    req: PresentationRequest,
    *,
    use_async: bool = False,
) -> PresentationResponse:
    """
    Full presentation generation pipeline (internal workhorse).

    When `use_async=True` (Celery workers), calls Presenton's /generate-async
    + polls so we never hold a single HTTP connection open for 10-20 min.
    When `use_async=False` (sync/OpenWebUI), calls blocking /generate.
    """
    # Phase 1: Gather context (research + KB)
    sources: list[dict] = []
    research_context = ""
    kb_context = ""

    if req.research:
        research_context, research_sources = _do_research(req.content)
        sources.extend(research_sources)

    if req.kb_search:
        kb_context, kb_sources = _search_kb(req.content)
        sources.extend(kb_sources)

    # Phase 2: Outline — use provided outline or generate via LLM
    outline = req.outline
    if not outline:
        outline = _generate_outline(
            topic=req.content,
            title=req.title,
            n_slides=req.n_slides,
            tone=req.tone,
            verbosity=req.verbosity,
            language=req.language,
            instructions=req.instructions,
            research_context=research_context,
            kb_context=kb_context,
        )

    # Phase 3: Resolve version and title from parent if parent_id is provided
    if req.parent_id is not None and req.version is None:
        parent_meta = _resolve_parent(req.parent_id)
        if parent_meta is not None:
            if req.title == parent_meta.title or not req.title:
                req.title = parent_meta.title
            version = parent_meta.version + 1
            logger.info(
                "Resolved parent %s: title=%s, next_version=%d",
                req.parent_id, parent_meta.title, version,
            )
        else:
            version = _next_version(req.title)
            logger.warning(
                "Parent %s not found, using _next_version for title %s",
                req.parent_id, req.title,
            )
    else:
        version = req.version if req.version is not None else _next_version(req.title)

    # Phase 4: Call Presenton
    presenton_fn = (
        client.generate_presentation_async if use_async
        else client.generate_presentation
    )
    result = presenton_fn(
        content=outline,
        n_slides=req.n_slides,
        template=req.template,
        tone=req.tone,
        verbosity=req.verbosity,
        language=req.language,
        export_as=req.export_as,
        parent_id=req.parent_id,
        instructions=req.instructions,
        include_table_of_contents=req.include_table_of_contents,
        include_title_slide=req.include_title_slide,
    )

    presentation_id = result.get("presentation_id") or result.get("id") or uuid.uuid4().hex[:12]

    # Phase 5: Download the file from Presenton using the path from the response
    export_path = result.get("path")
    if not export_path:
        raise RuntimeError(
            f"Presenton generate response missing 'path' field: {result!r}"
        )
    file_bytes = client.download_presentation(export_path)

    # Phase 6: Save to local storage
    filename = _generate_filename(req.title, version, req.export_as)
    local_path = _PRESENTATIONS_DIR / filename
    local_path.write_bytes(file_bytes)

    # Build URLs
    download_url = f"{PUBLIC_BASE_URL.rstrip('/')}/media/files/presentations/{filename}"
    internal_download_url = f"{INTERNAL_BASE_URL.rstrip('/')}/presentation/download/{filename}"
    edit_url = f"{PRESENTON_BASE_URL.rstrip('/')}/presentation?id={presentation_id}"

    # Phase 7: Build and persist metadata
    metadata = PresentationMetadata(
        presentation_id=presentation_id,
        title=req.title,
        version=version,
        parent_id=req.parent_id,
        slide_count=result.get("slide_count") or req.n_slides,
        filename=filename,
        local_path=str(local_path),
        download_url=download_url,
        internal_download_url=internal_download_url,
        edit_url=edit_url,
        metadata_path=str(_PRESENTATIONS_DIR / _metadata_filename(filename)),
        created_at=datetime.now(timezone.utc).isoformat(),
        outline=outline,
        sources=sources,
    )

    metadata.metadata_path = _save_metadata(metadata)

    return PresentationResponse(
        presentation_id=presentation_id,
        title=req.title,
        version=version,
        parent_id=req.parent_id,
        slide_count=metadata.slide_count,
        local_path=str(local_path),
        download_url=download_url,
        internal_download_url=internal_download_url,
        edit_url=edit_url,
        metadata_path=metadata.metadata_path,
    )


def generate_presentation_sync(
    client: PresentonClient,
    req: PresentationRequest,
) -> PresentationResponse:
    """Synchronous generation — uses blocking /generate (for OpenWebUI / direct API)."""
    return _run_generation_pipeline(client, req, use_async=False)


def generate_presentation_for_worker(
    client: PresentonClient,
    req: PresentationRequest,
) -> PresentationResponse:
    """Async generation — uses /generate-async + polling (for Celery workers)."""
    return _run_generation_pipeline(client, req, use_async=True)


def list_presentations() -> list[PresentationMetadata]:
    """List all presentations from disk."""
    return _scan_presentations()


def get_presentation(presentation_id: str) -> Optional[PresentationMetadata]:
    """Find a presentation by its Presenton ID."""
    for meta in _scan_presentations():
        if meta.presentation_id == presentation_id:
            return meta
    return None


def delete_presentation(presentation_id: str) -> bool:
    """Delete a presentation file and its metadata."""
    meta = get_presentation(presentation_id)
    if not meta:
        return False

    filepath = Path(meta.local_path)
    if filepath.exists():
        filepath.unlink()

    metadata_path = Path(meta.metadata_path)
    if metadata_path.exists():
        metadata_path.unlink()

    logger.info("Deleted presentation %s (%s)", presentation_id, meta.title)
    return True


def find_presentations(title: str) -> list[PresentationMetadata]:
    """Find presentations by title (fuzzy match)."""
    return _find_presentation_by_title(title)


# ---------- Session 4: regeneration / versioning ---------------------------

def regenerate_presentation(
    client: PresentonClient,
    presentation_id: str,
    update: "PresentationUpdateRequest",
) -> PresentationResponse:
    """Regenerate a presentation with modified parameters, creating a new version.

    Reads the existing presentation's metadata, merges in the requested updates,
    and creates a new version with auto-incremented version number.

    All fields in `update` are optional — only the provided fields override
    the parent's values.
    """
    # Find the parent presentation
    parent_meta = get_presentation(presentation_id)
    if parent_meta is None:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=404,
            detail=f"Presentation {presentation_id} not found",
        )

    # Build a new PresentationRequest by merging parent values with updates
    title = update.title if update.title is not None else parent_meta.title
    content = update.content if update.content is not None else parent_meta.outline or title

    req = PresentationRequest(
        title=title,
        content=content,
        outline=update.outline if update.outline is not None else parent_meta.outline,
        research=update.research if update.research is not None else False,
        kb_search=update.kb_search if update.kb_search is not None else False,
        n_slides=update.n_slides if update.n_slides is not None else parent_meta.slide_count,
        template=update.template if update.template is not None else "general",
        tone=update.tone if update.tone is not None else "default",
        verbosity=update.verbosity if update.verbosity is not None else "standard",
        language=update.language if update.language is not None else "English",
        export_as=update.export_as if update.export_as is not None else "pptx",
        parent_id=presentation_id,  # Link to the parent
        instructions=update.instructions,
        include_table_of_contents=(
            update.include_table_of_contents
            if update.include_table_of_contents is not None
            else False
        ),
        include_title_slide=(
            update.include_title_slide
            if update.include_title_slide is not None
            else True
        ),
    )

    logger.info(
        "Regenerating presentation %s → new version of %s",
        presentation_id,
        parent_meta.title,
    )

    return generate_presentation_sync(client, req)
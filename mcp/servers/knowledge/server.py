#!/usr/bin/env python3
"""MCP Knowledge Server v2 — the family KB (Qdrant `kb_*` collections).

The LLM is the operator: no watcher, no pipeline. Tools:
  Read:    kb_search, kb_get_document, kb_list_documents, kb_overview,
           kb_recent_changes
  Write:   kb_ingest_file, kb_add_fact, kb_delete_document,
           kb_forget, kb_correct
  Backup:  kb_backup

Design (kb-todo.md §3):
- One `kb_<slug>` collection per KB domain, created on the fly (768-dim
  Cosine). The `kb_` prefix is the isolation boundary: KB_API_KEY is a
  global-`m` Qdrant JWT (per-collection scoping CANNOT cover on-the-fly
  collections — proven 2026-08-29: Qdrant 403 "Global access is required"
  on collection create with a scoped JWT), so the CODE enforces the `kb_`
  prefix on every Qdrant operation. K7 audit-log scan proves it holds.
- Manifest point per collection (kind=manifest, required description on
  new-KB creation) — filtered out of search.
- Deterministic point IDs: sha256(source + ":" + chunk_index) → UUID.
  Re-ingest is an idempotent upsert; deletes are exact.
- Embeddings via LiteLLM `embeddings` alias (nomic, 768-dim), batched.
- Vision (page-render fallback + standalone images) via LiteLLM
  `matrix-coder` (≤5 images/call, thinking OFF).

Transport: streamable-http 0.0.0.0:8000 (ai-net only, no published ports).
"""

import asyncio
import base64
import hashlib
import io
import json
import logging
import os
import re
import tarfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import httpx
from mcp.server import FastMCP
from qdrant_client import AsyncQdrantClient
from qdrant_client.http.exceptions import UnexpectedResponse
from qdrant_client.models import (
    Direction,
    Distance,
    FieldCondition,
    Filter,
    IsEmptyCondition,
    MatchValue,
    OrderBy,
    PayloadField,
    VectorParams,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

QDRANT_URL: str = os.environ.get("QDRANT_URL", "http://qdrant:6333")
# Global-`m` JWT (sub=mcp-knowledge). Broader than the code will ever use —
# the `kb_` prefix gate below is the actual security boundary (see module
# docstring + kb-todo.md §3.1).
KB_API_KEY: str = os.environ.get("KB_API_KEY", "")
HTTP_TIMEOUT: float = float(os.environ.get("QDRANT_TIMEOUT", "30"))

LITELLM_API_BASE: str = os.environ.get(
    "LITELLM_API_BASE", "http://litellm-proxy:4000").rstrip("/")
LITELLM_API_KEY: str = os.environ.get("LITELLM_API_KEY", "")
EMBED_MODEL: str = os.environ.get("EMBED_MODEL", "embeddings")
VISION_MODEL: str = os.environ.get("VISION_MODEL", "matrix-coder")
EMBED_DIM: int = int(os.environ.get("EMBED_DIM", "768"))
EMBED_BATCH: int = int(os.environ.get("KB_EMBED_BATCH", "32"))
VISION_TIMEOUT: float = float(os.environ.get("VISION_TIMEOUT", "300"))
VISION_MAX_IMAGES: int = 5

# Source-path allowlist for kb_ingest_file (resolve() under one of these).
KB_ALLOWED_ROOTS: list[str] = [
    r.rstrip("/") for r in
    os.environ.get(
        "KB_ALLOWED_ROOTS",
        "/data/media,/data/workspace,/data/ai-kb/raw").split(",") if r
]
# Writable backup target (mounted rw from /home/chuck/data/backups/kb).
KB_BACKUP_DIR: str = os.environ.get("KB_BACKUP_DIR", "/backups/kb")

MAX_TOP_K: int = 20
DEFAULT_TOP_K: int = 5
SNIPPET_MAX_CHARS: int = 400
CORRECT_SCORE_GATE: float = float(os.environ.get("KB_CORRECT_GATE", "0.75"))
# Chunking: ~1200 tokens ≈ 4800 chars (4 chars/token), 15% overlap.
CHUNK_TARGET_CHARS: int = 4800
CHUNK_OVERLAP_FRAC: float = 0.15
# Quality gate: a PDF page flagged (image/table) with less text than this
# gets the vision page-render fallback.
PAGE_MIN_TEXT_CHARS: int = 200

logger = logging.getLogger("mcp_knowledge")

# ---------------------------------------------------------------------------
# `kb_` prefix gate — enforced on EVERY collection name this server uses
# ---------------------------------------------------------------------------

_KB_RE = re.compile(r"^kb_[a-z0-9_]{1,60}$")


def _validate_collection(name: str) -> str:
    """Reject any collection that is not `kb_*`. The KB key is global-`m`;
    this gate is what keeps it from ever touching mem0_memories etc."""
    if not isinstance(name, str) or not _KB_RE.fullmatch(name):
        raise ValueError(
            f"Collection '{name}' rejected: mcp_knowledge only operates on "
            f"kb_* collections (prefix gate).")
    return name


def _kb_name(friendly: str) -> str:
    """Slugify a friendly KB name ('Side Biz Project Blah') to kb_<slug>.
    Accepts names that already carry the kb_ prefix (no double-prefix)."""
    if not isinstance(friendly, str) or not friendly.strip():
        raise ValueError("KB name is required (a short friendly name).")
    s = friendly.strip()
    if s.lower().startswith("kb_"):
        s = s[3:]
    s = re.sub(r"[^a-z0-9]+", "_", s.lower())
    s = re.sub(r"_+", "_", s).strip("_")[:40].strip("_")
    if not s:
        raise ValueError(f"KB name '{friendly}' slugifies to nothing — use letters/digits.")
    return _validate_collection(f"kb_{s}")


def _point_id(source: str, chunk_index: int) -> uuid.UUID:
    """Deterministic point ID: sha256(source + ':' + chunk_index) → UUID."""
    h = hashlib.sha256(f"{source}:{chunk_index}".encode()).hexdigest()[:32]
    return uuid.UUID(hex=h)


def _manifest_id(collection: str) -> uuid.UUID:
    h = hashlib.sha256(f"manifest:{collection}".encode()).hexdigest()[:32]
    return uuid.UUID(hex=h)


def _as_id(pid) -> int | uuid.UUID:
    """Coerce a point ID (str/int/uuid) to a Qdrant-acceptable ID."""
    if isinstance(pid, int):
        return pid
    s = str(pid).strip()
    if s.isdigit():
        return int(s)
    return uuid.UUID(s)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_missing_collection(e: Exception) -> bool:
    """True only for a real Qdrant 404 (collection does not exist).

    status_code lives on the attribute in current qdrant-client (args[0]
    is None there); check both for version tolerance.
    """
    if not isinstance(e, UnexpectedResponse):
        return False
    status = getattr(e, "status_code", None)
    if status is None:
        status = e.args[0] if e.args else None
    return status == 404


def _truncate(text: str, max_chars: int = SNIPPET_MAX_CHARS) -> str:
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    t = text[:max_chars]
    i = t.rfind(" ")
    if i > max_chars * 0.5:
        t = t[:i]
    return t.rstrip() + "…"

# ---------------------------------------------------------------------------
# LiteLLM: vision (≤5 images, thinking OFF) + embeddings (batched)
# ---------------------------------------------------------------------------


def _vision_call_sync(prompt: str, images_b64: list[str]) -> str:
    """Sync httpx chat-completions call with image content (≤5 images).
    Thinking OFF (Qwen3 thinking burns the completion budget and returns
    content=None). 3 attempts with backoff on 429/5xx/timeout."""
    if len(images_b64) > VISION_MAX_IMAGES:
        raise ValueError(f"vision cap is {VISION_MAX_IMAGES} images/call.")
    content: list[dict] = [
        {"type": "image_url",
         "image_url": {"url": f"data:image/png;base64,{b64}"}}
        for b64 in images_b64
    ]
    content.append({"type": "text", "text": prompt})
    payload = {
        "model": VISION_MODEL,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0.1,
        "max_tokens": 2048,
        "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
    }
    last: Optional[Exception] = None
    for attempt in range(3):
        try:
            r = httpx.post(
                f"{LITELLM_API_BASE}/v1/chat/completions", json=payload,
                headers={"Authorization": f"Bearer {LITELLM_API_KEY}"},
                timeout=VISION_TIMEOUT)
            if r.status_code == 429 or r.status_code >= 500:
                last = RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
                time.sleep(5 * (attempt + 1))
                continue
            r.raise_for_status()
            text = (r.json()["choices"][0]["message"].get("content") or "").strip()
            if not text:
                raise RuntimeError("empty vision content (thinking leak?)")
            return text
        except (httpx.TimeoutException, httpx.HTTPError) as e:
            last = e
            time.sleep(5 * (attempt + 1))
        except RuntimeError:
            raise
    raise RuntimeError(f"vision call failed after 3 attempts: {last}")


async def _vision(prompt: str, images_b64: list[str]) -> str:
    return await asyncio.to_thread(_vision_call_sync, prompt, images_b64)# ---------------------------------------------------------------------------
# Embeddings (LiteLLM /v1/embeddings, batched)
# ---------------------------------------------------------------------------

def _embed_sync(texts: list[str]) -> list[list[float]]:
    """Embed texts via LiteLLM REST. Batches of EMBED_BATCH, 3 retries."""
    out: list[list[float]] = []
    for i in range(0, len(texts), EMBED_BATCH):
        batch = texts[i:i + EMBED_BATCH]
        last: Exception | None = None
        for attempt in range(3):
            try:
                r = httpx.post(
                    f"{LITELLM_API_BASE}/v1/embeddings",
                    json={"model": EMBED_MODEL, "input": batch},
                    headers={"Authorization": f"Bearer {LITELLM_API_KEY}"},
                    timeout=120,
                )
                r.raise_for_status()
                data = r.json()["data"]
                out.extend(d["embedding"] for d in sorted(data, key=lambda x: x["index"]))
                if i == 0 and len(out) > 0:
                    logger.info("embedding dim check: %d (expected %d)",
                                len(out[0]), EMBED_DIM)
                    if len(out[0]) != EMBED_DIM:
                        raise RuntimeError(
                            f"embedding dim {len(out[0])} != expected {EMBED_DIM} "
                            f"(EMBED_MODEL={EMBED_MODEL}) — check the alias.")
                break
            except Exception as e:  # noqa: BLE001 — retry on any transport error
                last = e
                time.sleep(5 * (attempt + 1))
        else:
            raise RuntimeError(f"embedding failed after 3 attempts: {last}")
    return out


async def _embed(texts: list[str]) -> list[list[float]]:
    return await asyncio.to_thread(_embed_sync, texts)


# ---------------------------------------------------------------------------
# Qdrant client + collection helpers
# ---------------------------------------------------------------------------

def _client() -> AsyncQdrantClient:
    return AsyncQdrantClient(
        url=QDRANT_URL, timeout=HTTP_TIMEOUT, api_key=KB_API_KEY or None)


async def _list_kb_collections(client: AsyncQdrantClient) -> list[str]:
    r = await client.get_collections()
    return sorted(c.name for c in r.collections if c.name.startswith("kb_"))


async def _ensure_collection(
    client: AsyncQdrantClient, col: str, description: str
) -> bool:
    """Create kb_<slug> (768-dim Cosine) + manifest point if missing.
    Returns True if created. `description` is REQUIRED on creation (owner N4)
    — the manifest is the LLM's map of the KB."""
    _validate_collection(col)
    r = await client.get_collections()
    if col in {c.name for c in r.collections}:
        return False
    if not description or not description.strip():
        raise ValueError(
            f"KB '{col}' does not exist yet — 'description' is required when "
            f"creating a new KB (a 1-3 sentence summary of what it covers; "
            f"derive it from the user's request or ask). Re-call with "
            f"description='...'")
    await client.create_collection(
        col, vectors_config=VectorParams(size=EMBED_DIM, distance=Distance.COSINE))
    # Payload index on ingested_at: enables kb_recent_changes (order_by).
    # ISO-8601 UTC strings; 'datetime' schema lets Qdrant validate + sort.
    try:
        await client.create_payload_index(
            col, field_name="ingested_at", field_schema="datetime")
    except Exception as e:  # noqa: BLE001 — index is an optimization
        logger.warning("payload index on ingested_at failed for %s: %s", col, e)
    now = _now()
    vec = (await _embed([description.strip()]))[0]
    await client.upsert(col, points=[{
        "id": _manifest_id(col),
        "vector": vec,
        "payload": {
            "text": description.strip(), "kind": "manifest",
            "source": "manifest", "chunk_index": 0, "page_range": None,
            "sha256": None, "ingested_at": now, "updated_at": now,
        },
    }])
    logger.info("created KB collection %s (%d-dim)", col, EMBED_DIM)
    return True


def _search_filter() -> Filter:
    """Filter out manifest points and superseded points from search.

    A point is kept when: kind != manifest AND superseded_by is empty/absent.
    `must_not[is_empty]` would wrongly drop every non-superseded point, so the
    superseded check is nested: must_not[ must_not[ is_empty ] ].
    """
    return Filter(must_not=[
        FieldCondition(key="kind", match=MatchValue(value="manifest")),
        Filter(must_not=[
            IsEmptyCondition(is_empty=PayloadField(key="superseded_by")),
        ]),
    ])


# ---------------------------------------------------------------------------
# Source-path validation (kb_ingest_file)
# ---------------------------------------------------------------------------

def _validate_source_path(path_str: str) -> Path:
    """Resolve a local path and require it to sit under an allowed root.
    Symlinks are resolved first (no escape via ../ or links)."""
    if not path_str or not path_str.strip():
        raise ValueError("path is required.")
    p = Path(path_str).expanduser()
    if not p.is_absolute():
        raise ValueError(f"path must be absolute (container path): {path_str}")
    rp = p.resolve()
    for root in KB_ALLOWED_ROOTS:
        rr = Path(root).resolve()
        if rp == rr or rr in rp.parents:
            return rp
    allowed = ", ".join(KB_ALLOWED_ROOTS)
    raise ValueError(
        f"Path '{path_str}' is outside the allowed source roots ({allowed}). "
        f"Drop files into /home/chuck/data/ai-kb/raw/ (canonical) or pass a "
        f"media//workspace path.")


def _file_sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Conversion (markitdown + pymupdf) + quality gate + vision fallback
# ---------------------------------------------------------------------------

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
_VISION_PAGE_PROMPT = (
    "This is page {page} of a document. Transcribe its content to markdown: "
    "body text verbatim, tables as markdown tables, and describe any "
    "diagrams/images in one or two sentences. Output markdown only, no "
    "preamble."
)


def _render_page_png(pymupdf_doc, page_index: int, dpi: int = 150) -> bytes:
    import fitz  # pymupdf (lazy — heavy import)
    page = pymupdf_doc[page_index]
    pix = page.get_pixmap(dpi=dpi)
    return pix.tobytes("png")


def _pdf_pages(p: Path) -> tuple[str, list[dict], list[str]]:
    """PDF → (markdown, page_meta, warnings). Page-by-page pymupdf pass;
    quality gate + vision fallback for image/table pages with thin text."""
    import fitz  # pymupdf
    warnings: list[str] = []
    doc = fitz.open(str(p))
    try:
        n_pages = len(doc)
        page_texts: list[str] = []
        flagged: list[int] = []
        for i in range(n_pages):
            page = doc[i]
            text = page.get_text("text")
            has_image = len(page.get_images()) > 0
            has_table = False
            try:
                has_table = len(page.find_tables().tables) > 0
            except Exception:  # noqa: BLE001 — find_tables may fail on odd pages
                pass
            page_texts.append(text)
            if (has_image or has_table) and len(text.strip()) < PAGE_MIN_TEXT_CHARS:
                flagged.append(i)
        # Vision fallback: ≤5 pages per call, rendered at 150 dpi.
        if flagged:
            for j in range(0, len(flagged), VISION_MAX_IMAGES):
                batch = flagged[j:j + VISION_MAX_IMAGES]
                b64s = []
                for i in batch:
                    b64s.append(base64.b64encode(
                        _render_page_png(doc, i)).decode())
                prompt = (
                    f"You are given {len(batch)} pages of a document. For each "
                    f"page, output a section starting with '## Page "
                    f"{batch[0] + 1}' (incrementing per page): transcribed "
                    f"markdown (body text, tables as markdown tables, brief "
                    f"image descriptions). Output markdown only."
                )
                try:
                    md = _vision_call_sync(prompt, b64s)
                    for i in batch:
                        page_texts[i] = (page_texts[i].strip() + "\n\n"
                                         if page_texts[i].strip() else "") + md
                    warnings.append(
                        f"pages {[(i + 1) for i in batch]} had thin text with "
                        f"image/table content — vision fallback applied "
                        f"({VISION_MODEL})")
                except Exception as e:  # noqa: BLE001
                    warnings.append(
                        f"vision fallback FAILED for pages "
                        f"{[i + 1 for i in batch]}: {e} (raw text kept)")
        markdown = "\n\n".join(
            f"<!-- page {i + 1} -->\n{t.strip()}"
            for i, t in enumerate(page_texts) if t.strip()
        )
        page_meta = [{"page": i + 1, "chars": len(t)} for i, t in enumerate(page_texts)]
        return markdown, page_meta, warnings
    finally:
        doc.close()


def _convert_markitdown(p: Path) -> tuple[str, list[dict], list[str]]:
    from markitdown import MarkItDown
    md = MarkItDown()
    result = md.convert(str(p))
    text = (result.text_content or "").strip()
    if not text:
        raise RuntimeError(
            f"markitdown produced no text for {p.name} (unsupported or "
            f"empty file). Supported: pdf, docx, pptx, xlsx, html, csv, "
            f"epub, txt, md, zip.")
    return text, [], []


def _convert_image(p: Path) -> tuple[str, list[dict], list[str]]:
    """Standalone image → EXIF-ish metadata + vision description (K4)."""
    import struct
    size = p.stat().st_size
    b64 = base64.b64encode(p.read_bytes()).decode()
    prompt = (
        "Describe this image for a knowledge base: subject, key details, and "
        "transcribe any visible text verbatim. If it contains a table, output "
        "the table as a markdown table. Output markdown only."
    )
    md = _vision_call_sync(prompt, [b64])
    head = f"<!-- image: {p.name} ({size} bytes) -->\n"
    return head + md, [{"page": 1, "chars": len(md)}], []


def _convert_file(p: Path) -> tuple[str, list[dict], list[str]]:
    """Dispatch by extension. Returns (markdown, page_meta, warnings)."""
    suffix = p.suffix.lower()
    if suffix == ".pdf":
        return _pdf_pages(p)
    if suffix in _IMAGE_EXTS:
        return _convert_image(p)
    return _convert_markitdown(p)


# ---------------------------------------------------------------------------
# Chunking (~1200 tokens, 15% overlap, heading/page-boundary preferred)
# ---------------------------------------------------------------------------

def _chunk_markdown(markdown: str) -> list[dict]:
    """Chunk markdown into ~CHUNK_TARGET_CHARS pieces.

    Paragraphs are packed greedily; a page marker (<!-- page N -->) or a
    markdown heading is a preferred break point. Each chunk carries
    chunk_index + page_range (from page markers; None for non-paged files).
    """
    items: list[tuple[Optional[int], str]] = []
    current_page: Optional[int] = None
    buf: list[str] = []
    for line in markdown.splitlines():
        m = re.match(r"<!--\s*page\s+(\d+)\s*-->", line.strip())
        if m:
            if buf:
                items.append((current_page, "\n".join(buf)))
                buf = []
            current_page = int(m.group(1))
            continue
        buf.append(line)
    if buf:
        items.append((current_page, "\n".join(buf)))

    # Merge consecutive same-page items.
    merged: list[tuple[Optional[int], str]] = []
    for page, text in items:
        text = text.strip()
        if not text:
            continue
        if merged and merged[-1][0] == page:
            merged[-1] = (page, merged[-1][1] + "\n\n" + text)
        else:
            merged.append((page, text))

    # Break oversized items at paragraph boundaries (a single long page,
    # or a whole non-paged document) so no chunk exceeds ~CHUNK_TARGET_CHARS;
    # hard-split as a last resort.
    pieces: list[tuple[Optional[int], str]] = []
    for page, text in merged:
        buf = ""
        for para in text.split("\n\n"):
            para = para.strip()
            if not para:
                continue
            while len(para) > CHUNK_TARGET_CHARS:
                pieces.append((page, para[:CHUNK_TARGET_CHARS]))
                para = para[CHUNK_TARGET_CHARS:]
            if buf and len(buf) + len(para) + 2 > CHUNK_TARGET_CHARS:
                pieces.append((page, buf))
                buf = para
            else:
                buf = (buf + "\n\n" + para) if buf else para
        if buf:
            pieces.append((page, buf))

    # Pack pieces into chunks with 15% overlap at a paragraph boundary.
    chunks: list[tuple[str, set[int]]] = []
    cur = ""
    cur_pages: set[int] = set()
    for page, text in pieces:
        if cur and len(cur) + len(text) + 2 > CHUNK_TARGET_CHARS:
            chunks.append((cur, cur_pages))
            # 15% overlap, aligned to a paragraph boundary.
            ov = int(CHUNK_TARGET_CHARS * CHUNK_OVERLAP_FRAC)
            tail = cur[-ov:]
            idx = tail.find("\n\n")
            tail = tail[idx + 2:] if idx > 0 else ""
            cur = (tail + "\n\n" + text) if tail else text
            cur_pages = {page} if page is not None else set()
        else:
            cur = (cur + "\n\n" + text) if cur else text
            if page is not None:
                cur_pages.add(page)
    if cur.strip():
        chunks.append((cur, cur_pages))

    return [
        {
            "text": t,
            "chunk_index": i,
            "page_range": [min(p), max(p)] if p else None,
        }
        for i, (t, p) in enumerate(chunks)
    ]# ---------------------------------------------------------------------------
# MCP server + tools
# ---------------------------------------------------------------------------

MCPS_HOST: str = os.environ.get("MCPS_HOST", "0.0.0.0")

mcp = FastMCP(
    name="mcp_knowledge",
    instructions=(
        "Family knowledge base (Qdrant kb_* collections, one per KB domain, "
        "created on the fly). The LLM is the operator: ingest files with "
        "kb_ingest_file (canonical drop point /home/chuck/data/ai-kb/raw/), "
        "add facts with kb_add_fact, query with kb_search. A 'description' "
        "is required when creating a new KB. kb_forget is two-step (matches "
        "first, confirm=true + ids to delete). kb_correct supersedes a "
        "matched fact. kb_backup snapshots all kb_* collections."
    ),
    host=MCPS_HOST,
)


def _format_hit(p, col: str, score: float | None = None) -> dict:
    pl = p.payload or {}
    return {
        "id": str(p.id),
        "kb": col,
        "score": round(score, 4) if score is not None else None,
        "kind": pl.get("kind"),
        "source": pl.get("source"),
        "page_range": pl.get("page_range"),
        "snippet": _truncate(pl.get("text", "")),
    }


async def _vector_search(
    client: AsyncQdrantClient, cols: list[str], qv: list[float], top_k: int
) -> list[tuple[object, str, float]]:
    """Vector search across cols. Returns (point, collection, score) tuples."""
    hits: list[tuple[object, str, float]] = []
    for col in cols:
        try:
            resp = await client.query_points(
                collection_name=col, query=qv, limit=top_k,
                query_filter=_search_filter(), with_payload=True)
            for h in resp.points:
                hits.append((h, col, h.score))
        except Exception as e:  # noqa: BLE001
            if _is_missing_collection(e):
                continue
            raise
    return hits


async def _keyword_search(
    client: AsyncQdrantClient, cols: list[str], query: str, top_k: int
) -> list[tuple[object, str, float]]:
    """Hybrid fallback: scroll points, Python-side word match.

    Plain scroll (no order_by) so it works on collections without a
    payload index; recency is not required for word matching.
    """
    qwords = [w for w in re.findall(r"[a-z0-9']+", query.lower()) if len(w) > 2]
    if not qwords:
        return []
    hits: list[tuple[object, str, float]] = []
    for col in cols:
        try:
            points, _ = await client.scroll(col, limit=512, with_payload=True)
        except Exception as e:  # noqa: BLE001
            if _is_missing_collection(e):
                continue
            raise
        for p in points:
            pl = p.payload or {}
            if pl.get("kind") == "manifest" or pl.get("superseded_by"):
                continue
            text = (pl.get("text") or "").lower()
            if any(w in text for w in qwords):
                hits.append((p, col, 0.0))
    return hits


async def _recent_points(
    client: AsyncQdrantClient, col: str, cutoff: str
) -> list[tuple[object, str]]:
    """Non-manifest points with ingested_at >= cutoff, newest first.

    Prefers order_by (fast, index-backed — _ensure_collection creates the
    index for new KBs). Collections created before the index existed fall
    back to a full scroll + Python filter/sort (fine at KB scale).
    """
    try:
        points, _ = await client.scroll(
            col, limit=10000, with_payload=True,
            order_by=OrderBy(key="ingested_at", direction=Direction.DESC))
        out: list[tuple[object, str]] = []
        for p in points:
            pl = p.payload or {}
            if pl.get("kind") == "manifest":
                continue
            ts = pl.get("ingested_at") or pl.get("updated_at") or ""
            if ts < cutoff:
                break  # sorted desc — nothing older qualifies
            out.append((p, ts))
        return out
    except Exception as e:  # noqa: BLE001
        if _is_missing_collection(e):
            raise
        # No payload index on ingested_at (pre-migration collection):
        # full scroll, filter + sort in Python.
        logger.warning("order_by scroll failed on %s (%s); unsorted fallback",
                       col, e)
        points, _ = await client.scroll(col, limit=10000, with_payload=True)
        out = []
        for p in points:
            pl = p.payload or {}
            if pl.get("kind") == "manifest":
                continue
            ts = pl.get("ingested_at") or pl.get("updated_at") or ""
            if ts >= cutoff:
                out.append((p, ts))
        out.sort(key=lambda x: x[1], reverse=True)
        return out


@mcp.tool(
    name="kb_search",
    description=(
        "Vector search across the family KB (all kb_* collections, or one "
        "via 'kb'). Embeds the query (nomic 768-dim) and ranks chunks; "
        "falls back to keyword match. Filters manifest + superseded points. "
        "Returns snippets with kb, source, page_range."
    ),
)
async def kb_search(query: str, top_k: int = DEFAULT_TOP_K,
                    kb: Optional[str] = None) -> dict:
    """Vector search across kb_* collections (or one KB).

    Args:
        query: Natural-language search query.
        top_k: Max results (default 5, cap 20).
        kb: Friendly KB name (e.g. 'gaming' or 'kb_gaming'). Omit = all KBs.
    """
    top_k = min(max(1, top_k), MAX_TOP_K)
    client = _client()
    try:
        if kb:
            col = _kb_name(kb)
            existing = {c.name for c in (await client.get_collections()).collections}
            if col not in existing:
                return {"query": query, "results": [],
                        "note": (f"KB '{kb}' does not exist yet. Create it with "
                                 f"kb_add_fact or kb_ingest_file (a 'description' "
                                 f"is required for new KBs).")}
            cols = [col]
        else:
            cols = await _list_kb_collections(client)
        if not cols:
            return {"query": query, "results": [],
                    "note": "No KB collections exist yet — nothing to search."}
        results: list[dict] = []
        mode = "keyword"
        try:
            qv = (await _embed([query]))[0]
            vh = await _vector_search(client, cols, qv, top_k)
            if vh:
                mode = "vector"
                results = [_format_hit(p, c, s) for p, c, s in vh]
        except Exception as e:  # noqa: BLE001 — embedding outage → keyword
            logger.warning("vector search unavailable (%s); keyword fallback", e)
        if not results:
            results = [_format_hit(p, c, s)
                       for p, c, s in await _keyword_search(client, cols, query, top_k)]
        results.sort(key=lambda r: (r["score"] is not None, r["score"] or 0),
                     reverse=True)
        return {"query": query, "mode": mode, "results": results[:top_k]}
    finally:
        await client.close()


@mcp.tool(
    name="kb_get_document",
    description=(
        "Retrieve all chunks of one document (by source path) from a KB, "
        "ordered by chunk_index, with page ranges."
    ),
)
async def kb_get_document(source: str, kb: str) -> dict:
    """All chunks of a document, ordered.

    Args:
        source: The source path the document was ingested from.
        kb: Friendly KB name.
    """
    col = _kb_name(kb)
    client = _client()
    try:
        points, _ = await client.scroll(
            col, limit=10000, with_payload=True,
            scroll_filter=Filter(must=[FieldCondition(
                key="source", match=MatchValue(value=source))]))
        chunks = [p for p in points
                  if (p.payload or {}).get("kind") != "manifest"]
        chunks.sort(key=lambda p: (p.payload or {}).get("chunk_index", 0))
        if not chunks:
            return {"found": False, "kb": col, "source": source,
                    "message": f"No document '{source}' in '{col}'."}
        pl0 = chunks[0].payload or {}
        return {
            "found": True, "kb": col, "source": source,
            "sha256": pl0.get("sha256"),
            "chunks": [
                {"chunk_index": (p.payload or {}).get("chunk_index"),
                 "page_range": (p.payload or {}).get("page_range"),
                 "text": (p.payload or {}).get("text", "")}
                for p in chunks
            ],
        }
    finally:
        await client.close()


@mcp.tool(
    name="kb_list_documents",
    description=(
        "Per-document metadata (source, chunks, pages, sha256, ingested_at) "
        "for one KB, or all KBs when kb is omitted."
    ),
)
async def kb_list_documents(kb: Optional[str] = None) -> dict:
    """List documents per KB.

    Args:
        kb: Friendly KB name. Omit = all KBs.
    """
    client = _client()
    try:
        cols = [_kb_name(kb)] if kb else await _list_kb_collections(client)
        out: dict[str, list[dict]] = {}
        for col in cols:
            try:
                points, _ = await client.scroll(
                    col, limit=10000,
                    with_payload=["kind", "source", "chunk_index",
                                   "page_range", "sha256", "ingested_at"])
            except Exception as e:  # noqa: BLE001
                if _is_missing_collection(e):
                    continue
                raise
            docs: dict[str, dict] = {}
            for p in points:
                pl = p.payload or {}
                if pl.get("kind") == "manifest":
                    continue
                src = pl.get("source", "?")
                d = docs.setdefault(src, {
                    "source": src, "chunks": 0, "sha256": None,
                    "ingested_at": None, "page_range": [None, None]})
                d["chunks"] += 1
                d["sha256"] = pl.get("sha256") or d["sha256"]
                d["ingested_at"] = pl.get("ingested_at") or d["ingested_at"]
                pr = pl.get("page_range")
                if pr:
                    d["page_range"][0] = (
                        min(d["page_range"][0], pr[0])
                        if d["page_range"][0] is not None else pr[0])
                    d["page_range"][1] = (
                        max(d["page_range"][1], pr[1])
                        if d["page_range"][1] is not None else pr[1])
            out[col] = sorted(docs.values(),
                              key=lambda d: d["ingested_at"] or "", reverse=True)
        return {"documents": out,
                "total_docs": sum(len(v) for v in out.values())}
    finally:
        await client.close()


@mcp.tool(
    name="kb_overview",
    description=(
        "Map of the KB: every kb_* collection with its manifest description, "
        "document count, chunk count, and last-ingested time. Call this "
        "first to see what KBs exist."
    ),
)
async def kb_overview() -> dict:
    """What KBs exist: descriptions, doc/chunk counts, last ingested."""
    client = _client()
    try:
        cols = await _list_kb_collections(client)
        kbs: list[dict] = []
        for col in cols:
            info = await client.get_collection(col)
            points, _ = await client.scroll(
                col, limit=10000,
                with_payload=["kind", "source", "text", "ingested_at"])
            manifest = next(
                (p for p in points if (p.payload or {}).get("kind") == "manifest"),
                None)
            sources: set[str] = set()
            chunks = 0
            last = ""
            for p in points:
                pl = p.payload or {}
                if pl.get("kind") == "manifest":
                    continue
                sources.add(pl.get("source") or "?")
                chunks += 1
                ts = pl.get("ingested_at") or ""
                if ts > last:
                    last = ts
            kbs.append({
                "kb": col,
                "description": (manifest.payload or {}).get("text", "")
                if manifest else "",
                "documents": len(sources),
                "chunks": chunks,
                "points": info.points_count,
                "last_ingested": last or None,
            })
        return {"kbs": kbs, "count": len(kbs)}
    finally:
        await client.close()


@mcp.tool(
    name="kb_recent_changes",
    description=(
        "Recent KB activity (ingested/updated within the last N days) across "
        "all kb_* collections."
    ),
)
async def kb_recent_changes(days: int = 7) -> dict:
    """Recent changes across all KBs.

    Args:
        days: Look-back window in days (default 7).
    """
    days = min(max(1, days), 365)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    client = _client()
    try:
        cols = await _list_kb_collections(client)
        changes: list[dict] = []
        for col in cols:
            for p, ts in await _recent_points(client, col, cutoff):
                pl = p.payload or {}
                changes.append({
                    "id": str(p.id), "kb": col, "source": pl.get("source"),
                    "kind": pl.get("kind"), "timestamp": ts,
                })
        changes.sort(key=lambda c: c["timestamp"] or "", reverse=True)
        return {"days": days, "changes": changes[:MAX_TOP_K]}
    finally:
        await client.close()


@mcp.tool(
    name="kb_add_fact",
    description=(
        "Store a verbatim fact in a KB (kind=fact). Also the vehicle for "
        "vision output: read an image/video, then store the description or "
        "table here. Creates the KB if missing — 'description' required on "
        "new-KB creation. Idempotent for identical text."
    ),
)
async def kb_add_fact(text: str, kb: str,
                      description: Optional[str] = None) -> dict:
    """Add a verbatim fact to a KB.

    Args:
        text: The fact (stored verbatim).
        kb: Friendly KB name (creates it if missing).
        description: REQUIRED when creating a new KB.
    """
    if not text or not text.strip():
        raise ValueError("text is required.")
    col = _kb_name(kb)
    client = _client()
    try:
        created = await _ensure_collection(client, col, description or "")
        source = f"fact:{hashlib.sha256(text.encode()).hexdigest()[:16]}"
        vecs = await _embed([text.strip()])
        now = _now()
        pid = _point_id(source, 0)
        await client.upsert(col, points=[{
            "id": pid, "vector": vecs[0],
            "payload": {
                "text": text.strip(), "kind": "fact", "source": source,
                "chunk_index": 0, "page_range": None, "sha256": None,
                "ingested_at": now, "updated_at": now,
            },
        }])
        return {"kb": col, "created_kb": created, "fact_id": str(pid),
                "source": source}
    finally:
        await client.close()


@mcp.tool(
    name="kb_ingest_file",
    description=(
        "Ingest a file into a KB: PDF (page-by-page pymupdf + vision "
        "fallback for image/table pages), DOCX/PPTX/XLSX/HTML/CSV/EPUB/txt "
        "via markitdown, images via vision description. ~1200-token chunks "
        "with page ranges; batched embeddings; deterministic IDs (re-ingest "
        "is an idempotent upsert). Long-running for big files. Creates the "
        "KB if missing — 'description' required on new-KB creation."
    ),
)
async def kb_ingest_file(path: str, kb: str,
                         description: Optional[str] = None) -> dict:
    """Ingest a file into a KB.

    Args:
        path: Absolute container path under an allowed root (media/,
            workspace/, ai-kb/raw/). Host: /home/chuck/data/ai-kb/raw/...
        kb: Friendly KB name (creates it if missing).
        description: REQUIRED when creating a new KB.
    """
    p = _validate_source_path(path)
    if not p.is_file():
        raise ValueError(f"File not found: {path}")
    col = _kb_name(kb)
    sha = _file_sha256(p)
    client = _client()
    try:
        created = await _ensure_collection(client, col, description or "")
        markdown, page_meta, warnings = await asyncio.to_thread(_convert_file, p)
        if not markdown.strip():
            raise RuntimeError(f"conversion produced no content for {p.name}")
        chunks = _chunk_markdown(markdown)
        # Re-ingest idempotency: warn if the source sha is unchanged.
        existing, _ = await client.scroll(
            col, limit=10000, with_payload=True,
            scroll_filter=Filter(must=[FieldCondition(
                key="source", match=MatchValue(value=str(p)))]))
        sha_unchanged = any(
            (e.payload or {}).get("sha256") == sha for e in existing)
        if sha_unchanged:
            warnings.append(
                "sha256 unchanged since last ingest — this is a no-op "
                "idempotent upsert (same content).")
        vecs = await _embed([c["text"] for c in chunks])
        now = _now()
        points = []
        for c, v in zip(chunks, vecs):
            points.append({
                "id": _point_id(str(p), c["chunk_index"]), "vector": v,
                "payload": {
                    "text": c["text"], "kind": "image" if p.suffix.lower()
                    in _IMAGE_EXTS else "doc", "source": str(p),
                    "chunk_index": c["chunk_index"],
                    "page_range": c["page_range"], "sha256": sha,
                    "ingested_at": now, "updated_at": now,
                },
            })
        for i in range(0, len(points), 256):
            await client.upsert(col, points=points[i:i + 256])
        return {
            "kb": col, "created_kb": created, "doc_id": str(p),
            "source": str(p), "pages": len(page_meta) or None,
            "chunks": len(chunks), "sha256": sha,
            "sha_unchanged": sha_unchanged, "warnings": warnings,
        }
    finally:
        await client.close()


@mcp.tool(
    name="kb_delete_document",
    description=(
        "Remove all chunks for a source path from one KB (or all KBs when "
        "kb is omitted). Re-ingest = kb_delete_document + kb_ingest_file."
    ),
)
async def kb_delete_document(source: str, kb: Optional[str] = None) -> dict:
    """Delete a document's chunks.

    Args:
        source: The source path the document was ingested from.
        kb: Friendly KB name. Omit = search all KBs.
    """
    client = _client()
    try:
        cols = [_kb_name(kb)] if kb else await _list_kb_collections(client)
        deleted: dict[str, int] = {}
        for col in cols:
            try:
                points, _ = await client.scroll(
                    col, limit=10000, with_payload=True,
                    scroll_filter=Filter(must=[FieldCondition(
                        key="source", match=MatchValue(value=source))]))
            except Exception as e:  # noqa: BLE001
                if _is_missing_collection(e):
                    continue
                raise
            ids = [p.id for p in points
                   if (p.payload or {}).get("kind") != "manifest"]
            if ids:
                await client.delete(col, points_selector=ids)
                deleted[col] = len(ids)
        return {"source": source, "deleted": deleted,
                "total": sum(deleted.values())}
    finally:
        await client.close()


@mcp.tool(
    name="kb_forget",
    description=(
        "Two-step semantic delete. Step 1 (default): returns semantic "
        "matches (ids + snippets), deletes NOTHING. Step 2: confirm=true + "
        "ids (from step 1) deletes those points. Manifests are never "
        "deleted. Permanent — no undo."
    ),
)
async def kb_forget(query: str, kb: Optional[str] = None,
                    confirm: bool = False,
                    ids: Optional[list[str]] = None) -> dict:
    """Forget a fact (two-step semantic delete).

    Args:
        query: What to forget (semantic match).
        kb: Friendly KB name. Omit = all KBs.
        confirm: True + ids to actually delete (step 2).
        ids: Point IDs from a step-1 call.
    """
    client = _client()
    try:
        cols = ([_kb_name(kb)] if kb
                else await _list_kb_collections(client))
        if confirm:
            if not ids:
                raise ValueError(
                    "confirm=true requires 'ids' (from a previous kb_forget "
                    "call). Nothing was deleted.")
            deleted: dict[str, int] = {}
            not_found: list[str] = []
            for raw in ids:
                pid = _as_id(raw)
                found_col = None
                for col in cols:
                    try:
                        got = await client.retrieve(col, ids=[pid],
                                                    with_payload=True)
                    except Exception as e:  # noqa: BLE001
                        if _is_missing_collection(e):
                            continue
                        raise
                    if got:
                        found_col = col
                        break
                if found_col is None:
                    not_found.append(str(raw))
                    continue
                pl = got[0].payload or {}
                if pl.get("kind") == "manifest":
                    not_found.append(f"{raw} (manifest — never deleted)")
                    continue
                await client.delete(found_col, points_selector=[pid])
                deleted[found_col] = deleted.get(found_col, 0) + 1
            return {
                "deleted": deleted, "total": sum(deleted.values()),
                "not_found": not_found,
                "note": "Deleted (permanent — no undo).",
            }
        # Step 1: semantic matches, nothing deleted.
        if not cols:
            return {"matches": [],
                    "note": "No KB collections exist yet — nothing to forget."}
        results: list[dict] = []
        try:
            qv = (await _embed([query]))[0]
            results = [_format_hit(p, c, s)
                       for p, c, s in await _vector_search(client, cols, qv, 10)]
        except Exception as e:  # noqa: BLE001
            logger.warning("forget: vector search unavailable (%s); keyword", e)
        if not results:
            results = [_format_hit(p, c, s)
                       for p, c, s in
                       await _keyword_search(client, cols, query, 10)]
        results.sort(key=lambda r: (r["score"] is not None, r["score"] or 0),
                     reverse=True)
        return {
            "matches": results[:10],
            "note": ("Nothing deleted. Review the matches, then call "
                     "kb_forget again with confirm=true and ids=[...]."),
        }
    finally:
        await client.close()


@mcp.tool(
    name="kb_correct",
    description=(
        "Supersede a fact: finds the best match for old_query (score gate "
        f"{CORRECT_SCORE_GATE}), marks it superseded_by, and stores "
        "new_text as a new fact (linked via 'corrects'). kb_search filters "
        "superseded points."
    ),
)
async def kb_correct(old_query: str, new_text: str,
                     kb: Optional[str] = None) -> dict:
    """Correct a fact ("it should be this instead").

    Args:
        old_query: Description of the fact to correct.
        new_text: The corrected fact (stored verbatim).
        kb: Friendly KB name. Omit = all KBs.
    """
    if not new_text or not new_text.strip():
        raise ValueError("new_text is required.")
    client = _client()
    try:
        cols = [_kb_name(kb)] if kb else await _list_kb_collections(client)
        if not cols:
            raise ValueError("No KB collections exist yet.")
        hits = await _vector_search(client, cols,
                                    (await _embed([old_query]))[0], 3)
        if not hits:
            return {"corrected": False,
                    "reason": "No match found for old_query."}
        hits.sort(key=lambda h: h[2], reverse=True)
        best, col, score = hits[0]
        if score < CORRECT_SCORE_GATE:
            return {
                "corrected": False,
                "reason": (f"Best match score {round(score, 4)} is below the "
                           f"gate {CORRECT_SCORE_GATE} — not confident "
                           f"enough to supersede. Show the match to the user "
                           f"or refine old_query."),
                "best_match": _format_hit(best, col, score),
            }
        old_pl = dict(best.payload or {})
        old_pl.pop("superseded_by", None)
        # query_points does not return vectors — fetch the old point's vector
        # so the supersede upsert can keep it.
        fetched = await client.retrieve(col, ids=[best.id],
                                        with_payload=False,
                                        with_vectors=True)
        old_vec = fetched[0].vector if fetched else None
        if old_vec is None:
            raise ValueError(
                f"Could not read the vector of match {best.id} — "
                "cannot supersede without it.")
        source = f"fact:{hashlib.sha256(new_text.encode()).hexdigest()[:16]}"
        vecs = await _embed([new_text.strip()])
        now = _now()
        new_id = _point_id(source, 0)
        await client.upsert(col, points=[{
            "id": new_id, "vector": vecs[0],
            "payload": {
                "text": new_text.strip(),
                "kind": old_pl.get("kind", "fact"), "source": source,
                "chunk_index": 0, "page_range": old_pl.get("page_range"),
                "sha256": None, "ingested_at": now, "updated_at": now,
                "corrects": str(best.id),
            },
        }])
        old_pl["superseded_by"] = str(new_id)
        old_pl["updated_at"] = now
        await client.upsert(col, points=[{
            "id": best.id, "vector": old_vec, "payload": old_pl,
        }])
        return {"corrected": True, "kb": col, "old_id": str(best.id),
                "new_id": str(new_id), "score": round(score, 4)}
    finally:
        await client.close()


@mcp.tool(
    name="kb_backup",
    description=(
        "Snapshot all kb_* Qdrant collections to the backup dir "
        "(same layout as memory backups). include_sources=true also tars "
        "the ingested source files that still exist on disk."
    ),
)
async def kb_backup(include_sources: bool = False) -> dict:
    """Snapshot all KB collections.

    Args:
        include_sources: Also tar the source files (paths that exist).
    """
    client = _client()
    try:
        cols = await _list_kb_collections(client)
        if not cols:
            return {"backups": [], "note": "No KB collections to back up."}
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
        out_dir = Path(KB_BACKUP_DIR)
        out_dir.mkdir(parents=True, exist_ok=True)
        backups: list[dict] = []
        async with httpx.AsyncClient(timeout=300) as h:
            auth = {"Authorization": f"Bearer {KB_API_KEY}"}
            for col in cols:
                r = await h.post(
                    f"{QDRANT_URL}/collections/{col}/snapshots", headers=auth)
                r.raise_for_status()
                snap_name = r.json()["result"]["name"]
                r2 = await h.get(
                    f"{QDRANT_URL}/collections/{col}/snapshots/{snap_name}",
                    headers=auth)
                r2.raise_for_status()
                dest = out_dir / f"{col}-{stamp}.snapshot"
                dest.write_bytes(r2.content)
                backups.append({
                    "collection": col,
                    "file": str(dest),
                    "bytes": len(r2.content),
                    "qdrant_snapshot": snap_name,
                })
        sources_tar = None
        if include_sources:
            tar_path = out_dir / f"kb-sources-{stamp}.tar.gz"
            seen: set[str] = set()
            with tarfile.open(tar_path, "w:gz") as tf:
                for col in cols:
                    docs, _ = await client.scroll(
                        col, limit=10000,
                        with_payload=["source", "kind"])
                    for p in docs:
                        pl = p.payload or {}
                        if pl.get("kind") == "manifest":
                            continue
                        src = pl.get("source") or ""
                        if src.startswith("fact:"):
                            continue
                        sp = Path(src)
                        if sp.is_file() and src not in seen:
                            seen.add(src)
                            tf.add(sp, arcname=f"sources/{src.lstrip('/')}")
            if seen:
                sources_tar = {"file": str(tar_path),
                               "files": sorted(seen)}
            else:
                tar_path.unlink(missing_ok=True)
        return {
            "backups": backups, "sources_tar": sources_tar,
            "note": (f"{len(backups)} collection snapshot(s) written to "
                     f"{KB_BACKUP_DIR} (host: /home/chuck/data/backups/kb)."),
        }
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the MCP knowledge server over streamable-http (0.0.0.0:8000)."""
    logging.basicConfig(level=logging.INFO)
    logger.info("Starting mcp_knowledge v2 (family KB) — Qdrant %s, "
                "LiteLLM %s, embed=%s (%d-dim), vision=%s",
                QDRANT_URL, LITELLM_API_BASE, EMBED_MODEL, EMBED_DIM,
                VISION_MODEL)
    logger.info("Allowed source roots: %s | backup dir: %s",
                ", ".join(KB_ALLOWED_ROOTS), KB_BACKUP_DIR)
    if not KB_API_KEY:
        logger.warning("KB_API_KEY is EMPTY — all tools will fail "
                       "(Qdrant requires auth).")
    mcp.run(transport="streamable-http")  # 0.0.0.0:8000


if __name__ == "__main__":
    main()
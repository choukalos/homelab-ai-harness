import re
from pathlib import Path
from uuid import uuid4
import httpx

from infra.core.config import MEDIA_OUTPUT_DIR
from infra.core.config import INTERNAL_BASE_URL
from infra.core.llm import chat_completion
from media.filename_util import generate_media_filename
from apps.pm_demo.prompts import SYSTEM_PROMPT


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```html"):
        text = text.removeprefix("```html").strip()
    elif text.startswith("```"):
        text = text.removeprefix("```").strip()

    if text.endswith("```"):
        text = text.removesuffix("```").strip()

    return text



async def generate_demo_html(
    title: str,
    prompt: str,
    model: str | None = None,
    save_name: str | None = None,
) -> dict:
    user_prompt = f"""
Demo title: {title}

Product/demo request:
{prompt}

Return one complete HTML file.
"""

    full_prompt = f"""
{SYSTEM_PROMPT}

{user_prompt}
"""

    async with httpx.AsyncClient(timeout=180.0) as client:
        html = await chat_completion(
            client=client,
            prompt=full_prompt,
            temperature=0.4,
            timeout=180.0,
        )

    html = _strip_code_fences(html)

    # Prompt-based filename with collision detection (same approach as images)
    output_dir = Path(MEDIA_OUTPUT_DIR) / "demos"
    output_dir.mkdir(parents=True, exist_ok=True)

    safe_name = save_name or title
    filename = generate_media_filename(
        prompt=safe_name,
        content_type="text/html",
        output_dir=output_dir,
    )
    # Force .html extension
    if not filename.endswith(".html"):
        filename = filename.rsplit(".", 1)[0] + ".html"

    path = output_dir / filename
    path.write_text(html, encoding="utf-8")

    return {
        "title": title,
        "filename": filename,
        "url": f"{INTERNAL_BASE_URL.rstrip('/')}/media/files/demos/{filename}",
        "html": html,
    }



import re
from pathlib import Path
from uuid import uuid4
import httpx

from core.config import MEDIA_OUTPUT_DIR
from core.config import MEDIA_PUBLIC_BASE_URL
from core.llm import chat_completion
from pm_demo.prompts import SYSTEM_PROMPT


def _safe_filename(name: str) -> str:
    name = name.lower().strip()
    name = re.sub(r"[^a-z0-9]+", "-", name)
    name = name.strip("-")
    return name or f"demo-{uuid4().hex[:8]}"


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

    filename_base = _safe_filename(save_name or title)
    filename = f"{filename_base}-{uuid4().hex[:8]}.html"

    output_dir = Path(MEDIA_OUTPUT_DIR) / "pm-demos"
    output_dir.mkdir(parents=True, exist_ok=True)

    path = output_dir / filename
    path.write_text(html, encoding="utf-8")

    return {
        "title": title,
        "filename": filename,
        "url": f"{MEDIA_PUBLIC_BASE_URL}/media/files/pm-demos/{filename}",
        "html": html,
    }



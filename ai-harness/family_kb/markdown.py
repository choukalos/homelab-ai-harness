import re
from pathlib import Path
from datetime import datetime

import pytesseract
from PIL import Image
from slugify import slugify
from docling.document_converter import DocumentConverter

converter = DocumentConverter()


def clean_markdown(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"!\[.*?\]\(.*?\)", " ", text)
    text = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", text)
    text = re.sub(r"#+\s*", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def safe_read_text(path: Path) -> str:
    return path.read_text(errors="ignore")


def extract_pdf_docling(path: Path, output_dir: Path, slug: str) -> str:
    result = converter.convert(str(path))
    doc = result.document

    json_path = output_dir / f"{slug}.docling.json"
    json_path.write_text(str(doc.export_to_dict()), encoding="utf-8")

    return doc.export_to_markdown()


def extract_image(path: Path) -> str:
    image = Image.open(path)
    return pytesseract.image_to_string(image).strip()


def source_to_markdown(path: Path, target_dir: Path, slug: str) -> str:
    ext = path.suffix.lower()

    if ext in {".md", ".markdown", ".txt"}:
        return safe_read_text(path)

    if ext == ".pdf":
        return extract_pdf_docling(path, target_dir, slug)

    if ext in {".png", ".jpg", ".jpeg", ".webp", ".tiff"}:
        text = extract_image(path)
        return f"# {path.stem}\n\n## OCR Text\n\n{text}"

    raise ValueError(f"Unsupported file type: {ext}")


def build_markdown_document(path: Path, rel_parent: Path, body: str) -> str:
    title = path.stem.replace("_", " ").replace("-", " ").title()

    if not body.strip():
        body = "_No readable text was extracted._"

    return (
        f"# {title}\n\n"
        f"> Source file: `{path.name}`  \n"
        f"> Category: `{rel_parent}`  \n"
        f"> Ingested: {datetime.now().isoformat(timespec='seconds')}\n\n"
        f"{body}\n"
    )


def slug_for(path: Path) -> str:
    return slugify(path.stem) or "document"



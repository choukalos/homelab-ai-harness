import shutil
import time
from pathlib import Path

from knowledge.family_kb.config import KB_FAILED, KB_PROCESSED, KB_RAW, KB_ROOT, SUPPORTED_EXTENSIONS
from knowledge.family_kb.markdown import build_markdown_document, slug_for, source_to_markdown
from knowledge.family_kb.nav_gen import regenerate_all
from knowledge.family_kb.schemas import FileIngestResponse


def ensure_kb_dirs() -> None:
    for folder in [KB_RAW, KB_ROOT, KB_PROCESSED, KB_FAILED]:
        folder.mkdir(parents=True, exist_ok=True)


def ingest_source_file(path: Path) -> FileIngestResponse:
    ensure_kb_dirs()

    if not path.is_file():
        return FileIngestResponse(
            source=str(path),
            status="skipped",
            message="Not a file",
        )

    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return FileIngestResponse(
            source=str(path),
            status="skipped",
            message=f"Unsupported file type: {path.suffix}",
        )

    time.sleep(1)

    try:
        rel_parent = path.parent.relative_to(KB_RAW)
        target_dir = KB_ROOT / rel_parent
        target_dir.mkdir(parents=True, exist_ok=True)

        slug = slug_for(path)
        output = target_dir / f"{slug}.md"

        body = source_to_markdown(path, target_dir, slug)
        document = build_markdown_document(path, rel_parent, body)

        output.write_text(document, encoding="utf-8")

        processed_dir = KB_PROCESSED / rel_parent
        processed_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(processed_dir / path.name))

        return FileIngestResponse(
            source=str(path),
            output=str(output),
            status="ingested",
        )

    except Exception as exc:
        try:
            failed_dir = KB_FAILED / path.parent.relative_to(KB_RAW)
        except ValueError:
            failed_dir = KB_FAILED

        failed_dir.mkdir(parents=True, exist_ok=True)

        if path.exists():
            shutil.move(str(path), str(failed_dir / path.name))

        return FileIngestResponse(
            source=str(path),
            status="failed",
            message=str(exc),
        )


def ingest_existing_raw_files() -> list[FileIngestResponse]:
    ensure_kb_dirs()

    results: list[FileIngestResponse] = []

    for path in KB_RAW.rglob("*"):
        if path.is_file():
            results.append(ingest_source_file(path))

    # Regenerate indexes and nav after batch ingest
    regenerate_all()

    return results



# family_kb_ingest Skill

Ingest files into the family knowledge base. Processes text, PDFs, etc. and stores embeddings in Qdrant.

## Overview

This skill is a thin wrapper around the AI Harness knowledge ingestion endpoint. It validates the input file, sends file metadata to the Harness, and returns the ingestion result. The Harness handles all heavy lifting: text extraction, chunking, embedding generation, and storage in Qdrant.

## Inputs

| Parameter  | Type   | Required | Default      | Description                      |
|------------|--------|----------|--------------|----------------------------------|
| file_path  | string | yes      | —            | Path to the file to ingest.      |
| collection | string | no       | `family_kb`  | Target Qdrant collection name.   |

## Output

Returns the AI Harness ingestion response, typically including:

- `collection` — Target Qdrant collection name
- `file_name` — Name of the ingested file
- `chunks` — Number of chunks created
- `status` — Ingestion status (e.g., `success`, `queued`)
- `file_path` — Original file path
- `error` — Error message (if applicable)
- `status` — Overall status (e.g., `validation_error`, `error`, `timeout`)

## Usage

### Via Skill Runner

```bash
curl -X POST http://localhost:8091/skills/family_kb_ingest/run \
  -H "Content-Type: application/json" \
  -d '{"file_path": "/home/chuck/data/documents/family_notes.pdf", "collection": "family_kb"}'
```

### Standalone (CLI)

```bash
cd /home/chuck/homelab/skills/family_kb_ingest
python skill.py --file-path /path/to/document.pdf
python skill.py --file-path /path/to/document.pdf --collection my_collection
python skill.py --file-path /path/to/document.pdf --dry-run
python skill.py --file-path /path/to/document.pdf --harness-url http://localhost:8090
```

## Configuration

| Environment Variable              | Default                      | Description                         |
|-----------------------------------|------------------------------|-------------------------------------|
| FAMILY_KB_INGEST_HARNESS_URL      | `http://skill-runner:8091`     | Skill Runner base URL             |
| FAMILY_KB_INGEST_MAX_RUNTIME      | `300`                        | Max runtime in seconds              |

## File Validation

Before calling the Harness, the skill validates:

1. The file exists at the given path.
2. The path points to a regular file (not a directory).
3. The file is readable.

If validation fails, the skill returns a `validation_error` without calling the Harness.

## Supported Formats

The AI Harness determines supported formats. Common types include:

- `.txt`, `.md`, `.csv` — Plain text
- `.pdf` — PDF documents
- `.docx` — Word documents

Large files (>100 MB) are accepted but may trigger a warning in logs.

## Future Enhancements

- **OCR for images**: Add support for ingesting image files (JPG, PNG) using a vision model or pytesseract.
- **Table extraction**: Better handling of tabular data in PDFs using pdfplumber or tabula-py.
- **Batch ingestion**: Support ingesting multiple files in a single call.

## Constraints

- **Max runtime:** 300 seconds (5 minutes)
- **No MCP tools:** Direct HTTP call to AI Harness only
- **Stateless:** No rollback or cleanup needed

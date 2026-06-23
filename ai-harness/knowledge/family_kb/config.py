import os
from pathlib import Path

KB_ROOT = Path(os.getenv("KB_ROOT", "/data/ai-kb/repo"))
KB_RAW = Path(os.getenv("KB_RAW", "/data/ai-kb/raw"))
KB_PROCESSED = Path(os.getenv("KB_PROCESSED", "/data/ai-kb/processed"))
KB_FAILED = Path(os.getenv("KB_FAILED", "/data/ai-kb/failed"))

QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
COLLECTION = os.getenv("KB_COLLECTION", "family_kb")

HARNESS_API_KEY = os.getenv("HARNESS_API_KEY", "")

EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-small-en-v1.5")

CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1200"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "200"))

SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".txt",
    ".md",
    ".markdown",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".tiff",
}


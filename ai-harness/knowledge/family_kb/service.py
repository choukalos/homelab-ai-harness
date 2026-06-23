from pathlib import Path

from qdrant_client.models import PointStruct

from knowledge.family_kb.chunking import chunk_text
from knowledge.family_kb.config import KB_ROOT
from knowledge.family_kb.embeddings import embed_query, embed_texts
from knowledge.family_kb.ids import point_id
from knowledge.family_kb.markdown import clean_markdown
from knowledge.family_kb.nav_gen import regenerate_all
from knowledge.family_kb.qdrant_store import search_points, upsert_points
from knowledge.family_kb.schemas import IngestResponse, SearchRequest


def ingest_markdown_repo() -> IngestResponse:
    md_files = list(KB_ROOT.rglob("*.md"))

    points: list[PointStruct] = []
    indexed_files = 0
    indexed_chunks = 0

    for path in md_files:
        rel_path = path.relative_to(KB_ROOT).as_posix()
        category = rel_path.split("/")[0] if "/" in rel_path else "root"

        raw = path.read_text(errors="ignore")
        text = clean_markdown(raw)
        chunks = chunk_text(text)

        if not chunks:
            continue

        indexed_files += 1
        vectors = embed_texts(chunks)

        for i, vector in enumerate(vectors):
            points.append(
                PointStruct(
                    id=point_id(rel_path, i),
                    vector=vector,
                    payload={
                        "source": rel_path,
                        "category": category,
                        "chunk_index": i,
                        "text": chunks[i],
                    },
                )
            )
            indexed_chunks += 1

    upsert_points(points)

    # Regenerate index files and mkdocs nav after re-indexing
    regenerate_all()

    return IngestResponse(
        indexed_files=indexed_files,
        indexed_chunks=indexed_chunks,
    )


def search_kb(req: SearchRequest) -> dict:
    query_vector = embed_query(req.query)

    hits = search_points(
        query_vector=query_vector,
        limit=req.limit,
        category=req.category,
    )

    results = [
        {
            "score": hit.score,
            "source": hit.payload.get("source"),
            "category": hit.payload.get("category"),
            "text": hit.payload.get("text"),
        }
        for hit in hits
    ]

    return {
        "query": req.query,
        "results": results,
        "instruction": (
            "Answer only from these results. If the answer is not present, "
            "say you could not find it in the family knowledge base."
        ),
    }



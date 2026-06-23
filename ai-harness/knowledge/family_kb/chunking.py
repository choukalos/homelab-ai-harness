from knowledge.family_kb.config import CHUNK_OVERLAP, CHUNK_SIZE


def chunk_text(text: str) -> list[str]:
    chunks = []
    start = 0

    while start < len(text):
        end = start + CHUNK_SIZE
        chunk = text[start:end].strip()

        if chunk:
            chunks.append(chunk)

        next_start = end - CHUNK_OVERLAP

        if next_start <= start:
            break

        start = next_start

    return chunks



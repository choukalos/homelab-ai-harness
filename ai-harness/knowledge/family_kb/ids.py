import hashlib


def point_id(source: str, chunk_index: int) -> int:
    digest = hashlib.sha256(f"{source}:{chunk_index}".encode()).hexdigest()
    return int(digest[:16], 16)



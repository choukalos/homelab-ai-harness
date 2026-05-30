from typing import Optional

from pydantic import BaseModel


class SearchRequest(BaseModel):
    query: str
    category: Optional[str] = None
    limit: int = 5


class SearchResult(BaseModel):
    score: float
    source: str | None = None
    category: str | None = None
    text: str | None = None


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
    instruction: str


class IngestResponse(BaseModel):
    indexed_files: int
    indexed_chunks: int


class FileIngestResponse(BaseModel):
    source: str
    output: str | None = None
    status: str
    message: str | None = None



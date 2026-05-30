from typing import Literal

from pydantic import BaseModel, Field


class WebSearchRequest(BaseModel):
    query: str
    max_results: int = Field(default=5, ge=1, le=10)
    crawl_results: int = Field(default=3, ge=0, le=5)
    category: str = "general"
    language: str = "en"
    time_range: Literal["day", "month", "year"] | None = None
    summarize: bool = True
    mode: Literal["quick", "sources", "answer"] = "answer"


class SearchResult(BaseModel):
    title: str | None = None
    url: str
    content: str | None = None
    engine: str | None = None
    score: float | None = None
    extracted_markdown: str | None = None


class ResearchBriefRequest(BaseModel):
    topic: str
    max_queries: int = Field(default=4, ge=1, le=8)
    results_per_query: int = Field(default=5, ge=1, le=10)



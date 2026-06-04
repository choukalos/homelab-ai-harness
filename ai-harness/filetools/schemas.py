"""Pydantic schemas for filetools operations."""

from pydantic import BaseModel, Field
from typing import Optional, Literal


class ListDirRequest(BaseModel):
    """Request to list directory contents."""
    path: str = Field(default="", description="Relative path within workspace")
    recursive: bool = Field(default=False, description="List recursively")
    max_depth: int = Field(default=3, ge=1, le=10, description="Max depth for recursive listing")
    include_hidden: bool = Field(default=False, description="Include hidden files/dirs")


class FileEntry(BaseModel):
    """A single file/directory entry."""
    name: str
    path: str  # relative to workspace
    is_dir: bool
    size: Optional[int] = None  # bytes, None for directories


class ListDirResponse(BaseModel):
    """Response for directory listing."""
    path: str  # the resolved relative path
    entries: list[FileEntry] = Field(default_factory=list)


class SearchRequest(BaseModel):
    """Request to search for files."""
    path: str = Field(default="", description="Relative path to search within (default: workspace root)")
    pattern: str = Field(default="", description="Filename pattern (supports glob * and ?)")
    content: str = Field(default="", description="Text content to search for (grep-like)")
    case_sensitive: bool = Field(default=False, description="Case-sensitive search")
    max_results: int = Field(default=50, ge=1, le=200, description="Max results to return")
    extensions: Optional[list[str]] = Field(default=None, description="Filter by extensions, e.g. ['.py', '.js']")


class SearchResult(BaseModel):
    """A single search result."""
    path: str  # relative to workspace
    match_type: Literal["name", "content"]
    line_number: Optional[int] = None  # for content matches
    preview: Optional[str] = None  # matched line content


class SearchResponse(BaseModel):
    """Response for file search."""
    results: list[SearchResult] = Field(default_factory=list)
    total: int = 0


class ReadFileRequest(BaseModel):
    """Request to read a file."""
    path: str = Field(description="Relative path within workspace")
    start_line: Optional[int] = Field(default=None, ge=1, description="Start line (1-indexed)")
    max_lines: Optional[int] = Field(default=None, ge=1, le=5000, description="Max lines to read")


class ReadFileResponse(BaseModel):
    """Response with file contents."""
    path: str
    content: str
    lines: int


class WriteFileRequest(BaseModel):
    """Request to write/create a file."""
    path: str = Field(description="Relative path within workspace")
    content: str = Field(description="File contents")
    create_dirs: bool = Field(default=True, description="Create parent directories if needed")


class WriteFileResponse(BaseModel):
    """Response after writing a file."""
    path: str
    bytes_written: int


class UpdateFileRequest(BaseModel):
    """Request to update part of a file using string replacement."""
    path: str = Field(description="Relative path within workspace")
    old_text: str = Field(description="Exact text to find and replace")
    new_text: str = Field(description="Replacement text")


class UpdateFileResponse(BaseModel):
    """Response after updating a file."""
    path: str
    replacements: int  # how many replacements made


class DeleteFileRequest(BaseModel):
    """Request to delete a file or directory."""
    path: str = Field(description="Relative path within workspace")
    recursive: bool = Field(default=False, description="Recursively delete directory contents")


class DeleteFileResponse(BaseModel):
    """Response after deleting."""
    path: str
    deleted: bool


class DiffRequest(BaseModel):
    """Request to diff two files."""
    path_a: str = Field(description="First file relative path")
    path_b: str = Field(description="Second file relative path")
    unified: bool = Field(default=True, description="Unified diff format (default)")


class DiffResponse(BaseModel):
    """Response with diff output."""
    diff: str
    path_a: str
    path_b: str


class PatchRequest(BaseModel):
    """Request to apply a patch to a file."""
    path: str = Field(description="Relative path to the file to patch")
    patch: str = Field(description="Unified diff patch string")
    backup: bool = Field(default=True, description="Create .bak backup before applying")


class PatchResponse(BaseModel):
    """Response after applying a patch."""
    path: str
    applied: bool
    message: str

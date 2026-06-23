from fastapi import APIRouter, Depends

from infra.core.security import require_auth
from filetools.schemas import (
    DeleteFileRequest,
    DeleteFileResponse,
    DiffRequest,
    DiffResponse,
    ListDirRequest,
    ListDirResponse,
    PatchRequest,
    PatchResponse,
    ReadFileRequest,
    ReadFileResponse,
    SearchRequest,
    SearchResponse,
    UpdateFileRequest,
    UpdateFileResponse,
    WriteFileRequest,
    WriteFileResponse,
)
from filetools.service import delete_file, diff_files, list_directory, patch_file, read_file, search_files, update_file, write_file

router = APIRouter(tags=["filetools"])


@router.post("/ls", response_model=ListDirResponse)
def ls(req: ListDirRequest, _: None = Depends(require_auth)):
    """List directory contents within the workspace."""
    return list_directory(req)


@router.post("/search", response_model=SearchResponse)
def search(req: SearchRequest, _: None = Depends(require_auth)):
    """Search for files by name pattern or content within the workspace."""
    return search_files(req)


@router.post("/read", response_model=ReadFileResponse)
def read(req: ReadFileRequest, _: None = Depends(require_auth)):
    """Read a text file within the workspace."""
    return read_file(req)


@router.post("/write", response_model=WriteFileResponse)
def write(req: WriteFileRequest, _: None = Depends(require_auth)):
    """Create or overwrite a text file within the workspace."""
    return write_file(req)


@router.post("/update", response_model=UpdateFileResponse)
def update(req: UpdateFileRequest, _: None = Depends(require_auth)):
    """Update a file by replacing exact text snippets."""
    return update_file(req)


@router.post("/delete", response_model=DeleteFileResponse)
def delete(req: DeleteFileRequest, _: None = Depends(require_auth)):
    """Delete a file or directory within the workspace."""
    return delete_file(req)


@router.post("/diff", response_model=DiffResponse)
def diff(req: DiffRequest, _: None = Depends(require_auth)):
    """Generate a unified diff between two files within the workspace."""
    return diff_files(req)


@router.post("/patch", response_model=PatchResponse)
def patch(req: PatchRequest, _: None = Depends(require_auth)):
    """Apply a unified diff patch to a file within the workspace."""
    return patch_file(req)

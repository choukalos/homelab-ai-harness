# Local file access/manipulation tools constrained to a workspace directory tree.
#
# Endpoints (under /files):
#   POST /ls       - List directory contents
#   POST /search   - Search files by name or content
#   POST /read     - Read a text file
#   POST /write    - Create or overwrite a file
#   POST /update   - Replace exact text within a file
#   POST /delete   - Delete a file or directory
#   POST /diff     - Unified diff between two files
#   POST /patch    - Apply a unified diff patch
#
# All paths are relative to the WORKSPACE environment variable
# (default: /home/chuck/workspace). Path traversal outside WORKSPACE is blocked.

"""Server-side transcript splitting for mcp_sessions (Phase 1).

The skill-runner ingest route caps a single transcript at 2 MiB
(``sessions.SESSION_TRANSCRIPT_MAX_BYTES``). Long pi sessions are split on
line boundaries into <=2 MiB parts and ingested as ``{session_id}.partN``
(the existing convention from the session-sync skill — the runner path is
unchanged; only the split moves from the client to this server).

Pure stdlib so it is unit-testable without the mcp/httpx dependencies.
"""
from __future__ import annotations

import re
from typing import Dict, List

# Must match skill-runner sessions.SESSION_TRANSCRIPT_MAX_BYTES (2 MiB).
PART_MAX_BYTES = 2 * 1024 * 1024
# Target chunk size: the session-sync convention uses ~1.5 MiB chunks so a
# part always fits the 2 MiB cap even with JSON payload overhead.
PART_TARGET_BYTES = int(1.5 * 1024 * 1024)
# Hard cap on the WHOLE transcript (explicit error above this).
MAX_TOTAL_BYTES = 20 * 1024 * 1024

# Same charset as skill-runner sessions.SESSION_ID_RE (session_id goes into
# a file name; the .partN suffix needs dots).
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
# Base id budget when splitting: base + ".partN" must stay <= 128 chars.
# pi session basenames are 64 chars, so this only bites on hand-crafted ids.
_PART_SUFFIX_BUDGET = 16  # ".part" + up to 5 digits


class SplitError(ValueError):
    """The transcript cannot be split/ingested as given."""


def validate_session_id(session_id: str) -> bool:
    """session_id is part of a file name — safe charset only."""
    return bool(SESSION_ID_RE.match(session_id))


def split_transcript(transcript: str, session_id: str) -> List[Dict]:
    """Split a transcript into ingestable parts.

    Returns a list of part dicts, in order:

        {"session_id": <ingest id>, "transcript": <part text>,
         "lines": (start, end)}

    where ``lines`` is a 1-based inclusive range over the WHOLE transcript
    and the ingest id is the bare ``session_id`` for a single-part
    transcript, or ``{session_id}.partN`` (N from 1) for a split one.

    Raises SplitError for: empty transcript, invalid session_id, total size
    above MAX_TOTAL_BYTES, a base id too long to carry a .partN suffix, or
    a single line above PART_MAX_BYTES (unsplitable).
    """
    if not transcript or not transcript.strip():
        raise SplitError("transcript is required")
    if not validate_session_id(session_id):
        raise SplitError(
            "session_id must match [A-Za-z0-9][A-Za-z0-9._-]{0,127}"
        )
    data = transcript.encode("utf-8")
    if len(data) > MAX_TOTAL_BYTES:
        raise SplitError(
            f"transcript too large ({len(data)} bytes; max {MAX_TOTAL_BYTES})"
        )

    # Single part: no suffix, one ingest call.
    if len(data) <= PART_MAX_BYTES:
        n_lines = len(transcript.splitlines())
        return [
            {
                "session_id": session_id,
                "transcript": transcript,
                "lines": (1, n_lines),
            }
        ]

    # Split: the base id must leave room for ".partN".
    if len(session_id) + _PART_SUFFIX_BUDGET > 128:
        raise SplitError(
            f"session_id too long to split (base {len(session_id)} chars; "
            f"'{session_id}.partN' must stay <= 128)"
        )

    lines = transcript.splitlines(keepends=True)
    parts: List[Dict] = []
    buf: List[str] = []
    buf_bytes = 0
    buf_start = 1
    for i, line in enumerate(lines, start=1):
        n = len(line.encode("utf-8"))
        if n > PART_MAX_BYTES:
            raise SplitError(
                f"single line of {n} bytes exceeds the {PART_MAX_BYTES}-byte "
                f"part cap (unsplitable)"
            )
        if buf and buf_bytes + n > PART_TARGET_BYTES:
            parts.append(
                {
                    "session_id": f"{session_id}.part{len(parts) + 1}",
                    "transcript": "".join(buf),
                    "lines": (buf_start, i - 1),
                }
            )
            buf, buf_bytes, buf_start = [], 0, i
        buf.append(line)
        buf_bytes += n
    if buf:
        parts.append(
            {
                "session_id": f"{session_id}.part{len(parts) + 1}",
                "transcript": "".join(buf),
                "lines": (buf_start, len(lines)),
            }
        )
    return parts

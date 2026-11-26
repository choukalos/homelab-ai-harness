"""Publish engine — P12-C (SEC-12). The single publish engine.

Extracted from `skills/publish_file/skill.py` (which becomes a thin HTTP
wrapper over this bridge's `POST /publish`) and PARAMETERIZED BY TARGET
CONFIG (the `publish_targets` section of filebridge.yaml): root, subdirs,
default_subdir, url_base, source_roots, size_cap_mb.

SAME semantics as the original skill (validated / atomic / size-capped /
idempotent, source roots restricted):

  - Source: absolute regular file, no symlinks, no special files, under
    the target's `source_roots` (default-deny).
  - Destination: always inside the target root; subdirectory allowlist
    (`'files'` banned — it would produce /files/files/...); sanitized
    destination_name (plain filename, 1..150 chars, charset-checked).
  - Size cap per target (`size_cap_mb`).
  - Atomic write: copy to a `.publish_*` temp file in the destination
    dir, sha256 en route, chmod 0644, os.replace. No partial files ever
    visible.
  - Idempotency (publish-file-dedup, 2026-11-13): republishing identical
    content to an existing destination is a no-op SUCCESS
    (report.duplicate=true, no copy, mtime unchanged). Different content
    fails unless overwrite=true; overwrite=true always replaces (the
    force flag — a changed render is never silently suppressed).

Result shape (the skill's contract, passed through verbatim):
  {summary, artifact_path, report: {path, url, size_bytes, sha256,
   destination_name, subdirectory[, duplicate]}}
`url` is None for targets without a public url_base (e.g. nas — access
via work-area tools / 1b tokens instead).

`PublishTarget` adapter interface (D14): LocalFSTarget implements it for
local-filesystem targets (blog, nas). A remote target (e.g. bluebovine)
would implement the same interface with an API upload in place of the
local atomic copy — see the protocol docstring. NO bluebovine
implementation exists (interface only, per D14).
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Protocol, runtime_checkable

MAX_NAME_LEN = 150
_CHUNK = 4 * 1024 * 1024
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class PublishError(ValueError):
    """Validation or publish failure (message is safe to surface)."""


# ---------------------------------------------------------------------------
# Adapter interface (D14)
# ---------------------------------------------------------------------------


@runtime_checkable
class PublishTarget(Protocol):
    """A publish target the engine can publish to.

    An implementation must provide:

      - ``name: str`` — the registry target name (filebridge.yaml
        ``publish_targets`` key).
      - ``publish(file, subdir, name, overwrite) -> dict`` — publish
        `file` (an absolute source path) into this target and return the
        report shape ``{summary, artifact_path, report: {path, url,
        size_bytes, sha256, destination_name, subdirectory[,
        duplicate]}}``; raise :class:`PublishError` on any validation
        failure (message safe to surface to the caller).

    Contract expectations (enforced by LocalFSTarget, expected of any
    implementation):
      - source validation against the target's approved source roots
        (default-deny; no symlinks / special files / traversal);
      - destination containment inside the target root;
      - size cap;
      - atomic visibility (no partial files);
      - idempotent republish (identical content -> no-op success with
        ``report.duplicate = True``; different content -> error unless
        ``overwrite``).

    LocalFSTarget (below) implements this for local-filesystem targets
    (blog, nas). A remote target (e.g. **bluebovine**) would implement
    the same interface with an API upload in place of the local atomic
    copy — e.g. an authenticated ``upload(file) -> {url, sha256?}``
    round-trip on the remote, then the same report shape (``url`` from
    the remote, ``path`` the remote artifact id). Documented only — NO
    bluebovine implementation exists (D14: interface only).
    """

    name: str

    def publish(self, file: Path, subdir: str, name: str,
                overwrite: bool) -> dict: ...


# ---------------------------------------------------------------------------
# Local-filesystem target (blog + nas)
# ---------------------------------------------------------------------------


class LocalFSTarget:
    """PublishTarget for a local-filesystem target, parameterized by the
    registry target config (root, subdirs, default_subdir, url_base,
    source_roots, size_cap_mb)."""

    def __init__(self, name: str, cfg: dict):
        self.name = name
        self.root = Path(str(cfg["root"]))
        self.subdirs = [str(s) for s in (cfg.get("subdirs") or [])]
        self.default_subdir = str(cfg.get("default_subdir") or "")
        self.url_base = str(cfg.get("url_base") or "").rstrip("/")
        self.source_roots = [Path(str(r)) for r in (cfg.get("source_roots") or [])]
        self.size_cap = int(float(cfg.get("size_cap_mb", 500)) * 1024 * 1024)

    # -- validation ---------------------------------------------------------

    def _validate_source(self, source_path) -> Path:
        """Resolve and validate the source file. Returns the resolved Path."""
        source_path = str(source_path)
        if not source_path or "\x00" in source_path:
            raise PublishError(
                "source_path is required and must not contain NUL bytes")
        p = Path(source_path)
        if not p.is_absolute():
            raise PublishError("source_path must be absolute")
        # Symlinks: resolve() follows them; reject if the *given* path was a
        # symlink (policy: no symlinks in the publish path).
        if p.is_symlink():
            raise PublishError("source must not be a symlink")
        resolved = p.resolve()
        if not resolved.is_file():
            raise PublishError(f"source is not a regular file: {source_path}")
        if resolved.is_symlink():
            raise PublishError("source must not be a symlink")
        # Special files (fifo/socket/device) — is_file() is False for those,
        # but be explicit.
        if not stat.S_ISREG(resolved.stat().st_mode):
            raise PublishError(
                "source must be a regular file (no fifos/sockets/devices)")
        # Containment: must be under one of the target's source roots.
        for root in self.source_roots:
            root_resolved = root.resolve()
            if resolved == root_resolved or resolved.is_relative_to(root_resolved):
                return resolved
        raise PublishError(
            f"source must be under one of the target's source_roots "
            f"({[str(r) for r in self.source_roots]})")

    def _validate_destination(self, subdirectory: str, name: str) -> Path:
        """Validate and build the destination path (always inside root)."""
        if subdirectory == "files":
            base_note = (f" The drop zone is already served at "
                         f"{self.url_base}/." if self.url_base else "")
            use_note = (f" Use one of {self.subdirs} "
                        f"(default: '{self.default_subdir}')."
                        if self.subdirs else
                        " This target is flat (no subdirectories).")
            raise PublishError(
                "subdirectory 'files' is not a valid subdirectory: it would "
                f"produce a /files/files/... URL.{base_note}{use_note}")
        if subdirectory:
            if not self.subdirs:
                raise PublishError(
                    f"target {self.name!r} has no subdirectories (flat) — "
                    "pass subdirectory=''")
            if subdirectory not in self.subdirs:
                raise PublishError(
                    f"subdirectory {subdirectory!r} is not allowed for this "
                    f"target (allowed: {', '.join(self.subdirs)})")
        if "/" in name or "\\" in name:
            raise PublishError(
                "destination_name must be a plain filename (no path "
                "separators)")
        if not name or len(name) > MAX_NAME_LEN:
            raise PublishError(f"destination_name must be 1..{MAX_NAME_LEN} chars")
        if name.startswith((".", "-")) or name == "~":
            raise PublishError(
                "destination_name must not start with '.' or '-'")
        if not _NAME_RE.match(name):
            raise PublishError(
                "destination_name may contain only letters, digits, '.', "
                "'_', '-' (must start with a letter or digit)")
        dest_dir = self.root / subdirectory if subdirectory else self.root
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / name
        # Final containment check (defence in depth).
        dest_resolved = dest.resolve()
        if not dest_resolved.is_relative_to(self.root.resolve()):
            raise PublishError(
                "destination escaped the target root (should be impossible)")
        return dest

    # -- publish ------------------------------------------------------------

    def publish(self, file: Path, subdir: str, name: str,
                overwrite: bool) -> dict:
        """Publish `file` into this target. See the module docstring for
        the semantics; returns the report shape, raises PublishError."""
        src = self._validate_source(file)
        name = name or src.name
        dest = self._validate_destination(subdir, name)

        if dest.exists() and not overwrite:
            # Idempotent republish (publish-file-dedup, 2026-11-13):
            # identical content is a no-op success; different content
            # still fails.
            _src_size, src_digest = _hash_file(src)
            dest_size, dest_digest = _hash_file(dest)
            if src_digest == dest_digest:
                return self._report(dest, subdir, dest.name, dest_size,
                                    dest_digest, duplicate=True)
            raise PublishError(
                f"destination already exists with different content: {dest} "
                f"(published sha256={dest_digest[:12]}… ≠ source "
                f"sha256={src_digest[:12]}…; pass overwrite=true to replace "
                "it)")

        size, digest = self._copy_atomic(src, dest)
        return self._report(dest, subdir, dest.name, size, digest)

    # -- helpers --------------------------------------------------------------

    def _url(self, subdir: str, name: str) -> str | None:
        if not self.url_base:
            return None
        return (f"{self.url_base}/{subdir}/{name}" if subdir
                else f"{self.url_base}/{name}")

    def _report(self, dest: Path, subdir: str, name: str, size: int,
                digest: str, duplicate: bool = False) -> dict:
        url = self._url(subdir, name)
        where = url or str(dest)
        if duplicate:
            summary = (f"already published (identical content) — no-op: "
                       f"{name} → {where}")
        else:
            summary = f"published {name} ({_human(size)}) → {where}"
        report = {
            "path": str(dest),
            "url": url,
            "size_bytes": size,
            "sha256": digest,
            "destination_name": name,
            "subdirectory": subdir,
        }
        if duplicate:
            report["duplicate"] = True
        return {"summary": summary, "artifact_path": str(dest),
                "report": report}

    def _copy_atomic(self, src: Path, dest: Path) -> tuple[int, str]:
        """Copy src → dest atomically (temp + os.replace), hashing en
        route. Returns (size_bytes, sha256_hex)."""
        size = src.stat().st_size
        if size > self.size_cap:
            raise PublishError(
                f"file is {_human(size)} — exceeds the {_human(self.size_cap)} "
                f"cap for target {self.name!r}")
        fd, tmp_name = tempfile.mkstemp(prefix=".publish_",
                                        dir=str(dest.parent))
        try:
            sha = hashlib.sha256()
            with os.fdopen(fd, "wb") as out, open(src, "rb") as fsrc:
                while True:
                    chunk = fsrc.read(_CHUNK)
                    if not chunk:
                        break
                    out.write(chunk)
                    sha.update(chunk)
            os.chmod(tmp_name, 0o644)  # world-readable, non-executable
            os.replace(tmp_name, dest)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        return size, sha.hexdigest()


# ---------------------------------------------------------------------------
# Engine entry point (registry-parameterized)
# ---------------------------------------------------------------------------


def target_for(doc: dict, name: str) -> LocalFSTarget | None:
    """The LocalFSTarget for registry target `name` (None if unknown)."""
    spec = (doc or {}).get("publish_targets", {}).get(name)
    if not isinstance(spec, dict):
        return None
    return LocalFSTarget(name, spec)


def publish(doc: dict, target_name: str, src, subdirectory: str = "",
            destination_name: str = "", overwrite: bool = False) -> dict:
    """Publish `src` to registry target `target_name`.

    `subdirectory` empty = the target's default (blog: 'ai'; flat targets
    like nas: ''). Returns the report shape; raises PublishError.
    """
    t = target_for(doc, target_name)
    if t is None:
        raise PublishError(
            f"unknown publish target: {target_name!r} (see file_targets())")
    sub = str(subdirectory or t.default_subdir or "")
    return t.publish(Path(src), sub, str(destination_name or ""), overwrite)


def _hash_file(path: Path) -> tuple[int, str]:
    """Stream-hash a file. Returns (size_bytes, sha256_hex)."""
    sha = hashlib.sha256()
    size = 0
    with open(path, "rb") as f:
        while True:
            chunk = f.read(_CHUNK)
            if not chunk:
                break
            size += len(chunk)
            sha.update(chunk)
    return size, sha.hexdigest()


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024  # type: ignore[assignment]
    return f"{n:.1f} GB"

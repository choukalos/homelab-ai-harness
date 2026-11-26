"""mcp_filebridge registry — load + lint (P12-B, SEC-12).

`filebridge.yaml` has three sections:

  public_file_serving:  (P12-A) GET /media/files/{path} — root + allowlisted
                             top-level subdirs (default-deny).
  work_areas:           (P12-B) registered thor work areas + the Matrix
                             pipeline (api area, first-class per D12).
  publish_targets:      (P12-B) publish targets (blog, nas).

Default-deny: anything not registered is invisible to the MCP face and to
public serving. `lint()` returns (errors, warnings) — boot fails fast on
errors (`python app.py` refuses to start; `python app.py lint` exits 1).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_URL_RE = re.compile(r"^https?://\S+$")
_BOOL_FLAGS = ("remote_write", "automount", "shared_output")


def load(path: Path | str) -> dict:
    """Load the registry YAML ({} when missing — P12-A behavior)."""
    try:
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}


def serving(doc: dict) -> dict:
    """The P12-A public-serving policy: {"root": Path, "allow": [str]}."""
    s = (doc or {}).get("public_file_serving") or {}
    root = Path(s.get("root") or os.environ.get(
        "MEDIA_ROOT", "/home/chuck/data/media"))
    allow = [str(x) for x in (s.get("allow") or [])]
    return {"root": root, "allow": allow}


def work_areas(doc: dict) -> dict:
    return (doc or {}).get("work_areas") or {}


def publish_targets(doc: dict) -> dict:
    return (doc or {}).get("publish_targets") or {}


def _is_abs(p: str) -> bool:
    return isinstance(p, str) and p.startswith("/")


def lint(doc: dict) -> tuple[list[str], list[str]]:
    """Validate the registry. Returns (errors, warnings); no errors = green.

    Checks: section presence, name/flag types, exactly-one-of path/api,
    absolute paths, path existence (autofs areas may be missing -> warning),
    no overlapping work-area paths, publish-target shape (root/subdirs/
    url_base/source_roots/size_cap_mb), 'files' subdir ban, and D13
    default-deny consistency (a remote_write:false area must not be
    publicly served).
    """
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(doc, dict):
        return ["registry: top level must be a mapping"], warnings

    # --- public_file_serving (P12-A) ---
    ps = doc.get("public_file_serving")
    allow: list[str] = []
    if not isinstance(ps, dict):
        errors.append("public_file_serving: missing or not a mapping")
    else:
        if not _is_abs(str(ps.get("root", ""))):
            errors.append("public_file_serving.root: must be an absolute path")
        raw_allow = ps.get("allow")
        if (not isinstance(raw_allow, list)
                or not all(isinstance(a, str) and _NAME_RE.fullmatch(a)
                           for a in raw_allow)):
            errors.append(
                "public_file_serving.allow: must be a list of top-level "
                "subdir names (no dots/slashes)")
        else:
            allow = [str(a) for a in raw_allow]

    # --- work_areas (P12-B) ---
    wa = doc.get("work_areas")
    if not isinstance(wa, dict) or not wa:
        errors.append("work_areas: missing or empty (P12-B requires the "
                      "full registry)")
        wa = {}
    paths: dict[str, str] = {}
    for name, spec in wa.items():
        if not _NAME_RE.fullmatch(str(name)):
            errors.append(f"work_areas.{name}: invalid name")
            continue
        if not isinstance(spec, dict):
            errors.append(f"work_areas.{name}: must be a mapping")
            continue
        has_path, has_api = "path" in spec, "api" in spec
        if has_path == has_api:
            errors.append(f"work_areas.{name}: exactly one of path/api "
                          "required")
            continue
        for flag in _BOOL_FLAGS:
            if flag in spec and not isinstance(spec[flag], bool):
                errors.append(f"work_areas.{name}.{flag}: must be a boolean")
        if has_path:
            p = str(spec["path"])
            if not _is_abs(p):
                errors.append(f"work_areas.{name}.path: must be an absolute "
                              f"path: {p!r}")
                continue
            if not Path(p).exists():
                if spec.get("automount"):
                    warnings.append(
                        f"work_areas.{name}.path: missing (autofs expected "
                        f"to materialize on access): {p}")
                else:
                    errors.append(f"work_areas.{name}.path: does not exist: "
                                  f"{p}")
            paths[name] = p
        else:
            if not _URL_RE.fullmatch(str(spec["api"])):
                errors.append(f"work_areas.{name}.api: must be an http(s) "
                              f"URL: {spec['api']!r}")

    # No work area may be nested under another (overlap).
    names = list(paths)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            pa, pb = paths[a], paths[b]
            if (pb.startswith(pa.rstrip("/") + "/")
                    or pa.startswith(pb.rstrip("/") + "/")):
                errors.append(f"work_areas: overlapping paths ({a}: {pa} "
                              f"~ {b}: {pb})")

    # --- publish_targets (P12-B) ---
    pt = doc.get("publish_targets")
    if not isinstance(pt, dict) or not pt:
        errors.append("publish_targets: missing or empty (P12-B requires "
                      "the full registry)")
        pt = {}
    for name, spec in pt.items():
        if not _NAME_RE.fullmatch(str(name)):
            errors.append(f"publish_targets.{name}: invalid name")
            continue
        if not isinstance(spec, dict):
            errors.append(f"publish_targets.{name}: must be a mapping")
            continue
        root = str(spec.get("root", ""))
        if not _is_abs(root):
            errors.append(f"publish_targets.{name}.root: must be an "
                          "absolute path")
        elif not Path(root).exists():
            errors.append(f"publish_targets.{name}.root: does not exist: "
                          f"{root}")
        subdirs = spec.get("subdirs", [])
        if (not isinstance(subdirs, list)
                or not all(isinstance(s, str) and _NAME_RE.fullmatch(s)
                           for s in subdirs)):
            errors.append(f"publish_targets.{name}.subdirs: must be a list "
                          "of subdir names")
            subdirs = []
        if "files" in subdirs:
            errors.append(
                f"publish_targets.{name}.subdirs: 'files' is banned (it "
                "would produce /files/files/)")
        ub = str(spec.get("url_base", "") or "")
        if ub and not _URL_RE.fullmatch(ub):
            errors.append(f"publish_targets.{name}.url_base: must be an "
                          "empty string or an http(s) URL")
        sroots = spec.get("source_roots", [])
        if (not isinstance(sroots, list) or not sroots
                or not all(_is_abs(str(s)) for s in sroots)):
            errors.append(f"publish_targets.{name}.source_roots: must be a "
                          "non-empty list of absolute paths")
        else:
            for s in sroots:
                if not Path(str(s)).exists():
                    errors.append(f"publish_targets.{name}.source_roots: "
                                  f"does not exist: {s}")
        cap = spec.get("size_cap_mb")
        if (not isinstance(cap, (int, float)) or isinstance(cap, bool)
                or cap <= 0):
            errors.append(
                f"publish_targets.{name}.size_cap_mb: must be a positive "
                "number")
        ds = str(spec.get("default_subdir", "") or "")
        if ds and subdirs and ds not in subdirs:
            errors.append(
                f"publish_targets.{name}.default_subdir: not in subdirs: "
                f"{ds}")

    # --- D13 default-deny consistency: a remote_write:false area must not
    # be publicly served (siri keeps its own access path).
    for name, spec in wa.items():
        if (isinstance(spec, dict) and spec.get("remote_write") is False):
            base = Path(str(spec.get("path", ""))).name
            if base and base in allow:
                errors.append(
                    f"work_areas.{name}: remote_write:false but publicly "
                    "served (allowlisted) — D13 violation")

    return errors, warnings


def lint_cli(doc: dict) -> int:
    """Print the lint report; return the process exit code (0 = green)."""
    errors, warnings = lint(doc)
    for w in warnings:
        print(f"registry lint WARN: {w}")
    for e in errors:
        print(f"registry lint ERROR: {e}")
    if errors:
        print(f"registry lint: FAILED ({len(errors)} errors)")
        return 1
    print(f"registry lint: OK ({len(work_areas(doc))} work areas, "
          f"{len(publish_targets(doc))} publish targets)")
    return 0

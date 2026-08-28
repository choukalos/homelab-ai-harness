#!/usr/bin/env python3
"""
CHOUKALOS // HOMELAB — public portal server.

Zero-dependency (Python stdlib only) static server for the Hugo portal.

Routes
------
  /            → Hugo site build (git-sync ``current`` symlink, resolved live
                 per request so deploys swap atomically without restarts)
  /files/...   → curated public drop zone: themed browse + file serving
  /status/...  → runtime status artifacts (publisher deferred)

Security properties
-------------------
  * Every request is resolved with ``os.path.realpath`` and must remain
    inside its root — path traversal is rejected by construction.
  * The portal is strictly read-only: it never writes to any mounted path.
  * Active content (``.html`` / ``.js`` / ``.svg``) is served inline per
    owner decision — see ``blog-todo.md`` §2.3 for the threat model and
    guardrails (cookie-less origin, no public upload path, nosniff).
  * Host paths are never exposed in responses (browse shows /files/ URLs
    only; errors are generic).
  * No version strings in responses.
"""

from __future__ import annotations

import html
import mimetypes
import os
import posixpath
import shutil
import sys
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ---------------------------------------------------------------------------
# Configuration (env-overridable; compose sets the canonical values)
# ---------------------------------------------------------------------------

GIT_ROOT = os.environ.get("PORTAL_GIT_ROOT", "/git")
FILES_ROOT = os.environ.get("PORTAL_FILES_ROOT", "/files")
RUNTIME_ROOT = os.environ.get("PORTAL_RUNTIME_ROOT", "/runtime")
SITE_LINK = os.path.join(GIT_ROOT, "current")

LISTEN_HOST = os.environ.get("PORTAL_HOST", "0.0.0.0")
PORT = int(os.environ.get("PORTAL_PORT", "8080"))

SITE_CACHE_MAX_AGE = 3600      # site assets (hashed filenames are immutable)
FILES_CACHE_MAX_AGE = 3600     # drop-zone files
CHUNK_SIZE = 256 * 1024

# MIME types the stdlib table doesn't know (or gets wrong).
EXTRA_MIME = {
    ".svg": "image/svg+xml",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".json": "application/json",
    ".xml": "application/xml",
    ".webmanifest": "application/manifest+json",
    ".ico": "image/x-icon",
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".csv": "text/csv",
    ".md": "text/markdown",
}

# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------


def site_root() -> str | None:
    """Resolve the live site root (git-sync ``current`` symlink).

    Returns None while no deploy is present (first sync in progress) — the
    caller serves a themed 503. Re-resolved per request so the atomic
    symlink swap is always followed.
    """
    try:
        root = os.path.realpath(SITE_LINK)
    except OSError:
        return None
    return root if os.path.isdir(root) else None


def safe_join(root: str, rel: str) -> str | None:
    """Join ``rel`` onto ``root``; return the resolved path only if it stays
    inside ``root``. Returns None for traversal attempts (``..``, symlinks
    escaping the root, absolute paths)."""
    if "\x00" in rel:
        return None
    # Normalize to a clean relative path; normpath collapses any .. segments.
    clean = posixpath.normpath("/" + rel).lstrip("/")
    target = os.path.realpath(os.path.join(root, clean))
    if target == root or target.startswith(root + os.sep):
        return target
    return None


def guess_type(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in EXTRA_MIME:
        return EXTRA_MIME[ext]
    ctype, _ = mimetypes.guess_type(path)
    return ctype or "application/octet-stream"


# ---------------------------------------------------------------------------
# Browse page (themed, no JS, reuses the site's stylesheet)
# ---------------------------------------------------------------------------

_CSS_CACHE: dict[str, float | str] = {"until": 0.0, "name": ""}


def site_css_href() -> str:
    """Find the site's current minified stylesheet (hashed filename changes
    per Hugo build). Cached for 30s. Empty string if the site is absent."""
    now = time.time()
    if now < _CSS_CACHE["until"] and _CSS_CACHE["name"]:
        return f"/css/{_CSS_CACHE['name']}"
    root = site_root()
    name = ""
    if root:
        css_dir = os.path.join(root, "css")
        best_mtime = -1.0
        try:
            for entry in os.scandir(css_dir):
                if not entry.name.startswith("main.min.") or not entry.name.endswith(".css"):
                    continue
                if entry.is_file():
                    mtime = entry.stat().st_mtime
                    if mtime > best_mtime:
                        best_mtime, name = mtime, entry.name
        except OSError:
            pass
    _CSS_CACHE["until"] = now + 30.0
    _CSS_CACHE["name"] = name
    return f"/css/{name}" if name else ""


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024  # type: ignore[assignment]
    return f"{n:.1f} TB"


def human_age(mtime: float) -> str:
    age = max(0, int(time.time() - mtime))
    if age < 60:
        return f"{age}s ago"
    if age < 3600:
        return f"{age // 60}m ago"
    if age < 86400:
        return f"{age // 3600}h ago"
    if age < 86400 * 30:
        return f"{age // 86400}d ago"
    return time.strftime("%Y-%m-%d", time.gmtime(mtime))


def _page(title: str, body: str) -> str:
    """Full HTML page in the site's visual language (reuses site CSS + nav)."""
    css = site_css_href()
    css_link = f'<link rel=stylesheet href={css}>' if css else (
        "<style>body{background:#05070f;color:#d9e3f5;font-family:sans-serif;"
        "margin:2rem auto;max-width:60rem;padding:0 1rem}</style>"
    )
    return (
        "<!doctype html><html lang=en><head>"
        "<meta charset=utf-8>"
        '<meta name=viewport content="width=device-width,initial-scale=1">'
        f"<title>{html.escape(title)}</title>"
        '<meta name=color-scheme content="dark">'
        f"{css_link}"
        "<style>"
        ".drop-banner{border-left:3px solid var(--amber);padding:.8rem 1rem;"
        "margin-bottom:1.2rem;background:var(--panel)}"
        ".drop-banner .mono{color:var(--amber)}"
        ".crumbs{margin:.5rem 0 1rem;font-size:.85rem}"
        ".crumbs a{color:var(--cyan);text-decoration:none}"
        ".crumbs a:hover{text-decoration:underline}"
        ".crumbs .sep{color:var(--dim);margin:0 .35rem}"
        ".crumbs .here{color:var(--muted)}"
        "table.filetable{width:100%;border-collapse:collapse}"
        "table.filetable th{font-family:var(--mono);font-size:.7rem;letter-spacing:.08em;"
        "color:var(--dim);text-align:left;padding:.4rem .6rem;border-bottom:1px solid var(--line)}"
        "table.filetable td{padding:.5rem .6rem;border-bottom:1px solid var(--line);vertical-align:middle}"
        "table.filetable tr:hover td{background:var(--panel-2)}"
        "table.filetable a.fname{color:var(--text);text-decoration:none}"
        "table.filetable a.fname:hover{color:var(--cyan)}"
        ".fsize,.fage{font-family:var(--mono);font-size:.78rem;color:var(--muted);white-space:nowrap}"
        ".ficon{margin-right:.5rem;font-family:var(--mono);color:var(--cyan)}"
        ".empty-note{color:var(--dim);font-family:var(--mono);padding:1rem 0}"
        "</style>"
        "</head><body>"
        '<a class=skip-link href=#main>skip to content</a>'
        '<header class=site-head><div class="wrap nav-row">'
        '<a class="brand mono" href=/ aria-label=Home>CHOUKALOS<span class=brand-dim>//</span>HOMELAB</a>'
        '<nav aria-label=Primary><ul class="nav mono">'
        "<li><a href=/arcade/>ARCADE</a></li>"
        "<li><a href=/lab/>LAB</a></li>"
        "<li><a href=/thoughts/>THOUGHTS</a></li>"
        "<li><a href=/files/>FILES</a></li>"
        "</ul></nav></div></header>"
        f'<main class=wrap id=main>{body}</main>'
        '<footer class=site-foot><div class="wrap foot-row mono">'
        "<span>CHOUKALOS // HOMELAB</span>"
        '<span class=foot-dim>static · git-published · no cookies · no trackers</span>'
        "</div></footer>"
        "</body></html>"
    )


def render_browse(url_path: str, rel: str) -> str:
    """Render the themed directory listing for ``rel`` ("" = drop root)."""
    target = safe_join(FILES_ROOT, rel)
    if target is None or not os.path.isdir(target):
        return ""
    dirs, files = [], []
    try:
        for entry in os.scandir(target):
            if entry.name.startswith("."):
                continue
            if entry.is_dir(follow_symlinks=False):
                dirs.append(entry)
            else:
                files.append(entry)
    except OSError:
        return ""
    dirs.sort(key=lambda e: e.name.lower())
    files.sort(key=lambda e: e.name.lower())

    # Breadcrumb: /files/ → segments
    segs = [s for s in rel.split("/") if s]
    crumbs = [('<a href=/files/>/files/</a>')]
    for i, seg in enumerate(segs):
        href = "/files/" + "/".join(segs[: i + 1]) + "/"
        if i == len(segs) - 1:
            crumbs.append(f'<span class=here>{html.escape(seg)}/</span>')
        else:
            crumbs.append(f'<a href={html.escape(href, quote=True)}>{html.escape(seg)}/</a>')
    crumbs_html = '<span class=sep>›</span>'.join(crumbs)

    rows = []
    for d in dirs:
        href = f"/files/{rel}/{d.name}/".replace("//", "/") if rel else f"/files/{d.name}/"
        rows.append(
            f'<tr><td><span class=ficon>▸</span>'
            f'<a class=fname href={html.escape(href, quote=True)}>{html.escape(d.name)}/</a></td>'
            "<td class=fsize>—</td>"
            f'<td class=fage title="{time.strftime("%Y-%m-%d %H:%M", time.gmtime(d.stat().st_mtime))}">'
            f"{human_age(d.stat().st_mtime)}</td></tr>"
        )
    for f in files:
        href = f"/files/{rel}/{f.name}".replace("//", "/") if rel else f"/files/{f.name}"
        try:
            st = f.stat()
            size, mtime_str, mtime_ts = human_size(st.st_size), human_age(st.st_mtime), st.st_mtime
        except OSError:
            size, mtime_str, mtime_ts = "—", "—", time.time()
        rows.append(
            f'<tr><td><span class=ficon>·</span>'
            f'<a class=fname href={html.escape(href, quote=True)}>{html.escape(f.name)}</a></td>'
            f'<td class=fsize>{size}</td>'
            f'<td class=fage title="{time.strftime("%Y-%m-%d %H:%M", time.gmtime(mtime_ts))}">'
            f"{mtime_str}</td></tr>"
        )

    table = ""
    if rows:
        table = (
            '<table class=filetable><thead><tr>'
            "<th>NAME</th><th>SIZE</th><th>MODIFIED</th>"
            "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
        )
    else:
        table = '<p class=empty-note>// empty sector — nothing published here yet</p>'

    body = (
        '<div class="drop-banner" role=note>'
        '<p class=mono>PUBLIC DROP // files published by the operator or AI skills. '
        "Not part of the site. Visitors cannot upload.</p></div>"
        '<div class="card brick"><div class=brick-studs aria-hidden=true></div>'
        '<header class=card-head><h2 class=mono>FILES</h2>'
        f'<span class="card-tag mono">{html.escape(url_path)}</span></header>'
        f'<nav class="crumbs mono" aria-label=Breadcrumb>{crumbs_html}</nav>'
        f"{table}"
        "</div>"
    )
    title = f"FILES {url_path} — CHOUKALOS // HOMELAB" if url_path != "/files/" else "FILES // PUBLIC DROP — CHOUKALOS // HOMELAB"
    return _page(title, body)


def render_syncing() -> str:
    return _page(
        "SYNCING — CHOUKALOS // HOMELAB",
        '<div class="card brick"><div class=brick-studs aria-hidden=true></div>'
        '<header class=card-head><h2 class=mono>PORTAL // SYNCING</h2></header>'
        '<div class=tile-body><p class=tile-copy>first deploy in progress — '
        "check back in a minute.</p></div></div>",
    )


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------


class PortalHandler(BaseHTTPRequestHandler):
    server_version = "Portal"
    sys_version = ""  # no version leakage in Server header

    # -- plumbing -----------------------------------------------------------

    def _send(self, status: int, body: bytes, ctype: str, extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_file(self, target: str, status: int, ctype: str,
                   extra: dict[str, str] | None = None) -> None:
        """Stream a file with correct headers, honoring a single Range
        request (needed for <video>/<audio> seeking in the drop zone)."""
        size = os.path.getsize(target)
        start, length, range_status = 0, size, 200
        rng = self.headers.get("Range")
        if rng and rng.startswith("bytes="):
            spec = rng[6:].split(",")[0].strip()  # single range only
            if "-" in spec:
                s_str, e_str = spec.split("-", 1)
                try:
                    if s_str and e_str:
                        start, end = int(s_str), int(e_str)
                        if start > end or start >= size:
                            self.send_response(416)
                            self.send_header("Content-Range", f"bytes */{size}")
                            self.end_headers()
                            return
                        length = min(end, size - 1) - start + 1
                    elif s_str:
                        start = int(s_str)
                        if start >= size:
                            self.send_response(416)
                            self.send_header("Content-Range", f"bytes */{size}")
                            self.end_headers()
                            return
                        length = size - start
                    else:
                        length = min(int(e_str), size)  # suffix: last N bytes
                        start = size - length
                    range_status = 206
                except ValueError:
                    pass  # malformed range → serve the whole file
        self.send_response(range_status if status == 200 else status)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if range_status == 206:
            self.send_header("Content-Range", f"bytes {start}-{start + length - 1}/{size}")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command == "HEAD":
            return
        try:
            with open(target, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(CHUNK_SIZE, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (OSError, BrokenPipeError):
            pass  # client went away; nothing to do

    def _not_found(self, use_site_404: bool = True) -> None:
        root = site_root() if use_site_404 else None
        if root:
            t = safe_join(root, "404.html")
            if t and os.path.isfile(t):
                self._send_file(t, 404, "text/html; charset=utf-8",
                                extra={"Cache-Control": "no-cache"})
                return
        self._send(404, b"404 // SIGNAL LOST - that page isn't in this sector\n",
                   "text/plain; charset=utf-8")

    def _method_not_allowed(self) -> None:
        self._send(405, b"405 // method not allowed - this portal is read-only\n",
                   "text/plain; charset=utf-8",
                   extra={"Allow": "GET, HEAD"})

    # -- routing --------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        self._route()

    def do_HEAD(self) -> None:  # noqa: N802
        self._route()

    def do_POST(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_PUT(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_DELETE(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_PATCH(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def _route(self) -> None:
        try:
            raw = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
            if raw.startswith("/files/") or raw == "/files":
                self._files(raw)
            elif raw.startswith("/status/"):
                self._status(raw)
            else:
                self._site(raw)
        except Exception:  # noqa: BLE001 — never leak a traceback publicly
            self.log_error("unhandled error routing %s", self.path)
            self._send(500, b"500 // internal error\n", "text/plain; charset=utf-8")

    # -- /files/ — public drop zone -------------------------------------------

    def _files(self, raw: str) -> None:
        rel = raw[len("/files"):].lstrip("/")
        if raw == "/files" or (rel and not raw.endswith("/")):
            # Canonicalize: add trailing slash for directories.
            target = safe_join(FILES_ROOT, rel)
            if target is not None and os.path.isdir(target):
                self.send_response(301)
                self.send_header("Location", raw + "/")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                return
        target = safe_join(FILES_ROOT, rel)
        if target is None or not os.path.exists(target):
            self._not_found()
            return
        if os.path.isdir(target):
            page = render_browse(raw if raw.endswith("/") else raw + "/", rel)
            if page:
                self._send(200, page.encode("utf-8"), "text/html; charset=utf-8",
                           extra={"Cache-Control": "no-cache"})
            else:
                self._not_found()
            return
        self._send_file(target, 200, guess_type(target),
                        extra={"Cache-Control": f"max-age={FILES_CACHE_MAX_AGE}"})

    # -- /status/ — runtime artifacts ------------------------------------------

    def _status(self, raw: str) -> None:
        rel = raw[len("/status/"):]
        target = safe_join(RUNTIME_ROOT, rel)
        if target is None or not os.path.isfile(target):
            self._send(404, b"{}\n", "application/json")
            return
        self._send_file(target, 200, guess_type(target),
                        extra={"Cache-Control": "no-cache"})

    # -- site ------------------------------------------------------------------

    def _site(self, raw: str) -> None:
        root = site_root()
        if root is None:
            self._send(503, render_syncing().encode("utf-8"),
                       "text/html; charset=utf-8",
                       extra={"Cache-Control": "no-cache",
                              "Retry-After": "30"})
            return
        if raw.endswith("/"):
            candidate = safe_join(root, raw[1:] + "index.html")
            if candidate and os.path.isfile(candidate):
                self._send_file(candidate, 200, "text/html; charset=utf-8",
                                extra={"Cache-Control": "no-cache"})
                return
            # Directory with no index.html → 404 (no site-side browse).
            self._not_found()
            return
        candidate = safe_join(root, raw[1:])
        if candidate and os.path.isfile(candidate):
            self._send_file(candidate, 200, guess_type(candidate),
                            extra={"Cache-Control": f"max-age={SITE_CACHE_MAX_AGE}"
                                   if raw != "/" else "no-cache"})
            return
        self._not_found()


def main() -> None:
    server = ThreadingHTTPServer((LISTEN_HOST, PORT), PortalHandler)
    server.daemon_threads = True
    print(f"portal listening on {LISTEN_HOST}:{PORT} "
          f"(site={SITE_LINK} files={FILES_ROOT} runtime={RUNTIME_ROOT})",
          file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
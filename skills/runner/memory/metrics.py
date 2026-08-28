"""Dependency-free Prometheus metrics for the memory module (Phase 8).

Tracks search/write latency, hit counts, errors, and per-user memory counts,
and emits the Prometheus text exposition format. It is intentionally
dependency-free (no ``prometheus_client``) so it works identically in the
production image and in throwaway test containers, and is unit-testable
without an extra install.

Non-negotiables honored here:
  - Non-fatal: recording a metric must NEVER break a memory op. Every public
    helper swallows its own errors.
  - No secrets: metrics carry only user_id / op / status labels — never API
    keys or memory text.
  - Thread-safe: a single lock guards all counters (memory ops run from
    multiple threads — the warmup thread, job threads, the request loop).
"""
from __future__ import annotations

import threading
import time
from typing import Dict, List, Optional, Tuple

# Fixed histogram buckets (seconds) for latency. Chosen to resolve the hot
# path (~100ms warm retrieval) from the degraded cold path (~1.5s timeout)
# and the writeback budget (~30s).
_BUCKETS: Tuple[float, ...] = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)

# A label key is a sorted tuple of (name, value) pairs.
_LKey = Tuple[Tuple[str, str], ...]


def _fmt_labels(key: _LKey, extra: Optional[Tuple[str, str]] = None) -> str:
    """Format a sorted label tuple as ``{k="v",...}`` (empty -> ``""``).

    ``extra`` (e.g. the histogram ``le`` label) is appended last.
    """
    labels = list(key)
    if extra is not None:
        labels.append(extra)
    if not labels:
        return ""
    parts = ",".join(f'{k}="{v}"' for k, v in labels)
    return "{" + parts + "}"


class _Counter:
    """A labelled counter."""

    def __init__(self) -> None:
        self._v: Dict[_LKey, float] = {}

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        key = tuple(sorted(labels.items()))
        self._v[key] = self._v.get(key, 0.0) + amount

    def value(self, **labels: str) -> float:
        return self._v.get(tuple(sorted(labels.items())), 0.0)

    def items(self) -> List[Tuple[_LKey, float]]:
        return list(self._v.items())


class _Histogram:
    """A labelled histogram with fixed buckets.

    Per label-set row layout: ``[b0, b1, ..., bN, sum, count]`` where
    ``bi`` is the number of observations whose value fell into the FIRST
    bucket with upper bound >= value, and ``bN`` (index ``len(buckets)``)
    is the beyond-last-bucket count. ``sum``/``count`` are the final two
    slots. The exposition step converts ``b*`` to Prometheus' cumulative
    form.
    """

    def __init__(self, buckets: Tuple[float, ...] = _BUCKETS) -> None:
        self._buckets = list(buckets)
        self._v: Dict[_LKey, List[float]] = {}

    def _row(self, key: _LKey) -> List[float]:
        if key not in self._v:
            # (len(buckets) + 1) bucket slots + sum + count
            self._v[key] = [0.0] * (len(self._buckets) + 3)
        return self._v[key]

    def observe(self, seconds: float, **labels: str) -> None:
        key = tuple(sorted(labels.items()))
        row = self._row(key)
        idx = len(self._buckets)  # default: beyond last bucket
        for i, b in enumerate(self._buckets):
            if seconds <= b:
                idx = i
                break
        row[idx] += 1.0
        row[-2] += seconds  # sum
        row[-1] += 1.0      # count

    def count(self, **labels: str) -> float:
        key = tuple(sorted(labels.items()))
        row = self._v.get(key)
        return row[-1] if row else 0.0

    def keys(self) -> List[_LKey]:
        return list(self._v.keys())


class _Gauge:
    """A labelled gauge (set to an absolute value)."""

    def __init__(self) -> None:
        self._v: Dict[_LKey, float] = {}

    def set(self, value: float, **labels: str) -> None:
        self._v[tuple(sorted(labels.items()))] = value

    def value(self, **labels: str) -> float:
        return self._v.get(tuple(sorted(labels.items())), 0.0)

    def items(self) -> List[Tuple[_LKey, float]]:
        return list(self._v.items())


class _Metrics:
    """The memory-module metric registry (single global instance)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # Counters.
        self.search_total = _Counter()         # labels: status
        self.search_hits = _Counter()          # unlabelled total hits
        self.writeback_total = _Counter()      # labels: status
        self.writeback_stored = _Counter()     # unlabelled total stored
        self.errors_total = _Counter()         # labels: op
        # Histograms.
        self.search_latency = _Histogram()     # labels: status
        self.writeback_latency = _Histogram()  # labels: status
        # Gauges.
        self.user_count = _Gauge()             # labels: user_id
        self.last_writeback = 0.0

    # ── recording (all non-fatal) ─────────────────────────────────────
    def record_search(self, status: str, latency_s: float, hits: int) -> None:
        with self._lock:
            self.search_total.inc(status=status)
            self.search_latency.observe(latency_s, status=status)
            if hits:
                self.search_hits.inc(hits)

    def record_writeback(self, status: str, latency_s: float, stored: int) -> None:
        with self._lock:
            self.writeback_total.inc(status=status)
            self.writeback_latency.observe(latency_s, status=status)
            if stored:
                self.writeback_stored.inc(stored)
            self.last_writeback = time.time()

    def record_error(self, op: str) -> None:
        with self._lock:
            self.errors_total.inc(op=op)

    def set_user_count(self, user_id: str, count: int) -> None:
        with self._lock:
            self.user_count.set(float(count), user_id=user_id)

    # ── exposition (Prometheus text format) ───────────────────────────
    def exposition(self) -> str:
        """Render all metrics in the Prometheus text exposition format."""
        with self._lock:
            lines: List[str] = []

            def counter(name: str, help_: str, c: _Counter) -> None:
                lines.append(f"# HELP {name} {help_}")
                lines.append(f"# TYPE {name} counter")
                items = c.items()
                if not items:
                    lines.append(f"{name} 0")
                for key, val in items:
                    lines.append(f"{name}{_fmt_labels(key)} {val:g}")

            def histogram(name: str, help_: str, h: _Histogram) -> None:
                lines.append(f"# HELP {name} {help_}")
                lines.append(f"# TYPE {name} histogram")
                keys = h.keys() or [()]
                for key in keys:
                    row = h._row(key)
                    lbl = key  # base labels; `le` appended per bucket
                    running = 0.0
                    for i, b in enumerate(h._buckets):
                        running += row[i]
                        lines.append(
                            f"{name}_bucket{_fmt_labels(lbl, ('le', f'{b:g}'))}"
                            f" {running:g}"
                        )
                    running += row[len(h._buckets)]  # beyond-last (== +Inf)
                    lines.append(
                        f"{name}_bucket{_fmt_labels(lbl, ('le', '+Inf'))}"
                        f" {running:g}"
                    )
                    lines.append(f"{name}_sum{_fmt_labels(lbl)} {row[-2]:g}")
                    lines.append(f"{name}_count{_fmt_labels(lbl)} {row[-1]:g}")

            def gauge(name: str, help_: str, g: _Gauge) -> None:
                lines.append(f"# HELP {name} {help_}")
                lines.append(f"# TYPE {name} gauge")
                items = g.items()
                if not items:
                    lines.append(f"{name} 0")
                for key, val in items:
                    lines.append(f"{name}{_fmt_labels(key)} {val:g}")

            counter("memory_search_total",
                    "Total memory searches (by status).", self.search_total)
            counter("memory_search_hits_total",
                    "Total memory search hits returned.", self.search_hits)
            counter("memory_writeback_total",
                    "Total memory writebacks (by status).", self.writeback_total)
            counter("memory_writeback_stored_total",
                    "Total memories stored via writeback.", self.writeback_stored)
            counter("memory_errors_total",
                    "Total memory errors (by op).", self.errors_total)
            histogram("memory_search_latency_seconds",
                      "Memory search latency.", self.search_latency)
            histogram("memory_writeback_latency_seconds",
                      "Memory writeback latency.", self.writeback_latency)
            gauge("memory_user_count",
                  "Per-user memory count (private).", self.user_count)
            if self.last_writeback:
                lines.append("# HELP memory_last_writeback_timestamp_seconds "
                              "Unix time of the last writeback.")
                lines.append("# TYPE memory_last_writeback_timestamp_seconds gauge")
                lines.append(f"memory_last_writeback_timestamp_seconds "
                             f"{self.last_writeback:g}")
            return "\n".join(lines) + "\n"


# ── Module-level singleton ────────────────────────────────────────────
_metrics = _Metrics()


def get_metrics() -> _Metrics:
    """Return the global metrics registry."""
    return _metrics


def exposition() -> str:
    """Return the Prometheus text exposition (non-fatal)."""
    try:
        return _metrics.exposition()
    except Exception:  # noqa: BLE001 - metrics must never raise
        return "# memory metrics unavailable\n"
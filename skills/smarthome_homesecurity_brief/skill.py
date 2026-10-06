#!/usr/bin/env python3
"""
smarthome_homesecurity_brief skill — specialty subskill for the
Smart Home & Home Security market.

Thin wrapper around the generic market_research_brief engine: it pins the
`smarthome_homesecurity` profile (competitors, analyst firms, seed queries,
publish slug) and delegates everything else — research collection, LLM
synthesis, HTML rendering, artifact retention, blog publishing, and the
January yearly summary — to the engine.

Why a separate skill (instead of just passing market=... to the engine)?
So the monthly scheduler and any channel can launch the specialty by name
without remembering the profile id, and so it shows up in GET /skills with
its own description.

All LLM/MCP traffic goes through LiteLLM (via the engine). Never touch MCP
servers directly.
"""

import importlib.util
from pathlib import Path
from typing import Any

# The pinned market profile (file: market_research_brief/profiles/smarthome_homesecurity.yml)
PROFILE = "smarthome_homesecurity"


def _load_engine() -> Any:
    """Load the generic market_research_brief engine module."""
    engine_path = (
        Path(__file__).resolve().parent.parent / "market_research_brief" / "skill.py"
    )
    spec = importlib.util.spec_from_file_location("market_research_engine", engine_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load engine spec from {engine_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(
    params: dict[str, Any],
    job,
    litellm_client=None,
) -> dict[str, Any]:
    """Execute the specialty brief by delegating to the generic engine with
    the smarthome_homesecurity profile pinned.

    Any explicit `market` in params is ignored (the specialty pins its own
    profile); all other params pass through unchanged.
    """
    engine = _load_engine()
    merged = dict(params or {})
    merged["market"] = PROFILE
    if hasattr(job, "add_log"):
        job.add_log(f"smarthome_homesecurity_brief → delegating to market_research_brief (market={PROFILE})")
    return engine.run(merged, job, litellm_client)


# ---------------------------------------------------------------------------
# CLI entrypoint (standalone testing)
# ---------------------------------------------------------------------------


def main() -> None:
    """Standalone CLI for testing the smarthome_homesecurity_brief skill."""
    import argparse

    engine = _load_engine()
    parser = argparse.ArgumentParser(
        description="smarthome_homesecurity_brief skill (standalone)"
    )
    parser.add_argument("--period-days", type=int, default=30,
                        help="Lookback window in days (default: %(default)s)")
    parser.add_argument("--max-items", type=int, default=5,
                        help="Max news items per query (default: %(default)s)")
    parser.add_argument("--publish", action="store_true", default=False,
                        help="Publish the HTML brief to the blog drop zone")
    parser.add_argument("--publish-path", default="",
                        help="Override the published 'latest' file path")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show resolved config without executing")
    args = parser.parse_args()

    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    params: dict[str, Any] = {
        "market": PROFILE,
        "period_days": args.period_days,
        "max_items": args.max_items,
        "publish": args.publish,
    }
    if args.publish_path:
        params["publish_path"] = args.publish_path

    if args.dry_run:
        print("Resolved configuration:")
        print(f"  market:       {PROFILE} (pinned)")
        print(f"  period_days:  {args.period_days}")
        print(f"  max_items:    {args.max_items}")
        print(f"  publish:      {args.publish}")
        print(f"  publish_path: {args.publish_path or '(profile default)'}")
        print(f"  model_alias:  {engine.MODEL_ALIAS}")
        print(f"  litellm:      {engine.LITELLM_BASE_URL}")
        print(f"  artifact_dir: {engine.ARTIFACT_DIR}")
        return

    class _CLIJob:
        def add_log(self, msg: str) -> None:
            print(f"[log] {msg}")

    job = _CLIJob()
    result = run(params, job)

    print("\n" + "=" * 70)
    print("SUMMARY:")
    for key in (
        "summary", "market", "period_days", "competitors_scanned",
        "competitors_with_news", "items_found", "memory_used", "kb_used",
        "artifact_path", "html_artifact_path",
        "published_path", "published_url",
        "dated_publish_path", "dated_publish_url",
    ):
        if key in result:
            print(f"  {key}: {result.get(key)}")
    if result.get("yearly"):
        print(f"  yearly: {result['yearly']}")
    if result.get("error"):
        print(f"  ERROR: {result['error']}")
    print("=" * 70)

    if result.get("report"):
        print("\nREPORT:\n")
        print(result["report"])


if __name__ == "__main__":
    main()
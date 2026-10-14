#!/usr/bin/env python3
"""
market_research_reference skill — annual reference (re)build for a market.

Rebuilds references/<market>.json via market_research_brief/reference.py
(crawl vendor sources + LLM extraction of the comparison facts, ratings,
market-size estimates, and share indicators), then republishes the
standalone reference page to the blog drop zone:

    briefs/market_research/<market>_reference.html

Why a separate skill? A full reference build takes ~15-30 min (outside the
600 s brief budget), so the January annual rebuild runs as its own
scheduled job BEFORE the monthly brief job, which then embeds the fresh
reference. The monthly brief's `build_reference: true` param only refreshes
when the reference is stale AND the build fits the budget (warm cache).

All LLM/MCP traffic goes through LiteLLM (via reference.py). Never touch
MCP servers directly.
"""

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SKILL_DIR = Path(__file__).resolve().parent
ENGINE_DIR = SKILL_DIR.parent / "market_research_brief"
PUBLIC_ROOT = Path(
    __import__("os").environ.get("PUBLIC_ROOT", "/home/chuck/data/media/public")
)


def _load_reference_module() -> Any:
    """Load the reference.py module from the market_research_brief skill."""
    ref_path = ENGINE_DIR / "reference.py"
    spec = importlib.util.spec_from_file_location("market_research_reference_mod", ref_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load reference module spec from {ref_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _publish_reference(ref_mod: Any, market: str, job) -> tuple[str, str]:
    """Render + publish the standalone reference page. Returns (path, url)."""
    profile, ref_block = ref_mod.load_profile(market)
    ref = json.loads(ref_mod.reference_path(market).read_text(encoding="utf-8"))
    doc = ref_mod.render_standalone_html(ref, ref_block, mode="full")

    target = PUBLIC_ROOT / "briefs" / "market_research" / f"{market}_reference.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(doc, encoding="utf-8")
    if hasattr(job, "add_log"):
        job.add_log(f"Published reference page: {target}")

    public_url = ""
    base = __import__("os").environ.get("PUBLIC_BASE_URL", "https://choukalos.com/files")
    public_url = f"{base}/briefs/market_research/{market}_reference.html"
    return str(target), public_url


def run(
    params: dict[str, Any],
    job,
    litellm_client=None,
) -> dict[str, Any]:
    """Rebuild the annual reference for `params['market']` and republish it."""
    market = str(params.get("market") or "").strip()
    if not market:
        ref_mod = _load_reference_module()
        available = sorted(p.stem for p in (ENGINE_DIR / "profiles").iterdir()
                           if p.suffix in (".yml", ".yaml", ".json"))
        return {"error": f"No market given. Available profiles: {', '.join(available)}"}

    ref_mod = _load_reference_module()

    if hasattr(job, "add_log"):
        job.add_log(f"market_research_reference → building reference for market={market}")

    ref = ref_mod.build_reference(market)

    try:
        published_path, published_url = _publish_reference(ref_mod, market, job)
    except Exception as exc:  # noqa: BLE001 — build succeeded; publish is best-effort
        published_path, published_url = "", str(exc)
        if hasattr(job, "add_log"):
            job.add_log(f"Reference publish failed: {exc}")

    n_competitors = len(ref.get("competitors") or [])
    n_sizes = len([s for s in (ref.get("market_size") or []) if isinstance(s.get("estimate_usd_b"), (int, float))])
    n_indicators = len([i for i in (ref.get("share_indicators") or []) if i.get("value")])
    return {
        "market": market,
        "summary": (
            f"Reference rebuilt: {n_competitors} competitors, "
            f"{n_sizes} market-size estimates, {n_indicators} share indicators "
            f"(built {ref.get('built_at')})"
        ),
        "reference_path": str(ref_mod.reference_path(market)),
        "published_path": published_path,
        "published_url": published_url,
    }


# ---------------------------------------------------------------------------
# CLI entrypoint (standalone testing)
# ---------------------------------------------------------------------------


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="market_research_reference skill (standalone)")
    parser.add_argument("--market", default="", help="Market profile name (required)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show resolved config without executing")
    args = parser.parse_args()

    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.dry_run:
        print("Resolved configuration:")
        print(f"  market:       {args.market or '(not set)'}")
        print(f"  engine_dir:   {ENGINE_DIR}")
        print(f"  public_root:  {PUBLIC_ROOT}")
        return

    class _CLIJob:
        def add_log(self, msg: str) -> None:
            print(f"[log] {msg}")

    result = run({"market": args.market}, _CLIJob())
    print("\n" + "=" * 70)
    print("SUMMARY:")
    for key, val in result.items():
        print(f"  {key}: {val}")
    print("=" * 70)


if __name__ == "__main__":
    main()

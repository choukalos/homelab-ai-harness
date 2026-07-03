#!/usr/bin/env python3
"""Example usage of the MCP Search Server.

This script demonstrates calling each of the three search tools directly.
It requires a running SearXNG instance at the URL configured in SEARXNG_URL.

Usage:
    # Container (Docker network):
    python examples/example_usage.py

    # Host (direct):
    SEARXNG_URL=http://192.168.4.54:8088 python examples/example_usage.py
"""

import asyncio
import sys
import os

# Allow importing server from parent directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main():
    from server import search_web, search_recent, search_news

    print("=" * 60)
    print("Example: search_web")
    print("=" * 60)
    try:
        results = await search_web("homelab self-hosted AI", max_results=3)
        for i, r in enumerate(results, 1):
            print(f"\n{i}. {r['title']}")
            print(f"   URL: {r['url']}")
            print(f"   Snippet: {r['snippet']}")
    except RuntimeError as e:
        print(f"Error: {e}")
        print("  (SearXNG may not be reachable at the configured URL)")

    print("\n" + "=" * 60)
    print("Example: search_recent")
    print("=" * 60)
    try:
        results = await search_recent("open source AI", days=7, max_results=3)
        for i, r in enumerate(results, 1):
            print(f"\n{i}. {r['title']}")
            print(f"   URL: {r['url']}")
            print(f"   Snippet: {r['snippet']}")
    except RuntimeError as e:
        print(f"Error: {e}")

    print("\n" + "=" * 60)
    print("Example: search_news")
    print("=" * 60)
    try:
        results = await search_news("artificial intelligence", max_results=3)
        for i, r in enumerate(results, 1):
            print(f"\n{i}. {r['title']}")
            print(f"   URL: {r['url']}")
            print(f"   Snippet: {r['snippet']}")
    except RuntimeError as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    asyncio.run(main())

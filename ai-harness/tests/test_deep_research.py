"""
Test script for the Deep Research module.

Usage:
    python tests/test_deep_research.py

Ensure the ai-harness is running and HARNESS_URL / HARNESS_API_KEY are set
in your environment (or edit the defaults below).
"""

import os
import sys
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BASE_URL = os.getenv("HARNESS_URL", "http://localhost:8090")
API_KEY = os.getenv("HARNESS_API_KEY", "")
DEEP_RESEARCH_URL = f"{BASE_URL}/workflows/deep-research/run"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _headers() -> dict:
    h = {"Content-Type": "application/json"}
    if API_KEY:
        h["X-API-Key"] = API_KEY
    return h

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_health() -> bool:
    """Verify the harness is reachable."""
    print("Checking app health...")
    r = requests.get(f"{BASE_URL}/health", timeout=5)
    print(f"  -> {r.status_code} {r.json()}")
    return r.status_code == 200


def test_deep_research() -> bool:
    """Hit the deep-research endpoint with a simple query."""
    print(f"\nPOST {DEEP_RESEARCH_URL}")
    print('  Body: {"query": "What is 2+2?"}')
    
    try:
        r = requests.post(
            DEEP_RESEARCH_URL,
            headers=_headers(),
            json={"query": "What is 2+2?"},
            timeout=120,
        )
        print(f"  -> {r.status_code}")
        
        if r.status_code in (401, 403):
            print("  ❌ Auth failed. Check HARNESS_API_KEY.")
            return False
            
        if r.status_code == 200:
            data = r.json()
            print("  ✅ Success!")
            print(f"     Thread ID : {data.get('thread_id')}")
            print(f"     Answer    : {data.get('answer', 'N/A')[:200]}")
            if data.get("error"):
                print(f"     ⚠️  Error   : {data['error']}")
            return True
        else:
            print(f"  ❌ Failed: {r.text[:500]}")
            return False
            
    except requests.exceptions.ConnectionError:
        print(f"  ❌ Cannot connect to {BASE_URL}. Is the harness running?")
        return False
    except Exception as e:
        print(f"  ❌ Unexpected error: {e}")
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 55)
    print("  Deep Research Integration Test")
    print("=" * 55)
    
    if not test_health():
        print("\nApp is not reachable. Aborting.")
        sys.exit(1)
        
    success = test_deep_research()
    print("\n" + ("=" * 55))
    print(f"  Result: {'PASSED' if success else 'FAILED'}")
    print("=" * 55)
    sys.exit(0 if success else 1)

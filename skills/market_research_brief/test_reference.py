#!/usr/bin/env python3
"""Tests for reference.py's merge + write-guard logic (Tier 1 proposals
pinned-reference-values + reference-json-overwrite-guard, applied 2026-11-23).

Stdlib only (the skill is stdlib-only). No network, no LLM — pure
functions on in-memory payloads + temp-file writes.

Run: python3 -m unittest test_reference -v   (from this directory)
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

import reference as ref


def _valid_reference(market="smarthome_homesecurity") -> dict:
    """A minimal payload that passes the write guard."""
    return {
        "market": market,
        "title": "Smart Home & Home Security",
        "built_at": "2026-11-23",
        "stale_after_days": 365,
        "market_size": [
            {"estimate_usd_b": 75.0, "year": 2025, "cagr_pct": 10.0,
             "horizon_year": 2030, "scope": "global", "source": "Mordor",
             "url": "https://example.com/a", "note": "free summary"},
        ],
        "market_context": ["driver bullet (per Mordor, https://example.com/a)"],
        "share_indicators": [
            {"competitor": "Ring", "type": "revenue", "value": "$1B FY2025",
             "pct": None, "as_of": "2025", "source": "SEC", "url": "u",
             "note": "scope"},
        ],
        "competitors": [
            {"name": "Ring", "segment": "video doorbells", "note": "",
             "facts": {}, "ratings": {}, "review_data": []},
        ],
    }


class TestMergeMarketSize(unittest.TestCase):
    def test_empty_new_keeps_prior(self):
        old = [{"estimate_usd_b": 75.0, "year": 2025, "source": "Mordor"}]
        self.assertEqual(ref._merge_market_size(old, []), old)
        self.assertEqual(ref._merge_market_size(old, None), old)
        # non-numeric fresh entries count as "no usable estimates"
        self.assertEqual(ref._merge_market_size(old, [{"estimate_usd_b": None}]), old)

    def test_pinned_prior_wins_over_fresh(self):
        old = [{"estimate_usd_b": 75.0, "year": 2025, "source": "Mordor", "pinned": True}]
        new = [{"estimate_usd_b": 99.9, "year": 2025, "source": "Mordor"}]
        merged = ref._merge_market_size(old, new)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["estimate_usd_b"], 75.0)
        self.assertTrue(merged[0]["pinned"])

    def test_unpinned_prior_updated_by_fresh(self):
        old = [{"estimate_usd_b": 75.0, "year": 2025, "source": "Mordor"}]
        new = [{"estimate_usd_b": 80.0, "year": 2025, "source": "Mordor"}]
        merged = ref._merge_market_size(old, new)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["estimate_usd_b"], 80.0)

    def test_new_source_appended_order_preserved(self):
        old = [{"estimate_usd_b": 75.0, "year": 2025, "source": "Mordor"},
               {"estimate_usd_b": 56.0, "year": 2025, "source": "Emergen"}]
        new = [{"estimate_usd_b": 80.0, "year": 2025, "source": "Mordor"},
               {"estimate_usd_b": 150.0, "year": 2026, "source": "Statista"}]
        merged = ref._merge_market_size(old, new)
        self.assertEqual([m["source"] for m in merged], ["Mordor", "Emergen", "Statista"])
        self.assertEqual(merged[0]["estimate_usd_b"], 80.0)

    def test_key_is_source_and_year(self):
        # Same publisher, different base year = different estimate.
        old = [{"estimate_usd_b": 75.0, "year": 2025, "source": "Mordor"}]
        new = [{"estimate_usd_b": 90.0, "year": 2026, "source": "Mordor"}]
        merged = ref._merge_market_size(old, new)
        self.assertEqual(len(merged), 2)
        # Source matching is case-insensitive / whitespace-insensitive.
        self.assertEqual(
            ref._market_size_key({"source": " Mordor ", "year": 2025}),
            ref._market_size_key({"source": "MORDOR", "year": 2025}),
        )

    def test_fresh_entry_without_number_never_written(self):
        old = [{"estimate_usd_b": 75.0, "year": 2025, "source": "Mordor"}]
        new = [{"estimate_usd_b": None, "year": 2025, "source": "Mordor"},
               {"estimate_usd_b": 90.0, "year": 2026, "source": "NewCo"}]
        merged = ref._merge_market_size(old, new)
        self.assertEqual([m["source"] for m in merged], ["Mordor", "NewCo"])
        self.assertEqual(merged[0]["estimate_usd_b"], 75.0)

    def test_both_empty(self):
        self.assertEqual(ref._merge_market_size([], []), [])


class TestMergeMarketContext(unittest.TestCase):
    def test_empty_new_keeps_prior(self):
        old = ["bullet a", "bullet b"]
        self.assertEqual(ref._merge_market_context(old, []), old)
        self.assertEqual(ref._merge_market_context(old, ["", "  "]), old)

    def test_fresh_replaces(self):
        self.assertEqual(ref._merge_market_context(["old"], ["new"]), ["new"])

    def test_both_empty(self):
        self.assertEqual(ref._merge_market_context([], []), [])


class TestValidateReferencePayload(unittest.TestCase):
    def test_valid_payload_passes(self):
        ref.validate_reference_payload("smarthome_homesecurity", _valid_reference())

    def test_extra_keys_allowed(self):
        payload = _valid_reference()
        payload["sources"] = [{"url": "https://example.com"}]
        ref.validate_reference_payload("smarthome_homesecurity", payload)

    def test_profile_block_rejected_with_hint(self):
        profile_block = {
            "title": "Smart Home & Home Security",
            "segments": [{"label": "video doorbells", "competitors": ["Ring"]}],
            "reference": {"aspects": [{"id": "price", "label": "Price", "type": "usd"}]},
        }
        with self.assertRaises(ref.ReferencePayloadError) as ctx:
            ref.validate_reference_payload("smarthome_homesecurity", profile_block)
        self.assertIn("PROFILE block", str(ctx.exception))
        self.assertIn("competitors", str(ctx.exception))

    def test_missing_keys_rejected(self):
        payload = _valid_reference()
        del payload["market_size"]
        with self.assertRaises(ref.ReferencePayloadError) as ctx:
            ref.validate_reference_payload("smarthome_homesecurity", payload)
        self.assertIn("market_size", str(ctx.exception))

    def test_market_mismatch_rejected(self):
        with self.assertRaises(ref.ReferencePayloadError) as ctx:
            ref.validate_reference_payload("ecommerce_platforms", _valid_reference())
        self.assertIn("mismatch", str(ctx.exception))

    def test_non_dict_rejected(self):
        with self.assertRaises(ref.ReferencePayloadError):
            ref.validate_reference_payload("smarthome_homesecurity", ["not", "a", "dict"])

    def test_competitor_without_name_rejected(self):
        payload = _valid_reference()
        payload["competitors"] = [{"facts": {}}]
        with self.assertRaises(ref.ReferencePayloadError) as ctx:
            ref.validate_reference_payload("smarthome_homesecurity", payload)
        self.assertIn("competitors[0]", str(ctx.exception))

    def test_competitors_not_a_list_rejected(self):
        payload = _valid_reference()
        payload["competitors"] = {"name": "Ring"}
        with self.assertRaises(ref.ReferencePayloadError):
            ref.validate_reference_payload("smarthome_homesecurity", payload)


class TestSaveReference(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "smarthome_homesecurity.json"
        self.market = "smarthome_homesecurity"

    def tearDown(self):
        self._tmp.cleanup()

    def test_refuses_bad_payload_file_untouched(self):
        self.path.write_text('{"previously": "verified"}\n', encoding="utf-8")
        with self.assertRaises(ref.ReferencePayloadError):
            ref._save_reference(self.path, self.market,
                                {"title": "x", "segments": [], "reference": {}})
        self.assertEqual(json.loads(self.path.read_text()), {"previously": "verified"})
        # no temp file left behind
        self.assertFalse(list(self.path.parent.glob("*.tmp")))

    def test_writes_valid_payload_atomically(self):
        ref._save_reference(self.path, self.market, _valid_reference())
        data = json.loads(self.path.read_text())
        self.assertEqual(data["market"], self.market)
        self.assertEqual(len(data["competitors"]), 1)
        self.assertFalse(list(self.path.parent.glob("*.tmp")))


if __name__ == "__main__":
    unittest.main(verbosity=2)

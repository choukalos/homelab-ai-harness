# Guard reference JSON writes against profile-block payloads

- slug: reference-json-overwrite-guard
- date: 2026-11-22
- status: applied (2026-11-23) — `reference.py`: `validate_reference_payload`
  (required top-level keys + explicit profile-block detection) + `_save_reference`
  (single write path, atomic temp-file rename) on all three write paths
  (`build_reference`, `retry_competitors`, `retry_market`); tests in
  `test_reference.py`. (skill.py only reads the reference JSON — no change needed.)
- target user: chuck

## What
Add a pre-write check in the reference JSON write path that rejects payloads lacking the expected top-level competitors key and aborts before writing if the payload appears to be a profile/reference block instead of stored reference data.

## Why (evidence)
The session shows a script overwrote the reference JSON with the profile block returned by load_profile, causing a KeyError on competitors and requiring a rebuild.

Evidence refs:
- session:2026-10-13T19-54-31-925Z_01a136d4-b473-7320-b0d9-073b173b7377.part2

## Risk + rollback
Low risk; rollback by removing the guard. It may block legitimate schema changes, so update the expected-keys check when the reference schema changes.

## Files touched
- skill.py
- reference.py

---
_Proposed by the weekly harness_reflection run (Tier 1, propose-only). Review with `cli/proposals.sh`; applying is a human decision (Tier 2)._

# Add regression test for publish_file subdirectory enum

- slug: publish-file-subdirectory-enum-test
- date: 2026-11-08
- status: applied
- reviewed: 2026-11-13 — accepted + applied. Landed as
  skills/publish_file/test_skill.py (repo test convention — alongside the
  publish-file-dedup tests; 41 checks, all green): SUBDIRS ==
  (ai, images, audio, video, tabs); 'files' rejected with the
  /files/files/... explanation; 'tabs' + every valid subdirectory accepted;
  invalid subdirectories rejected with the valid set listed; skill.yml's
  documented enum asserted equal to the code enum (guards the 2026-11-06
  bd2d2f3 drift). Test path differs from the proposal (tests/
  test_subdirectory_enum.py → test_skill.py) to match the memory_review /
  harness_reflection convention.
- target user: chuck

## What
Add a test that asserts the publish_file subdirectory enum excludes invalid 'files' and includes 'tabs', and update the skill docs to list the valid subdirectories.

## Why (evidence)
Git commit bd2d2f32d502 fixed an invalid subdirectory enum, showing a gap in validation.

Evidence refs:
- git:bd2d2f32d502

## Risk + rollback
Low; test-only and docs-only change, rollback by reverting the commit.

## Files touched
- skills/publish_file/SKILL.md
- skills/publish_file/tests/test_subdirectory_enum.py

---
_Proposed by the weekly harness_reflection run (Tier 1, propose-only). Review with `cli/proposals.sh`; applying is a human decision (Tier 2)._

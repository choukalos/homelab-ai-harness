# Add regression test for publish_file subdirectory enum

- slug: publish-file-subdirectory-enum-test
- date: 2026-11-08
- status: open
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

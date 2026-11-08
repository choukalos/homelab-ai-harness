# Deduplicate repeated publish_file requests

- slug: publish-file-dedup
- date: 2026-11-08
- status: open
- target user: chuck

## What
In the publish_file skill, compute a stable content/path hash or job intent key and return the existing completed publish job instead of creating a new one when the same file is published repeatedly within a short window.

## Why (evidence)
24 publish_file jobs completed during the week, including repeated groups in the same minute.

Evidence refs:
- job:abbba7d985b2
- job:e1573004cd89
- job:51dc49413e4a
- job:5b847b01aa86
- job:1d0197894ca4
- job:311d6195e5df
- job:d93b04e8aa69
- job:e13b811fd3cc
- job:c439c404112a
- job:5774c444feb7
- job:36c9973a2b8b
- job:d56c9922d8ce
- job:381ff8b4b5b3
- job:afa68a4a81d8
- job:87b75ff6beb6
- job:1758a0c3949d
- job:4657cab2e3c0
- job:44a9a10b0352
- job:15d956768cf4
- job:ddb986c07053
- job:41e5134e3ffd
- job:90291bd54f0d
- job:6afe60075c45
- job:2e1de4635f54

## Risk + rollback
Risk: dedup could hide a legitimate republish if content changed. Rollback: disable dedup or require an explicit force flag.

## Files touched
- skills/publish_file/SKILL.md

---
_Proposed by the weekly harness_reflection run (Tier 1, propose-only). Review with `cli/proposals.sh`; applying is a human decision (Tier 2)._

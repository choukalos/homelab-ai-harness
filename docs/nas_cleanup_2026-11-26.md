# NAS media-store cleanup report — 2026-11-26

**Task:** pi-long-task TODO 2 (decision 4-published): inventory
`/mnt/lego-media-store`, conservatively clean up prior-convention
artifacts, create the `/mnt/lego-media-store/published/` publish root.
**Policy:** inventory first; delete only clearly test/transient items;
board-tracked deliverables and anything ambiguous are LEFT in place and
flagged. No board-tracked or ambiguous item was deleted.

## 1. Mount

| | |
|---|---|
| Local path | `/mnt/lego-media-store` |
| Remote | `//lego.local/workspace` (lego.local, 192.168.5.100) |
| Protocol | CIFS 2.1 via autofs (`_netdev`, `soft`) |
| Identity | `username=backup`, `uid=1000`/`gid=1000` (chuck), `file_mode=0755`, `dir_mode=0755` |
| Capacity (2026-11-26) | 39T total, 19T used (49%), 21T avail |

## 2. Full inventory (2026-11-26)

36 items total (2 top-level entries). Full listing:

| Path | Type | Size | Date | Classification |
|---|---|---|---|---|
| `@Recently-Snapshot/` | dir (read-only, Windows system) | 4.0K | Nov 22 00:21 | (b) transient system artifact — DELETE attempted, blocked (see §4) |
| `@Recently-Snapshot/desktop.ini` | file | 102 B | Nov 22 00:21 | (b) transient system artifact — DELETE attempted, blocked (see §4) |
| `potato-wars-v2/` | dir | 100M | Nov 26 04:11 | (a) board-tracked deliverable — LEAVE |
| `potato-wars-v2/b1/` | dir | — | Nov 23 01:56 | (a) LEAVE |
| `potato-wars-v2/b1/potato-wars-v2b.mp4` | file | 2,526,307 B | Nov 23 02:00 | (a) LEAVE |
| `potato-wars-v2/b1/state.json` | file | 30,215 B | Nov 23 02:00 | (a) LEAVE |
| `potato-wars-v2/b2/` | dir | — | Nov 23 01:41 | (a) LEAVE |
| `potato-wars-v2/b2/Potato_Wars_Revenge_Of_The_Banana_v2b_draft.mp4` | file | 12,565,341 B | Nov 23 01:41 | (a) LEAVE |
| `potato-wars-v2/b2/state.json` | file | 73,180 B | Nov 23 01:26 | (a) LEAVE |
| `potato-wars-v2/c1/` | dir | — | Nov 24 14:14 | (a) LEAVE |
| `potato-wars-v2/c1/potato-wars-v2.mp4` | file | 14,901,522 B | Nov 24 14:25 | (a) LEAVE |
| `potato-wars-v2/c1/state.json` | file | 133,412 B | Nov 24 14:16 | (a) LEAVE |
| `potato-wars-v2/c1/draft-state.json` | file | 92,006 B | Nov 24 03:05 | (a) LEAVE |
| `potato-wars-v2/c1/GATE_REPORT.md` | file | 5,170 B | Nov 24 02:58 | (a) LEAVE |
| `potato-wars-v2/c1/qc-report.md` | file | 4,321 B | Nov 24 14:14 | (a) LEAVE |
| `potato-wars-v2/c1-draft/` | dir | — | Nov 24 02:58 | (a) LEAVE |
| `potato-wars-v2/c1-draft/potato-wars-v2-draft.mp4` | file | 14,557,300 B | Nov 23 05:15 | (a) LEAVE |
| `potato-wars-v2/c1-draft/state.json` | file | 92,006 B | Nov 24 02:58 | (a) LEAVE |
| `potato-wars-v2/c1-draft/REVIEW_PACK.md` | file | 8,686 B | Nov 24 03:05 | (a) LEAVE |
| `potato-wars-v2/c2/` | dir | — | Nov 26 02:28 | (a) LEAVE |
| `potato-wars-v2/c2/vegetables-strike-back-v2.mp4` | file | 18,424,018 B | Nov 26 02:28 | (a) LEAVE |
| `potato-wars-v2/c2/state_prod.json` | file | 199,434 B | Nov 25 06:01 | (a) LEAVE |
| `potato-wars-v2/c2/qc-report.md` | file | 8,579 B | Nov 25 06:00 | (a) LEAVE |
| `potato-wars-v2/c2-draft/` | dir | — | Nov 24 02:58 | (a) LEAVE |
| `potato-wars-v2/c2-draft/vegetables-strike-back-v2-draft.mp4` | file | 5,542,410 B | Nov 23 06:01 | (a) LEAVE |
| `potato-wars-v2/c2-draft/state.json` | file | 40,889 B | Nov 24 02:51 | (a) LEAVE |
| `potato-wars-v2/c3/` | dir | — | Nov 25 23:43 | (a) LEAVE |
| `potato-wars-v2/c3/revenge-of-the-potato-v2.mp4` | file | 24,078,755 B | Nov 25 23:42 | (a) LEAVE |
| `potato-wars-v2/c3/state.json` | file | 219,130 B | Nov 25 23:43 | (a) LEAVE |
| `potato-wars-v2/c3/qc-report.md` | file | 5,342 B | Nov 25 23:43 | (a) LEAVE |
| `potato-wars-v2/c3-draft/` | dir | — | Nov 24 02:58 | (a) LEAVE |
| `potato-wars-v2/c3-draft/revenge-of-the-potato-v2-draft.mp4` | file | 11,132,700 B | Nov 23 13:16 | (a) LEAVE |
| `potato-wars-v2/c3-draft/state.json` | file | 78,816 B | Nov 24 02:58 | (a) LEAVE |
| `potato-wars-v2/c3-draft/REVIEW_PACK.md` | file | 8,383 B | Nov 23 13:16 | (a) LEAVE |
| `potato-wars-v2/comparison/` | dir | — | Nov 26 04:11 | (a) LEAVE |
| `potato-wars-v2/comparison/COMPARISON.md` | file | 49,929 B | Nov 26 04:22 | (a) LEAVE |

**Finding:** the store contains NO prior-convention publish artifacts
beyond the `potato-wars-v2` board-tracked tree and the Windows system
folder. There were no stray files, no old publish roots, and no other
test/transient items to clean up.

## 3. Classification rationale

- **(a) Board-tracked deliverable — `potato-wars-v2/` (34 items, 100M):**
  explicitly board-tracked (long-task key pointers: "potato-wars-v2 is
  board-tracked — DO NOT DELETE"). Contains the full project tree: b1/b2
  early drafts, c1/c2/c3 production renders with `qc-report.md` +
  `state*.json`, c*-draft review packs, and `comparison/COMPARISON.md`.
  The `-draft` subdirs are part of the tracked review workflow (they
  carry `REVIEW_PACK.md` / `state.json`), not transient scratch — LEFT
  in place with the rest of the tree.
- **(b) Test/transient — `@Recently-Snapshot/` (2 items, 102 B):**
  a Windows Explorer system folder auto-created when the share was
  browsed from a Windows machine (read-only `dr-xr-xr-x`, contains only
  a 102 B `desktop.ini`). No data value, not a deliverable,
  auto-recreated by Windows on the next browse. Classified clearly
  transient → deletion attempted.
- **(c) Ambiguous:** none.

## 4. Deletion attempt (transient items)

Attempted on 2026-11-26 from thor:

```
chmod u+w '/mnt/lego-media-store/@Recently-Snapshot'   # (no-op / refused by CIFS)
rm -f  '/mnt/lego-media-store/@Recently-Snapshot/desktop.ini'
# rm: cannot remove '@Recently-Snapshot/desktop.ini': Permission denied
rmdir '/mnt/lego-media-store/@Recently-Snapshot'
# rmdir: failed to remove '@Recently-Snapshot': Permission denied
```

**Result: deletion blocked** — the CIFS share enforces the Windows
read-only attribute; thor (uid 1000 via the `backup` account) cannot
remove it. **LEFT IN PLACE and flagged.** It is 102 bytes of Windows
system metadata with no data value; it will reappear after any Windows
browse of the share. Optional manual cleanup from the NAS admin UI or a
Windows client (where the attribute is writable) if desired — not
required.

**Nothing else was deleted. No board-tracked or ambiguous item was
touched.**

## 5. `published/` publish root (decision 4-published)

Created 2026-11-26:

```
mkdir -p /mnt/lego-media-store/published && chmod 755 /mnt/lego-media-store/published
```

Verification:

```
$ stat -c '%U %G %a %n' /mnt/lego-media-store/published
chuck chuck 755 /mnt/lego-media-store/published
$ touch /mnt/lego-media-store/published/.writetest && rm ...   # write+delete OK
```

- Owner/group: `chuck:chuck` (uid/gid 1000 via the CIFS `forceuid`/`forcegid` mapping)
- Mode: `755`
- Writable from thor: verified (create + delete round-trip)
- This is the P12-C `nas` publish target root
  (`publish_targets.nas.root: /mnt/lego-media-store/published/` in the
  filebridge registry, `docs/filebridge_p12bc.md` §3/§5).

## 6. Post-cleanup state

```
/mnt/lego-media-store/
├── @Recently-Snapshot/      (102 B, Windows system, read-only — FLAGGED, left)
├── potato-wars-v2/          (100M, 34 items — board-tracked, untouched)
└── published/               (new, chuck:chuck 755, empty, writable)
```

Integrity check: `potato-wars-v2` still contains all 33 items under its
root (34 counting the root dir) and 100M — identical to the pre-cleanup
inventory.

## 7. Summary

| Action | Items | Outcome |
|---|---|---|
| Inventoried | 36 items (2 top-level) | full table in §2 |
| Left (board-tracked) | `potato-wars-v2/**` (34 items, 100M) | untouched, verified intact |
| Left (flagged) | `@Recently-Snapshot/` + `desktop.ini` (102 B) | deletion blocked (CIFS read-only); no data value; auto-recreated by Windows |
| Deleted | — | none (no other transient artifacts existed) |
| Created | `published/` | chuck:chuck 755, writable — P12-C nas publish root |

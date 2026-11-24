# Ship user-facing docs for TipCalc (README + docs/ on tipcalc task/9) + record via proposal lifecycle

- slug: tier2-tipcalc-ship-docs
- date: 2026-11-23
- status: applied
- applied: 2026-11-23 (tipcalc task/9) — user-facing docs shipped + verified
  (evidence below). The tipcalc E2E test project was torn down 2026-11-24
  (commits c5f989e/6fec099 — compose stack removed; test.choukalos.com reserved
  for future public-facing tests).
- tier: 2
- target user: chuck

> **Reconstructed 2026-11-24 during docs housekeeping.** The original proposal
> file was never committed — only the DB row survived (`tier2-tipcalc-ship-docs`,
> created 2026-11-24 01:09 UTC, reviewed 01:09 UTC, status applied). This file
> mirrors the DB row (title, evidence, target files) so the two places agree
> again.

## Evidence (from the DB row)

- tipcalc task/9 commit 8c16175: README.md + docs/usage.md + docs/api.md + docs/deploy.md
- npm test 40/40 pass on tipcalc task/9 (incl. readme.test.js)
- live spot-check of local run (:8099, temp DB) matched docs/api.md (endpoints, error codes, tax/tip_base math)
- test.choukalos.com still placeholder (mode: placeholder) at 2026-11-23 — docs code-based and say so
- ship-docs checklist (G6) complete: 1 README updated, 2 API/ops docs updated, 3 user-facing surface described by docs/usage.md (live surface still placeholder, re-verify post-deploy), 4 project constraints N/A (docs-only, no gate/behavior change), 5 proposals/README.md Current state refreshed + dated

## Target files (from the DB row)

- `tipcalc:README.md`
- `tipcalc:docs/usage.md`
- `tipcalc:docs/api.md`
- `tipcalc:docs/deploy.md`
- `homelab:proposals/2026-11-23-tier2-tipcalc-ship-docs.md` (this file)
- `homelab:proposals/README.md`

# Market Research Skill — Annual Reference Data & Comparison (TODO / Plan)

Status: **bootstrap complete — awaiting review** (2026-10-13)
Owner: chuck · Skill: `skills/market_research_brief/`

**Review artifacts:**
- Published sample page: https://choukalos.com/files/briefs/market_research/smarthome_homesecurity_reference.html
  (drop-zone copy: `data/media/public/briefs/market_research/smarthome_homesecurity_reference.html`;
  source artifact: `data/media/market_research_briefs/reference_smarthome_homesecurity_2026-10-13T21-39-40.html`)
- Editable reference: `skills/market_research_brief/references/smarthome_homesecurity.json`
  (hand-editable; `python3 reference.py --market smarthome_homesecurity --render-only` re-renders)

## 1. Goal

The monthly market research brief is good on *news*, but weak on *context*. Add
two **annual-reference** artifacts (updated ~once/year, embedded in every
monthly brief, fully present in the yearly summary):

1. **Market context** — market size (multiple independent free estimates,
   shown as a range), growth (CAGRs), and per-competitor **size/share
   indicators** (revenue for public companies; clearly-labeled
   survey-share / PR-cited / install-base proxies for private ones).
2. **Competitor comparison** — a comparison table of all competitors on the
   market's **key aspects** (per-market, e.g. home security: kit cost,
   monthly monitoring, sensors, AI features, cellular backup, emergency
   response, …) plus **LLM rubric ratings** (1–5) per aspect, with free
   review-site scores shown where available from a selected set of sites.

Both are rendered as **charts/tables** (bar charts + heatmap-style rating
table), self-contained HTML (no JS/CDN), mobile-friendly, dark-mode aware.

## 2. Design decisions (agreed with chuck, 2026-10-13)

| # | Decision |
|---|---|
| 1 | Monthly brief gets a **compact** comparison table + market-share bar chart (static, cheap to include). Yearly summary gets the **full** detail table, ratings, and a **year-over-year diff** (price/share changes). |
| 2 | Ratings = **pure LLM rubric scores** (consistent across competitors/markets), 1–5 per aspect, with one-line rationale. Free review-site scores (PCMag, CNET, SafeHome.org, TechRadar — selected set) are shown **additionally** where available, never used to compute the rubric score. |
| 3 | Aspect set is **per-market** (defined in the profile). Home security set = base set + cellular backup, emergency/police response, family tracking / SOS-help, camera types (indoor/outdoor/wireless/doorbell), camera resolution, advanced AI (person/familiar-person detection, etc.). |
| 4 | Private companies get **proxy share indicators** (survey share, PR-cited estimates, install base, traffic) via a **consistent mechanism**: every indicator carries `type` (revenue / survey_share / pr_estimate / install_base / other) + source + as-of date, and the report states the type explicitly. |
| 5 | Reference is **rebuilt on the January run** (alongside the yearly summary) + **bootstrapped now** for review/tweak. |
| 6 | Second market for validation: **ecommerce platforms** (Shopify, BigCommerce, Adobe Commerce/Magento, WooCommerce, PrestaShop, …) — different aspect set proves the per-market design. |
| 7 | Bootstrap now so chuck can review/tweak the reference data before the engine integration. |

## 3. Free sources catalog (all verified reachable 2026-10-13)

### 3.1 Market size & growth (annual, stable)
- **Research-firm free summary pages** (each publishes size + CAGR + forecast
  on a free page; full report paywalled — figures from free page summary,
  always flagged): Fortune Business Insights, MarketsandMarkets, Mordor
  Intelligence, Grand View Research, Precedence Research, Straits Research,
  Dataintelo, Business Research Company.
  → Collect **2–4 independent estimates** per market; present as a range with
  per-estimate source + CAGR + horizon year. Note the spread explicitly.
- **Analyst free coverage**: Parks Associates "State of the Connected Home"
  (free blog/PR), Gartner/IDC free press releases.
- **Government anchors**: US Census / BLS retail categories (coarse but
  authoritative).
- ⚠️ **Statista free pages mask numbers** (`US$***bn`) — cite only, never
  extract.

### 3.2 Competitor size / share indicators
- **Public companies → hard revenue** (free): SEC EDGAR
  (`data.sec.gov/submissions/CIK….json` + full-text search, no key needed —
  verified on Arlo), company IR press releases (Arlo, Shopify 6-K, Adobe,
  Comcast, Alphabet), HKEX for Anker.
- **Private companies → proxies** (consistent mechanism, labeled by type):
  - `survey_share` — SafeHome.org annual industry report (free; 2026 report
    verified: 74.9M US camera households, top brands, feature popularity),
    Parks Associates free coverage, PCMag reader surveys.
  - `pr_estimate` — company PRs citing share (e.g. ADT June 2026 PR:
    ~9.5% US share, ~$57.8B US market — free on PR Newswire).
  - `install_base` — W3Techs usage stats (free, monthly; verified for
    ecommerce platforms), WordPress.org plugin stats.
  - `other` — app-store rankings, SimilarWeb free tier (weak, last resort).

### 3.3 Comparison facts (pricing, features, sensors, …)
- **Vendor pricing/product pages** — authoritative for price & feature set.
  Crawlable via `mcp_crawl` `crawl_page` (full page → markdown, 50k chars;
  verified). Caveats: consent-banner boilerplate, some JS-rendered pages,
  quote-based pricing (ADT/Brinks publish no prices → use comparison sites,
  marked `estimated`).
- **Cross-brand comparison sites** (free, refreshed regularly): SafeHome.org
  "Best Home Security Systems", Security.org, findprices.com (2026
  kit+monitoring price comparison verified), PCMag/CNET "best of" roundups.
- **Extraction**: crawl 1 vendor page + 1–2 comparison pages + 1–2 review
  pages per market → LLM extracts into the strict per-market schema (below)
  → every field carries `source` + `url` + `as_of`.

### 3.4 Ratings
- **LLM rubric** (primary): 1–5 per rating aspect, same rubric applied to
  every competitor, one-line rationale, based only on the crawled material.
- **Review-site scores** (supplementary, selected set): PCMag, CNET,
  SafeHome.org, TechRadar. Shown as "PCMag 4.0/5 (link)" next to the rubric
  score; never averaged into it.

## 4. Architecture

### 4.1 Profile extension (`profiles/<market>.yml`)

Add a `reference:` block (per-market; the aspect set is what flexes):

```yaml
reference:
  stale_after_days: 365          # monthly run warns if older; Jan run rebuilds
  aspects:                       # ordered; type: usd | bool | list | text
    - {id: kit_cost,        label: "Initial kit cost",          type: usd}
    - {id: kit_includes,    label: "Starter kit includes",      type: text}
    - {id: monthly_monitoring, label: "Monthly pro monitoring", type: usd}
    - {id: self_monitoring, label: "Self-monitoring option",    type: bool}
    - {id: cloud_storage,   label: "Cloud storage / recording", type: text}
    - {id: cellular_backup, label: "Cellular backup",           type: bool}
    - {id: emergency_response, label: "Police/fire/medical dispatch", type: bool}
    - {id: family_tracking, label: "Family tracking / SOS help", type: text}
    - {id: camera_types,    label: "Camera types",              type: list}
    - {id: camera_resolution, label: "Camera resolution",       type: text}
    - {id: ai_features,     label: "Advanced AI",               type: list}
    - {id: sensors,         label: "Supported sensors",         type: list}
    - {id: hub,             label: "Hub / base station",        type: text}
    - {id: integrations,    label: "Ecosystem integrations",    type: list}
    - {id: pro_install,     label: "Pro installation",          type: bool}
    - {id: contract,        label: "Contract terms",            type: text}
    - {id: warranty,        label: "Warranty",                  type: text}
  rating_aspects:                # LLM rubric, 1–5 each
    - {id: value,     label: "Value"}
    - {id: features,  label: "Features"}
    - {id: ecosystem, label: "Ecosystem"}
    - {id: support,   label: "Monitoring & support"}
  review_sites: [PCMag, CNET, SafeHome.org, TechRadar]
  sources:                       # crawl list for the reference build
    - {url: https://www.simplisafe.com/pricing,      competitors: [SimpliSafe]}
    - {url: https://www.safehome.org/resources/best-home-security-systems/,
       competitors: [all]}
    ...
  share_indicators:
    - {competitor: Arlo,     type: revenue,     source: "Arlo IR FY press release"}
    - {competitor: ADT,      type: pr_estimate, source: "ADT PR (PR Newswire)"}
    - {competitor: Ring,     type: survey_share, source: "SafeHome.org annual"}
  market_size_queries:           # in addition to profile market_size_queries
    - "home security systems market size"
    - "smart home market size"
```

### 4.2 Reference data file (`references/<market>.json`, git-tracked)

Living, human-editable, diffable. Schema (one entry per competitor):

```json
{
  "market": "smarthome_homesecurity",
  "built_at": "2026-10-13",
  "market_size": [
    {"estimate_usd_b": 72.4, "year": 2025, "cagr_pct": 8.6, "horizon_year": 2030,
     "scope": "global home security systems", "source": "MarketsandMarkets",
     "url": "...", "note": "free page summary; full report paywalled"}
  ],
  "market_context": ["2–4 sourced bullets: growth drivers, regional notes"],
  "share_indicators": [
    {"competitor": "Arlo", "type": "revenue", "value": "$XXX M FY2025",
     "as_of": "FY2025", "source": "Arlo IR", "url": "...", "note": ""}
  ],
  "competitors": [
    {
      "name": "Ring", "segment": "Home Security",
      "facts": {
        "kit_cost": {"value": 249, "display": "$249 (starter kit)",
                     "source": "ring.com", "url": "...", "as_of": "2026-10"}
      },
      "ratings": {
        "value": {"score": 4, "rationale": "…"}
      },
      "review_data": [
        {"site": "PCMag", "score": "4.0/5", "url": "...", "as_of": "2026-09"}
      ]
    }
  ]
}
```

Location: `skills/market_research_brief/references/<market>.json` — in the
repo (git) so chuck can review/tweak and the yearly diff is a plain
`git diff` / JSON diff.

### 4.3 Build pipeline (`reference.py`, new module)

```
python3 reference.py --market smarthome_homesecurity [--force]
```

1. Load profile + `reference:` block. Skip if a fresh reference exists
   (`built_at` within `stale_after_days`) unless `--force`.
2. **Crawl phase** — `mcp_crawl` `crawl_page` for each source URL (parallel,
   deadline-bounded, per-page failure non-fatal → competitor keeps prior
   value, flagged `stale`).
3. **Extraction phase** — one LLM call per competitor (matrix-coder):
   context = vendor page + comparison excerpts + review excerpts; output =
   strict JSON for that competitor's facts + rubric ratings + review_data.
   Rubric prompt: same scale/definitions for every competitor; score from
   material only; rationale ≤ 20 words.
4. **Market phase** — `search_web` for `market_size_queries` + share-indicator
   sources; one LLM call consolidates into `market_size[]` +
   `market_context[]` + `share_indicators[]` (each with source/url/type).
5. **Merge & save** — merge into existing JSON (stale fields carry forward
   with `stale: true`), write `references/<market>.json`, log a per-field
   change summary.

Runtime: ~14–16 crawls + ~12 LLM calls ≈ 3–6 min → its own budget
(`MARKET_RESEARCH_REFERENCE_MAX_RUNTIME`, default 900s).

### 4.4 Monthly brief integration (skill.py)

- New optional param `build_reference` (default false). When true (January
  run), the build runs first; effective max runtime = max(configured, 1500s).
  Build failure is non-fatal → brief proceeds with the existing reference.
- **Every** run: load `references/<market>.json`; if missing → section
  omitted (today's behavior). If older than `stale_after_days` → one-line
  "reference data last updated YYYY-MM" note.
- New section after Market Size & Share:

  ```
  ## Competitor Comparison (annual reference)
  *Reference data as of 2026-10 · rebuilt yearly · sources cited per field*

  [market-size range line + share bar chart]
  [compact table: competitor × top ~8 aspects + 4 rubric scores]
  [full detail table + ratings heatmap in the HTML render]
  ```

- **Renderer**: `_md_to_html` has **no table support** — the comparison
  section is rendered **deterministically in Python from the JSON** (not
  LLM markdown): exact numbers, no drift, no token cost. New functions in
  `reference.py`: `render_reference_html(ref, profile, mode=compact|full)`
  producing:
  - **Bar chart** (pure HTML/CSS divs, % widths): market share indicators
    (where comparable) + kit-cost comparison.
  - **Comparison table**: scrollable wrapper on mobile; `usd` columns right-
    aligned; `bool` as ✓/–; `list` as compact chips.
  - **Ratings heatmap**: 1–5 cells colored green→red (CSS only), rubric
    score + rationale tooltip (`title=` attr) + review-site scores beneath.
  - Footer: "Reference rebuilt YYYY-MM-DD · free sources only · paywalled
    figures flagged".
- The LLM still writes all narrative sections; the reference section is
  spliced into the HTML after markdown rendering (and into the .md artifact
  as a markdown table for grep-ability).

### 4.5 Yearly summary integration

- Yearly prompt gets the current reference JSON + the prior-year reference
  (if it exists) → new sections:
  - **Market Size & Share — Year Over Year** (already exists; now backed by
    the reference estimates).
  - **Competitor Comparison (updated)** — full table + ratings.
  - **Year-over-Year Changes** — deterministic diff from the two JSONs:
    price changes (kit/monitoring), new/dropped features, share-indicator
    movement, rating deltas. Rendered as a small table.

### 4.6 Publishing

- Monthly: unchanged (latest + dated copies).
- Reference: published as a standalone page
  `briefs/market_research/<slug>_reference.html` (overwritten each build) so
  it can be shared/linked independently of the monthly brief.

## 5. Implementation steps

- [x] 0. Research free sources + verify pipeline (search/crawl/LLM) — done.
- [x] 1. **Bootstrap build** (this turn): `reference.py` + home-security
      `reference:` block + `references/smarthome_homesecurity.json` + sample
      HTML for review. — **BUILT 2026-10-13**: 11/11 competitors (9–14 facts
      each, w/ source URLs + `~` estimate flags), 4 rubric ratings +
      review-site scores each, 4 independent market-size estimates,
      4 labeled share indicators (Ring 43% survey share → bar chart,
      Arlo $330M ARR, ADT $5.0B 2024 rev, Xfinity 36-device proxy).
      Published: `briefs/market_research/smarthome_homesecurity_reference.html`.
- [x] 2. `profiles/ecommerce_platforms.yml` — new profile with its own
      aspect set + sources (validation market). — PROFILE DRAFTED (2026-10-13);
      source URLs to be verified when the ecommerce bootstrap runs.
- [x] 3. `skill.py`: load reference + splice section (monthly),
      `build_reference` param + extended runtime (January), renderer wiring,
      markdown-table fallback in the .md artifact. — DONE (validated
      2026-10-13; import robustness fixed 2026-10-14, see round 3).
- [x] 4. `skill.py`: yearly summary — reference sections + YoY diff. — DONE
      (Phase 7 full reference + deterministic YoY diff from the two JSONs).
- [x] 5. Publishing: standalone reference page; skill.yml/README/agents-
      skills SKILL.md updates. — DONE (standalone page published; skill.yml
      `build_reference` documented; README annual-reference section added
      2026-10-14; agents-skills SKILL.md updated).
- [x] 6. Ecommerce validation: bootstrap the ecommerce reference, run a
      monthly brief with the reference embedded, review both. — DONE
      (sections 9–10; final 16-competitor brief re-validated 2026-10-14
      after the round-3 fixes).
- [x] 7. Scheduler: January n8n run passes `build_reference: true` (or a
      separate n8n job calling the reference build before the brief). — DONE
      (separate `market_research_reference` jobs, Jan 1 07:00/08:00 CT,
      verified live via hot-reload + GET /api/schedule).
- [ ] 8. Git: commit `references/*.json` so yearly diffs are reviewable.

### Lessons learned (bootstrap, 2026-10-13)

- **`.env` vars are not exported** — standalone runs need
  `export LITELLM_API_KEY=$(grep '^LITELLM_API_KEY=' .env | cut -d= -f2)`.
  (Runner/skill.py runs get the env from the skill-runner compose file.)
- **matrix-coder is a reasoning model** — it burns its token budget on
  internal reasoning; extraction calls need `max_tokens=16000` (same as
  skill.py's synthesis), not 3500. With 11 competitors × ~90 s each,
  extraction is parallelized (3 workers) and the default max runtime is
  1800 s (env: `MARKET_RESEARCH_REFERENCE_MAX_RUNTIME`).
- **Vendor pages are often nav/cookie-heavy** — per-brand review-site pages
  (SafeHome.org /security-systems/<brand>/ and /home-security-cameras/<brand>/,
  security.org /home-security-systems/<brand>/) are the reliable fallback;
  the profile's `sources:` list now carries both vendor + review pages per
  brand.
- **Quote-based pricing (ADT/Brinks)** — vendor pages have no prices;
  review-site estimates carry `estimated: true` and render with a `~` marker.
- **Search results are non-deterministic** — share-indicator data can vary
  between runs. Mitigation: `share_indicators` merge by competitor prefers
  the newest non-null entry (`_merge_share_indicators`); `--retry-market`
  re-runs just the market phase. `market_size` is replaced each run (fresh
  estimates preferred).
- **CLI ops** (reference.py): `--force` full rebuild · `--retry Wyze,Eufy`
  re-extract competitors from the crawl cache · `--retry-market` re-run the
  market phase · `--populate-cache` pre-fetch source pages ·
  `--render-only` re-render HTML from the JSON. Crawl cache:
  `references/<market>.crawls.json` (24 h freshness).

### Post-review fixes (2026-10-13, chuck review round 1)

- **CSS was emitted as raw body text** (missing `<style>` tag) — page was
  unstyled + unreadable in dark mode. Fixed: `render_reference_html` now
  wraps `REF_CSS` in `<style>` inside `.ref`; dark-mode overrides completed
  (`.est`, `.na`, `.stale-chip`, `.bar-type`).
- **Xfinity Shield facts corrected** (user-provided): free app w/ Xfinity
  Internet; $10/mo + bring-your-own devices; Xfinity indoor camera $5/mo
  EIP x36mo (≈$15/mo tier w/ camera + sensors). Source: Yahoo Finance
  Comcast announcement (2026-08-19), added to profile sources so the
  January rebuild extracts it correctly.
- **FILES navigation**: portal sends `Cache-Control: no-cache` on directory
  listings, but the Cloudflare edge overrides it (observed `max-age=14400`)
  → new files can lag up to 4 h in folder listings. Workaround: hard
  refresh / query-string bust. Proper fix = CF cache rule for `/files/*`
  (dashboard) or a CF API token for purges (not on disk by design).

### Post-review fixes (2026-10-13, chuck review round 2)

- **Xfinity Home share indicator dropped** — user has internal Comcast data
  (noted in profile). Removed from JSON + profile.
- **Private-company insights added** (like Ring's): SafeHome.org 2026 annual
  industry report (survey of 2,435 U.S. adults) has a full brand-share
  table — Ring 43%, ADT 10%, Google Nest 7%, Wyze 6%, Xfinity 5%,
  SimpliSafe 5%, Eufy 4%, Honeywell 3%, Vivint 3%. Added survey_share
  indicators for **Nest 7%**, **Eufy 4%**, **SimpliSafe 5%** (all pct →
  bar chart). **ADT upgraded to SEC 10-K revenue** ($5.13B FY2025,
  NYSE: ADT, CIK 1703056 — public company; better than 3rd-party estimate).
  SafeHome annual report added to profile sources (survey table ~char 5750,
  inside the 9000-char crawl budget) so the January rebuild re-finds it.
  SimpliSafe/Anker/Eufy confirmed private (no SEC filings — checked
  company_tickers.json + EDGAR).
- **Xfinity Shield row decontaminated** — removed Xfinity-Home-derived facts
  (cellular backup, sensors, hub, 24-month contract, HD resolution);
  $15/mo-tier features (cloud storage, 24/7 urgent response, door/window
  sensors) now attributed to the Comcast announcement, not SafeHome.
- **Vendor-first sources in the matrix** — extraction prompt now mandates
  the competitor's OWN site for facts (review sites only as fallback +
  for review_data scores) and a distinct-products rule (Shield vs Home).
  Added adt.com + brinks.com to sources; re-extracted 10 competitors:
  Ring ring.com×11, ADT adt.com×9, Eufy eufy.com×8, SimpliSafe/Wyze/Blink
  vendor pages used where they carry the data (thin vendor pages fall back
  to SafeHome summaries — approved by user). Fact-level merge on retry
  (`_merge_competitor_entry`) keeps prior non-null facts when a re-extract
  comes back null.

### Post-review fixes (2026-10-14, round 3 — 16-competitor re-run)

The 01:01 UTC re-run of the ecommerce brief (16 competitors) came out
**broken** and exposed two engine bugs:

1. **Reference section silently missing when the engine is loaded via
   importlib** — the wrapper skills (`ecommerce_platforms_brief`,
   `smarthome_homesecurity_brief`) and the skill-runner load the engine
   with `importlib.util.spec_from_file_location`, so the engine dir is NOT
   on `sys.path`; the engine's bare `import reference` then raised
   ImportError, which `_reference_sections` swallowed → no reference
   section in the HTML, no standalone-page refresh in Phase 6. The 23:58
   run had the section only because it was launched from the engine dir
   (CLI). **Fix:** `_ref_module()` in skill.py — tries `import reference`,
   falls back to loading `reference.py` via spec from
   `Path(__file__).parent`; used at all three import sites
   (`_reference_sections`, `build_reference` block, Phase 6 publish).
   Verified: compact render now works from the wrapper context (26.5 KB
   HTML, 16 competitors).
2. **16-competitor synthesis truncated** — matrix-coder burned most of the
   16000-token budget on internal reasoning and the report stopped mid-
   heading at "### Squarespace —" (Wix/Lightspeed/Outlook missing;
   finish_reason=length, non-empty content so the empty-retry never
   fired). **Fix:** `_synthesize` now detects `finish_reason=length` and
   retries once with 2× max_tokens (cap 32768 — the litellm proxy cap for
   matrix-coder), keeping the longer output.
3. **Compact table missing the rubric score columns** — design (§4.4):
   compact = top ~8 aspects + 4 rubric scores; the renderer only added
   the aspects (ratings were full-mode only). **Fix:** `_comparison_table`
   compact mode now appends the `rating_aspects` columns as heat-colored
   score cells (rationale in `title=`), matching the full-mode heatmap
   style. Re-spliced the 01:29 published brief + dated copy + artifact
   with the new render (deterministic, no LLM).

Also: `skills/market_research_brief/README.md` gained the Annual
reference section (reference.py CLI, JSON schema location, integration,
January rebuild).

**Validation (01:29 UTC wrapper re-run, `--publish`):** brief complete
(16/16 competitors in scan + Analyst Watch + Trends & Outlook), compact
reference embedded (8 aspects + 4 rubric scores, 64 heat cells),
standalone reference page refreshed. Published:
https://choukalos.com/files/briefs/ecommerce_platforms_brief.html

## 6. Per-market aspect sets

### 6.1 smarthome_homesecurity (final, per chuck 2026-10-13)

Facts: kit_cost, kit_includes, monthly_monitoring, self_monitoring,
cloud_storage, **cellular_backup**, **emergency_response (police/fire/
medical dispatch)**, **family_tracking (track users on the go / SOS / get
help)**, **camera_types (indoor, outdoor, wireless/battery, doorbell)**,
**camera_resolution**, **ai_features (person detection, familiar people,
package detection, etc.)**, sensors, hub, integrations, pro_install,
contract, warranty.
Ratings: value, features, ecosystem, monitoring & support.

### 6.2 ecommerce_platforms (draft — validation market)

Competitors: Shopify, BigCommerce, Adobe Commerce (Magento), WooCommerce,
PrestaShop (core) + Salesforce Commerce Cloud, Squarespace, Wix, Lightspeed,
OpenCart (up-and-comers/alternatives).
Facts: platform_type (SaaS/OSS/hybrid), entry_price (mo, USD; 0 = free
self-hosted), top_price, transaction_fee (%), setup_fee, hosting
(managed/self-hosted), app_ecosystem, payments (built-in processing),
multichannel (POS/marketplace/social), open_source (license), support
(tiers), migration (import tools).
Ratings: value, ease_of_use, features, support.
Share sources: W3Techs usage share (`install_base`), Shopify 6-K revenue
(`revenue`), Adobe 10-K segment, BigCommerce PRs (`pr_estimate`),
WordPress.org stats (WooCommerce).
Market-size queries: "e-commerce platform market size", "ecommerce SaaS
market size", "e-commerce software market size".
Review sites: PCMag, TechRadar, G2 (free tier), Digital Commerce 360.

## 7. Risks / mitigations

| Risk | Mitigation |
|---|---|
| Vendor pages JS-render / consent walls | comparison-site fallback per competitor; field marked `estimated` + source note |
| Quote-based pricing (ADT/Brinks) | comparison-site estimates, `estimated: true`, flagged in report |
| LLM extraction drift (numbers) | strict JSON schema + per-field source url; monthly run renders from JSON (no re-LLM); human-tweakable file |
| 600s monthly budget | build is separate (Jan run / CLI); monthly run only loads JSON |
| Paywalled data leakage | same rules as today: flag, never fabricate; `note` field per estimate |
| Aspect set wrong for a market | per-market in profile; validation via ecommerce market before wider rollout |

## 8. Open questions (none blocking)

- Ecommerce competitor set — confirm the 10 above (esp. include
  Salesforce Commerce Cloud? drop OpenCart?).
- Ecommerce rating aspects — value/ease_of_use/features/support OK?
- Review-site selected set for ecommerce — PCMag, TechRadar, G2,
  Digital Commerce 360 OK?
## 9. Ecommerce validation results (2026-10-13)

Bootstrap built and published. Per-market design validated — the
reference block, extraction, and rendering all worked without changes
to the generic engine.

**Artifacts**
- Reference JSON: `skills/market_research_brief/references/ecommerce_platforms.json`
- Standalone page: `https://choukalos.com/files/briefs/market_research/ecommerce_platforms_reference.html`
- Monthly brief (Oct 2026, compact reference embedded):
  `https://choukalos.com/files/briefs/ecommerce_platforms_brief.html`
  (+ dated copy `market_research/ecommerce_platforms_brief_2026-10.html`)

**Competitor fact fill (12 aspects)**
Shopify 10, BigCommerce 8, WooCommerce 7, OpenCart 7, Wix 7,
Salesforce CC 6, Adobe Commerce 5, Lightspeed 5, PrestaShop 5,
Squarespace 3. (Squarespace/Wix/Lightspeed prices are JS-gated on
vendor pages — left as "–" rather than estimated.)

**Source findings (per-market, as predicted)**
- W3Techs usage tables are JS-gated (crawl returns no rows) — dropped.
- **Store Leads** (`storeleads.app/reports`, free) is the working
  install-base source: 13.8M tracked stores; WooCommerce 4.0M,
  Shopify 3.1M, Wix 967K, Squarespace 392K (Oct 2026).
- Shopify (NYSE: SHOP, CIK 1594805) and Wix (NASDAQ: WIX, CIK 1576789)
  are public — SEC EDGAR 10-Q/6-K give verified quarterly revenue:
  Shopify Q2 2026 $3,583M (+34% y/y); Wix Q2 2026 $563M (+15% y/y).
  These are pinned in the JSON (`pinned: true`) so rebuilds keep them.
- Shopify investor page claims ">14% US ecommerce market share" and
  "$1.6T cumulative GMV" (company-stated, flagged as such).
- Adobe does NOT disclose Commerce-segment revenue in its 10-K — the
  original "Adobe 10-K (Commerce segment)" indicator was removed
  (would have been fabricated).
- Lightspeed Commerce rebranded to `lightspeedhq.com` (2026); old
  `lightspeed.com/retail` pages are thin.
- BigCommerce pricing page was intermittently bot-blocked (311 chars);
  a retry got the full table ($29/$79/$299/$1,499).
- Search API (mcp_search) is weak for finance/market-size queries
  (returns generic homepages); direct SEC EDGAR + vendor pages worked.
  Market-size phase found 0 concrete figures on the rebuild, so the
  eMarketer $7.3T (2027, global retail ecommerce sales) context
  figure is pinned in the JSON.

**Engine changes made during validation**
- `skill.py`: `_reference_sections()` (compact/full), Phase 5b splice
  into monthly HTML + .md artifact, Phase 6 standalone reference
  publish (`briefs/market_research/<market>_reference.html`), Phase 7
  full reference in yearly summary, `build_reference` param (January).
- `skill.py`: `_load_profile` now passes the `reference` block through.
- `reference.py`: `_merge_share_indicators` keyed by (competitor, type)
  so one competitor can carry several indicators; `pinned: true`
  entries survive rebuilds; market-phase prompt allows multiple
  indicators per competitor; null-safe fact access in compact mode.
- `reference.py`: `render_standalone_html()` + `reference_is_stale()`.
- `skill.yml`: `build_reference` input documented.

**Open questions (none blocking)**
- Ecommerce competitor set — confirm the 10 (Salesforce CC in, OpenCart in).
- Ecommerce rating aspects — value/ease_of_use/features/support OK?
- Review-site set — PCMag, TechRadar, G2, Digital Commerce 360 OK?
- Squarespace/Wix/Lightspeed pricing: accept "–" or add a
  comparison-site fallback source (would be `estimated`)?

## 10. Ecommerce platform expansion + scheduling (2026-10-14)

**Owner correction:** the open-source version of Adobe Commerce is
**Magento** (github.com/magento/magento2). The `open_source` fact is now
hand-pinned: "the open-source core is Magento Open Source (MIT); Adobe
Commerce is the commercial edition".

**Competitor set expanded 10 → 16** (profiles/ecommerce_platforms.yml):
- SaaS core: Shopify, BigCommerce, Salesforce Commerce Cloud
- Open source, headless/API-first: Medusa, Saleor, Bagisto, Spree
- Open source, traditional/monolithic: WooCommerce, Adobe Commerce
  (Magento), PrestaShop, OpenCart, Shopware, nopCommerce
- Website builders (adjacent): Squarespace, Wix, Lightspeed

New profile aspects: `tech_stack` (13 total). Vendor pages for the new
platforms are thin/bot-blocked (nopcommerce.com, saleor.com), so the
profile sources now include the **GitHub repos** (medusajs/medusa,
saleor/saleor, bagisto/bagisto, spree/spree, shopware/shopware,
nopSolutions/nopCommerce) + docs.saleor.io — GitHub crawls cleanly.

**Reference data (16 competitors, 13 aspects, 14 share indicators):**
- All 16 re-extracted from the warm crawl cache (35 pages); fact fill
  5–10/13 each.
- GitHub-star share indicators (pinned, `other` type): Medusa 36,734,
  Bagisto 28,232, Saleor 23,436, Spree 15,752, nopCommerce 10,156,
  Shopware 3,447 (checked 2026-10-14; labeled as popularity proxies,
  not install-base/revenue).
- Hand-pinned tech_stack facts: Spree = Ruby on Rails (the LLM had
  hallucinated Node.js from README storefront examples), Saleor =
  Python (Django) + GraphQL, Medusa = Node.js/TypeScript, PrestaShop =
  PHP, OpenCart = PHP, Adobe Commerce = PHP.
- Raw-null facts from the LLM (47) cleaned; merge now tolerates them.
- Squarespace/Wix/Lightspeed pricing still "–" (JS-gated vendor pages).

**Scheduler (scheduler/schedules.json — hot-reloaded, verified live):**
- `monthly-ecommerce-platforms-brief` — `30 9 1 * *` CT (9:30, after the
  9:00 smarthome brief), skill `ecommerce_platforms_brief`, publish.
- `annual-ecommerce-platforms-reference` — `0 7 1 1 *` CT (Jan 1, 7:00),
  skill `market_research_reference`, market=ecommerce_platforms.
- `annual-smarthome-homesecurity-reference` — `0 8 1 1 *` CT (Jan 1, 8:00),
  skill `market_research_reference`, market=smarthome_homesecurity.
- Next runs verified via GET /api/schedule: Nov 1 09:30 (ecom brief),
  Jan 1 2027 07:00/08:00 (reference rebuilds).

**New skills:**
- `skills/ecommerce_platforms_brief/` — thin wrapper (like the smarthome
  one) pinning the ecommerce_platforms profile; 600 s budget.
- `skills/market_research_reference/` — generic annual reference rebuild
  (build_reference via reference.py + standalone-page republish);
  5400 s budget (full builds take 15–30 min, outside the brief budget).

**Files-listing visibility (choukalos.com/files/briefs):**
- Direct file URLs work immediately. Directory listings are edge-cached
  by Cloudflare up to ~4h: the portal sends `Cache-Control: no-cache`
  (and I tested `no-store` + `Pragma: no-cache` after rebuilding the
  portal image), but the CF response still carries
  `cache-control: max-age=14400` + `cf-cache-status: HIT` — a **CF zone
  rule is overriding origin headers**. Reverted the portal change
  (no effect). Permanent fix needs a CF API token (zone scope: cache
  rules or purge) — then either a bypass rule for /files/* or a purge
  call in the publish flow. Until then: new files appear in listings
  within ~4h; direct links always work.

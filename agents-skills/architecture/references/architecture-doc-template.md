# Architecture doc template

Read this when writing the system design doc (S/DEV-1 `architecture`). Fill
every section; write "not applicable — <reason>" rather than skipping silently.
1–2 pages per section max for typical homelab systems; the whole doc should be
readable in one sitting.

```markdown
# <System/feature name> — Architecture

- Status: draft | reviewed | approved | superseded
- Date: <YYYY-MM-DD>
- Spec: <board card / PRD link>
- Supersedes: <prior doc, if any>

## 1. Context & goals

<What exists today (from the recon note), what this change is, what "done"
means. 1–2 pages max.>

Goals:
- <goal, testable>

Non-goals:
- <explicit — what this change deliberately does not do>

## 2. Component diagram

<ASCII diagram. Existing components + new ones. Trust boundary drawn:
public / LAN / internal. Arrows = data/control flow.>

    [public]  Caddy ──▶ <service> ──▶ <store>
    [LAN]     <agent> ──▶ <service> (unauthenticated by design — LAN trust)

## 3. Data flow

<Where data enters, how it moves, where it lands (stores, caches, logs).
Mark untrusted→trusted crossings explicitly:
  <untrusted source> ──(validation at <boundary>)──▶ <trusted consumer>>

## 4. Interfaces/contracts

| Interface | Shape | Auth | Error contract | New/changed |
|-----------|-------|------|----------------|-------------|
| <endpoint/CLI/message> | <request/response shape> | <none (LAN) / token / ...> | <status codes / error shape> | new |

## 5. Data model

<New/changed tables/collections/documents. Columns/types/indexes.
Migration story: how existing data is handled (backfill? dual-write? none?).>

## 6. Tech choices with rationale

| Choice | Why X | Alternatives considered | Why rejected |
|--------|-------|-------------------------|--------------|
| <X> | <stated reason> | <Y, Z> | <...> |

<Prefer the boring option + existing homelab patterns. A new technology
needs a stated reason.>

## 7. Constraints & trade-offs

- <project constraint respected — deploy gate, LAN trust model, resource limit>
- <trade-off made — latency / complexity / ops burden, and why accepted>

## 8. ADRs

### ADR-<n> — <decision>
- **Context:** <the question that forced the decision>
- **Decision:** <what was decided>
- **Alternatives:** <what else was considered>
- **Consequences:** <what this makes easier/harder>

## 9. Rollout plan

1. <migration order step>
2. <feature flag / staged enablement, if any>
3. <rollback path — how to undo this if it fails>
4. <post-deploy watch — what to watch, for how long (feeds S3 qa-verify)>
```

# Skill: morning_brief

Daily morning brief — news across configurable interest topics, synthesized
into a short-and-sweet bullet-point summary.

## Inputs

| Input | Default | Description |
|---|---|---|
| `interests` | built-in topic list (AI/tech, smart home security, home automation, open source, local news) | List of topic strings to search |
| `publish` | `false` | When `true`, also publish the brief to the public drop zone (atomic overwrite of `PUBLISH_PATH`) |
| `publish_path` | `/home/chuck/data/media/public/briefs/latest.md` | Public target file for `publish: true` |

## Behavior

1. **Search** — web + news search per interest topic (mcp_search)
2. **Deduplicate** — collapse near-identical items
3. **Group** — by category (topic)
4. **Synthesize** — LLM produces a compact markdown brief (headline + one-line
   summary + source link per item)
5. **Artifact** — `morning_brief_<timestamp>.md` →
   `/home/chuck/data/media/homelab_reports/`
6. **Publish (optional)** — when `publish: true`, atomically overwrites
   `publish_path` (single-file retention — no dated history)

## Scheduling

Runs as the `weekday-morning-brief` schedule (Mon–Fri 09:00
`America/Chicago`, `publish: true`) — see `homelab/scheduler/schedules.json`
and `scheduler/README.md`.

**Public output:** `https://choukalos.com/files/briefs/latest.md`
(overwritten each weekday; the previous day's brief is replaced).

## Result

| Key | Description |
|---|---|
| `summary` | Short text summary |
| `report` | Full markdown brief |
| `artifact_path` | `homelab_reports/morning_brief_<ts>.md` |
| `published_path` | Set when `publish: true` (public file path) |
| `categories` | Grouped items by topic |
| `item_count` | Number of items in the brief |
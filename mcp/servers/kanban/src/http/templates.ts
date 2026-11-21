/**
 * Server-rendered HTML templates (requirements §9: dark theme only, no JS
 * framework or build step, HTMX for auto-refresh, native <dialog> for
 * popups). Slice 1: board with data + month stats, projects list, project
 * page (settings + Idea/Grooming/Icebox columns), project editor + idea
 * drop dialogs. Slice 4: reports page (server-rendered SVG charts) +
 * project-page completed list (hidden by default, paginated).
 */
import { svgBarChart, svgHBarChart } from "../charts.js";

export type NavPage = "board" | "projects" | "reports";

const NAV: Array<{ page: NavPage; href: string; label: string }> = [
  { page: "board", href: "/", label: "Board" },
  { page: "projects", href: "/projects", label: "Projects" },
  { page: "reports", href: "/reports", label: "Reports" },
];

export function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function trunc(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

function fmtMoney(n: number): string {
  return `$${n.toFixed(2)}`;
}

export interface LayoutOptions {
  /** GET url for the 60s HTMX auto-refresh of <main> (board). */
  autoRefreshUrl?: string;
}

/** Base layout: dark theme, nav (Board · Projects · Reports), HTMX, dialog styles. */
export function layout(title: string, active: NavPage, body: string, opts: LayoutOptions = {}): string {
  const nav = NAV.map(
    (n) =>
      `<a href="${n.href}"${n.page === active ? ' class="active"' : ""}>${n.label}</a>`,
  ).join("\n    ");
  const mainAttrs = opts.autoRefreshUrl
    ? ` hx-get="${escapeHtml(opts.autoRefreshUrl)}" hx-trigger="every 60s" hx-swap="outerSwap"`
    : "";
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escapeHtml(title)} · ai-kanban</title>
<script src="https://unpkg.com/htmx.org@2.0.4" defer></script>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin: 0; background: #0f1115; color: #e5e7eb; font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
  nav { display: flex; gap: 1.25rem; align-items: center; padding: 0.8rem 1.5rem; background: #161a22; border-bottom: 1px solid #262b36; }
  nav .brand { font-weight: 700; color: #fff; margin-right: 0.5rem; }
  nav a { color: #9ca3af; text-decoration: none; }
  nav a:hover { color: #e5e7eb; }
  nav a.active { color: #fff; font-weight: 600; }
  main { max-width: 1200px; margin: 0 auto; padding: 1.5rem; }
  h1 { font-size: 1.3rem; margin: 0 0 1rem; }
  .columns { display: grid; grid-template-columns: repeat(5, 1fr); gap: 0.75rem; }
  .columns.three { grid-template-columns: repeat(3, 1fr); }
  .column { background: #161a22; border: 1px solid #262b36; border-radius: 8px; padding: 0.75rem; min-height: 120px; }
  .column h2 { font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.05em; color: #9ca3af; margin: 0 0 0.5rem; }
  .count { color: #6b7280; font-weight: 400; }
  .empty { color: #6b7280; font-size: 0.9rem; margin: 0; }
  .muted { color: #6b7280; }
  .stats { display: flex; gap: 1rem; margin-bottom: 1rem; }
  .stat { background: #161a22; border: 1px solid #262b36; border-radius: 8px; padding: 0.5rem 1rem; }
  .stat-label { display: block; font-size: 0.7rem; color: #9ca3af; text-transform: uppercase; letter-spacing: 0.05em; }
  .stat-value { font-size: 1.15rem; font-weight: 600; }
  .card { background: #1c212c; border: 1px solid #262b36; border-radius: 6px; padding: 0.5rem 0.6rem; margin-bottom: 0.5rem; font-size: 0.9rem; }
  .card-top { display: flex; gap: 0.4rem; align-items: center; margin-bottom: 0.25rem; }
  .tag { background: rgba(37, 99, 235, 0.15); color: #93c5fd; border: 1px solid rgba(37, 99, 235, 0.4); border-radius: 4px; padding: 0 0.35rem; font-size: 0.75rem; }
  .tag.owner { background: rgba(22, 101, 52, 0.18); color: #86efac; border-color: rgba(22, 101, 52, 0.45); }
  .badge { background: #7c2d12; color: #fdba74; border-radius: 4px; padding: 0 0.35rem; font-size: 0.75rem; }
  .card-title { color: #e5e7eb; }
  .card-meta { color: #6b7280; font-size: 0.8rem; margin-top: 0.2rem; }
  .page-actions { display: flex; gap: 0.5rem; margin-bottom: 1rem; }
  button { background: #2563eb; color: #fff; border: 0; border-radius: 6px; padding: 0.4rem 0.9rem; font-size: 0.9rem; cursor: pointer; }
  button.secondary { background: #262b36; }
  table.project-list { width: 100%; border-collapse: collapse; }
  table.project-list th, table.project-list td { text-align: left; padding: 0.5rem 0.75rem; border-bottom: 1px solid #262b36; }
  table.project-list th { font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.05em; color: #9ca3af; }
  table.project-list a { color: #93c5fd; text-decoration: none; }
  .settings { background: #161a22; border: 1px solid #262b36; border-radius: 8px; padding: 1rem; margin-bottom: 1rem; }
  .settings h2 { font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.05em; color: #9ca3af; margin: 0 0 0.5rem; }
  .settings dl { display: grid; grid-template-columns: 180px 1fr; gap: 0.35rem 0.75rem; margin: 0; }
  .settings dt { color: #9ca3af; font-size: 0.85rem; }
  .settings dd { margin: 0; font-size: 0.9rem; white-space: pre-wrap; word-break: break-word; }
  dialog { background: #1c212c; color: #e5e7eb; border: 1px solid #262b36; border-radius: 8px; padding: 1.25rem; max-width: 560px; width: 90%; }
  dialog::backdrop { background: rgba(0, 0, 0, 0.6); }
  dialog h2 { font-size: 1rem; margin: 0; }
  label { display: block; margin: 0.6rem 0; font-size: 0.85rem; color: #9ca3af; }
  input, textarea { display: block; width: 100%; margin-top: 0.2rem; background: #0f1115; color: #e5e7eb; border: 1px solid #262b36; border-radius: 6px; padding: 0.4rem 0.5rem; font: inherit; }
  .form-actions { display: flex; gap: 0.5rem; margin-top: 1rem; }
  .card-link { display: block; color: inherit; text-decoration: none; }
  .card-link:hover { border-color: #3b82f6; }
  .msg { background: #1c212c; border: 1px solid #262b36; border-radius: 6px; padding: 0.6rem 0.8rem; margin-bottom: 0.5rem; }
  .msg.user { background: #182234; border-color: #1e3a5f; }
  .msg.error { background: #2a1516; border-color: #7f1d1d; color: #fca5a5; }
  .msg.status { background: #1a2332; border-color: #1e3a5f; color: #93c5fd; font-size: 0.85rem; font-style: italic; display: flex; align-items: center; gap: 0.5rem; }
  .msg.status .dot { width: 8px; height: 8px; border-radius: 50%; background: #3b82f6; animation: pulse 1.2s ease-in-out infinite; flex-shrink: 0; }
  @keyframes pulse { 0%, 100% { opacity: 0.3; } 50% { opacity: 1; } }
  .groom-badge { font-size: 0.72rem; color: #9ca3af; margin-bottom: 0.3rem; }
  .groom-badge.working { color: #93c5fd; display: flex; align-items: center; gap: 0.4rem; font-weight: 600; }
  .groom-badge.working .dot { width: 8px; height: 8px; border-radius: 50%; background: #3b82f6; animation: pulse 1.2s ease-in-out infinite; flex-shrink: 0; }
  .groom-banner { display: flex; gap: 0.75rem; align-items: flex-start; background: #1a2332; border: 1px solid #1e3a5f; border-left: 4px solid #3b82f6; border-radius: 8px; padding: 0.7rem 0.9rem; margin: 0.75rem 0; color: #dbeafe; font-size: 0.9rem; }
  .groom-banner .dot { width: 10px; height: 10px; border-radius: 50%; background: #3b82f6; animation: pulse 1.2s ease-in-out infinite; margin-top: 0.35rem; flex-shrink: 0; }
  .msg-role { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em; color: #9ca3af; margin-bottom: 0.25rem; }
  .msg-text { white-space: pre-wrap; word-break: break-word; font-size: 0.92rem; }
  #groom-messages { max-height: 60vh; overflow-y: auto; margin-bottom: 1rem; padding-right: 0.25rem; }
  .groom-note { display: flex; gap: 0.75rem; align-items: flex-start; background: #1a2332; border: 1px solid #1e3a5f; border-left: 4px solid #3b82f6; border-radius: 8px; padding: 0.7rem 0.9rem; margin: 0.75rem 0; color: #dbeafe; font-size: 0.9rem; }
  .groom-note code { background: #0f1115; border: 1px solid #262b36; border-radius: 4px; padding: 0 0.3rem; font-size: 0.85rem; }
  button.danger { background: #7f1d1d; }
  .icebox-move { margin-top: 0.5rem; }
  .badge.state-backlog { background: #1e3a5f; color: #93c5fd; }
  .badge.state-running { background: #14532d; color: #86efac; }
  .badge.state-deploy { background: #3b2f14; color: #fde68a; }
  .badge.state-done { background: #14532d; color: #86efac; }
  .badge.state-needs_attention { background: #7f1d1d; color: #fca5a5; }
  .log { background: #0b0d10; border: 1px solid #262b36; border-radius: 6px; padding: 0.6rem 0.8rem; font: 12px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace; max-height: 45vh; overflow-y: auto; white-space: pre-wrap; word-break: break-word; }
  .log-line { color: #d1d5db; }
  .log-ts { color: #6b7280; margin-right: 0.5rem; }
  .log-type { color: #93c5fd; margin-right: 0.5rem; text-transform: uppercase; font-size: 10px; letter-spacing: 0.05em; }
  .resolution { background: #0b0d10; border: 1px solid #262b36; border-radius: 6px; padding: 0.6rem 0.8rem; white-space: pre-wrap; font-size: 0.9rem; margin: 0; }
  .chart { margin: 0.75rem 0; }
  .chart svg { display: block; }
  .filters { display: flex; gap: 0.5rem; flex-wrap: wrap; align-items: center; margin-bottom: 0.75rem; }
  .filters select, .filters input { width: auto; min-width: 140px; margin-top: 0; display: inline-block; }
  .filters input[type="search"] { flex: 1; min-width: 180px; }
  .filters button { padding: 0.4rem 0.9rem; }
  table.usage-table { width: 100%; border-collapse: collapse; }
  table.usage-table th, table.usage-table td { text-align: left; padding: 0.45rem 0.6rem; border-bottom: 1px solid #262b36; font-size: 0.88rem; }
  table.usage-table th { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; color: #9ca3af; }
  table.usage-table td.num, table.usage-table th.num { text-align: right; font-variant-numeric: tabular-nums; }
  table.usage-table a { color: #93c5fd; text-decoration: none; }
  details.completed { margin-top: 1rem; background: #161a22; border: 1px solid #262b36; border-radius: 8px; padding: 0.75rem 1rem; }
  details.completed summary { cursor: pointer; font-size: 0.9rem; color: #e5e7eb; }
  .pager { display: flex; gap: 0.5rem; align-items: center; margin-top: 0.5rem; font-size: 0.85rem; color: #9ca3af; }
  .pager a { color: #93c5fd; text-decoration: none; }
  /* Task detail slide-over panel (post-MVP enhancement, PLAN.md §5) */
  #task-panel { position: fixed; top: 0; right: 0; bottom: 0; width: min(880px, 96vw); max-width: 96vw; margin: 0; padding: 1rem 1.25rem 2rem; background: #14171f; border-left: 1px solid #262b36; border-radius: 0; overflow-y: auto; }
  #task-panel::backdrop { background: rgba(0, 0, 0, 0.55); }
  #task-panel .panel-close { position: absolute; top: 0.75rem; right: 0.9rem; background: #262b36; border-radius: 6px; padding: 0.2rem 0.6rem; font-size: 0.85rem; }
  #task-panel h1 { padding-right: 2.5rem; }
  #task-panel .log { max-height: 50vh; }
</style>
</head>
<body>
<nav>
  <span class="brand">ai-kanban</span>
    ${nav}
</nav>
<main${mainAttrs}>
${body}
</main>
<dialog id="task-panel" onclick="if (event.target === this) this.close()"></dialog>
<script>
// Task detail slide-over panel: open via the board card / task links
// (data-task-panel="<id>"), close via the ✕ button, the backdrop, or Esc.
document.addEventListener("click", (e) => {
  const a = e.target instanceof Element ? e.target.closest("a[data-task-panel]") : null;
  if (!a) return;
  e.preventDefault();
  openTaskPanel(a.getAttribute("data-task-panel") || "");
});
function openTaskPanel(id) {
  if (!id) return;
  const d = document.getElementById("task-panel");
  if (!d) return;
  d.removeAttribute("open"); // reset (clears stale content + HTMX timers)
  d.innerHTML = '<p class="muted">Loading task…</p>';
  if (typeof d.showModal === "function") d.showModal();
  else d.setAttribute("open", "");
  fetch("/tasks/" + id, { headers: { "HX-Request": "true" } })
    .then((r) => r.text())
    .then((html) => { d.innerHTML = html; })
    .catch(() => { d.innerHTML = '<p class="muted">Failed to load task.</p>'; });
}
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    const d = document.getElementById("task-panel");
    if (d && d.open) d.close();
  }
});
</script>
</body>
</html>
`;
}

// ---------------------------------------------------------------------------
// Board (landing)
// ---------------------------------------------------------------------------

export interface BoardCardView {
  taskId: number;
  projectName: string;
  title: string;
  paused: boolean;
  cost: number;
  /** Owner (inherited from the idea); '' = unattributed (legacy). */
  owner: string;
  waitingOn: string[];
}

export interface BoardPageData {
  columns: Array<{ title: string; cards: BoardCardView[] }>;
  month: { spend: number; completed: number };
}

function cardHtml(card: BoardCardView): string {
  const meta: string[] = [fmtMoney(card.cost)];
  if (card.waitingOn.length > 0) {
    meta.push(`waiting on: ${card.waitingOn.map((d) => trunc(d, 40)).join(", ")}`);
  }
  return `<a class="card card-link" href="/tasks/${card.taskId}" data-task-panel="${card.taskId}">
  <div class="card-top"><span class="tag">${escapeHtml(card.projectName)}</span>${
    card.owner !== "" ? `<span class="tag owner">${escapeHtml(card.owner)}</span>` : ""
  }${card.paused ? '<span class="badge">paused</span>' : ""}</div>
  <div class="card-title">${escapeHtml(trunc(card.title, 90))}</div>
  <div class="card-meta">${meta.map(escapeHtml).join(" · ")}</div>
</a>`;
}

/** Board (landing): month stats + 5 columns with task cards. */
export function boardPage(data: BoardPageData): string {
  const cols = data.columns
    .map((c) => {
      const cards = c.cards.length > 0 ? c.cards.map(cardHtml).join("\n") : `<p class="empty">—</p>`;
      return `<section class="column"><h2>${escapeHtml(c.title)} <span class="count">${c.cards.length}</span></h2>\n${cards}</section>`;
    })
    .join("\n");
  return `<h1>Board</h1>
<p class="muted">Read-only view — add ideas, groom, move to backlog, and control tasks via the MCP tools (the web UI shows where things are at).</p>
<div class="stats">
  <div class="stat"><span class="stat-label">Spend this month</span><span class="stat-value">${fmtMoney(data.month.spend)}</span></div>
  <div class="stat"><span class="stat-label">Completed this month</span><span class="stat-value">${data.month.completed}</span></div>
</div>
<div class="columns">
${cols}
</div>`;
}

// ---------------------------------------------------------------------------
// Projects
// ---------------------------------------------------------------------------

export interface ProjectSummaryView {
  id: number;
  name: string;
  description: string;
  owner: string;
}

/** Projects list (read-only): name + owner + short description. */
export function projectsPage(data: { projects: ProjectSummaryView[] }): string {
  const rows =
    data.projects.length > 0
      ? data.projects
          .map(
            (p) =>
              `<tr><td><a href="/projects/${p.id}">${escapeHtml(p.name)}</a></td><td>${
                p.owner !== "" ? `<span class="tag owner">${escapeHtml(p.owner)}</span>` : "—"
              }</td><td>${escapeHtml(p.description || "—")}</td></tr>`,
          )
          .join("\n")
      : `<tr><td colspan="3" class="muted">No projects yet — create one via the MCP <code>create_project</code> tool.</td></tr>`;
  return `<h1>Projects</h1>
<p class="muted">Read-only view — projects, ideas, grooming, and task control happen via the MCP tools (the web UI shows where things are at).</p>
<table class="project-list">
<tr><th>Name</th><th>Owner</th><th>Description</th></tr>
${rows}
</table>`;
}

// ---------------------------------------------------------------------------
// Project page
// ---------------------------------------------------------------------------

export interface ProjectPageData {
  id: number;
  name: string;
  /** Owner (caller identity of the creating mutation); '' = unattributed (legacy). */
  owner: string;
  description: string;
  goal: string;
  repoUrl: string | null;
  defaultBranch: string | null;
  blogRepoUrl: string | null;
  blogContentPath: string | null;
  mediaPaths: string[] | null;
  constraints: string | null;
  architectureNotes: string | null;
  notes: string | null;
  stateSummary: string | null;
  ideas: Array<{
    id: number;
    text: string;
    state: string;
    owner: string;
    dependsOn: number[] | null;
    spec: { goal: string; steps: string[]; acceptance: string[]; kind: string; publish_targets?: string[]; notes?: string } | null;
  }>;
  /** Live grooming turn status per idea id (badge in the Grooming column). */
  groomingStatus: Record<number, { active: boolean; since: number | null; label: string | null }>;
  /** Completed/deployed items (hidden by default, paginated — requirements §9). */
  completed: {
    items: Array<{ taskId: number; title: string; finishedAt: number; cost: number }>;
    page: number;
    pageSize: number;
    total: number;
    pageCount: number;
  };
}

/**
 * Project page (READ-ONLY): settings + LLM state summary + the three
 * pipeline columns (Idea / Grooming / Icebox) + the completed/deployed
 * items list (hidden by default, paginated — requirements §9).
 * Idea/Grooming cards link to the grooming transcript viewer; the Icebox
 * column shows finalized specs (goal, kind, dependencies). All mutations
 * (new idea, grooming, move to backlog) happen via the MCP tools.
 */
export function projectPage(data: ProjectPageData): string {
  const byState = (s: string) => data.ideas.filter((i) => i.state === s);
  const ideaText = new Map(data.ideas.map((i) => [i.id, i.text]));

  const pipelineCard = (i: ProjectPageData["ideas"][number], hint: string, badge?: string) =>
    `<a class="card card-link" href="/ideas/${i.id}/groom">
  <div class="card-top">${
    i.owner !== "" ? `<span class="tag owner">${escapeHtml(i.owner)}</span>` : ""
  }</div>
  <div class="card-title">${escapeHtml(trunc(i.text, 90))}</div>
  ${badge ?? ""}
  <div class="card-meta">${hint}</div>
</a>`;

  /** Live badge for the Grooming column: pulsing while the agent works. */
  const groomBadge = (i: ProjectPageData["ideas"][number]): string => {
    const st = data.groomingStatus[i.id];
    if (st?.active) {
      const what = st.label ? ` — ${st.label}` : "";
      return `<div class="groom-badge working"><span class="dot"></span>agent working${what} (since ${new Date(st.since ?? Date.now()).toLocaleTimeString()})</div>`;
    }
    return `<div class="groom-badge">in grooming chat</div>`;
  };

  const column = (title: string, items: ProjectPageData["ideas"], hint: string, withBadge = false) => {
    const cards =
      items.length > 0
        ? items.map((i) => pipelineCard(i, hint, withBadge ? groomBadge(i) : undefined)).join("\n")
        : `<p class="empty">—</p>`;
    return `<section class="column"><h2>${title} <span class="count">${items.length}</span></h2>\n${cards}</section>`;
  };

  const iceboxItems = byState("icebox");
  const iceboxCards =
    iceboxItems.length > 0
      ? iceboxItems
          .map((i) => {
            const deps = (i.dependsOn ?? [])
              .map((d) => ideaText.get(d))
              .filter((d): d is string => d !== undefined);
            const goal = i.spec?.goal ? `<div class="card-meta">${escapeHtml(trunc(i.spec.goal, 140))}</div>` : "";
            const depsLine =
              deps.length > 0
                ? `<div class="card-meta">depends on: ${deps
                    .map((d) => escapeHtml(trunc(d, 40)))
                    .join(", ")}</div>`
                : "";
            return `<div class="card icebox-card">
  <div class="card-top">${
    i.owner !== "" ? `<span class="tag owner">${escapeHtml(i.owner)}</span>` : ""
  }<span class="tag">${escapeHtml(i.spec?.kind ?? "other")}</span></div>
  <div class="card-title">${escapeHtml(trunc(i.text, 90))}</div>
  ${goal}
  ${depsLine}
</div>`;
          })
          .join("\n")
      : `<p class="empty">—</p>`;
  const iceboxColumn = `<section class="column"><h2>Icebox <span class="count">${iceboxItems.length}</span></h2>
${iceboxCards}
${
  iceboxItems.length > 0
    ? `<p class="muted" style="margin-top:0.5rem;font-size:0.8rem">Move to backlog via the MCP <code>move_to_backlog</code> tool.</p>`
    : ""
}
</section>`;

  const settings: Array<[string, string]> = [
    ["Owner", data.owner],
    ["Description", data.description],
    ["Goal", data.goal],
    [
      "Repo",
      data.repoUrl ? `${data.repoUrl}${data.defaultBranch ? ` (${data.defaultBranch})` : ""}` : "",
    ],
    [
      "Blog",
      data.blogRepoUrl
        ? `${data.blogRepoUrl}${data.blogContentPath ? ` → ${data.blogContentPath}` : ""}`
        : "",
    ],
    ["Media paths", (data.mediaPaths ?? []).join(", ")],
    ["Constraints", data.constraints ?? ""],
    ["Architecture notes", data.architectureNotes ?? ""],
    ["Notes", data.notes ?? ""],
  ].filter(([, v]) => v !== "") as Array<[string, string]>;

  const dl = settings.map(([k, v]) => `<dt>${k}</dt><dd>${escapeHtml(v)}</dd>`).join("\n");

  // Completed/deployed items (hidden by default via <details>, paginated).
  const c = data.completed;
  const pageHref = (p: number) => `/projects/${data.id}${p > 1 ? `?page=${p}` : ""}`;
  const completedRows =
    c.items.length > 0
      ? c.items
          .map(
            (it) =>
              `<tr><td><a href="/tasks/${it.taskId}">#${it.taskId}</a></td><td>${escapeHtml(trunc(it.title, 120))}</td><td>${fmtTs(it.finishedAt)}</td><td>${fmtMoney(it.cost)}</td></tr>`,
          )
          .join("\n")
      : `<tr><td colspan="4" class="muted">No completed items yet.</td></tr>`;
  const pager =
    c.pageCount > 1
      ? `<div class="pager">${
          c.page > 1 ? `<a href="${pageHref(c.page - 1)}">← prev</a>` : `<span>← prev</span>`
        } <span>page ${c.page} of ${c.pageCount} (${c.total} total)</span> ${
          c.page < c.pageCount ? `<a href="${pageHref(c.page + 1)}">next →</a>` : `<span>next →</span>`
        }</div>`
      : `<div class="pager"><span>${c.total} total</span></div>`;
  const completedSection = `<details class="completed">
<summary>Completed items (${c.total})</summary>
<table class="usage-table">
<tr><th>#</th><th>Title</th><th>Completed</th><th>Cost</th></tr>
${completedRows}
</table>
${pager}
</details>`;

  return `<h1>${escapeHtml(data.name)}</h1>
<p class="muted">Read-only view — add ideas, groom, and move icebox items to the backlog via the MCP tools.</p>
<section class="settings">
  <h2>Settings</h2>
  <dl>${dl || '<dd class="muted">—</dd>'}</dl>
  <h2 style="margin-top:1rem">State summary</h2>
  <p class="${data.stateSummary ? "" : "muted"}" style="margin:0;white-space:pre-wrap">${escapeHtml(
    data.stateSummary ?? "—",
  )}</p>
</section>
<div class="columns three">
${column("Idea", byState("idea"), "groom via MCP")}
${column("Grooming", byState("grooming"), "view chat →", true)}
${iceboxColumn}
</div>
${completedSection}`;
}

// ---------------------------------------------------------------------------
// Grooming chat (requirements §9: interactive chat page with the LLM)
// ---------------------------------------------------------------------------

export interface GroomMessageView {
  role: "user" | "assistant";
  text: string;
}

export interface GroomPageData {
  ideaId: number;
  projectId: number;
  projectName: string;
  ideaText: string;
  /** Current idea state (idea / grooming / icebox / moved / discarded). */
  state: string;
  messages: GroomMessageView[];
  /** Live turn status (is the assistant working right now?). */
  turn: { active: boolean; since: number | null; label: string | null };
}

/** One chat message as an HTML fragment (also the HTMX swap unit). */
export function groomMessageFragment(role: "user" | "assistant", text: string): string {
  const who = role === "user" ? "You" : "Assistant";
  return `<div class="msg ${role}">
  <div class="msg-role">${who}</div>
  <div class="msg-text">${escapeHtml(text)}</div>
</div>`;
}

/**
 * The #groom-messages container as an HTML fragment: status line (when a
 * turn is in flight) + full transcript. The container re-emits its own poll
 * attributes so the 3s HTMX poll (hx-swap="outerHTML") survives swaps.
 */
export function groomMessagesFragment(
  ideaId: number,
  messages: GroomMessageView[],
  turn: { active: boolean; since: number | null; label: string | null },
): string {
  const status = turn.active
    ? `<div class="msg status"><span class="dot"></span>Assistant is working${turn.label ? ` — ${escapeHtml(turn.label)}` : ""}… (since ${new Date(turn.since ?? Date.now()).toLocaleTimeString()}) — new messages will be queued</div>`
    : "";
  const body =
    messages.length > 0
      ? messages.map((m) => groomMessageFragment(m.role, m.text)).join("\n")
      : `<p class="empty">No messages yet — the assistant will reply here.</p>`;
  return `<div id="groom-messages" hx-get="/ideas/${ideaId}/groom/messages" hx-trigger="every 3s" hx-swap="outerHTML">
${status}
${body}
</div>`;
}

/**
 * Grooming transcript viewer (READ-ONLY): the grooming conversation happens
 * via MCP (start_grooming / groom_message / groom_accept / groom_cancel /
 * groom_re_groom); this page shows where the conversation is at. While the
 * idea is in `grooming`, the transcript polls every 3s.
 */
export function groomPage(data: GroomPageData): string {
  if (data.state !== "grooming") {
    const message =
      data.state === "idea"
        ? "Grooming has not started yet — start it via the MCP <code>start_grooming</code> tool (the grooming LLM will research the idea, state its assumptions, and ask questions)."
        : `This idea is no longer in grooming (state: ${escapeHtml(data.state)}).`;
    return `<h1>Grooming — ${escapeHtml(trunc(data.ideaText, 120))}</h1>
<p class="muted">Project: <a href="/projects/${data.projectId}">${escapeHtml(data.projectName)}</a> · read-only view (grooming happens via MCP)</p>
<div class="groom-note"><div>${message}</div></div>`;
  }
  const banner = data.turn.active
    ? `<div class="groom-banner"><span class="dot"></span>
  <div><strong>The agent is working on this idea</strong>${data.turn.label ? ` — ${escapeHtml(data.turn.label)}` : ""} (since ${new Date(data.turn.since ?? Date.now()).toLocaleTimeString()}).
  This can take several minutes — new messages sent via MCP will be queued.</div></div>`
    : "";
  return `<h1>Grooming — ${escapeHtml(trunc(data.ideaText, 120))}</h1>
${banner}
<p class="muted">Project: <a href="/projects/${data.projectId}">${escapeHtml(data.projectName)}</a> · read-only view — chat, accept, and cancel via the MCP tools (<code>groom_message</code>, <code>groom_accept</code>, <code>groom_cancel</code>, <code>groom_re_groom</code>)</p>
${groomMessagesFragment(data.ideaId, data.messages, data.turn)}`;
}

// ---------------------------------------------------------------------------
// Task detail (requirements §9: live agent log, 2s auto-refresh while running)
// ---------------------------------------------------------------------------

export interface TaskLogLineView {
  ts: number;
  type: string;
  text: string;
}

export interface TaskPageData {
  id: number;
  title: string;
  state: string;
  paused: boolean;
  stateChangedAt: number;
  project: { id: number; name: string };
  /** Owner (inherited from the idea); '' = unattributed (legacy). */
  owner: string;
  kind: string;
  workspace: string | null;
  branch: string | null;
  lastCommit: string | null;
  qaRounds: number;
  goal: string;
  steps: string[];
  acceptance: string[];
  resolution: string | null;
  waitingOn: string[];
  usageTotal: number;
  usageByRole: Record<string, number>;
  log: TaskLogLineView[];
  /** 2s HTMX auto-refresh of the log while running. */
  live: boolean;
  /** Last task_event ts (watchdog visibility: when the task last did something). */
  lastActivityAt: number | null;
  /** Failure reason (last state event with a reason) for Needs Attention. */
  failureReason: string | null;
  /** Last QA feedback (what-happened panel). */
  qaFeedback: string | null;
}

function fmtTs(ts: number): string {
  return new Date(ts).toISOString().replace("T", " ").slice(0, 19);
}

function logLineHtml(line: TaskLogLineView): string {
  return `<div class="log-line"><span class="log-ts">${fmtTs(line.ts)}</span><span class="log-type">${escapeHtml(
    line.type,
  )}</span>${escapeHtml(line.text)}</div>`;
}

/** Log tail fragment (the HTMX swap unit for #task-log). */
export function taskLogFragment(lines: TaskLogLineView[]): string {
  const body =
    lines.length > 0 ? lines.map(logLineHtml).join("\n") : `<span class="muted">no log lines yet</span>`;
  return `<div class="log">${body}</div>`;
}

/**
 * Task detail (PLAN.md §5: slide-over panel, post-MVP): state + workspace +
 * branch + last commit, spec, usage so far, and the live log (2s HTMX
 * auto-refresh while running). Rendered two ways:
 *   - as the slide-over panel body (GET /tasks/<id>?panel=1, HTMX swap unit
 *     into #task-panel on the board page) — the normal path; and
 *   - as a full page (GET /tasks/<id>) for deep links / direct navigation.
 * READ-ONLY: no manual control buttons — task control (pause/resume/stop,
 * retry deploy) and Needs-Attention resolution happen via the MCP tools
 * (pause_task / resume_task / stop_task / retry_deploy / restart_task).
 * Needs Attention tasks show a what-happened panel (failure reason, QA
 * feedback) + a pointer at the MCP resolution loop.
 */
export function taskPage(data: TaskPageData, opts: { panel?: boolean } = {}): string {
  const closeBtn = opts.panel
    ? `<button type="button" class="panel-close" onclick="document.getElementById('task-panel').close()" title="Close (Esc)">✕</button>`
    : "";
  const usageRoles = Object.entries(data.usageByRole)
    .map(([role, cost]) => `${escapeHtml(role)} ${fmtMoney(cost)}`)
    .join(" · ");
  const logAttrs = data.live ? ` hx-get="/tasks/${data.id}/log" hx-trigger="every 2s" hx-swap="innerHTML"` : "";
  const details: Array<[string, string]> = [
    ["State", `${data.state}${data.paused ? " (paused)" : ""} — since ${fmtTs(data.stateChangedAt)}`],
    ["Project", data.project.name],
    ["Owner", data.owner],
    ["Workspace", data.workspace ?? "—"],
    ["Branch", data.branch ?? "—"],
    ["Last commit", data.lastCommit ?? "—"],
    ["Last activity", data.lastActivityAt ? fmtTs(data.lastActivityAt) : "—"],
    ["QA rounds", String(data.qaRounds)],
    ["Waiting on", data.waitingOn.join(", ") || "—"],
  ];
  const dl = details.map(([k, v]) => `<dt>${k}</dt><dd>${escapeHtml(v || "—")}</dd>`).join("\n");
  const steps =
    data.steps.length > 0 ? `<ol>${data.steps.map((s) => `<li>${escapeHtml(s)}</li>`).join("")}</ol>` : "";
  const acceptance =
    data.acceptance.length > 0
      ? `<ul>${data.acceptance.map((a) => `<li>${escapeHtml(a)}</li>`).join("")}</ul>`
      : "";
  const resolution = data.resolution
    ? `<h2 style="margin-top:1rem">Accepted resolution plan</h2><pre class="resolution">${escapeHtml(data.resolution)}</pre>`
    : "";
  const needsAttention = data.state === "needs_attention";
  const failed = needsAttention
    ? `<section class="settings"><h2>What happened</h2>
  <p style="white-space:pre-wrap">${escapeHtml(data.failureReason ?? "(no failure reason recorded)")}</p>
  ${data.qaFeedback ? `<p class="muted" style="white-space:pre-wrap"><strong>QA feedback:</strong> ${escapeHtml(data.qaFeedback)}</p>` : ""}
  <p class="muted" style="margin:0">See the log tail below for the last activity before the failure.</p>
  <p class="muted" style="margin-top:0.75rem;margin-bottom:0">Resolve via MCP: <code>task_status(${data.id})</code> for the full failure context + log tail, dialog with the user, then <code>restart_task(${data.id}, resolution_note)</code> (resume from last commit, plan injected, QA rounds reset) — or <code>retry_deploy(${data.id})</code> for a deploy failure.</p>
  </section>`
    : "";
  return `${closeBtn}<h1>Task #${data.id} — ${escapeHtml(trunc(data.title, 120))} <span class="badge state-${escapeHtml(data.state)}">${escapeHtml(data.state)}</span>${
    data.paused ? ' <span class="badge">paused</span>' : ""
  }</h1>
<p class="muted"><a href="/">← Board</a> · <a href="/projects/${data.project.id}">${escapeHtml(data.project.name)}</a> · kind ${escapeHtml(data.kind)} · read-only view (task control via MCP)</p>
<section class="settings">
  <h2>Details</h2>
  <dl>${dl}</dl>
  <h2 style="margin-top:1rem">Spec</h2>
  <p style="margin:0 0 0.5rem;white-space:pre-wrap">${escapeHtml(data.goal)}</p>
  ${steps}
  ${acceptance}
  ${resolution}
</section>
${failed}
<div class="stats">
  <div class="stat"><span class="stat-label">Usage so far</span><span class="stat-value">${fmtMoney(data.usageTotal)}</span></div>
  <div class="stat"><span class="stat-label">By role</span><span class="stat-value" style="font-size:0.9rem">${usageRoles || "—"}</span></div>
</div>
<h2>Log ${data.live ? '<span class="muted" style="font-size:0.9rem;font-weight:400">(live, 2s refresh)</span>' : ""}</h2>
<div id="task-log"${logAttrs}>
${taskLogFragment(data.log)}
</div>`;
}

// ---------------------------------------------------------------------------
// Misc
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Reports (Slice 4, requirements §9/§11): rolling-12-month $ spend chart +
// total callout, per-project completed count + $ spend, per-task usage
// table (filterable). Charts are server-rendered SVG (src/charts.ts).
// ---------------------------------------------------------------------------

export interface ReportsPageData {
  /** 12 month buckets, oldest → newest (chart data). */
  months: Array<{ key: string; label: string; short: string; spend: number }>;
  /** Total $ spend across the rolling 12 months (callout). */
  total: number;
  /**
   * Per-user $ spend, rolling 12 months (Phase 2). One row per owner present
   * in the window; `owner` '' = unattributed (service key / legacy rows).
   * `byMonth` is keyed by the `months[].key` values (absent = $0).
   */
  owners: Array<{ owner: string; byMonth: Record<string, number>; total: number }>;
  /** $ spend per usage role, rolling 12 months (groom/task/qa/summary/resolve). */
  roleSpend: Array<{ role: string; total: number; tokensIn: number; tokensOut: number }>;
  projects: Array<{ id: number; name: string; completed: number; spend: number }>;
  tasks: Array<{
    taskId: number;
    project: string;
    title: string;
    state: string;
    tokensIn: number;
    tokensOut: number;
    cost: number;
    byRole: Record<string, number>;
  }>;
  /** Normalized filters (echoed into the filter form). */
  filters: { project: string; state: string; role: string; q: string };
  projectOptions: Array<{ id: number; name: string }>;
  states: string[];
  roles: string[];
}

/** Reports page (GET /reports). */
export function reportsPage(data: ReportsPageData): string {
  const barChart = svgBarChart(
    data.months.map((m) => ({ label: m.short, value: m.spend, sub: m.label })),
    { formatValue: (n) => `$${n.toFixed(2)}` },
  );
  const ownerLabel = (owner: string) => (owner === "" ? "unattributed" : owner);
  const ownerRows =
    data.owners.length > 0
      ? data.owners
          .map((o) => {
            const cells = data.months
              .map((m) => `<td class="num">${fmtMoney(o.byMonth[m.key] ?? 0)}</td>`)
              .join("");
            return `<tr><td>${escapeHtml(ownerLabel(o.owner))}</td>${cells}<td class="num"><strong>${fmtMoney(o.total)}</strong></td></tr>`;
          })
          .join("\n")
      : `<tr><td colspan="${data.months.length + 2}" class="muted">No usage recorded in the window yet.</td></tr>`;
  const ownerHead = data.months.map((m) => `<th class="num">${escapeHtml(m.short)}</th>`).join("");
  const ownerChart = svgHBarChart(
    data.owners.map((o) => ({ label: ownerLabel(o.owner), value: o.total })),
    { formatValue: (n) => `$${n.toFixed(2)}` },
  );
  const roleRows =
    data.roleSpend.length > 0
      ? data.roleSpend
          .map(
            (r) =>
              `<tr><td>${escapeHtml(r.role)}</td><td class="num">${r.tokensIn}</td><td class="num">${r.tokensOut}</td><td class="num"><strong>${fmtMoney(r.total)}</strong></td></tr>`,
          )
          .join("\n")
      : `<tr><td colspan="4" class="muted">No usage recorded in the window yet.</td></tr>`;
  const roleChart = svgHBarChart(
    data.roleSpend.map((r) => ({ label: r.role, value: r.total })),
    { formatValue: (n) => `$${n.toFixed(2)}` },
  );
  const projectChart = svgHBarChart(
    data.projects.map((p) => ({ label: p.name, value: p.spend, sub: `${p.completed} completed` })),
    { formatValue: (n) => `$${n.toFixed(2)}` },
  );
  const projectRows =
    data.projects.length > 0
      ? data.projects
          .map(
            (p) =>
              `<tr><td><a href="/projects/${p.id}">${escapeHtml(p.name)}</a></td><td class="num">${p.completed}</td><td class="num">${fmtMoney(p.spend)}</td></tr>`,
          )
          .join("\n")
      : `<tr><td colspan="3" class="muted">No projects yet.</td></tr>`;
  const taskRows =
    data.tasks.length > 0
      ? data.tasks
          .map((t) => {
            const byRole = Object.entries(t.byRole)
              .map(([role, cost]) => `${escapeHtml(role)} ${fmtMoney(cost)}`)
              .join(" · ");
            return `<tr>
<td><a href="/tasks/${t.taskId}">#${t.taskId}</a></td>
<td>${escapeHtml(t.project)}</td>
<td>${escapeHtml(trunc(t.title, 100))}</td>
<td><span class="badge state-${escapeHtml(t.state)}">${escapeHtml(t.state)}</span></td>
<td class="num">${t.tokensIn}</td>
<td class="num">${t.tokensOut}</td>
<td class="num">${fmtMoney(t.cost)}</td>
<td class="muted">${byRole || "—"}</td>
</tr>`;
          })
          .join("\n")
      : `<tr><td colspan="8" class="muted">No task usage recorded${
          data.filters.project || data.filters.state || data.filters.role || data.filters.q
            ? " for the current filters"
            : " yet"
        }.</td></tr>`;
  const opt = (value: string, label: string, selected: boolean) =>
    `<option value="${escapeHtml(value)}"${selected ? " selected" : ""}>${escapeHtml(label)}</option>`;
  const f = data.filters;
  return `<h1>Reports</h1>
<section class="settings">
  <h2>Spend — rolling 12 months</h2>
  <div class="stats">
    <div class="stat"><span class="stat-label">Total spend (12 mo)</span><span class="stat-value">${fmtMoney(data.total)}</span></div>
  </div>
  <div class="chart">${barChart}</div>
</section>
<section class="settings">
  <h2>Per user — rolling 12 months</h2>
  <p class="muted">Spend by the key each LLM call billed to (per-user attribution); the per-project and total sections span all keys.</p>
  <table class="usage-table">
<tr><th>User</th>${ownerHead}<th class="num">Total</th></tr>
${ownerRows}
</table>
  <div class="chart">${ownerChart}</div>
</section>
<section class="settings">
  <h2>By role — rolling 12 months</h2>
  <p class="muted">Where the money goes: LLM spend per agent role (groom / task / qa / summary / resolve).</p>
  <table class="usage-table">
<tr><th>Role</th><th class="num">Tokens in</th><th class="num">Tokens out</th><th class="num">Cost</th></tr>
${roleRows}
</table>
  <div class="chart">${roleChart}</div>
</section>
<section class="settings">
  <h2>Per project — rolling 12 months</h2>
  <table class="usage-table">
<tr><th>Project</th><th class="num">Completed items</th><th class="num">Spend</th></tr>
${projectRows}
</table>
  <div class="chart">${projectChart}</div>
</section>
<section class="settings">
  <h2>Per-task usage</h2>
  <form class="filters" method="get" action="/reports">
    <select name="project">
${opt("", "All projects", f.project === "")}
${data.projectOptions.map((p) => opt(String(p.id), p.name, f.project === String(p.id))).join("\n")}
    </select>
    <select name="state">
${opt("", "All states", f.state === "")}
${data.states.map((s) => opt(s, s, f.state === s)).join("\n")}
    </select>
    <select name="role">
${opt("", "All roles", f.role === "")}
${data.roles.map((r) => opt(r, r, f.role === r)).join("\n")}
    </select>
    <input type="search" name="q" value="${escapeHtml(f.q)}" placeholder="Search task title">
    <button type="submit">Filter</button>
  </form>
  <table class="usage-table">
<tr><th>Task</th><th>Project</th><th>Title</th><th>State</th><th class="num">Tokens in</th><th class="num">Tokens out</th><th class="num">Cost</th><th>By role</th></tr>
${taskRows}
</table>
</section>`;
}

export function errorPage(message: string): string {
  return `<p>${escapeHtml(message)}</p>`;
}

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
  #groom-chat { display: flex; gap: 0.5rem; align-items: flex-end; }
  #groom-chat textarea { flex: 1; }
  #groom-chat button { white-space: nowrap; }
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
    card.paused ? '<span class="badge">paused</span>' : ""
  }</div>
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
}

/** Projects list: name + short description, New project button + editor dialog. */
export function projectsPage(data: { projects: ProjectSummaryView[] }): string {
  const rows =
    data.projects.length > 0
      ? data.projects
          .map(
            (p) =>
              `<tr><td><a href="/projects/${p.id}">${escapeHtml(p.name)}</a></td><td>${escapeHtml(
                p.description || "—",
              )}</td></tr>`,
          )
          .join("\n")
      : `<tr><td colspan="2" class="muted">No projects yet — create one.</td></tr>`;
  return `<h1>Projects</h1>
<div class="page-actions"><button onclick="document.getElementById('project-editor').showModal()">New project</button></div>
<table class="project-list">
<tr><th>Name</th><th>Description</th></tr>
${rows}
</table>
${projectEditorDialog("/projects", { title: "New project", submitLabel: "Create project" })}`;
}

interface ProjectFormValues {
  name?: string | null;
  description?: string | null;
  goal?: string | null;
  repoUrl?: string | null;
  defaultBranch?: string | null;
  blogRepoUrl?: string | null;
  blogContentPath?: string | null;
  mediaPaths?: string[] | null;
  constraints?: string | null;
  architectureNotes?: string | null;
  notes?: string | null;
}

function field(
  label: string,
  name: string,
  value: string,
  opts: { textarea?: boolean; rows?: number; required?: boolean } = {},
): string {
  const req = opts.required ? " *" : "";
  if (opts.textarea) {
    return `<label>${label}${req}<textarea name="${name}" rows="${opts.rows ?? 2}"${
      opts.required ? " required" : ""
    }>${escapeHtml(value)}</textarea></label>`;
  }
  return `<label>${label}${req}<input name="${name}" value="${escapeHtml(value)}"${
    opts.required ? " required" : ""
  } maxlength="512"></label>`;
}

/**
 * Project editor popup (native <dialog>): create (action /projects) or
 * edit (action /projects/<id>, pre-filled).
 */
export function projectEditorDialog(
  action: string,
  opts: { title: string; submitLabel: string; values?: ProjectFormValues },
): string {
  const v = opts.values ?? {};
  return `<dialog id="project-editor">
<form method="post" action="${action}">
<h2>${escapeHtml(opts.title)}</h2>
${field("Name", "name", v.name ?? "", { required: true })}
${field("Description", "description", v.description ?? "", { textarea: true })}
${field("Goal", "goal", v.goal ?? "", { textarea: true })}
${field("Repo URL", "repo_url", v.repoUrl ?? "")}
${field("Default branch", "default_branch", v.defaultBranch ?? "")}
${field("Blog repo URL", "blog_repo_url", v.blogRepoUrl ?? "")}
${field("Blog content path", "blog_content_path", v.blogContentPath ?? "")}
${field("Media paths (comma-separated)", "media_paths", (v.mediaPaths ?? []).join(", "))}
${field("Constraints", "constraints", v.constraints ?? "", { textarea: true })}
${field("Architecture notes", "architecture_notes", v.architectureNotes ?? "", { textarea: true })}
${field("Notes", "notes", v.notes ?? "", { textarea: true })}
<div class="form-actions"><button type="submit">${escapeHtml(opts.submitLabel)}</button><button type="button" class="secondary" onclick="this.closest('dialog').close()">Cancel</button></div>
</form>
</dialog>`;
}

// ---------------------------------------------------------------------------
// Project page
// ---------------------------------------------------------------------------

export interface ProjectPageData {
  id: number;
  name: string;
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
 * Project page: settings + LLM state summary + the three pipeline columns
 * (Idea / Grooming / Icebox) + idea drop popup + edit dialog + the
 * completed/deployed items list (hidden by default, paginated —
 * requirements §9). Idea/Grooming cards link to the grooming chat page;
 * the Icebox column shows finalized specs (goal, kind, dependencies) with
 * multi-select + Move to Backlog.
 */
export function projectPage(data: ProjectPageData): string {
  const byState = (s: string) => data.ideas.filter((i) => i.state === s);
  const ideaText = new Map(data.ideas.map((i) => [i.id, i.text]));

  const pipelineCard = (i: ProjectPageData["ideas"][number], hint: string, badge?: string) =>
    `<a class="card card-link" href="/ideas/${i.id}/groom">
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
            return `<label class="card icebox-card">
  <div class="card-top"><input type="checkbox" name="idea_ids" value="${i.id}"><span class="tag">${escapeHtml(i.spec?.kind ?? "other")}</span></div>
  <div class="card-title">${escapeHtml(trunc(i.text, 90))}</div>
  ${goal}
  ${depsLine}
</label>`;
          })
          .join("\n")
      : `<p class="empty">—</p>`;
  const iceboxColumn = `<form method="post" action="/projects/${data.id}/icebox/move">
<section class="column"><h2>Icebox <span class="count">${iceboxItems.length}</span></h2>
${iceboxCards}
${
  iceboxItems.length > 0
    ? `<div class="icebox-move"><button type="submit">Move to Backlog</button></div>`
    : ""
}
</section>
</form>`;

  const settings: Array<[string, string]> = [
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
<div class="page-actions">
  <button onclick="document.getElementById('idea-drop').showModal()">New idea</button>
  <button onclick="document.getElementById('project-editor').showModal()">Edit project</button>
</div>
<section class="settings">
  <h2>Settings</h2>
  <dl>${dl || '<dd class="muted">—</dd>'}</dl>
  <h2 style="margin-top:1rem">State summary</h2>
  <p class="${data.stateSummary ? "" : "muted"}" style="margin:0;white-space:pre-wrap">${escapeHtml(
    data.stateSummary ?? "—",
  )}</p>
</section>
<div class="columns three">
${column("Idea", byState("idea"), "click to groom")}
${column("Grooming", byState("grooming"), "continue chat →", true)}
${iceboxColumn}
</div>
${completedSection}
<dialog id="idea-drop">
<form method="post" action="/projects/${data.id}/ideas">
<h2>New idea — ${escapeHtml(data.name)}</h2>
<label>Idea *<textarea name="text" rows="4" required></textarea></label>
<div class="form-actions"><button type="submit">Add idea</button><button type="button" class="secondary" onclick="this.closest('dialog').close()">Cancel</button></div>
</form>
</dialog>
${projectEditorDialog(`/projects/${data.id}`, {
    title: `Edit project — ${data.name}`,
    submitLabel: "Save changes",
    values: {
      name: data.name,
      description: data.description,
      goal: data.goal,
      repoUrl: data.repoUrl,
      defaultBranch: data.defaultBranch,
      blogRepoUrl: data.blogRepoUrl,
      blogContentPath: data.blogContentPath,
      mediaPaths: data.mediaPaths,
      constraints: data.constraints,
      architectureNotes: data.architectureNotes,
      notes: data.notes,
    },
  })}`;
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
 * Grooming chat page: message list, input (HTMX turn), and the
 * Accept / Cancel / Re-groom / Discard actions (one <form> each).
 */
export function groomPage(data: GroomPageData): string {
  const banner = data.turn.active
    ? `<div class="groom-banner"><span class="dot"></span>
  <div><strong>The agent is working on this idea</strong>${data.turn.label ? ` — ${escapeHtml(data.turn.label)}` : ""} (since ${new Date(data.turn.since ?? Date.now()).toLocaleTimeString()}).
  This can take several minutes — you can keep chatting; new messages will be queued.</div></div>`
    : "";
  const action = (action: string, label: string, cls = "") =>
    `<form method="post" action="${action}"><button type="submit"${cls ? ` class="${cls}"` : ""}>${label}</button></form>`;
  return `<h1>Grooming — ${escapeHtml(trunc(data.ideaText, 120))}</h1>
${banner}
<p class="muted">Project: <a href="/projects/${data.projectId}">${escapeHtml(data.projectName)}</a> · session persisted, tools + skills available (share URLs or images to analyze)</p>
<div class="page-actions">
  ${action(`/ideas/${data.ideaId}/groom/accept`, "Accept")}
  ${action(`/ideas/${data.ideaId}/groom/cancel`, "Cancel", "secondary")}
  ${action(`/ideas/${data.ideaId}/groom/re-groom`, "Re-groom", "secondary")}
  ${action(`/ideas/${data.ideaId}/discard`, "Discard", "danger")}
</div>
${groomMessagesFragment(data.ideaId, data.messages, data.turn)}
<form id="groom-chat" method="post" action="/ideas/${data.ideaId}/groom/messages"
  hx-post="/ideas/${data.ideaId}/groom/messages" hx-target="#groom-messages" hx-swap="beforeend">
  <textarea name="message" rows="2" required placeholder="Discuss the idea — ask questions, share links/images…"></textarea>
  <button type="submit">Send</button>
</form>`;
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
  /** Resolution dialog transcript (needs_attention only). */
  resolveMessages: Array<{ role: "user" | "assistant"; text: string }>;
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

/** Resolution dialog message fragment (the HTMX swap unit for #resolve-messages). */
export function resolveMessageFragment(role: "user" | "assistant", text: string): string {
  return groomMessageFragment(role, text);
}

/**
 * Task detail (PLAN.md §5: slide-over panel, post-MVP): state + workspace +
 * branch + last commit, spec, usage so far, and the live log (2s HTMX
 * auto-refresh while running). Rendered two ways:
 *   - as the slide-over panel body (GET /tasks/<id>?panel=1, HTMX swap unit
 *     into #task-panel on the board page) — the normal path; and
 *   - as a full page (GET /tasks/<id>) for deep links / direct navigation.
 * Needs Attention tasks show a what-happened panel (failure reason, QA
 * feedback) + the resolution dialog (chat + Accept → Backlog).
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
    ["Workspace", data.workspace ?? "—"],
    ["Branch", data.branch ?? "—"],
    ["Last commit", data.lastCommit ?? "—"],
    ["Last activity", data.lastActivityAt ? fmtTs(data.lastActivityAt) : "—"],
    ["QA rounds", String(data.qaRounds)],
    ["Waiting on", data.waitingOn.join(", ") || "—"],
  ];
  const dl = details.map(([k, v]) => `<dt>${k}</dt><dd>${escapeHtml(v)}</dd>`).join("\n");
  const steps =
    data.steps.length > 0 ? `<ol>${data.steps.map((s) => `<li>${escapeHtml(s)}</li>`).join("")}</ol>` : "";
  const acceptance =
    data.acceptance.length > 0
      ? `<ul>${data.acceptance.map((a) => `<li>${escapeHtml(a)}</li>`).join("")}</ul>`
      : "";
  const resolution = data.resolution
    ? `<h2 style="margin-top:1rem">Accepted resolution plan</h2><pre class="resolution">${escapeHtml(data.resolution)}</pre>`
    : "";
  // Manual control (Slice 5): Stop/Resume for running tasks (paused is an
  // orthogonal flag), Retry deploy for deploy / needs_attention tasks.
  const controls: string[] = [];
  if (data.state === "running" && !data.paused) {
    controls.push(
      `<form hx-post="/tasks/${data.id}/stop" hx-target="body"><button type="submit">Stop (pause)</button></form>`,
    );
  }
  if (data.state === "running" && data.paused) {
    controls.push(
      `<form hx-post="/tasks/${data.id}/resume" hx-target="body"><button type="submit">Resume</button></form>`,
    );
  }
  if (data.state === "deploy" || data.state === "needs_attention") {
    controls.push(
      `<form hx-post="/tasks/${data.id}/retry-deploy" hx-target="body"><button type="submit">Retry deploy</button></form>`,
    );
  }
  const controlsHtml = controls.length > 0 ? `<div class="page-actions">${controls.join(" ")}</div>` : "";
  const needsAttention = data.state === "needs_attention";
  const failed = needsAttention
    ? `<section class="settings"><h2>What happened</h2>
  <p style="white-space:pre-wrap">${escapeHtml(data.failureReason ?? "(no failure reason recorded)")}</p>
  ${data.qaFeedback ? `<p class="muted" style="white-space:pre-wrap"><strong>QA feedback:</strong> ${escapeHtml(data.qaFeedback)}</p>` : ""}
  <p class="muted" style="margin:0">See the log tail below for the last activity before the failure.</p>
  </section>`
    : "";
  const resolveDialog = needsAttention
    ? `<section class="settings">
  <h2>Resolution dialog</h2>
  <p class="muted">Chat with the resolution agent (it has the failure context${data.workspace ? ", the task spec, and workspace tools" : ", and the task spec"}). Accept to capture the plan and send the task back to the backlog — it resumes from the last commit with the plan injected and QA rounds reset.</p>
  <div id="resolve-messages">
${data.resolveMessages.length > 0 ? data.resolveMessages.map((m) => resolveMessageFragment(m.role, m.text)).join("\n") : `<span class="muted">No messages yet — ask the agent what went wrong.</span>`}
  </div>
  <form hx-post="/tasks/${data.id}/resolve/messages" hx-target="#resolve-messages" hx-swap="beforeend" style="display:flex;gap:0.5rem;margin-top:0.5rem">
    <textarea name="message" rows="2" style="flex:1" placeholder="e.g. what do you think went wrong?" required></textarea>
    <button type="submit">Send</button>
  </form>
  <form hx-post="/tasks/${data.id}/resolve/accept" hx-target="body" style="margin-top:0.5rem">
    <button type="submit">Accept plan → Backlog</button>
  </form>
  </section>`
    : "";
  return `${closeBtn}<h1>Task #${data.id} — ${escapeHtml(trunc(data.title, 120))} <span class="badge state-${escapeHtml(data.state)}">${escapeHtml(data.state)}</span>${
    data.paused ? ' <span class="badge">paused</span>' : ""
  }</h1>
<p class="muted"><a href="/">← Board</a> · <a href="/projects/${data.project.id}">${escapeHtml(data.project.name)}</a> · kind ${escapeHtml(data.kind)}</p>
${controlsHtml}
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
${resolveDialog}
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
  months: Array<{ label: string; short: string; spend: number }>;
  /** Total $ spend across the rolling 12 months (callout). */
  total: number;
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

/**
 * Project services (requirements §6): CRUD over the projects table.
 *
 * - `name` is unique (case-sensitive on SQLite; the MySQL unique index uses
 *   the default collation) — duplicates are rejected with 409.
 * - `stateSummary` is LLM-maintained (updated by the summary session after
 *   each deploy) and is read-only through this API.
 * - create: optional fields default to "" / null.
 * - update: only provided fields change; an empty string clears a field.
 */
import { asc, desc, eq, and, ne } from "drizzle-orm";
import { type IdeaSpec, type ProjectRow } from "../db/schema.js";
import { ideas, projects, tasks } from "../db/tables.js";
import { isUniqueViolation, ServiceError, type Db } from "./common.js";

export type Project = ProjectRow;

export interface ProjectSummary {
  id: number;
  name: string;
  description: string;
  /** Owner (caller identity of the creating mutation); '' = unattributed (legacy). */
  owner: string;
}

/** Project fields accepted by create/update (requirements §6). */
export interface ProjectInput {
  name?: string;
  description?: string;
  goal?: string;
  repoUrl?: string | null;
  defaultBranch?: string | null;
  blogRepoUrl?: string | null;
  blogContentPath?: string | null;
  mediaPaths?: string[] | null;
  constraints?: string | null;
  architectureNotes?: string | null;
  notes?: string | null;
}

const MAX_NAME = 255;

/** Normalized fields; `undefined` = "not provided" (keep on update). */
interface Normalized {
  name?: string;
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

function strOrNull(v: string | null | undefined): string | null | undefined {
  if (v === undefined) return undefined;
  const t = (v ?? "").trim();
  return t === "" ? null : t;
}

/** Like strOrNull, but empty → "" (for NOT NULL columns: description, goal). */
function strOrEmpty(v: string | null | undefined): string | null | undefined {
  if (v === undefined) return undefined;
  return (v ?? "").trim();
}

function normalize(input: ProjectInput, requireName: boolean): Normalized {
  const name = strOrNull(input.name);
  if (requireName && (name === undefined || name === null)) {
    throw new ServiceError(400, "name is required");
  }
  if (name !== undefined && name !== null && name.length > MAX_NAME) {
    throw new ServiceError(400, `name must be at most ${MAX_NAME} characters`);
  }
  const mediaPaths =
    input.mediaPaths === undefined
      ? undefined
      : (() => {
          const filtered = (input.mediaPaths ?? []).map((p) => p.trim()).filter((p) => p !== "");
          return filtered.length > 0 ? filtered : null;
        })();
  return {
    name: name ?? undefined,
    description: strOrEmpty(input.description),
    goal: strOrEmpty(input.goal),
    repoUrl: strOrNull(input.repoUrl),
    defaultBranch: strOrNull(input.defaultBranch),
    blogRepoUrl: strOrNull(input.blogRepoUrl),
    blogContentPath: strOrNull(input.blogContentPath),
    mediaPaths,
    constraints: strOrNull(input.constraints),
    architectureNotes: strOrNull(input.architectureNotes),
    notes: strOrNull(input.notes),
  };
}

/** All projects (id, name, description, owner), ordered by name. */
export async function listProjects(db: Db): Promise<ProjectSummary[]> {
  return db
    .select({ id: projects.id, name: projects.name, description: projects.description, owner: projects.owner })
    .from(projects)
    .orderBy(asc(projects.name));
}

/** One project by id, or undefined. */
export async function getProject(db: Db, id: number): Promise<Project | undefined> {
  const [row] = await db.select().from(projects).where(eq(projects.id, id)).limit(1);
  return row;
}

/** Create a project. 400 on invalid input, 409 on duplicate name.
 * `owner` = caller identity of the creating mutation (MCP key → user name). */
export async function createProject(db: Db, input: ProjectInput, owner = ""): Promise<Project> {
  const n = normalize(input, true);
  const now = Date.now();
  try {
    await db.insert(projects).values({
      name: n.name!,
      description: n.description ?? "",
      goal: n.goal ?? "",
      repoUrl: n.repoUrl ?? null,
      defaultBranch: n.defaultBranch ?? null,
      blogRepoUrl: n.blogRepoUrl ?? null,
      blogContentPath: n.blogContentPath ?? null,
      mediaPaths: n.mediaPaths ?? null,
      constraints: n.constraints ?? null,
      architectureNotes: n.architectureNotes ?? null,
      notes: n.notes ?? null,
      owner: owner ?? "",
      createdAt: now,
      updatedAt: now,
    });
  } catch (err) {
    if (isUniqueViolation(err)) {
      throw new ServiceError(409, `project name "${n.name}" already exists`);
    }
    throw err;
  }
  // Name is unique: fetch the row we just inserted (driver-agnostic —
  // MySQL has no RETURNING clause).
  const [row] = await db
    .select()
    .from(projects)
    .where(eq(projects.name, n.name!))
    .orderBy(desc(projects.id))
    .limit(1);
  if (!row) throw new ServiceError(500, "project insert did not persist");
  return row;
}

/**
 * Project status for the MCP `project_status` tool (PLAN.md §5/§10):
 * the project spec incl. the LLM-maintained state summary, the icebox
 * listing (finalized specs + LLM-identified deps), and task counts per
 * board state. undefined when the project does not exist.
 */
export interface ProjectStatus {
  id: number;
  name: string;
  description: string;
  goal: string;
  /** Owner (caller identity of the creating mutation); '' = unattributed (legacy). */
  owner: string;
  repoUrl: string | null;
  defaultBranch: string | null;
  blogRepoUrl: string | null;
  blogContentPath: string | null;
  mediaPaths: string[] | null;
  constraints: string | null;
  architectureNotes: string | null;
  notes: string | null;
  /** LLM-maintained current completion state (updated on each deploy). */
  stateSummary: string | null;
  /** Icebox listing: finalized specs ready to move to the backlog. */
  icebox: Array<{
    id: number;
    text: string;
    spec: IdeaSpec | null;
    dependsOn: number[] | null;
  }>;
  /** Task counts per board state (backlog/running/deploy/done/needs_attention). */
  taskCounts: Record<string, number>;
}

export async function getProjectStatus(db: Db, id: number): Promise<ProjectStatus | undefined> {
  const [project] = await db.select().from(projects).where(eq(projects.id, id)).limit(1);
  if (!project) return undefined;
  const [iceboxRows, taskRows] = await Promise.all([
    db
      .select()
      .from(ideas)
      .where(and(eq(ideas.projectId, id), eq(ideas.state, "icebox")))
      .orderBy(asc(ideas.id)),
    db.select({ state: tasks.state }).from(tasks).where(eq(tasks.projectId, id)),
  ]);
  const taskCounts: Record<string, number> = {};
  for (const t of taskRows) taskCounts[t.state] = (taskCounts[t.state] ?? 0) + 1;
  return {
    id: project.id,
    name: project.name,
    description: project.description,
    goal: project.goal,
    owner: project.owner,
    repoUrl: project.repoUrl,
    defaultBranch: project.defaultBranch,
    blogRepoUrl: project.blogRepoUrl,
    blogContentPath: project.blogContentPath,
    mediaPaths: project.mediaPaths,
    constraints: project.constraints,
    architectureNotes: project.architectureNotes,
    notes: project.notes,
    stateSummary: project.stateSummary,
    icebox: iceboxRows.map((i) => ({ id: i.id, text: i.text, spec: i.spec, dependsOn: i.dependsOn })),
    taskCounts,
  };
}

/**
 * Update a project by id. Only provided fields change; `name` may be
 * provided to rename (subject to the uniqueness check). Returns undefined
 * when the project does not exist. 409 on duplicate name.
 */
export async function updateProject(
  db: Db,
  id: number,
  input: ProjectInput,
): Promise<Project | undefined> {
  const existing = await getProject(db, id);
  if (!existing) return undefined;

  const n = normalize(input, false);
  if (n.name !== undefined && n.name !== existing.name) {
    const clash = await db
      .select({ id: projects.id })
      .from(projects)
      .where(and(eq(projects.name, n.name), ne(projects.id, id)))
      .limit(1);
    if (clash.length > 0) {
      throw new ServiceError(409, `project name "${n.name}" already exists`);
    }
  }

  const set: Record<string, unknown> = { updatedAt: Date.now() };
  for (const [key, value] of Object.entries(n)) {
    if (value !== undefined) set[key] = value;
  }
  await db.update(projects).set(set).where(eq(projects.id, id));
  return await getProject(db, id);
}

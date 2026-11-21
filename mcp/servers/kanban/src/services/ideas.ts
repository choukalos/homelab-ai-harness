/**
 * Idea services (requirements §5): raw ideas scoped to a project.
 *
 * Slice 1: drop + listing. Slice 2: grooming/icebox transitions live in
 * src/agent/grooming.ts (state machine over the same ideas table) and
 * src/services/icebox.ts (Move to Backlog).
 */
import { and, asc, desc, eq, ne } from "drizzle-orm";
import { type IdeaRow } from "../db/schema.js";
import { ideas, projects } from "../db/tables.js";
import { ServiceError, type Db } from "./common.js";

export type Idea = IdeaRow & { projectName: string };

/**
 * List ideas (with their project name), optionally filtered by project.
 * Ordered by id (drop order). Discarded ideas are excluded (soft-deleted:
 * they disappear from every view — the state is kept for the audit trail).
 */
export async function listIdeas(db: Db, projectId?: number): Promise<Idea[]> {
  const base = db
    .select({ idea: ideas, projectName: projects.name })
    .from(ideas)
    .innerJoin(projects, eq(ideas.projectId, projects.id));
  const rows =
    projectId !== undefined
      ? await base
          .where(and(ne(ideas.state, "discarded"), eq(ideas.projectId, projectId)))
          .orderBy(asc(ideas.id))
      : await base.where(ne(ideas.state, "discarded")).orderBy(asc(ideas.id));
  return rows.map((r) => ({ ...r.idea, projectName: r.projectName }));
}

/**
 * One idea by id (with its project name), or undefined.
 */
export async function getIdea(db: Db, id: number): Promise<Idea | undefined> {
  const [r] = await db
    .select({ idea: ideas, projectName: projects.name })
    .from(ideas)
    .innerJoin(projects, eq(ideas.projectId, projects.id))
    .where(eq(ideas.id, id))
    .limit(1);
  return r ? { ...r.idea, projectName: r.projectName } : undefined;
}

/**
 * Drop a raw idea into a project (state `idea`).
 * 400 on empty text, 404 on unknown project.
 * `owner` = caller identity of the creating mutation (MCP key → user name).
 */
export async function addIdea(db: Db, projectId: number, text: string, owner = ""): Promise<Idea> {
  const t = (text ?? "").trim();
  if (t === "") throw new ServiceError(400, "idea text is required");
  const [proj] = await db
    .select({ id: projects.id })
    .from(projects)
    .where(eq(projects.id, projectId))
    .limit(1);
  if (!proj) throw new ServiceError(404, `project ${projectId} not found`);

  const now = Date.now();
  await db.insert(ideas).values({
    projectId,
    text: t,
    state: "idea",
    spec: null,
    dependsOn: [],
    owner: owner ?? "",
    createdAt: now,
    updatedAt: now,
  });
  // Single-user app: the newest idea of the project is the one we inserted.
  const [row] = await db
    .select()
    .from(ideas)
    .where(eq(ideas.projectId, projectId))
    .orderBy(desc(ideas.id))
    .limit(1);
  if (!row) throw new ServiceError(500, "idea insert did not persist");
  const [projRow] = await db
    .select({ name: projects.name })
    .from(projects)
    .where(eq(projects.id, projectId))
    .limit(1);
  return { ...row, projectName: projRow?.name ?? "" };
}

/**
 * Edit an idea's text (MCP edit_idea) — fix typos / tweak scope before
 * grooming. Only the `idea` state is editable: grooming → the spec is being
 * generated from the text; icebox → the spec is final; moved → has a task;
 * discarded → soft-deleted. Only `text` changes (spec/depends_on are
 * LLM-generated at grooming). 404 unknown idea, 409 wrong state, 400
 * empty text.
 */
export async function editIdea(db: Db, ideaId: number, text: string): Promise<Idea> {
  const t = (text ?? "").trim();
  if (t === "") throw new ServiceError(400, "idea text is required");
  const [idea] = await db.select().from(ideas).where(eq(ideas.id, ideaId)).limit(1);
  if (!idea) throw new ServiceError(404, `idea ${ideaId} not found`);
  if (idea.state !== "idea") {
    throw new ServiceError(
      409,
      `idea ${ideaId} is in state "${idea.state}" — only ideas in the "idea" state can be edited ` +
        `(grooming/icebox specs are generated from the text at grooming)`,
    );
  }
  await db
    .update(ideas)
    .set({ text: t, updatedAt: Date.now() })
    .where(eq(ideas.id, ideaId));
  return (await getIdea(db, ideaId))!;
}

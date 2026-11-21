/**
 * Shared service-layer primitives (PLAN.md §7: transport-agnostic service
 * layer; both the REST API and the MCP tools call into these).
 */
import type { BetterSQLite3Database } from "drizzle-orm/better-sqlite3";

/**
 * Driver-agnostic db handle for service queries. The column sets are
 * identical across drivers (src/db/schema.ts), so queries built from the
 * shared schema objects generate compatible SQL for both backends; the
 * mysql drizzle instance is cast to this type at the service boundary
 * (createKanbanServices) — both instances expose the same query methods.
 */
export type Db = BetterSQLite3Database<any>;

/**
 * Service-layer error carrying the HTTP status the REST layer should
 * respond with (400 validation, 404 not found, 409 conflict, ...).
 */
export class ServiceError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ServiceError";
  }
}

/** True for unique-constraint violations on either driver. */
export function isUniqueViolation(err: unknown): boolean {
  const e = err as { code?: string; errno?: number } | null;
  return e?.code === "SQLITE_CONSTRAINT_UNIQUE" || e?.errno === 1062;
}

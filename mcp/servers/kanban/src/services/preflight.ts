/**
 * Spec-path reachability preflight (proposal:
 * tier2-kanban-remote-client-file-intake, part 3/3).
 *
 * At move_to_backlog and start_task, extract local file paths and media
 * URLs from the task spec and check each reference against the execution
 * environment (the mcp_kanban container's mounted roots; URLs via bounded
 * HTTP HEAD). Unreachable references return a structured advisory warning
 * on the tool result — fail fast at task creation, not after two QA
 * rounds. Strict mode (KANBAN_PREFLIGHT_STRICT=1) refuses the move/start
 * instead.
 *
 * Advisory by design: specs may legitimately reference paths created by
 * earlier tasks in the same project (shared state dirs) — the executor's
 * own P0 gate remains the source of truth.
 */
import type { IdeaSpec } from "../db/schema.js";
import { ServiceError } from "./common.js";
import { checkRef, type FetchLike, type ReachabilityResult } from "./reachability.js";

/** Env var enabling strict preflight (1/true). */
export const PREFLIGHT_STRICT_ENV = "KANBAN_PREFLIGHT_STRICT";

/** Strict mode when KANBAN_PREFLIGHT_STRICT is 1/true (case-insensitive). */
export function isPreflightStrict(env: NodeJS.ProcessEnv = process.env): boolean {
  const v = (env[PREFLIGHT_STRICT_ENV] ?? "").trim().toLowerCase();
  return v === "1" || v === "true";
}

/** The spec's free-text fields, in order (goal, steps, acceptance, notes). */
export function specText(spec: IdeaSpec | null | undefined): string {
  if (!spec) return "";
  return [spec.goal, ...(spec.steps ?? []), ...(spec.acceptance ?? []), spec.notes ?? ""].join("\n");
}

/**
 * Extract candidate input references from free-form spec text: http(s)
 * URLs and absolute local paths (≥ 2 path segments; `~/...` home-relative
 * forms included). Relative paths and single-segment tokens are ignored
 * (prose like "the /data dir" is not an input reference). Deduped,
 * first-seen order.
 */
export function extractSpecRefs(text: string): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  const re =
    /(https?:\/\/[^\s"'<>()\[\]{}]+)|(?:~\/[A-Za-z0-9._-]+(?:\/[A-Za-z0-9._-]+)+)|(?:\/[A-Za-z0-9._-]+(?:\/[A-Za-z0-9._-]+)+)/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    let ref = m[1] ?? m[0];
    if (m[1]) ref = ref.replace(/[.,;:!?]+$/, ""); // trailing prose punctuation
    if (ref === "" || seen.has(ref)) continue;
    seen.add(ref);
    out.push(ref);
  }
  return out;
}

/** Outcome of a spec preflight pass. */
export interface PreflightReport {
  /** Every extracted reference, with its reachability outcome. */
  checked: ReachabilityResult[];
  /** The unreachable subset (empty = clean spec). */
  unreachable: ReachabilityResult[];
}

export interface PreflightOpts {
  /** Mounted roots for path checks (default: the container's MOUNTED_ROOTS). */
  roots?: readonly string[];
  /** Bounded HTTP HEAD timeout for URL checks (default 10s). */
  timeoutMs?: number;
  /** HTTP client for URL checks (default global fetch). */
  fetchImpl?: FetchLike;
  /** Strict: throw ServiceError(409) when any reference is unreachable. */
  strict?: boolean;
}

/**
 * Check a spec's input references: extract URLs + absolute paths from the
 * spec's text fields and check each (in parallel; every URL check is
 * timeout-bounded). With `strict`, any unreachable reference throws
 * ServiceError(409) listing them.
 */
export async function preflightSpec(
  spec: IdeaSpec | null | undefined,
  opts: PreflightOpts = {},
): Promise<PreflightReport> {
  return preflightText(specText(spec), opts);
}

/** Preflight across several specs (move_to_backlog takes several ideas). */
export async function preflightSpecs(
  specs: Array<IdeaSpec | null | undefined>,
  opts: PreflightOpts = {},
): Promise<PreflightReport> {
  return preflightText(specs.map(specText).join("\n"), opts);
}

async function preflightText(text: string, opts: PreflightOpts): Promise<PreflightReport> {
  const refs = extractSpecRefs(text);
  const checked = await Promise.all(refs.map((ref) => checkRef(ref, opts)));
  const unreachable = checked.filter((r) => !r.reachable);
  if (opts.strict && unreachable.length > 0) {
    throw new ServiceError(
      409,
      `preflight strict: ${unreachable.length} unreachable spec reference(s): ` +
        unreachable.map((r) => `${r.ref} (${r.reason})`).join("; "),
    );
  }
  return { checked, unreachable };
}

/** The structured advisory warning attached to a tool result. */
export interface PreflightWarning {
  warning: string;
  unreachable: Array<{ ref: string; kind: "url" | "path"; reason: string }>;
}

/**
 * Attach the structured advisory warning to a tool result (only when there
 * are unreachable references — a clean spec adds nothing). The return type
 * always carries the optional `preflight` field so callers can inspect it
 * uniformly (absent when the report is clean).
 */
export function withPreflightWarning<T extends object>(
  result: T,
  report: PreflightReport,
): T & { preflight?: PreflightWarning } {
  if (report.unreachable.length === 0) return result as T & { preflight?: PreflightWarning };
  return {
    ...result,
    preflight: {
      warning:
        "spec references unreachable from the executor — stage them (stage_file for small files, " +
        "stage_ref for media) or fix the paths before starting; advisory unless KANBAN_PREFLIGHT_STRICT=1",
      unreachable: report.unreachable.map((r) => ({ ref: r.ref, kind: r.kind, reason: r.reason })),
    },
  };
}

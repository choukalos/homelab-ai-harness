/**
 * Spec-reference reachability (proposal:
 * tier2-kanban-remote-client-file-intake, part 2/3): checks whether a local
 * file path or media URL cited in a task spec is reachable from the
 * execution environment (the mcp_kanban container).
 *
 * - Local paths: reachable only when they exist under one of the container's
 *   mounted roots (/files, /workspace, /media-store, /publish, /data).
 *   Client/host paths (~/Code/..., /home/chuck/...) are unreachable by
 *   construction — that is the gap the durable file store + stage_ref close.
 * - URLs: bounded HTTP HEAD → 200 (default 10s timeout).
 *
 * Consumers: stage_ref (reachability validated at registration) and the
 * spec-path preflight (move_to_backlog / start_task).
 */
import { stat } from "node:fs/promises";

/** Container mounted roots visible to the task executor. */
export const MOUNTED_ROOTS = ["/files", "/workspace", "/media-store", "/publish", "/data"] as const;
/** NAS media store mount (lego share; media inputs live here). */
export const MEDIA_STORE_MOUNT = "/media-store";
/** Bounded HTTP HEAD timeout for URL reachability (ms). */
export const URL_CHECK_TIMEOUT_MS = 10_000;

export type FetchLike = typeof fetch;

export interface ReachabilityResult {
  /** The reference as given (trimmed). */
  ref: string;
  kind: "url" | "path";
  reachable: boolean;
  /** Why it is unreachable ("" when reachable). */
  reason: string;
}

/** True for http(s) URLs (the only URL forms the executor can fetch). */
export function isHttpUrl(ref: string): boolean {
  try {
    const u = new URL(ref);
    return u.protocol === "http:" || u.protocol === "https:";
  } catch {
    return false;
  }
}

/**
 * The mounted root `p` is under (longest match wins), or null when the path
 * is not absolute / not under any root. Matching is root-boundary aware
 * (`/workspace-evil` is NOT under `/workspace`).
 */
export function rootForPath(p: string, roots: readonly string[] = MOUNTED_ROOTS): string | null {
  if (!p.startsWith("/")) return null;
  let best: string | null = null;
  for (const raw of roots) {
    const root = raw.endsWith("/") ? raw.slice(0, -1) : raw;
    if (root === "" ) continue;
    if (p === root || p.startsWith(root + "/")) {
      if (best === null || root.length > best.length) best = root;
    }
  }
  return best;
}

/**
 * Local path reachability: the path exists (file or directory) under one of
 * the mounted roots. A path outside every root is unreachable (client/host
 * path — the executor cannot see it).
 */
export async function checkLocalPath(
  ref: string,
  opts: { roots?: readonly string[] } = {},
): Promise<ReachabilityResult> {
  const roots = opts.roots ?? MOUNTED_ROOTS;
  const root = rootForPath(ref, roots);
  if (root === null) {
    return {
      ref,
      kind: "path",
      reachable: false,
      reason: `not under a mounted root (${roots.join(", ")}) — client/host path is not visible to the executor`,
    };
  }
  try {
    await stat(ref);
    return { ref, kind: "path", reachable: true, reason: "" };
  } catch (err) {
    const code = (err as NodeJS.ErrnoException).code ?? "stat failed";
    return { ref, kind: "path", reachable: false, reason: `does not exist under ${root} (${code})` };
  }
}

/** URL reachability: bounded HTTP HEAD → 200. */
export async function checkUrl(
  ref: string,
  opts: { timeoutMs?: number; fetchImpl?: FetchLike } = {},
): Promise<ReachabilityResult> {
  const timeoutMs = opts.timeoutMs ?? URL_CHECK_TIMEOUT_MS;
  const doFetch = opts.fetchImpl ?? fetch;
  let res: Response;
  try {
    res = await doFetch(ref, { method: "HEAD", signal: AbortSignal.timeout(timeoutMs) });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return { ref, kind: "url", reachable: false, reason: `HEAD failed: ${msg}` };
  }
  if (res.status === 200) {
    return { ref, kind: "url", reachable: true, reason: "" };
  }
  return { ref, kind: "url", reachable: false, reason: `HTTP ${res.status}${res.statusText ? ` ${res.statusText}` : ""}` };
}

/** Dispatch a reference: http(s) URL → HEAD check; anything else → local path check. */
export async function checkRef(
  ref: string,
  opts: { roots?: readonly string[]; timeoutMs?: number; fetchImpl?: FetchLike } = {},
): Promise<ReachabilityResult> {
  const trimmed = (ref ?? "").trim();
  if (isHttpUrl(trimmed)) return checkUrl(trimmed, opts);
  return checkLocalPath(trimmed, opts);
}

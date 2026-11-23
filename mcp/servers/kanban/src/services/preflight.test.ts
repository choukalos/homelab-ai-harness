/**
 * Tests for the spec-path reachability preflight (proposal:
 * tier2-kanban-remote-client-file-intake, part 3/3): reference extraction
 * (path + URL forms), reachability outcomes (mocked fetch, temp roots),
 * strict mode, and the advisory-warning attachment.
 */
import assert from "node:assert";
import { test } from "node:test";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import type { IdeaSpec } from "../db/schema.js";
import { ServiceError } from "./common.js";
import {
  PREFLIGHT_STRICT_ENV,
  extractSpecRefs,
  isPreflightStrict,
  preflightSpec,
  preflightSpecs,
  specText,
  withPreflightWarning,
} from "./preflight.js";

const spec = (over: Partial<IdeaSpec> = {}): IdeaSpec => ({
  goal: "g",
  steps: [],
  acceptance: [],
  kind: "code",
  ...over,
});

/** A controllable fetch mock: status (or throw when `fail`). */
function mockFetch(status: number, fail = false) {
  return (async (_url: string, _init?: RequestInit) => {
    if (fail) throw new Error("HEAD failed: boom");
    return new Response(null, { status });
  }) as typeof fetch;
}

// ---------------------------------------------------------------------------
// specText + extractSpecRefs
// ---------------------------------------------------------------------------

test("specText: joins goal/steps/acceptance/notes; null spec → empty", () => {
  assert.equal(specText(null), "");
  assert.equal(specText(undefined), "");
  const t = specText(spec({ goal: "g", steps: ["s1", "s2"], acceptance: ["a1"], notes: "n" }));
  assert.deepEqual(t.split("\n"), ["g", "s1", "s2", "a1", "n"]);
});

test("extractSpecRefs: URLs (http/https) with trailing punctuation stripped", () => {
  const refs = extractSpecRefs(
    "cite https://choukalos.com/files/a.mp4 and http://x.y/z.js, then done.",
  );
  assert.deepEqual(refs, ["https://choukalos.com/files/a.mp4", "http://x.y/z.js"]);
});

test("extractSpecRefs: absolute + home-relative paths; relative and single-segment ignored", () => {
  const refs = extractSpecRefs(
    "scripts at /files/7/potato-wars-v2/frozen.py, ~/Code/media-film/potato-wars-v2/evolved.py, " +
      "/media-store/potato-wars-v2/ref.mp4; local ./rel.py and /single are not refs",
  );
  assert.deepEqual(refs, [
    "/files/7/potato-wars-v2/frozen.py",
    "~/Code/media-film/potato-wars-v2/evolved.py",
    "/media-store/potato-wars-v2/ref.mp4",
  ]);
});

test("extractSpecRefs: dedupes across fields, first-seen order", () => {
  const refs = extractSpecRefs("/files/7/a.py\nand again /files/7/a.py plus https://x.y/z.js");
  assert.deepEqual(refs, ["/files/7/a.py", "https://x.y/z.js"]);
});

test("extractSpecRefs: empty text → no refs", () => {
  assert.deepEqual(extractSpecRefs(""), []);
  assert.deepEqual(extractSpecRefs("no refs here, just prose"), []);
});

// ---------------------------------------------------------------------------
// isPreflightStrict
// ---------------------------------------------------------------------------

test("isPreflightStrict: unset/0/false → false; 1/true → true", () => {
  assert.equal(isPreflightStrict({}), false);
  assert.equal(isPreflightStrict({ [PREFLIGHT_STRICT_ENV]: "0" }), false);
  assert.equal(isPreflightStrict({ [PREFLIGHT_STRICT_ENV]: "false" }), false);
  assert.equal(isPreflightStrict({ [PREFLIGHT_STRICT_ENV]: "yes" }), false);
  assert.equal(isPreflightStrict({ [PREFLIGHT_STRICT_ENV]: "1" }), true);
  assert.equal(isPreflightStrict({ [PREFLIGHT_STRICT_ENV]: "TRUE" }), true);
});

// ---------------------------------------------------------------------------
// preflightSpec — reachability outcomes
// ---------------------------------------------------------------------------

test("preflightSpec: clean spec (reachable path under root + 200 URL) → no unreachable", async () => {
  const dir = mkdtempSync(path.join(tmpdir(), "ai-kanban-preflight-"));
  const filesRoot = path.join(dir, "files");
  mkdirSync(path.join(filesRoot, "7"), { recursive: true });
  writeFileSync(path.join(filesRoot, "7", "frozen.py"), "x");
  const frozen = path.join(filesRoot, "7", "frozen.py");

  const report = await preflightSpec(
    spec({
      goal: `run ${frozen}`,
      steps: ["cite https://choukalos.com/files/a.mp4"],
    }),
    { roots: [filesRoot], fetchImpl: mockFetch(200) },
  );
  assert.equal(report.checked.length, 2);
  assert.equal(report.unreachable.length, 0);
});

test("preflightSpec: client path + dead URL → unreachable with reasons", async () => {
  const report = await preflightSpec(
    spec({
      goal: "~/Code/media-film/potato-wars-v2/frozen.py",
      steps: ["cite https://choukalos.com/files/gone.mp4"],
    }),
    { roots: ["/files"], fetchImpl: mockFetch(404) },
  );
  assert.equal(report.unreachable.length, 2);
  const byRef = new Map(report.unreachable.map((r) => [r.ref, r]));
  const clientPath = byRef.get("~/Code/media-film/potato-wars-v2/frozen.py");
  const deadUrl = byRef.get("https://choukalos.com/files/gone.mp4");
  assert.equal(clientPath?.kind, "path");
  assert.match(clientPath?.reason ?? "", /not under a mounted root/);
  assert.equal(deadUrl?.kind, "url");
  assert.match(deadUrl?.reason ?? "", /HTTP 404/);
});

test("preflightSpec: fetch failure → unreachable (never throws)", async () => {
  const report = await preflightSpec(
    spec({ goal: "https://choukalos.com/files/x.mp4" }),
    { fetchImpl: mockFetch(0, true) },
  );
  assert.equal(report.unreachable.length, 1);
  assert.match(report.unreachable[0]!.reason, /HEAD failed/);
});

test("preflightSpec: nonexistent path under a mounted root → unreachable", async () => {
  const dir = mkdtempSync(path.join(tmpdir(), "ai-kanban-preflight-"));
  const report = await preflightSpec(
    spec({ goal: path.join(dir, "files", "7", "missing.py") }),
    { roots: [path.join(dir, "files")] },
  );
  assert.equal(report.unreachable.length, 1);
  assert.match(report.unreachable[0]!.reason, /does not exist/);
});

test("preflightSpec: spec with no refs → empty report", async () => {
  const report = await preflightSpec(spec({}), {});
  assert.deepEqual(report, { checked: [], unreachable: [] });
});

// ---------------------------------------------------------------------------
// preflightSpec — strict mode
// ---------------------------------------------------------------------------

test("preflightSpec strict: unreachable → ServiceError 409 listing refs; clean → passes", async () => {
  await assert.rejects(
    preflightSpec(spec({ goal: "~/Code/x/y.py" }), { roots: ["/files"], strict: true }),
    (err: unknown) =>
      err instanceof ServiceError &&
      err.status === 409 &&
      /preflight strict/.test(err.message) &&
      /~\/Code\/x\/y\.py/.test(err.message),
  );
  const clean = await preflightSpec(spec({}), { strict: true });
  assert.equal(clean.unreachable.length, 0);
});

test("preflightSpecs: aggregates refs across several specs (deduped)", async () => {
  const report = await preflightSpecs(
    [
      spec({ goal: "~/Code/a/b.py" }),
      spec({ goal: "~/Code/a/b.py again", steps: ["https://x.y/z.js"] }),
      null,
    ],
    { roots: ["/files"], fetchImpl: mockFetch(200) },
  );
  assert.equal(report.checked.length, 2, "deduped across specs");
  assert.equal(report.unreachable.length, 1);
  assert.equal(report.unreachable[0]!.ref, "~/Code/a/b.py");
});

// ---------------------------------------------------------------------------
// withPreflightWarning
// ---------------------------------------------------------------------------

test("withPreflightWarning: clean report → result untouched (same reference)", () => {
  const base = { tasks: [{ id: 1 }] };
  const clean = withPreflightWarning(base, { checked: [], unreachable: [] });
  assert.equal(clean, base);
});

test("withPreflightWarning: unreachable refs → structured preflight field", () => {
  const base = { tasks: [{ id: 1 }] };
  const warn = withPreflightWarning(base, {
    checked: [],
    unreachable: [{ ref: "~/Code/x/y.py", kind: "path", reachable: false, reason: "nope" }],
  });
  assert.ok(warn.preflight, "preflight field present");
  assert.equal(warn.preflight!.unreachable.length, 1);
  assert.equal(warn.preflight!.unreachable[0]!.ref, "~/Code/x/y.py");
  assert.match(warn.preflight!.warning, /stage_file/);
  assert.match(warn.preflight!.warning, /KANBAN_PREFLIGHT_STRICT/);
});

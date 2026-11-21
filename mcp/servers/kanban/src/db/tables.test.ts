/**
 * Driver-conditional table objects (src/db/tables.ts).
 *
 * Regression: the service layer must query through the MYSQL table objects
 * when DB_DRIVER=mysql. The SQLite text({mode:"json"}) mappers JSON.parse()
 * driver values, but mysql2 returns native JSON columns already parsed
 * (objects) — double-parsing crashes with "Unexpected end of JSON input"
 * (JSON.parse(String([])) === JSON.parse("")).
 */
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  ideas as sqliteIdeas,
  mysqlIdeas,
  mysqlProjects,
  projects as sqliteProjects,
} from "./schema.js";
import { ideas, projects, tablesUseMysql } from "./tables.js";

const here = dirname(fileURLToPath(import.meta.url));

test("default (no DB_DRIVER): sqlite table objects are active", () => {
  assert.equal(tablesUseMysql, false);
  assert.equal(ideas, sqliteIdeas);
  assert.equal(projects, sqliteProjects);
});

test("sqlite json mapper parses strings; mysql2-style objects crash it (the bug)", () => {
  // better-sqlite3 returns JSON columns as strings:
  assert.deepEqual(sqliteIdeas.dependsOn.mapFromDriverValue("[]"), []);
  // mysql2 returns JSON columns already parsed (objects). The SQLite mapper
  // double-parses: JSON.parse(String([])) -> JSON.parse("") -> SyntaxError.
  assert.throws(
    () => sqliteIdeas.dependsOn.mapFromDriverValue([]),
    /Unexpected end of JSON input/,
  );
});

test("mysql json mapper passes driver values through untouched", () => {
  // mysql-core json() has no mapFromDriverValue override (identity): the
  // already-parsed object mysql2 returns is what the service sees.
  const col = mysqlIdeas.dependsOn;
  const mapped = col.mapFromDriverValue?.([]) ?? [];
  assert.deepEqual(mapped, []);
  const spec = { goal: "g", steps: [], acceptance: [], kind: "code" as const };
  const mappedSpec = col.mapFromDriverValue?.(spec) ?? spec;
  assert.deepEqual(mappedSpec, spec);
});

test("DB_DRIVER=mysql: mysql table objects are active (fresh process)", () => {
  // The switch is evaluated at module load, so check it in a child process
  // with the env set before import.
  const script = `
    import { ideas, projects, tablesUseMysql } from "${join(here, "tables.js")}";
    import { ideas as sqliteIdeas, projects as sqliteProjects, mysqlIdeas, mysqlProjects } from "${join(here, "schema.js")}";
    if (tablesUseMysql !== true) throw new Error("expected mysql tables");
    if (ideas !== mysqlIdeas || projects !== mysqlProjects) throw new Error("expected mysql table objects");
    if (ideas === sqliteIdeas || projects === sqliteProjects) throw new Error("sqlite objects leaked");
    console.log("ok");
  `;
  const out = execFileSync(process.execPath, ["--input-type=module", "-e", script], {
    env: { ...process.env, DB_DRIVER: "mysql" },
    encoding: "utf8",
  });
  assert.match(out, /ok/);
});

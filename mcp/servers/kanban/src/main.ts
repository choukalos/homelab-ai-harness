/**
 * Bootstrap (PLAN.md §7): config → db → agent runtime → orchestrator →
 * HTTP + MCP server. Clean start/stop on SIGINT/SIGTERM.
 */
import { ConfigError, loadConfig } from "./config.js";
import { initDb } from "./db/index.js";
import { AgentRuntime, TaskSessionRunner } from "./agent/sessions.js";
import { GroomingManager } from "./agent/grooming.js";
import type { Db } from "./services/common.js";
import { Orchestrator } from "./orchestrator.js";
import { buildApp } from "./http/app.js";
import { createKanbanServices } from "./services/index.js";

async function main(): Promise<void> {
  const cfg = await loadConfig();
  console.log(
    `[config] model=${cfg.model} db=${cfg.db.driver} ` +
      `workspace=${cfg.workspace.dir} agentSlots=${cfg.agentConcurrentTasks} ` +
      `mediaSlots=${cfg.mediaConcurrentTasks} ` +
      `nonMediaSlots=${cfg.nonMediaConcurrentTasks} ` +
      `cleanupDays=${cfg.workspaceCleanupDays}` +
      (cfg.agentSlugs.length > 0 ? ` agentSlugs=${cfg.agentSlugs.join(",")}` : "") +
      (Object.keys(cfg.userKeys).length > 0 ? ` userKeys=${Object.keys(cfg.userKeys).join(",")}` : ""),
  );

  const db = await initDb(cfg);
  const agent = await AgentRuntime.create(cfg);
  const grooming = new GroomingManager({
    db: db.db as unknown as Db,
    cfg,
    agent,
    workspaceRoot: cfg.workspace.dir,
  });
  const taskRunner = new TaskSessionRunner({
    agent,
    token: cfg.githubToken,
    workspaceRoot: cfg.workspace.dir,
  });
  const orchestrator = new Orchestrator({
    cfg,
    db,
    agent,
    tasks: taskRunner,
    workspaceRoot: cfg.workspace.dir,
    cleanupAgeMs: cfg.workspaceCleanupDays * 86_400_000,
  });
  const services = createKanbanServices(db, { grooming, orchestrator });
  await orchestrator.start();

  const app = buildApp({ cfg, db, agent, services, orchestrator, grooming });
  await app.listen({ host: cfg.server.bindAddr, port: cfg.server.port });

  let shuttingDown = false;
  const shutdown = (signal: string) => {
    if (shuttingDown) return;
    shuttingDown = true;
    console.log(`[main] ${signal} received, shutting down`);
    (async () => {
      try {
        await orchestrator.stop();
        await app.close();
        grooming.dispose();
        agent.dispose();
        await db.close();
        process.exit(0);
      } catch (err) {
        console.error("shutdown failed:", err);
        process.exit(1);
      }
    })();
  };
  process.on("SIGINT", () => shutdown("SIGINT"));
  process.on("SIGTERM", () => shutdown("SIGTERM"));
}

main().catch((err: unknown) => {
  if (err instanceof ConfigError) {
    console.error(`startup failed: ${err.message}`);
  } else {
    console.error("startup failed:", err);
  }
  process.exit(1);
});

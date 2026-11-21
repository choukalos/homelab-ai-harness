/**
 * MCP endpoint: streamable HTTP on POST /mcp (SDK_NOTES.md §5), served by
 * the same Fastify app as the GUI/API.
 *
 * - Auth = a LiteLLM access key as a Bearer token. The kanban key
 *   (LITELLM_API_KEY) gets the full tool set; other keys can be scoped via
 *   MCP_KEY_CAPABILITIES (key-suffix:read;key-suffix:control,...) — the
 *   guardrails for multi-user remote control (PLAN.md §5 "full remote
 *   control"). Unknown keys are rejected with a clear error.
 * - Owner attribution: the caller key resolves to a user name via USER_KEYS
 *   (full-key match — the same map that picks the key profile for LLM
 *   spend) and is stamped on the items the caller creates (the kanban key →
 *   "kanban").
 * - **Unauthenticated discovery (2026-11-21):** the LiteLLM proxy's startup
 *   `tools/list` handshake carries no caller key, so `initialize` /
 *   `tools/list` / `ping` (+ notifications) are served WITHOUT a Bearer key
 *   — with the FULL tool set, because the proxy builds one global registry
 *   from it (per-key tool *listing* scoping is not possible through the
 *   proxy; every caller sees the union). Per-key scoping is enforced at
 *   CALL time: `tools/call` (and every other method) requires a key, and a
 *   scoped key calling an out-of-scope tool gets a clear error. Same
 *   pattern as mcp_sessions / mcp_skills (open discovery, auth at call
 *   time). Exposure is LAN/ai-net only (the port is LAN-bound), consistent
 *   with the unauthenticated LAN board UI.
 * - Stateless mode (fresh server + transport per request): the current tool
 *   set is stateless queries/actions over the service layer, so no session
 *   store is needed.
 */
import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import type { KanbanConfig } from "../config.js";
import {
  createKanbanMcpServer,
  MCP_TOOL_NAMES,
  parseMcpKeyCapabilities,
  resolveMcpCapabilities,
  resolveMcpOwner,
  type KanbanServices,
} from "./server.js";

/**
 * JSON-RPC methods safe to serve without a Bearer key: the LiteLLM proxy's
 * startup discovery (initialize + tools/list, plus ping/notifications).
 * Discovery returns the FULL tool set so the proxy's global registry is
 * complete; actions (tools/call) always require a key.
 */
const DISCOVERY_METHODS = new Set([
  "initialize",
  "tools/list",
  "ping",
  "notifications/initialized",
  "notifications/cancelled",
]);

/** True if the (possibly batched) JSON-RPC body contains only discovery methods. */
function isDiscoveryOnly(body: unknown): boolean {
  const msgs = Array.isArray(body) ? body : [body];
  if (msgs.length === 0) return false;
  return msgs.every((m) => {
    if (typeof m !== "object" || m === null) return false;
    const method = (m as { method?: unknown }).method;
    return typeof method === "string" && DISCOVERY_METHODS.has(method);
  });
}

export interface McpRouteDeps {
  cfg: KanbanConfig;
  services: KanbanServices;
  /**
   * Key-suffix → capability mapping (default: parsed from the
   * MCP_KEY_CAPABILITIES env var at route registration). Owner resolution
   * uses `cfg.userKeys` (USER_KEYS) directly — no separate owner map.
   */
  keyCapabilities?: Map<string, Set<string>>;
}

export function registerMcpRoutes(app: FastifyInstance, deps: McpRouteDeps): void {
  const mapping = deps.keyCapabilities ?? parseMcpKeyCapabilities(process.env.MCP_KEY_CAPABILITIES);
  app.post("/mcp", async (req: FastifyRequest, reply: FastifyReply) => {
    const auth = String(req.headers.authorization ?? "");
    const bearer = auth.startsWith("Bearer ") ? auth.slice("Bearer ".length) : "";
    let allowed: Set<string> | undefined;
    let owner = "";
    if (!bearer) {
      // Unauthenticated: discovery only (the LiteLLM proxy's startup
      // tools/list). Full tool set — the proxy's global registry must be
      // complete for admin keys to work through the proxy; per-key scoping
      // is enforced at call time (tools/call requires a key below).
      if (!isDiscoveryOnly(req.body)) {
        reply.code(401).send({
          jsonrpc: "2.0",
          id: null,
          error: {
            code: -32001,
            message:
              "unauthorized: expected Bearer <access key> (unauthenticated " +
              "requests may only use discovery methods: initialize, tools/list, ping)",
          },
        });
        return;
      }
      allowed = undefined; // full tool set for the proxy's global registry
    } else {
      const resolved = resolveMcpCapabilities(bearer, deps.cfg.litellm.apiKey, mapping);
      if (!resolved) {
        reply.code(401).send({
          jsonrpc: "2.0",
          id: null,
          error: {
            code: -32001,
            message:
              "unauthorized: this key is not authorized for the kanban MCP endpoint " +
              "(add it to MCP_KEY_CAPABILITIES with a capability set, e.g. <key-suffix>:read)",
          },
        });
        return;
      }
      allowed = resolved;
      owner = resolveMcpOwner(bearer, deps.cfg.litellm.apiKey, deps.cfg.userKeys);
    }
    const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined });
    const server = createKanbanMcpServer(deps.services, allowed, owner);
    try {
      await server.connect(transport);
      reply.hijack(); // transport owns the raw response from here on
      await transport.handleRequest(req.raw, reply.raw, req.body);
    } finally {
      await server.close().catch(() => {});
    }
  });

  // Streamable HTTP uses POST (and GET for SSE in stateful mode only).
  app.get("/mcp", async (_req: FastifyRequest, reply: FastifyReply) => {
    reply.code(405).send({ error: "MCP endpoint is POST /mcp (streamable HTTP)" });
  });
}

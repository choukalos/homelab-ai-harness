/**
 * MCP endpoint: streamable HTTP on POST /mcp (SDK_NOTES.md §5), served by
 * the same Fastify app as the GUI/API.
 *
 * - Auth = a LiteLLM access key as a Bearer token. The kanban key
 *   (LITELLM_API_KEY) gets the full tool set; other keys can be scoped via
 *   MCP_KEY_CAPABILITIES (key-suffix:read;key-suffix:control,...) — the
 *   guardrails for multi-user remote control (PLAN.md §5 "full remote
 *   control"). Unknown keys are rejected with a clear error.
 * - Stateless mode (fresh server + transport per request): the current tool
 *   set is stateless queries/actions over the service layer, so no session
 *   store is needed.
 */
import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import type { KanbanConfig } from "../config.js";
import {
  createKanbanMcpServer,
  parseMcpKeyCapabilities,
  resolveMcpCapabilities,
  type KanbanServices,
} from "./server.js";

export interface McpRouteDeps {
  cfg: KanbanConfig;
  services: KanbanServices;
  /**
   * Key-suffix → capability mapping (default: parsed from the
   * MCP_KEY_CAPABILITIES env var at route registration).
   */
  keyCapabilities?: Map<string, Set<string>>;
}

export function registerMcpRoutes(app: FastifyInstance, deps: McpRouteDeps): void {
  const mapping = deps.keyCapabilities ?? parseMcpKeyCapabilities(process.env.MCP_KEY_CAPABILITIES);
  app.post("/mcp", async (req: FastifyRequest, reply: FastifyReply) => {
    const auth = String(req.headers.authorization ?? "");
    const bearer = auth.startsWith("Bearer ") ? auth.slice("Bearer ".length) : "";
    if (!bearer) {
      reply.code(401).send({
        jsonrpc: "2.0",
        id: null,
        error: { code: -32001, message: "unauthorized: expected Bearer <access key>" },
      });
      return;
    }
    const allowed = resolveMcpCapabilities(bearer, deps.cfg.litellm.apiKey, mapping);
    if (!allowed) {
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
    const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined });
    const server = createKanbanMcpServer(deps.services, allowed);
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

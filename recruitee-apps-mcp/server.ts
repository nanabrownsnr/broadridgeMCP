import { registerAppResource, registerAppTool, RESOURCE_MIME_TYPE } from "@modelcontextprotocol/ext-apps/server";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import fs from "node:fs/promises";
import path from "node:path";
import { z } from "zod";

type JsonSchema = Record<string, unknown>;

const DIST_DIR = path.join(import.meta.dirname, "dist");
const OPENINGS_RESOURCE_URI = "ui://recruitee/openings.html";
const PIPELINE_RESOURCE_URI = "ui://recruitee/pipeline.html";
const RECRUITEE_MCP_BASE_URL = process.env.RECRUITEE_MCP_BASE_URL ?? "http://recruitee-mcp:8000";

async function callRecruiteeApi(pathname: string, method: "GET" | "POST", body?: unknown) {
  const url = `${RECRUITEE_MCP_BASE_URL}${pathname}`;
  const response = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });

  const text = await response.text();
  let data: unknown;
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { raw: text };
  }

  if (!response.ok) {
    throw new Error(`Recruitee API error (${response.status}): ${text}`);
  }

  return data;
}

function errorResult(message: string) {
  return { content: [{ type: "text" as const, text: message }], isError: true };
}

function addProxyTool(
  server: McpServer,
  cfg: {
    name: string;
    description: string;
    method: "GET" | "POST";
    path: string;
    inputSchema?: JsonSchema;
    visibility?: Array<"model" | "app">;
    uiResourceUri?: string;
    mapArgsToPath?: (args: Record<string, unknown>) => string;
    mapArgsToBody?: (args: Record<string, unknown>) => unknown;
    mapResult?: (result: unknown) => unknown;
  },
) {
  const metaUi: Record<string, unknown> = { visibility: cfg.visibility ?? ["model", "app"] };
  if (cfg.uiResourceUri) {
    metaUi.resourceUri = cfg.uiResourceUri;
  }

  registerAppTool(
    server,
    cfg.name,
    {
      title: cfg.name,
      description: cfg.description,
      inputSchema: z.object({}).passthrough(),
      _meta: { ui: metaUi },
    },
    async (rawArgs) => {
      try {
        const args = (rawArgs ?? {}) as Record<string, unknown>;
        const path = cfg.mapArgsToPath ? cfg.mapArgsToPath(args) : cfg.path;
        const body = cfg.method === "POST" ? (cfg.mapArgsToBody ? cfg.mapArgsToBody(args) : args) : undefined;
        const data = await callRecruiteeApi(path, cfg.method, body);
        const mapped = cfg.mapResult ? cfg.mapResult(data) : data;
        return {
          content: [{ type: "text", text: `${cfg.name} executed successfully.` }],
          structuredContent: mapped,
        };
      } catch (err) {
        return errorResult(err instanceof Error ? err.message : `Unknown error in ${cfg.name}`);
      }
    },
  );
}

export function createServer(): McpServer {
  const server = new McpServer({ name: "Recruitee Unified MCP", version: "0.3.0" });

  // UI resource used by the two interactive views.
  registerAppResource(
    server,
    OPENINGS_RESOURCE_URI,
    OPENINGS_RESOURCE_URI,
    { mimeType: RESOURCE_MIME_TYPE, description: "Recruitee MCP app shell" },
    async () => {
      const html = await fs.readFile(path.join(DIST_DIR, "mcp-app.html"), "utf-8");
      return {
        contents: [
          {
            uri: OPENINGS_RESOURCE_URI,
            mimeType: RESOURCE_MIME_TYPE,
            text: html,
            _meta: {
              ui: {
                prefersBorder: true,
                csp: {
                  // Bridge-only UI mode: browser iframe should not call internal Docker hosts.
                  // All data actions go through MCP tool calls on the host bridge.
                  connectDomains: [],
                  resourceDomains: [],
                },
              },
            },
          },
        ],
      };
    },
  );
  registerAppResource(
    server,
    PIPELINE_RESOURCE_URI,
    PIPELINE_RESOURCE_URI,
    { mimeType: RESOURCE_MIME_TYPE, description: "Recruitee pipeline MCP app shell" },
    async () => {
      const html = await fs.readFile(path.join(DIST_DIR, "mcp-app.html"), "utf-8");
      return {
        contents: [
          {
            uri: PIPELINE_RESOURCE_URI,
            mimeType: RESOURCE_MIME_TYPE,
            text: html,
            _meta: {
              ui: {
                prefersBorder: true,
                csp: {
                  // Bridge-only UI mode: browser iframe should not call internal Docker hosts.
                  // All data actions go through MCP tool calls on the host bridge.
                  connectDomains: [],
                  resourceDomains: [],
                },
              },
            },
          },
        ],
      };
    },
  );

  // View 1: openings explorer
  addProxyTool(server, {
    name: "recruitee_list_job_openings",
    description: "List Recruitee openings for openings explorer view.",
    method: "GET",
    path: "/api/v1/recruitee/list_job_openings?include_raw=false",
    inputSchema: {
      type: "object",
      properties: { include_raw: { type: "boolean", default: false } },
      additionalProperties: false,
    },
    uiResourceUri: OPENINGS_RESOURCE_URI,
    mapResult: (data) => ({ view: "openings_explorer", data }),
  });

  // View 2: pipeline kanban
  addProxyTool(server, {
    name: "recruitee_list_candidates",
    description: "List candidates; use offer_id for pipeline kanban view.",
    method: "POST",
    path: "/api/v1/recruitee/list_candidates",
    inputSchema: {
      type: "object",
      properties: {
        offer_id: { type: "integer" },
        stage_id: { type: "integer" },
        limit: { type: "integer", default: 50 },
        page: { type: "integer", default: 1 },
        include_raw: { type: "boolean", default: false },
      },
      additionalProperties: false,
    },
    uiResourceUri: PIPELINE_RESOURCE_URI,
    mapResult: (data) => ({ view: "pipeline_kanban", data }),
  });

  // App-only action from kanban drag/drop
  addProxyTool(server, {
    name: "recruitee_move_candidate_stage",
    description: "Move candidate to a new stage.",
    method: "POST",
    path: "/api/v1/recruitee/move_candidate_stage",
    inputSchema: {
      type: "object",
      properties: {
        candidate_id: { type: "integer" },
        offer_id: { type: "integer" },
        stage_id: { type: "integer" },
      },
      required: ["candidate_id", "offer_id", "stage_id"],
      additionalProperties: false,
    },
    visibility: ["model", "app"],
    uiResourceUri: PIPELINE_RESOURCE_URI,
    mapResult: (data) => ({ view: "pipeline_kanban", action_result: data }),
  });

  // Remaining existing tools (non-UI tools, still on same endpoint)
  addProxyTool(server, {
    name: "recruitee_create_job_offer",
    description: "Create a Recruitee job offer.",
    method: "POST",
    path: "/api/v1/recruitee/create_job_offer",
    inputSchema: { type: "object", additionalProperties: true },
    visibility: ["model", "app"],
  });

  addProxyTool(server, {
    name: "recruitee_publish_job",
    description: "Publish an existing Recruitee job.",
    method: "POST",
    path: "/api/v1/recruitee/publish_job",
    inputSchema: {
      type: "object",
      properties: { offer_id: { type: "integer" } },
      required: ["offer_id"],
      additionalProperties: false,
    },
    visibility: ["model", "app"],
  });

  addProxyTool(server, {
    name: "recruitee_get_job_public_url",
    description: "Get public apply URL for an offer.",
    method: "POST",
    path: "/api/v1/recruitee/get_job_public_url",
    inputSchema: {
      type: "object",
      properties: {
        offer_id: { type: "integer" },
        include_raw_offer: { type: "boolean", default: false },
      },
      required: ["offer_id"],
      additionalProperties: false,
    },
    visibility: ["model", "app"],
  });

  addProxyTool(server, {
    name: "recruitee_list_offer_stages",
    description: "List stages for an offer pipeline.",
    method: "POST",
    path: "/api/v1/recruitee/list_offer_stages",
    inputSchema: {
      type: "object",
      properties: {
        offer_id: { type: "integer" },
        include_raw: { type: "boolean", default: false },
      },
      required: ["offer_id"],
      additionalProperties: false,
    },
    visibility: ["model", "app"],
  });

  addProxyTool(server, {
    name: "recruitee_get_candidate_resume_source",
    description: "Get one candidate resume source payload.",
    method: "POST",
    path: "/api/v1/recruitee/get_candidate_resume_source",
    inputSchema: {
      type: "object",
      properties: {
        candidate_id: { type: "integer" },
        include_raw_candidate: { type: "boolean", default: false },
      },
      required: ["candidate_id"],
      additionalProperties: false,
    },
    visibility: ["model", "app"],
  });

  addProxyTool(server, {
    name: "recruitee_get_candidates_resume_sources",
    description: "Batch resume source resolution for candidate IDs.",
    method: "POST",
    path: "/api/v1/recruitee/get_candidates_resume_sources",
    inputSchema: {
      type: "object",
      properties: {
        candidate_ids: { type: "array", items: { type: "integer" } },
        include_raw_candidate: { type: "boolean", default: false },
      },
      required: ["candidate_ids"],
      additionalProperties: false,
    },
    visibility: ["model", "app"],
  });

  addProxyTool(server, {
    name: "recruitee_build_batch_matching_input",
    description: "Build batch matching payload for Candidate Intelligence.",
    method: "POST",
    path: "/api/v1/recruitee/build_batch_matching_input",
    inputSchema: {
      type: "object",
      properties: {
        candidate_ids: { type: "array", items: { type: "integer" } },
        include_raw_candidate: { type: "boolean", default: false },
      },
      required: ["candidate_ids"],
      additionalProperties: false,
    },
    visibility: ["model", "app"],
  });

  addProxyTool(server, {
    name: "recruitee_register_webhook",
    description: "Register Recruitee webhook.",
    method: "POST",
    path: "/api/v1/recruitee/register_webhook",
    inputSchema: {
      type: "object",
      properties: {
        target_url: { type: "string" },
        event_type: { type: "string" },
      },
      required: ["target_url", "event_type"],
      additionalProperties: false,
    },
    visibility: ["model", "app"],
  });

  addProxyTool(server, {
    name: "recruitee_model_info",
    description: "Return Recruitee MCP configuration info.",
    method: "GET",
    path: "/api/v1/recruitee/model_info",
    visibility: ["model", "app"],
  });

  return server;
}


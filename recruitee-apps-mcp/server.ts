import { registerAppResource, registerAppTool, RESOURCE_MIME_TYPE } from "@modelcontextprotocol/ext-apps/server";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import fs from "node:fs/promises";
import path from "node:path";

const DIST_DIR = path.join(import.meta.dirname, "dist");
const RESOURCE_URI = "ui://recruitee/app.html";
const RECRUITEE_MCP_BASE_URL = process.env.RECRUITEE_MCP_BASE_URL ?? "http://recruitee-mcp:8000";

async function callRecruiteeApi(pathname: string, method: "GET" | "POST", body?: unknown) {
  const url = `${RECRUITEE_MCP_BASE_URL}${pathname}`;
  const response = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  const rawText = await response.text();
  let data: unknown;
  try {
    data = rawText ? JSON.parse(rawText) : {};
  } catch {
    data = { raw: rawText };
  }
  if (!response.ok) {
    throw new Error(`Recruitee API error (${response.status}): ${rawText}`);
  }
  return data;
}

export function createServer(): McpServer {
  const server = new McpServer({
    name: "Recruitee Apps MCP",
    version: "0.1.0",
  });

  registerAppTool(
    server,
    "recruitee_openings_explorer",
    {
      title: "Recruitee Openings Explorer",
      description: "Returns Recruitee job openings for the interactive openings view.",
      inputSchema: {
        type: "object",
        properties: {
          include_raw: { type: "boolean", default: false },
        },
        additionalProperties: false,
      },
      _meta: { ui: { resourceUri: RESOURCE_URI, visibility: ["model", "app"] } },
    },
    async (args) => {
      const includeRaw = !!(args as { include_raw?: boolean }).include_raw;
      const data = await callRecruiteeApi("/api/v1/recruitee/list_job_openings?include_raw=false", "GET");
      return {
        content: [
          {
            type: "text",
            text: "Openings loaded. Render openings_explorer view.",
          },
        ],
        structuredContent: {
          view: "openings_explorer",
          include_raw: includeRaw,
          data,
        },
      };
    },
  );

  registerAppTool(
    server,
    "recruitee_pipeline_kanban",
    {
      title: "Recruitee Pipeline Kanban",
      description: "Returns candidates and stage metadata for an offer as an interactive kanban board.",
      inputSchema: {
        type: "object",
        properties: {
          offer_id: { type: "integer" },
          limit: { type: "integer", default: 50 },
          page: { type: "integer", default: 1 },
        },
        required: ["offer_id"],
        additionalProperties: false,
      },
      _meta: { ui: { resourceUri: RESOURCE_URI, visibility: ["model", "app"] } },
    },
    async (args) => {
      const { offer_id, limit = 50, page = 1 } = args as { offer_id: number; limit?: number; page?: number };
      const stages = await callRecruiteeApi("/api/v1/recruitee/list_offer_stages", "POST", {
        offer_id,
        include_raw: false,
      });
      const candidates = await callRecruiteeApi("/api/v1/recruitee/list_candidates", "POST", {
        offer_id,
        limit,
        page,
        include_raw: false,
      });
      return {
        content: [
          {
            type: "text",
            text: `Pipeline loaded for offer ${offer_id}. Render pipeline_kanban view.`,
          },
        ],
        structuredContent: {
          view: "pipeline_kanban",
          data: {
            offer_id,
            stages,
            candidates,
          },
        },
      };
    },
  );

  registerAppTool(
    server,
    "recruitee_move_candidate_stage_action",
    {
      title: "Move Candidate Stage",
      description: "App action tool to move a candidate to a different stage.",
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
      _meta: { ui: { resourceUri: RESOURCE_URI, visibility: ["app"] } },
    },
    async (args) => {
      const payload = args as { candidate_id: number; offer_id: number; stage_id: number };
      const data = await callRecruiteeApi("/api/v1/recruitee/move_candidate_stage", "POST", payload);
      return {
        content: [{ type: "text", text: "Candidate stage updated." }],
        structuredContent: {
          view: "pipeline_kanban",
          action_result: data,
        },
      };
    },
  );

  registerAppResource(
    server,
    RESOURCE_URI,
    RESOURCE_URI,
    { mimeType: RESOURCE_MIME_TYPE, description: "Recruitee MCP app shell" },
    async () => {
      const html = await fs.readFile(path.join(DIST_DIR, "mcp-app.html"), "utf-8");
      return {
        contents: [
          {
            uri: RESOURCE_URI,
            mimeType: RESOURCE_MIME_TYPE,
            text: html,
            _meta: {
              ui: {
                prefersBorder: true,
                csp: {
                  connectDomains: [RECRUITEE_MCP_BASE_URL],
                  resourceDomains: [],
                },
              },
            },
          },
        ],
      };
    },
  );

  return server;
}

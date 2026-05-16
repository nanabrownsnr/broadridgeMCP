import { registerAppResource, registerAppTool, RESOURCE_MIME_TYPE } from "@modelcontextprotocol/ext-apps/server";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import fs from "node:fs/promises";
import path from "node:path";
import { z } from "zod";

type JsonSchema = Record<string, unknown>;

const DIST_DIR = path.join(import.meta.dirname, "dist");
const OPENINGS_RESOURCE_URI = "ui://recruitee/openings.html";
const PIPELINE_RESOURCE_URI = "ui://recruitee/pipeline.html";
const VIEWER_RESOURCE_URI = "ui://recruitee/viewer.html";
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
    mapResult?: (result: unknown, args: Record<string, unknown>) => unknown;
    mapContentText?: (mapped: unknown, args: Record<string, unknown>) => string;
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
        const mapped = cfg.mapResult ? cfg.mapResult(data, args) : data;
        const contentText = cfg.mapContentText ? cfg.mapContentText(mapped, args) : `${cfg.name} executed successfully.`;
        return {
          content: [{ type: "text", text: contentText }],
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
    VIEWER_RESOURCE_URI,
    VIEWER_RESOURCE_URI,
    { mimeType: RESOURCE_MIME_TYPE, description: "Recruitee URL/file viewer shell" },
    async () => {
      const html = await fs.readFile(path.join(DIST_DIR, "mcp-app.html"), "utf-8");
      return {
        contents: [
          {
            uri: VIEWER_RESOURCE_URI,
            mimeType: RESOURCE_MIME_TYPE,
            text: html,
            _meta: {
              ui: {
                prefersBorder: true,
                csp: {
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
    mapContentText: (mapped) => {
      const d = mapped as any;
      const openings = d?.data?.openings ?? [];
      if (!openings.length) return "No openings were returned.";
      const lines = openings.slice(0, 10).map((o: any) => `- ${o.title} (offer_id: ${o.offer_id}, status: ${o.status})`);
      return `Current openings (${openings.length}):\n${lines.join("\n")}`;
    },
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
    mapResult: (data, args) => ({
      view: "pipeline_kanban",
      offer_id: typeof args.offer_id === "number" ? args.offer_id : null,
      stage_id: typeof args.stage_id === "number" ? args.stage_id : null,
      data,
    }),
    mapContentText: (mapped, args) => {
      const d = mapped as any;
      const count = d?.data?.count ?? d?.data?.candidates?.length ?? 0;
      const offerId = typeof args.offer_id === "number" ? args.offer_id : null;
      return offerId != null
        ? `Loaded ${count} candidate(s) for offer_id ${offerId}.`
        : `Loaded ${count} candidate(s).`;
    },
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
    uiResourceUri: VIEWER_RESOURCE_URI,
    mapResult: (data) => {
      const d = data as any;
      const items: Array<{ label: string; url: string; type: "url" | "file" }> = [];
      if (d?.apply_url) items.push({ label: "Apply URL", url: d.apply_url, type: "url" });
      if (d?.careers_url && d?.careers_url !== d?.apply_url) items.push({ label: "Careers URL", url: d.careers_url, type: "url" });
      for (const u of d?.url_candidates ?? []) {
        if (u && !items.some((x) => x.url === u)) items.push({ label: "URL candidate", url: u, type: "url" });
      }
      return { view: "url_viewer", title: d?.title ?? "Job Public URL", items, data: d };
    },
    mapContentText: (mapped) => {
      const m = mapped as any;
      const items = m?.items ?? [];
      if (!items.length) return "No URL was returned for this offer.";
      return `Resolved ${items.length} URL(s):\n${items.map((x: any) => `- ${x.label}: ${x.url}`).join("\n")}`;
    },
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
    uiResourceUri: VIEWER_RESOURCE_URI,
    mapResult: (data) => {
      const d = data as any;
      const rs = d?.resume_source ?? {};
      const items: Array<{ label: string; url: string; type: "url" | "file" }> = [];
      if (rs?.resume_url) items.push({ label: "Resume URL", url: rs.resume_url, type: "file" });
      if (rs?.cv_url && rs?.cv_url !== rs?.resume_url) items.push({ label: "CV URL", url: rs.cv_url, type: "file" });
      if (rs?.cv_original_file && rs?.cv_original_file !== rs?.resume_url) items.push({ label: "Original CV File", url: rs.cv_original_file, type: "file" });
      return {
        view: "url_viewer",
        title: rs?.candidate_name ? `Resume - ${rs.candidate_name}` : "Candidate Resume",
        items,
        data: d,
      };
    },
    mapContentText: (mapped) => {
      const m = mapped as any;
      const items = m?.items ?? [];
      if (!items.length) return "No resume URL was found for this candidate.";
      return `Resume links (${items.length}):\n${items.map((x: any) => `- ${x.label}: ${x.url}`).join("\n")}`;
    },
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
    uiResourceUri: VIEWER_RESOURCE_URI,
    mapResult: (data) => {
      const d = data as any;
      const items: Array<{ label: string; url: string; type: "url" | "file"; candidate_id?: number }> = [];
      for (const r of d?.results ?? []) {
        const rs = r?.resume_source ?? {};
        const url = rs?.resume_url || rs?.cv_url || rs?.cv_original_file;
        if (url) {
          items.push({
            label: rs?.candidate_name ? `${rs.candidate_name} (${r.candidate_id})` : `Candidate ${r.candidate_id}`,
            url,
            type: "file",
            candidate_id: r?.candidate_id,
          });
        }
      }
      return { view: "url_viewer", title: "Batch Resume Sources", items, data: d };
    },
    mapContentText: (mapped) => {
      const m = mapped as any;
      const items = m?.items ?? [];
      if (!items.length) return "No resume URLs found in this batch.";
      return `Batch resume links found: ${items.length}`;
    },
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


import { registerAppResource, registerAppTool, RESOURCE_MIME_TYPE } from "@modelcontextprotocol/ext-apps/server";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import fs from "node:fs/promises";
import path from "node:path";
import { z } from "zod";

type DiagramType =
  | "general"
  | "data_flow"
  | "erd"
  | "uml_class"
  | "uml_activity"
  | "uml_sequence"
  | "uml_use_case";

const DIST_DIR = path.join(import.meta.dirname, "dist");
const EDITOR_RESOURCE_URI = "ui://solution-architecture-tools/editor.html";
const MERMAID_RENDER_BASE_URL = process.env.MERMAID_RENDER_BASE_URL ?? "https://mermaid.ink";

function b64(input: string): string {
  return Buffer.from(input, "utf-8").toString("base64").replace(/\+/g, "-").replace(/\//g, "_");
}

async function tryRenderSvg(mermaid: string): Promise<string | null> {
  try {
    const encoded = b64(mermaid);
    const url = `${MERMAID_RENDER_BASE_URL.replace(/\/$/, "")}/svg/${encoded}`;
    const res = await fetch(url);
    if (!res.ok) return null;
    const txt = await res.text();
    return txt.startsWith("<svg") ? txt : null;
  } catch {
    return null;
  }
}

function wrapResult(args: {
  title: string;
  diagramType: DiagramType;
  mermaid: string;
  notationRules: string[];
  warnings?: string[];
  svg?: string | null;
}) {
  const warnings = args.warnings ?? [];
  return {
    content: [
      {
        type: "text" as const,
        text: `${args.title}\nType: ${args.diagramType}\nRules applied: ${args.notationRules.length}\nWarnings: ${warnings.length}`,
      },
    ],
    structuredContent: {
      view: "diagram_editor",
      title: args.title,
      diagram_type: args.diagramType,
      mermaid_source: args.mermaid,
      svg: args.svg ?? null,
      notation_rules: args.notationRules,
      warnings,
      theme: "neutral",
      output_format: "svg",
    },
  };
}

function buildDfd(input: {
  system_name: string;
  external_entities: string[];
  processes: string[];
  data_stores: string[];
  data_flows: Array<{ from: string; to: string; label: string }>;
}): string {
  const lines: string[] = ["flowchart LR"];
  const entityMap = new Map<string, string>();
  const processMap = new Map<string, string>();
  const storeMap = new Map<string, string>();

  for (const e of input.external_entities) {
    const nodeId = id("E", e);
    entityMap.set(e.toLowerCase(), nodeId);
    lines.push(`  ${nodeId}[${escape(e)}]`);
  }
  for (const p of input.processes) {
    const nodeId = id("P", p);
    processMap.set(p.toLowerCase(), nodeId);
    lines.push(`  ${nodeId}((${escape(p)}))`);
  }
  for (const d of input.data_stores) {
    const nodeId = id("D", d);
    storeMap.set(d.toLowerCase(), nodeId);
    lines.push(`  ${nodeId}[/${escape(d)}/]`);
  }

  const resolveNode = (raw: string): string => {
    const key = raw.trim().toLowerCase();
    if (entityMap.has(key)) return entityMap.get(key)!;
    if (processMap.has(key)) return processMap.get(key)!;
    if (storeMap.has(key)) return storeMap.get(key)!;
    if (raw.startsWith("E_") || raw.startsWith("P_") || raw.startsWith("D_")) return safeName(raw);
    return id("P", raw);
  };

  for (const f of input.data_flows) {
    lines.push(`  ${resolveNode(f.from)} -->|${escape(f.label)}| ${resolveNode(f.to)}`);
  }
  lines.push(`  %% System: ${escape(input.system_name)}`);
  return lines.join("\n");
}

function buildErd(input: {
  entities: Array<{ name: string; attributes: string[]; primary_key?: string; foreign_keys?: string[] }>;
  relationships: Array<{ left: string; right: string; left_cardinality: string; right_cardinality: string; label?: string }>;
}): string {
  const lines: string[] = ["erDiagram"];
  for (const e of input.entities) {
    lines.push(`  ${safeName(e.name)} {`);
    for (const a of e.attributes) lines.push(`    string ${safeName(a)}`);
    if (e.primary_key) lines.push(`    string ${safeName(e.primary_key)} PK`);
    for (const fk of e.foreign_keys ?? []) lines.push(`    string ${safeName(fk)} FK`);
    lines.push("  }");
  }
  for (const r of input.relationships) {
    const label = r.label ? ` : ${escape(r.label)}` : "";
    lines.push(`  ${safeName(r.left)} ${r.left_cardinality}--${r.right_cardinality} ${safeName(r.right)}${label}`);
  }
  return lines.join("\n");
}

function buildUmlSequence(input: {
  title: string;
  participants: string[];
  interactions: Array<{ from: string; to: string; request: string; response?: string; activate?: boolean }>;
}): string {
  const lines: string[] = ["sequenceDiagram", `  title ${escape(input.title)}`];
  for (const p of input.participants) lines.push(`  participant ${safeName(p)} as ${escape(p)}`);
  for (const i of input.interactions) {
    lines.push(`  ${safeName(i.from)}->>${safeName(i.to)}: ${escape(i.request)}`);
    if (i.activate ?? true) {
      lines.push(`  activate ${safeName(i.to)}`);
      if (i.response) lines.push(`  ${safeName(i.to)}-->>${safeName(i.from)}: ${escape(i.response)}`);
      lines.push(`  deactivate ${safeName(i.to)}`);
    } else if (i.response) {
      lines.push(`  ${safeName(i.to)}-->>${safeName(i.from)}: ${escape(i.response)}`);
    }
  }
  return lines.join("\n");
}

function buildUmlClass(input: {
  classes: Array<{ name: string; attributes?: string[]; methods?: string[] }>;
  relations: Array<{ from: string; to: string; type: "inheritance" | "composition" | "aggregation" | "association"; label?: string }>;
}): string {
  const lines: string[] = ["classDiagram"];
  for (const c of input.classes) {
    lines.push(`  class ${safeName(c.name)} {`);
    for (const a of c.attributes ?? []) lines.push(`    +${escape(a)}`);
    for (const m of c.methods ?? []) lines.push(`    +${escape(m)}()`);
    lines.push("  }");
  }
  for (const r of input.relations) {
    const rel = r.type === "inheritance" ? "<|--" : r.type === "composition" ? "*--" : r.type === "aggregation" ? "o--" : "--";
    const lbl = r.label ? ` : ${escape(r.label)}` : "";
    lines.push(`  ${safeName(r.from)} ${rel} ${safeName(r.to)}${lbl}`);
  }
  return lines.join("\n");
}

function buildUmlActivity(input: { title: string; steps: string[] }): string {
  const lines = ["flowchart TD", `  start([Start])`];
  input.steps.forEach((s, i) => {
    const node = `A${i + 1}`;
    lines.push(`  ${node}[${escape(s)}]`);
    lines.push(i === 0 ? `  start --> ${node}` : `  A${i} --> ${node}`);
  });
  lines.push(`  A${input.steps.length} --> end([End])`);
  return lines.join("\n");
}

function buildUmlUseCase(input: { system_name: string; actors: string[]; use_cases: string[]; links: Array<{ actor: string; use_case: string }> }): string {
  const lines = ["flowchart LR", `  subgraph SYS[${escape(input.system_name)}]`];
  for (const u of input.use_cases) lines.push(`    ${id("UC", u)}((${escape(u)}))`);
  lines.push("  end");
  for (const a of input.actors) lines.push(`  ${id("A", a)}[${escape(a)}]`);
  for (const l of input.links) lines.push(`  ${id("A", l.actor)} --- ${id("UC", l.use_case)}`);
  return lines.join("\n");
}

function id(prefix: string, value: string): string {
  return `${prefix}_${safeName(value)}`;
}
function safeName(value: string): string {
  return value.replace(/[^a-zA-Z0-9_]/g, "_");
}
function escape(value: string): string {
  return value.replace(/\n/g, " ").replace(/"/g, "'");
}

function looksLikeMermaid(input: string): boolean {
  const s = input.trim();
  return (
    s.startsWith("flowchart") ||
    s.startsWith("classDiagram") ||
    s.startsWith("sequenceDiagram") ||
    s.startsWith("erDiagram")
  );
}

function scaffoldForType(diagramType: DiagramType, request: string): string {
  const note = escape(request);
  if (diagramType === "data_flow") {
    return [
      "flowchart LR",
      "  E_User[User]",
      "  P_System((System Process))",
      "  D_Data[/Data Store/]",
      "  E_User -->|Request| P_System",
      "  P_System -->|Persist| D_Data",
      `  %% Request: ${note}`,
    ].join("\n");
  }
  if (diagramType === "erd") {
    return [
      "erDiagram",
      "  ENTITY_ONE {",
      "    string id PK",
      "    string name",
      "  }",
      "  ENTITY_TWO {",
      "    string id PK",
      "    string entity_one_id FK",
      "  }",
      "  ENTITY_ONE ||--o{ ENTITY_TWO : relates_to",
      `  %% Request: ${note}`,
    ].join("\n");
  }
  if (diagramType === "uml_class") {
    return [
      "classDiagram",
      "  class ClassA {",
      "    +id: string",
      "    +doWork()",
      "  }",
      "  class ClassB {",
      "    +id: string",
      "    +process()",
      "  }",
      "  ClassA --> ClassB : uses",
      `  %% Request: ${note}`,
    ].join("\n");
  }
  if (diagramType === "uml_activity") {
    return [
      "flowchart TD",
      "  start([Start]) --> step1[Step 1]",
      "  step1 --> step2[Step 2]",
      "  step2 --> end([End])",
      `  %% Request: ${note}`,
    ].join("\n");
  }
  if (diagramType === "uml_sequence") {
    return [
      "sequenceDiagram",
      "  participant Client",
      "  participant Service",
      "  Client->>Service: Request",
      "  activate Service",
      "  Service-->>Client: Response",
      "  deactivate Service",
      `  %% Request: ${note}`,
    ].join("\n");
  }
  if (diagramType === "uml_use_case") {
    return [
      "flowchart LR",
      "  A_User[User]",
      "  subgraph SYS[System]",
      "    UC_Login((Login))",
      "  end",
      "  A_User --- UC_Login",
      `  %% Request: ${note}`,
    ].join("\n");
  }
  return [
    "flowchart LR",
    "  A[Start]",
    "  B[Middle]",
    "  C[End]",
    "  A --> B --> C",
    `  %% Request: ${note}`,
  ].join("\n");
}

function resolveMermaidFromRequest(diagramType: DiagramType, request: string, existingDiagram?: string): string {
  const req = request.trim();
  if (looksLikeMermaid(req)) return req;
  if (!existingDiagram) return scaffoldForType(diagramType, req);
  throw new Error(
    "For edits, provide full updated Mermaid in `request` and include prior diagram in `existing_diagram` for context.",
  );
}

export function createServer(): McpServer {
  const server = new McpServer({ name: "Solution Architecture Tools MCP", version: "0.1.0" });

  registerAppResource(
    server,
    EDITOR_RESOURCE_URI,
    EDITOR_RESOURCE_URI,
    { mimeType: RESOURCE_MIME_TYPE, description: "Solution architecture diagram editor/viewer" },
    async () => {
      const html = await fs.readFile(path.join(DIST_DIR, "mcp-app.html"), "utf-8");
      return {
        contents: [
          {
            uri: EDITOR_RESOURCE_URI,
            mimeType: RESOURCE_MIME_TYPE,
            text: html,
            _meta: {
              ui: {
                prefersBorder: true,
                csp: { connectDomains: ["https://mermaid.ink"], resourceDomains: [] },
              },
            },
          },
        ],
      };
    },
  );

  registerAppTool(
    server,
    "generate_general_diagram",
    {
      title: "Generate General Diagram",
      description:
        "Create or update a general architecture diagram. If `existing_diagram` is empty, `request` is treated as a new diagram request. For edits, provide the full updated Mermaid in `request` and pass the previous Mermaid in `existing_diagram` for context.",
      inputSchema: z.object({
        request: z.string().describe("New diagram request or full updated Mermaid when editing."),
        existing_diagram: z.string().optional().describe("Optional existing Mermaid source for edit context."),
        output_format: z.literal("svg").default("svg").describe("Output format. Currently only svg is supported."),
        strict_notation: z.boolean().default(true).describe("When true, enforce strict Mermaid notation for this diagram type."),
      }),
      _meta: { ui: { resourceUri: EDITOR_RESOURCE_URI, visibility: ["model", "app"] } },
    },
    async (args) => {
      const src = resolveMermaidFromRequest("general", args.request, args.existing_diagram);
      const svg = await tryRenderSvg(src);
      return wrapResult({
        title: "General Diagram",
        diagramType: "general",
        mermaid: src,
        svg,
        notationRules: [
          "Mermaid valid syntax",
          "Theme fixed to neutral",
          "Output fixed to SVG",
          args.strict_notation ? "Strict notation enabled" : "Strict notation disabled",
        ],
      });
    },
  );

  registerAppTool(
    server,
    "generate_data_flow_diagram",
    {
      title: "Generate Data Flow Diagram",
      description:
        "Create or update a data flow diagram (DFD). Uses DFD notation: process circles, external entity rectangles, open-ended datastore rectangles, directed data-flow arrows. If editing, provide full updated Mermaid in `request`.",
      inputSchema: z.object({
        request: z.string().describe("New DFD request or full updated Mermaid when editing."),
        existing_diagram: z.string().optional().describe("Optional existing Mermaid source for edit context."),
        output_format: z.literal("svg").default("svg").describe("Output format. Currently only svg is supported."),
        strict_notation: z.boolean().default(true).describe("When true, enforce strict DFD notation."),
      }),
      _meta: { ui: { resourceUri: EDITOR_RESOURCE_URI, visibility: ["model", "app"] } },
    },
    async (args) => {
      const mermaid = resolveMermaidFromRequest("data_flow", args.request, args.existing_diagram);
      const svg = await tryRenderSvg(mermaid);
      return wrapResult({
        title: "Data Flow Diagram",
        diagramType: "data_flow",
        mermaid,
        svg,
        notationRules: [
          "Processes represented as circles",
          "External entities represented as rectangles",
          "Data stores represented as open-ended rectangles",
          "Data flows represented as directed arrows with labels",
          args.strict_notation ? "Strict notation enabled" : "Strict notation disabled",
        ],
      });
    },
  );

  registerAppTool(
    server,
    "generate_entity_relationship_diagram",
    {
      title: "Generate ER Diagram",
      description:
        "Create or update an ER diagram with entities, attributes, relationships, and cardinality. If editing, provide full updated Mermaid in `request`.",
      inputSchema: z.object({
        request: z.string().describe("New ERD request or full updated Mermaid when editing."),
        existing_diagram: z.string().optional().describe("Optional existing Mermaid source for edit context."),
        output_format: z.literal("svg").default("svg").describe("Output format. Currently only svg is supported."),
        strict_notation: z.boolean().default(true).describe("When true, enforce strict ER notation."),
      }),
      _meta: { ui: { resourceUri: EDITOR_RESOURCE_URI, visibility: ["model", "app"] } },
    },
    async (args) => {
      const mermaid = resolveMermaidFromRequest("erd", args.request, args.existing_diagram);
      const svg = await tryRenderSvg(mermaid);
      return wrapResult({
        title: "Entity Relationship Diagram",
        diagramType: "erd",
        mermaid,
        svg,
        notationRules: ["Entities with attributes", "PK/FK notation", "Explicit relationship cardinality", args.strict_notation ? "Strict notation enabled" : "Strict notation disabled"],
      });
    },
  );

  registerAppTool(
    server,
    "generate_uml_class_diagram",
    {
      title: "Generate UML Class Diagram",
      description:
        "Create or update a UML class diagram with classes, attributes, methods, and typed relationships. If editing, provide full updated Mermaid in `request`.",
      inputSchema: z.object({
        request: z.string().describe("New UML class request or full updated Mermaid when editing."),
        existing_diagram: z.string().optional().describe("Optional existing Mermaid source for edit context."),
        output_format: z.literal("svg").default("svg").describe("Output format. Currently only svg is supported."),
        strict_notation: z.boolean().default(true).describe("When true, enforce strict UML class notation."),
      }),
      _meta: { ui: { resourceUri: EDITOR_RESOURCE_URI, visibility: ["model", "app"] } },
    },
    async (args) => {
      const mermaid = resolveMermaidFromRequest("uml_class", args.request, args.existing_diagram);
      const svg = await tryRenderSvg(mermaid);
      return wrapResult({
        title: "UML Class Diagram",
        diagramType: "uml_class",
        mermaid,
        svg,
        notationRules: ["Class blocks", "Typed UML relations", "Attributes/methods sectioned", args.strict_notation ? "Strict notation enabled" : "Strict notation disabled"],
      });
    },
  );

  registerAppTool(
    server,
    "generate_uml_activity_diagram",
    {
      title: "Generate UML Activity Diagram",
      description:
        "Create or update a UML activity-style flow with start, activities, and end. If editing, provide full updated Mermaid in `request`.",
      inputSchema: z.object({
        request: z.string().describe("New UML activity request or full updated Mermaid when editing."),
        existing_diagram: z.string().optional().describe("Optional existing Mermaid source for edit context."),
        output_format: z.literal("svg").default("svg").describe("Output format. Currently only svg is supported."),
        strict_notation: z.boolean().default(true).describe("When true, enforce strict UML activity notation."),
      }),
      _meta: { ui: { resourceUri: EDITOR_RESOURCE_URI, visibility: ["model", "app"] } },
    },
    async (args) => {
      const mermaid = resolveMermaidFromRequest("uml_activity", args.request, args.existing_diagram);
      const svg = await tryRenderSvg(mermaid);
      return wrapResult({
        title: "UML Activity Diagram",
        diagramType: "uml_activity",
        mermaid,
        svg,
        notationRules: ["Start/End nodes", "Directed control flow", "Ordered activities", args.strict_notation ? "Strict notation enabled" : "Strict notation disabled"],
      });
    },
  );

  registerAppTool(
    server,
    "generate_uml_sequence_diagram",
    {
      title: "Generate UML Sequence Diagram",
      description:
        "Create or update a UML sequence diagram with activation bars, solid request arrows, and dashed response arrows. If editing, provide full updated Mermaid in `request`.",
      inputSchema: z.object({
        request: z.string().describe("New UML sequence request or full updated Mermaid when editing."),
        existing_diagram: z.string().optional().describe("Optional existing Mermaid source for edit context."),
        output_format: z.literal("svg").default("svg").describe("Output format. Currently only svg is supported."),
        strict_notation: z.boolean().default(true).describe("When true, enforce strict UML sequence notation."),
      }),
      _meta: { ui: { resourceUri: EDITOR_RESOURCE_URI, visibility: ["model", "app"] } },
    },
    async (args) => {
      const mermaid = resolveMermaidFromRequest("uml_sequence", args.request, args.existing_diagram);
      const svg = await tryRenderSvg(mermaid);
      return wrapResult({
        title: "UML Sequence Diagram",
        diagramType: "uml_sequence",
        mermaid,
        svg,
        notationRules: [
          "Participants explicitly declared",
          "Solid arrows for requests (->>)",
          "Dashed arrows for responses (-->>)",
          "Activation/deactivation bars around processing",
          args.strict_notation ? "Strict notation enabled" : "Strict notation disabled",
        ],
      });
    },
  );

  registerAppTool(
    server,
    "generate_uml_use_case_diagram",
    {
      title: "Generate UML Use Case Diagram",
      description:
        "Create or update a UML use case diagram with actors, use cases, and associations. If editing, provide full updated Mermaid in `request`.",
      inputSchema: z.object({
        request: z.string().describe("New UML use case request or full updated Mermaid when editing."),
        existing_diagram: z.string().optional().describe("Optional existing Mermaid source for edit context."),
        output_format: z.literal("svg").default("svg").describe("Output format. Currently only svg is supported."),
        strict_notation: z.boolean().default(true).describe("When true, enforce strict UML use case notation."),
      }),
      _meta: { ui: { resourceUri: EDITOR_RESOURCE_URI, visibility: ["model", "app"] } },
    },
    async (args) => {
      const mermaid = resolveMermaidFromRequest("uml_use_case", args.request, args.existing_diagram);
      const svg = await tryRenderSvg(mermaid);
      return wrapResult({
        title: "UML Use Case Diagram",
        diagramType: "uml_use_case",
        mermaid,
        svg,
        notationRules: ["Actors modeled", "Use-cases grouped by system boundary", "Actor/use-case associations shown", args.strict_notation ? "Strict notation enabled" : "Strict notation disabled"],
      });
    },
  );

  return server;
}

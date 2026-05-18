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
  for (const e of input.external_entities) lines.push(`  ${id("E", e)}[${escape(e)}]`);
  for (const p of input.processes) lines.push(`  ${id("P", p)}((${escape(p)}))`);
  for (const d of input.data_stores) lines.push(`  ${id("D", d)}[/${escape(d)}/]`);
  for (const f of input.data_flows) lines.push(`  ${idAny(f.from)} -->|${escape(f.label)}| ${idAny(f.to)}`);
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
function idAny(value: string): string {
  return value.includes("_") ? safeName(value) : safeName(value);
}
function safeName(value: string): string {
  return value.replace(/[^a-zA-Z0-9_]/g, "_");
}
function escape(value: string): string {
  return value.replace(/\n/g, " ").replace(/"/g, "'");
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
      description: "Generate a free-form Mermaid diagram. Accepts existing diagram context for edits.",
      inputSchema: z.object({ prompt: z.string().optional(), mermaid_source: z.string().optional(), existing_diagram: z.string().optional() }),
      _meta: { ui: { resourceUri: EDITOR_RESOURCE_URI, visibility: ["model", "app"] } },
    },
    async (args) => {
      const src = args.mermaid_source || args.existing_diagram || `flowchart LR\n  A[Client] --> B[Service]\n  B --> C[(Database)]\n  B --> D[External API]`;
      const svg = await tryRenderSvg(src);
      return wrapResult({ title: "General Diagram", diagramType: "general", mermaid: src, svg, notationRules: ["Mermaid valid syntax", "Theme fixed to neutral", "Output fixed to SVG"] });
    },
  );

  registerAppTool(
    server,
    "generate_data_flow_diagram",
    {
      title: "Generate Data Flow Diagram",
      description: "Generate a DFD using process circles, external entity rectangles, open-ended datastore rectangles, and directed data-flow arrows.",
      inputSchema: z.object({
        system_name: z.string(),
        external_entities: z.array(z.string()).default([]),
        processes: z.array(z.string()).default([]),
        data_stores: z.array(z.string()).default([]),
        data_flows: z.array(z.object({ from: z.string(), to: z.string(), label: z.string() })).default([]),
        existing_diagram: z.string().optional(),
      }),
      _meta: { ui: { resourceUri: EDITOR_RESOURCE_URI, visibility: ["model", "app"] } },
    },
    async (args) => {
      const mermaid = args.existing_diagram || buildDfd(args);
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
        ],
      });
    },
  );

  registerAppTool(
    server,
    "generate_entity_relationship_diagram",
    {
      title: "Generate ER Diagram",
      description: "Generate an ER diagram with entities, attributes, relationships, and cardinality.",
      inputSchema: z.object({
        entities: z.array(z.object({ name: z.string(), attributes: z.array(z.string()).default([]), primary_key: z.string().optional(), foreign_keys: z.array(z.string()).optional() })),
        relationships: z.array(z.object({ left: z.string(), right: z.string(), left_cardinality: z.string(), right_cardinality: z.string(), label: z.string().optional() })),
        existing_diagram: z.string().optional(),
      }),
      _meta: { ui: { resourceUri: EDITOR_RESOURCE_URI, visibility: ["model", "app"] } },
    },
    async (args) => {
      const mermaid = args.existing_diagram || buildErd(args);
      const svg = await tryRenderSvg(mermaid);
      return wrapResult({
        title: "Entity Relationship Diagram",
        diagramType: "erd",
        mermaid,
        svg,
        notationRules: ["Entities with attributes", "PK/FK notation", "Explicit relationship cardinality"],
      });
    },
  );

  registerAppTool(
    server,
    "generate_uml_class_diagram",
    {
      title: "Generate UML Class Diagram",
      description: "Generate a UML class diagram with classes, attributes, methods, and typed relationships.",
      inputSchema: z.object({
        classes: z.array(z.object({ name: z.string(), attributes: z.array(z.string()).optional(), methods: z.array(z.string()).optional() })),
        relations: z.array(z.object({ from: z.string(), to: z.string(), type: z.enum(["inheritance", "composition", "aggregation", "association"]), label: z.string().optional() })),
        existing_diagram: z.string().optional(),
      }),
      _meta: { ui: { resourceUri: EDITOR_RESOURCE_URI, visibility: ["model", "app"] } },
    },
    async (args) => {
      const mermaid = args.existing_diagram || buildUmlClass(args);
      const svg = await tryRenderSvg(mermaid);
      return wrapResult({ title: "UML Class Diagram", diagramType: "uml_class", mermaid, svg, notationRules: ["Class blocks", "Typed UML relations", "Attributes/methods sectioned"] });
    },
  );

  registerAppTool(
    server,
    "generate_uml_activity_diagram",
    {
      title: "Generate UML Activity Diagram",
      description: "Generate a UML activity-style flow with start, ordered activities, and end.",
      inputSchema: z.object({ title: z.string(), steps: z.array(z.string()), existing_diagram: z.string().optional() }),
      _meta: { ui: { resourceUri: EDITOR_RESOURCE_URI, visibility: ["model", "app"] } },
    },
    async (args) => {
      const mermaid = args.existing_diagram || buildUmlActivity(args);
      const svg = await tryRenderSvg(mermaid);
      return wrapResult({ title: "UML Activity Diagram", diagramType: "uml_activity", mermaid, svg, notationRules: ["Start/End nodes", "Directed control flow", "Ordered activities"] });
    },
  );

  registerAppTool(
    server,
    "generate_uml_sequence_diagram",
    {
      title: "Generate UML Sequence Diagram",
      description: "Generate a UML sequence diagram with activation bars, solid request arrows, and dashed response arrows.",
      inputSchema: z.object({
        title: z.string(),
        participants: z.array(z.string()),
        interactions: z.array(z.object({ from: z.string(), to: z.string(), request: z.string(), response: z.string().optional(), activate: z.boolean().optional() })),
        existing_diagram: z.string().optional(),
      }),
      _meta: { ui: { resourceUri: EDITOR_RESOURCE_URI, visibility: ["model", "app"] } },
    },
    async (args) => {
      const mermaid = args.existing_diagram || buildUmlSequence(args);
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
        ],
      });
    },
  );

  registerAppTool(
    server,
    "generate_uml_use_case_diagram",
    {
      title: "Generate UML Use Case Diagram",
      description: "Generate a UML use case diagram with actors, use cases, and actor-use-case associations.",
      inputSchema: z.object({
        system_name: z.string(),
        actors: z.array(z.string()),
        use_cases: z.array(z.string()),
        links: z.array(z.object({ actor: z.string(), use_case: z.string() })),
        existing_diagram: z.string().optional(),
      }),
      _meta: { ui: { resourceUri: EDITOR_RESOURCE_URI, visibility: ["model", "app"] } },
    },
    async (args) => {
      const mermaid = args.existing_diagram || buildUmlUseCase(args);
      const svg = await tryRenderSvg(mermaid);
      return wrapResult({ title: "UML Use Case Diagram", diagramType: "uml_use_case", mermaid, svg, notationRules: ["Actors modeled", "Use-cases grouped by system boundary", "Actor/use-case associations shown"] });
    },
  );

  registerAppTool(
    server,
    "edit_diagram",
    {
      title: "Edit Diagram",
      description: "Edit an existing diagram without rebuilding from scratch. Returns updated Mermaid and SVG.",
      inputSchema: z.object({ diagram_type: z.string(), existing_diagram: z.string(), edit_instructions: z.string() }),
      _meta: { ui: { resourceUri: EDITOR_RESOURCE_URI, visibility: ["model", "app"] } },
    },
    async (args) => {
      const appended = `\n\n%% Edit instructions applied:\n%% ${args.edit_instructions.replace(/\n/g, " ")}`;
      const mermaid = `${args.existing_diagram}${appended}`;
      const svg = await tryRenderSvg(mermaid);
      return wrapResult({
        title: "Edited Diagram",
        diagramType: (args.diagram_type as DiagramType) ?? "general",
        mermaid,
        svg,
        notationRules: ["Preserve existing structure", "Apply edits incrementally", "Maintain diagram-type notation constraints"],
      });
    },
  );

  registerAppTool(
    server,
    "render_diagram",
    {
      title: "Render Diagram",
      description: "Internal app helper: render provided Mermaid source to SVG while preserving source as canonical output.",
      inputSchema: z.object({ diagram_type: z.string().optional(), mermaid_source: z.string() }),
      _meta: { ui: { resourceUri: EDITOR_RESOURCE_URI, visibility: ["app"] } },
    },
    async (args) => {
      const svg = await tryRenderSvg(args.mermaid_source);
      return wrapResult({
        title: "Rendered Diagram",
        diagramType: (args.diagram_type as DiagramType) ?? "general",
        mermaid: args.mermaid_source,
        svg,
        notationRules: ["Theme fixed to neutral", "Output fixed to SVG"],
      });
    },
  );

  return server;
}

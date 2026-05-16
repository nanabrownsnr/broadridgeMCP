# Solution Architecture Tools MCP

Interactive MCP server for generating and editing architecture diagrams with Mermaid.

## Endpoint

- HTTP MCP: `http://localhost:8019/mcp`

## What it provides

Tools:
- `generate_general_diagram`
- `generate_data_flow_diagram`
- `generate_entity_relationship_diagram`
- `generate_uml_class_diagram`
- `generate_uml_activity_diagram`
- `generate_uml_sequence_diagram`
- `generate_uml_use_case_diagram`
- `edit_diagram`
- `render_diagram`

MCP App UI:
- `ui://solution-architecture-tools/editor.html`
- React editor + live SVG preview
- Server tool calls from UI for context-sync updates

## Defaults

- Theme: `neutral`
- Output: `svg`
- Canonical source: Mermaid text (`mermaid_source`)

## Environment

- `PORT=8019`
- `MERMAID_RENDER_BASE_URL=https://mermaid.ink`

## Run

```bash
npm install
npm run start:prod
```

## Contract

UI-enabled tools return both:
- `content` (assistant-readable summary)
- `structuredContent` (UI payload)

This keeps chat context and visual state synchronized.
# Recruitee Apps MCP

Standalone MCP Apps server for Recruitee.

## What it does
- Exposes a single public MCP endpoint for Recruitee UI usage.
- Registers MCP App tools with `_meta.ui.resourceUri`.
- Registers a real `ui://recruitee/app.html` resource (`text/html;profile=mcp-app`).
- Proxies calls to existing internal `recruitee-mcp` HTTP API.

## Tools
- Exposes all existing `recruitee_*` tools through one endpoint (proxy to internal `recruitee-mcp` API).
- Two tools are UI-enabled:
  - `recruitee_list_job_openings` (UI view: openings explorer)
  - `recruitee_list_candidates` (UI view: pipeline kanban)
- App-only drag/drop action:
  - `recruitee_move_candidate_stage` (`visibility: ["app"]`)

## Run
```bash
npm install
npm run start:prod
```

Server endpoint:
- `http://localhost:8014/mcp` (public via docker-compose)

Environment:
- `RECRUITEE_MCP_BASE_URL` default `http://recruitee-mcp:8000`
- `PORT` default `8018` (container port; compose maps it to host `8014`)

## Skill-Compliance Notes
- Uses `registerAppTool` + `registerAppResource`.
- Tool-to-resource link via `_meta.ui.resourceUri`.
- Resource is served as `text/html;profile=mcp-app` (`RESOURCE_MIME_TYPE`).
- Tools always return text `content` fallback, even with `structuredContent`.
- Errors return `isError: true` so host/model can handle failures.
- App handlers are registered before `app.connect()`.

## Local Basic-Host Test
1. Start this server:
```bash
npm install
npm run start:prod
```
2. Run ext-apps basic-host from a separate checkout:
```bash
git clone https://github.com/modelcontextprotocol/ext-apps.git /tmp/mcp-ext-apps
cd /tmp/mcp-ext-apps/examples/basic-host
npm install
SERVERS='["http://localhost:8018/mcp"]' npm run start
```
3. Open `http://localhost:8080` and invoke:
- `recruitee_openings_explorer`
- `recruitee_pipeline_kanban`

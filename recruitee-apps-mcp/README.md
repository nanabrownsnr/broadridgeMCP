# Recruitee Apps MCP

Standalone MCP Apps server for Recruitee.

## What it does
- Registers MCP App tools with `_meta.ui.resourceUri`.
- Registers a real `ui://recruitee/app.html` resource (`text/html;profile=mcp-app`).
- Proxies data calls to existing `recruitee-mcp` HTTP API.

## Tools
- `recruitee_openings_explorer`
- `recruitee_pipeline_kanban`
- `recruitee_move_candidate_stage_action` (app-only)

## Run
```bash
npm install
npm run start:prod
```

Server endpoint:
- `http://localhost:8018/mcp`

Environment:
- `RECRUITEE_MCP_BASE_URL` default `http://recruitee-mcp:8000`
- `PORT` default `8018`

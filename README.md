# MCP Suite

Two independent MCP servers in one repo:

- `filesystem-mcp`: safe file operations, command execution, and static preview serving
- `vision-mcp`: download and analyze a source URL (image/pdf/html) into structured JSON
- `text-classifier-mcp`: CPU-first IT triage classifier (backend_bug, frontend_bug, missing_feature, etc.)

## One-command deploy

```powershell
./deploy.ps1
```

This builds and starts both services via Docker Compose.

- Filesystem MCP: `http://localhost:8011`
- Vision MCP: `http://localhost:8012`
- Text Classifier MCP: `http://localhost:8013`
- Streamable HTTP MCP endpoints:
  - `http://localhost:8011/mcp`
  - `http://localhost:8012/mcp`
- SSE fallback endpoints:
  - `http://localhost:8011/sse`
  - `http://localhost:8012/sse`

## Notes

- This scaffold follows the local `MCP ref Doc` architecture shape.
- Fill environment variables in each service `.env` before production use.
- `vision-mcp` includes `compare_images` for redesign fidelity scoring and correction hints.
- `vision-mcp` supports OCR backend selection via `OCR_BACKEND` (`paddle` default, `rapid` fallback).
- `text-classifier-mcp` supports single classify, batch classify, and incremental retraining endpoints.

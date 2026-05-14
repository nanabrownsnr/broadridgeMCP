# MCP Suite

MCP servers in one repo:

- `filesystem-mcp`: safe file operations, command execution, and static preview serving
- `vision-mcp`: download and analyze a source URL (image/pdf/html) into structured JSON
- `text-classifier-mcp`: CPU-first taxonomy classifier (e.g., `twynity_tickets`, `hr_tickets`) with locked label sets
- `recruitee-mcp`: hiring workflow tools for roles, candidates, stages, and publish URLs
- `candidate-intelligence-mcp`: resume-to-role matching (single + batch) with built-in mini-graph scoring and evidence
- `docusign-mcp`: send signature envelopes, track status, list candidate-linked envelopes, and fetch completed document references

## One-command deploy

```powershell
./deploy.ps1
```

This builds and starts all services via Docker Compose.

- Filesystem MCP: `http://localhost:8011`
- Vision MCP: `http://localhost:8012`
- Text Classifier MCP: `http://localhost:8013`
- Recruitee MCP: `http://localhost:8014`
- Candidate Intelligence MCP: `http://localhost:8015`
- DocuSign MCP: `http://localhost:8016`
- Streamable HTTP MCP endpoints:
  - `http://localhost:8011/mcp`
  - `http://localhost:8012/mcp`
  - `http://localhost:8013/mcp`
  - `http://localhost:8014/mcp`
  - `http://localhost:8015/mcp`
  - `http://localhost:8016/mcp`
- SSE fallback endpoints:
  - `http://localhost:8011/sse`
  - `http://localhost:8012/sse`
  - `http://localhost:8013/sse`
  - `http://localhost:8014/sse`
  - `http://localhost:8015/sse`
  - `http://localhost:8016/sse`

## Notes

- This scaffold follows the local `MCP ref Doc` architecture shape.
- Fill environment variables in each service `.env` before production use.
- `vision-mcp` includes `compare_images` for redesign fidelity scoring and correction hints.
- `vision-mcp` supports OCR backend selection via `OCR_BACKEND` (`paddle` default, `rapid` fallback).
- `text-classifier-mcp` supports taxonomy management, taxonomy-scoped classify/batch classify, and incremental retraining.

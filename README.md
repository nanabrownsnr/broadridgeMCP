# MCP Suite

Two independent MCP servers in one repo:

- `filesystem-mcp`: safe file operations, command execution, and static preview serving
- `vision-mcp`: download and analyze a source URL (image/pdf/html) into structured JSON

## One-command deploy

```powershell
./deploy.ps1
```

This builds and starts both services via Docker Compose.

- Filesystem MCP: `http://localhost:8011`
- Vision MCP: `http://localhost:8012`

## Notes

- This scaffold follows the local `MCP ref Doc` architecture shape.
- Fill environment variables in each service `.env` before production use.

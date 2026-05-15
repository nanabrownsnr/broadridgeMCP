import { App } from "@modelcontextprotocol/ext-apps";

const app = new App({ name: "Recruitee App", version: "0.1.0" });

const root = document.getElementById("app")!;

function escapeHtml(value: unknown): string {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function renderJsonBlock(data: unknown): string {
  return `<pre>${escapeHtml(JSON.stringify(data, null, 2))}</pre>`;
}

function renderOpenings(data: any): string {
  const openings = data?.data?.openings ?? [];
  const rows = openings
    .map((o: any) => `<tr><td>${o.offer_id}</td><td>${escapeHtml(o.title)}</td><td>${escapeHtml(o.status)}</td></tr>`)
    .join("");
  return `
    <h3>Openings Explorer</h3>
    <table><thead><tr><th>Offer ID</th><th>Title</th><th>Status</th></tr></thead><tbody>${rows}</tbody></table>
    ${renderJsonBlock(data)}
  `;
}

function renderPipeline(data: any): string {
  return `
    <h3>Pipeline Kanban</h3>
    <p>Offer: <strong>${escapeHtml(data?.data?.offer_id)}</strong></p>
    ${renderJsonBlock(data)}
  `;
}

app.ontoolresult = (result) => {
  const payload: any = result.structuredContent ?? {};
  const view = payload?.view;

  if (view === "openings_explorer") {
    root.innerHTML = renderOpenings(payload);
    return;
  }

  if (view === "pipeline_kanban") {
    root.innerHTML = renderPipeline(payload);
    return;
  }

  root.innerHTML = `<h3>Recruitee App</h3>${renderJsonBlock(result)}`;
};

app.connect();

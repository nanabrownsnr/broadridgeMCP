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

function formatDate(v: unknown): string {
  if (!v) return "Not published";
  const d = new Date(String(v));
  return Number.isNaN(d.getTime()) ? String(v) : d.toLocaleDateString();
}

function renderOpenings(payload: any): string {
  const openings = payload?.data?.openings ?? [];
  const summary = payload?.data?.total_count ?? openings.length;
  const rows = openings
    .map(
      (o: any) => `
      <tr class="opening-row" data-offer-id="${o.offer_id}">
        <td>${o.offer_id}</td>
        <td>${escapeHtml(o.title)}</td>
        <td><span class="status-chip">${escapeHtml(o.status)}</span></td>
        <td>${escapeHtml(formatDate(o.published_at))}</td>
      </tr>`,
    )
    .join("");

  return `
    <section class="panel-card">
      <div class="panel-head">
        <h3>Openings Explorer</h3>
        <p>${summary} opening(s)</p>
      </div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Offer ID</th><th>Title</th><th>Status</th><th>Published</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      <div id="opening-details" class="detail-card">Click a row to view opening details.</div>
    </section>
  `;
}

function renderPipeline(payload: any): string {
  const selectedOfferId = payload?.offer_id;
  const candidates = payload?.data?.candidates ?? [];
  const buckets = new Map<string, Array<{ id: number; name: string; email: string; stageId: number | null }>>();

  for (const c of candidates) {
    const placements = Array.isArray(c.placements) ? c.placements : [];
    const placement =
      selectedOfferId != null
        ? placements.find((p: any) => p.offer_id === selectedOfferId)
        : placements.find((p: any) => p.offer_id != null);
    if (!placement) continue;

    const stageId = placement.stage_id ?? null;
    const stageName =
      placement.stage_name && String(placement.stage_name).trim().length > 0
        ? String(placement.stage_name)
        : null;
    const stageKey = stageName ?? (stageId != null ? `Stage ${stageId}` : "Unstaged");
    const card = {
      id: c.candidate_id,
      name: c.name ?? "Unknown",
      email: Array.isArray(c.emails) && c.emails.length > 0 ? c.emails[0] : "",
      stageId,
    };

    if (!buckets.has(stageKey)) buckets.set(stageKey, []);
    buckets.get(stageKey)!.push(card);
  }

  const columns = Array.from(buckets.entries())
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([stage, cards]) => {
      const stageId = stage.startsWith("Stage ") ? stage.replace("Stage ", "") : "";
      const cardsHtml = cards
        .map(
          (card) => `
          <div class="candidate-card" draggable="true" data-candidate-id="${card.id}" data-stage-id="${card.stageId ?? ""}">
            <div class="candidate-name">${escapeHtml(card.name)}</div>
            <div class="candidate-email">${escapeHtml(card.email)}</div>
            <div class="candidate-meta">ID: ${card.id}</div>
          </div>`,
        )
        .join("");
      return `
        <section class="stage-column" data-stage-id="${stageId}">
          <header class="stage-head">${escapeHtml(stage)} (${cards.length})</header>
          <div class="stage-cards">
            ${cardsHtml || `<div class="stage-empty">No candidates</div>`}
          </div>
        </section>
      `;
    })
    .join("");

  return `
    <section class="panel-card">
      <div class="panel-head">
        <h3>Pipeline Kanban</h3>
        <p>Offer: ${escapeHtml(selectedOfferId ?? "All offers")}</p>
      </div>
      <p id="kanban-status" class="helper">Drag a card to move candidate stages.</p>
      <div class="kanban-wrap">${columns || "<p>No candidates available for this view.</p>"}</div>
    </section>
  `;
}

function bindOpeningsInteractions() {
  const details = document.getElementById("opening-details");
  const rows = Array.from(document.querySelectorAll<HTMLTableRowElement>(".opening-row"));
  const openings = (window as any).__openings ?? [];

  for (const row of rows) {
    row.tabIndex = 0;
    row.addEventListener("click", () => {
      for (const r of rows) r.classList.remove("selected");
      row.classList.add("selected");
      const offerId = Number(row.dataset.offerId ?? "0");
      const opening = openings.find((o: any) => o.offer_id === offerId);
      if (!details || !opening) return;
      details.innerHTML = `
        <h4>${escapeHtml(opening.title)}</h4>
        <div><strong>Offer ID:</strong> ${opening.offer_id}</div>
        <div><strong>Status:</strong> ${escapeHtml(opening.status)}</div>
        <div><strong>Slug:</strong> ${escapeHtml(opening.slug ?? "-")}</div>
        <div><strong>Published:</strong> ${escapeHtml(formatDate(opening.published_at))}</div>
      `;
    });
    row.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" || ev.key === " ") {
        ev.preventDefault();
        row.click();
      }
    });
  }
}

function bindKanbanInteractions(payload: any) {
  const statusEl = document.getElementById("kanban-status");
  const cards = Array.from(document.querySelectorAll<HTMLElement>(".candidate-card"));
  const columns = Array.from(document.querySelectorAll<HTMLElement>(".stage-column"));
  const offerId = payload?.offer_id;

  for (const card of cards) {
    card.tabIndex = 0;
    card.addEventListener("dragstart", (ev) => {
      card.classList.add("dragging");
      ev.dataTransfer?.setData("candidate-id", card.dataset.candidateId ?? "");
    });
    card.addEventListener("dragend", () => card.classList.remove("dragging"));
  }

  for (const col of columns) {
    col.tabIndex = 0;
    col.addEventListener("dragover", (ev) => {
      ev.preventDefault();
      col.classList.add("drop-target");
    });
    col.addEventListener("dragleave", () => col.classList.remove("drop-target"));
    col.addEventListener("drop", async (ev) => {
      ev.preventDefault();
      col.classList.remove("drop-target");

      const candidateId = Number(ev.dataTransfer?.getData("candidate-id") ?? "0");
      const stageRaw = col.dataset.stageId ?? "";
      const stageId = Number(stageRaw);
      if (!candidateId || !stageRaw || Number.isNaN(stageId)) return;

      const card = document.querySelector<HTMLElement>(`.candidate-card[data-candidate-id="${candidateId}"]`);
      const targetCards = col.querySelector(".stage-cards");
      if (card && targetCards) {
        targetCards.appendChild(card);
        card.dataset.stageId = String(stageId);
      }

      if (statusEl) statusEl.textContent = `Moving candidate ${candidateId} to stage ${stageId}...`;

      if (offerId == null) {
        if (statusEl) statusEl.textContent = "Move not synced: missing offer_id.";
        return;
      }

      try {
        await app.callServerTool("recruitee_move_candidate_stage", {
          candidate_id: candidateId,
          offer_id: offerId,
          stage_id: stageId,
        });
        if (statusEl) statusEl.textContent = `Candidate ${candidateId} moved to stage ${stageId}.`;
      } catch {
        if (statusEl) statusEl.textContent = `Move failed for candidate ${candidateId}.`;
      }
    });
  }
}

app.ontoolinput = () => {
  root.innerHTML = `<section class="panel-card"><p class="helper">Loading view data...</p></section>`;
};

app.ontoolresult = (result) => {
  const payload: any = result.structuredContent ?? {};
  const view = payload?.view;

  if (view === "openings_explorer") {
    (window as any).__openings = payload?.data?.openings ?? [];
    root.innerHTML = renderOpenings(payload);
    bindOpeningsInteractions();
    return;
  }

  if (view === "pipeline_kanban") {
    root.innerHTML = renderPipeline(payload);
    bindKanbanInteractions(payload);
    return;
  }

  root.innerHTML = `<section class="panel-card"><h3>Recruitee App</h3><p class="helper">Run a supported Recruitee UI tool to load a view.</p></section>`;
};

app.onteardown = async () => ({});
app.connect();

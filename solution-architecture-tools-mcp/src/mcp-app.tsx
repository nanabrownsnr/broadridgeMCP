import React, { useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { App } from "@modelcontextprotocol/ext-apps";

type Payload = {
  view?: string;
  title?: string;
  diagram_type?: string;
  mermaid_source?: string;
  svg?: string | null;
  notation_rules?: string[];
  warnings?: string[];
};

const app = new App({ name: "Solution Architecture App", version: "0.1.0" });

function DiagramEditor() {
  const [payload, setPayload] = useState<Payload | null>(null);
  const [source, setSource] = useState("");
  const [editInstructions, setEditInstructions] = useState("Refine labels and improve readability");

  app.ontoolresult = (result) => {
    const p = (result.structuredContent ?? {}) as Payload;
    setPayload(p);
    setSource(p.mermaid_source ?? "");
  };

  app.ontoolinput = () => {};

  const svgDataUri = useMemo(() => {
    if (!payload?.svg) return null;
    return `data:image/svg+xml;utf8,${encodeURIComponent(payload.svg)}`;
  }, [payload?.svg]);

  const onRender = async () => {
    await app.callServerTool("render_diagram", {
      diagram_type: payload?.diagram_type ?? "general",
      mermaid_source: source,
    });
  };

  const onEdit = async () => {
    await app.callServerTool("edit_diagram", {
      diagram_type: payload?.diagram_type ?? "general",
      existing_diagram: source,
      edit_instructions: editInstructions,
    });
  };

  if (!payload || payload.view !== "diagram_editor") {
    return (
      <section className="card">
        <h1>Solution Architecture Tools</h1>
        <p className="meta">Run a diagram tool to load the interactive editor.</p>
      </section>
    );
  }

  return (
    <div className="shell">
      <section className="card">
        <h1>{payload.title ?? "Diagram Editor"}</h1>
        <p className="meta">
          Type: {payload.diagram_type ?? "general"} | Theme: neutral | Output: svg
        </p>
        <div className="actions">
          <button className="primary" onClick={onRender}>Render SVG</button>
          <button onClick={onEdit}>Apply Edit</button>
        </div>
        <textarea value={source} onChange={(e) => setSource(e.target.value)} spellCheck={false} />
        <div className="warn">Edits run through server tools to keep chat context and UI state synchronized.</div>
      </section>
      <section className="card">
        <h1>Preview</h1>
        <div className="preview">{svgDataUri ? <img src={svgDataUri} alt="diagram preview" /> : <p className="meta">No SVG available yet.</p>}</div>
        <div style={{ marginTop: 10 }}>
          <p className="meta" style={{ marginBottom: 6 }}>Notation Rules</p>
          <ul className="rules">
            {(payload.notation_rules ?? []).map((r, idx) => (
              <li key={idx}>{r}</li>
            ))}
          </ul>
        </div>
        <div style={{ marginTop: 10 }}>
          <p className="meta" style={{ marginBottom: 6 }}>Warnings</p>
          <ul className="rules">
            {(payload.warnings ?? []).length ? (payload.warnings ?? []).map((w, idx) => <li key={idx}>{w}</li>) : <li>None</li>}
          </ul>
        </div>
        <div style={{ marginTop: 10 }}>
          <p className="meta" style={{ marginBottom: 6 }}>Edit Instruction</p>
          <textarea value={editInstructions} onChange={(e) => setEditInstructions(e.target.value)} style={{ minHeight: 90 }} />
        </div>
      </section>
    </div>
  );
}

const root = createRoot(document.getElementById("app")!);
root.render(<DiagramEditor />);

app.onteardown = async () => ({});
app.connect();
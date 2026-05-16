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
  const [canFullscreen, setCanFullscreen] = useState(false);
  const [displayMode, setDisplayMode] = useState<string>("inline");

  app.ontoolresult = (result) => {
    const p = (result.structuredContent ?? {}) as Payload;
    setPayload(p);
    const nextSource = p.mermaid_source ?? "";
    setSource(nextSource);
  };

  app.ontoolinput = () => {};
  app.onhostcontextchanged = (ctx: any) => {
    const modes = Array.isArray(ctx?.availableDisplayModes) ? ctx.availableDisplayModes : [];
    setCanFullscreen(modes.includes("fullscreen"));
    if (ctx?.displayMode) setDisplayMode(ctx.displayMode);
  };

  const svgDataUri = useMemo(() => {
    if (!payload?.svg) return null;
    return `data:image/svg+xml;utf8,${encodeURIComponent(payload.svg)}`;
  }, [payload?.svg]);

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
          {canFullscreen ? (
            <button
              onClick={async () => {
                const nextMode = displayMode === "fullscreen" ? "inline" : "fullscreen";
                await app.requestDisplayMode({ mode: nextMode as any });
              }}
            >
              {displayMode === "fullscreen" ? "Exit Fullscreen" : "Fullscreen"}
            </button>
          ) : null}
        </div>
        <textarea value={source} readOnly spellCheck={false} />
        <div className="warn">To edit diagrams, ask in chat and the tool will update both context and preview.</div>
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
      </section>
    </div>
  );
}

const root = createRoot(document.getElementById("app")!);
root.render(<DiagramEditor />);

app.onteardown = async () => ({});
app.connect();

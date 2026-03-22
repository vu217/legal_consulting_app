import { useCallback, useEffect, useState } from "react";
import { fetchConfig, fetchHealthDependencies, fetchIndexStats, ingestUpload } from "../api";
import type { HealthDeps, IndexStats, PublicConfig } from "../types";

export interface AnalysisUiState {
  running: boolean;
  pct: number;
  completedSteps: number;
  pulsingStep: number | null;
  statusText: string;
  timeNote: string;
}

interface StatusPanelProps {
  analysis: AnalysisUiState;
  onCancelAnalysis: () => void;
}

function isWindows(): boolean {
  return typeof navigator !== "undefined" && /Win/i.test(navigator.userAgent);
}

function CopyRow({ label, hint, command }: { label: string; hint: string; command: string }) {
  const [copied, setCopied] = useState(false);
  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* ignore */
    }
  };
  return (
    <div className="shutdown-row">
      <div>
        <div className="shutdown-label">{label}</div>
        <div className="shutdown-hint">{hint}</div>
      </div>
      <button
        type="button"
        className={`copy-btn${copied ? " copy-btn--copied" : ""}`}
        onClick={onCopy}
        aria-label={`Copy ${label}`}
      >
        {copied ? "Copied!" : "Copy"}
      </button>
    </div>
  );
}

export function StatusPanel({ analysis, onCancelAnalysis }: StatusPanelProps) {
  const [cfg, setCfg] = useState<PublicConfig | null>(null);
  const [cfgErr, setCfgErr] = useState<string | null>(null);
  const [health, setHealth] = useState<HealthDeps | null>(null);
  const [stats, setStats] = useState<IndexStats | null>(null);
  const [bootLoading, setBootLoading] = useState(true);
  const [serverReachable, setServerReachable] = useState(true);
  const [files, setFiles] = useState<FileList | null>(null);
  const [ingestBusy, setIngestBusy] = useState(false);
  const [ingestLines, setIngestLines] = useState<{ name: string; ok: boolean; text: string }[]>([]);
  const [dragOver, setDragOver] = useState(false);

  const refreshStats = useCallback(async () => {
    try {
      const s = await fetchIndexStats();
      setStats(s);
    } catch {
      /* ignore */
    }
  }, []);

  const loadAll = useCallback(async () => {
    try {
      const [h, s, c] = await Promise.all([
        fetchHealthDependencies(),
        fetchIndexStats(),
        fetchConfig(),
      ]);
      setHealth(h);
      setStats(s);
      setCfg(c);
      setCfgErr(null);
      setServerReachable(true);
    } catch (e) {
      setServerReachable(false);
      setCfgErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBootLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadAll();
    const t = window.setInterval(() => {
      void (async () => {
        try {
          const [h, s] = await Promise.all([fetchHealthDependencies(), fetchIndexStats()]);
          setHealth(h);
          setStats(s);
          setServerReachable(true);
        } catch (e) {
          setServerReachable(false);
          setCfgErr(e instanceof Error ? e.message : String(e));
        }
      })();
    }, 30_000);
    return () => window.clearInterval(t);
  }, [loadAll]);

  const onIngest = async () => {
    if (!files?.length) return;
    setIngestBusy(true);
    setIngestLines([]);
    const lines: { name: string; ok: boolean; text: string }[] = [];
    try {
      for (let i = 0; i < files.length; i++) {
        const f = files[i];
        try {
          const r = await ingestUpload(f);
          lines.push({
            name: f.name,
            ok: true,
            text: `${r.chunks} sections added`,
          });
        } catch (e) {
          lines.push({
            name: f.name,
            ok: false,
            text: e instanceof Error ? e.message : String(e),
          });
        }
      }
      setIngestLines(lines);
      await refreshStats();
    } finally {
      setIngestBusy(false);
    }
  };

  const ollamaReachable = !!(health?.ollama_api_ok ?? health?.ollama_ok);
  const aiGreen =
    ollamaReachable &&
    !!health?.models_present?.llm &&
    !!health?.models_present?.fast_llm &&
    !!health?.models_present?.embed;
  const aiAmber = ollamaReachable && !aiGreen;
  const aiRed = health != null && !ollamaReachable;
  const libGreen = !!health?.qdrant_ok && !!health?.collection_exists;
  const libRed = health != null && !libGreen;

  const maxChunks = Math.max(1, ...(stats?.pdfs.map((p) => p.chunks) ?? [1]));

  const ollamaKill = isWindows() ? "taskkill /IM ollama.exe /F" : "pkill ollama";

  return (
    <aside className="sidebar">
      <h2>LegalMind</h2>
      <p className="sidebar-tagline">Your case research runs on this computer.</p>

      <section className="status-cards">
        {bootLoading ? (
          <>
            <div className="skeleton skeleton-line" />
            <div className="skeleton skeleton-line short" />
            <div className="skeleton skeleton-line" style={{ marginTop: 12 }} />
            <div className="skeleton skeleton-line short" />
          </>
        ) : !serverReachable ? (
          <div className="status-card status-card--bad">
            <span className="status-dot status-dot--red" />
            <div>
              <strong>Can&apos;t reach the app server</strong>
              <p className="status-sub">{cfgErr || "Start the backend and refresh the page."}</p>
            </div>
          </div>
        ) : (
          <>
            <div className={`status-card${aiGreen ? " status-card--ok" : aiAmber ? " status-card--warn" : " status-card--bad"}`}>
              <span
                className={`status-dot${aiGreen ? " status-dot--green" : aiAmber ? " status-dot--amber" : " status-dot--red"}${aiGreen ? " status-dot--pulse" : ""}`}
              />
              <div>
                <strong>Your AI</strong>
                <p className="status-sub">
                  {aiGreen && "Your AI is connected and ready."}
                  {aiAmber && "The AI server is running but some models are missing. Open the Ollama app and pull the models your project needs."}
                  {aiRed && (
                    <>
                      Your AI isn&apos;t running. In a terminal run{" "}
                      <code className="inline-code">ollama serve</code>
                      <button
                        type="button"
                        className="copy-btn copy-btn--inline"
                        onClick={() => void navigator.clipboard.writeText("ollama serve")}
                      >
                        Copy
                      </button>
                    </>
                  )}
                </p>
              </div>
            </div>
            <div className={`status-card${libGreen ? " status-card--ok" : " status-card--bad"}`}>
              <span className={`status-dot${libGreen ? " status-dot--green status-dot--pulse" : " status-dot--red"}`} />
              <div>
                <strong>Case library</strong>
                <p className="status-sub">
                  {libGreen && "Your case library is ready."}
                  {libRed && "The case library isn’t reachable. Make sure Docker is running, then start the database container."}
                </p>
              </div>
            </div>
          </>
        )}
      </section>

      {analysis.running && (
        <div className="progress-panel progress-panel--active">
          <div className="progress-pct">{Math.round(analysis.pct)}%</div>
          <div className="progress-track">
            <div className="progress-fill progress-fill--shimmer" style={{ width: `${analysis.pct}%` }} />
          </div>
          <div className="stepper">
            {["Finding similar cases", "Organizing the answer", "Writing your summary"].map((label, i) => {
              const done = analysis.completedSteps > i;
              const active = analysis.pulsingStep === i;
              return (
                <div key={label} className="stepper-row">
                  <div
                    className={`stepper-circle${done ? " stepper-circle--done" : ""}${active && !done ? " stepper-circle--active" : ""}`}
                  >
                    {done ? "✓" : i + 1}
                  </div>
                  <span className={`stepper-label${active ? " stepper-label--active" : ""}`}>{label}</span>
                </div>
              );
            })}
          </div>
          <p className="progress-status">{analysis.statusText}</p>
          <p className="progress-time">{analysis.timeNote}</p>
          <button type="button" className="cancel-link" onClick={onCancelAnalysis}>
            Cancel
          </button>
        </div>
      )}

      <details className="sidebar-section" open>
        <summary>Your documents</summary>
        {stats && (
          <div className="doc-summary">
            <span className="doc-stat">
              <strong>{stats.pdf_count}</strong> PDFs
            </span>
            <span className="doc-stat">
              <strong>{stats.total_chunks}</strong> sections indexed
            </span>
          </div>
        )}
        {stats?.qdrant_vector_count != null &&
          stats.total_chunks > 0 &&
          Math.abs(stats.qdrant_vector_count - stats.total_chunks) > Math.max(20, stats.total_chunks * 0.15) && (
            <p className="doc-hint">Some vectors may be from older indexing not listed here.</p>
          )}
        <div className="doc-list">
          {stats?.pdfs.map((p) => (
            <div key={p.path} className={`doc-row${p.ok ? "" : " doc-row--bad"}`}>
              <span className="doc-icon" title={p.display_name}>
                📄
              </span>
              <div className="doc-meta">
                <div className="doc-name" title={p.display_name}>
                  {p.display_name}
                </div>
                <div className="doc-bar-wrap">
                  <div className="doc-bar" style={{ width: `${(p.chunks / maxChunks) * 100}%` }} />
                </div>
              </div>
              <span className="doc-count">{p.ok ? p.chunks : "—"}</span>
            </div>
          ))}
          {stats && stats.pdfs.length === 0 && <p className="hint">No PDFs indexed yet. Add some below.</p>}
        </div>
      </details>

      <details className="sidebar-section" open>
        <summary>Add PDFs</summary>
        <div
          className={`drop-zone${dragOver ? " drop-zone--active" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            const list = e.dataTransfer.files;
            const pdfs = Array.from(list).filter((f) => f.name.toLowerCase().endsWith(".pdf"));
            if (pdfs.length) {
              const dt = new DataTransfer();
              pdfs.forEach((f) => dt.items.add(f));
              setFiles(dt.files);
            }
          }}
        >
          <input
            type="file"
            accept="application/pdf"
            multiple
            id="pdf-input"
            className="drop-zone-input"
            onChange={(e) => setFiles(e.target.files)}
          />
          <label htmlFor="pdf-input" className="drop-zone-label">
            Click or drag PDFs here
          </label>
        </div>
        <button type="button" className="secondary ingest-btn" onClick={() => void onIngest()} disabled={!files?.length || ingestBusy}>
          {ingestBusy ? (
            <>
              <span className="spinner" /> Adding…
            </>
          ) : (
            "Add to library"
          )}
        </button>
        {ingestLines.length > 0 && (
          <ul className="ingest-results">
            {ingestLines.map((l) => (
              <li key={l.name} className={l.ok ? "ingest-ok" : "ingest-bad"}>
                {l.ok ? "✓" : "✗"} {l.name} — {l.text}
              </li>
            ))}
          </ul>
        )}
      </details>

      <details className="sidebar-section">
        <summary>Shut down</summary>
        <div className="shutdown-row shutdown-row--textonly">
          <div>
            <div className="shutdown-label">Stop the dev stack</div>
            <div className="shutdown-hint">In the terminal where you ran npm run dev, press Ctrl+C.</div>
          </div>
        </div>
        <CopyRow label="Stop the case library (Docker)" hint="From your project folder:" command="docker compose down" />
        <CopyRow label="Stop the AI server" hint="Terminal command:" command={ollamaKill} />
      </details>

      <details className="sidebar-section">
        <summary>Advanced</summary>
        {cfgErr && !cfg && <p className="hint">{cfgErr}</p>}
        {cfg && (
          <div className="advanced-block">
            <div>
              <span className="adv-k">Main model</span> <code>{cfg.llm_model}</code>
            </div>
            <div>
              <span className="adv-k">Fast model</span> <code>{cfg.fast_llm_model}</code>
            </div>
            <div>
              <span className="adv-k">Embeddings</span> <code>{cfg.embed_model}</code>
            </div>
            <div>
              <span className="adv-k">Vector URL</span> <code>{cfg.qdrant_url}</code>
            </div>
          </div>
        )}
      </details>

      <p className="sidebar-foot">Nothing is sent to the cloud. It all stays on your machine.</p>
    </aside>
  );
}

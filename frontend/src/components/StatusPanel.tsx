import { useCallback, useEffect, useState } from "react";
import { fetchConfig, fetchHealthDependencies, fetchIndexStats, ingestUpload } from "../api";
import type { HealthDeps, IndexStats, PublicConfig } from "../types";
import type { PipelineState } from "./PipelineTracker";
import { PipelineTracker } from "./PipelineTracker";
import type { ActivityLogEntry } from "../types";

export interface StatusPanelProps {
  pipeline: PipelineState;
  activityLog: ActivityLogEntry[];
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
    } catch { /* ignore */ }
  };
  return (
    <div className="shutdown-row">
      <div>
        <div className="shutdown-label">{label}</div>
        <div className="shutdown-hint">{hint}</div>
      </div>
      <button type="button" className={`copy-btn${copied ? " copy-btn--copied" : ""}`} onClick={onCopy}>
        {copied ? "Copied!" : "Copy"}
      </button>
    </div>
  );
}

export function StatusPanel({ pipeline, activityLog, onCancelAnalysis }: StatusPanelProps) {
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
      setStats(await fetchIndexStats());
    } catch { /* ignore */ }
  }, []);

  const loadAll = useCallback(async () => {
    try {
      const [h, s, c] = await Promise.all([fetchHealthDependencies(), fetchIndexStats(), fetchConfig()]);
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
          lines.push({ name: f.name, ok: true, text: `${r.chunks} sections added` });
        } catch (e) {
          lines.push({ name: f.name, ok: false, text: e instanceof Error ? e.message : String(e) });
        }
      }
      setIngestLines(lines);
      await refreshStats();
    } finally {
      setIngestBusy(false);
    }
  };

  const ollamaReachable = !!(health?.ollama_api_ok ?? health?.ollama_ok);
  const aiGreen = ollamaReachable && !!health?.models_present?.llm && !!health?.models_present?.fast_llm && !!health?.models_present?.embed;
  const aiAmber = ollamaReachable && !aiGreen;
  const aiRed = health != null && !ollamaReachable;
  const libGreen = !!health?.qdrant_ok && !!health?.collection_exists;
  const libRed = health != null && !libGreen;

  const maxChunks = Math.max(1, ...(stats?.pdfs.map((p) => p.chunks) ?? [1]));
  const ollamaKill = isWindows() ? "taskkill /IM ollama.exe /F" : "pkill ollama";

  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="brand-icon">
          <path d="M12 2L2 7l10 5 10-5-10-5z" />
          <path d="M2 17l10 5 10-5" />
          <path d="M2 12l10 5 10-5" />
        </svg>
        <div>
          <h2>LegalMind</h2>
          <p className="sidebar-tagline">AI-powered case intelligence</p>
        </div>
      </div>

      <section className="status-cards">
        {bootLoading ? (
          <>
            <div className="skeleton skeleton-line" />
            <div className="skeleton skeleton-line short" />
          </>
        ) : !serverReachable ? (
          <div className="status-card status-card--bad">
            <span className="status-dot status-dot--red" />
            <div>
              <strong>Server unreachable</strong>
              <p className="status-sub">{cfgErr || "Start the backend and refresh."}</p>
            </div>
          </div>
        ) : (
          <>
            <div className={`status-card${aiGreen ? " status-card--ok" : aiAmber ? " status-card--warn" : " status-card--bad"}`}>
              <span className={`status-dot${aiGreen ? " status-dot--green status-dot--pulse" : aiAmber ? " status-dot--amber" : " status-dot--red"}`} />
              <div>
                <strong>AI Engine</strong>
                <p className="status-sub">
                  {aiGreen && "Connected and ready"}
                  {aiAmber && "Running but models missing"}
                  {aiRed && "Not running — start Ollama"}
                </p>
              </div>
            </div>
            <div className={`status-card${libGreen ? " status-card--ok" : " status-card--bad"}`}>
              <span className={`status-dot${libGreen ? " status-dot--green status-dot--pulse" : " status-dot--red"}`} />
              <div>
                <strong>Case Library</strong>
                <p className="status-sub">
                  {libGreen ? `${stats?.pdf_count ?? 0} PDFs, ${stats?.total_chunks ?? 0} sections` : "Qdrant unreachable"}
                </p>
              </div>
            </div>
          </>
        )}
      </section>

      <PipelineTracker state={pipeline} log={activityLog} onCancel={onCancelAnalysis} />

      <details className="sidebar-section" open>
        <summary>Case Library</summary>
        {stats && (
          <div className="doc-summary">
            <span className="doc-stat"><strong>{stats.pdf_count}</strong> PDFs</span>
            <span className="doc-stat"><strong>{stats.total_chunks}</strong> sections</span>
          </div>
        )}
        <div className="doc-list">
          {stats?.pdfs.map((p) => (
            <div key={p.path} className={`doc-row${p.ok ? "" : " doc-row--bad"}`}>
              <div className="doc-meta">
                <div className="doc-name" title={p.display_name}>{p.display_name}</div>
                <div className="doc-bar-wrap">
                  <div className="doc-bar" style={{ width: `${(p.chunks / maxChunks) * 100}%` }} />
                </div>
              </div>
              <span className="doc-count">{p.ok ? p.chunks : "\u2014"}</span>
            </div>
          ))}
          {stats && stats.pdfs.length === 0 && <p className="hint">No PDFs indexed yet.</p>}
        </div>
      </details>

      <details className="sidebar-section" open>
        <summary>Add PDFs to Library</summary>
        <div
          className={`drop-zone${dragOver ? " drop-zone--active" : ""}`}
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
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
          <input type="file" accept="application/pdf" multiple id="pdf-input" className="drop-zone-input" onChange={(e) => setFiles(e.target.files)} />
          <label htmlFor="pdf-input" className="drop-zone-label">Drop PDFs here or click to browse</label>
        </div>
        <button type="button" className="btn-secondary ingest-btn" onClick={() => void onIngest()} disabled={!files?.length || ingestBusy}>
          {ingestBusy ? (<><span className="spinner" /> Adding...</>) : "Add to library"}
        </button>
        {ingestLines.length > 0 && (
          <ul className="ingest-results">
            {ingestLines.map((l) => (
              <li key={l.name} className={l.ok ? "ingest-ok" : "ingest-bad"}>
                {l.ok ? "\u2713" : "\u2717"} {l.name} — {l.text}
              </li>
            ))}
          </ul>
        )}
      </details>

      <details className="sidebar-section">
        <summary>System</summary>
        {cfg && (
          <div className="advanced-block">
            <div><span className="adv-k">Main model</span> <code>{cfg.llm_model}</code></div>
            <div><span className="adv-k">Fast model</span> <code>{cfg.fast_llm_model}</code></div>
            <div><span className="adv-k">Embeddings</span> <code>{cfg.embed_model}</code></div>
            <div><span className="adv-k">Vector DB</span> <code>{cfg.qdrant_url}</code></div>
          </div>
        )}
        <CopyRow label="Stop Docker" hint="From project folder:" command="docker compose down" />
        <CopyRow label="Stop AI" hint="Terminal:" command={ollamaKill} />
      </details>

      <p className="sidebar-foot">Everything runs locally. Nothing leaves your machine.</p>
    </aside>
  );
}

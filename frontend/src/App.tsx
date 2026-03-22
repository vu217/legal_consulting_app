import { useCallback, useEffect, useState } from "react";
import { analyzeCase, fetchConfig, ingestUpload } from "./api";
import type { AnalysisResult, PublicConfig } from "./types";
import { OutcomeBarChart } from "./components/OutcomeBarChart";
import { ProbCompareChart } from "./components/ProbCompareChart";
import { WinGauge } from "./components/WinGauge";
import "./App.css";

function OutcomeBadge({ outcome }: { outcome: string }) {
  const o = outcome.toLowerCase();
  if (["acquitted", "allowed", "upheld", "quashed"].some((w) => o.includes(w))) {
    return <span className="badge-win">{outcome}</span>;
  }
  if (["convicted", "dismissed", "sentenced", "remanded"].some((w) => o.includes(w))) {
    return <span className="badge-loss">{outcome}</span>;
  }
  return <span className="badge-unk">{outcome || "unknown"}</span>;
}

export default function App() {
  const [cfg, setCfg] = useState<PublicConfig | null>(null);
  const [cfgErr, setCfgErr] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [files, setFiles] = useState<FileList | null>(null);
  const [ingestBusy, setIngestBusy] = useState(false);
  const [ingestLog, setIngestLog] = useState<string[]>([]);

  useEffect(() => {
    fetchConfig()
      .then(setCfg)
      .catch((e: Error) => setCfgErr(e.message));
  }, []);

  const run = useCallback(async () => {
    const q = query.trim();
    if (!q) return;
    setLoading(true);
    setErr(null);
    try {
      const r = await analyzeCase(q);
      setResult(r);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [query]);

  const onIngest = async () => {
    if (!files?.length) return;
    setIngestBusy(true);
    setIngestLog([]);
    const lines: string[] = [];
    try {
      for (let i = 0; i < files.length; i++) {
        const f = files[i];
        try {
          const r = await ingestUpload(f);
          lines.push(`${f.name}: ${r.chunks} chunks`);
        } catch (e) {
          lines.push(`${f.name}: ${e instanceof Error ? e.message : String(e)}`);
        }
      }
      setIngestLog(lines);
    } finally {
      setIngestBusy(false);
    }
  };

  const similar = result?.precedent?.similar_cases ?? [];
  const statutesRaw = result?.statute?.statutes_raw ?? [];
  const stats = result?.winrate?.stats;
  const winProb = result?.win_probability ?? 50;

  return (
    <div className="layout">
      <aside className="sidebar">
        <h2>LegalMind</h2>
        <p style={{ fontSize: 13, marginTop: 0 }}>100% local · DeepSeek R1 · Qdrant</p>
        <hr style={{ borderColor: "var(--border-soft)", margin: "1rem 0" }} />
        <h3>Index PDFs</h3>
        <input
          type="file"
          accept="application/pdf"
          multiple
          onChange={(e) => setFiles(e.target.files)}
        />
        <button type="button" className="secondary" style={{ marginTop: 8 }} onClick={onIngest} disabled={!files?.length || ingestBusy}>
          {ingestBusy ? "Indexing…" : "Ingest selected PDFs"}
        </button>
        {ingestLog.length > 0 && (
          <div className="upload-list">
            {ingestLog.map((l, i) => (
              <div key={i}>{l}</div>
            ))}
          </div>
        )}
        <hr style={{ borderColor: "var(--border-soft)", margin: "1rem 0" }} />
        <h3>Model</h3>
        {cfgErr && <p style={{ color: "#f87171", fontSize: 12 }}>{cfgErr}</p>}
        {cfg && (
          <>
            <p style={{ fontSize: 12, margin: "0.25rem 0" }}>
              LLM: <code style={{ color: "var(--body)" }}>{cfg.llm_model}</code>
            </p>
            <p style={{ fontSize: 12, margin: "0.25rem 0" }}>
              Embeddings: <code style={{ color: "var(--body)" }}>{cfg.embed_model}</code>
            </p>
            <p style={{ fontSize: 12, margin: "0.25rem 0" }}>
              Vector DB: <code style={{ color: "var(--body)" }}>{cfg.qdrant_url}</code>
            </p>
          </>
        )}
        <hr style={{ borderColor: "var(--border-soft)", margin: "1rem 0" }} />
        <p style={{ fontSize: 11, opacity: 0.85 }}>All inference runs locally. No data leaves your machine.</p>
      </aside>

      <main className="main">
        <h1>Case Intelligence Dashboard</h1>
        <p className="sub">
          Describe your case below. The system runs specialist analysis and synthesises the results.
        </p>

        <textarea
          className="query"
          placeholder='e.g. My client is accused of cheating under Section 420 IPC...'
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <div className="row-actions">
          <button type="button" className="primary" onClick={run} disabled={loading || !query.trim()}>
            {loading ? "Running…" : "Run analysis"}
          </button>
          <span className="hint">Requires Ollama and indexed PDFs for best results.</span>
        </div>
        {err && <div className="err">{err}</div>}

        {result && (
          <>
            <hr style={{ borderColor: "var(--border-soft)", margin: "1.5rem 0" }} />
            <div className="metrics">
              <div className="metric">
                <label>Win probability</label>
                <div className="val">{winProb}%</div>
              </div>
              <div className="metric">
                <label>Similar cases found</label>
                <div className="val">{similar.length}</div>
              </div>
              <div className="metric">
                <label>Statutes identified</label>
                <div className="val">{statutesRaw.length}</div>
              </div>
              <div className="metric">
                <label>Historical base rate</label>
                <div className="val">{stats?.base_rate_pct ?? "—"}%</div>
              </div>
            </div>

            <div className="grid-2">
              <div className="card">
                <div className="card-title">Win probability gauge</div>
                <WinGauge value={winProb} />
                <p className="hint" style={{ textAlign: "center", marginTop: 4 }}>
                  Assessment:{" "}
                  {winProb >= 60 ? "Favourable outlook" : winProb >= 40 ? "Uncertain" : "Challenging case"}
                </p>
              </div>
              <div className="card">
                <div className="card-title">Outcome distribution in similar cases</div>
                {similar.length ? (
                  <OutcomeBarChart cases={similar} />
                ) : (
                  <p className="hint">No similar cases retrieved yet. Index some PDFs first.</p>
                )}
              </div>
            </div>

            <div className="card">
              <div className="card-title">Executive summary</div>
              <div className="card-body">{result.summary}</div>
            </div>

            <h2 style={{ fontSize: "1.1rem", fontWeight: 500, marginTop: "1.5rem" }}>Similar case references</h2>
            {similar.length ? (
              <div className="case-grid">
                {similar.slice(0, 3).map((c) => (
                  <div key={c.rank} className="card">
                    <div className="card-title">Case {c.rank}</div>
                    <div className="card-body">
                      <strong style={{ color: "var(--accent-pill)" }}>{c.case_name || "Unknown case"}</strong>
                      <br />
                      <small style={{ color: "var(--muted)" }}>
                        {c.court} · {c.year}
                      </small>
                      <br />
                      <br />
                      <OutcomeBadge outcome={c.outcome} />
                      <br />
                      <br />
                      <small style={{ color: "var(--muted)" }}>{(c.chunk || "").slice(0, 250)}…</small>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="hint">No similar cases found. Upload and index PDFs to populate the knowledge base.</p>
            )}

            <div className="grid-2" style={{ marginTop: "1.25rem" }}>
              <div>
                <h2 style={{ fontSize: "1.1rem", fontWeight: 500 }}>Statute map</h2>
                <div className="card">
                  <div className="card-title">Applicable laws</div>
                  {statutesRaw.length > 0 && (
                    <div style={{ marginBottom: "0.8rem" }}>
                      {statutesRaw.slice(0, 10).map((s, i) => (
                        <span key={i} className="case-pill">
                          {s.slice(0, 60)}
                        </span>
                      ))}
                    </div>
                  )}
                  <div className="card-body">{result.statute?.analysis}</div>
                </div>
              </div>
              <div>
                <h2 style={{ fontSize: "1.1rem", fontWeight: 500 }}>Evidence to seek</h2>
                <div className="card">
                  <div className="card-title">Recommended evidence</div>
                  <div className="card-body">{result.evidence?.analysis}</div>
                </div>
              </div>
            </div>

            <h2 style={{ fontSize: "1.1rem", fontWeight: 500 }}>Case framing strategies</h2>
            <div className="card">
              <div className="card-title">Recommended approaches</div>
              <div className="card-body">{result.strategy?.analysis}</div>
            </div>

            <h2 style={{ fontSize: "1.1rem", fontWeight: 500 }}>Win-rate analysis</h2>
            <div className="grid-2">
              <div className="card">
                <div className="card-title">Detailed probability breakdown</div>
                <div className="card-body">{result.winrate?.analysis}</div>
              </div>
              <div className="card">
                <div className="card-title">Probability components</div>
                <ProbCompareChart
                  baseRate={result.winrate?.base_rate ?? 50}
                  llmEst={result.winrate?.llm_estimate ?? 50}
                  blended={winProb}
                />
              </div>
            </div>
          </>
        )}

        {!result && !loading && (
          <div className="empty-state">
            <div className="icon">⚖</div>
            <div style={{ fontSize: 18, fontWeight: 500, color: "var(--body)", marginBottom: 8 }}>No case loaded yet</div>
            <div style={{ fontSize: 14 }}>
              Upload PDFs in the sidebar to build your knowledge base,
              <br />
              then describe your case above to run the analysis.
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

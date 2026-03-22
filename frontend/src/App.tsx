import { useCallback, useRef, useState } from "react";
import { analyzeCaseStream } from "./api";
import type { AnalysisUiState } from "./components/StatusPanel";
import { StatusPanel } from "./components/StatusPanel";
import { OutcomeBarChart } from "./components/OutcomeBarChart";
import { ProbCompareChart } from "./components/ProbCompareChart";
import { WinGauge } from "./components/WinGauge";
import { PHASE_STATUS, formatTimeNote, phaseToStep } from "./statusCopy";
import type { AnalysisResult } from "./types";
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

const initialAnalysis: AnalysisUiState = {
  running: false,
  pct: 0,
  completedSteps: 0,
  pulsingStep: null,
  statusText: "",
  timeNote: "",
};

export default function App() {
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [analysisUi, setAnalysisUi] = useState<AnalysisUiState>(initialAnalysis);
  const [err, setErr] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const t0Ref = useRef(0);

  const onCancelAnalysis = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const run = useCallback(async () => {
    const q = query.trim();
    if (!q) return;
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    t0Ref.current = Date.now();
    setErr(null);
    setAnalysisUi({
      running: true,
      pct: 5,
      completedSteps: 0,
      pulsingStep: 0,
      statusText: PHASE_STATUS.retrieve_start,
      timeNote: formatTimeNote(0),
    });

    let outcome;
    try {
      outcome = await analyzeCaseStream(
      q,
      (msg) => {
        if (msg.type !== "progress") return;
        const phase = msg.phase;
        const elapsed = (Date.now() - t0Ref.current) / 1000;
        if (phase === "phase_error") {
          const fp = String(msg.failed_phase || "");
          const detail = String(msg.detail || "").slice(0, 140);
          const map: Record<string, string> = {
            retrieve: `Finding cases failed: ${detail}`,
            fast_llm: `Organizing the answer failed: ${detail}`,
            summary_llm: `Writing the summary failed: ${detail}`,
          };
          setAnalysisUi((prev) => ({
            ...prev,
            statusText: map[fp] || `Something went wrong: ${detail}`,
          }));
          return;
        }
        const { pct } = phaseToStep(phase);
        let completedSteps = 0;
        let pulsingStep: number | null = 0;
        switch (phase) {
          case "retrieve_start":
            completedSteps = 0;
            pulsingStep = 0;
            break;
          case "retrieve_done":
            completedSteps = 1;
            pulsingStep = 1;
            break;
          case "fast_llm_start":
            completedSteps = 1;
            pulsingStep = 1;
            break;
          case "fast_llm_done":
            completedSteps = 2;
            pulsingStep = 2;
            break;
          case "summary_llm_start":
            completedSteps = 2;
            pulsingStep = 2;
            break;
          case "summary_llm_done":
            completedSteps = 3;
            pulsingStep = null;
            break;
          default:
            return;
        }
        setAnalysisUi((prev) => ({
          ...prev,
          pct: Math.max(prev.pct, pct),
          completedSteps: Math.max(prev.completedSteps, completedSteps),
          pulsingStep,
          statusText: PHASE_STATUS[phase] ?? prev.statusText,
          timeNote: formatTimeNote(elapsed),
        }));
      },
      ac.signal,
    );
    } catch (e) {
      setAnalysisUi((prev) => ({ ...prev, running: false, pulsingStep: null }));
      setErr(e instanceof Error ? e.message : String(e));
      return;
    }

    setAnalysisUi((prev) => ({
      ...prev,
      running: false,
      pulsingStep: null,
      pct: outcome.status === "complete" ? 100 : prev.pct,
    }));

    if (outcome.status === "complete") {
      setResult(outcome.result);
    } else if (outcome.status === "cancelled") {
      setErr(null);
    } else {
      setErr(outcome.message);
    }
  }, [query]);

  const similar = result?.precedent?.similar_cases ?? [];
  const statutesRaw = result?.statute?.statutes_raw ?? [];
  const stats = result?.winrate?.stats;
  const winProb = result?.win_probability ?? 50;

  return (
    <div className="layout">
      <StatusPanel analysis={analysisUi} onCancelAnalysis={onCancelAnalysis} />

      <main className="main">
        <h1>Case Intelligence Dashboard</h1>
        <p className="sub">Describe your case below. The system runs specialist analysis and synthesises the results.</p>

        <textarea
          className="query"
          placeholder='e.g. My client is accused of cheating under Section 420 IPC...'
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <div className="row-actions">
          <button type="button" className="primary" onClick={() => void run()} disabled={analysisUi.running || !query.trim()}>
            {analysisUi.running ? "Running…" : "Run analysis"}
          </button>
          <span className="hint">Works best with PDFs added in the sidebar and your local AI running.</span>
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

        {!result && !analysisUi.running && (
          <div className="empty-state">
            <div className="icon">⚖</div>
            <div style={{ fontSize: 18, fontWeight: 500, color: "var(--body)", marginBottom: 8 }}>No case loaded yet</div>
            <div style={{ fontSize: 14 }}>
              Add PDFs in the sidebar to build your knowledge base,
              <br />
              then describe your case above to run the analysis.
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

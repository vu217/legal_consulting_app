import { useCallback, useRef, useState } from "react";
import { analyzeCaseStream } from "./api";
import { CaseForm } from "./components/CaseForm";
import { StatusPanel } from "./components/StatusPanel";
import type { PipelineState } from "./components/PipelineTracker";
import { initialPipelineState } from "./components/PipelineTracker";
import { OutcomeBarChart } from "./components/OutcomeBarChart";
import { ProbCompareChart } from "./components/ProbCompareChart";
import { WinGauge } from "./components/WinGauge";
import { PHASE_STATUS, phaseToStep, phaseToStepKey, formatTimeNote } from "./statusCopy";
import type { ActivityLogEntry, AnalysisResult, CaseFormData } from "./types";
import "./App.css";

function OutcomeBadge({ outcome }: { outcome: string }) {
  const o = outcome.toLowerCase();
  if (["acquitted", "allowed", "upheld", "quashed"].some((w) => o.includes(w)))
    return <span className="badge badge--win">{outcome}</span>;
  if (["convicted", "dismissed", "sentenced", "remanded"].some((w) => o.includes(w)))
    return <span className="badge badge--loss">{outcome}</span>;
  return <span className="badge badge--unk">{outcome || "unknown"}</span>;
}

export default function App() {
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [pipeline, setPipeline] = useState<PipelineState>(initialPipelineState);
  const [activityLog, setActivityLog] = useState<ActivityLogEntry[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const t0Ref = useRef(0);

  const onCancel = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const addLogEntry = useCallback((phase: string, data: Record<string, unknown>) => {
    setActivityLog((prev) => [
      ...prev,
      {
        timestamp: Date.now(),
        phase,
        task: data.task as string | undefined,
        model: data.model as string | undefined,
        elapsed_ms: data.elapsed_ms as number | undefined,
        doc_count: data.doc_count as number | undefined,
        error: data.error as string | undefined,
        detail: data.detail as string | undefined,
      },
    ]);
  }, []);

  const handleSubmit = useCallback(
    async (formData: CaseFormData) => {
      abortRef.current?.abort();
      const ac = new AbortController();
      abortRef.current = ac;
      t0Ref.current = Date.now();
      setErr(null);
      setResult(null);
      setActivityLog([]);
      setPipeline({
        running: true,
        pct: 5,
        completedSteps: new Set(),
        activeStep: "retrieve",
        statusText: PHASE_STATUS.retrieve_start,
        timeNote: formatTimeNote(0),
        currentModel: null,
        currentTask: null,
      });

      let outcome;
      try {
        outcome = await analyzeCaseStream(
          formData,
          (msg) => {
            if (msg.type !== "progress") return;
            const phase = msg.phase;
            const elapsed = (Date.now() - t0Ref.current) / 1000;

            addLogEntry(phase, msg as Record<string, unknown>);

            if (phase === "phase_error") {
              const detail = String(msg.detail || "").slice(0, 200);
              setPipeline((prev) => ({
                ...prev,
                statusText: `Error: ${detail}`,
              }));
              return;
            }

            const { pct } = phaseToStep(phase);
            const stepKey = phaseToStepKey(phase);

            setPipeline((prev) => {
              const completed = new Set(prev.completedSteps);

              if (phase === "retrieve_done") completed.add("retrieve");
              if (phase === "fast_llm_done") completed.add("analyze");
              if (phase === "summary_llm_done") {
                completed.add("summary");
                completed.add("complete");
              }

              return {
                ...prev,
                pct: Math.max(prev.pct, pct),
                completedSteps: completed,
                activeStep: completed.has("complete") ? null : stepKey,
                statusText: PHASE_STATUS[phase] ?? prev.statusText,
                timeNote: formatTimeNote(elapsed),
                currentModel: (msg.model as string) ?? prev.currentModel,
                currentTask: (msg.task as string) ?? prev.currentTask,
              };
            });
          },
          ac.signal,
        );
      } catch (e) {
        setPipeline((prev) => ({ ...prev, running: false, activeStep: null }));
        setErr(e instanceof Error ? e.message : String(e));
        return;
      }

      setPipeline((prev) => ({
        ...prev,
        running: false,
        activeStep: null,
        pct: outcome.status === "complete" ? 100 : prev.pct,
        completedSteps: outcome.status === "complete"
          ? new Set(["retrieve", "analyze", "summary", "complete"])
          : prev.completedSteps,
      }));

      if (outcome.status === "complete") {
        setResult(outcome.result);
      } else if (outcome.status === "cancelled") {
        setErr(null);
      } else {
        setErr(outcome.message);
      }
    },
    [addLogEntry],
  );

  const similar = result?.precedent?.similar_cases ?? [];
  const statutesRaw = result?.statute?.statutes_raw ?? [];
  const judgments = result?.judgments ?? [];
  const stats = result?.winrate?.stats;
  const winProb = result?.win_probability ?? 50;

  return (
    <div className="layout">
      <StatusPanel
        pipeline={pipeline}
        activityLog={activityLog}
        onCancelAnalysis={onCancel}
      />

      <main className="main">
        <header className="page-header">
          <h1>Case Intelligence Dashboard</h1>
          <p className="page-sub">
            Enter your case details below. The AI analyzes precedents, statutes,
            evidence patterns, and strategies from your case library.
          </p>
        </header>

        <section className="form-card">
          <CaseForm onSubmit={handleSubmit} disabled={pipeline.running} />
        </section>

        {err && <div className="error-banner">{err}</div>}

        {result && (
          <div className="results">
            {/* Metrics row */}
            <div className="metrics">
              <div className="metric-card">
                <div className="metric-value">{winProb}%</div>
                <div className="metric-label">Win Probability</div>
              </div>
              <div className="metric-card">
                <div className="metric-value">{similar.length}</div>
                <div className="metric-label">Similar Cases</div>
              </div>
              <div className="metric-card">
                <div className="metric-value">{statutesRaw.length}</div>
                <div className="metric-label">Statutes Identified</div>
              </div>
              <div className="metric-card">
                <div className="metric-value">{stats?.base_rate_pct ?? "\u2014"}%</div>
                <div className="metric-label">Historical Base Rate</div>
              </div>
            </div>

            {/* Charts row */}
            <div className="grid-2">
              <div className="card">
                <div className="card-header">Win Probability</div>
                <WinGauge value={winProb} />
                <p className="card-footnote">
                  {winProb >= 60 ? "Favourable outlook" : winProb >= 40 ? "Uncertain" : "Challenging case"}
                </p>
              </div>
              <div className="card">
                <div className="card-header">Outcome Distribution</div>
                {similar.length ? (
                  <OutcomeBarChart cases={similar} />
                ) : (
                  <p className="card-empty">No similar cases found yet.</p>
                )}
              </div>
            </div>

            {/* Executive Summary */}
            <div className="card card--highlight">
              <div className="card-header">Executive Summary</div>
              <div className="card-body summary-text">{result.summary}</div>
            </div>

            {/* Judgments Passed */}
            {judgments.length > 0 && (
              <div className="card">
                <div className="card-header">Judgments from Similar Cases</div>
                <div className="judgments-table-wrap">
                  <table className="judgments-table">
                    <thead>
                      <tr>
                        <th>Case</th>
                        <th>Court</th>
                        <th>Year</th>
                        <th>Outcome</th>
                        <th>Key Statutes</th>
                      </tr>
                    </thead>
                    <tbody>
                      {judgments.map((j, i) => (
                        <tr key={i}>
                          <td className="jt-case">{j.case_name}</td>
                          <td>{j.court}</td>
                          <td>{j.year}</td>
                          <td>
                            <OutcomeBadge outcome={j.outcome} />
                            {j.outcome_detail && (
                              <div className="jt-detail">{j.outcome_detail}</div>
                            )}
                          </td>
                          <td className="jt-statutes">{j.statutes || "\u2014"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Similar Cases */}
            <div className="card">
              <div className="card-header">Similar Case References</div>
              {similar.length ? (
                <div className="case-grid">
                  {similar.slice(0, 5).map((c) => (
                    <div key={c.rank} className="case-card">
                      <div className="case-card-head">
                        <span className="case-rank">#{c.rank}</span>
                        <OutcomeBadge outcome={c.outcome} />
                      </div>
                      <div className="case-card-name">{c.case_name || "Unknown case"}</div>
                      <div className="case-card-meta">
                        {c.court} &middot; {c.year}
                        {c.court_type !== "other" && (
                          <span className="case-type-tag">{c.court_type.replace("_", " ")}</span>
                        )}
                      </div>
                      <div className="case-card-snippet">{(c.chunk || "").slice(0, 200)}...</div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="card-empty">Upload case PDFs to populate the knowledge base.</p>
              )}
            </div>

            {/* Two-column: Statutes & Evidence */}
            <div className="grid-2">
              <div className="card">
                <div className="card-header">Applicable Statutes</div>
                {statutesRaw.length > 0 && (
                  <div className="pills">
                    {statutesRaw.slice(0, 12).map((s, i) => (
                      <span key={i} className="pill">{s.slice(0, 60)}</span>
                    ))}
                  </div>
                )}
                <div className="card-body">{result.statute?.analysis}</div>
              </div>
              <div className="card">
                <div className="card-header">Evidence Required</div>
                <div className="card-body">{result.evidence?.analysis}</div>
              </div>
            </div>

            {/* Strategy */}
            <div className="card">
              <div className="card-header">Recommended Strategies</div>
              <div className="card-body">{result.strategy?.analysis}</div>
            </div>

            {/* Win Rate breakdown */}
            <div className="grid-2">
              <div className="card">
                <div className="card-header">Win Rate Analysis</div>
                <div className="card-body">{result.winrate?.analysis}</div>
              </div>
              <div className="card">
                <div className="card-header">Probability Breakdown</div>
                <ProbCompareChart
                  baseRate={result.winrate?.base_rate ?? 50}
                  llmEst={result.winrate?.llm_estimate ?? 50}
                  blended={winProb}
                />
              </div>
            </div>
          </div>
        )}

        {!result && !pipeline.running && (
          <div className="empty-state">
            <div className="empty-icon">
              <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="10" />
                <path d="M8 14s1.5 2 4 2 4-2 4-2" />
                <line x1="9" y1="9" x2="9.01" y2="9" />
                <line x1="15" y1="9" x2="15.01" y2="9" />
              </svg>
            </div>
            <h2>Ready to Analyze</h2>
            <p>
              Add case PDFs to the library in the sidebar, then describe your
              case above to get AI-powered legal intelligence.
            </p>
            <div className="empty-steps">
              <div className="empty-step">
                <span className="empty-step-num">1</span>
                <span>Upload case law PDFs</span>
              </div>
              <div className="empty-step">
                <span className="empty-step-num">2</span>
                <span>Describe your case</span>
              </div>
              <div className="empty-step">
                <span className="empty-step-num">3</span>
                <span>Get AI analysis</span>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

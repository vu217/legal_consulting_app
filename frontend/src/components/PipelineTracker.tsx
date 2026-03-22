import type { ActivityLogEntry } from "../types";
import { PIPELINE_STEPS } from "../statusCopy";

export interface PipelineState {
  running: boolean;
  pct: number;
  completedSteps: Set<string>;
  activeStep: string | null;
  statusText: string;
  timeNote: string;
  currentModel: string | null;
  currentTask: string | null;
}

interface PipelineTrackerProps {
  state: PipelineState;
  log: ActivityLogEntry[];
  onCancel: () => void;
}

export const initialPipelineState: PipelineState = {
  running: false,
  pct: 0,
  completedSteps: new Set(),
  activeStep: null,
  statusText: "",
  timeNote: "",
  currentModel: null,
  currentTask: null,
};

function StepIcon({ done, active }: { done: boolean; active: boolean }) {
  if (done)
    return (
      <div className="step-icon step-icon--done">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
          <polyline points="20,6 9,17 4,12" />
        </svg>
      </div>
    );
  if (active)
    return (
      <div className="step-icon step-icon--active">
        <div className="step-spinner" />
      </div>
    );
  return <div className="step-icon step-icon--pending" />;
}

export function PipelineTracker({ state, log, onCancel }: PipelineTrackerProps) {
  if (!state.running && log.length === 0) return null;

  const lastEntries = log.slice(-5);

  return (
    <div className={`pipeline-tracker${state.running ? " pipeline-tracker--active" : ""}`}>
      <div className="pipeline-header">
        <span className="pipeline-title">Analysis Pipeline</span>
        {state.running && (
          <span className="pipeline-pct">{Math.round(state.pct)}%</span>
        )}
      </div>

      <div className="pipeline-bar">
        <div
          className="pipeline-fill"
          style={{ width: `${state.pct}%`, transition: "width 0.5s ease" }}
        />
      </div>

      <div className="pipeline-steps">
        {PIPELINE_STEPS.map((step) => {
          const done = state.completedSteps.has(step.key);
          const active = state.activeStep === step.key;
          return (
            <div key={step.key} className={`pipeline-step${active ? " pipeline-step--active" : ""}${done ? " pipeline-step--done" : ""}`}>
              <StepIcon done={done} active={active} />
              <div className="step-content">
                <span className="step-label">{step.label}</span>
                {active && state.currentModel && (
                  <span className="step-model">Model: {state.currentModel}</span>
                )}
                {active && state.currentTask && (
                  <span className="step-task">{state.currentTask}</span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {state.running && (
        <div className="pipeline-footer">
          <span className="pipeline-status">{state.statusText}</span>
          <span className="pipeline-time">{state.timeNote}</span>
        </div>
      )}

      {lastEntries.length > 0 && (
        <details className="pipeline-log">
          <summary>Activity log ({log.length} events)</summary>
          <div className="log-entries">
            {log.map((entry, i) => (
              <div key={i} className="log-entry">
                <span className="log-time">
                  {new Date(entry.timestamp).toLocaleTimeString()}
                </span>
                <span className={`log-phase log-phase--${entry.error ? "error" : "ok"}`}>
                  {entry.phase}
                </span>
                {entry.task && <span className="log-task">{entry.task}</span>}
                {entry.model && <span className="log-model">{entry.model}</span>}
                {entry.elapsed_ms != null && (
                  <span className="log-elapsed">{(entry.elapsed_ms / 1000).toFixed(1)}s</span>
                )}
                {entry.doc_count != null && (
                  <span className="log-docs">{entry.doc_count} docs</span>
                )}
                {entry.error && <span className="log-error">{entry.error}</span>}
              </div>
            ))}
          </div>
        </details>
      )}

      {state.running && (
        <button type="button" className="pipeline-cancel" onClick={onCancel}>
          Cancel analysis
        </button>
      )}
    </div>
  );
}

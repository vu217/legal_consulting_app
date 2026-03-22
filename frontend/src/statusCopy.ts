/** User-facing strings for progress phases. */

export const PHASE_STATUS: Record<string, string> = {
  retrieve_start: "Searching the case library for similar cases...",
  retrieve_done: "Found related cases. Preparing analysis...",
  fast_llm_start: "AI is analyzing precedents, evidence, and strategy...",
  fast_llm_done: "Analysis complete. Generating summary...",
  task_start: "Running analysis task...",
  task_done: "Task completed.",
  task_retry: "Retrying task...",
  task_error: "A task encountered an error.",
  summary_llm_start: "AI is writing the executive summary...",
  summary_llm_done: "Summary complete. Finalizing...",
  phase_error: "Something went wrong in this step.",
};

export const PHASE_ESTIMATE_SEC = [12, 65, 65] as const;

export interface StepInfo {
  active: number;
  completed: number;
  pct: number;
}

export function phaseToStep(phase: string): StepInfo {
  switch (phase) {
    case "retrieve_start":
      return { active: 0, completed: 0, pct: 8 };
    case "retrieve_done":
      return { active: 1, completed: 1, pct: 25 };
    case "fast_llm_start":
      return { active: 1, completed: 1, pct: 30 };
    case "task_start":
      return { active: 1, completed: 1, pct: 35 };
    case "task_done":
      return { active: 1, completed: 1, pct: 50 };
    case "fast_llm_done":
      return { active: 2, completed: 2, pct: 65 };
    case "summary_llm_start":
      return { active: 2, completed: 2, pct: 70 };
    case "summary_llm_done":
      return { active: 3, completed: 3, pct: 95 };
    default:
      return { active: 0, completed: 0, pct: 5 };
  }
}

export const PIPELINE_STEPS = [
  { key: "retrieve", label: "Search case library" },
  { key: "analyze", label: "Analyze case dimensions" },
  { key: "summary", label: "Generate executive summary" },
  { key: "complete", label: "Finalize results" },
] as const;

export function phaseToStepKey(phase: string): string {
  if (phase.startsWith("retrieve")) return "retrieve";
  if (phase.startsWith("fast_llm") || phase.startsWith("task_")) return "analyze";
  if (phase.startsWith("summary")) return "summary";
  return "retrieve";
}

export function formatTimeNote(elapsedSec: number): string {
  const totalEst = PHASE_ESTIMATE_SEC[0] + PHASE_ESTIMATE_SEC[1] + PHASE_ESTIMATE_SEC[2];
  const remaining = Math.max(0, Math.round(totalEst - elapsedSec));
  if (elapsedSec > totalEst + 30) {
    return "Still working — this can take a few minutes on slower machines.";
  }
  if (remaining <= 0) return "Almost done...";
  if (remaining < 60) return `~${remaining}s remaining`;
  const m = Math.ceil(remaining / 60);
  return `~${m} min${m > 1 ? "s" : ""} remaining`;
}

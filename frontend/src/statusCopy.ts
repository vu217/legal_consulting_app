/** User-facing strings for progress phases (non-technical copy). */

export const PHASE_STATUS: Record<string, string> = {
  retrieve_start: "Finding similar cases in your files…",
  retrieve_done: "Found related material. Organizing next…",
  fast_llm_start: "The AI is reading and organizing the answer…",
  fast_llm_done: "Almost there — preparing your summary…",
  summary_llm_start: "The AI is writing your summary…",
  summary_llm_done: "Finishing up…",
  phase_error: "Something went wrong in this step.",
};

/** Rough seconds per phase for time hints (retrieve, fast LLM, summary). */
export const PHASE_ESTIMATE_SEC = [12, 65, 65] as const;

export function phaseToStep(phase: string): { active: number; completed: number; pct: number } {
  switch (phase) {
    case "retrieve_start":
      return { active: 0, completed: 0, pct: 8 };
    case "retrieve_done":
      return { active: 1, completed: 1, pct: 33 };
    case "fast_llm_start":
      return { active: 1, completed: 1, pct: 38 };
    case "fast_llm_done":
      return { active: 2, completed: 2, pct: 66 };
    case "summary_llm_start":
      return { active: 2, completed: 2, pct: 72 };
    case "summary_llm_done":
      return { active: 2, completed: 3, pct: 95 };
    default:
      return { active: 0, completed: 0, pct: 5 };
  }
}

export function formatTimeNote(elapsedSec: number): string {
  const totalEst = PHASE_ESTIMATE_SEC[0] + PHASE_ESTIMATE_SEC[1] + PHASE_ESTIMATE_SEC[2];
  const remaining = Math.max(0, Math.round(totalEst - elapsedSec));
  if (elapsedSec > totalEst + 30) {
    return "Still working — this can take a few minutes on slower machines.";
  }
  if (remaining <= 0) {
    return "Almost done…";
  }
  if (remaining < 60) {
    return `About ${remaining} seconds remaining`;
  }
  const m = Math.ceil(remaining / 60);
  return `About ${m} minute${m > 1 ? "s" : ""} remaining`;
}

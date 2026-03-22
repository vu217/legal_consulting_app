export interface SimilarCase {
  rank: number;
  case_name: string;
  court: string;
  court_type: string;
  year: string;
  case_type: string;
  outcome: string;
  outcome_detail: string;
  parties: string;
  statutes: string;
  chunk: string;
  source: string;
}

export interface Judgment {
  case_name: string;
  court: string;
  year: string;
  outcome: string;
  outcome_detail: string;
  statutes: string;
}

export interface AnalysisResult {
  query: string;
  win_probability: number;
  summary: string;
  precedent: {
    agent: string;
    similar_cases: SimilarCase[];
    analysis: string;
  };
  evidence: { agent: string; analysis: string };
  statute: { agent: string; statutes_raw: string[]; analysis: string };
  strategy: { agent: string; analysis: string };
  winrate: {
    agent: string;
    win_probability: number;
    base_rate: number;
    llm_estimate: number;
    stats: { wins: number; losses: number; unknowns: number; base_rate_pct: number };
    analysis: string;
  };
  judgments: Judgment[];
}

export interface CaseFormData {
  query: string;
  court_type: string | null;
  case_type: string | null;
  case_context: string | null;
  desired_outcome: string | null;
  uploaded_file_ids: string[];
}

export interface PublicConfig {
  qdrant_url: string;
  collection: string;
  llm_model: string;
  fast_llm_model: string;
  embed_model: string;
}

export interface HealthDeps {
  qdrant_url: string;
  collection: string;
  qdrant_ok: boolean;
  collection_exists: boolean;
  qdrant_error?: string;
  ollama_ok: boolean;
  ollama_api_ok?: boolean;
  ollama_error?: string;
  ollama_models: string[];
  expected_models: { llm: string; fast_llm: string; embed: string };
  models_present: { llm: boolean; fast_llm: boolean; embed: boolean };
}

export interface IndexPdfRow {
  path: string;
  display_name: string;
  chunks: number;
  ok: boolean;
  last_error: string | null;
}

export interface IndexStats {
  pdf_count: number;
  total_chunks: number;
  pdfs: IndexPdfRow[];
  qdrant_vector_count: number | null;
  qdrant_error?: string;
}

export interface CaseUploadResult {
  filename: string;
  file_id?: string;
  chunks?: number;
  status: string;
  detail?: string;
}

export interface ActivityLogEntry {
  timestamp: number;
  phase: string;
  task?: string;
  model?: string;
  detail?: string;
  elapsed_ms?: number;
  doc_count?: number;
  error?: string;
}

export type StreamServerMessage =
  | ({ type: "progress"; phase: string } & Record<string, unknown>)
  | { type: "result"; payload: AnalysisResult }
  | { type: "error"; detail: string; code?: string };

export type AnalysisStreamOutcome =
  | { status: "complete"; result: AnalysisResult }
  | { status: "cancelled" }
  | { status: "error"; message: string };

export const COURT_TYPES = [
  { value: "", label: "Any court" },
  { value: "supreme_court", label: "Supreme Court" },
  { value: "high_court", label: "High Court" },
  { value: "district_court", label: "District Court" },
  { value: "sessions_court", label: "Sessions Court" },
  { value: "tribunal", label: "Tribunal" },
  { value: "consumer_forum", label: "Consumer Forum" },
  { value: "family_court", label: "Family Court" },
  { value: "other", label: "Other" },
] as const;

export const CASE_TYPES = [
  { value: "", label: "Any type" },
  { value: "criminal", label: "Criminal" },
  { value: "civil", label: "Civil" },
  { value: "constitutional", label: "Constitutional" },
  { value: "family", label: "Family" },
  { value: "commercial", label: "Commercial" },
  { value: "tax", label: "Tax" },
  { value: "labor", label: "Labor" },
  { value: "other", label: "Other" },
] as const;

export const DESIRED_OUTCOMES = [
  { value: "", label: "No preference" },
  { value: "acquittal", label: "Acquittal" },
  { value: "conviction", label: "Conviction" },
  { value: "compensation", label: "Compensation" },
  { value: "injunction", label: "Injunction" },
  { value: "bail", label: "Bail" },
  { value: "quashing", label: "Quashing of charges" },
  { value: "divorce", label: "Divorce decree" },
  { value: "custody", label: "Custody" },
  { value: "other", label: "Other" },
] as const;

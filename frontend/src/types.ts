export interface SimilarCase {
  rank: number;
  case_name: string;
  court: string;
  year: string;
  outcome: string;
  parties: string;
  statutes: string;
  chunk: string;
  source: string;
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

export type StreamServerMessage =
  | ({ type: "progress"; phase: string } & Record<string, unknown>)
  | { type: "result"; payload: AnalysisResult }
  | { type: "error"; detail: string; code?: string };

export type AnalysisStreamOutcome =
  | { status: "complete"; result: AnalysisResult }
  | { status: "cancelled" }
  | { status: "error"; message: string };

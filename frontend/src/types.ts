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

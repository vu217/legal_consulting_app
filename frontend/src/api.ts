import type { AnalysisResult, PublicConfig } from "./types";

const API_BASE = (import.meta.env.VITE_API_BASE || "http://localhost:8000/api").replace(/\/$/, "");

async function handle(res: Response): Promise<unknown> {
  const text = await res.text();
  if (!res.ok) {
    let detail = text;
    try {
      const j = JSON.parse(text) as { detail?: string | Array<{ msg?: string }> };
      if (j.detail) {
        detail = Array.isArray(j.detail)
          ? j.detail.map((x) => x.msg || JSON.stringify(x)).join("; ")
          : String(j.detail);
      }
    } catch {
      /* keep text */
    }
    throw new Error(detail || res.statusText);
  }
  return text ? JSON.parse(text) : {};
}

export async function fetchConfig(): Promise<PublicConfig> {
  const res = await fetch(`${API_BASE}/config`);
  return handle(res) as Promise<PublicConfig>;
}

export async function analyzeCase(query: string): Promise<AnalysisResult> {
  const res = await fetch(`${API_BASE}/analysis`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
  });
  return handle(res) as Promise<AnalysisResult>;
}

export async function ingestSync(): Promise<unknown> {
  const res = await fetch(`${API_BASE}/ingest/sync`, { method: "POST" });
  return handle(res);
}

export async function ingestUpload(file: File): Promise<{ file: string; chunks: number; status: string }> {
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch(`${API_BASE}/ingest/upload`, {
    method: "POST",
    body: fd,
  });
  return handle(res) as Promise<{ file: string; chunks: number; status: string }>;
}

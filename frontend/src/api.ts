import type { AnalysisResult, PublicConfig } from "./types";

const API_BASE = (import.meta.env.VITE_API_BASE || "http://localhost:8000/api").replace(/\/$/, "");

async function handle(res: Response, op: string): Promise<unknown> {
  const text = await res.text();
  // #region agent log
  fetch("http://127.0.0.1:7247/ingest/372c8d01-8027-4cb7-8dd8-e127597ea1d9", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Debug-Session-Id": "bfe8eb" },
    body: JSON.stringify({
      sessionId: "bfe8eb",
      runId: "pre-fix",
      hypothesisId: "H4",
      location: "api.ts:handle",
      message: res.ok ? "response_ok" : "response_error",
      data: { op, status: res.status, ok: res.ok, body_len: text.length },
      timestamp: Date.now(),
    }),
  }).catch(() => {});
  // #endregion
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
  try {
    const res = await fetch(`${API_BASE}/config`);
    return handle(res, "/config") as Promise<PublicConfig>;
  } catch (e) {
    // #region agent log
    fetch("http://127.0.0.1:7247/ingest/372c8d01-8027-4cb7-8dd8-e127597ea1d9", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Debug-Session-Id": "bfe8eb" },
      body: JSON.stringify({
        sessionId: "bfe8eb",
        runId: "pre-fix",
        hypothesisId: "H4",
        location: "api.ts:fetchConfig",
        message: "network_error",
        data: { op: "/config", err: e instanceof Error ? e.name : "unknown" },
        timestamp: Date.now(),
      }),
    }).catch(() => {});
    // #endregion
    throw e;
  }
}

export async function analyzeCase(query: string): Promise<AnalysisResult> {
  try {
    const res = await fetch(`${API_BASE}/analysis`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
    });
    return handle(res, "/analysis") as Promise<AnalysisResult>;
  } catch (e) {
    // #region agent log
    fetch("http://127.0.0.1:7247/ingest/372c8d01-8027-4cb7-8dd8-e127597ea1d9", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Debug-Session-Id": "bfe8eb" },
      body: JSON.stringify({
        sessionId: "bfe8eb",
        runId: "pre-fix",
        hypothesisId: "H4",
        location: "api.ts:analyzeCase",
        message: "network_error",
        data: { op: "/analysis", err: e instanceof Error ? e.name : "unknown" },
        timestamp: Date.now(),
      }),
    }).catch(() => {});
    // #endregion
    throw e;
  }
}

export async function ingestSync(): Promise<unknown> {
  const res = await fetch(`${API_BASE}/ingest/sync`, { method: "POST" });
  return handle(res, "/ingest/sync");
}

export async function ingestUpload(file: File): Promise<{ file: string; chunks: number; status: string }> {
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch(`${API_BASE}/ingest/upload`, {
    method: "POST",
    body: fd,
  });
  return handle(res, "/ingest/upload") as Promise<{ file: string; chunks: number; status: string }>;
}

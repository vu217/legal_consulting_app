import type {
  AnalysisResult,
  AnalysisStreamOutcome,
  HealthDeps,
  IndexStats,
  PublicConfig,
  StreamServerMessage,
} from "./types";

/**
 * In dev, default to same-origin `/api` so Vite can proxy to the backend (avoids CORS and wrong-host issues).
 * Set VITE_API_BASE explicitly to override (production or custom ports).
 */
function resolveApiBase(): string {
  const v = (import.meta.env.VITE_API_BASE ?? "").trim().replace(/\/$/, "");
  if (v) return v;
  if (import.meta.env.DEV) return "/api";
  return "http://localhost:8000/api";
}

const API_BASE = resolveApiBase();

/** For error messages / debugging */
export function getApiBaseLabel(): string {
  return API_BASE.startsWith("http") ? API_BASE : `${typeof window !== "undefined" ? window.location.origin : ""}${API_BASE}`;
}

function httpHint(status: number, op: string): string {
  if (status === 404) {
    return ` Wrong URL or API_PREFIX mismatch. Use repo-root "npm run dev" (Vite proxies /api → backend), or set VITE_API_BASE in frontend/.env to match your backend (default mount is /api).`;
  }
  if (status === 0 || status >= 500) {
    return " Backend may be down or still starting — check the terminal running uvicorn.";
  }
  return "";
}

async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  const url = `${API_BASE}${path.startsWith("/") ? path : `/${path}`}`;
  try {
    return await fetch(url, init);
  } catch (e) {
    if (e instanceof TypeError) {
      throw new Error(
        `Cannot reach the API (${getApiBaseLabel()}). Start the stack from the repo root with npm run dev, or run uvicorn on port 8000.`,
      );
    }
    throw e;
  }
}

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
    const body = (detail || res.statusText || "Error").trim();
    const hint = httpHint(res.status, op);
    throw new Error(`${body} [${op} → HTTP ${res.status}]${hint}`);
  }
  return text ? JSON.parse(text) : {};
}

export async function fetchConfig(): Promise<PublicConfig> {
  try {
    const res = await apiFetch("/config");
    return handle(res, "GET /api/config") as Promise<PublicConfig>;
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
    const res = await apiFetch("/analysis", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
    });
    return handle(res, "POST /api/analysis") as Promise<AnalysisResult>;
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
  const res = await apiFetch("/ingest/sync", { method: "POST" });
  return handle(res, "POST /api/ingest/sync");
}

export async function ingestUpload(file: File): Promise<{ file: string; chunks: number; status: string }> {
  const fd = new FormData();
  fd.append("file", file);
  const res = await apiFetch("/ingest/upload", {
    method: "POST",
    body: fd,
  });
  return handle(res, "POST /api/ingest/upload") as Promise<{ file: string; chunks: number; status: string }>;
}

export async function fetchHealthDependencies(): Promise<HealthDeps> {
  const res = await apiFetch("/health/dependencies");
  return handle(res, "GET /api/health/dependencies") as Promise<HealthDeps>;
}

export async function fetchIndexStats(): Promise<IndexStats> {
  const res = await apiFetch("/index/stats");
  return handle(res, "GET /api/index/stats") as Promise<IndexStats>;
}

function parseSseBlocks(buffer: string): { events: string[]; rest: string } {
  const events: string[] = [];
  let rest = buffer;
  let pos: number;
  while ((pos = rest.indexOf("\n\n")) !== -1) {
    events.push(rest.slice(0, pos));
    rest = rest.slice(pos + 2);
  }
  return { events, rest };
}

export async function analyzeCaseStream(
  query: string,
  onMessage: (msg: StreamServerMessage) => void,
  signal?: AbortSignal,
): Promise<AnalysisStreamOutcome> {
  try {
    const res = await apiFetch("/analysis/stream", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      },
      body: JSON.stringify({ query }),
      signal,
    });
    if (!res.ok) {
      const text = await res.text();
      let detail = text;
      try {
        const j = JSON.parse(text) as { detail?: string };
        if (j.detail) detail = String(j.detail);
      } catch {
        /* keep */
      }
      const body = (detail || res.statusText).trim();
      return {
        status: "error",
        message: `${body} [POST /api/analysis/stream → HTTP ${res.status}]${httpHint(res.status, "stream")}`,
      };
    }
    const reader = res.body?.getReader();
    if (!reader) {
      return { status: "error", message: "No response body" };
    }
    const decoder = new TextDecoder();
    let buf = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const { events, rest } = parseSseBlocks(buf);
      buf = rest;
      for (const block of events) {
        for (const rawLine of block.split("\n")) {
          const line = rawLine.trim();
          if (!line.startsWith("data:")) continue;
          const payload = line.slice(5).trim();
          if (!payload) continue;
          let msg: StreamServerMessage;
          try {
            msg = JSON.parse(payload) as StreamServerMessage;
          } catch {
            continue;
          }
          onMessage(msg);
          if (msg.type === "result") {
            return { status: "complete", result: msg.payload };
          }
          if (msg.type === "error") {
            if (msg.code === "cancelled") {
              return { status: "cancelled" };
            }
            return { status: "error", message: msg.detail || "Analysis failed" };
          }
        }
      }
    }
    return { status: "error", message: "Connection closed before the result arrived." };
  } catch (e) {
    if (e instanceof Error && e.name === "AbortError") {
      return { status: "cancelled" };
    }
    throw e;
  }
}

/**
 * One-command dev: Docker (Qdrant) → FastAPI → incremental PDF ingest → Vite.
 * Run from repo root: npm install (once), then npm run dev
 */

const { spawn, execSync } = require("child_process");
const fs = require("fs");
const net = require("net");
const path = require("path");

const root = path.resolve(__dirname, "..");
const backend = path.join(root, "backend");
const frontend = path.join(root, "frontend");
const isWin = process.platform === "win32";

const py = isWin
  ? path.join(root, ".venv", "Scripts", "python.exe")
  : path.join(root, ".venv", "bin", "python");

const npmCmd = isWin ? "npm.cmd" : "npm";

function debugDevLog(message, data) {
  try {
    const line =
      JSON.stringify({
        sessionId: "bfe8eb",
        runId: "pre-fix",
        hypothesisId: "H0",
        location: "scripts/dev.js",
        message,
        data: data || {},
        timestamp: Date.now(),
      }) + "\n";
    fs.appendFileSync(path.join(root, "debug-bfe8eb.log"), line, { encoding: "utf8" });
  } catch {
    /* ignore */
  }
}

function waitPort(port, host = "127.0.0.1", timeoutMs = 90000) {
  return new Promise((resolve, reject) => {
    const start = Date.now();
    const tryOnce = () => {
      const s = net.createConnection({ port, host }, () => {
        s.end();
        resolve();
      });
      s.on("error", () => {
        s.destroy();
        if (Date.now() - start > timeoutMs) {
          reject(new Error(`Timeout waiting for ${host}:${port}`));
        } else {
          setTimeout(tryOnce, 400);
        }
      });
    };
    tryOnce();
  });
}

/** Best-effort stop Ollama so dev can start a clean `ollama serve`. */
function killExistingOllama() {
  if (isWin) {
    try {
      execSync("taskkill /IM ollama.exe /F", { stdio: "ignore", shell: true });
    } catch {
      /* not running */
    }
    try {
      execSync("taskkill /IM Ollama.exe /F", { stdio: "ignore", shell: true });
    } catch {
      /* not running */
    }
  } else {
    try {
      execSync("pkill -9 ollama", { stdio: "ignore" });
    } catch {
      /* not running */
    }
  }
}

function copyRootPdfsToBackend() {
  const srcDir = path.join(root, "pdfs");
  const dstDir = path.join(backend, "pdfs");
  if (!fs.existsSync(srcDir)) return;
  fs.mkdirSync(dstDir, { recursive: true });
  for (const name of fs.readdirSync(srcDir)) {
    if (!name.toLowerCase().endsWith(".pdf")) continue;
    const sp = path.join(srcDir, name);
    const dp = path.join(dstDir, name);
    if (!fs.existsSync(dp)) {
      fs.copyFileSync(sp, dp);
      console.log(`[dev] copied pdf: ${name} → backend/pdfs`);
    }
  }
}

function triggerIngest() {
  const http = require("http");
  return new Promise((resolve, reject) => {
    const req = http.request(
      "http://127.0.0.1:8000/api/ingest",
      { method: "POST", headers: { "Content-Type": "application/json" }, timeout: 300000 },
      (res) => {
        let body = "";
        res.on("data", (chunk) => { body += chunk; });
        res.on("end", () => {
          try {
            const json = JSON.parse(body);
            json.ok = res.statusCode >= 200 && res.statusCode < 300;
            resolve(json);
          } catch {
            resolve({ ok: res.statusCode >= 200 && res.statusCode < 300, raw: body });
          }
        });
      },
    );
    req.on("error", reject);
    req.on("timeout", () => { req.destroy(); reject(new Error("ingest request timed out")); });
    req.end();
  });
}

function ensureFrontendDeps() {
  if (fs.existsSync(path.join(frontend, "node_modules"))) return;
  console.log("[dev] installing frontend dependencies…");
  execSync(`"${npmCmd}" install`, { cwd: frontend, stdio: "inherit", shell: isWin });
}

function findSystemPython() {
  const candidates = isWin ? ["python", "python3", "py"] : ["python3", "python"];
  for (const cmd of candidates) {
    try {
      const out = execSync(`"${cmd}" --version`, { stdio: "pipe", shell: true }).toString().trim();
      if (out.startsWith("Python 3")) return cmd;
    } catch { /* try next */ }
  }
  return null;
}

function ensureVenv() {
  if (fs.existsSync(py)) return;
  console.log("[dev] Python virtual environment not found. Creating .venv …");
  const sysPy = findSystemPython();
  if (!sysPy) {
    console.error("[dev] No Python 3 found on PATH. Install Python 3.10+ and try again.");
    process.exit(1);
  }
  console.log(`[dev] Using system Python: ${sysPy}`);
  execSync(`"${sysPy}" -m venv .venv`, { cwd: root, stdio: "inherit", shell: true });
  if (!fs.existsSync(py)) {
    console.error("[dev] venv creation succeeded but python executable not found at expected path.");
    process.exit(1);
  }
  console.log("[dev] .venv created successfully.");
}

function ensureBackendDeps() {
  try {
    execSync(`"${py}" -c "import fastapi"`, { stdio: "pipe" });
  } catch {
    console.log("[dev] installing backend Python dependencies…");
    execSync(`"${py}" -m pip install -r requirements.txt`, { cwd: backend, stdio: "inherit" });
  }
}

function readEnvModels() {
  const envPath = path.join(root, ".env");
  const models = new Set();
  if (!fs.existsSync(envPath)) return ["nomic-embed-text", "qwen2.5:3b"];
  const lines = fs.readFileSync(envPath, "utf8").split("\n");
  for (const line of lines) {
    const m = line.match(/^(EMBED_MODEL|LLM_MODEL|FAST_LLM_MODEL)\s*=\s*(.+)/);
    if (m) models.add(m[2].trim());
  }
  return models.size ? [...models] : ["nomic-embed-text", "qwen2.5:3b"];
}

function ensureOllamaModels() {
  const needed = readEnvModels();
  let installed = [];
  try {
    const out = execSync("ollama list", { stdio: "pipe", shell: true }).toString();
    installed = out.split("\n").map((l) => l.split(/\s+/)[0]).filter(Boolean);
  } catch {
    console.warn("[dev] could not list Ollama models — will attempt pulls anyway.");
  }

  for (const model of needed) {
    const found = installed.some((m) => m === model || m.startsWith(model + ":") || model.includes(":") && m === model.split(":")[0]);
    if (found) {
      console.log(`[dev] Ollama model '${model}' ✓ already available`);
    } else {
      console.log(`[dev] Pulling Ollama model '${model}' — this may take a few minutes on first run …`);
      try {
        execSync(`ollama pull ${model}`, { stdio: "inherit", shell: true });
        console.log(`[dev] '${model}' pulled successfully.`);
      } catch (e) {
        console.error(`[dev] Failed to pull '${model}': ${e.message}`);
        console.error("[dev] You can pull it manually later: ollama pull " + model);
      }
    }
  }
}

async function main() {
  debugDevLog("npm_run_dev_enter", { root });
  const children = [];

  let shuttingDown = false;

  const shutdown = () => {
    if (shuttingDown) return;
    shuttingDown = true;
    console.log("\n[dev] Shutting down …");

    // 1. Kill spawned child processes (uvicorn, vite)
    for (const c of children) {
      try {
        if (c.pid) {
          if (isWin) {
            // /T kills the entire process tree (uvicorn reload children, node sub-procs)
            execSync(`taskkill /PID ${c.pid} /T /F`, { stdio: "ignore", shell: true });
          } else {
            process.kill(-c.pid, "SIGTERM");
          }
        }
      } catch { /* already dead */ }
    }

    // 2. Stop Ollama (if we started it)
    if (!process.env.LEGAL_AI_SKIP_OLLAMA_BOOT) {
      console.log("[dev] stopping Ollama …");
      killExistingOllama();
    }

    // 3. Stop Qdrant Docker container
    console.log("[dev] stopping Qdrant container …");
    try {
      execSync("docker compose down", { cwd: root, stdio: "ignore", timeout: 15000 });
    } catch { /* docker may not be available or already stopped */ }

    console.log("[dev] all services stopped. Goodbye.");
  };

  process.on("SIGINT", () => { shutdown(); process.exit(0); });
  process.on("SIGTERM", () => { shutdown(); process.exit(0); });
  process.on("exit", shutdown);

  ensureVenv();
  ensureBackendDeps();
  ensureFrontendDeps();

  // Set LEGAL_AI_SKIP_OLLAMA_BOOT=1 if you share one Ollama with other projects.
  if (!process.env.LEGAL_AI_SKIP_OLLAMA_BOOT) {
    console.log("[dev] stopping any running Ollama processes…");
    killExistingOllama();
    console.log("[dev] starting ollama serve in a separate window…");
    if (isWin) {
      // Open Ollama in its own cmd window so its output doesn't mix with this terminal.
      // Cleanup on SIGINT is handled by killExistingOllama() (taskkill by name).
      const ollamaWin = spawn("cmd", ["/c", `start "Ollama Server" cmd /k ollama serve`], {
        shell: true,
        detached: true,
        stdio: "ignore",
      });
      ollamaWin.unref();
    } else {
      const ollamaProc = spawn("ollama", ["serve"], {
        cwd: root,
        stdio: "inherit",
        shell: false,
      });
      children.push(ollamaProc);
      ollamaProc.on("error", (err) => {
        console.error("[dev] Could not start ollama:", err.message);
      });
    }
    try {
      await waitPort(11434);
    } catch {
      console.error("[dev] Ollama did not open port 11434. Install Ollama and ensure it is on PATH.");
      console.error("[dev] Or set LEGAL_AI_SKIP_OLLAMA_BOOT=1 if you start Ollama yourself.");
      killAll();
      process.exit(1);
    }
  } else {
    console.log("[dev] LEGAL_AI_SKIP_OLLAMA_BOOT set — skipping Ollama kill/spawn.");
  }

  console.log("[dev] checking Ollama models …");
  ensureOllamaModels();

  console.log("[dev] docker compose up -d …");
  try {
    execSync(`docker compose up -d`, { cwd: root, stdio: "inherit" });
  } catch {
    console.error("[dev] docker compose failed — ensure Docker is running.");
    process.exit(1);
  }

  await waitPort(6333);

  const uvicorn = spawn(py, ["-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"], {
    cwd: root,
    stdio: "inherit",
    shell: false,
  });
  children.push(uvicorn);

  uvicorn.on("error", (err) => {
    console.error("[dev] uvicorn spawn error:", err);
  });

  await waitPort(8000);

  copyRootPdfsToBackend();

  // Trigger incremental ingest via the running backend's API.
  // Runs in the background so Vite startup isn't blocked.
  console.log("[dev] triggering incremental PDF ingest via backend API …");
  triggerIngest().then((res) => {
    if (res.ok) {
      console.log(`[dev] ingest done — processed: ${res.processed ?? 0}, skipped (unchanged): ${res.skipped ?? "all"}`);
    } else {
      console.warn(`[dev] ingest request returned non-OK: ${res.detail || "unknown error"}`);
    }
  }).catch((err) => {
    console.warn(`[dev] ingest request failed (non-fatal): ${err.message}`);
  });

  const vite = spawn(npmCmd, ["run", "dev"], {
    cwd: frontend,
    stdio: "inherit",
    shell: isWin,
  });
  children.push(vite);

  await new Promise(() => {});
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});

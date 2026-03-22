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

function ensureFrontendDeps() {
  if (fs.existsSync(path.join(frontend, "node_modules"))) return;
  console.log("[dev] installing frontend dependencies…");
  execSync(`"${npmCmd}" install`, { cwd: frontend, stdio: "inherit", shell: isWin });
}

function ensureBackendDeps() {
  if (!fs.existsSync(py)) {
    console.error(`[dev] Missing venv Python at ${py}. Create .venv and pip install -r backend/requirements.txt`);
    process.exit(1);
  }
  try {
    execSync(`"${py}" -c "import fastapi"`, { stdio: "pipe" });
  } catch {
    console.log("[dev] installing backend Python dependencies…");
    execSync(`"${py}" -m pip install -r requirements.txt`, { cwd: backend, stdio: "inherit" });
  }
}

async function main() {
  debugDevLog("npm_run_dev_enter", { root });
  const children = [];

  const killAll = () => {
    for (const c of children) {
      try {
        c.kill("SIGTERM");
      } catch {
        /* ignore */
      }
    }
    if (!process.env.LEGAL_AI_SKIP_OLLAMA_BOOT) {
      killExistingOllama();
    }
  };
  process.on("SIGINT", () => {
    killAll();
    process.exit(0);
  });
  process.on("SIGTERM", () => {
    killAll();
    process.exit(0);
  });

  if (!fs.existsSync(py)) {
    console.error(`[dev] No venv found. Run: python -m venv .venv && .venv\\Scripts\\pip install -r backend\\requirements.txt`);
    process.exit(1);
  }

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

  console.log("[dev] docker compose up -d …");
  try {
    execSync(`docker compose up -d`, { cwd: root, stdio: "inherit" });
  } catch {
    console.error("[dev] docker compose failed — ensure Docker is running.");
    process.exit(1);
  }

  await waitPort(6333);

  const uvicorn = spawn(py, ["-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"], {
    cwd: backend,
    stdio: "inherit",
    shell: false,
  });
  children.push(uvicorn);

  uvicorn.on("error", (err) => {
    console.error("[dev] uvicorn spawn error:", err);
  });

  await waitPort(8000);

  copyRootPdfsToBackend();

  // Spawn sync in the background so Vite (and the UI) are not blocked.
  console.log("[dev] incremental PDF sync starting in background …");
  const syncProc = spawn(py, ["-m", "app.core.sync_incremental"], {
    cwd: backend,
    stdio: "inherit",
    shell: false,
  });
  children.push(syncProc);
  syncProc.on("exit", (code) => {
    if (code === 0 || code === null) {
      console.log("[dev] incremental PDF sync finished.");
    } else {
      console.warn(`[dev] incremental PDF sync exited with code ${code} — check Ollama / Qdrant.`);
    }
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

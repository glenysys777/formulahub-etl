"use strict";

const { spawn } = require("child_process");
const http = require("http");
const path = require("path");
const { resolvePythonBin } = require("./paths");

const DEFAULT_API_PORT = Number(process.env.FORMULAETL_API_PORT || 18765);
const HEALTH_PATH = "/health";

function healthUrl(port = DEFAULT_API_PORT) {
  return `http://127.0.0.1:${port}${HEALTH_PATH}`;
}

function fetchHealth(port = DEFAULT_API_PORT, timeoutMs = 1500) {
  return new Promise((resolve) => {
    const req = http.get(
      healthUrl(port),
      { timeout: timeoutMs },
      (res) => {
        let body = "";
        res.setEncoding("utf8");
        res.on("data", (chunk) => {
          body += chunk;
        });
        res.on("end", () => {
          if (res.statusCode !== 200) {
            resolve(null);
            return;
          }
          try {
            resolve(JSON.parse(body));
          } catch {
            resolve({ status: "ok", raw: body });
          }
        });
      },
    );
    req.on("error", () => resolve(null));
    req.on("timeout", () => {
      req.destroy();
      resolve(null);
    });
  });
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

/**
 * Ensure local API is up. Reuses a healthy existing process when present.
 * Returns { owned: boolean, child?: ChildProcess, health, port, workDir }
 */
async function ensureApi({ workDir, port = DEFAULT_API_PORT, log = console }) {
  const existing = await fetchHealth(port);
  if (existing && existing.status === "ok") {
    log.info?.("[desktop] API already healthy — reusing", healthUrl(port));
    return { owned: false, health: existing, port, workDir };
  }

  const python = resolvePythonBin();
  const apiPkg = path.join(workDir, "packages", "api");
  const runnerPkg = path.join(workDir, "packages", "runner");
  const env = {
    ...process.env,
    FORMULAETL_DEMO: process.env.FORMULAETL_DEMO || "1",
    FORMULAETL_WORK_DIR: workDir,
    FORMULAETL_EMBEDDED_WORKER: process.env.FORMULAETL_EMBEDDED_WORKER || "1",
    PYTHONPATH: [apiPkg, runnerPkg, process.env.PYTHONPATH || ""]
      .filter(Boolean)
      .join(path.delimiter),
  };

  const args = [
    "-m",
    "uvicorn",
    "formulaetl_api.main:app",
    "--host",
    "127.0.0.1",
    "--port",
    String(port),
    "--app-dir",
    apiPkg,
  ];

  log.info?.(
    `[desktop] Starting API: ${python} ${args.join(" ")} (work_dir=${workDir})`,
  );

  const child = spawn(python, args, {
    cwd: workDir,
    env,
    stdio: ["ignore", "pipe", "pipe"],
    // Detach false so we can stop on quit; Windows needs windowsHide
    windowsHide: true,
  });

  child.stdout?.on("data", (buf) => {
    const line = String(buf).trim();
    if (line) log.info?.(`[api] ${line}`);
  });
  child.stderr?.on("data", (buf) => {
    const line = String(buf).trim();
    if (line) log.info?.(`[api] ${line}`);
  });

  child.on("exit", (code, signal) => {
    log.info?.(`[desktop] API process exited code=${code} signal=${signal}`);
  });

  const deadline = Date.now() + 45000;
  let health = null;
  while (Date.now() < deadline) {
    if (child.exitCode != null) {
      throw new Error(
        `API process exited before becoming healthy (code ${child.exitCode}). ` +
          `Is Python + formulaetl installed? Try: make install`,
      );
    }
    health = await fetchHealth(port);
    if (health && health.status === "ok") {
      return { owned: true, child, health, port, workDir };
    }
    await sleep(400);
  }

  try {
    child.kill("SIGTERM");
  } catch {
    /* ignore */
  }
  throw new Error(
    `Timed out waiting for API health at ${healthUrl(port)}. ` +
      `Check Python deps: make install && make seed`,
  );
}

/**
 * Best-effort stop of an API child we spawned.
 */
async function stopApi(handle, log = console) {
  if (!handle || !handle.owned || !handle.child) {
    return;
  }
  const child = handle.child;
  if (child.exitCode != null) {
    return;
  }
  log.info?.("[desktop] Stopping owned API process…");
  try {
    child.kill("SIGTERM");
  } catch (err) {
    log.info?.(`[desktop] SIGTERM failed: ${err}`);
  }
  const until = Date.now() + 5000;
  while (Date.now() < until && child.exitCode == null) {
    await sleep(100);
  }
  if (child.exitCode == null) {
    try {
      child.kill("SIGKILL");
    } catch {
      /* ignore */
    }
  }
}

module.exports = {
  DEFAULT_API_PORT,
  healthUrl,
  fetchHealth,
  ensureApi,
  stopApi,
};

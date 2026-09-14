"use strict";

const path = require("path");
const fs = require("fs");
const http = require("http");
const { app, BrowserWindow, shell, dialog, Menu } = require("electron");
const {
  resolveWorkDir,
  resolveStudioWebRoot,
  resolvePythonBin,
} = require("./paths");
const {
  ensureApi,
  stopApi,
  fetchHealth,
  DEFAULT_API_PORT,
} = require("./api-manager");

/** @type {import('electron').BrowserWindow | null} */
let mainWindow = null;
/** @type {Awaited<ReturnType<typeof ensureApi>> | null} */
let apiHandle = null;
/** @type {http.Server | null} */
let staticServer = null;
let quitting = false;
/** Studio URL currently loaded in the window (http://127.0.0.1:UI_PORT/). */
let studioUrl = null;
/** Prevent repeated auto-restarts in one session after a single recovery. */
let apiAutoRestartUsed = false;
/** @type {ReturnType<typeof setInterval> | null} */
let healthTimer = null;
let restartingApi = false;

const isDev = process.argv.includes("--dev");
const UI_PORT = Number(process.env.FORMULAETL_UI_PORT || 18766);

const log = {
  info: (...args) => console.log(...args),
};

function createLoadingHtml(message, { reconnect = false } = {}) {
  const reconnectBlock = reconnect
    ? `<p class="hint">The local API stopped. Retrying once…</p>`
    : "";
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>FormulaHub Studio</title>
  <style>
    :root {
      --bg0: #0f1419;
      --bg1: #1a2332;
      --accent: #3d8bfd;
      --text: #e8eef7;
      --muted: #8b9bb4;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      font-family: "SF Pro Display", "Segoe UI", system-ui, sans-serif;
      color: var(--text);
      background:
        radial-gradient(ellipse 80% 60% at 20% 10%, #1e3a5f 0%, transparent 55%),
        radial-gradient(ellipse 70% 50% at 90% 80%, #152238 0%, transparent 50%),
        linear-gradient(160deg, var(--bg0), var(--bg1));
    }
    .card { text-align: center; padding: 2rem; max-width: 28rem; }
    .brand {
      font-size: 1.75rem;
      font-weight: 700;
      letter-spacing: -0.02em;
      margin: 0 0 0.35rem;
    }
    .sub { color: var(--muted); margin: 0 0 1.5rem; font-size: 0.95rem; }
    .msg { color: var(--text); font-size: 0.9rem; opacity: 0.9; }
    .hint { color: var(--accent); font-size: 0.85rem; margin-top: 1rem; }
    .spin {
      width: 28px; height: 28px; margin: 0 auto 1.25rem;
      border: 2px solid rgba(61,139,253,0.25);
      border-top-color: var(--accent);
      border-radius: 50%;
      animation: rot 0.8s linear infinite;
    }
    @keyframes rot { to { transform: rotate(360deg); } }
  </style>
</head>
<body>
  <div class="card">
    <div class="spin" aria-hidden="true"></div>
    <h1 class="brand">FormulaHub Studio</h1>
    <p class="sub">Local ETL on this machine</p>
    <p class="msg" id="msg">${message}</p>
    ${reconnectBlock}
  </div>
</body>
</html>`;
}

function loadLoading(message, opts) {
  if (!mainWindow || mainWindow.isDestroyed()) return Promise.resolve();
  return mainWindow.loadURL(
    `data:text/html;charset=utf-8,${encodeURIComponent(
      createLoadingHtml(message, opts),
    )}`,
  );
}

function startStaticServer(webRoot) {
  return new Promise((resolve, reject) => {
    const server = http.createServer((req, res) => {
      const urlPath = decodeURIComponent((req.url || "/").split("?")[0]);
      let rel = urlPath === "/" ? "/index.html" : urlPath;
      const filePath = path.normalize(path.join(webRoot, rel));
      if (!filePath.startsWith(webRoot)) {
        res.writeHead(403);
        res.end("Forbidden");
        return;
      }
      fs.readFile(filePath, (err, data) => {
        if (err) {
          // SPA fallback
          fs.readFile(path.join(webRoot, "index.html"), (err2, html) => {
            if (err2) {
              res.writeHead(404);
              res.end("Not found");
              return;
            }
            res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
            res.end(html);
          });
          return;
        }
        const ext = path.extname(filePath).toLowerCase();
        const types = {
          ".html": "text/html; charset=utf-8",
          ".js": "text/javascript; charset=utf-8",
          ".css": "text/css; charset=utf-8",
          ".svg": "image/svg+xml",
          ".png": "image/png",
          ".json": "application/json",
          ".woff2": "font/woff2",
        };
        res.writeHead(200, {
          "Content-Type": types[ext] || "application/octet-stream",
        });
        res.end(data);
      });
    });
    server.once("error", reject);
    server.listen(UI_PORT, "127.0.0.1", () => {
      staticServer = server;
      resolve(`http://127.0.0.1:${UI_PORT}/`);
    });
  });
}

function stopStaticServer() {
  if (!staticServer) return;
  try {
    staticServer.close();
  } catch {
    /* ignore */
  }
  staticServer = null;
}

function studioBrowserUrl() {
  return studioUrl || `http://127.0.0.1:${UI_PORT}/`;
}

function openInBrowser() {
  shell.openExternal(studioBrowserUrl());
}

function stopHealthWatch() {
  if (healthTimer) {
    clearInterval(healthTimer);
    healthTimer = null;
  }
}

function startHealthWatch() {
  stopHealthWatch();
  healthTimer = setInterval(() => {
    void onHealthTick();
  }, 4000);
}

async function onHealthTick() {
  if (quitting || restartingApi || !mainWindow || mainWindow.isDestroyed()) {
    return;
  }
  const health = await fetchHealth(DEFAULT_API_PORT);
  if (health && health.status === "ok") {
    return;
  }
  // API gone — auto-restart once, then show reconnect message.
  log.info("[desktop] API health lost");
  if (!apiAutoRestartUsed) {
    apiAutoRestartUsed = true;
    await restartApi({ reason: "auto-reconnect" });
    return;
  }
  await loadLoading(
    "Local API disconnected.<br/><br/>Use <b>Studio → Restart API</b> or quit and reopen.",
  );
}

async function restartApi({ reason = "menu" } = {}) {
  if (restartingApi || quitting) return;
  restartingApi = true;
  log.info(`[desktop] Restart API (${reason})`);
  try {
    await loadLoading(
      reason === "auto-reconnect"
        ? "Reconnecting to local API…"
        : "Restarting local API…",
      { reconnect: reason === "auto-reconnect" },
    );
    await stopApi(apiHandle, log);
    apiHandle = null;
    const workDir = resolveWorkDir();
    apiHandle = await ensureApi({ workDir, log });
    if (studioUrl) {
      await mainWindow?.loadURL(studioUrl);
    } else {
      await loadStudioUi(workDir);
    }
    log.info("[desktop] API restart OK");
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    await loadLoading(`Could not restart API.<br/><br/>${msg}`);
    dialog.showErrorBox("FormulaHub Studio", msg);
  } finally {
    restartingApi = false;
  }
}

function buildMenu() {
  const studioMenu = {
    label: "Studio",
    submenu: [
      {
        label: "Open in Browser",
        accelerator: "CmdOrCtrl+Shift+B",
        click: () => openInBrowser(),
      },
      {
        label: "Restart API",
        accelerator: "CmdOrCtrl+Shift+R",
        click: () => {
          void restartApi({ reason: "menu" });
        },
      },
      { type: "separator" },
      {
        label: "API health…",
        click: async () => {
          const h = await fetchHealth(DEFAULT_API_PORT);
          dialog.showMessageBox({
            type: "info",
            title: "API health",
            message: h
              ? JSON.stringify(h, null, 2)
              : "API not reachable on 127.0.0.1:18765",
          });
        },
      },
    ],
  };

  const template = [
    ...(process.platform === "darwin"
      ? [
          {
            label: app.name,
            submenu: [
              { role: "about" },
              { type: "separator" },
              { role: "hide" },
              { role: "hideOthers" },
              { role: "unhide" },
              { type: "separator" },
              { role: "quit" },
            ],
          },
        ]
      : []),
    {
      label: "File",
      submenu: [
        process.platform === "darwin" ? { role: "close" } : { role: "quit" },
      ],
    },
    {
      label: "Edit",
      submenu: [
        { role: "undo" },
        { role: "redo" },
        { type: "separator" },
        { role: "cut" },
        { role: "copy" },
        { role: "paste" },
        { role: "selectAll" },
      ],
    },
    studioMenu,
    {
      label: "View",
      submenu: [
        { role: "reload" },
        { role: "toggleDevTools" },
        { type: "separator" },
        { role: "resetZoom" },
        { role: "zoomIn" },
        { role: "zoomOut" },
        { type: "separator" },
        { role: "togglefullscreen" },
      ],
    },
    {
      label: "Help",
      submenu: [
        {
          label: "Docs: Desktop shell",
          click: () => {
            const workDir = resolveWorkDir();
            const doc = path.join(workDir, "docs", "studio", "DESKTOP_SHELL.md");
            if (fs.existsSync(doc)) {
              shell.openPath(doc);
            } else {
              shell.openExternal(
                "https://github.com/glenysys777/formulahub-etl/blob/main/docs/studio/DESKTOP_SHELL.md",
              );
            }
          },
        },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

async function loadStudioUi(workDir) {
  // Dev: prefer Vite if running; else built Studio web.
  if (isDev) {
    const viteOk = await new Promise((resolve) => {
      const req = http.get(
        `http://127.0.0.1:${UI_PORT}/`,
        { timeout: 800 },
        (res) => {
          res.resume();
          resolve(res.statusCode && res.statusCode < 500);
        },
      );
      req.on("error", () => resolve(false));
      req.on("timeout", () => {
        req.destroy();
        resolve(false);
      });
    });
    if (viteOk) {
      studioUrl = `http://127.0.0.1:${UI_PORT}/`;
      await mainWindow.loadURL(studioUrl);
      return;
    }
  }

  const webRoot = resolveStudioWebRoot(workDir);
  if (!webRoot) {
    const tip =
      "Studio UI build not found. Run: cd apps/web && npm ci && npm run build";
    await loadLoading(tip);
    dialog.showErrorBox("FormulaHub Studio", tip);
    return;
  }

  if (!staticServer) {
    studioUrl = await startStaticServer(webRoot);
  } else {
    studioUrl = `http://127.0.0.1:${UI_PORT}/`;
  }
  log.info(`[desktop] Serving Studio from ${webRoot} at ${studioUrl}`);
  await mainWindow.loadURL(studioUrl);
}

async function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1024,
    minHeight: 680,
    title: "FormulaHub Studio",
    backgroundColor: "#0f1419",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
    show: false,
  });

  mainWindow.once("ready-to-show", () => mainWindow?.show());

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  await loadLoading("Starting local API…");

  const workDir = resolveWorkDir();
  log.info(`[desktop] work_dir=${workDir}`);
  log.info(`[desktop] python=${resolvePythonBin()}`);

  try {
    apiHandle = await ensureApi({ workDir, log });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    await loadLoading(`Could not start API.<br/><br/>${msg}`);
    dialog.showErrorBox("FormulaHub Studio", msg);
    return;
  }

  const health = apiHandle.health;
  const shownWorkDir = health?.work_dir || workDir;
  log.info(`[desktop] API ready · work_dir=${shownWorkDir}`);

  await loadStudioUi(workDir);
  startHealthWatch();
}

app.whenReady().then(async () => {
  buildMenu();
  await createWindow();

  app.on("activate", async () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      await createWindow();
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", (event) => {
  if (quitting) return;
  quitting = true;
  event.preventDefault();
  (async () => {
    stopHealthWatch();
    stopStaticServer();
    await stopApi(apiHandle, log);
    apiHandle = null;
    app.exit(0);
  })();
});

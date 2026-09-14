"use strict";

const fs = require("fs");
const path = require("path");

/**
 * Resolve the FormulaHub ETL repo / work_dir root.
 *
 * Priority:
 * 1. FORMULAETL_WORK_DIR
 * 2. FORMULAETL_HOME
 * 3. Packaged: sibling of .app Resources, or ~/FormulaHub-ETL
 * 4. Dev: walk up from this file until packages/api + apps/web exist
 */
function findRepoRoot(startDir) {
  let cur = path.resolve(startDir);
  for (let i = 0; i < 8; i++) {
    const api = path.join(cur, "packages", "api");
    const web = path.join(cur, "apps", "web");
    if (fs.existsSync(api) && fs.existsSync(web)) {
      return cur;
    }
    const parent = path.dirname(cur);
    if (parent === cur) break;
    cur = parent;
  }
  return null;
}

function tryElectronApp() {
  try {
    // Outside Electron, `require("electron")` may resolve to the package stub
    // where `app` is undefined. Only treat a real runtime app as present.
    // eslint-disable-next-line global-require
    const mod = require("electron");
    if (mod && typeof mod === "object" && mod.app && typeof mod.app.isPackaged === "boolean") {
      return mod.app;
    }
    return null;
  } catch {
    return null;
  }
}

function resolveWorkDir() {
  const fromEnv =
    process.env.FORMULAETL_WORK_DIR || process.env.FORMULAETL_HOME || "";
  if (fromEnv.trim()) {
    return path.resolve(fromEnv.trim());
  }

  const electronApp = tryElectronApp();
  const packaged = Boolean(electronApp?.isPackaged);

  if (packaged) {
    const resourcesPath = process.resourcesPath || "";
    const sibling = resourcesPath
      ? findRepoRoot(path.dirname(resourcesPath))
      : null;
    if (sibling) return sibling;
    const home =
      electronApp.getPath?.("home") ||
      process.env.HOME ||
      process.env.USERPROFILE ||
      "";
    const homeDefault = path.join(home, "FormulaHub-ETL");
    if (fs.existsSync(path.join(homeDefault, "packages", "api"))) {
      return homeDefault;
    }
    return homeDefault;
  }

  const fromSrc = findRepoRoot(__dirname);
  if (fromSrc) return fromSrc;

  return path.resolve(process.cwd());
}

function resolveStudioWebRoot(workDir) {
  const electronApp = tryElectronApp();
  if (electronApp?.isPackaged && process.resourcesPath) {
    const bundled = path.join(process.resourcesPath, "studio-web");
    if (fs.existsSync(path.join(bundled, "index.html"))) {
      return bundled;
    }
  }
  const dist = path.join(workDir, "apps", "web", "dist");
  if (fs.existsSync(path.join(dist, "index.html"))) {
    return dist;
  }
  return null;
}

function resolvePythonBin() {
  return (
    process.env.FORMULAETL_PYTHON ||
    process.env.PYTHON ||
    (process.platform === "win32" ? "python" : "python3")
  );
}

module.exports = {
  findRepoRoot,
  resolveWorkDir,
  resolveStudioWebRoot,
  resolvePythonBin,
};

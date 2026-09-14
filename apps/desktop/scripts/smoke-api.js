"use strict";

/**
 * Headless smoke test: spawn/reuse API + confirm /health work_dir.
 * Does not open Electron (Linux CI / cloud agent safe).
 */
const path = require("path");
const {
  resolveWorkDir,
  resolveStudioWebRoot,
  findRepoRoot,
} = require("../src/paths");
const { ensureApi, stopApi, fetchHealth } = require("../src/api-manager");

async function main() {
  const workDir = resolveWorkDir();
  const repo = findRepoRoot(__dirname);
  if (!repo) {
    throw new Error("could not find repo root from apps/desktop");
  }
  if (path.resolve(workDir) !== path.resolve(repo) && !process.env.FORMULAETL_WORK_DIR) {
    console.warn(`work_dir=${workDir} (repo=${repo})`);
  }

  const web = resolveStudioWebRoot(workDir);
  if (!web) {
    throw new Error("apps/web/dist missing — run make build first");
  }
  console.log("studio web root:", web);

  const before = await fetchHealth();
  const handle = await ensureApi({
    workDir,
    log: { info: (...a) => console.log(...a) },
  });
  if (!handle.health || handle.health.status !== "ok") {
    throw new Error("API health not ok");
  }
  if (!handle.health.work_dir) {
    throw new Error("health missing work_dir");
  }
  console.log("health work_dir:", handle.health.work_dir);
  console.log("api owned by shell:", handle.owned);

  // If we started it, stop it. If we reused, leave it.
  if (handle.owned) {
    await stopApi(handle, { info: (...a) => console.log(...a) });
    const after = await fetchHealth();
    if (after) {
      console.warn("API still healthy after stop (best-effort may lag)");
    } else {
      console.log("API stopped cleanly");
    }
  } else if (!before) {
    console.log("unexpected: owned=false but no prior health");
  } else {
    console.log("reused existing API — left running");
  }
  console.log("smoke OK");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});

"use strict";

/**
 * Lightweight syntax/structure check for the desktop shell (no Electron runtime required).
 * Used by CI on Linux where we lint/build-check but do not produce a signed Mac .app.
 */
const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");

const root = path.join(__dirname, "..");
const required = [
  "package.json",
  "src/main.js",
  "src/api-manager.js",
  "src/paths.js",
  "src/preload.js",
  "build/icon.png",
  "build/icon.icns",
  "README.md",
];

let failed = false;

for (const rel of required) {
  const full = path.join(root, rel);
  if (!fs.existsSync(full)) {
    console.error(`missing: ${rel}`);
    failed = true;
  }
}

const pkg = JSON.parse(
  fs.readFileSync(path.join(root, "package.json"), "utf8"),
);
if (pkg.main !== "src/main.js") {
  console.error("package.json main must be src/main.js");
  failed = true;
}
if (!pkg.scripts?.["build:check"]) {
  console.error("package.json missing build:check script");
  failed = true;
}
if (!pkg.scripts?.["dist:mac"]) {
  console.error("package.json missing dist:mac script");
  failed = true;
}

const mainSrc = fs.readFileSync(path.join(root, "src/main.js"), "utf8");
for (const needle of ["Open in Browser", "Restart API", "auto-reconnect"]) {
  if (!mainSrc.includes(needle)) {
    console.error(`src/main.js missing expected feature marker: ${needle}`);
    failed = true;
  }
}

for (const file of [
  "src/main.js",
  "src/api-manager.js",
  "src/paths.js",
  "src/preload.js",
  "scripts/lint.js",
]) {
  const r = spawnSync(process.execPath, ["--check", path.join(root, file)], {
    encoding: "utf8",
  });
  if (r.status !== 0) {
    console.error(`syntax error in ${file}:\n${r.stderr || r.stdout}`);
    failed = true;
  }
}

if (failed) {
  process.exit(1);
}
console.log("desktop shell lint OK");

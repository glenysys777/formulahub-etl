import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  addContextSet,
  deleteContextSet,
  duplicateContextSet,
  ensureContextsMetadata,
  parseContexts,
  renameContextSet,
  rowsToContextEntries,
  setActiveContext,
  setContextEntries,
  setRunParam,
} from "./vars.ts";

describe("Job Contexts helpers", () => {
  it("seeds DEV/QA/PROD with starter keys when empty", () => {
    const meta = ensureContextsMetadata({});
    const { active, sets } = parseContexts(meta);
    assert.equal(active, "DEV");
    assert.deepEqual(Object.keys(sets).sort(), ["DEV", "PROD", "QA"]);
    assert.deepEqual(sets.DEV, { env: "", catalog: "", schema: "" });
    assert.ok(meta.run_params);
    assert.equal((meta.run_params as Record<string, unknown>).run_date, "");
    assert.equal((meta.run_params as Record<string, unknown>).job_name, "");
  });

  it("does not overwrite existing context sets", () => {
    const meta = ensureContextsMetadata({
      contexts: {
        active: "QA",
        sets: { QA: { env: "qa", catalog: "qa_main" } },
      },
    });
    const { active, sets } = parseContexts(meta);
    assert.equal(active, "QA");
    assert.deepEqual(Object.keys(sets), ["QA"]);
    assert.equal(sets.QA.env, "qa");
  });

  it("switches active context and edits entries", () => {
    let meta = ensureContextsMetadata({});
    meta = setActiveContext(meta, "PROD");
    assert.equal(parseContexts(meta).active, "PROD");
    meta = setContextEntries(meta, "PROD", { env: "prod", catalog: "main" });
    assert.equal(parseContexts(meta).sets.PROD.catalog, "main");
  });

  it("adds, duplicates, renames, and deletes sets", () => {
    let meta = ensureContextsMetadata({});
    meta = addContextSet(meta, "STAGING");
    assert.ok(parseContexts(meta).sets.STAGING);
    meta = duplicateContextSet(meta, "DEV", "DEV2");
    assert.deepEqual(parseContexts(meta).sets.DEV2, parseContexts(meta).sets.DEV);
    meta = renameContextSet(meta, "DEV2", "DEV_CLONE");
    assert.ok(parseContexts(meta).sets.DEV_CLONE);
    assert.equal(parseContexts(meta).sets.DEV2, undefined);
    meta = deleteContextSet(meta, "STAGING");
    assert.equal(parseContexts(meta).sets.STAGING, undefined);
  });

  it("updates run_params", () => {
    let meta = ensureContextsMetadata({});
    meta = setRunParam(meta, "run_date", "2026-09-14");
    meta = setRunParam(meta, "job_name", "nightly");
    const rp = meta.run_params as Record<string, unknown>;
    assert.equal(rp.run_date, "2026-09-14");
    assert.equal(rp.job_name, "nightly");
  });

  it("rowsToContextEntries skips blank keys and duplicate keys", () => {
    const entries = rowsToContextEntries([
      { key: "env", value: "dev" },
      { key: "  ", value: "x" },
      { key: "env", value: "ignored" },
      { key: "catalog", value: "sandbox" },
    ]);
    assert.deepEqual(entries, { env: "dev", catalog: "sandbox" });
  });
});

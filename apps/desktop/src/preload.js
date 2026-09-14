"use strict";

/**
 * Preload stays minimal — Studio talks to the local API over HTTP.
 * No Node APIs are exposed to the WebView (cloud auth stays out of this wave).
 */
const { contextBridge } = require("electron");

contextBridge.exposeInMainWorld("formulaHubDesktop", {
  isDesktop: true,
  shell: "electron",
});

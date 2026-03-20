/**
 * SpiritPool — Minimal Browser API Polyfill
 *
 * Firefox uses the `browser.*` namespace (Promise-based).
 * Chrome/Safari MV3 use `chrome.*` (also Promise-based in MV3).
 *
 * This shim aliases `chrome` → `browser` so the same source code
 * works on all three platforms without modification.
 *
 * Loaded FIRST in every context (content scripts via manifest,
 * popup/options via <script> tag, background via concatenation).
 */
if (typeof browser === "undefined") {
  if (typeof chrome !== "undefined") {
    var browser = chrome;          // var hoists to function/global scope
    globalThis.browser = chrome;   // covers service-worker scope
    if (typeof window !== "undefined") {
      window.browser = chrome;     // covers content-script & popup scope
    }
    if (typeof self !== "undefined") {
      self.browser = chrome;       // covers service-worker scope
    }
  }
}

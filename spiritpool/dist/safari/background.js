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

// ── Original background.js ────────────────────────────────
/**
 * SpiritPool — Background Service Worker
 *
 * Responsibilities:
 *  - Receive signals from content scripts
 *  - Queue signals in domain-separated local cache
 *  - Batch flush to backend when ready (future)
 *  - Manage alarms for periodic flush
 *  - Enforce consent state before accepting signals
 */

const QUEUE_ALARM = "spiritpool-flush";
const FLUSH_INTERVAL_MIN = 10; // minutes between batch flushes
const MAX_QUEUE_SIZE = 500;    // flush immediately if queue exceeds this

// ── Initialisation ─────────────────────────────────────────────────────────

browser.runtime.onInstalled.addListener(async (details) => {
  if (details.reason === "install") {
    // First install — set default state
    await browser.storage.local.set({
      consent: {
        given: false,
        timestamp: null,
        version: 1,
      },
      siteToggles: {
        "indeed.com": true,
        "linkedin.com": true,
        "glassdoor.com": true,
        "google.com/maps": true,
        "apply.starbucks.com": true,
      },
      stats: {
        totalSignals: 0,
        todaySignals: 0,
        lastResetDate: new Date().toISOString().slice(0, 10),
        lastFlush: null,
      },
    });

    // Initialise domain-separated caches
    await initDomainCaches();

    console.log("[SpiritPool] Extension installed — awaiting consent.");
  }

  // Set up periodic flush alarm
  browser.alarms.create(QUEUE_ALARM, { periodInMinutes: FLUSH_INTERVAL_MIN });
});

browser.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name === QUEUE_ALARM) {
    await flushAllDomains();
  }
});

// ── Domain Cache Management ────────────────────────────────────────────────

/**
 * Each domain stores signals independently under its own key.
 * This keeps data separate and makes per-site opt-out trivial.
 *
 * Storage layout:
 *   cache:indeed.com       → { signals: [...], lastUpdate: ISO }
 *   cache:linkedin.com     → { signals: [...], lastUpdate: ISO }
 *   cache:glassdoor.com    → { signals: [...], lastUpdate: ISO }
 *   cache:google.com/maps  → { signals: [...], lastUpdate: ISO }
 *   cache:apply.starbucks.com → { signals: [...], lastUpdate: ISO }
 */

const DOMAINS = [
  "indeed.com",
  "linkedin.com",
  "glassdoor.com",
  "google.com/maps",
  "apply.starbucks.com",
];

function cacheKey(domain) {
  return `cache:${domain}`;
}

async function initDomainCaches() {
  const defaults = {};
  for (const domain of DOMAINS) {
    defaults[cacheKey(domain)] = {
      signals: [],
      lastUpdate: null,
    };
  }
  await browser.storage.local.set(defaults);
}

async function getDomainCache(domain) {
  const key = cacheKey(domain);
  const result = await browser.storage.local.get(key);
  return result[key] || { signals: [], lastUpdate: null };
}

async function appendSignal(domain, signal) {
  const key = cacheKey(domain);
  const cache = await getDomainCache(domain);

  cache.signals.push(signal);
  cache.lastUpdate = new Date().toISOString();

  // Trim oldest if over limit
  if (cache.signals.length > MAX_QUEUE_SIZE) {
    cache.signals = cache.signals.slice(-MAX_QUEUE_SIZE);
  }

  await browser.storage.local.set({ [key]: cache });

  // Update stats
  await incrementStats();

  return cache.signals.length;
}

async function clearDomainCache(domain) {
  const key = cacheKey(domain);
  await browser.storage.local.set({
    [key]: { signals: [], lastUpdate: new Date().toISOString() },
  });
}

// ── Stats Tracking ─────────────────────────────────────────────────────────

async function incrementStats() {
  const { stats } = await browser.storage.local.get("stats");
  const today = new Date().toISOString().slice(0, 10);

  if (stats.lastResetDate !== today) {
    stats.todaySignals = 0;
    stats.lastResetDate = today;
  }

  stats.totalSignals += 1;
  stats.todaySignals += 1;

  await browser.storage.local.set({ stats });
}

// ── Consent Check ──────────────────────────────────────────────────────────

async function isConsentGiven() {
  const { consent } = await browser.storage.local.get("consent");
  return consent && consent.given === true;
}

async function isSiteEnabled(domain) {
  const { siteToggles } = await browser.storage.local.get("siteToggles");
  return siteToggles && siteToggles[domain] !== false;
}

// ── Tracking Pause ─────────────────────────────────────────────────────────

const PAUSE_DURATION_MS = 24 * 60 * 60 * 1000; // 24 hours

/**
 * Returns { paused: bool, pausedAt: ISO|null, remainingMs: number|null }.
 * Auto-re-enables tracking if 24 h have elapsed.
 */
async function getTrackingPauseState() {
  const { trackingPause } = await browser.storage.local.get("trackingPause");
  if (!trackingPause || !trackingPause.paused) {
    return { paused: false, pausedAt: null, remainingMs: null };
  }

  const elapsed = Date.now() - new Date(trackingPause.pausedAt).getTime();
  if (elapsed >= PAUSE_DURATION_MS) {
    // Auto-re-enable
    await browser.storage.local.set({ trackingPause: { paused: false, pausedAt: null } });
    console.log("[SpiritPool] Tracking auto-re-enabled after 24 h pause.");
    return { paused: false, pausedAt: null, remainingMs: null };
  }

  return {
    paused: true,
    pausedAt: trackingPause.pausedAt,
    remainingMs: PAUSE_DURATION_MS - elapsed,
  };
}

// ── Message Handler — Content Scripts → Background ─────────────────────────
// Chrome MV3 does not reliably support returning a Promise from an async
// onMessage listener.  The cross-browser safe pattern is:
//   1. Kick off the async work
//   2. Call sendResponse() when done
//   3. Return true synchronously to keep the channel open

browser.runtime.onMessage.addListener((message, sender, sendResponse) => {
  handleMessage(message, sender).then(sendResponse, (err) =>
    sendResponse({ ok: false, reason: err.message })
  );
  return true; // keep channel open for async sendResponse
});

async function handleMessage(message, sender) {
  if (message.type === "spiritpool:signal") {
    const { domain, signal } = message;

    // Gate on consent
    if (!(await isConsentGiven())) {
      return { ok: false, reason: "consent_not_given" };
    }

    // Gate on tracking pause
    const pauseState = await getTrackingPauseState();
    if (pauseState.paused) {
      return { ok: false, reason: "tracking_paused" };
    }

    // Gate on per-site toggle
    if (!(await isSiteEnabled(domain))) {
      return { ok: false, reason: "site_disabled" };
    }

    // Validate minimal signal shape
    if (!signal || !signal.source || !signal.observedAt) {
      return { ok: false, reason: "invalid_signal" };
    }

    // Stamp with metadata
    signal.collectedAt = new Date().toISOString();
    signal.tabUrl = sender.tab?.url || null;

    const queueLen = await appendSignal(domain, signal);

    console.log(
      `[SpiritPool] Queued signal from ${domain} (${queueLen} in cache)`
    );

    // Immediate flush if queue is large
    if (queueLen >= MAX_QUEUE_SIZE) {
      await flushDomain(domain);
    }

    return { ok: true, queued: queueLen };
  }

  if (message.type === "spiritpool:getStatus") {
    const consent = await isConsentGiven();
    const { stats } = await browser.storage.local.get("stats");
    const { siteToggles } = await browser.storage.local.get("siteToggles");
    const trackingPause = await getTrackingPauseState();

    // Gather per-domain queue sizes
    const caches = {};
    for (const d of DOMAINS) {
      const c = await getDomainCache(d);
      caches[d] = c.signals.length;
    }

    return { consent, stats, siteToggles, caches, trackingPause };
  }

  if (message.type === "spiritpool:grantConsent") {
    await browser.storage.local.set({
      consent: {
        given: true,
        timestamp: new Date().toISOString(),
        version: 1,
      },
    });
    return { ok: true };
  }

  if (message.type === "spiritpool:revokeConsent") {
    await browser.storage.local.set({
      consent: {
        given: false,
        timestamp: new Date().toISOString(),
        version: 1,
      },
    });
    // Clear all caches when consent is revoked
    for (const d of DOMAINS) {
      await clearDomainCache(d);
    }
    return { ok: true };
  }

  if (message.type === "spiritpool:toggleSite") {
    const { domain: d, enabled } = message;
    const { siteToggles } = await browser.storage.local.get("siteToggles");
    siteToggles[d] = enabled;
    await browser.storage.local.set({ siteToggles });

    // If disabling, clear that domain's cache
    if (!enabled) {
      await clearDomainCache(d);
    }

    return { ok: true };
  }

  if (message.type === "spiritpool:getDomainCache") {
    const cache = await getDomainCache(message.domain);
    return cache;
  }

  if (message.type === "spiritpool:clearDomainCache") {
    await clearDomainCache(message.domain);
    return { ok: true };
  }

  if (message.type === "spiritpool:flushAll") {
    try {
      await flushAllDomains();
      return { ok: true };
    } catch (err) {
      return { ok: false, reason: err.message };
    }
  }

  if (message.type === "spiritpool:pauseTracking") {
    await browser.storage.local.set({
      trackingPause: { paused: true, pausedAt: new Date().toISOString() },
    });
    console.log("[SpiritPool] Tracking paused by user (auto-resumes in 24 h).");
    return { ok: true };
  }

  if (message.type === "spiritpool:resumeTracking") {
    await browser.storage.local.set({
      trackingPause: { paused: false, pausedAt: null },
    });
    console.log("[SpiritPool] Tracking resumed by user.");
    return { ok: true };
  }

  if (message.type === "spiritpool:getBackendStats") {
    try {
      const response = await fetch(`${BACKEND_URL}/stats`);
      if (response.ok) {
        const data = await response.json();
        return { ok: true, stats: data };
      }
      return { ok: false, reason: `HTTP ${response.status}` };
    } catch (err) {
      return { ok: false, reason: err.message };
    }
  }

  return { ok: false, reason: "unknown_message_type" };
}

// ── Flush Logic (local cache → SQL backend) ───────────────────────────────

const BACKEND_URL = "http://localhost:8765/api/spiritpool";

/**
 * Generate or retrieve a stable contributor UUID for this extension install.
 */
async function getContributorId() {
  const { contributorId } = await browser.storage.local.get("contributorId");
  if (contributorId) return contributorId;

  // Generate a new UUID (crypto.randomUUID is available in MV3)
  const newId = typeof crypto !== "undefined" && crypto.randomUUID
    ? crypto.randomUUID()
    : "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
        const r = (Math.random() * 16) | 0;
        return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
      });

  await browser.storage.local.set({ contributorId: newId });
  return newId;
}

/**
 * Flush signals for one domain to the SQL backend.
 * On success, clears the local cache for that domain.
 * On failure, signals stay in local cache for retry next cycle.
 */
async function flushDomain(domain) {
  const cache = await getDomainCache(domain);
  if (cache.signals.length === 0) return;

  console.log(
    `[SpiritPool] Flushing ${cache.signals.length} signals for ${domain} → backend...`
  );

  try {
    const contributorId = await getContributorId();
    const response = await fetch(`${BACKEND_URL}/contribute`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        domain,
        signals: cache.signals,
        contributorId,
      }),
    });

    if (response.ok) {
      const result = await response.json();
      console.log(
        `[SpiritPool] ✅ Flushed ${domain}: ${result.accepted} accepted, ${result.new_jobs} new jobs`
      );
      await clearDomainCache(domain);

      // Update flush timestamp
      const { stats } = await browser.storage.local.get("stats");
      stats.lastFlush = new Date().toISOString();
      await browser.storage.local.set({ stats });
    } else {
      const errText = await response.text();
      console.warn(`[SpiritPool] ⚠ Flush failed for ${domain}: HTTP ${response.status} — ${errText}`);
    }
  } catch (err) {
    console.warn(
      `[SpiritPool] ⚠ Flush failed for ${domain} (backend offline?): ${err.message}`
    );
    // Signals stay in local cache — will retry on next alarm
  }
}

async function flushAllDomains() {
  for (const domain of DOMAINS) {
    await flushDomain(domain);
  }
}

console.log("[SpiritPool] Background service worker loaded.");

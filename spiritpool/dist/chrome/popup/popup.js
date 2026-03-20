/**
 * SpiritPool — Popup Controller
 *
 * Manages the popup UI: consent flow, stats display, site toggles.
 */

const DOMAINS = [
  { key: "indeed.com", label: "Indeed" },
  { key: "linkedin.com", label: "LinkedIn Jobs" },
  { key: "glassdoor.com", label: "Glassdoor" },
  { key: "google.com/maps", label: "Google Maps" },
  { key: "apply.starbucks.com", label: "Starbucks Careers" },
];

document.addEventListener("DOMContentLoaded", init);

async function init() {
  const status = await browser.runtime.sendMessage({
    type: "spiritpool:getStatus",
  });

  if (!status || !status.consent) {
    showConsent();
  } else {
    showMain(status);
  }

  bindEvents();
}

function showConsent() {
  document.getElementById("consent-gate").classList.remove("hidden");
  document.getElementById("main-popup").classList.add("hidden");
}

function showMain(status) {
  document.getElementById("consent-gate").classList.add("hidden");
  document.getElementById("main-popup").classList.remove("hidden");

  // Update stats
  const stats = status.stats || {};
  document.getElementById("stat-today").textContent = stats.todaySignals || 0;
  document.getElementById("stat-total").textContent = stats.totalSignals || 0;

  // Total queued
  const caches = status.caches || {};
  const totalQueued = Object.values(caches).reduce((a, b) => a + b, 0);
  document.getElementById("stat-queued").textContent = totalQueued;

  // Status badge — reflect tracking pause
  const badge = document.getElementById("status-badge");
  const trackSwitch = document.getElementById("tracking-switch");
  const pauseTimer = document.getElementById("pause-timer");
  const pauseState = status.trackingPause || { paused: false };

  if (pauseState.paused) {
    badge.textContent = "Paused";
    badge.classList.add("inactive");
    trackSwitch.checked = false;
    // Show countdown
    if (pauseState.remainingMs) {
      pauseTimer.textContent = formatRemaining(pauseState.remainingMs);
    }
  } else {
    badge.textContent = "Active";
    badge.classList.remove("inactive");
    trackSwitch.checked = true;
    pauseTimer.textContent = "";
  }

  // Site toggles
  const toggleList = document.getElementById("site-toggles");
  toggleList.innerHTML = "";

  for (const domain of DOMAINS) {
    const enabled =
      status.siteToggles && status.siteToggles[domain.key] !== false;
    const count = caches[domain.key] || 0;

    const li = document.createElement("li");
    li.innerHTML = `
      <span class="site-name">${domain.label}</span>
      <span class="site-count">${count} cached</span>
      <label class="toggle">
        <input type="checkbox" data-domain="${domain.key}" ${enabled ? "checked" : ""}>
        <span class="slider"></span>
      </label>
    `;
    toggleList.appendChild(li);
  }

  // Cache list
  const cacheList = document.getElementById("cache-list");
  cacheList.innerHTML = "";
  for (const domain of DOMAINS) {
    const count = caches[domain.key] || 0;
    if (count > 0) {
      const li = document.createElement("li");
      li.innerHTML = `
        <span>${domain.label}</span>
        <span class="cache-count">${count} signals</span>
      `;
      cacheList.appendChild(li);
    }
  }

  if (cacheList.children.length === 0) {
    cacheList.innerHTML = '<li style="color:#7f8fa6">No cached signals yet</li>';
  }

  // Fetch and display backend stats
  refreshBackendStats();
}

function bindEvents() {
  // Consent checkbox enables the accept button
  const check = document.getElementById("consent-check");
  const accept = document.getElementById("consent-accept");

  check.addEventListener("change", () => {
    accept.disabled = !check.checked;
  });

  // Accept consent
  accept.addEventListener("click", async () => {
    await browser.runtime.sendMessage({ type: "spiritpool:grantConsent" });
    const status = await browser.runtime.sendMessage({
      type: "spiritpool:getStatus",
    });
    showMain(status);
  });

  // Flush Now button
  document.getElementById("btn-flush").addEventListener("click", async () => {
    const btn = document.getElementById("btn-flush");
    const statusEl = document.getElementById("flush-status");

    btn.disabled = true;
    btn.textContent = "Flushing...";
    statusEl.textContent = "";

    try {
      const result = await browser.runtime.sendMessage({
        type: "spiritpool:flushAll",
      });

      if (result?.ok) {
        statusEl.textContent = "✅ Flushed!";
        statusEl.style.color = "#44bd32";
      } else {
        statusEl.textContent = `⚠ ${result?.reason || "Unknown error"}`;
        statusEl.style.color = "#e84118";
      }
    } catch (err) {
      statusEl.textContent = `⚠ ${err.message}`;
      statusEl.style.color = "#e84118";
    }

    btn.disabled = false;
    btn.textContent = "⚡ Flush Now";

    // Refresh all stats after flush
    const status = await browser.runtime.sendMessage({
      type: "spiritpool:getStatus",
    });
    showMain(status);
  });

  // Burn button — clears all cached signals
  document.getElementById("btn-burn").addEventListener("click", async () => {
    const btn = document.getElementById("btn-burn");
    const statusEl = document.getElementById("flush-status");

    btn.disabled = true;
    btn.textContent = "Burning...";
    statusEl.textContent = "";

    try {
      for (const domain of DOMAINS) {
        await browser.runtime.sendMessage({
          type: "spiritpool:clearDomainCache",
          domain: domain.key,
        });
      }
      statusEl.textContent = "🔥 Cache burned!";
      statusEl.style.color = "#e84118";
    } catch (err) {
      statusEl.textContent = `⚠ ${err.message}`;
      statusEl.style.color = "#e84118";
    }

    btn.disabled = false;
    btn.textContent = "🔥 Burn";

    // Refresh stats after burn
    const status = await browser.runtime.sendMessage({
      type: "spiritpool:getStatus",
    });
    showMain(status);
  });

  // Site toggle changes (delegated)
  document
    .getElementById("site-toggles")
    .addEventListener("change", async (e) => {
      if (e.target.type === "checkbox" && e.target.dataset.domain) {
        await browser.runtime.sendMessage({
          type: "spiritpool:toggleSite",
          domain: e.target.dataset.domain,
          enabled: e.target.checked,
        });
      }
    });

  // Options button
  document.getElementById("btn-options").addEventListener("click", () => {
    browser.runtime.openOptionsPage();
  });

  // Revoke consent
  document.getElementById("btn-revoke").addEventListener("click", async () => {
    if (confirm("This will delete all collected data. Continue?")) {
      await browser.runtime.sendMessage({ type: "spiritpool:revokeConsent" });
      showConsent();
    }
  });

  // Tracking toggle
  document.getElementById("tracking-switch").addEventListener("change", async (e) => {
    const pausing = !e.target.checked;
    if (pausing) {
      await browser.runtime.sendMessage({ type: "spiritpool:pauseTracking" });
    } else {
      await browser.runtime.sendMessage({ type: "spiritpool:resumeTracking" });
    }
    // Refresh UI
    const status = await browser.runtime.sendMessage({ type: "spiritpool:getStatus" });
    showMain(status);
  });
}

/**
 * Fetch backend /stats and display in the popup.
 */
async function refreshBackendStats() {
  const container = document.getElementById("backend-stats-content");

  try {
    const result = await browser.runtime.sendMessage({
      type: "spiritpool:getBackendStats",
    });

    if (result?.ok && result.stats) {
      const s = result.stats;
      const sourceList = Object.entries(s.by_source || {})
        .map(([src, count]) => `<li>${src}: <strong>${count}</strong> jobs</li>`)
        .join("");

      container.innerHTML = `
        <div class="backend-grid">
          <div class="backend-stat">
            <span class="backend-value">${s.total_jobs}</span>
            <span class="backend-label">Jobs</span>
          </div>
          <div class="backend-stat">
            <span class="backend-value">${s.total_observations}</span>
            <span class="backend-label">Observations</span>
          </div>
          <div class="backend-stat">
            <span class="backend-value">${s.total_companies}</span>
            <span class="backend-label">Companies</span>
          </div>
          <div class="backend-stat">
            <span class="backend-value">${s.observations_last_24h}</span>
            <span class="backend-label">Last 24h</span>
          </div>
        </div>
        ${sourceList ? `<ul class="source-list">${sourceList}</ul>` : ""}
      `;
    } else {
      container.innerHTML = `<span class="backend-offline">⚠ Server offline${result?.reason ? ": " + result.reason : ""}</span>`;
    }
  } catch (err) {
    container.innerHTML = `<span class="backend-offline">⚠ Cannot reach server</span>`;
  }
}

/**
 * Format milliseconds remaining into "Xh Ym" human-readable string.
 */
function formatRemaining(ms) {
  const totalMin = Math.ceil(ms / 60000);
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  if (h > 0) return `resumes in ${h}h ${m}m`;
  return `resumes in ${m}m`;
}

/**
 * SpiritPool — Options Page Controller
 */

const DOMAINS = [
  {
    key: "indeed.com",
    label: "Indeed",
    url: "indeed.com",
    desc: "Job titles, salaries, posting dates, applicant counts, urgency badges",
  },
  {
    key: "linkedin.com",
    label: "LinkedIn Jobs",
    url: "linkedin.com/jobs",
    desc: "Job titles, salaries, applicant counts, Easy Apply flags, reposts",
  },
  {
    key: "glassdoor.com",
    label: "Glassdoor",
    url: "glassdoor.com",
    desc: "Job titles, salary estimates, company ratings",
  },
  {
    key: "google.com/maps",
    label: "Google Maps",
    url: "google.com/maps",
    desc: "Store ratings, review counts, popular times, closure flags, review snippets",
  },
  {
    key: "apply.starbucks.com",
    label: "Starbucks Careers",
    url: "apply.starbucks.com",
    desc: "Job titles, store locations, posting dates, job IDs",
  },
];

document.addEventListener("DOMContentLoaded", init);

async function init() {
  await renderConsentStatus();
  await renderSiteToggles();
  await renderCacheManagement();
  await renderDataLog();
  bindEvents();
}

// ── Consent ────────────────────────────────────────────────────────────────

async function renderConsentStatus() {
  const { consent } = await browser.storage.local.get("consent");
  const badge = document.getElementById("consent-badge");
  const dateEl = document.getElementById("consent-date");
  const btnGrant = document.getElementById("btn-grant");
  const btnRevoke = document.getElementById("btn-revoke");

  if (consent && consent.given) {
    badge.textContent = "Consent Granted";
    badge.className = "badge granted";
    dateEl.textContent = `Since ${new Date(consent.timestamp).toLocaleString()}`;
    btnGrant.style.display = "none";
    btnRevoke.style.display = "inline-block";
  } else {
    badge.textContent = "Not Granted";
    badge.className = "badge revoked";
    dateEl.textContent = consent?.timestamp
      ? `Revoked ${new Date(consent.timestamp).toLocaleString()}`
      : "";
    btnGrant.style.display = "inline-block";
    btnRevoke.style.display = "none";
  }
}

// ── Site Toggles ───────────────────────────────────────────────────────────

async function renderSiteToggles() {
  const { siteToggles } = await browser.storage.local.get("siteToggles");
  const container = document.getElementById("site-toggles");
  container.innerHTML = "";

  for (const domain of DOMAINS) {
    const enabled = siteToggles && siteToggles[domain.key] !== false;
    const row = document.createElement("div");
    row.className = "site-row";
    row.innerHTML = `
      <div class="site-info">
        <div class="site-name">${domain.label}</div>
        <div class="site-url">${domain.url}</div>
        <div class="site-desc">${domain.desc}</div>
      </div>
      <label class="toggle">
        <input type="checkbox" data-domain="${domain.key}" ${enabled ? "checked" : ""}>
        <span class="slider"></span>
      </label>
    `;
    container.appendChild(row);
  }
}

// ── Cache Management ───────────────────────────────────────────────────────

async function renderCacheManagement() {
  const container = document.getElementById("cache-management");
  container.innerHTML = "";

  for (const domain of DOMAINS) {
    const cache = await browser.runtime.sendMessage({
      type: "spiritpool:getDomainCache",
      domain: domain.key,
    });

    const count = cache ? cache.signals.length : 0;
    const lastUpdate = cache?.lastUpdate
      ? new Date(cache.lastUpdate).toLocaleString()
      : "Never";

    const row = document.createElement("div");
    row.className = "cache-row";
    row.innerHTML = `
      <span class="domain">${domain.label}</span>
      <span class="count">${count} signals</span>
      <span style="color:#7f8fa6; font-size:11px">Updated: ${lastUpdate}</span>
      <button data-domain="${domain.key}" class="btn-clear-domain">Clear</button>
    `;
    container.appendChild(row);
  }
}

// ── Data Log ───────────────────────────────────────────────────────────────

async function renderDataLog() {
  const logEl = document.getElementById("data-log");
  const allSignals = [];

  for (const domain of DOMAINS) {
    const cache = await browser.runtime.sendMessage({
      type: "spiritpool:getDomainCache",
      domain: domain.key,
    });
    if (cache && cache.signals.length > 0) {
      for (const s of cache.signals.slice(-20)) {
        allSignals.push(s);
      }
    }
  }

  // Sort by observedAt descending
  allSignals.sort(
    (a, b) => new Date(b.observedAt) - new Date(a.observedAt)
  );

  if (allSignals.length === 0) {
    logEl.textContent = "No signals collected yet.\nBrowse an allowlisted site to start collecting.";
    return;
  }

  // Show last 50 entries
  const entries = allSignals.slice(0, 50).map((s) => {
    const time = new Date(s.observedAt).toLocaleString();
    const parts = [
      `[${time}]`,
      `source: ${s.source}`,
      s.jobTitle ? `title: "${s.jobTitle}"` : null,
      s.company ? `company: ${s.company}` : null,
      s.location ? `location: ${s.location}` : null,
      s.salary ? `salary: $${s.salary.min}-$${s.salary.max}/${s.salary.period}` : null,
      s.rating ? `rating: ${s.rating}` : null,
    ].filter(Boolean);
    return parts.join(" | ");
  });

  logEl.textContent = entries.join("\n\n");
}

// ── Event Binding ──────────────────────────────────────────────────────────

function bindEvents() {
  // Grant consent
  document.getElementById("btn-grant").addEventListener("click", async () => {
    await browser.runtime.sendMessage({ type: "spiritpool:grantConsent" });
    await renderConsentStatus();
  });

  // Revoke consent
  document.getElementById("btn-revoke").addEventListener("click", async () => {
    if (
      confirm(
        "Revoking consent will delete ALL collected data. This cannot be undone. Continue?"
      )
    ) {
      await browser.runtime.sendMessage({ type: "spiritpool:revokeConsent" });
      await renderConsentStatus();
      await renderCacheManagement();
      await renderDataLog();
    }
  });

  // Site toggles (delegated)
  document
    .getElementById("site-toggles")
    .addEventListener("change", async (e) => {
      if (e.target.type === "checkbox" && e.target.dataset.domain) {
        await browser.runtime.sendMessage({
          type: "spiritpool:toggleSite",
          domain: e.target.dataset.domain,
          enabled: e.target.checked,
        });
        // Refresh cache display since disabling clears cache
        await renderCacheManagement();
        await renderDataLog();
      }
    });

  // Per-domain clear (delegated)
  document
    .getElementById("cache-management")
    .addEventListener("click", async (e) => {
      if (e.target.classList.contains("btn-clear-domain")) {
        const domain = e.target.dataset.domain;
        await browser.runtime.sendMessage({
          type: "spiritpool:clearDomainCache",
          domain,
        });
        await renderCacheManagement();
        await renderDataLog();
      }
    });

  // Clear all caches
  document
    .getElementById("btn-clear-all")
    .addEventListener("click", async () => {
      if (confirm("Clear all cached signals from all domains?")) {
        for (const domain of DOMAINS) {
          await browser.runtime.sendMessage({
            type: "spiritpool:clearDomainCache",
            domain: domain.key,
          });
        }
        await renderCacheManagement();
        await renderDataLog();
      }
    });

  // Export data
  document.getElementById("btn-export").addEventListener("click", async () => {
    const exportData = {};
    for (const domain of DOMAINS) {
      const cache = await browser.runtime.sendMessage({
        type: "spiritpool:getDomainCache",
        domain: domain.key,
      });
      exportData[domain.key] = cache;
    }

    const blob = new Blob([JSON.stringify(exportData, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `spiritpool-export-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  });
}

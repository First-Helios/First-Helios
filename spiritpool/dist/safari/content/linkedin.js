/**
 * SpiritPool — LinkedIn Content Script (TEST BUILD)
 *
 * Heavy diagnostic logging. No company filter (captures ALL jobs).
 * LinkedIn is an Ember SPA — content renders after DOMContentLoaded.
 *
 * Console filter: [SP/LI]
 */

(() => {
  const DOMAIN = "linkedin.com";
  const TAG = "[SP/LI]";

  console.log(`${TAG} === Content script injected on ${location.href} ===`);

  // ── Dedup ────────────────────────────────────────────────────────────

  const sentHashes = new Set();

  function djb2(str) {
    let hash = 5381;
    for (let i = 0; i < str.length; i++) {
      hash = ((hash << 5) + hash + str.charCodeAt(i)) | 0;
    }
    return hash;
  }

  // ── Send to background ───────────────────────────────────────────────

  async function sendSignal(signal) {
    try {
      const result = await browser.runtime.sendMessage({
        type: "spiritpool:signal",
        domain: DOMAIN,
        signal,
      });
      console.log(`${TAG} sendSignal result:`, result);
      return result?.ok || false;
    } catch (err) {
      console.error(`${TAG} sendSignal ERROR:`, err.message);
      return false;
    }
  }

  // ── Check extension state ────────────────────────────────────────────

  async function checkStatus() {
    try {
      const status = await browser.runtime.sendMessage({
        type: "spiritpool:getStatus",
      });
      console.log(`${TAG} Extension status:`, JSON.stringify(status, null, 2));
      if (!status.consent) {
        console.warn(
          `${TAG} ⚠ CONSENT NOT GRANTED — signals will be rejected. Click the SpiritPool icon and accept.`
        );
      }
      return status;
    } catch (err) {
      console.error(`${TAG} Cannot reach background script:`, err.message);
      return null;
    }
  }

  // ── DOM Probing — discover what LinkedIn actually rendered ────────────

  function probeDOM() {
    console.group(`${TAG} DOM Probe`);

    const probes = [
      { label: "data-job-id", sel: "[data-job-id]" },
      { label: "data-occludable-job-id", sel: "[data-occludable-job-id]" },
      { label: ".job-card-container", sel: ".job-card-container" },
      { label: ".jobs-search-results__list-item", sel: ".jobs-search-results__list-item" },
      { label: ".scaffold-layout__list-item", sel: ".scaffold-layout__list-item" },
      { label: ".scaffold-layout__list", sel: ".scaffold-layout__list" },
      { label: ".base-card", sel: ".base-card" },
      { label: ".base-search-card", sel: ".base-search-card" },
      { label: "article tags", sel: "article" },
      { label: "[role='listitem']", sel: "[role='listitem']" },
      { label: "[role='list']", sel: "[role='list']" },
      { label: "[class*='job']", sel: "[class*='job']" },
      { label: "[class*='Job']", sel: "[class*='Job']" },
      { label: "li.ember-view", sel: "li.ember-view" },
      { label: "div.ember-view", sel: "div.ember-view" },
      { label: "a[href*='/jobs/']", sel: "a[href*='/jobs/']" },
      { label: "a[href*='/jobs/view/']", sel: "a[href*='/jobs/view/']" },
      { label: "h1", sel: "h1" },
      { label: "h2", sel: "h2" },
      { label: "h3", sel: "h3" },
      { label: ".feed-shared-update-v2", sel: ".feed-shared-update-v2" },
      { label: ".occludable-update", sel: ".occludable-update" },
      { label: ".jobs-search__job-details", sel: ".jobs-search__job-details" },
      { label: ".jobs-unified-top-card", sel: ".jobs-unified-top-card" },
    ];

    for (const { label, sel } of probes) {
      try {
        const els = document.querySelectorAll(sel);
        if (els.length > 0) {
          const samples = Array.from(els)
            .slice(0, 2)
            .map((e) => ({
              tag: e.tagName,
              cls: e.className?.toString().slice(0, 80),
              txt: (e.textContent || "").trim().slice(0, 120),
            }));
          console.log(`  ✅ ${label}: ${els.length}`, samples);
        }
      } catch { /* skip */ }
    }

    const body = document.body?.textContent || "";
    const kws = ["job", "hiring", "apply", "salary", "applicant", "posted", "remote"];
    const hits = {};
    for (const k of kws) {
      const c = (body.match(new RegExp(k, "gi")) || []).length;
      if (c > 0) hits[k] = c;
    }
    console.log("  Keyword hits:", hits);
    console.log("  Body length:", body.length);
    console.groupEnd();
  }

  // ── Strategy 1: Structured card elements ─────────────────────────────

  function extractFromCards() {
    const cardSelectors = [
      "[data-job-id]",
      "[data-occludable-job-id]",
      ".job-card-container",
      ".jobs-search-results__list-item",
      ".scaffold-layout__list-item",
      ".base-card",
      ".base-search-card",
      "li.ember-view",
    ];

    for (const sel of cardSelectors) {
      try {
        const cards = document.querySelectorAll(sel);
        if (cards.length === 0) continue;

        console.log(`${TAG} Card selector "${sel}" → ${cards.length} candidates`);

        const signals = [];
        for (const card of cards) {
          const sig = parseCard(card);
          if (sig) {
            sig._sourceEl = card;
            signals.push(sig);
          }
        }

        if (signals.length > 0) {
          console.log(`${TAG} → ${signals.length} parsed signals from "${sel}"`);
          return signals;
        }
      } catch { /* skip */ }
    }
    return [];
  }

  function parseCard(card) {
    const text = (card.textContent || "").trim();
    if (text.length < 20 || text.length > 5000) return null;
    if (card.closest("nav, header, footer, #msg-overlay, .msg-overlay-list-bubble")) return null;

    const jobTitle = firstText(card, [
      "a strong",
      ".job-card-list__title",
      ".base-search-card__title",
      "h3 a",
      "h3",
    ]);

    const company = firstText(card, [
      ".job-card-container__primary-description",
      ".artdeco-entity-lockup__subtitle",
      ".base-search-card__subtitle",
      "h4 a",
      "h4",
    ]);

    const location =
      firstText(card, [
        ".job-card-container__metadata-item",
        ".artdeco-entity-lockup__caption",
        ".job-search-card__location",
      ]) || extractLocationFromText(text);

    let jobUrl = null;
    const link =
      card.querySelector('a[href*="/jobs/"], a[href*="/job/"]') ||
      card.querySelector("a[href]");
    if (link) jobUrl = link.href;

    let jobId =
      card.getAttribute("data-job-id") ||
      card.getAttribute("data-occludable-job-id") ||
      null;
    if (!jobId && jobUrl) {
      const m =
        jobUrl.match(/\/view\/(\d+)/) || jobUrl.match(/currentJobId=(\d+)/);
      if (m) jobId = m[1];
    }

    const timeEl = card.querySelector("time[datetime]");
    const postingDate = timeEl
      ? timeEl.getAttribute("datetime")
      : parseRelativeDate(
          firstText(card, ["time", "[class*='listed']", "[class*='posted']"])
        );

    const salaryText = firstText(card, [
      "[class*='salary']",
      "[class*='compensation']",
    ]);
    const salary = parseSalary(salaryText || extractSalaryFromText(text));

    const badges = [];
    if (text.includes("Easy Apply")) badges.push("Easy Apply");
    if (text.includes("Reposted")) badges.push("Reposted");
    if (text.includes("Promoted")) badges.push("Promoted");
    if (text.includes("Actively recruiting")) badges.push("Actively recruiting");

    const appMatch =
      text.match(/(\d[\d,]*)\+?\s*applicants?/i) ||
      text.match(/Be (?:among )?(?:the )?first\s+(\d+)/i);
    const applicantCount = appMatch
      ? parseInt(appMatch[1].replace(/,/g, ""), 10)
      : null;

    if (!jobTitle && !company) return null;

    return {
      source: DOMAIN,
      signalType: "listing",
      storeNum: null,
      company: company || "Unknown",
      jobTitle: jobTitle || "Unknown",
      location,
      salary,
      postingDate,
      applicantCount,
      badges,
      url: jobUrl || window.location.href,
      observedAt: new Date().toISOString(),
      jobId,
    };
  }

  // ── Strategy 2: Detail panel ─────────────────────────────────────────

  function extractFromDetailPanel() {
    const panelSels = [
      ".jobs-search__job-details",
      ".job-view-layout",
      ".jobs-details",
      ".jobs-unified-top-card",
      ".job-details-jobs-unified-top-card",
    ];

    let panel = null;
    for (const sel of panelSels) {
      panel = document.querySelector(sel);
      if (panel) break;
    }
    if (!panel) return null;

    const jobTitle = firstText(panel, [
      "h1",
      "h2.t-24",
      ".jobs-unified-top-card__job-title",
    ]);
    const company = firstText(panel, [
      ".jobs-unified-top-card__company-name a",
      ".job-details-jobs-unified-top-card__company-name a",
      ".jobs-unified-top-card__company-name",
    ]);

    if (!jobTitle && !company) return null;

    const location = firstText(panel, [
      ".jobs-unified-top-card__bullet",
      ".job-details-jobs-unified-top-card__bullet",
    ]);
    const applicantText = firstText(panel, [
      ".jobs-unified-top-card__applicant-count",
      "[class*='applicant-count']",
    ]);

    const badges = [];
    const pt = panel.textContent || "";
    if (pt.includes("Easy Apply")) badges.push("Easy Apply");
    if (pt.includes("Reposted")) badges.push("Reposted");

    const detail = {
      source: DOMAIN,
      signalType: "listing_detail",
      storeNum: null,
      company,
      jobTitle,
      location,
      salary: null,
      postingDate: null,
      applicantCount: applicantText
        ? parseInt(applicantText.replace(/\D/g, ""), 10) || null
        : null,
      badges,
      url: window.location.href,
      observedAt: new Date().toISOString(),
    };
    detail._sourceEl = panel;
    return detail;
  }

  // ── Strategy 3: All /jobs/view/ links (most resilient) ───────────────

  function extractFromJobLinks() {
    const links = document.querySelectorAll('a[href*="/jobs/view/"]');
    if (links.length === 0) return [];

    console.log(`${TAG} Found ${links.length} /jobs/view/ links`);

    const signals = [];
    const seenUrls = new Set();

    for (const link of links) {
      const href = link.href;
      if (!href || seenUrls.has(href)) continue;
      seenUrls.add(href);

      // Walk up to find a card-like container
      let container = link;
      for (let i = 0; i < 8; i++) {
        const p = container.parentElement;
        if (!p || p === document.body) break;
        const len = (p.textContent || "").trim().length;
        if (len > 80 && len < 3000) {
          container = p;
          break;
        }
        container = p;
      }

      if (container.closest("nav, header, footer")) continue;

      const text = (container.textContent || "").trim();

      const titleEl = link.querySelector("strong, span") || link;
      const jobTitle = titleEl.textContent.trim() || null;

      const company = findNearbyText(container, [
        "h4",
        "[class*='subtitle']",
        "[class*='company']",
      ]);

      const location =
        findNearbyText(container, [
          "[class*='location']",
          "[class*='caption']",
          "[class*='metadata']",
        ]) || extractLocationFromText(text);

      const idMatch = href.match(/\/jobs\/view\/(\d+)/);
      const jobId = idMatch ? idMatch[1] : null;

      const badges = [];
      if (text.includes("Easy Apply")) badges.push("Easy Apply");
      if (text.includes("Promoted")) badges.push("Promoted");
      if (text.includes("Reposted")) badges.push("Reposted");

      const appMatch = text.match(/(\d[\d,]*)\+?\s*applicants?/i);
      const applicantCount = appMatch
        ? parseInt(appMatch[1].replace(/,/g, ""), 10)
        : null;

      const timeEl = container.querySelector("time[datetime]");
      const postingDate = timeEl ? timeEl.getAttribute("datetime") : null;

      signals.push({
        source: DOMAIN,
        signalType: "listing",
        storeNum: null,
        company: company || null,
        jobTitle: jobTitle || null,
        location,
        salary: parseSalary(extractSalaryFromText(text)),
        postingDate,
        applicantCount,
        badges,
        url: href,
        observedAt: new Date().toISOString(),
        jobId,
        _sourceEl: container,
      });
    }

    return signals;
  }

  // ── Utility ──────────────────────────────────────────────────────────

  function firstText(root, selectors) {
    for (const sel of selectors) {
      try {
        const el = root.querySelector(sel);
        if (el) {
          const t = el.textContent.trim();
          if (t.length > 0 && t.length < 300) return t;
        }
      } catch { /* skip */ }
    }
    return null;
  }

  function findNearbyText(container, selectors) {
    for (const sel of selectors) {
      try {
        const el = container.querySelector(sel);
        if (el) {
          const t = el.textContent.trim();
          if (t.length > 0 && t.length < 200) return t;
        }
      } catch { /* skip */ }
    }
    return null;
  }

  function extractLocationFromText(text) {
    const m = text.match(/\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)*,\s*[A-Z]{2})\b/);
    if (m) return m[1];
    if (/\bRemote\b/i.test(text)) return "Remote";
    if (/\bHybrid\b/i.test(text)) return "Hybrid";
    return null;
  }

  function extractSalaryFromText(text) {
    const m = text.match(
      /\$[\d,]+(?:\.\d{1,2})?\s*[-–—\/to]+\s*\$[\d,]+(?:\.\d{1,2})?[^.]{0,20}/i
    );
    return m ? m[0] : null;
  }

  function parseSalary(text) {
    if (!text) return null;
    const rm = text.match(
      /\$\s*([\d,]+(?:\.\d{1,2})?)\s*[-–—to\/]+\s*\$\s*([\d,]+(?:\.\d{1,2})?)/i
    );
    if (rm) {
      const min = parseFloat(rm[1].replace(/,/g, ""));
      const max = parseFloat(rm[2].replace(/,/g, ""));
      const period =
        text.toLowerCase().includes("yr") ||
        text.toLowerCase().includes("year")
          ? "yearly"
          : "hourly";
      return { min, max, period };
    }
    return null;
  }

  function parseRelativeDate(text) {
    if (!text) return null;
    const lower = text.toLowerCase().trim();
    const now = new Date();
    const pats = [
      { re: /(\d+)\+?\s*minutes?\s*ago/i, fn: (n, d) => d.setMinutes(d.getMinutes() - n) },
      { re: /(\d+)\+?\s*hours?\s*ago/i, fn: (n, d) => d.setHours(d.getHours() - n) },
      { re: /(\d+)\+?\s*days?\s*ago/i, fn: (n, d) => d.setDate(d.getDate() - n) },
      { re: /(\d+)\+?\s*weeks?\s*ago/i, fn: (n, d) => d.setDate(d.getDate() - n * 7) },
      { re: /(\d+)\+?\s*months?\s*ago/i, fn: (n, d) => d.setMonth(d.getMonth() - n) },
    ];
    for (const { re, fn } of pats) {
      const m = lower.match(re);
      if (m) {
        const d = new Date(now);
        fn(parseInt(m[1], 10), d);
        return d.toISOString();
      }
    }
    return null;
  }

  // ── Main scan orchestrator ───────────────────────────────────────────

  let scanCount = 0;

  async function scan() {
    scanCount++;
    const scanId = scanCount;
    console.log(`${TAG} ─── Scan #${scanId} start: ${location.href} ───`);

    probeDOM();

    let allSignals = [];

    // Strategy 1: Structured cards
    const cardSigs = extractFromCards();
    console.log(`${TAG} Strategy 1 (cards): ${cardSigs.length}`);
    allSignals.push(...cardSigs);

    // Strategy 2: Detail panel
    const detail = extractFromDetailPanel();
    if (detail) {
      console.log(`${TAG} Strategy 2 (detail): ${detail.jobTitle}`);
      allSignals.push(detail);
    } else {
      console.log(`${TAG} Strategy 2 (detail): none`);
    }

    // Strategy 3: Job links
    const linkSigs = extractFromJobLinks();
    console.log(`${TAG} Strategy 3 (links): ${linkSigs.length}`);
    allSignals.push(...linkSigs);

    // Dedup — across strategies AND against previously sent signals
    const unique = [];
    let alreadySent = 0;
    let crossStrategyDup = 0;
    const thisScanKeys = new Set();

    for (const sig of allSignals) {
      const key = `${sig.jobTitle}|${sig.company}|${sig.url}`;
      const h = djb2(key);

      // Already sent to background in a prior scan cycle
      if (sentHashes.has(h)) {
        alreadySent++;
        continue;
      }

      // Duplicate within this scan (cross-strategy overlap)
      if (thisScanKeys.has(h)) {
        crossStrategyDup++;
        continue;
      }

      thisScanKeys.add(h);
      unique.push(sig);
    }

    // Mark all unique signals as sent
    for (const h of thisScanKeys) {
      sentHashes.add(h);
    }
    // Trim sentHashes if too large
    while (sentHashes.size > 2000) {
      sentHashes.delete(sentHashes.values().next().value);
    }

    console.log(
      `${TAG} Scan #${scanId} summary: ${allSignals.length} total, ` +
      `${unique.length} new, ${alreadySent} already sent, ` +
      `${crossStrategyDup} cross-strategy duplicates`
    );

    if (unique.length === 0) {
      if (scanId === 1) {
        console.warn(
          `${TAG} ⚠ No signals found on first scan. Try: https://www.linkedin.com/jobs/search/?keywords=starbucks`
        );
      } else {
        console.log(`${TAG} ℹ No new signals (page hasn't changed since last scan)`);
      }
      return;
    }

    let sentCount = 0;
    for (const sig of unique) {
      console.log(
        `${TAG} → Sending: "${sig.jobTitle}" @ ${sig.company} [${sig.location}]`
      );
      const el = sig._sourceEl;
      delete sig._sourceEl;  // don't send DOM refs to background
      if (await sendSignal(sig)) {
        sentCount++;
        if (typeof spiritpoolHighlight === "function" && el) spiritpoolHighlight(el);
      }
    }

    console.log(`${TAG} ✅ Sent ${sentCount}/${unique.length} new signals to cache`);
  }

  // ── SPA navigation detection ─────────────────────────────────────────

  let lastUrl = location.href;
  let scanTimer = null;

  function scheduleScan(delayMs = 2500) {
    clearTimeout(scanTimer);
    scanTimer = setTimeout(scan, delayMs);
  }

  for (const method of ["pushState", "replaceState"]) {
    const original = history[method];
    history[method] = function (...args) {
      original.apply(this, args);
      if (location.href !== lastUrl) {
        lastUrl = location.href;
        console.log(`${TAG} Nav: ${method} → ${location.href}`);
        scheduleScan();
      }
    };
  }

  window.addEventListener("popstate", () => {
    if (location.href !== lastUrl) {
      lastUrl = location.href;
      console.log(`${TAG} Nav: popstate → ${location.href}`);
      scheduleScan();
    }
  });

  const urlWatcher = new MutationObserver(() => {
    if (location.href !== lastUrl) {
      lastUrl = location.href;
      console.log(`${TAG} Nav: DOM mutation → ${location.href}`);
      scheduleScan();
    }
  });
  urlWatcher.observe(document.documentElement, {
    childList: true,
    subtree: true,
  });

  // ── Bootstrap ────────────────────────────────────────────────────────

  async function init() {
    console.log(`${TAG} Init — waiting 3s for Ember hydration...`);
    await checkStatus();
    await new Promise((r) => setTimeout(r, 3000));
    await scan();
    setInterval(scan, 15000);
    console.log(`${TAG} Ready. Re-scanning every 15s.`);
  }

  init();
})();

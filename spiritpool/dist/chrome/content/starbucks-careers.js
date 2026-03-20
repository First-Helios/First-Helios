/**
 * SpiritPool — Starbucks Careers Content Script
 *
 * Extracts job listings from apply.starbucks.com.
 * Supplements the server-side scraper with user-sourced observations.
 *
 * Observes: job title, store/location, posting date, job ID.
 * Ignores:  user application data.
 */

(() => {
  const DOMAIN = "apply.starbucks.com";
  const SCAN_INTERVAL_MS = 3000;

  let lastScanHash = "";

  /**
   * Parse job cards from the Starbucks careers search results page.
   */
  function parseJobCard(card) {
    // Title
    const titleEl =
      card.querySelector(".job-title, h3, h2") ||
      card.querySelector("a[href*='/job/']");
    const jobTitle = titleEl ? titleEl.textContent.trim() : null;

    // Location (usually "City, ST" format)
    const locationEl =
      card.querySelector(".job-location, .location") ||
      card.querySelector("span.city");
    const location = locationEl ? locationEl.textContent.trim() : null;

    // Store number (sometimes embedded in the listing)
    let storeNum = null;
    const storeMatch = card.textContent.match(/store\s*#?\s*(\d{4,5})/i);
    if (storeMatch) storeNum = storeMatch[1];

    // Posting date
    const dateEl = card.querySelector(".job-date, .posted-date, time");
    let postingDate = null;
    if (dateEl) {
      postingDate =
        dateEl.getAttribute("datetime") || dateEl.textContent.trim();
    }

    // Job ID / URL
    const linkEl = card.querySelector("a[href*='/job/']") || card.querySelector("a");
    const jobUrl = linkEl ? linkEl.href : null;
    let jobId = null;
    if (jobUrl) {
      const match = jobUrl.match(/\/job\/([^/?#]+)/);
      if (match) jobId = match[1];
    }

    // Category (barista, shift supervisor, etc.)
    const categoryEl = card.querySelector(".job-category, .category");
    const category = categoryEl ? categoryEl.textContent.trim() : null;

    return {
      source: DOMAIN,
      signalType: "listing",
      storeNum,
      company: "Starbucks",
      jobTitle,
      location,
      salary: null,
      postingDate,
      applicantCount: null,
      badges: [],
      url: jobUrl || window.location.href,
      observedAt: new Date().toISOString(),
      jobId,
      category,
    };
  }

  /**
   * Try to parse the detail view of a single job posting.
   */
  function parseDetailPage() {
    const container =
      document.querySelector(".job-detail, .job-description") ||
      document.querySelector("main");
    if (!container) return null;

    const titleEl = container.querySelector("h1, h2.job-title");
    const jobTitle = titleEl ? titleEl.textContent.trim() : null;
    if (!jobTitle) return null;

    const locationEl = container.querySelector(".job-location, .location");
    const location = locationEl ? locationEl.textContent.trim() : null;

    let storeNum = null;
    const storeMatch = container.textContent.match(/store\s*#?\s*(\d{4,5})/i);
    if (storeMatch) storeNum = storeMatch[1];

    // Extract job requirements/qualifications if visible
    const reqsEl = container.querySelector(
      ".job-requirements, .qualifications, [data-automation='jobDescription']"
    );
    const requirements = reqsEl ? reqsEl.textContent.trim().slice(0, 500) : null;

    let jobId = null;
    const urlMatch = window.location.href.match(/\/job\/([^/?#]+)/);
    if (urlMatch) jobId = urlMatch[1];

    return {
      source: DOMAIN,
      signalType: "listing_detail",
      storeNum,
      company: "Starbucks",
      jobTitle,
      location,
      salary: null,
      postingDate: null,
      applicantCount: null,
      badges: [],
      url: window.location.href,
      observedAt: new Date().toISOString(),
      jobId,
      requirements,
    };
  }

  async function scanPage() {
    // Try search results first
    const cards = document.querySelectorAll(
      ".job-card, .job-list-item, .search-result-item, " +
      "[data-automation='jobListing'], tr.job-row"
    );

    const hash = `list:${cards.length}:${location.href}`;
    if (hash === lastScanHash) return;
    lastScanHash = hash;

    let sent = 0;

    if (cards.length > 0) {
      for (const card of cards) {
        const signal = parseJobCard(card);
        if (signal && signal.jobTitle) {
          const result = await browser.runtime.sendMessage({
            type: "spiritpool:signal",
            domain: DOMAIN,
            signal,
          });
          if (result?.ok) {
            sent++;
            if (typeof spiritpoolHighlight === "function") spiritpoolHighlight(card);
          }
        }
      }
    } else {
      // Maybe we're on a detail page
      const detail = parseDetailPage();
      if (detail) {
        const result = await browser.runtime.sendMessage({
          type: "spiritpool:signal",
          domain: DOMAIN,
          signal: detail,
        });
        if (result?.ok) {
          sent++;
          const container = document.querySelector(".job-detail, .job-description") || document.querySelector("main");
          if (typeof spiritpoolHighlight === "function" && container) spiritpoolHighlight(container);
        }
      }
    }

    if (sent > 0) {
      console.log(`[SpiritPool/StarbucksCareers] Sent ${sent} signals`);
    }
  }

  // Lifecycle
  scanPage();
  setInterval(scanPage, SCAN_INTERVAL_MS);

  let lastUrl = location.href;
  new MutationObserver(() => {
    if (location.href !== lastUrl) {
      lastUrl = location.href;
      lastScanHash = "";
      setTimeout(scanPage, 1000);
    }
  }).observe(document.body, { childList: true, subtree: true });

  console.log("[SpiritPool/StarbucksCareers] Content script loaded.");
})();

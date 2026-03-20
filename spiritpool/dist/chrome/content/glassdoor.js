/**
 * SpiritPool — Glassdoor Content Script
 *
 * Extracts Starbucks job listings from Glassdoor job search and detail pages.
 *
 * Observes: job title, company, location, salary estimate, posting date,
 *           rating, review count.
 * Ignores:  user profile, applications, saved jobs.
 */

(() => {
  const DOMAIN = "glassdoor.com";
  const SCAN_INTERVAL_MS = 3000;
  const TARGET_COMPANIES = ["starbucks"];

  let lastScanHash = "";

  function isTargetCompany(name) {
    if (!name) return false;
    const lower = name.toLowerCase();
    return TARGET_COMPANIES.some((t) => lower.includes(t));
  }

  function parseJobCard(card) {
    // Title
    const titleEl =
      card.querySelector(".job-title, .jobTitle") ||
      card.querySelector("a[data-test='job-link']") ||
      card.querySelector("h2 a");
    const jobTitle = titleEl ? titleEl.textContent.trim() : null;

    // Company
    const companyEl =
      card.querySelector(".job-search-key-l2wjgv") ||
      card.querySelector("[data-test='emp-name']") ||
      card.querySelector(".employer-name");
    const company = companyEl ? companyEl.textContent.trim() : null;

    if (!isTargetCompany(company)) return null;

    // Location
    const locationEl =
      card.querySelector("[data-test='emp-location']") ||
      card.querySelector(".location, .job-search-key-iii2h0");
    const location = locationEl ? locationEl.textContent.trim() : null;

    // Salary estimate
    const salaryEl =
      card.querySelector("[data-test='detailSalary']") ||
      card.querySelector(".salary-estimate, .css-1xe2xww");
    const salaryText = salaryEl ? salaryEl.textContent.trim() : null;
    const salary = parseSalary(salaryText);

    // Rating
    const ratingEl = card.querySelector(".job-search-key-9l4hov, .ratingStar");
    const rating = ratingEl ? parseFloat(ratingEl.textContent) || null : null;

    // Job URL
    const linkEl = card.querySelector("a[href*='/job-listing/'], a[data-test='job-link']");
    const jobUrl = linkEl ? linkEl.href : null;

    // Posting age
    const dateEl = card.querySelector(".job-search-key-1m0hx0, .listing-age, [data-test='job-age']");
    const dateText = dateEl ? dateEl.textContent.trim() : null;
    const postingDate = parseRelativeDate(dateText);

    return {
      source: DOMAIN,
      signalType: "listing",
      storeNum: null,
      company,
      jobTitle,
      location,
      salary,
      postingDate,
      applicantCount: null,
      badges: [],
      rating,
      url: jobUrl || window.location.href,
      observedAt: new Date().toISOString(),
    };
  }

  async function scanPage() {
    const cards = document.querySelectorAll(
      ".react-job-listing, " +
      "[data-test='jobListing'], " +
      ".job-listing, " +
      "li.jl"
    );

    const hash = `${cards.length}:${location.href}`;
    if (hash === lastScanHash) return;
    lastScanHash = hash;

    let sent = 0;
    for (const card of cards) {
      const signal = parseJobCard(card);
      if (signal) {
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

    if (sent > 0) {
      console.log(`[SpiritPool/Glassdoor] Sent ${sent} signals`);
    }
  }

  function parseSalary(text) {
    if (!text) return null;
    const rangeMatch = text.match(
      /\$\s*([\d,]+(?:\.\d{0,2})?)[kK]?\s*[-–—to]+\s*\$\s*([\d,]+(?:\.\d{0,2})?)[kK]?/i
    );
    if (rangeMatch) {
      let min = parseFloat(rangeMatch[1].replace(/,/g, ""));
      let max = parseFloat(rangeMatch[2].replace(/,/g, ""));
      // Handle "$32K - $45K" notation
      if (text.toLowerCase().includes("k")) {
        if (min < 1000) min *= 1000;
        if (max < 1000) max *= 1000;
      }
      const period = min > 1000 ? "yearly" : "hourly";
      return { min, max, period };
    }
    return null;
  }

  function parseRelativeDate(text) {
    if (!text) return null;
    const lower = text.toLowerCase().trim();
    const now = new Date();
    const numMatch = lower.match(/(\d+)/);
    if (!numMatch) return null;
    const n = parseInt(numMatch[1], 10);
    const d = new Date(now);
    if (lower.includes("d")) d.setDate(d.getDate() - n);
    else if (lower.includes("h")) d.setHours(d.getHours() - n);
    else if (lower.includes("w")) d.setDate(d.getDate() - n * 7);
    else if (lower.includes("m") && !lower.includes("min")) d.setMonth(d.getMonth() - n);
    else return null;
    return d.toISOString();
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

  console.log("[SpiritPool/Glassdoor] Content script loaded.");
})();

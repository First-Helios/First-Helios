/**
 * SpiritPool — Indeed Content Script
 *
 * Extracts Starbucks (and other chain) job listings from Indeed
 * search results and detail pages.
 *
 * Observes: job title, company, location, salary, posting date,
 *           applicant count, urgency badges, job ID.
 * Ignores:  user resume, saved jobs, application history.
 */

(() => {
  const DOMAIN = "indeed.com";
  const SCAN_INTERVAL_MS = 3000; // re-scan for dynamically loaded results
  const TARGET_COMPANIES = ["starbucks"]; // extend for multi-chain

  let lastScanHash = "";

  /**
   * Determine if a listing matches our target companies.
   */
  function isTargetCompany(companyName) {
    if (!companyName) return false;
    const lower = companyName.toLowerCase();
    return TARGET_COMPANIES.some((t) => lower.includes(t));
  }

  /**
   * Parse a single job card from Indeed search results.
   * Indeed's DOM changes frequently — selectors are best-effort.
   */
  function parseJobCard(card) {
    // Job title
    const titleEl =
      card.querySelector("h2.jobTitle a") ||
      card.querySelector("h2.jobTitle span") ||
      card.querySelector('[data-testid="jobTitle"]') ||
      card.querySelector(".jobTitle");
    const jobTitle = titleEl ? titleEl.textContent.trim() : null;

    // Company name
    const companyEl =
      card.querySelector('[data-testid="company-name"]') ||
      card.querySelector(".companyName") ||
      card.querySelector(".company");
    const company = companyEl ? companyEl.textContent.trim() : null;

    // Skip non-target companies
    if (!isTargetCompany(company)) return null;

    // Location
    const locationEl =
      card.querySelector('[data-testid="text-location"]') ||
      card.querySelector(".companyLocation") ||
      card.querySelector(".location");
    const location = locationEl ? locationEl.textContent.trim() : null;

    // Salary
    const salaryEl =
      card.querySelector(".salary-snippet-container") ||
      card.querySelector('[data-testid="attribute_snippet_testid"]') ||
      card.querySelector(".salaryText");
    const salaryText = salaryEl ? salaryEl.textContent.trim() : null;
    const salary = salaryText ? parseSalary(salaryText) : null;

    // Posting date
    const dateEl =
      card.querySelector(".date") ||
      card.querySelector('[data-testid="myJobsStateDate"]') ||
      card.querySelector(".new") ||
      card.querySelector("span.css-qvloho");
    const dateText = dateEl ? dateEl.textContent.trim() : null;
    const postingDate = parseRelativeDate(dateText);

    // Job URL / ID
    const linkEl =
      card.querySelector("h2.jobTitle a") || card.querySelector("a.jcs-JobTitle");
    const jobUrl = linkEl ? linkEl.href : null;
    const jobId = extractJobId(jobUrl);

    // Badges (urgently hiring, etc.)
    const badges = [];
    const badgeEls = card.querySelectorAll(
      '.urgentlyHiring, [data-testid="urgentlyHiring"], .tapItem .badge'
    );
    badgeEls.forEach((el) => {
      const text = el.textContent.trim();
      if (text) badges.push(text);
    });

    // Applicant count (sometimes shown)
    let applicantCount = null;
    const metaEls = card.querySelectorAll(".metadata, .jobMetaDataGroup span");
    metaEls.forEach((el) => {
      const text = el.textContent;
      if (text && text.match(/\d+\+?\s*applicant/i)) {
        applicantCount = extractNumber(text);
      }
    });

    return buildSignal({
      source: DOMAIN,
      signalType: "listing",
      company,
      jobTitle,
      location,
      salary,
      postingDate,
      applicantCount,
      badges,
      url: jobUrl || window.location.href,
      extra: { jobId },
    });
  }

  /**
   * Scan the page for job cards and send signals.
   */
  async function scanPage() {
    const cards = document.querySelectorAll(
      ".jobsearch-ResultsList .result, " +
      ".jobsearch-ResultsList .job_seen_beacon, " +
      '[data-testid="slider_item"], ' +
      ".tapItem, " +
      ".resultContent"
    );

    if (cards.length === 0) return;

    // Simple dedup: hash of card count + first card text
    const hash = `${cards.length}:${cards[0]?.textContent?.slice(0, 50)}`;
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
      console.log(`[SpiritPool/Indeed] Sent ${sent} signals from ${cards.length} cards`);
    }
  }

  // ── Utility wrappers ────────────────────────────────────────────────────

  function parseSalary(text) {
    if (!text) return null;
    const rangeMatch = text.match(
      /\$\s*([\d,]+(?:\.\d{1,2})?)\s*[-–—to]+\s*\$\s*([\d,]+(?:\.\d{1,2})?)/i
    );
    const singleMatch = text.match(/\$\s*([\d,]+(?:\.\d{1,2})?)/);
    let min = null, max = null;
    if (rangeMatch) {
      min = parseFloat(rangeMatch[1].replace(/,/g, ""));
      max = parseFloat(rangeMatch[2].replace(/,/g, ""));
    } else if (singleMatch) {
      min = parseFloat(singleMatch[1].replace(/,/g, ""));
      max = min;
    } else {
      return null;
    }
    let period = "unknown";
    const lower = text.toLowerCase();
    if (lower.includes("hour") || lower.includes("/hr")) period = "hourly";
    else if (lower.includes("year") || lower.includes("/yr")) period = "yearly";
    else if (min < 200) period = "hourly";
    else if (min > 15000) period = "yearly";
    return { min, max, period };
  }

  function parseRelativeDate(text) {
    if (!text) return null;
    const lower = text.toLowerCase().trim();
    const now = new Date();
    if (lower === "just posted" || lower === "today" || lower.includes("just now")) {
      return now.toISOString();
    }
    const daysMatch = lower.match(/(\d+)\+?\s*days?\s*ago/);
    if (daysMatch) {
      const d = new Date(now);
      d.setDate(d.getDate() - parseInt(daysMatch[1], 10));
      return d.toISOString();
    }
    const hoursMatch = lower.match(/(\d+)\+?\s*hours?\s*ago/);
    if (hoursMatch) {
      const d = new Date(now);
      d.setHours(d.getHours() - parseInt(hoursMatch[1], 10));
      return d.toISOString();
    }
    return null;
  }

  function extractNumber(text) {
    if (!text) return null;
    const match = text.replace(/,/g, "").match(/(\d+)/);
    return match ? parseInt(match[1], 10) : null;
  }

  function extractJobId(url) {
    if (!url) return null;
    const match = url.match(/jk=([a-f0-9]+)/i) || url.match(/vjk=([a-f0-9]+)/i);
    return match ? match[1] : null;
  }

  function buildSignal(params) {
    return {
      source: params.source,
      signalType: params.signalType,
      storeNum: params.storeNum || null,
      company: params.company,
      jobTitle: params.jobTitle,
      location: params.location,
      salary: params.salary,
      postingDate: params.postingDate,
      applicantCount: params.applicantCount,
      badges: params.badges || [],
      url: params.url || window.location.href,
      observedAt: new Date().toISOString(),
      ...(params.extra || {}),
    };
  }

  // ── Lifecycle ─────────────────────────────────────────────────────────────

  // Initial scan
  scanPage();

  // Re-scan periodically for dynamic content / pagination
  setInterval(scanPage, SCAN_INTERVAL_MS);

  // Also scan on URL changes (Indeed uses client-side routing)
  let lastUrl = location.href;
  new MutationObserver(() => {
    if (location.href !== lastUrl) {
      lastUrl = location.href;
      lastScanHash = "";
      setTimeout(scanPage, 1000); // wait for DOM to update
    }
  }).observe(document.body, { childList: true, subtree: true });

  console.log("[SpiritPool/Indeed] Content script loaded.");
})();

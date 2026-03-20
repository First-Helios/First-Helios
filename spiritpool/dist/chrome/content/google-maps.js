/**
 * SpiritPool — Google Maps Content Script
 *
 * Extracts data from Starbucks store pages on Google Maps.
 *
 * Observes: store name, address, rating, review count, popular times,
 *           "temporarily closed" flag, recent review snippets.
 * Ignores:  user location history, saved places, directions.
 */

(() => {
  const DOMAIN = "google.com/maps";
  const SCAN_INTERVAL_MS = 4000;
  const TARGET_COMPANIES = ["starbucks"];

  let lastScanHash = "";

  function isTargetStore(name) {
    if (!name) return false;
    const lower = name.toLowerCase();
    return TARGET_COMPANIES.some((t) => lower.includes(t));
  }

  /**
   * Parse the currently open place/store panel on Google Maps.
   */
  function parsePlacePanel() {
    // Store name — usually the first h1 or prominent heading in the panel
    const nameEl =
      document.querySelector("h1.DUwDvf") ||
      document.querySelector('[data-attrid="title"] span') ||
      document.querySelector("h1.fontHeadlineLarge") ||
      document.querySelector("div.tAiQdd h1");
    const storeName = nameEl ? nameEl.textContent.trim() : null;

    if (!isTargetStore(storeName)) return null;

    // Address
    const addressEl =
      document.querySelector('[data-item-id="address"] .fontBodyMedium') ||
      document.querySelector('button[data-item-id="address"]') ||
      document.querySelector('[aria-label*="Address"]');
    const address = addressEl ? addressEl.textContent.trim() : null;

    // Rating
    const ratingEl =
      document.querySelector("div.F7nice span[aria-hidden='true']") ||
      document.querySelector("span.ceNzKf") ||
      document.querySelector(".fontDisplayLarge");
    const rating = ratingEl ? parseFloat(ratingEl.textContent) || null : null;

    // Review count
    const reviewCountEl =
      document.querySelector("div.F7nice span:last-child") ||
      document.querySelector('button[jsaction*="review"] span');
    let reviewCount = null;
    if (reviewCountEl) {
      const text = reviewCountEl.textContent.replace(/[(),]/g, "").trim();
      reviewCount = parseInt(text.replace(/,/g, ""), 10) || null;
    }

    // Temporarily closed
    const temporarilyClosed =
      document.body.textContent.includes("Temporarily closed") ||
      document.querySelector('[data-closed="true"]') !== null;

    // Popular times — extract if visible
    const popularTimes = parsePopularTimes();

    // Recent review snippets (staffing-related keywords)
    const reviewSnippets = parseReviewSnippets();

    // Open/closed status
    const statusEl =
      document.querySelector(".o0Svhf span span") ||
      document.querySelector('[data-item-id="oh"] .fontBodyMedium');
    const openStatus = statusEl ? statusEl.textContent.trim() : null;

    // Phone number (can help with store identification)
    const phoneEl = document.querySelector(
      'button[data-item-id^="phone"] .fontBodyMedium'
    );
    const phone = phoneEl ? phoneEl.textContent.trim() : null;

    return {
      source: DOMAIN,
      signalType: "store_info",
      storeNum: null, // Will need to resolve from address
      company: storeName,
      jobTitle: null,
      location: address,
      salary: null,
      postingDate: null,
      applicantCount: null,
      badges: temporarilyClosed ? ["Temporarily Closed"] : [],
      url: window.location.href,
      observedAt: new Date().toISOString(),
      rating,
      reviewCount,
      openStatus,
      phone,
      popularTimes,
      reviewSnippets,
    };
  }

  /**
   * Attempt to parse the "Popular times" bar chart on Google Maps.
   * Returns an object like { "Monday": [0, 10, 25, ...], ... } or null.
   */
  function parsePopularTimes() {
    const container = document.querySelector(".C7xf8b, .g2BVhd");
    if (!container) return null;

    try {
      const bars = container.querySelectorAll('[aria-label*="busy"]');
      if (bars.length === 0) return null;

      const times = [];
      bars.forEach((bar) => {
        const label = bar.getAttribute("aria-label") || "";
        times.push(label);
      });
      return times.length > 0 ? times : null;
    } catch {
      return null;
    }
  }

  /**
   * Extract recent review snippets that mention staffing-related keywords.
   */
  function parseReviewSnippets() {
    const KEYWORDS = [
      "understaffed", "short-staffed", "short staffed", "slow service",
      "long wait", "waiting forever", "no staff", "only one person",
      "closed early", "nobody working", "skeleton crew", "overwhelmed",
    ];

    const snippets = [];
    const reviewEls = document.querySelectorAll(
      ".MyEned .wiI7pd, .jftiEf .wiI7pd, .review-full-text"
    );

    reviewEls.forEach((el) => {
      const text = el.textContent.trim();
      const lower = text.toLowerCase();
      for (const kw of KEYWORDS) {
        if (lower.includes(kw)) {
          snippets.push({
            keyword: kw,
            excerpt: text.slice(0, 200),
          });
          break; // one match per review is enough
        }
      }
    });

    return snippets.length > 0 ? snippets : null;
  }

  async function scanPage() {
    const hash = `${location.href}:${document.querySelector("h1")?.textContent || ""}`;
    if (hash === lastScanHash) return;
    lastScanHash = hash;

    const signal = parsePlacePanel();
    if (signal) {
      const result = await browser.runtime.sendMessage({
        type: "spiritpool:signal",
        domain: DOMAIN,
        signal,
      });
      if (result?.ok) {
        console.log(`[SpiritPool/GoogleMaps] Sent store signal for "${signal.company}"`);
        // Highlight the place info panel
        const headingEl = document.querySelector("h1.DUwDvf, h1.fontHeadlineLarge, div.tAiQdd h1");
        const panel = (headingEl && headingEl.closest("div")) || document.querySelector(".m6QErb, .bJzME, .Io6YTe");
        if (typeof spiritpoolHighlight === "function" && panel) spiritpoolHighlight(panel);
      }
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
      setTimeout(scanPage, 1500);
    }
  }).observe(document.body, { childList: true, subtree: true });

  console.log("[SpiritPool/GoogleMaps] Content script loaded.");
})();

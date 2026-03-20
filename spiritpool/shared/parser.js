/**
 * SpiritPool — DOM Extraction Utilities
 *
 * Shared helpers used by content scripts to safely extract
 * structured data from page DOMs across job board sites.
 */

const Parser = {
  /**
   * Safely get text content from a CSS selector.
   * @param {Element} root - Parent element to search within
   * @param {string} selector - CSS selector
   * @param {string} fallback - Default if element not found
   * @returns {string}
   */
  text(root, selector, fallback = "") {
    const el = root.querySelector(selector);
    return el ? el.textContent.trim() : fallback;
  },

  /**
   * Safely get an attribute from a selected element.
   * @param {Element} root
   * @param {string} selector
   * @param {string} attr
   * @param {string} fallback
   * @returns {string}
   */
  attr(root, selector, attr, fallback = "") {
    const el = root.querySelector(selector);
    return el ? (el.getAttribute(attr) || fallback) : fallback;
  },

  /**
   * Get all elements matching a selector and map them.
   * @param {Element} root
   * @param {string} selector
   * @param {function} mapFn - (element, index) => any
   * @returns {Array}
   */
  all(root, selector, mapFn) {
    return Array.from(root.querySelectorAll(selector)).map(mapFn);
  },

  /**
   * Check if an element matching the selector exists.
   * @param {Element} root
   * @param {string} selector
   * @returns {boolean}
   */
  exists(root, selector) {
    return root.querySelector(selector) !== null;
  },

  /**
   * Extract a numeric value from text (e.g. "42 applicants" → 42).
   * @param {string} text
   * @returns {number|null}
   */
  extractNumber(text) {
    if (!text) return null;
    const match = text.replace(/,/g, "").match(/(\d+)/);
    return match ? parseInt(match[1], 10) : null;
  },

  /**
   * Extract salary range from text like "$15.50 - $18.00 an hour".
   * @param {string} text
   * @returns {{min: number, max: number, period: string}|null}
   */
  extractSalary(text) {
    if (!text) return null;

    // Match patterns like "$15 - $18", "$15.50/hr", "$32,000 - $45,000/year"
    const rangeMatch = text.match(
      /\$\s*([\d,]+(?:\.\d{1,2})?)\s*[-–—to]+\s*\$\s*([\d,]+(?:\.\d{1,2})?)/i
    );
    const singleMatch = text.match(/\$\s*([\d,]+(?:\.\d{1,2})?)/);

    let min = null,
      max = null;

    if (rangeMatch) {
      min = parseFloat(rangeMatch[1].replace(/,/g, ""));
      max = parseFloat(rangeMatch[2].replace(/,/g, ""));
    } else if (singleMatch) {
      min = parseFloat(singleMatch[1].replace(/,/g, ""));
      max = min;
    } else {
      return null;
    }

    // Guess period
    let period = "unknown";
    const lower = text.toLowerCase();
    if (lower.includes("hour") || lower.includes("/hr") || lower.includes("an hr")) {
      period = "hourly";
    } else if (lower.includes("year") || lower.includes("annual") || lower.includes("/yr")) {
      period = "yearly";
    } else if (lower.includes("month")) {
      period = "monthly";
    } else if (lower.includes("week")) {
      period = "weekly";
    } else if (min < 200) {
      period = "hourly"; // heuristic: small numbers are likely hourly
    } else if (min > 15000) {
      period = "yearly";
    }

    return { min, max, period };
  },

  /**
   * Extract a relative date string into an approximate ISO date.
   * Handles "3 days ago", "Just posted", "30+ days ago", "Today".
   * @param {string} text
   * @returns {string|null} ISO date string or null
   */
  parseRelativeDate(text) {
    if (!text) return null;
    const lower = text.toLowerCase().trim();
    const now = new Date();

    if (lower === "just posted" || lower === "today" || lower === "just now") {
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

    const weeksMatch = lower.match(/(\d+)\+?\s*weeks?\s*ago/);
    if (weeksMatch) {
      const d = new Date(now);
      d.setDate(d.getDate() - parseInt(weeksMatch[1], 10) * 7);
      return d.toISOString();
    }

    const monthsMatch = lower.match(/(\d+)\+?\s*months?\s*ago/);
    if (monthsMatch) {
      const d = new Date(now);
      d.setMonth(d.getMonth() - parseInt(monthsMatch[1], 10));
      return d.toISOString();
    }

    return null;
  },

  /**
   * Build a standardised signal object.
   * @param {object} params
   * @returns {object}
   */
  buildSignal({
    source,
    signalType,
    storeNum = null,
    company = null,
    jobTitle = null,
    location = null,
    salary = null,
    postingDate = null,
    applicantCount = null,
    badges = [],
    url = null,
    extra = {},
  }) {
    return {
      source,
      signalType,
      storeNum,
      company,
      jobTitle,
      location,
      salary,
      postingDate,
      applicantCount,
      badges,
      url: url || window.location.href,
      observedAt: new Date().toISOString(),
      ...extra,
    };
  },
};

if (typeof globalThis !== "undefined") {
  globalThis.SpiritPoolParser = Parser;
}

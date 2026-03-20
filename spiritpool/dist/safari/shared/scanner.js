/**
 * SpiritPool — Generic DOM Scanner
 *
 * Instead of hardcoded CSS selectors that break when sites change,
 * this module programmatically discovers job-related content by:
 *
 *  1. Walking the DOM tree from known anchor points
 *  2. Trying selectors from the external selectors.json config (ordered by priority)
 *  3. Falling back to text-pattern matching and structural heuristics
 *  4. Scoring candidate elements to pick the best match
 *
 * Used by all content scripts. Config is loaded once from selectors.json.
 */

const DOMScanner = (() => {
  // ── Config Loading ──────────────────────────────────────────────────────

  let _config = null;
  let _configPromise = null;

  /**
   * Load selectors.json config. Cached after first load.
   * @returns {Promise<object>}
   */
  async function loadConfig() {
    if (_config) return _config;
    if (_configPromise) return _configPromise;

    _configPromise = (async () => {
      try {
        const url = browser.runtime.getURL("shared/selectors.json");
        const resp = await fetch(url);
        _config = await resp.json();
        console.log("[SpiritPool/Scanner] Loaded selectors config v" + (_config._version || "?"));
        return _config;
      } catch (err) {
        console.warn("[SpiritPool/Scanner] Failed to load selectors.json, using empty config:", err);
        _config = {};
        return _config;
      }
    })();

    return _configPromise;
  }

  /**
   * Get site-specific config for a domain.
   * @param {string} domain
   * @returns {Promise<object>}
   */
  async function getSiteConfig(domain) {
    const cfg = await loadConfig();
    return cfg[domain] || {};
  }

  // ── Exclusion Filtering ─────────────────────────────────────────────────

  /**
   * Check if an element is inside an excluded container (nav, footer, ads, etc).
   * @param {Element} el
   * @param {object} exclusions - from config
   * @returns {boolean}
   */
  function isExcluded(el, exclusions) {
    if (!exclusions) return false;

    // Check if any ancestor matches exclusion selectors
    if (exclusions.containerSelectors) {
      for (const sel of exclusions.containerSelectors) {
        try {
          if (el.closest(sel)) return true;
        } catch { /* invalid selector */ }
      }
    }

    // Check class substrings on the element and its parents (up to 5 levels)
    if (exclusions.classSubstrings) {
      let node = el;
      for (let depth = 0; depth < 5 && node; depth++) {
        const cls = node.className;
        if (typeof cls === "string" && cls.length > 0) {
          const lower = cls.toLowerCase();
          for (const sub of exclusions.classSubstrings) {
            if (lower.includes(sub)) return true;
          }
        }
        node = node.parentElement;
      }
    }

    return false;
  }

  // ── Card Discovery ──────────────────────────────────────────────────────

  /**
   * Discover job card elements on the page.
   *
   * Strategy:
   *  1. Try each selector from config.cardDiscovery.selectors
   *  2. Filter out cards in excluded containers
   *  3. Filter by text length (too short = not a real card)
   *  4. If no config selectors match, fall back to heuristic discovery
   *
   * @param {object} siteConfig
   * @returns {Element[]}
   */
  function discoverCards(siteConfig) {
    const discovery = siteConfig.cardDiscovery || {};
    const exclusions = siteConfig.exclusions || {};
    const minLen = discovery.minCardTextLength || 20;
    const maxLen = discovery.maxCardTextLength || 5000;

    // Strategy 1: configured selectors
    if (discovery.selectors) {
      for (const sel of discovery.selectors) {
        try {
          const candidates = document.querySelectorAll(sel);
          if (candidates.length > 0) {
            const filtered = Array.from(candidates).filter((el) => {
              if (isExcluded(el, exclusions)) return false;
              const textLen = (el.textContent || "").trim().length;
              return textLen >= minLen && textLen <= maxLen;
            });
            if (filtered.length > 0) {
              console.log(
                `[SpiritPool/Scanner] Found ${filtered.length} cards via selector "${sel}"`
              );
              return filtered;
            }
          }
        } catch { /* invalid selector, skip */ }
      }
    }

    // Strategy 2: find list containers, then their children
    if (discovery.listContainerSelectors) {
      for (const sel of discovery.listContainerSelectors) {
        try {
          const container = document.querySelector(sel);
          if (container) {
            const children = Array.from(container.children).filter((el) => {
              if (isExcluded(el, exclusions)) return false;
              const textLen = (el.textContent || "").trim().length;
              return textLen >= minLen && textLen <= maxLen;
            });
            if (children.length >= 2) {
              console.log(
                `[SpiritPool/Scanner] Found ${children.length} cards as children of "${sel}"`
              );
              return children;
            }
          }
        } catch { /* skip */ }
      }
    }

    // Strategy 3: heuristic — find repeated sibling elements with similar structure
    return discoverCardsHeuristic(exclusions, minLen, maxLen);
  }

  /**
   * Heuristic card discovery: look for clusters of sibling elements
   * that share the same tag+class signature and contain link elements.
   */
  function discoverCardsHeuristic(exclusions, minLen, maxLen) {
    // Find all <li> and <div> elements that contain at least one <a>
    const candidates = document.querySelectorAll("li, div, article, section");
    const signatureMap = new Map(); // signature → [elements]

    for (const el of candidates) {
      if (isExcluded(el, exclusions)) continue;
      const textLen = (el.textContent || "").trim().length;
      if (textLen < minLen || textLen > maxLen) continue;
      if (!el.querySelector("a")) continue;

      // Signature = tag + sorted class list (first 3 classes)
      const classes = Array.from(el.classList).slice(0, 3).sort().join(",");
      const sig = `${el.tagName}:${classes}`;

      if (!signatureMap.has(sig)) signatureMap.set(sig, []);
      signatureMap.get(sig).push(el);
    }

    // Find the largest cluster of siblings with matching signatures
    let bestCluster = [];
    for (const [sig, elements] of signatureMap) {
      if (elements.length > bestCluster.length && elements.length >= 3) {
        // Check they share a common parent (or close ancestor)
        const parent = elements[0].parentElement;
        const siblings = elements.filter((el) => el.parentElement === parent);
        if (siblings.length > bestCluster.length) {
          bestCluster = siblings;
        }
      }
    }

    if (bestCluster.length > 0) {
      console.log(
        `[SpiritPool/Scanner] Heuristic found ${bestCluster.length} card candidates`
      );
    }

    return bestCluster;
  }

  // ── Field Extraction ────────────────────────────────────────────────────

  /**
   * Extract a text field from an element using the config's extraction rules.
   *
   * Priority:
   *  1. CSS selectors (tried in order)
   *  2. ARIA labels
   *  3. Heading level match
   *  4. Text pattern regex search on the card's full text
   *
   * @param {Element} card
   * @param {object} fieldConfig - e.g. config.fieldExtraction.jobTitle
   * @param {string} fieldName - for logging
   * @returns {{value: string|null, el: Element|null, method: string}}
   */
  function extractField(card, fieldConfig, fieldName) {
    if (!fieldConfig) return { value: null, el: null, method: "none" };

    // 1. CSS selectors
    if (fieldConfig.selectors) {
      for (const sel of fieldConfig.selectors) {
        try {
          const el = card.querySelector(sel);
          if (el) {
            const text = el.textContent.trim();
            if (text.length > 0) {
              return { value: text, el, method: `selector:${sel}` };
            }
          }
        } catch { /* skip invalid */ }
      }
    }

    // 2. ARIA labels — find elements whose aria-label contains keywords
    if (fieldConfig.ariaLabels) {
      for (const label of fieldConfig.ariaLabels) {
        const el = card.querySelector(`[aria-label*="${label}" i]`);
        if (el) {
          const text = el.textContent.trim() || el.getAttribute("aria-label");
          if (text && text.length > 0) {
            return { value: text, el, method: `aria:${label}` };
          }
        }
      }
    }

    // 3. Heading level
    if (fieldConfig.headingLevel) {
      for (const lvl of fieldConfig.headingLevel) {
        const headings = card.querySelectorAll(`h${lvl}`);
        for (const h of headings) {
          const text = h.textContent.trim();
          if (text.length > 2 && text.length < 200) {
            return { value: text, el: h, method: `heading:h${lvl}` };
          }
        }
      }
    }

    // 4. Attribute extraction (e.g. datetime from <time>)
    if (fieldConfig.attributes) {
      for (const sel of fieldConfig.selectors || []) {
        try {
          const el = card.querySelector(sel);
          if (el) {
            for (const attr of fieldConfig.attributes) {
              const val = el.getAttribute(attr);
              if (val) {
                return { value: val, el, method: `attr:${attr}` };
              }
            }
          }
        } catch { /* skip */ }
      }
    }

    // 5. Text pattern search on the card's full text content
    if (fieldConfig.textPatterns) {
      const cardText = card.textContent || "";
      for (const pat of fieldConfig.textPatterns) {
        try {
          const regex = new RegExp(pat, "i");
          const match = cardText.match(regex);
          if (match) {
            return {
              value: match[1] || match[0],
              el: null,
              method: `textPattern:${pat.slice(0, 30)}`,
            };
          }
        } catch { /* bad regex */ }
      }
    }

    return { value: null, el: null, method: "not_found" };
  }

  /**
   * Extract all known fields from a card element.
   *
   * @param {Element} card
   * @param {object} fieldConfigs - config.fieldExtraction
   * @returns {object} - { fieldName: { value, method }, ... }
   */
  function extractAllFields(card, fieldConfigs) {
    const result = {};
    for (const [fieldName, fieldConfig] of Object.entries(fieldConfigs)) {
      result[fieldName] = extractField(card, fieldConfig, fieldName);
    }
    return result;
  }

  // ── Badge / Text Marker Scanning ────────────────────────────────────────

  /**
   * Scan a card for text markers (badges like "Easy Apply", "Reposted", etc.)
   *
   * @param {Element} card
   * @param {object} badgeConfig - config.fieldExtraction.badges
   * @returns {string[]}
   */
  function extractBadges(card, badgeConfig) {
    if (!badgeConfig) return [];
    const badges = [];
    const cardText = card.textContent || "";

    // Check text markers in the card's full text
    if (badgeConfig.textMarkers) {
      for (const marker of badgeConfig.textMarkers) {
        if (cardText.includes(marker)) {
          badges.push(marker);
        }
      }
    }

    // Also check specific badge elements
    if (badgeConfig.selectors) {
      for (const sel of badgeConfig.selectors) {
        try {
          const els = card.querySelectorAll(sel);
          els.forEach((el) => {
            const text = el.textContent.trim();
            if (text && text.length < 50 && !badges.includes(text)) {
              badges.push(text);
            }
          });
        } catch { /* skip */ }
      }
    }

    return badges;
  }

  // ── Numeric / Salary / Date Extraction ──────────────────────────────────

  /**
   * Parse a salary from extracted text.
   */
  function parseSalary(text) {
    if (!text) return null;

    const rangeMatch = text.match(
      /\$\s*([\d,]+(?:\.\d{1,2})?)\s*[-–—to\/]+\s*\$\s*([\d,]+(?:\.\d{1,2})?)/i
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

    // Handle "$32K" notation
    if (text.toLowerCase().includes("k")) {
      if (min < 1000) min *= 1000;
      if (max < 1000) max *= 1000;
    }

    let period = "unknown";
    const lower = text.toLowerCase();
    if (lower.includes("hour") || lower.includes("/hr") || lower.includes("an hr")) {
      period = "hourly";
    } else if (lower.includes("year") || lower.includes("/yr") || lower.includes("annual")) {
      period = "yearly";
    } else if (lower.includes("month")) {
      period = "monthly";
    } else if (lower.includes("week")) {
      period = "weekly";
    } else if (min < 200) {
      period = "hourly";
    } else if (min > 15000) {
      period = "yearly";
    }

    return { min, max, period };
  }

  /**
   * Parse a relative date string into an ISO timestamp.
   */
  function parseRelativeDate(text) {
    if (!text) return null;
    const lower = text.toLowerCase().trim();
    const now = new Date();

    if (lower.includes("just") || lower === "today" || lower === "now") {
      return now.toISOString();
    }

    if (lower === "reposted") {
      return null; // not a date, but a badge
    }

    // "3 days ago", "1 hour ago", "2 weeks ago", "30+ days ago"
    const unitPatterns = [
      { regex: /(\d+)\+?\s*minutes?\s*ago/i, unit: "minutes" },
      { regex: /(\d+)\+?\s*hours?\s*ago/i, unit: "hours" },
      { regex: /(\d+)\+?\s*days?\s*ago/i, unit: "days" },
      { regex: /(\d+)\+?\s*weeks?\s*ago/i, unit: "weeks" },
      { regex: /(\d+)\+?\s*months?\s*ago/i, unit: "months" },
    ];

    for (const { regex, unit } of unitPatterns) {
      const m = lower.match(regex);
      if (m) {
        const n = parseInt(m[1], 10);
        const d = new Date(now);
        switch (unit) {
          case "minutes": d.setMinutes(d.getMinutes() - n); break;
          case "hours": d.setHours(d.getHours() - n); break;
          case "days": d.setDate(d.getDate() - n); break;
          case "weeks": d.setDate(d.getDate() - n * 7); break;
          case "months": d.setMonth(d.getMonth() - n); break;
        }
        return d.toISOString();
      }
    }

    // Short format: "3d", "1w", "2h" (Glassdoor style)
    const shortMatch = lower.match(/^(\d+)([dhwm])$/);
    if (shortMatch) {
      const n = parseInt(shortMatch[1], 10);
      const d = new Date(now);
      switch (shortMatch[2]) {
        case "d": d.setDate(d.getDate() - n); break;
        case "h": d.setHours(d.getHours() - n); break;
        case "w": d.setDate(d.getDate() - n * 7); break;
        case "m": d.setMonth(d.getMonth() - n); break;
      }
      return d.toISOString();
    }

    // If it looks like an ISO date already, return it
    if (/^\d{4}-\d{2}-\d{2}/.test(text.trim())) {
      return text.trim();
    }

    return null;
  }

  /**
   * Extract a number from text.
   */
  function extractNumber(text) {
    if (!text) return null;
    const match = text.replace(/,/g, "").match(/(\d+)/);
    return match ? parseInt(match[1], 10) : null;
  }

  // ── Full Card → Signal Conversion ───────────────────────────────────────

  /**
   * Convert a card element into a structured signal using the site config.
   *
   * @param {Element} card
   * @param {object} siteConfig
   * @param {string} domain
   * @returns {object|null} - null if card doesn't match target companies
   */
  function cardToSignal(card, siteConfig, domain) {
    const fields = siteConfig.fieldExtraction || {};
    const extracted = extractAllFields(card, fields);

    // Check target company filter
    const companyText = extracted.company?.value || "";
    const targets = siteConfig.targetCompanies || [];

    if (targets.length > 0) {
      const companyLower = companyText.toLowerCase();
      const match = targets.some((t) => companyLower.includes(t));
      if (!match) return null;
    }

    // Build the signal
    const badges = extractBadges(card, fields.badges);

    // Extract job URL from the card's first relevant link
    let jobUrl = null;
    const linkEl = card.querySelector(
      'a[href*="/job"], a[href*="/jobs/"], a[href*="jk="], a[href*="/job-listing/"]'
    );
    if (linkEl) jobUrl = linkEl.href;

    // Extract job ID from URL or data attributes
    let jobId =
      card.getAttribute("data-job-id") ||
      card.getAttribute("data-occludable-job-id") ||
      card.getAttribute("data-jk") ||
      null;
    if (!jobId && jobUrl) {
      const idMatch =
        jobUrl.match(/\/view\/(\d+)/) ||
        jobUrl.match(/currentJobId=(\d+)/) ||
        jobUrl.match(/jk=([a-f0-9]+)/i) ||
        jobUrl.match(/\/job-listing\/[^/]*-(\d+)/);
      if (idMatch) jobId = idMatch[1];
    }

    const salaryText = extracted.salary?.value;
    const dateText = extracted.postingDate?.value;
    const applicantText = extracted.applicantCount?.value;

    const signal = {
      source: domain,
      signalType: "listing",
      storeNum: null,
      company: companyText || null,
      jobTitle: extracted.jobTitle?.value || null,
      location: extracted.location?.value || null,
      salary: parseSalary(salaryText),
      postingDate: parseRelativeDate(dateText) || dateText,
      applicantCount: extractNumber(applicantText),
      badges,
      url: jobUrl || window.location.href,
      observedAt: new Date().toISOString(),
      jobId,
      _extractionMethods: Object.fromEntries(
        Object.entries(extracted).map(([k, v]) => [k, v.method])
      ),
    };

    return signal;
  }

  // ── Page-Wide Text Scan (Fallback) ──────────────────────────────────────

  /**
   * When no cards are found via selectors or heuristics, do a broad
   * text scan of the page for target company mentions and try to
   * extract minimal signal from surrounding context.
   *
   * This catches edge cases like:
   *  - Feed posts about hiring
   *  - Single-job detail pages without a card list
   *  - Redesigned layouts where card structure changed
   *
   * @param {object} siteConfig
   * @param {string} domain
   * @returns {object[]} - array of signals
   */
  function textScanFallback(siteConfig, domain) {
    const targets = siteConfig.targetCompanies || [];
    if (targets.length === 0) return [];

    const signals = [];

    // Build a regex that matches any target company name
    const targetRegex = new RegExp(
      targets.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|"),
      "gi"
    );

    // Walk all text nodes looking for target mentions
    const walker = document.createTreeWalker(
      document.body,
      NodeFilter.SHOW_TEXT,
      {
        acceptNode(node) {
          // Skip script/style/hidden elements
          const parent = node.parentElement;
          if (!parent) return NodeFilter.FILTER_REJECT;
          const tag = parent.tagName;
          if (tag === "SCRIPT" || tag === "STYLE" || tag === "NOSCRIPT") {
            return NodeFilter.FILTER_REJECT;
          }
          if (parent.offsetParent === null && tag !== "BODY") {
            return NodeFilter.FILTER_REJECT; // hidden
          }
          return targetRegex.test(node.textContent)
            ? NodeFilter.FILTER_ACCEPT
            : NodeFilter.FILTER_REJECT;
        },
      }
    );

    const seen = new Set();
    let node;
    while ((node = walker.nextNode())) {
      // Walk up to find the nearest meaningful container
      let container = node.parentElement;
      for (let i = 0; i < 8 && container; i++) {
        const textLen = (container.textContent || "").length;
        if (textLen >= 50 && textLen <= 2000) break;
        container = container.parentElement;
      }

      if (!container) continue;

      // Dedup by container element
      if (seen.has(container)) continue;
      seen.add(container);

      // Try to extract fields from this container context
      const fields = siteConfig.fieldExtraction || {};
      const extracted = extractAllFields(container, fields);

      const companyText = extracted.company?.value || "";
      const companyLower = companyText.toLowerCase();
      const isTarget = targets.some((t) => companyLower.includes(t));

      // If we couldn't extract a company field but we know the text
      // contained a target name, attribute it anyway
      const resolvedCompany = isTarget
        ? companyText
        : targets.find((t) =>
            container.textContent.toLowerCase().includes(t)
          ) || null;

      if (!resolvedCompany) continue;

      const signal = {
        source: domain,
        signalType: "mention",
        storeNum: null,
        company: resolvedCompany,
        jobTitle: extracted.jobTitle?.value || null,
        location: extracted.location?.value || null,
        salary: parseSalary(extracted.salary?.value),
        postingDate: null,
        applicantCount: null,
        badges: [],
        url: window.location.href,
        observedAt: new Date().toISOString(),
        excerpt: container.textContent.trim().slice(0, 300),
        _extractionMethods: { fallback: "textScan" },
      };

      signals.push(signal);
    }

    return signals;
  }

  // ── Detail Panel Extraction ─────────────────────────────────────────────

  /**
   * Extract data from a detail/focus panel (e.g. LinkedIn's right-side panel).
   *
   * @param {object} siteConfig
   * @param {string} domain
   * @returns {object|null}
   */
  function extractDetailPanel(siteConfig, domain) {
    const panelConfig = siteConfig.detailPanel;
    if (!panelConfig) return null;

    // Find the panel container
    let panel = null;
    for (const sel of panelConfig.containerSelectors || []) {
      try {
        panel = document.querySelector(sel);
        if (panel) break;
      } catch { /* skip */ }
    }
    if (!panel) return null;

    // Extract fields using panel-specific selectors
    const extractFromList = (selectors) => {
      if (!selectors) return null;
      for (const sel of selectors) {
        try {
          const el = panel.querySelector(sel);
          if (el) {
            const text = el.textContent.trim();
            if (text.length > 0) return text;
          }
        } catch { /* skip */ }
      }
      return null;
    };

    const jobTitle = extractFromList(panelConfig.titleSelectors);
    const company = extractFromList(panelConfig.companySelectors);
    const location = extractFromList(panelConfig.locationSelectors);
    const applicantText = extractFromList(panelConfig.applicantSelectors);

    // Check target company filter
    const targets = siteConfig.targetCompanies || [];
    if (targets.length > 0 && company) {
      const companyLower = company.toLowerCase();
      if (!targets.some((t) => companyLower.includes(t))) return null;
    }

    if (!jobTitle && !company) return null;

    // Look for badges in the panel text
    const fields = siteConfig.fieldExtraction || {};
    const badges = extractBadges(panel, fields.badges);

    return {
      source: domain,
      signalType: "listing_detail",
      storeNum: null,
      company,
      jobTitle,
      location,
      salary: null,
      postingDate: null,
      applicantCount: extractNumber(applicantText),
      badges,
      url: window.location.href,
      observedAt: new Date().toISOString(),
    };
  }

  // ── Debug / Diagnostics ─────────────────────────────────────────────────

  /**
   * Run a full diagnostic scan and log what was found (for debugging).
   * Call from the browser console: SpiritPoolScanner.diagnose("linkedin.com")
   */
  async function diagnose(domain) {
    const cfg = await getSiteConfig(domain);
    console.group(`[SpiritPool/Scanner] Diagnostic for ${domain}`);

    // Card discovery
    const cards = discoverCards(cfg);
    console.log(`Cards found: ${cards.length}`);

    if (cards.length > 0) {
      const sample = cards[0];
      console.log("Sample card tag:", sample.tagName);
      console.log("Sample card classes:", sample.className);
      console.log("Sample card text:", sample.textContent.trim().slice(0, 200));

      const fields = extractAllFields(sample, cfg.fieldExtraction || {});
      console.log("Extracted fields:", fields);

      const badges = extractBadges(sample, cfg.fieldExtraction?.badges);
      console.log("Badges:", badges);

      const signal = cardToSignal(sample, cfg, domain);
      console.log("Signal:", signal);
    }

    // Detail panel
    const detail = extractDetailPanel(cfg, domain);
    console.log("Detail panel:", detail);

    // Text fallback
    const fallback = textScanFallback(cfg, domain);
    console.log("Text scan fallback signals:", fallback.length);

    console.groupEnd();

    return { cards: cards.length, detail, fallbackSignals: fallback.length };
  }

  // ── Public API ──────────────────────────────────────────────────────────

  return {
    loadConfig,
    getSiteConfig,
    discoverCards,
    extractField,
    extractAllFields,
    extractBadges,
    cardToSignal,
    textScanFallback,
    extractDetailPanel,
    parseSalary,
    parseRelativeDate,
    extractNumber,
    isExcluded,
    diagnose,
  };
})();

// Expose globally for content scripts and console debugging
if (typeof globalThis !== "undefined") {
  globalThis.SpiritPoolScanner = DOMScanner;
}

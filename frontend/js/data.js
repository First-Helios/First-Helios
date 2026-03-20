/**
 * data.js — Chain Staffing Tracker
 * Handles all localStorage persistence for staffing reports,
 * and provides utilities to compute current staffing status per location.
 */

const Data = (() => {
  const STORAGE_KEY = 'cst_reports_v1';
  // Reports older than this many days are de-weighted (not deleted)
  const RECENT_DAYS = 7;
  // Threshold percentages for regional alerts
  const ALERT_CRITICAL_PCT = 0.25; // >= 25% critical  → critical alert
  const ALERT_LOW_PCT      = 0.40; // >= 40% low|critical → low alert

  /* ── Vacancy data (from scraper) ────────────────────────────── */

  // Raw payload from data/vacancies.json — set via setVacancyData()
  let _vacancyPayload  = null;
  // Map: osmLocationId (string) → store vacancy object from scraper
  let _vacancyByOsmId  = {};

  /**
   * Store the parsed vacancies.json payload.
   * @param {object} payload  — JSON from data/vacancies.json
   */
  function setVacancyData(payload) {
    _vacancyPayload = payload;
  }

  /**
   * Haversine distance in km between two lat/lng points.
   */
  function _haversineKm(lat1, lng1, lat2, lng2) {
    const R = 6371;
    const dLat = (lat2 - lat1) * Math.PI / 180;
    const dLng = (lng2 - lng1) * Math.PI / 180;
    const a =
      Math.sin(dLat / 2) ** 2 +
      Math.cos(lat1 * Math.PI / 180) *
      Math.cos(lat2 * Math.PI / 180) *
      Math.sin(dLng / 2) ** 2;
    return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  }

  /**
   * After OSM locations are loaded, match each to the nearest scraped
   * vacancy store (within MATCH_RADIUS_KM).  Populates _vacancyByOsmId.
   *
   * @param {Location[]} osmLocations — array of location objects from map.js
   */
  const MATCH_RADIUS_KM = 0.35; // ~350 m tolerance

  function buildVacancyIndex(osmLocations) {
    _vacancyByOsmId = {};
    if (!_vacancyPayload) return;

    const stores = Object.values(_vacancyPayload.stores || {});
    if (!stores.length) return;

    // Only consider stores with geocoded coordinates
    const geoStores = stores.filter(s => s.lat != null && s.lng != null);

    for (const loc of osmLocations) {
      if (loc.lat == null || loc.lng == null) continue;
      let best = null, bestDist = Infinity;
      for (const sv of geoStores) {
        const d = _haversineKm(loc.lat, loc.lng, sv.lat, sv.lng);
        if (d < bestDist) { bestDist = d; best = sv; }
      }
      if (best && bestDist <= MATCH_RADIUS_KM) {
        _vacancyByOsmId[loc.id] = best;
      }
    }
    console.log(
      `[Data] Vacancy index built: ${Object.keys(_vacancyByOsmId).length}` +
      ` of ${osmLocations.length} OSM locations matched to scraped data.`
    );
  }

  /**
   * Return the scraped vacancy info for an OSM location, or null.
   * @param {string} locationId
   * @returns {object|null}
   */
  function getVacancyInfo(locationId) {
    return _vacancyByOsmId[locationId] || null;
  }

  /**
   * True if any vacancy data has been loaded.
   */
  function hasVacancyData() {
    return _vacancyPayload !== null;
  }

  /* ── Internal helpers ───────────────────────────────────────── */

  function now() { return Date.now(); }

  function msPerDay() { return 1000 * 60 * 60 * 24; }

  function isRecent(report) {
    return (now() - report.timestamp) <= RECENT_DAYS * msPerDay();
  }

  /* ── Read / Write ───────────────────────────────────────────── */

  /**
   * Load ALL reports from localStorage.
   * @returns {Object} { [locationId]: Report[] }
   */
  function loadAll() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      return raw ? JSON.parse(raw) : {};
    } catch {
      return {};
    }
  }

  /**
   * Persist the full reports store back to localStorage.
   * Also prunes reports older than 30 days to keep storage tidy.
   */
  function saveAll(store) {
    const cutoff = now() - 30 * msPerDay();
    // Prune old entries
    for (const id of Object.keys(store)) {
      store[id] = store[id].filter(r => r.timestamp >= cutoff);
      if (store[id].length === 0) delete store[id];
    }
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(store));
    } catch (e) {
      console.warn('[Data] localStorage write failed:', e);
    }
  }

  /**
   * Add a new report for a location.
   * @param {string} locationId   — OSM node/way ID
   * @param {'adequate'|'low'|'critical'} level
   * @param {string}  comment
   * @param {boolean} isFormerStaff
   */
  function addReport(locationId, level, comment, isFormerStaff) {
    const store = loadAll();
    if (!store[locationId]) store[locationId] = [];
    /** @type {Report} */
    const report = {
      id:            crypto.randomUUID ? crypto.randomUUID() : String(now()),
      locationId,
      level,
      comment:       comment.trim(),
      isFormerStaff: Boolean(isFormerStaff),
      timestamp:     now(),
    };
    store[locationId].unshift(report); // newest first
    saveAll(store);
    return report;
  }

  /**
   * Get all reports for a single location, newest first.
   * @param {string} locationId
   * @returns {Report[]}
   */
  function getReports(locationId) {
    const store = loadAll();
    return (store[locationId] || []).sort((a, b) => b.timestamp - a.timestamp);
  }

  /* ── Status Computation ─────────────────────────────────────── */

  /**
   * Compute the effective staffing status for a single location
   * based on the most recent reports.
   *
   * Algorithm:
   *  - Use only reports from the last RECENT_DAYS days.
   *  - If no recent reports → 'unknown'.
   *  - Otherwise take the most common level among the 5 most recent reports
   *    (former-staff reports count double).
   *  - Tie-break towards the worse status.
   *
   * @param {string} locationId
   * @returns {'adequate'|'low'|'critical'|'unknown'}
   */
  function getStatus(locationId) {
    // ── 1. Community reports (highest priority) ──────────────────
    const all    = getReports(locationId);
    const recent = all.filter(isRecent);
    if (recent.length > 0) {
      const topN = recent.slice(0, 5);
      const weights = { adequate: 0, low: 0, critical: 0 };
      for (const r of topN) {
        const w = r.isFormerStaff ? 2 : 1;
        weights[r.level] = (weights[r.level] || 0) + w;
      }
      const order = ['critical', 'low', 'adequate'];
      let best = 'adequate', bestW = -1;
      for (const lvl of order) {
        if (weights[lvl] > bestW) { bestW = weights[lvl]; best = lvl; }
      }
      return best;
    }

    // ── 2. Scraped vacancy data (fallback) ───────────────────────
    const vacancy = _vacancyByOsmId[locationId];
    if (vacancy && vacancy.vacancy_level && vacancy.vacancy_level !== 'unknown') {
      return vacancy.vacancy_level;
    }

    return 'unknown';
  }

  /**
   * Get the most recent report object for a location (or null).
   * @param {string} locationId
   * @returns {Report|null}
   */
  function getLatestReport(locationId) {
    const reports = getReports(locationId);
    return reports.find(isRecent) || reports[0] || null;
  }

  /**
   * Count reports in the last RECENT_DAYS for a location.
   */
  function getRecentCount(locationId) {
    return getReports(locationId).filter(isRecent).length;
  }

  /* ── Regional Analytics ─────────────────────────────────────── */

  /**
   * Given an array of location IDs, compute regional staffing stats
   * and determine if any alert should be fired.
   *
   * @param {string[]} locationIds
   * @returns {{ total, adequate, low, critical, unknown, alertLevel: 'critical'|'low'|null }}
   */
  function getRegionalStats(locationIds) {
    const counts = { adequate: 0, low: 0, critical: 0, unknown: 0 };
    for (const id of locationIds) {
      counts[getStatus(id)]++;
    }
    const total = locationIds.length;
    let alertLevel = null;

    if (total > 0) {
      const critPct = counts.critical / total;
      const lowPct  = (counts.low + counts.critical) / total;

      if (critPct >= ALERT_CRITICAL_PCT)      alertLevel = 'critical';
      else if (lowPct >= ALERT_LOW_PCT)        alertLevel = 'low';
    }

    return { total, ...counts, alertLevel };
  }

  /* ── Utilities ──────────────────────────────────────────────── */

  /** Human-readable relative time ("2 h ago", "3 d ago"). */
  function relativeTime(timestamp) {
    const delta = now() - timestamp;
    const mins  = Math.floor(delta / 60000);
    if (mins <  1)  return 'just now';
    if (mins <  60) return `${mins} min ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs  <  24) return `${hrs} h ago`;
    const days = Math.floor(hrs / 24);
    return `${days} d ago`;
  }

  /* ── Cache system ────────────────────────────────────────────── */

  const CACHE_PREFIX = 'cst_cache_';
  const OSM_CACHE_TTL   = 24 * 60 * 60 * 1000; // 24 h
  const VAC_CACHE_TTL   =  1 * 60 * 60 * 1000; //  1 h

  /**
   * Write a value into localStorage with a TTL.
   * @param {string} key
   * @param {*}      value   — must be JSON-serialisable
   * @param {number} ttlMs   — milliseconds until the entry expires
   */
  function cacheSet(key, value, ttlMs) {
    try {
      const entry = { v: value, exp: Date.now() + ttlMs };
      localStorage.setItem(CACHE_PREFIX + key, JSON.stringify(entry));
    } catch (e) {
      console.warn('[Data] Cache write failed (quota?):', e.message);
    }
  }

  /**
   * Read a value from the cache.  Returns the value or null if missing/expired.
   */
  function cacheGet(key) {
    try {
      const raw = localStorage.getItem(CACHE_PREFIX + key);
      if (!raw) return null;
      const entry = JSON.parse(raw);
      if (entry.exp < Date.now()) {
        localStorage.removeItem(CACHE_PREFIX + key);
        return null;
      }
      return entry.v;
    } catch {
      return null;
    }
  }

  /**
   * Remove a specific cache entry.
   */
  function cacheDel(key) {
    localStorage.removeItem(CACHE_PREFIX + key);
  }

  /** Normalise a bbox into a stable cache key. */
  function _bboxKey(bbox) {
    return 'osm_' + bbox.map(n => n.toFixed(4)).join('_');
  }

  // ── OSM locations cache ──────────────────────────────────────

  function cacheOsmLocations(bbox, locations) {
    cacheSet(_bboxKey(bbox), locations, OSM_CACHE_TTL);
    console.log(`[Data] Cached ${locations.length} OSM locations (bbox ${_bboxKey(bbox)}).`);
  }

  function getCachedOsmLocations(bbox) {
    const cached = cacheGet(_bboxKey(bbox));
    if (cached) console.log(`[Data] OSM cache hit for bbox ${_bboxKey(bbox)}: ${cached.length} locations.`);
    return cached;
  }

  // ── Vacancy data cache ───────────────────────────────────────

  function cacheVacancyData(payload) {
    cacheSet('vacancies', payload, VAC_CACHE_TTL);
    console.log('[Data] Vacancy data cached.');
  }

  function getCachedVacancyData() {
    return cacheGet('vacancies');
  }

  function invalidateVacancyCache() {
    cacheDel('vacancies');
  }

  /* ── Public API ─────────────────────────────────────────────── */
  return {
    addReport,
    getReports,
    getStatus,
    getLatestReport,
    getRecentCount,
    getRegionalStats,
    relativeTime,
    RECENT_DAYS,
    // Vacancy data API
    setVacancyData,
    buildVacancyIndex,
    getVacancyInfo,
    hasVacancyData,
    // Cache API
    cacheOsmLocations,
    getCachedOsmLocations,
    cacheVacancyData,
    getCachedVacancyData,
    invalidateVacancyCache,
  };
})();

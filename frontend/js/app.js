/**
 * app.js — Chain Staffing Tracker
 * Top-level controller: wires Search, MapModule, UI, and Data together.
 */

// Expose selected methods globally so scan.js can call them
const App = {};

(function AppModule() {
  /* ── State ──────────────────────────────────────────────────── */
  let _currentLocations = []; // Location[] for the current region view

  /* ── Bootstrap ──────────────────────────────────────────────── */
  document.addEventListener('DOMContentLoaded', () => {
    // Initialise the map; pass the "open report modal" callback
    MapModule.init('map', loc => UI.openReportModal(loc));

    // Wire UI callbacks
    UI.onFocusLocation = locationId => MapModule.focusLocation(locationId);
    UI.onReportSubmit  = handleReportSubmit;

    // Wire search controls
    document.getElementById('search-btn').addEventListener('click', handleSearch);
    document.getElementById('region-search').addEventListener('keydown', e => {
      if (e.key === 'Enter') handleSearch();
    });
    document.getElementById('locate-btn').addEventListener('click', handleGeolocate);

    // Initialise scan panel (talks to Flask server; degrades gracefully)
    Scan.init();

    // Initialise trends drawer
    Trends.init();

    // Attempt to pre-load scraped vacancy data (non-blocking)
    loadVacancyData();
  });

  /**
   * Fetch the vacancy JSON produced by the Python scraper.
   * Silently ignored if the file doesn't exist yet.
   */
  async function loadVacancyData() {
    try {
      // Try localStorage cache first (1 h TTL)
      const cached = Data.getCachedVacancyData();
      if (cached) {
        Data.setVacancyData(cached);
        const n = Object.keys(cached.stores || {}).length;
        console.log(`[App] Vacancy data loaded from cache: ${n} stores.`);
        return;
      }

      const resp = await fetch('data/vacancies.json', { cache: 'no-cache' });
      if (!resp.ok) return; // file not generated yet — that's fine
      const payload = await resp.json();
      Data.setVacancyData(payload);
      Data.cacheVacancyData(payload);
      const storeCount = Object.keys(payload.stores || {}).length;
      console.log(`[App] Vacancy data loaded: ${storeCount} stores scraped.`);
      if (storeCount > 0) {
        UI.showToast('info',
          `Staffing data loaded for ${storeCount} scraped store${storeCount !== 1 ? 's' : ''}. ` +
          `Map will reflect open job listings.`);
      }
    } catch (e) {
      // vacancies.json not yet generated — fail silently
      console.debug('[App] No vacancy data available yet:', e.message);
    }
  }

  /* ================================================================
     SEARCH / LOAD
     ================================================================ */

  async function handleSearch() {
    const query = document.getElementById('region-search').value.trim();
    if (!query) return UI.showToast('info', 'Enter a city or region name first.');
    await loadRegion(query);
  }

  async function handleGeolocate() {
    if (!('geolocation' in navigator)) {
      return UI.showToast('error', 'Geolocation is not supported in your browser.');
    }
    UI.setStatus('loading', 'Locating…');
    navigator.geolocation.getCurrentPosition(
      async pos => {
        const { latitude: lat, longitude: lng } = pos.coords;
        // Build a ±0.25 degree bounding box around the user
        const delta = 0.25;
        const bbox  = [lat - delta, lng - delta, lat + delta, lng + delta];
        MapModule.fitBounds(bbox);
        Scan.setRegion(label || `${lat.toFixed(4)},${lng.toFixed(4)}`, 25);
        await loadBbox(bbox);
        // Reverse-geocode for the search box label (best-effort)
        try {
          const r = await fetch(
            `https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lng}&format=json`,
            { headers: { 'Accept-Language': 'en', 'User-Agent': 'ChainStaffingTracker/1.0' } }
          );
          const j = await r.json();
          const addr = j.address || {};
          const label = [addr.city || addr.town || addr.village, addr.state || addr.country]
            .filter(Boolean).join(', ');
          if (label) document.getElementById('region-search').value = label;
        } catch { /* non-critical */ }
      },
      err => {
        UI.setStatus('error', 'Location error');
        UI.showToast('error', `Could not get your location: ${err.message}`);
      },
      { timeout: 10_000 }
    );
  }

  /**
   * Geocode a text query then fetch and display Starbucks for that region.
   */
  async function loadRegion(query) {
    UI.setStatus('loading', 'Searching…');
    UI.showListLoading();
    UI.hideMapHint();

    let geo;
    try {
      geo = await MapModule.geocodeRegion(query);
    } catch (err) {
      UI.setStatus('error', 'Geocode failed');
      UI.showToast('error', `Could not find "${query}". Check spelling and try again.`);
      return;
    }

    if (!geo) {
      UI.setStatus('error', 'Not found');
      UI.showToast('error', `No results found for "${query}".`);
      return;
    }

    MapModule.fitBounds(geo.bbox);
    // Tell scan panel what region is active
    Scan.setRegion(query, parseInt(document.getElementById('region-search').dataset.radius || '25'));
    await loadBbox(geo.bbox);
  }

  /**
   * Fetch and display Starbucks within a bounding box [s,w,n,e].
   */
  async function loadBbox(bbox) {
    UI.setStatus('loading', 'Fetching…');
    UI.showListLoading();
    UI.hideMapHint();

    let locations;
    try {
      locations = await MapModule.fetchStarbucks(bbox);
    } catch (err) {
      console.error('[App] Overpass fetch failed:', err);
      UI.setStatus('error', 'Fetch failed');
      UI.showToast('error', 'Failed to fetch Starbucks locations. The Overpass API may be busy — please try again shortly.');
      return;
    }

    _currentLocations = locations;

    if (locations.length === 0) {
      UI.setStatus('ok', 'No results');
      UI.showToast('info', 'No Starbucks locations found in this area. Try zooming out or searching a larger region.');
      UI.renderList([]);
      UI.updateStats([]);
      return;
    }

    // Build vacancy index: match scraped stores → OSM locations by proximity
    Data.buildVacancyIndex(locations);

    // Render map markers and sidebar list
    MapModule.renderMarkers(locations);
    UI.renderList(locations);

    // Update regional stats & possibly fire alerts
    const ids = locations.map(l => l.id);
    UI.updateStats(ids);

    UI.setStatus('ok', `${locations.length} locations`);
    UI.showToast('success', `Loaded ${locations.length} Starbucks location${locations.length !== 1 ? 's' : ''}.`);
  }

  /**
   * Reload vacancies.json from disk after a scrape completes,
   * then rebuild the proximity index and refresh all markers + list.
   * Exposed on App so scan.js can call it.
   */
  async function reloadVacancyData() {
    try {
      // Invalidate cache so we fetch fresh data from disk
      Data.invalidateVacancyCache();
      const resp = await fetch('data/vacancies.json', { cache: 'no-cache' });
      if (!resp.ok) return;
      const payload = await resp.json();
      Data.setVacancyData(payload);
      Data.cacheVacancyData(payload);
      Data.buildVacancyIndex(_currentLocations);
      MapModule.renderMarkers(_currentLocations);
      UI.renderList(_currentLocations);

      // Refresh the stats card + alert banner (was missing — caused stale report after scan)
      if (_currentLocations.length) {
        const ids = _currentLocations.map(l => l.id);
        UI.updateStats(ids);
      }

      const n = Object.keys(payload.stores || {}).length;
      console.log(`[App] Vacancy data reloaded: ${n} stores.`);
    } catch (e) {
      console.warn('[App] reloadVacancyData failed:', e.message);
    }
  }

  // Register on global App so scan.js and console can call it
  App.reloadVacancyData = () => reloadVacancyData();

  /* ================================================================
     REPORT SUBMISSION
     ================================================================ */

  /**
   * Called when a user submits a staffing report from the modal.
   * @param {Location}             location
   * @param {'adequate'|'low'|'critical'} level
   * @param {string}               comment
   * @param {boolean}              isFormerStaff
   */
  function handleReportSubmit(location, level, comment, isFormerStaff) {
    // Persist report
    Data.addReport(location.id, level, comment, isFormerStaff);

    // Refresh the map marker for this location
    MapModule.refreshMarker(location.id);

    // Re-render the sidebar list (status may have changed)
    UI.renderList(_currentLocations);

    // Re-run regional stats/alerts
    const ids = _currentLocations.map(l => l.id);
    UI.updateStats(ids);

    const levelLabel = level.charAt(0).toUpperCase() + level.slice(1);
    UI.showToast('success', `Report submitted — ${levelLabel} staffing at ${location.name}.`);
  }

})();

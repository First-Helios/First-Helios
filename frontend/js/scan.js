/**
 * scan.js — Chain Staffing Tracker
 * ===================================
 * Manages the "Scan for Update" panel in the header.
 *
 * Works alongside app.js:
 *   - On init, fetches /api/scan/status to show last-scan freshness.
 *   - Scan button POSTs /api/scan with the current region.
 *   - Polls status every 2 s while a scan is running.
 *   - On completion, calls App.reloadVacancyData() to refresh markers.
 *   - Force-refresh bypasses the 7-day server-side cooldown.
 *
 * Degrades gracefully: if /api/scan/status returns a network error
 * (e.g. running via plain file:// or python -m http.server), the
 * entire scan panel is hidden so it looks exactly like before.
 */

const Scan = (() => {
  /* ── DOM refs ─────────────────────────────────────────────────── */
  const $panel       = document.getElementById('scan-panel');
  const $scanBtn     = document.getElementById('scan-btn');
  const $forceBtn    = document.getElementById('scan-force-btn');
  const $scanStatus  = document.getElementById('scan-status-text');
  const $scanAge     = document.getElementById('scan-age-text');
  const $scanSpinner = document.getElementById('scan-spinner');

  /* ── State ────────────────────────────────────────────────────── */
  let _pollTimer = null;
  let _apiAvailable = false;   // set to false if server endpoints 404/fail

  /* ── Init ─────────────────────────────────────────────────────── */
  async function init() {
    if (!$panel) return;

    $scanBtn.addEventListener('click',  () => startScan(false));
    $forceBtn.addEventListener('click', () => startScan(true));

    await _fetchStatus();
  }

  /* ── API calls ────────────────────────────────────────────────── */

  async function _fetchStatus() {
    try {
      const resp = await fetch('/api/scan/status', { cache: 'no-cache' });
      if (!resp.ok) { _hidePanel(); return; }
      _apiAvailable = true;
      const data = await resp.json();
      _renderStatus(data);
      // If a scan is currently running (e.g. server restarted mid-scan), start polling
      if (data.scan?.status === 'running') _startPolling();
    } catch {
      _hidePanel(); // plain http.server or file:// — hide cleanly
    }
  }

  /**
   * Trigger a scrape on the server.
   * @param {boolean} force  Skip 7-day cooldown (dev mode)
   */
  async function startScan(force = false) {
    if (!_apiAvailable) return;

    const region = _currentRegion();
    if (!region.location) {
      UI.showToast('info', 'Search for a city first so the scraper knows which region to scan.');
      return;
    }

    try {
      const resp = await fetch('/api/scan', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({
          location: region.location,
          radius:   region.radius,
          force,
        }),
      });

      const data = await resp.json();

      if (resp.status === 409) {
        UI.showToast('info', 'A scan is already running.');
        _startPolling();
        return;
      }
      if (resp.status === 429) {
        // Still fresh — tell the user
        const next = data.next_allowed ? _relDate(data.next_allowed) : '';
        UI.showToast('info',
          `Data is still fresh (< ${STALE_AFTER_DAYS} days old).` +
          (next ? ` Next scan allowed ${next}.` : '') +
          ' Use Force Refresh to override.');
        return;
      }
      if (!resp.ok) {
        UI.showToast('error', data.error || 'Scan failed to start.');
        return;
      }

      // Started OK — update UI and begin polling
      _setScanningUI(region.location);
      _startPolling();
    } catch (err) {
      UI.showToast('error', `Could not reach scan API: ${err.message}`);
    }
  }

  /* ── Polling ──────────────────────────────────────────────────── */

  function _startPolling() {
    if (_pollTimer) return;
    _pollTimer = setInterval(_poll, 2000);
  }

  function _stopPolling() {
    if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
  }

  async function _poll() {
    try {
      const resp = await fetch('/api/scan/status', { cache: 'no-cache' });
      const data = await resp.json();
      _renderStatus(data);

      if (data.scan?.status !== 'running') {
        _stopPolling();
        if (data.scan?.status === 'done') {
          UI.showToast('success', `Scan complete — data updated for ${data.scan?.location || 'region'}.`);
          // Reload vacancy data into the frontend without a full page refresh
          if (typeof App !== 'undefined' && App.reloadVacancyData) {
            await App.reloadVacancyData();
          }
        } else if (data.scan?.status === 'error') {
          UI.showToast('error', `Scan error: ${data.scan?.message || 'Unknown error'}`);
        }
      }
    } catch { _stopPolling(); }
  }

  /* ── UI rendering ─────────────────────────────────────────────── */

  const STALE_AFTER_DAYS = 7;

  /**
   * Normalise a location string for loose comparison.
   * "Austin, TX, US" → "austin tx us"
   */
  function _normLoc(s) {
    return (s || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
  }

  /**
   * Check whether the current map region matches the last-scanned region.
   * Uses substring containment so "Columbus, OH" matches "Columbus, OH, US".
   */
  function _isRegionMatch(dataLocation) {
    const cur  = _normLoc(_region.location);
    const data = _normLoc(dataLocation);
    if (!cur || !data) return false;
    return cur === data || data.includes(cur) || cur.includes(data);
  }

  function _renderStatus(data) {
    const scan  = data.scan  || {};
    const meta  = data.last_scan || {};
    const stale = data.stale;

    if (scan.status === 'running') {
      _setScanningUI(scan.location);
      return;
    }

    // Determine freshness label
    const generated   = meta.generated;
    const total       = meta.total_stores || 0;
    const regionMatch = _isRegionMatch(meta.location);

    if (!generated) {
      $scanStatus.textContent  = 'No data yet';
      $scanAge.textContent     = 'Never scanned';
      $panel.dataset.freshness = 'stale';
    } else if (!regionMatch && _region.location) {
      // Data exists but for a different region
      $scanStatus.textContent  = `No data for ${_region.location}`;
      $scanAge.textContent     = `Last scan was for ${meta.location || 'another region'}`;
      $panel.dataset.freshness = 'stale';
    } else {
      $scanStatus.textContent = `${total} store${total !== 1 ? 's' : ''} scraped`;
      $scanAge.textContent    = stale
        ? `Stale — last scan ${_relDate(generated)}`
        : `Fresh — updated ${_relDate(generated)}`;
      $panel.dataset.freshness = stale ? 'stale' : 'fresh';
    }

    const needsScan = !generated || stale || (!regionMatch && _region.location);

    // Button state
    $scanBtn.disabled  = (scan.status === 'running');
    $scanBtn.innerHTML = `<i class="fa-solid fa-rotate"></i> ${needsScan ? 'Scan Region' : 'Re-scan'}`;
    $scanSpinner.hidden = true;
  }

  function _setScanningUI(location) {
    $scanStatus.textContent  = `Scanning ${location || 'region'}…`;
    $scanAge.textContent     = 'This may take 1–3 minutes';
    $panel.dataset.freshness = 'running';
    $scanBtn.disabled        = true;
    $scanSpinner.hidden      = false;
  }

  function _hidePanel() {
    if ($panel) $panel.hidden = true;
  }

  /* ── Helpers ──────────────────────────────────────────────────── */

  /** Human-readable relative date from an ISO string. */
  function _relDate(iso) {
    if (!iso) return '';
    try {
      const d = new Date(iso);
      const delta = Date.now() - d.getTime();
      const mins  = Math.floor(delta / 60000);
      if (mins <  1)  return 'just now';
      if (mins <  60) return `${mins} min ago`;
      const hrs = Math.floor(mins / 60);
      if (hrs  <  24) return `${hrs} h ago`;
      return `${Math.floor(hrs / 24)} d ago`;
    } catch { return iso; }
  }

  /* ── Current region (injected by App) ────────────────────────── */

  // App.js sets this via Scan.setRegion()
  let _region = { location: null, radius: 25 };

  function setRegion(location, radius) {
    const prev = _region.location;
    _region = { location, radius: radius || 25 };
    // When user switches to a new region, refresh scan panel status
    if (_apiAvailable && location && _normLoc(location) !== _normLoc(prev)) {
      _fetchStatus().then(() => {
        // Auto-prompt if no data for this region
        _checkAutoPrompt();
      });
    }
  }

  function _currentRegion() { return _region; }

  /**
   * If the current region has no scraped data, show a helpful toast.
   */
  function _checkAutoPrompt() {
    if ($panel.dataset.freshness === 'stale' && _region.location) {
      UI.showToast('info',
        `No vacancy data for ${_region.location}. Click "Scan Region" to fetch staffing data.`);
    }
  }

  /* ── Public API ───────────────────────────────────────────────── */
  return { init, startScan, setRegion, refreshStatus: _fetchStatus };
})();

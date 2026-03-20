/**
 * map.js — Chain Staffing Tracker
 * Manages the Leaflet map, custom markers, popups,
 * and the Overpass + Nominatim API calls.
 */

const MapModule = (() => {
  /* ── State ──────────────────────────────────────────────────── */
  let _map         = null;
  let _markerLayer = null;   // L.LayerGroup for all location markers
  let _markers     = {};     // { locationId: L.Marker }
  let _onReport    = null;   // callback(location) → opens report modal

  /* ── Overpass API ───────────────────────────────────────────── */
  const OVERPASS_URL  = 'https://overpass-api.de/api/interpreter';
  // Fallback mirrors if main is slow
  const OVERPASS_MIRRORS = [
    'https://overpass-api.de/api/interpreter',
    'https://overpass.kumi.systems/api/interpreter',
    'https://maps.mail.ru/osm/tools/overpass/api/interpreter',
  ];
  const NOMINATIM_URL = 'https://nominatim.openstreetmap.org/search';

  /**
   * Build an Overpass QL query for Starbucks (brand:wikidata Q37158)
   * within a bounding box [south, west, north, east].
   */
  function buildOverpassQuery(bbox) {
    const [s, w, n, e] = bbox;
    return `
[out:json][timeout:30];
(
  node["brand:wikidata"="Q37158"](${s},${w},${n},${e});
  way["brand:wikidata"="Q37158"](${s},${w},${n},${e});
  relation["brand:wikidata"="Q37158"](${s},${w},${n},${e});
);
out center;
`.trim();
  }

  /**
   * Geocode a free-text region string using Nominatim.
   * Returns { lat, lng, boundingbox: [s, n, w, e] } or null on failure.
   */
  async function geocodeRegion(query) {
    const params = new URLSearchParams({
      q:              query,
      format:         'json',
      limit:          '1',
      addressdetails: '0',
    });
    const url = `${NOMINATIM_URL}?${params}`;
    const resp = await fetch(url, {
      headers: { 'Accept-Language': 'en', 'User-Agent': 'ChainStaffingTracker/1.0' },
    });
    if (!resp.ok) throw new Error(`Nominatim error ${resp.status}`);
    const results = await resp.json();
    if (!results.length) return null;
    const r = results[0];
    // Nominatim bbox is [south, north, west, east] — reorder to [s,w,n,e]
    const [s, n, w, e] = r.boundingbox.map(Number);
    return { lat: parseFloat(r.lat), lng: parseFloat(r.lon), bbox: [s, w, n, e] };
  }

  /**
   * Fetch Starbucks locations from Overpass API.
   * Tries mirrors in sequence if the primary fails.
   * @param {[number,number,number,number]} bbox — [south, west, north, east]
   * @returns {Location[]}
   */
  async function fetchStarbucks(bbox) {
    // Check cache first
    const cached = Data.getCachedOsmLocations(bbox);
    if (cached) return cached;

    const query = buildOverpassQuery(bbox);
    let lastErr;

    for (const mirror of OVERPASS_MIRRORS) {
      try {
        const resp = await fetch(mirror, {
          method:  'POST',
          headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
          body:    `data=${encodeURIComponent(query)}`,
          signal:  AbortSignal.timeout(28_000),
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const json = await resp.json();
        const locations = parseOverpassElements(json.elements || []);
        // Cache the result
        Data.cacheOsmLocations(bbox, locations);
        return locations;
      } catch (err) {
        lastErr = err;
        console.warn(`[MapModule] Overpass mirror ${mirror} failed:`, err.message);
      }
    }
    throw lastErr || new Error('All Overpass mirrors failed');
  }

  /**
   * Convert raw OSM elements into our Location objects.
   * @param {object[]} elements
   * @returns {Location[]}
   */
  function parseOverpassElements(elements) {
    return elements.map(el => {
      // Ways/relations have a `center` property; nodes use lat/lon directly
      const lat = el.lat ?? el.center?.lat;
      const lon = el.lon ?? el.center?.lon;
      const tags = el.tags || {};

      // Build a human-readable address from available tags
      const addrParts = [
        tags['addr:housenumber'],
        tags['addr:street'],
        tags['addr:city'] || tags['addr:town'],
        tags['addr:state'],
      ].filter(Boolean);

      return {
        id:        `${el.type}/${el.id}`,
        osmId:     el.id,
        osmType:   el.type,
        lat:       lat,
        lng:       lon,
        name:      tags.name || 'Starbucks',
        address:   addrParts.join(', ') || tags['addr:full'] || '',
        phone:     tags.phone || tags['contact:phone'] || '',
        website:   tags.website || tags['contact:website'] || '',
        openingHours: tags.opening_hours || '',
        tags,
      };
    }).filter(l => l.lat != null && l.lng != null);
  }

  /* ── Map Initialisation ─────────────────────────────────────── */

  /**
   * Initialise the Leaflet map and layers.
   * @param {string}   containerId — DOM element ID
   * @param {Function} onReport    — callback when user clicks "Report" in popup
   */
  function init(containerId, onReport) {
    _onReport = onReport;

    _map = L.map(containerId, {
      center:  [20, 0],
      zoom:    2,
      zoomControl: false,
    });

    // Zoom control in a better position
    L.control.zoom({ position: 'bottomright' }).addTo(_map);

    // Base tile layer — CartoDB Dark Matter (no API key needed)
    L.tileLayer(
      'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
      {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/">CARTO</a>',
        subdomains:  'abcd',
        maxZoom:     20,
      }
    ).addTo(_map);

    _markerLayer = L.layerGroup().addTo(_map);
    return _map;
  }

  /* ── Markers ────────────────────────────────────────────────── */

  /**
   * Build a coloured Leaflet divIcon for a given status.
   */
  function buildIcon(status) {
    const cls = `marker-${status}`;
    // Starbucks siren "S" glyph as the marker inner character
    const inner = '<i class="fa-solid fa-mug-hot custom-marker-inner"></i>';
    return L.divIcon({
      className: '',
      html:      `<div class="custom-marker ${cls}">${inner}</div>`,
      iconSize:  [32, 32],
      iconAnchor:[16, 32],
      popupAnchor:[0, -34],
    });
  }

  /**
   * Render all locations onto the map.
   * Clears any existing markers first.
   * @param {Location[]} locations
   */
  function renderMarkers(locations) {
    _markerLayer.clearLayers();
    _markers = {};

    for (const loc of locations) {
      const status = Data.getStatus(loc.id);
      const marker = L.marker([loc.lat, loc.lng], { icon: buildIcon(status) });

      marker.bindPopup(() => buildPopupContent(loc), {
        maxWidth: 280,
        className: 'dark-popup',
      });

      marker.on('popupopen', () => {
        // Re-render popup content in case status changed
        marker.setPopupContent(buildPopupContent(loc));
        // Wire up button inside popup
        const btn = document.querySelector(`.popup-report-btn[data-id="${loc.id}"]`);
        if (btn) btn.addEventListener('click', () => _onReport && _onReport(loc));
      });

      marker.addTo(_markerLayer);
      _markers[loc.id] = marker;
    }
  }

  /**
   * Refresh a single marker's icon after a new report is submitted.
   * @param {string} locationId
   */
  function refreshMarker(locationId) {
    const marker = _markers[locationId];
    if (!marker) return;
    const status = Data.getStatus(locationId);
    marker.setIcon(buildIcon(status));
    if (marker.isPopupOpen()) {
      // Rebuild popup requires knowing the location; store it on the marker
      const loc = marker._cstLocation;
      if (loc) marker.setPopupContent(buildPopupContent(loc));
    }
  }

  /** Build the HTML string for a location popup. */
  function buildPopupContent(loc) {
    // Store reference so we can refresh popup
    if (_markers[loc.id]) _markers[loc.id]._cstLocation = loc;

    const status     = Data.getStatus(loc.id);
    const totalRpts  = Data.getRecentCount(loc.id);
    const latest     = Data.getLatestReport(loc.id);
    const levelLabel = status.charAt(0).toUpperCase() + status.slice(1);
    const vacancy    = Data.getVacancyInfo(loc.id);

    const lastLine = latest
      ? `<p class="popup-last-report">“${latest.comment || levelLabel}” — ${Data.relativeTime(latest.timestamp)}${latest.isFormerStaff ? ' (staff)' : ''}</p>`
      : '<p class="popup-last-report">No community reports yet.</p>';

    // Vacancy block (scraped data)
    let vacancyBlock = '';
    if (vacancy && vacancy.listing_count > 0) {
      const roleRows = Object.entries(vacancy.open_roles || {})
        .sort((a, b) => b[1] - a[1])
        .map(([role, count]) =>
          `<span class="popup-vacancy-role"><span class="popup-vacancy-count">${count}x</span> ${escapeHtml(role)}</span>`
        ).join('');
      const fresh = vacancy.latest_posting
        ? Data.relativeTime(vacancy.latest_posting * 1000) : '';
      vacancyBlock = `
        <div class="popup-vacancy-block">
          <div class="popup-vacancy-header">
            <i class="fa-solid fa-briefcase-blank"></i>
            <strong>${vacancy.listing_count} open listing${vacancy.listing_count !== 1 ? 's' : ''}</strong>
            ${fresh ? `<span class="popup-vacancy-fresh">latest ${fresh}</span>` : ''}
          </div>
          <div class="popup-vacancy-roles">${roleRows}</div>
          <p class="popup-vacancy-source">Source: Starbucks Careers scraper</p>
        </div>`;
    }

    return `
      <div class="popup-content">
        <p class="popup-name">${escapeHtml(loc.name)}</p>
        <p class="popup-addr">${escapeHtml(loc.address || 'Address unknown')}</p>
        <div class="popup-level-row">
          <span class="list-item-level level-${status}">${levelLabel}</span>
          <span class="popup-reports-note">${totalRpts} community report${totalRpts !== 1 ? 's' : ''}</span>
        </div>
        ${vacancyBlock}
        ${lastLine}
        <button class="popup-report-btn" data-id="${loc.id}">
          <i class="fa-solid fa-flag"></i>&nbsp; Report Staffing
        </button>
      </div>
    `;
  }

  /* ── Map Navigation ─────────────────────────────────────────── */

  /**
   * Pan/zoom the map to fit a bounding box.
   * @param {[s,w,n,e]} bbox
   */
  function fitBounds(bbox) {
    const [s, w, n, e] = bbox;
    _map.fitBounds([[s, w], [n, e]], { padding: [30, 30], maxZoom: 14 });
  }

  /**
   * Pan to a specific location and open its popup.
   */
  function focusLocation(locationId) {
    const marker = _markers[locationId];
    if (!marker) return;
    _map.setView(marker.getLatLng(), Math.max(_map.getZoom(), 15), { animate: true });
    marker.openPopup();
  }

  /**
   * Return current map bounding box as [south, west, north, east].
   */
  function getCurrentBbox() {
    const b = _map.getBounds();
    return [
      b.getSouth(),
      b.getWest(),
      b.getNorth(),
      b.getEast(),
    ];
  }

  /* ── Utilities ──────────────────────────────────────────────── */
  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  /* ── Public API ─────────────────────────────────────────────── */
  return {
    init,
    geocodeRegion,
    fetchStarbucks,
    renderMarkers,
    refreshMarker,
    fitBounds,
    focusLocation,
    getCurrentBbox,
  };
})();

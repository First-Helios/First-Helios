/**
 * ChainStaffingTracker — Leaflet map application
 *
 * Fetches store scores, targeting data, and reference metadata from the
 * Flask API and renders them on a dark-themed Leaflet map.
 *
 * Filter dropdowns are populated dynamically from /api/ref/summary so
 * adding a new chain or industry only requires updating the reference DB.
 */

(function () {
    'use strict';

    const API_BASE = '';
    const AUSTIN_CENTER = [30.2672, -97.7431];
    const DEFAULT_ZOOM = 11;

    // Marker colors
    // brand  = multi-location employer (H-E-B, CVS, etc.)  — amber
    // local  = single-location independent employer         — purple
    const BRAND_COLOR = '#f0a500';
    const LOCAL_COLOR = '#6c5ce7';

    // ── Map initialization ──────────────────────────────────────────
    const map = L.map('map', {
        center: AUSTIN_CENTER,
        zoom: DEFAULT_ZOOM,
        zoomControl: true,
    });

    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; OSM &copy; CARTO',
        subdomains: 'abcd',
        maxZoom: 19,
    }).addTo(map);

    let storeMarkers = [];
    let localMarkers = [];

    // ── Populate filter dropdowns from reference data ───────────────
    async function loadFilters() {
        try {
            const resp = await fetch(API_BASE + '/api/ref/summary');
            const data = await resp.json();
            if (data.status !== 'ok') return;

            // Chain filter — driven by actual ingested data.
            // Tracked chains (has_scores=true) have targeting data.
            // Area chains (has_scores=false) are map-location-only.
            const chainSel = document.getElementById('chain-filter');
            (data.chains || []).forEach(function (c) {
                const opt = document.createElement('option');
                opt.value = c.chain_key || c.chain_name;
                var cnt = c.store_count || c.location_count || 0;
                opt.textContent = c.chain_name + ' (' + cnt + ')';
                chainSel.appendChild(opt);
            });

            // Industry filter — keyed by IndustryTaxonomy.industry_key, same key
            // stored in Store.industry and LocalEmployer.industry.
            const indSel = document.getElementById('industry-filter');
            (data.industries || []).forEach(function (ind) {
                const opt = document.createElement('option');
                opt.value = ind.industry_key;
                var label = ind.display_name;
                var total = (ind.store_count || 0) + (ind.local_count || 0);
                if (total) label += ' (' + total + ')';
                opt.textContent = label;
                indSel.appendChild(opt);
            });

            // Store count badge
            updateCountBadge(data.store_total, data.local_employer_total);
        } catch (err) {
            console.warn('Could not load reference data — using defaults', err);
        }
    }

    function updateCountBadge(storeTotal, localTotal) {
        var badge = document.getElementById('store-count');
        var parts = [];
        if (storeTotal != null) parts.push(storeTotal + ' stores');
        if (localTotal != null) parts.push(localTotal + ' local');
        badge.textContent = parts.join(' · ') || '—';
    }

    // ── Unified map load ─────────────────────────────────────────────
    // Fetches both chain stores and local employers from /api/map-employers.
    // Industry and chain filters apply uniformly to both source types.
    // show-local checkbox toggles local marker visibility without re-fetching.
    // local-sample selector triggers a full reload with a new count.

    async function loadMapEmployers() {
        const chainFilter    = document.getElementById('chain-filter').value;
        const industryFilter = document.getElementById('industry-filter').value;
        const sample         = document.getElementById('local-sample').value;
        const showLocal      = document.getElementById('show-local').checked;

        let url = API_BASE + '/api/map-employers?region=austin_tx';
        if (chainFilter)    url += '&chain='    + encodeURIComponent(chainFilter);
        if (industryFilter) url += '&industry=' + encodeURIComponent(industryFilter);
        if (!industryFilter) url += '&sample=' + sample;

        try {
            const resp = await fetch(url);
            const data = await resp.json();

            // Clear all existing markers
            storeMarkers.forEach(function (m) { map.removeLayer(m); });
            storeMarkers = [];
            localMarkers.forEach(function (m) { map.removeLayer(m); });
            localMarkers = [];

            var brandCount = 0, localCount = 0;

            (data.employers || []).forEach(function (emp) {
                if (!emp.lat || !emp.lng) return;

                var isBrand = emp.source_type === 'brand';
                var color   = isBrand ? BRAND_COLOR : LOCAL_COLOR;
                var radius  = isBrand ? 6 : 4;
                var label   = isBrand ? (emp.location_count + ' locations') : 'Local employer';

                var marker = L.circleMarker([emp.lat, emp.lng], {
                    radius: radius,
                    fillColor: color,
                    color: color,
                    weight: 1,
                    opacity: isBrand ? 0.85 : 0.6,
                    fillOpacity: isBrand ? 0.55 : 0.35,
                });

                if (showLocal || isBrand) marker.addTo(map);

                marker.bindPopup(
                    '<strong>' + emp.name + '</strong><br>' +
                    '<em>' + label + '</em><br>' +
                    (emp.industry ? 'Industry: ' + emp.industry + '<br>' : '') +
                    '<small>' + (emp.address || '') + '</small>'
                );

                if (isBrand) {
                    storeMarkers.push(marker);
                    brandCount++;
                } else {
                    localMarkers.push(marker);
                    localCount++;
                }
            });

            document.getElementById('store-count').textContent =
                brandCount + ' brands · ' +
                (showLocal ? localCount + ' local' : localCount + ' local (hidden)');

        } catch (err) {
            console.error('Failed to load map employers:', err);
        }
    }

    function clearLocalMarkers() {
        localMarkers.forEach(function (m) { map.removeLayer(m); });
        localMarkers = [];
    }

    function setLocalVisibility(visible) {
        localMarkers.forEach(function (m) {
            if (visible) { m.addTo(map); } else { map.removeLayer(m); }
        });
    }

    // ── Fetch and render targeting sidebar ──────────────────────────
    async function loadTargets() {
        const industryFilter = document.getElementById('industry-filter').value;
        const chainFilter = document.getElementById('chain-filter').value;
        let url = API_BASE + '/api/targeting?region=austin_tx&limit=10';
        if (industryFilter) url += '&industry=' + industryFilter;
        if (chainFilter) url += '&chain=' + chainFilter;

        try {
            const resp = await fetch(url);
            const data = await resp.json();
            const container = document.getElementById('targets-list');
            container.innerHTML = '';

            (data.targets || []).forEach(function (target, i) {
                var card = document.createElement('div');
                card.className = 'target-card';
                card.innerHTML =
                    '<div class="store-name">#' + (i + 1) + ' ' + (target.address || target.store_num) + '</div>' +
                    '<div class="score tier-' + target.targeting_tier + '">' +
                    target.targeting_score.toFixed(1) + ' — ' + target.targeting_tier +
                    '</div>' +
                    '<div class="details">' +
                    'Stress: ' + target.staffing_stress.toFixed(0) +
                    ' | Wage Gap: ' + target.wage_gap.toFixed(0) +
                    ' | Isolation: ' + target.isolation.toFixed(0) +
                    (target.wage_premium_pct != null ? ' | Premium: ' + target.wage_premium_pct + '%' : '') +
                    '</div>';
                container.appendChild(card);
            });

            if (!(data.targets || []).length) {
                container.innerHTML = '<div class="target-card"><div class="details">No targeting data yet. Run a scan first.</div></div>';
            }
        } catch (err) {
            console.error('Failed to load targets:', err);
        }
    }

    // ── Mode switching ───────────────────────────────────────────────
    var currentMode = 'targeting';

    function switchMode(mode) {
        currentMode = mode;
        var isTargeting = (mode === 'targeting');

        document.getElementById('targeting-controls').style.display = isTargeting ? '' : 'none';
        document.getElementById('pathfinder-controls').style.display = isTargeting ? 'none' : '';
        document.getElementById('targeting-sidebar').style.display  = isTargeting ? '' : 'none';
        document.getElementById('pathfinder-sidebar').style.display  = isTargeting ? 'none' : '';

        document.getElementById('mode-targeting').classList.toggle('active', isTargeting);
        document.getElementById('mode-pathfinder').classList.toggle('active', !isTargeting);

        // Clear markers from the other mode
        if (isTargeting) {
            if (window.pathfinderClearMarkers) window.pathfinderClearMarkers();
            loadMapEmployers();
            loadTargets();
        } else {
            storeMarkers.forEach(function (m) { map.removeLayer(m); });
            storeMarkers = [];
            clearLocalMarkers();
            if (window.pathfinderInit) window.pathfinderInit();
        }
    }

    document.getElementById('mode-targeting').addEventListener('click', function () { switchMode('targeting'); });
    document.getElementById('mode-pathfinder').addEventListener('click', function () { switchMode('pathfinder'); });

    // ── Event listeners ─────────────────────────────────────────────
    document.getElementById('refresh-btn').addEventListener('click', function () {
        loadMapEmployers();
        loadTargets();
    });

    document.getElementById('chain-filter').addEventListener('change', function () {
        loadMapEmployers();
        loadTargets();
    });

    document.getElementById('industry-filter').addEventListener('change', function () {
        loadMapEmployers();
        loadTargets();
    });

    // show-local: toggle visibility without re-fetching
    document.getElementById('show-local').addEventListener('change', function () {
        setLocalVisibility(this.checked);
    });

    // local-sample: reload with new count
    document.getElementById('local-sample').addEventListener('change', function () {
        loadMapEmployers();
    });

    // ── Initial load ────────────────────────────────────────────────
    loadFilters().then(function () {
        loadMapEmployers();
        loadTargets();
    });

    // Expose map for pathfinder.js
    window.sharedMap = map;
})();

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

    // Tier / targeting colors
    const TIER_COLORS = {
        critical: '#e94560',
        elevated: '#f0a500',
        adequate: '#4ecca3',
        unknown: '#666',
        prime: '#e94560',
        strong: '#f0a500',
        moderate: '#4ecca3',
    };

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

            // Chain filter
            const chainSel = document.getElementById('chain-filter');
            (data.brands || []).forEach(function (b) {
                const opt = document.createElement('option');
                opt.value = b.brand_key;
                opt.textContent = b.display_name + (b.store_count ? ' (' + b.store_count + ')' : '');
                chainSel.appendChild(opt);
            });

            // Industry filter
            const indSel = document.getElementById('industry-filter');
            (data.industries || []).forEach(function (ind) {
                const opt = document.createElement('option');
                opt.value = ind.internal_key;
                opt.textContent = ind.naics_title;
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

    // ── Fetch and render scored stores ──────────────────────────────
    async function loadScores() {
        const chainFilter = document.getElementById('chain-filter').value;
        const tierFilter = document.getElementById('tier-filter').value;
        const industryFilter = document.getElementById('industry-filter').value;

        let url = API_BASE + '/api/stores?region=austin_tx';
        if (chainFilter) url += '&chain=' + chainFilter;
        if (industryFilter) url += '&industry=' + industryFilter;

        try {
            const resp = await fetch(url);
            const data = await resp.json();

            // Clear existing store markers
            storeMarkers.forEach(function (m) { map.removeLayer(m); });
            storeMarkers = [];

            var stores = data.stores || [];
            if (tierFilter) {
                stores = stores.filter(function (s) { return s.tier === tierFilter; });
            }

            stores.forEach(function (store) {
                if (!store.lat || !store.lng) return;

                var color = TIER_COLORS[store.tier] || TIER_COLORS.unknown;
                var marker = L.circleMarker([store.lat, store.lng], {
                    radius: 8,
                    fillColor: color,
                    color: color,
                    weight: 2,
                    opacity: 0.9,
                    fillOpacity: 0.6,
                }).addTo(map);

                marker.bindPopup(
                    '<strong>' + (store.name || store.store_num) + '</strong><br>' +
                    'Chain: ' + (store.chain || '—') + '<br>' +
                    'Score: ' + (store.score != null ? store.score.toFixed(1) : 'n/a') + '<br>' +
                    'Tier: <span style="color:' + color + '">' + store.tier + '</span><br>' +
                    '<small>' + (store.address || '') + '</small>'
                );
                storeMarkers.push(marker);
            });

            // Update visible-count portion of badge
            document.getElementById('store-count').textContent =
                stores.length + ' visible' + (storeMarkers.length !== stores.length ? ' (' + storeMarkers.length + ' mapped)' : '');

        } catch (err) {
            console.error('Failed to load stores:', err);
        }
    }

    // ── Fetch and render local employers ────────────────────────────
    async function loadLocalEmployers() {
        const industryFilter = document.getElementById('industry-filter').value;
        let url = API_BASE + '/api/local-employers?region=austin_tx';
        if (industryFilter) url += '&industry=' + industryFilter;

        try {
            const resp = await fetch(url);
            const data = await resp.json();

            // Clear existing local markers
            localMarkers.forEach(function (m) { map.removeLayer(m); });
            localMarkers = [];

            (data.employers || []).forEach(function (emp) {
                if (!emp.lat || !emp.lng) return;
                var marker = L.circleMarker([emp.lat, emp.lng], {
                    radius: 4,
                    fillColor: LOCAL_COLOR,
                    color: LOCAL_COLOR,
                    weight: 1,
                    opacity: 0.6,
                    fillOpacity: 0.35,
                }).addTo(map);

                marker.bindPopup(
                    '<strong>' + emp.name + '</strong><br>' +
                    '<em>Local employer</em><br>' +
                    (emp.category ? 'Category: ' + emp.category + '<br>' : '') +
                    '<small>' + (emp.address || '') + '</small>'
                );
                localMarkers.push(marker);
            });
        } catch (err) {
            console.error('Failed to load local employers:', err);
        }
    }

    function clearLocalMarkers() {
        localMarkers.forEach(function (m) { map.removeLayer(m); });
        localMarkers = [];
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

    // ── Event listeners ─────────────────────────────────────────────
    document.getElementById('refresh-btn').addEventListener('click', function () {
        loadScores();
        loadTargets();
        if (document.getElementById('show-local').checked) loadLocalEmployers();
    });

    document.getElementById('chain-filter').addEventListener('change', function () {
        loadScores();
        loadTargets();
    });

    document.getElementById('tier-filter').addEventListener('change', loadScores);

    document.getElementById('industry-filter').addEventListener('change', function () {
        loadScores();
        loadTargets();
        if (document.getElementById('show-local').checked) loadLocalEmployers();
    });

    document.getElementById('show-local').addEventListener('change', function () {
        if (this.checked) {
            loadLocalEmployers();
        } else {
            clearLocalMarkers();
        }
    });

    // ── Initial load ────────────────────────────────────────────────
    loadFilters().then(function () {
        loadScores();
        loadTargets();
    });
})();

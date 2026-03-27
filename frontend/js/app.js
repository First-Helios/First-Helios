/**
 * ChainStaffingTracker — Leaflet map application
 *
 * Map layer: H3 hex aggregates only — no individual dots.
 * Sidebar: "Top Targets" by default; clicking a hex loads employer listings
 * for that cell. Back button restores top targets.
 *
 * Filter dropdowns are populated dynamically from /api/ref/summary.
 */

(function () {
    'use strict';

    const API_BASE = '';
    const AUSTIN_CENTER = [30.2672, -97.7431];
    const DEFAULT_ZOOM = 11;

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

    // ── Populate filter dropdowns from reference data ───────────────
    async function loadFilters() {
        try {
            const resp = await fetch(API_BASE + '/api/ref/summary');
            const data = await resp.json();
            if (data.status !== 'ok') return;

            const chainSel = document.getElementById('chain-filter');
            (data.chains || []).forEach(function (c) {
                const opt = document.createElement('option');
                opt.value = c.chain_key || c.chain_name;
                var cnt = c.store_count || c.location_count || 0;
                opt.textContent = c.chain_name + ' (' + cnt + ')';
                chainSel.appendChild(opt);
            });

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

            var badge = document.getElementById('store-count');
            if (badge && data.local_employer_total != null) {
                badge.textContent = data.local_employer_total + ' employers';
            }
        } catch (err) {
            console.warn('Could not load reference data — using defaults', err);
        }
    }

    // ── Map refresh — always H3 hex, no dots ────────────────────────
    function refreshMap() {
        var industry = document.getElementById('industry-filter').value;
        var chain    = document.getElementById('chain-filter').value;
        if (window.h3map) window.h3map.refresh(industry, chain);
    }

    // Re-render on zoom (resolution changes)
    map.on('zoomend', function () {
        if (currentMode !== 'targeting') return;
        refreshMap();
    });

    // ── Sidebar: Top Targets ────────────────────────────────────────
    async function loadTargets() {
        const industryFilter = document.getElementById('industry-filter').value;
        const chainFilter    = document.getElementById('chain-filter').value;
        let url = API_BASE + '/api/targeting?region=austin_tx&limit=10';
        if (industryFilter) url += '&industry=' + industryFilter;
        if (chainFilter)    url += '&chain='    + chainFilter;

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
                container.innerHTML = '<div class="target-card"><div class="details">No targeting data yet.</div></div>';
            }
        } catch (err) {
            console.error('Failed to load targets:', err);
        }
    }

    // ── Sidebar: Hex cell listings ──────────────────────────────────
    // Shows employer listing cards when a hex is clicked.

    function showTopTargetsView() {
        document.getElementById('sidebar-top-targets').style.display = 'block';
        document.getElementById('sidebar-listings').style.display = 'none';
    }

    function showListingsView(title) {
        document.getElementById('sidebar-top-targets').style.display = 'none';
        var listingsPanel = document.getElementById('sidebar-listings');
        listingsPanel.style.display = 'block';
        document.getElementById('listings-title').textContent = title;
        document.getElementById('listings-list').innerHTML =
            '<div class="listing-card"><div class="listing-name">Loading…</div></div>';
    }

    async function loadCellListings(cellId, resolution) {
        var industry = document.getElementById('industry-filter').value;
        var chain    = document.getElementById('chain-filter').value;

        var url = API_BASE + '/api/map-employers?region=austin_tx' +
            '&h3_cell=' + encodeURIComponent(cellId) +
            '&resolution=' + resolution;
        if (industry) url += '&industry=' + encodeURIComponent(industry);
        if (chain)    url += '&chain='    + encodeURIComponent(chain);

        try {
            const resp = await fetch(url);
            const data = await resp.json();
            const container = document.getElementById('listings-list');
            container.innerHTML = '';

            var employers = data.employers || [];
            if (!employers.length) {
                container.innerHTML = '<div class="listing-card"><div class="listing-name">No employers found in this cell.</div></div>';
                return;
            }

            // Sort: brands first, then alphabetical
            employers.sort(function (a, b) {
                var ab = a.source_type === 'brand' ? 0 : 1;
                var bb = b.source_type === 'brand' ? 0 : 1;
                return ab - bb || a.name.localeCompare(b.name);
            });

            employers.forEach(function (emp) {
                var isBrand = emp.source_type === 'brand';
                var card = document.createElement('div');
                card.className = 'listing-card';
                card.innerHTML =
                    '<div class="listing-name">' + emp.name +
                        (isBrand ? '<span class="listing-badge brand">brand</span>' : '<span class="listing-badge local">local</span>') +
                    '</div>' +
                    (emp.address ? '<div class="listing-addr">' + emp.address + '</div>' : '') +
                    (emp.industry ? '<div class="listing-meta">' + emp.industry + '</div>' : '');
                container.appendChild(card);
            });
        } catch (err) {
            console.error('Failed to load cell listings:', err);
        }
    }

    // Called by h3map.js on hex click
    window.onHexClick = function (cellId, resolution, count, brandCount) {
        var localCount = count - brandCount;
        var title = count + ' employers — ' + brandCount + ' brand · ' + localCount + ' local';
        showListingsView(title);
        loadCellListings(cellId, resolution);
    };

    // ── Mode switching ───────────────────────────────────────────────
    var currentMode = 'targeting';

    function switchMode(mode) {
        currentMode = mode;
        var isTargeting = (mode === 'targeting');

        document.getElementById('targeting-controls').style.display = isTargeting ? 'flex' : 'none';
        document.getElementById('pathfinder-controls').style.display = isTargeting ? 'none' : 'flex';
        document.getElementById('targeting-sidebar').style.display  = isTargeting ? 'block' : 'none';
        document.getElementById('pathfinder-sidebar').style.display  = isTargeting ? 'none' : 'block';

        document.getElementById('mode-targeting').classList.toggle('active', isTargeting);
        document.getElementById('mode-pathfinder').classList.toggle('active', !isTargeting);

        if (isTargeting) {
            if (window.pathfinderClearMarkers) window.pathfinderClearMarkers();
            map.setView(AUSTIN_CENTER, DEFAULT_ZOOM);
            showTopTargetsView();
            refreshMap();
            loadTargets();
        } else {
            if (window.h3map) window.h3map.clear();
            map.setView(AUSTIN_CENTER, DEFAULT_ZOOM);
            if (window.pathfinderInit) window.pathfinderInit();
        }
    }

    document.getElementById('mode-targeting').addEventListener('click', function () { switchMode('targeting'); });
    document.getElementById('mode-pathfinder').addEventListener('click', function () { switchMode('pathfinder'); });

    // ── Event listeners ─────────────────────────────────────────────
    document.getElementById('refresh-btn').addEventListener('click', function () {
        showTopTargetsView();
        refreshMap();
        loadTargets();
    });

    document.getElementById('chain-filter').addEventListener('change', function () {
        showTopTargetsView();
        refreshMap();
        loadTargets();
    });

    document.getElementById('industry-filter').addEventListener('change', function () {
        showTopTargetsView();
        refreshMap();
        loadTargets();
    });

    document.getElementById('listings-back-btn').addEventListener('click', function () {
        showTopTargetsView();
    });

    // ── Initial load ────────────────────────────────────────────────
    loadFilters().then(function () {
        refreshMap();
        loadTargets();
    });

    // Expose map for pathfinder.js
    window.sharedMap = map;
})();

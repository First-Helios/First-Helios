/**
 * ChainStaffingTracker — Leaflet map application
 *
 * Three modes:
 *   targeting  — H3 hex aggregates of employers (brand vs. local coloring)
 *   pathfinder — Career transition paths with occupation search
 *   jobfinder  — H3 hex aggregates of job postings + job listing sidebar
 *
 * Filter dropdowns are populated dynamically from /api/ref/summary (targeting)
 * and /api/jobs/categories (jobfinder).
 */

(function () {
    'use strict';

    function _esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    const API_BASE    = '';
    const AUSTIN_CENTER = [30.2672, -97.7431];
    const DEFAULT_ZOOM  = 11;

    // ── Map initialization ──────────────────────────────────────────
    const map = L.map('map', {
        center: AUSTIN_CENTER,
        zoom:   DEFAULT_ZOOM,
        zoomControl: true,
    });

    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; OSM &copy; CARTO',
        subdomains: 'abcd',
        maxZoom: 19,
    }).addTo(map);

    // ── Populate targeting filter dropdowns ─────────────────────────
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

    // ── Populate job category dropdown ──────────────────────────────
    async function loadJobCategories() {
        try {
            const resp = await fetch(API_BASE + '/api/jobs/categories?region=austin_tx');
            const data = await resp.json();
            if (data.status !== 'ok') return;

            const sel = document.getElementById('job-category-filter');
            (data.categories || []).forEach(function (cat) {
                const opt = document.createElement('option');
                opt.value = cat.key;
                opt.textContent = cat.label + ' (' + cat.count + ')';
                sel.appendChild(opt);
            });
        } catch (err) {
            console.warn('[jobfinder] Could not load categories:', err);
        }
    }

    // ── Map refresh (targeting mode) ────────────────────────────────
    function refreshMap() {
        var industry = document.getElementById('industry-filter').value;
        var chain    = document.getElementById('chain-filter').value;
        if (window.h3map) window.h3map.refresh(industry, chain);
    }

    // ── Job Finder refresh ──────────────────────────────────────────
    var _jfMode = 'remote';

    function refreshJobFinder() {
        var category = document.getElementById('job-category-filter').value;
        if (window.jobfinder) window.jobfinder.refresh('austin_tx', category, _jfMode);
    }

    // ── Event Finder refresh ────────────────────────────────────────
    function refreshEventFinder() {
        var category = document.getElementById('event-category-filter').value;
        if (window.eventfinder) window.eventfinder.refresh('austin_tx', category);
    }

    // ── Map zoom handler ────────────────────────────────────────────
    map.on('zoomend', function () {
        if (currentMode === 'targeting') refreshMap();
        if (currentMode === 'jobfinder' && window.jobfinder) window.jobfinder.onZoom();
        if (currentMode === 'eventfinder' && window.eventfinder) window.eventfinder.onZoom();
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
                    '<div class="store-name">#' + (i + 1) + ' ' + _esc(target.address || target.store_num) + '</div>' +
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

    // ── Sidebar: Hex cell listings (targeting mode) ─────────────────
    function showTopTargetsView() {
        document.getElementById('sidebar-top-targets').style.display = 'block';
        document.getElementById('sidebar-listings').style.display    = 'none';
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
                    '<div class="listing-name">' + _esc(emp.name) +
                        (isBrand ? '<span class="listing-badge brand">brand</span>' : '<span class="listing-badge local">local</span>') +
                    '</div>' +
                    (emp.address  ? '<div class="listing-addr">' + _esc(emp.address)  + '</div>' : '') +
                    (emp.industry ? '<div class="listing-meta">' + _esc(emp.industry) + '</div>' : '');
                container.appendChild(card);
            });
        } catch (err) {
            console.error('Failed to load cell listings:', err);
        }
    }

    // Called by h3map.js on hex click (targeting mode)
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

        var isTargeting   = mode === 'targeting';
        var isPathfinder  = mode === 'pathfinder';
        var isJobFinder   = mode === 'jobfinder';
        var isEventFinder = mode === 'eventfinder';

        // Controls
        document.getElementById('targeting-controls').style.display    = isTargeting   ? 'flex' : 'none';
        document.getElementById('pathfinder-controls').style.display   = isPathfinder  ? 'flex' : 'none';
        document.getElementById('jobfinder-controls').style.display    = isJobFinder   ? 'flex' : 'none';
        document.getElementById('eventfinder-controls').style.display  = isEventFinder ? 'flex' : 'none';

        // Sidebars
        document.getElementById('targeting-sidebar').style.display     = isTargeting   ? 'block' : 'none';
        document.getElementById('pathfinder-sidebar').style.display    = isPathfinder  ? 'block' : 'none';
        document.getElementById('jobfinder-sidebar').style.display     = isJobFinder   ? 'block' : 'none';
        document.getElementById('eventfinder-sidebar').style.display   = isEventFinder ? 'block' : 'none';

        // Map legends
        var targLegend  = document.getElementById('map-legend');
        var jobLegend   = document.getElementById('map-legend-jobs');
        var eventLegend = document.getElementById('map-legend-events');
        if (targLegend)  targLegend.style.display  = isTargeting ? 'flex' : 'none';
        if (jobLegend)   jobLegend.style.display   = isJobFinder ? 'flex' : 'none';
        if (eventLegend) eventLegend.style.display  = isEventFinder ? 'flex' : 'none';

        // Mode buttons
        document.getElementById('mode-targeting').classList.toggle('active',    isTargeting);
        document.getElementById('mode-pathfinder').classList.toggle('active',   isPathfinder);
        document.getElementById('mode-jobfinder').classList.toggle('active',    isJobFinder);
        document.getElementById('mode-eventfinder').classList.toggle('active',  isEventFinder);

        if (isTargeting) {
            if (window.pathfinderClearMarkers) window.pathfinderClearMarkers();
            if (window.jobfinder) window.jobfinder.clear();
            if (window.eventfinder) window.eventfinder.clear();
            map.setView(AUSTIN_CENTER, DEFAULT_ZOOM);
            showTopTargetsView();
            refreshMap();
            loadTargets();

        } else if (isPathfinder) {
            if (window.h3map) window.h3map.clear();
            if (window.jobfinder) window.jobfinder.clear();
            if (window.eventfinder) window.eventfinder.clear();
            map.setView(AUSTIN_CENTER, DEFAULT_ZOOM);
            if (window.pathfinderInit) window.pathfinderInit();

        } else if (isJobFinder) {
            if (window.h3map) window.h3map.clear();
            if (window.pathfinderClearMarkers) window.pathfinderClearMarkers();
            if (window.eventfinder) window.eventfinder.clear();
            map.setView(AUSTIN_CENTER, DEFAULT_ZOOM);
            _jfMode = 'remote'; // reset to default mode
            _syncLocationBtns('remote');
            // Reset hex resolution to auto and clear search/sort
            _syncResBtns('auto');
            if (window.jobfinder) window.jobfinder.setResolution('auto');
            if (window.jobfinder) window.jobfinder.resetFilters();
            refreshJobFinder();

        } else if (isEventFinder) {
            if (window.h3map) window.h3map.clear();
            if (window.pathfinderClearMarkers) window.pathfinderClearMarkers();
            if (window.jobfinder) window.jobfinder.clear();
            map.setView(AUSTIN_CENTER, DEFAULT_ZOOM);
            refreshEventFinder();
        }
    }

    // ── Location mode toggle (Job Finder) ───────────────────────────
    function _syncLocationBtns(activeMode) {
        document.querySelectorAll('#location-mode-toggle .location-btn').forEach(function (btn) {
            btn.classList.toggle('active', btn.dataset.mode === activeMode);
        });
    }

    document.querySelectorAll('#location-mode-toggle .location-btn').forEach(function (btn) {
        btn.addEventListener('click', function () {
            _jfMode = this.dataset.mode;
            _syncLocationBtns(_jfMode);
            refreshJobFinder();
        });
    });

    // ── Hex resolution toggle (Job Finder) ──────────────────────────
    function _syncResBtns(activeRes) {
        document.querySelectorAll('#hex-res-toggle .res-btn').forEach(function (btn) {
            btn.classList.toggle('active', btn.dataset.res === activeRes);
        });
    }

    document.querySelectorAll('#hex-res-toggle .res-btn').forEach(function (btn) {
        btn.addEventListener('click', function () {
            _syncResBtns(this.dataset.res);
            if (window.jobfinder) window.jobfinder.setResolution(this.dataset.res);
        });
    });

    // ── City area shortcut (Job Finder) ─────────────────────────────
    document.getElementById('jf-city-btn').addEventListener('click', function () {
        if (window.jobfinder) window.jobfinder.selectCityHex();
    });

    // ── Event listeners ─────────────────────────────────────────────
    document.getElementById('mode-targeting').addEventListener('click',  function () { switchMode('targeting'); });
    document.getElementById('mode-pathfinder').addEventListener('click', function () { switchMode('pathfinder'); });
    document.getElementById('mode-jobfinder').addEventListener('click',  function () { switchMode('jobfinder'); });
    document.getElementById('mode-eventfinder').addEventListener('click', function () { switchMode('eventfinder'); });

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

    document.getElementById('job-category-filter').addEventListener('change', function () {
        refreshJobFinder();
    });

    document.getElementById('event-category-filter').addEventListener('change', function () {
        refreshEventFinder();
    });

    document.getElementById('listings-back-btn').addEventListener('click', function () {
        showTopTargetsView();
    });

    // ── Initial load ────────────────────────────────────────────────
    loadFilters().then(function () {
        refreshMap();
        loadTargets();
    });
    loadJobCategories();

    // Expose map for pathfinder.js
    window.sharedMap = map;
})();

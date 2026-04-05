/**
 * Career Pathfinder mode — js/pathfinder.js
 *
 * Autocomplete:  loads all occupations once via /api/mobility/occupations,
 *                then filters client-side for instant, keyboard-navigable results.
 * Paths:         GET /api/mobility/paths?soc=<code>&wage_filter=up
 * Employers:     GET /api/mobility/employers?soc=<code>&lat=&lng=
 *
 * Map layer: H3 hex aggregates only — no individual dots.
 * Each career path gets its own color-coded hex layer.
 * Single click → employer popup. Double click → zoom into cell.
 * Zoom change → re-renders all cached paths at the new resolution.
 *
 * Relies on window.sharedMap (Leaflet instance) set by app.js.
 * window.pathfinderInit() is called by app.js when switching to this mode.
 */

(function () {
    'use strict';

    const API_BASE = '';

    // ── Direction colors ──────────────────────────────────────────────
    const DIR_COLOR = { up: '#4ecca3', lateral: '#f0a500', down: '#e94560' };

    function _esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function dirLabel(d) { return d === 1 ? 'up' : d === 0 ? 'lateral' : d === -1 ? 'down' : 'unknown'; }
    function dirColor(d) { return DIR_COLOR[dirLabel(d)] || '#888'; }
    function fmtWage(v)  { return v == null ? '—' : '$' + v.toFixed(0) + '/hr'; }
    function fmtGap(v)   { return v == null ? '—' : v.toFixed(2); }

    // ── Gradient color utilities ──────────────────────────────────────
    function hexToRgb(hex) {
        return [parseInt(hex.slice(1,3),16), parseInt(hex.slice(3,5),16), parseInt(hex.slice(5,7),16)];
    }
    function lerpRgb(a, b, t) {
        return [Math.round(a[0]+(b[0]-a[0])*t), Math.round(a[1]+(b[1]-a[1])*t), Math.round(a[2]+(b[2]-a[2])*t)];
    }
    function rgbToHex(rgb) {
        return '#' + rgb.map(function(v){ return ('0'+v.toString(16)).slice(-2); }).join('');
    }

    var SAME_START = hexToRgb('#4ecca3');
    var SAME_END   = hexToRgb('#555555');
    var OUT_START  = hexToRgb('#4a9eff');
    var OUT_END    = hexToRgb('#f0a500');

    function assignPathColors(paths) {
        var sameCount = paths.filter(function(p){ return p.same_cluster === true; }).length;
        var outCount  = paths.length - sameCount;
        var sameIdx = 0, outIdx = 0;
        paths.forEach(function(p) {
            var t, color;
            if (p.same_cluster === true) {
                t = sameCount > 1 ? sameIdx / (sameCount - 1) : 0;
                color = rgbToHex(lerpRgb(SAME_START, SAME_END, t));
                sameIdx++;
            } else {
                t = outCount > 1 ? outIdx / (outCount - 1) : 0;
                color = rgbToHex(lerpRgb(OUT_START, OUT_END, t));
                outIdx++;
            }
            p._color = color;
        });
    }

    // ── H3 resolution mapping ─────────────────────────────────────────
    function zoomToResolution(zoom) {
        if (zoom >= 14) return 9;
        if (zoom >= 12) return 8;
        if (zoom >= 10) return 7;
        return 6;
    }

    // ── State ─────────────────────────────────────────────────────────
    var allOccupations    = null;
    var activeSoc         = null;
    var lastSearchedSoc   = null;
    var acSelectedIdx     = -1;
    var _reqToken         = 0;

    // H3 hex state — replaces pathMarkers array
    var pathHexLayers     = {};   // keyed by dest_soc → L.layerGroup
    var pathEmployerCache = {};   // keyed by dest_soc → { employers, color }
    var _hexRenderGen     = 0;    // generation counter; stale renders are discarded

    // ── DOM refs ──────────────────────────────────────────────────────
    var searchInput = document.getElementById('job-search');
    var acEl        = document.getElementById('job-autocomplete');
    var statusEl    = document.getElementById('path-status');
    var pathsList   = document.getElementById('paths-list');

    // ── Load occupation list ──────────────────────────────────────────
    async function ensureOccupations() {
        if (allOccupations) return;
        try {
            statusEl.textContent = 'Loading occupations…';
            var resp = await fetch(API_BASE + '/api/mobility/occupations');
            var data = await resp.json();
            allOccupations = data.occupations || [];
            statusEl.textContent = allOccupations.length + ' occupations loaded';
        } catch (err) {
            statusEl.textContent = 'Could not load occupations.';
            console.error('[pathfinder] occupation load failed', err);
        }
    }

    window.pathfinderInit = function () {
        ensureOccupations();
        // Re-render cached paths at new resolution on zoom
        window.sharedMap && window.sharedMap.on('zoomend', function () {
            if (Object.keys(pathEmployerCache).length) rerenderAllPaths();
        });
    };

    // ── Autocomplete filtering ────────────────────────────────────────
    function filterOccupations(q) {
        if (!allOccupations || !q) return [];
        var lower = q.toLowerCase();
        var titlePrefix = [], titleContains = [], aliasContains = [];
        var seen = new Set();
        allOccupations.forEach(function(o) {
            var t = o.title.toLowerCase();
            if (t.startsWith(lower))       { titlePrefix.push(o);   seen.add(o.soc_code); }
            else if (t.includes(lower))    { titleContains.push(o); seen.add(o.soc_code); }
            else if (o.aliases) {
                for (var i = 0; i < o.aliases.length; i++) {
                    if (o.aliases[i].includes(lower)) { aliasContains.push(o); seen.add(o.soc_code); break; }
                }
            }
        });
        return titlePrefix.concat(titleContains).concat(aliasContains).slice(0, 10);
    }

    function showDropdown(results) {
        acEl.innerHTML = '';
        acSelectedIdx = -1;
        if (!results.length) { acEl.style.display = 'none'; return; }
        results.forEach(function(occ, idx) {
            var item = document.createElement('div');
            item.className = 'ac-item';
            item.dataset.idx = idx;
            var dot = occ.has_transitions
                ? '<span class="ac-dot ac-dot-yes" title="Transition data available"></span>'
                : '<span class="ac-dot ac-dot-no"  title="Limited transition data"></span>';
            item.innerHTML =
                dot +
                '<span class="ac-title">' + _esc(occ.title) + '</span>' +
                (occ.cluster_name ? '<span class="ac-cluster">' + _esc(occ.cluster_name) + '</span>' : '') +
                (occ.median_hourly_wage ? '<span class="ac-wage">' + fmtWage(occ.median_hourly_wage) + '</span>' : '');
            item.addEventListener('mousedown', function(e) { e.preventDefault(); selectOccupation(occ); });
            acEl.appendChild(item);
        });
        acEl.style.display = 'block';
    }

    function hideDropdown() { acEl.style.display = 'none'; acEl.innerHTML = ''; acSelectedIdx = -1; }

    function moveSelection(delta) {
        var items = acEl.querySelectorAll('.ac-item');
        if (!items.length) return;
        items[acSelectedIdx] && items[acSelectedIdx].classList.remove('ac-selected');
        acSelectedIdx = Math.max(0, Math.min(items.length - 1, acSelectedIdx + delta));
        items[acSelectedIdx].classList.add('ac-selected');
        items[acSelectedIdx].scrollIntoView({ block: 'nearest' });
    }

    function selectOccupation(occ) {
        searchInput.value = occ.title;
        activeSoc = occ.soc_code;
        hideDropdown();
        runPathfinder(occ);
    }

    // ── Input event listeners ─────────────────────────────────────────
    searchInput.addEventListener('focus', function () {
        var q = this.value.trim();
        if (q.length >= 1) showDropdown(filterOccupations(q));
        else if (allOccupations) {
            var hint = allOccupations.filter(function(o) {
                return o.has_transitions && o.median_hourly_wage != null && o.median_hourly_wage < 22;
            }).slice(0, 8);
            showDropdown(hint);
        }
    });

    searchInput.addEventListener('input', function () {
        activeSoc = null;
        var q = this.value.trim();
        if (q.length === 0) { hideDropdown(); return; }
        showDropdown(filterOccupations(q));
    });

    searchInput.addEventListener('keydown', function (e) {
        var items = acEl.querySelectorAll('.ac-item');
        if (e.key === 'ArrowDown')      { e.preventDefault(); moveSelection(1); }
        else if (e.key === 'ArrowUp')   { e.preventDefault(); moveSelection(-1); }
        else if (e.key === 'Enter') {
            e.preventDefault();
            if (acSelectedIdx >= 0 && items[acSelectedIdx])     items[acSelectedIdx].dispatchEvent(new MouseEvent('mousedown'));
            else if (items[0])                                   items[0].dispatchEvent(new MouseEvent('mousedown'));
            else if (activeSoc)                                  runPathfinderBySoc(activeSoc);
        } else if (e.key === 'Escape') { hideDropdown(); searchInput.blur(); }
    });

    searchInput.addEventListener('blur', function () { setTimeout(hideDropdown, 150); });

    function rerunSearch() {
        var soc = activeSoc || lastSearchedSoc;
        if (soc) runPathfinderBySoc(soc);
    }

    document.getElementById('search-btn').addEventListener('click', function () {
        if (activeSoc || lastSearchedSoc) {
            rerunSearch();
        } else {
            var q = searchInput.value.trim();
            var results = filterOccupations(q);
            if (results[0]) selectOccupation(results[0]);
            else statusEl.textContent = 'Select an occupation from the list.';
        }
    });

    document.getElementById('wage-filter').addEventListener('change', rerunSearch);
    document.getElementById('cluster-filter').addEventListener('change', function () {
        this.className = this.value === 'in' ? 'cf-same' : this.value === 'out' ? 'cf-out' : '';
        rerunSearch();
    });

    // ── Pathfinder flow ───────────────────────────────────────────────
    function runPathfinder(occ) {
        renderOrigin(occ);
        runPathfinderBySoc(occ.soc_code);
    }

    function renderOrigin(occ) {
        document.getElementById('pathfinder-origin').innerHTML =
            '<div class="origin-card">' +
            '<div class="origin-title">Starting from: <strong>' + _esc(occ.title) + '</strong></div>' +
            '<div class="origin-meta">SOC ' + _esc(occ.soc_code) +
            (occ.median_hourly_wage ? ' · ' + fmtWage(occ.median_hourly_wage) + ' median' : '') +
            (occ.cluster_name ? ' · ' + _esc(occ.cluster_name) : '') +
            (occ.has_transitions === false ? ' · <span style="color:#f0a500">limited data</span>' : '') +
            '</div></div>';
    }

    async function runPathfinderBySoc(soc) {
        var wageFilter    = document.getElementById('wage-filter').value;
        var clusterFilter = document.getElementById('cluster-filter').value;

        var url = API_BASE + '/api/mobility/paths?soc=' + encodeURIComponent(soc) + '&limit=15';
        if (wageFilter)              url += '&wage_filter=' + wageFilter;
        if (clusterFilter === 'in')  url += '&same_cluster=1';
        if (clusterFilter === 'out') url += '&same_cluster=0';

        lastSearchedSoc = soc;
        var myToken = ++_reqToken;
        clearPathLayers();
        pathsList.innerHTML = '<div class="path-card"><div class="path-details">Loading…</div></div>';
        statusEl.textContent = 'Loading paths…';

        try {
            var resp = await fetch(url);
            var data = await resp.json();
            if (myToken !== _reqToken) return;

            var paths = data.paths || [];
            assignPathColors(paths);
            renderPaths(paths, data.origin_soc_used !== soc ? data.origin_soc_used : null);
            statusEl.textContent = paths.length ? paths.length + ' paths found' : 'No paths found.';
            if (paths.length) plotPathEmployers(paths);
        } catch (err) {
            if (myToken !== _reqToken) return;
            pathsList.innerHTML = '<div class="path-card"><div class="path-details">Error loading paths.</div></div>';
            statusEl.textContent = 'Error loading paths.';
            console.error(err);
        }
    }

    function renderPaths(paths, fallbackSoc) {
        var cf = document.getElementById('cluster-filter').value;
        if (cf === 'in')  paths = paths.filter(function(p){ return p.same_cluster === true; });
        if (cf === 'out') paths = paths.filter(function(p){ return p.same_cluster !== true; });

        pathsList.innerHTML = '';

        if (fallbackSoc) {
            var banner = document.createElement('div');
            banner.className = 'path-fallback-note';
            banner.textContent = 'Using closest related occupation (SOC ' + fallbackSoc + ') for transitions.';
            pathsList.appendChild(banner);
        }

        if (!paths.length) {
            pathsList.innerHTML += '<div class="path-card"><div class="path-details">No transition data for this occupation.</div></div>';
            return;
        }

        paths.forEach(function(p, i) {
            var wageColor = dirColor(p.wage_direction);
            var pathColor = p._color || '#888';
            var card = document.createElement('div');
            card.className = 'path-card';
            card.dataset.soc = p.dest_soc;
            card.style.borderLeftColor = pathColor;
            card.style.borderLeftWidth = '3px';
            card.style.borderLeftStyle = 'solid';

            var label = p.same_cluster === true ? 'Same industry' : 'Out of industry';
            var badge = '<span class="cluster-badge" style="color:' + pathColor + ';border-color:' + pathColor + '44;background:' + pathColor + '18">' + label + '</span>';

            card.innerHTML =
                '<div class="path-title">' + (i+1) + '. ' + _esc(p.dest_title || p.dest_soc) + badge + '</div>' +
                '<div class="path-direction" style="color:' + wageColor + '">' +
                dirLabel(p.wage_direction).toUpperCase() +
                (p.wage_change_dollars != null ? ' · ' + (p.wage_change_dollars >= 0 ? '+' : '') + fmtWage(p.wage_change_dollars) : '') +
                (p.dest_median_wage ? ' → ' + fmtWage(p.dest_median_wage) : '') +
                '</div>' +
                '<div class="path-details">' +
                'Score: ' + (p.ranking_score != null ? p.ranking_score.toFixed(2) : '—') +
                ' · Gap: ' + fmtGap(p.avg_skill_gap) +
                (p.dest_traj_3yr != null ? ' · 3yr: +' + p.dest_traj_3yr.toFixed(0) + '%' : '') +
                (p.requires_license ? ' · <span style="color:#f0a500">new license</span>' : '') +
                (p.dest_cluster ? ' · ' + _esc(p.dest_cluster) : '') +
                '</div>';

            card.addEventListener('click', function () {
                highlightDestSoc(p.dest_soc);
                document.querySelectorAll('.path-card').forEach(function(c){ c.classList.remove('active'); });
                card.classList.add('active');
            });

            pathsList.appendChild(card);
        });
    }

    // ── H3 hex layer management ───────────────────────────────────────

    function clearPathLayers() {
        var map = window.sharedMap;
        _hexRenderGen++;
        Object.keys(pathHexLayers).forEach(function(soc) {
            if (map) map.removeLayer(pathHexLayers[soc]);
        });
        pathHexLayers     = {};
        pathEmployerCache = {};
    }

    // Exposed so app.js switchMode can clean up when leaving pathfinder
    window.pathfinderClearMarkers = clearPathLayers;

    function aggregateToHex(employers, resolution) {
        var cells = {};
        employers.forEach(function(emp) {
            if (!emp.lat || !emp.lng) return;
            var cellId = h3.latLngToCell(emp.lat, emp.lng, resolution);
            if (!cells[cellId]) cells[cellId] = [];
            cells[cellId].push(emp);
        });
        return cells;
    }

    function buildHexLayer(employers, color, resolution) {
        var map = window.sharedMap;
        var cells = aggregateToHex(employers, resolution);
        var cellIds = Object.keys(cells);
        if (!cellIds.length) return null;

        var maxCount = Math.max.apply(null, cellIds.map(function(id){ return cells[id].length; }));

        var polys = [];
        cellIds.forEach(function(cellId) {
            var emps     = cells[cellId];
            var boundary = h3.cellToBoundary(cellId);
            var baseOpacity = 0.1 + 0.6 * Math.pow(emps.length / Math.max(maxCount, 1), 0.45);

            var poly = L.polygon(boundary, {
                fillColor:   color,
                fillOpacity: baseOpacity,
                color:       color,
                weight:      0.8,
                opacity:     0.5,
            });
            poly._baseOpacity = baseOpacity;  // stored for highlight/restore

            poly.bindTooltip(
                emps.length + ' employer' + (emps.length !== 1 ? 's' : ''),
                { sticky: true, className: 'h3-tooltip' }
            );

            // Single click: popup listing employers in this cell
            poly.on('click', function(e) {
                L.DomEvent.stopPropagation(e);
                var names = emps.slice(0, 12).map(function(e) {
                    return '<div style="padding:2px 0">' + e.name + '</div>';
                }).join('');
                var more  = emps.length > 12
                    ? '<div style="color:#888;font-size:0.78rem;margin-top:4px">+' + (emps.length - 12) + ' more</div>'
                    : '';
                L.popup().setLatLng(L.latLngBounds(boundary).getCenter())
                    .setContent('<strong>' + emps.length + ' employer' + (emps.length !== 1 ? 's' : '') + '</strong>' + names + more)
                    .openOn(map);
            });

            // Double click: zoom into cell
            poly.on('dblclick', function(e) {
                L.DomEvent.stopPropagation(e);
                map.fitBounds(L.latLngBounds(boundary).pad(0.15));
            });

            polys.push(poly);
        });

        return L.layerGroup(polys);
    }

    function renderCachedPath(soc) {
        var map = window.sharedMap;
        if (!map || !pathEmployerCache[soc]) return;

        // Remove stale layer for this SOC
        if (pathHexLayers[soc]) { map.removeLayer(pathHexLayers[soc]); delete pathHexLayers[soc]; }

        var cached  = pathEmployerCache[soc];
        var res     = zoomToResolution(map.getZoom());
        var layer   = buildHexLayer(cached.employers, cached.color, res);
        if (layer) { layer.addTo(map); pathHexLayers[soc] = layer; }
    }

    function rerenderAllPaths() {
        Object.keys(pathEmployerCache).forEach(renderCachedPath);
    }

    // ── Fetch and plot employer hex layers ────────────────────────────
    const REGION_LAT    = 30.2672;
    const REGION_LNG    = -97.7431;
    const REGION_RADIUS = 30;

    async function plotPathEmployers(paths) {
        clearPathLayers();
        var map = window.sharedMap;
        if (!map) return;

        var myToken  = _reqToken;
        var myGen    = ++_hexRenderGen;
        var allLatLngs = [];

        for (var i = 0; i < paths.length; i++) {
            if (myToken !== _reqToken || myGen !== _hexRenderGen) return;

            var p     = paths[i];
            var color = p._color || '#888';

            try {
                var url = API_BASE + '/api/mobility/employers?soc=' + encodeURIComponent(p.dest_soc) +
                    '&lat=' + REGION_LAT + '&lng=' + REGION_LNG +
                    '&radius=' + REGION_RADIUS + '&limit=200';
                var resp = await fetch(url);
                var data = await resp.json();
                if (myToken !== _reqToken || myGen !== _hexRenderGen) return;

                var employers = (data.employers || []).filter(function(e){ return e.lat && e.lng; });
                if (!employers.length) continue;

                // Cache for zoom-based re-renders
                pathEmployerCache[p.dest_soc] = { employers: employers, color: color };

                // Render at current zoom resolution
                var res   = zoomToResolution(map.getZoom());
                var layer = buildHexLayer(employers, color, res);
                if (layer) { layer.addTo(map); pathHexLayers[p.dest_soc] = layer; }

                employers.forEach(function(e) { allLatLngs.push([e.lat, e.lng]); });
            } catch (err) {
                console.warn('[pathfinder] employer load failed for ' + p.dest_soc, err);
            }
        }

        // Fit map to all loaded employer locations
        if (allLatLngs.length) {
            map.fitBounds(L.latLngBounds(allLatLngs).pad(0.1));
        }
    }

    // ── Highlight selected path, dim others ───────────────────────────
    function highlightDestSoc(soc) {
        Object.keys(pathHexLayers).forEach(function(s) {
            var match = s === soc;
            pathHexLayers[s].eachLayer(function(poly) {
                if (match) {
                    poly.setStyle({ fillOpacity: Math.min((poly._baseOpacity || 0.4) + 0.25, 0.9), opacity: 0.9 });
                    poly.bringToFront();
                } else {
                    poly.setStyle({ fillOpacity: 0.04, opacity: 0.08 });
                }
            });
        });
    }

})();

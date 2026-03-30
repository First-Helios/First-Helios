/**
 * h3map.js — H3 hexagonal rendering layer (always active, no dot fallback)
 *
 * Resolution scales with zoom:
 *   zoom  8–9  → res 6  (~83 cells,  city overview)
 *   zoom 10–11 → res 7  (~453 cells, neighborhood)
 *   zoom 12–13 → res 8  (~1915 cells, corridor)
 *   zoom 14+   → res 9  (~8000 cells, block)
 *
 * Clicking a hex fires window.onHexClick(cellId, resolution, count, brandCount)
 * so app.js can populate the listings sidebar.
 *
 * Exposes window.h3map for app.js integration.
 */

(function () {
    'use strict';

    function zoomToResolution(zoom) {
        if (zoom >= 14) return 9;
        if (zoom >= 12) return 8;
        if (zoom >= 10) return 7;
        return 6;
    }

    // Brand-heavy → amber, local-heavy → purple, blended between
    function hexFillColor(brandCount, totalCount) {
        var ratio = totalCount > 0 ? brandCount / totalCount : 0;
        var r = Math.round(0xf0 * ratio + 0x6c * (1 - ratio));
        var g = Math.round(0xa5 * ratio + 0x5c * (1 - ratio));
        var b = Math.round(0x00 * ratio + 0xe7 * (1 - ratio));
        return 'rgb(' + r + ',' + g + ',' + b + ')';
    }

    function hexOpacity(count, maxCount) {
        var t = maxCount > 0 ? count / maxCount : 0;
        return 0.12 + 0.62 * Math.pow(t, 0.45);
    }

    var hexLayer = null;
    var renderGen = 0;   // incremented on every render call; stale responses are discarded

    function clearHexLayer() {
        var map = window.sharedMap;
        if (hexLayer && map) map.removeLayer(hexLayer);
        hexLayer = null;
    }

    function renderHexLayer(resolution, industry, chain) {
        var map = window.sharedMap;
        if (!map) return Promise.resolve();

        var url = '/api/h3-map?resolution=' + resolution + '&region=austin_tx';
        if (industry) url += '&industry=' + encodeURIComponent(industry);
        if (chain)    url += '&chain='    + encodeURIComponent(chain);

        // Clear immediately and stamp this request with the current generation
        if (hexLayer) { map.removeLayer(hexLayer); hexLayer = null; }
        var myGen = ++renderGen;

        return fetch(url).then(function (resp) {
            return resp.json();
        }).then(function (data) {
            // A newer render was requested while this one was in flight — discard
            if (myGen !== renderGen) return;
            if (data.status !== 'ok') return;

            var maxCount = 1;
            data.cells.forEach(function (c) { if (c.count > maxCount) maxCount = c.count; });

            var polys = [];
            data.cells.forEach(function (cell) {
                var boundary = h3.cellToBoundary(cell.cell_id);
                var color    = hexFillColor(cell.brand_count, cell.count);
                var opacity  = hexOpacity(cell.count, maxCount);

                var poly = L.polygon(boundary, {
                    fillColor:   color,
                    fillOpacity: opacity,
                    color:       '#ffffff',
                    weight:      0.6,
                    opacity:     0.25,
                });

                var brandPct = cell.count > 0 ? Math.round(100 * cell.brand_count / cell.count) : 0;
                poly.bindTooltip(
                    cell.count + ' employers · ' + brandPct + '% brand',
                    { sticky: true, className: 'h3-tooltip' }
                );

                // Single click: load listings in sidebar
                poly.on('click', function (e) {
                    L.DomEvent.stopPropagation(e);
                    if (typeof window.onHexClick === 'function') {
                        window.onHexClick(cell.cell_id, resolution, cell.count, cell.brand_count);
                    }
                });

                // Double click: zoom into the cell
                poly.on('dblclick', function (e) {
                    L.DomEvent.stopPropagation(e);
                    map.fitBounds(L.latLngBounds(boundary).pad(0.15));
                });

                polys.push(poly);
            });

            hexLayer = L.layerGroup(polys).addTo(map);

            var badge = document.getElementById('store-count');
            if (badge) {
                var total = data.cells.reduce(function (s, c) { return s + c.count; }, 0);
                badge.textContent = data.cell_count + ' cells · ' + total + ' employers';
            }
        }).catch(function (err) {
            console.error('[h3map] fetch failed:', err);
        });
    }

    // ── Public API ────────────────────────────────────────────────────────────

    window.h3map = {
        /** Render hex layer at the resolution matching current zoom + filters. */
        refresh: function (industry, chain) {
            var map = window.sharedMap;
            if (!map) return;
            var res = zoomToResolution(map.getZoom());
            renderHexLayer(res, industry, chain);
        },

        /** Remove the hex layer and cancel any in-flight render. */
        clear: function () { renderGen++; clearHexLayer(); },
    };

})();

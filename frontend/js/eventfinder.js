/**
 * eventfinder.js — Events map layer and listing sidebar
 *
 * H3 hex layer: aggregates events by h3_r7/r8 for events with coordinates.
 * Sidebar: paginated event cards; clicking a hex shows events in that area.
 *
 * Exposes window.eventfinder for app.js integration.
 */

(function () {
    'use strict';

    var _state = { region: 'austin_tx', category: '' };

    var _hexLayer  = null;
    var _cellPolys = {};
    var _renderGen = 0;
    var _selectedCell = null;
    var _origStyle = null;

    var _listPage  = 1;
    var _listTotal = 0;
    var _PAGE_SIZE = 20;

    // ── Resolution ────────────────────────────────────────────────────────────

    function _evtRes(zoom) { return zoom >= 12 ? 8 : 7; }

    function _hexOpacity(count, maxCount) {
        var t = maxCount > 0 ? count / maxCount : 0;
        return 0.14 + 0.60 * Math.pow(t, 0.40);
    }

    // ── Hex layer ─────────────────────────────────────────────────────────────

    function _clearHex() {
        var map = window.sharedMap;
        if (_hexLayer && map) map.removeLayer(_hexLayer);
        _hexLayer  = null;
        _cellPolys = {};
    }

    function _renderHex(resolution, region, category) {
        var map = window.sharedMap;
        if (!map) return;

        var url = '/api/events/h3-map?resolution=' + resolution
                + '&region=' + encodeURIComponent(region);
        if (category) url += '&category=' + encodeURIComponent(category);

        _clearHex();
        var myGen = ++_renderGen;

        fetch(url)
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (myGen !== _renderGen) return;
                if (data.status !== 'ok') return;

                var cells = data.cells;
                if (!cells.length) return;

                var maxCount = 0;
                cells.forEach(function (c) { if (c.count > maxCount) maxCount = c.count; });

                var group = L.featureGroup();

                cells.forEach(function (c) {
                    var boundary;
                    try { boundary = h3.cellToBoundary(c.cell_id); }
                    catch (e) { return; }

                    var latlngs = boundary.map(function (b) { return [b[0], b[1]]; });
                    var opacity = _hexOpacity(c.count, maxCount);

                    var poly = L.polygon(latlngs, {
                        color: '#ff6b6b',
                        weight: 1,
                        opacity: 0.6,
                        fillColor: '#ff6b6b',
                        fillOpacity: opacity,
                    });

                    poly.cellId = c.cell_id;
                    poly.cellCount = c.count;

                    poly.on('click', function () {
                        _showCellPanel(c.cell_id, c.count, resolution);
                    });

                    poly.on('mouseover', function () {
                        this.setStyle({ weight: 2, opacity: 1.0 });
                        this.bindTooltip(c.count + ' events').openTooltip();
                    });
                    poly.on('mouseout', function () {
                        if (_selectedCell !== c.cell_id) {
                            this.setStyle({ weight: 1, opacity: 0.6 });
                        }
                        this.unbindTooltip();
                    });

                    _cellPolys[c.cell_id] = poly;
                    group.addLayer(poly);
                });

                _hexLayer = group;
                map.addLayer(group);

                var badge = document.getElementById('event-count');
                if (badge) {
                    var total = 0;
                    cells.forEach(function (c) { total += c.count; });
                    badge.textContent = total + ' events';
                }
            })
            .catch(function (err) {
                console.error('[eventfinder] hex fetch failed:', err);
            });
    }

    // ── Sidebar: default list ─────────────────────────────────────────────────

    function _showDefaultPanel() {
        var defPanel  = document.getElementById('ef-default-panel');
        var cellPanel = document.getElementById('ef-cell-panel');
        if (defPanel)  defPanel.style.display  = 'block';
        if (cellPanel) cellPanel.style.display = 'none';

        // Reset selected hex
        if (_selectedCell && _cellPolys[_selectedCell] && _origStyle) {
            _cellPolys[_selectedCell].setStyle(_origStyle);
        }
        _selectedCell = null;
        _origStyle = null;

        _listPage = 1;
        _loadList();
    }

    function _loadList() {
        var url = '/api/events/listings?region=' + encodeURIComponent(_state.region)
                + '&page=' + _listPage
                + '&limit=' + _PAGE_SIZE;
        if (_state.category) url += '&category=' + encodeURIComponent(_state.category);

        var freeFilter = document.getElementById('ef-free-filter');
        if (freeFilter && freeFilter.value) url += '&is_free=' + freeFilter.value;

        fetch(url)
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.status !== 'ok') return;
                _listTotal = data.total || 0;

                var container = document.getElementById('ef-list');
                if (!container) return;

                if (_listPage === 1) container.innerHTML = '';

                (data.events || []).forEach(function (e) {
                    container.appendChild(_buildCard(e));
                });

                if (!data.events || !data.events.length) {
                    if (_listPage === 1) {
                        container.innerHTML = '<div class="listing-card"><div class="listing-name">No events found.</div></div>';
                    }
                }

                var loadMore = document.getElementById('ef-load-more');
                if (loadMore) {
                    loadMore.style.display = (_listPage * _PAGE_SIZE < _listTotal) ? 'block' : 'none';
                }
            })
            .catch(function (err) { console.error('[eventfinder] list fetch failed:', err); });
    }

    // ── Sidebar: cell panel ────────────────────────────────────────────────────

    function _showCellPanel(cellId, count, resolution) {
        var defPanel  = document.getElementById('ef-default-panel');
        var cellPanel = document.getElementById('ef-cell-panel');
        if (defPanel)  defPanel.style.display  = 'none';
        if (cellPanel) cellPanel.style.display = 'block';

        // Highlight selected hex
        if (_selectedCell && _cellPolys[_selectedCell] && _origStyle) {
            _cellPolys[_selectedCell].setStyle(_origStyle);
        }
        _selectedCell = cellId;
        if (_cellPolys[cellId]) {
            _origStyle = { color: '#ff6b6b', weight: 1, opacity: 0.6, fillOpacity: _cellPolys[cellId].options.fillOpacity };
            _cellPolys[cellId].setStyle({ color: '#ff6b6b', weight: 3, opacity: 1.0, fillOpacity: 0.9 });
        }

        var title = document.getElementById('ef-cell-title');
        if (title) title.textContent = count + ' events in this area';

        var url = '/api/events/listings?region=' + encodeURIComponent(_state.region)
                + '&h3_cell=' + encodeURIComponent(cellId)
                + '&resolution=' + resolution
                + '&limit=50';
        if (_state.category) url += '&category=' + encodeURIComponent(_state.category);

        var container = document.getElementById('ef-cell-list');
        if (container) container.innerHTML = '<div class="listing-card"><div class="listing-name">Loading…</div></div>';

        fetch(url)
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (!container) return;
                container.innerHTML = '';
                if (data.status !== 'ok' || !(data.events || []).length) {
                    container.innerHTML = '<div class="listing-card"><div class="listing-name">No events found.</div></div>';
                    return;
                }
                (data.events || []).forEach(function (e) {
                    container.appendChild(_buildCard(e));
                });
            })
            .catch(function (err) { console.error('[eventfinder] cell fetch failed:', err); });
    }

    // ── Card builder ──────────────────────────────────────────────────────────

    function _buildCard(e) {
        var card = document.createElement('div');
        card.className = 'listing-card';

        var dateStr = '';
        if (e.start_time) {
            try {
                var d = new Date(e.start_time);
                dateStr = d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
                var timeStr = d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
                dateStr += ' · ' + timeStr;
            } catch (ex) { dateStr = e.start_time; }
        }

        var priceStr = '';
        if (e.is_free) {
            priceStr = '<span class="listing-badge" style="background:#22c55e;color:#fff">Free</span>';
        } else if (e.price_min != null) {
            priceStr = '$' + e.price_min.toFixed(0);
            if (e.price_max != null && e.price_max !== e.price_min) {
                priceStr += '–$' + e.price_max.toFixed(0);
            }
        }

        var catBadge = e.category
            ? '<span class="listing-badge">' + e.category + '</span>'
            : '';

        var venueStr = e.raw_venue_name
            ? '<div class="listing-addr">' + e.raw_venue_name + '</div>'
            : '';

        var mapPin = '';
        if (e.lat != null && e.lng != null) {
            mapPin = '<span class="jf-map-pin" data-lat="' + e.lat + '" data-lng="' + e.lng + '" title="Show on map" style="cursor:pointer;margin-left:6px">📍</span>';
        }

        var links = '';
        if (e.source_url) {
            links += '<a href="' + e.source_url + '" target="_blank" rel="noopener" class="listing-link">Details ↗</a>';
        }
        if (e.ticket_url && e.ticket_url !== e.source_url) {
            links += ' <a href="' + e.ticket_url + '" target="_blank" rel="noopener" class="listing-link">Tickets ↗</a>';
        }

        card.innerHTML =
            '<div class="listing-header" style="display:flex;justify-content:space-between;align-items:center">' +
                '<div class="listing-name">' + e.title + mapPin + '</div>' +
                '<div>' + catBadge + ' ' + priceStr + '</div>' +
            '</div>' +
            (dateStr ? '<div class="listing-meta">' + dateStr + '</div>' : '') +
            venueStr +
            (e.description ? '<div class="listing-meta" style="opacity:0.7;max-height:3em;overflow:hidden">' + e.description.substring(0, 200) + '</div>' : '') +
            (links ? '<div style="margin-top:4px">' + links + '</div>' : '');

        // Map pin click
        var pin = card.querySelector('.jf-map-pin');
        if (pin) {
            pin.addEventListener('click', function (ev) {
                ev.stopPropagation();
                var map = window.sharedMap;
                if (map) map.flyTo([parseFloat(this.dataset.lat), parseFloat(this.dataset.lng)], 15);
            });
        }

        return card;
    }

    // ── Event listeners (sidebar) ─────────────────────────────────────────────

    document.addEventListener('DOMContentLoaded', function () {
        var backBtn = document.getElementById('ef-back-btn');
        if (backBtn) backBtn.addEventListener('click', _showDefaultPanel);

        var loadMore = document.getElementById('ef-load-more');
        if (loadMore) loadMore.addEventListener('click', function () {
            _listPage++;
            _loadList();
        });

        var freeFilter = document.getElementById('ef-free-filter');
        if (freeFilter) freeFilter.addEventListener('change', function () {
            _listPage = 1;
            _loadList();
        });
    });

    // ── Public API ────────────────────────────────────────────────────────────

    window.eventfinder = {
        refresh: function (region, category) {
            _state.region   = region   || 'austin_tx';
            _state.category = category || '';

            var map = window.sharedMap;
            if (!map) return;

            var res = _evtRes(map.getZoom());
            _renderHex(res, _state.region, _state.category);
            _showDefaultPanel();
        },

        clear: function () {
            _renderGen++;
            _clearHex();
        },

        onZoom: function () {
            var map = window.sharedMap;
            if (!map) return;
            var res = _evtRes(map.getZoom());
            _renderHex(res, _state.region, _state.category);
        },
    };
})();

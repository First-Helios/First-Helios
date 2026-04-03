/**
 * jobfinder.js — Job Finder map layer and listing sidebar
 *
 * H3 hex layer: aggregates job_postings by h3_r7/r8 for jobs with coordinates.
 * Sidebar: paginated job cards for remote jobs (default) or a clicked hex cell.
 *
 * Location mode toggle (controlled by app.js via jobfinder.refresh):
 *   local  — hex layer + sidebar list of local jobs; clicking hex zooms to cell
 *   remote — sidebar list of remote jobs; no hex layer
 *   all    — hex layer (jobs with coords) + sidebar list of all jobs
 *
 * Resolution override (controlled by app.js via jobfinder.setResolution):
 *   auto   — resolution tracks zoom level (default)
 *   8      — Small hexes (r8)
 *   7      — Med hexes (r7)
 *   6      — Large hexes (r6, aggregated from r7 server-side)
 *
 * Exposes window.jobfinder for app.js integration.
 */

(function () {
    'use strict';

    // ── Internal state ────────────────────────────────────────────────────────
    var _state = { region: 'austin_tx', category: '', mode: 'remote', sort: 'date', q: '', wageMin: '', wageMax: '', postedWithin: '', timeType: '' };

    // ── Hex layer ─────────────────────────────────────────────────────────────
    var _hexLayer    = null;
    var _cellPolys   = {};     // cell_id → L.polygon, for hover-to-glow
    var _renderGen   = 0;
    var _selectedCell = null;  // currently selected cell_id for visual highlight
    var _resOverride = null;   // null = auto; 6, 7, or 8 = manual override

    var AUSTIN_LAT = 30.2672;
    var AUSTIN_LNG = -97.7431;

    // JobPosting only has h3_r7 and h3_r8 — clamp zoom-derived resolution
    function _jobRes(zoom) {
        if (_resOverride !== null) return _resOverride;
        return zoom >= 12 ? 8 : 7;
    }

    function _hexOpacity(count, maxCount) {
        var t = maxCount > 0 ? count / maxCount : 0;
        return 0.14 + 0.60 * Math.pow(t, 0.40);
    }

    function _clearHex() {
        var map = window.sharedMap;
        if (_hexLayer && map) map.removeLayer(_hexLayer);
        _hexLayer  = null;
        _cellPolys = {};
    }

    function _renderHex(resolution, region, category, mode) {
        var map = window.sharedMap;
        if (!map) return;

        // r6 is not stored in DB — fetch r7 and aggregate client-side
        var aggToR6  = resolution <= 6;
        var fetchRes = aggToR6 ? 7 : resolution;

        var url = '/api/jobs/h3-map?resolution=' + fetchRes
                + '&region='   + encodeURIComponent(region)
                + '&mode='     + encodeURIComponent(mode);
        if (category) url += '&category=' + encodeURIComponent(category);

        _clearHex();
        var myGen = ++_renderGen;

        fetch(url)
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (myGen !== _renderGen) return;
                if (data.status !== 'ok') return;

                // Aggregate r7 → r6 client-side when Large is selected
                var cells = data.cells;
                if (aggToR6) {
                    var r6map = {};
                    cells.forEach(function (c) {
                        var parent = h3.cellToParent(c.cell_id, 6);
                        if (!r6map[parent]) r6map[parent] = 0;
                        r6map[parent] += c.count;
                    });
                    cells = Object.keys(r6map).map(function (k) {
                        return { cell_id: k, count: r6map[k] };
                    });
                }

                // Pre-compute the city-center cell at this resolution so we can
                // highlight it differently — it aggregates all city-geocoded jobs.
                var cityCell = h3.latLngToCell(AUSTIN_LAT, AUSTIN_LNG, resolution);

                var maxCount = 1;
                cells.forEach(function (c) { if (c.count > maxCount) maxCount = c.count; });

                _cellPolys = {};
                var polys = [];
                cells.forEach(function (cell) {
                    var boundary  = h3.cellToBoundary(cell.cell_id);
                    var isCity    = (cell.cell_id === cityCell);

                    var origStyle = {
                        fillColor:   isCity ? '#f0a500' : '#4ecca3',
                        fillOpacity: _hexOpacity(cell.count, maxCount),
                        color:       isCity ? '#f0a500' : '#ffffff',
                        weight:      isCity ? 1.5 : 0.6,
                        opacity:     isCity ? 0.70 : 0.25,
                    };
                    var poly = L.polygon(boundary, origStyle);
                    poly._origStyle = origStyle;
                    _cellPolys[cell.cell_id] = poly;

                    var tip = cell.count + ' job' + (cell.count !== 1 ? 's' : '') + ' · click to view';
                    if (isCity) tip = '📍 ' + cell.count + ' Austin-area jobs · click to view';
                    poly.bindTooltip(tip, { sticky: true, className: 'h3-tooltip' });

                    poly.on('click', function (e) {
                        L.DomEvent.stopPropagation(e);
                        _showCellPanel(cell.cell_id, resolution, cell.count, isCity);
                    });

                    poly.on('dblclick', function (e) {
                        L.DomEvent.stopPropagation(e);
                        map.fitBounds(L.latLngBounds(boundary).pad(0.15));
                    });

                    polys.push(poly);
                });

                _hexLayer = L.layerGroup(polys).addTo(map);

                var badge = document.getElementById('job-count');
                if (badge) {
                    var total = cells.reduce(function (s, c) { return s + c.count; }, 0);
                    badge.textContent = cells.length + ' areas · ' + total + ' jobs';
                }
            })
            .catch(function (err) { console.error('[jobfinder] hex fetch failed:', err); });
    }

    // ── Job card builder ──────────────────────────────────────────────────────

    var _SOURCE_LABELS = {
        'jobspy':               'LinkedIn / Indeed',
        'serpapi_google_jobs':  'Google Jobs',
        'jobicy':               'Jobicy',
        'theirstack':           'TheirStack',
        'workday_gov':          'austintexas.gov',
        'careers_api':          'Workday',
        'usajobs':              'USAJobs',
        'rapidapi_activejobs':  'ActiveJobs',
        'juju':                 'Juju',
        'spiritpool_indeed':    'via SpiritPool (Indeed)',
        'spiritpool_linkedin':  'via SpiritPool (LinkedIn)',
        'spiritpool_glassdoor': 'via SpiritPool (Glassdoor)',
        'spiritpool_google':    'via SpiritPool (Google Maps)',
        'spiritpool_ziprecruiter': 'via SpiritPool (ZipRecruiter)',
        'spiritpool_apply':     'via SpiritPool (Careers)',
        'spiritpool_www':       'via SpiritPool (Google)',
    };

    function _esc(s) {
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function _daysAgo(isoDate) {
        if (!isoDate) return null;
        var d = Math.floor((Date.now() - new Date(isoDate)) / 86400000);
        return d === 0 ? 'today' : d + 'd ago';
    }

    function _glowCellId(job) {
        // Returns the cell ID at the current map resolution for a job.
        var res = window.sharedMap ? _jobRes(window.sharedMap.getZoom()) : 7;
        if (res <= 6) {
            return job.h3_r7 ? h3.cellToParent(job.h3_r7, 6) : null;
        }
        return job['h3_r' + res] || null;
    }

    function _buildCard(job) {
        var card = document.createElement('div');
        card.className = 'job-card';
        if (job.h3_r7) card.dataset.h3r7 = job.h3_r7;
        if (job.h3_r8) card.dataset.h3r8 = job.h3_r8;

        var d = job.detail || {};

        // ── Employer header row ───────────────────────────────────────────
        var emp = '<div class="job-employer">' + _esc(job.employer || '—');
        if (job.is_remote) emp += '<span class="listing-badge remote">remote</span>';
        // time_type badge with job_type fallback
        var typeLabel = d.time_type || d.job_type;
        if (typeLabel) emp += '<span class="listing-badge time-type">' + _esc(typeLabel) + '</span>';
        var srcLabel = _SOURCE_LABELS[job.source] || job.source;
        if (srcLabel) emp += '<span class="listing-badge source">' + _esc(srcLabel) + '</span>';
        // Date pinned to header row
        var ago = _daysAgo(job.posted_date);
        if (ago) emp += '<span class="listing-badge" style="margin-left:auto;opacity:0.7;font-size:11px">' + _esc(ago) + '</span>';
        // Map pin link
        if (job.lat && job.lng) {
            emp += '<span class="listing-badge map-pin" data-lat="' + job.lat + '" data-lng="' + job.lng
                 + '" title="Fly to location" style="cursor:pointer">📍</span>';
        }
        emp += '</div>';

        var title = job.role_title
            ? '<div class="job-title">' + _esc(job.role_title) + '</div>'
            : '';

        // Wage: show both hourly and yearly; fall back to raw pay range text
        var wage = '';
        if (job.wage || job.wage_yr) {
            var wageParts = [];
            if (job.wage) wageParts.push(_esc(job.wage));
            if (job.wage_yr) wageParts.push('<span class="job-wage-alt">' + _esc(job.wage_yr) + '</span>');
            wage = '<div class="job-wage">' + wageParts.join(' <span class="job-wage-sep">·</span> ') + '</div>';
        } else if (d.pay_range_raw) {
            wage = '<div class="job-wage">' + _esc(d.pay_range_raw) + '</div>';
        }

        var meta = [];
        if (job.industry)    meta.push(job.industry);
        if (d.location_detail) {
            meta.push(d.location_detail.length > 60 ? d.location_detail.slice(0, 60) + '…' : d.location_detail);
        } else if (job.raw_address) {
            meta.push(job.raw_address.length > 60 ? job.raw_address.slice(0, 60) + '…' : job.raw_address);
        }
        if (d.days_and_hours) {
            meta.push('🕐 ' + (d.days_and_hours.length > 50 ? d.days_and_hours.slice(0, 50) + '…' : d.days_and_hours));
        }
        var metaLine = meta.length
            ? '<div class="job-meta">' + _esc(meta.join(' · ')) + '</div>'
            : '';

        // Job excerpt (description snippet)
        var excerpt = '';
        if (job.excerpt) {
            var snippetText = job.excerpt.length > 200 ? job.excerpt.slice(0, 200) + '…' : job.excerpt;
            excerpt = '<div class="job-excerpt">' + _esc(snippetText) + '</div>';
        }

        // Detail sections (expandable)
        var detailHtml = '';
        var sections = [];
        if (d.minimum_qualifications) sections.push({ label: 'Minimum Qualifications', text: d.minimum_qualifications });
        if (d.education)              sections.push({ label: 'Education', text: d.education });
        if (d.ksa)                    sections.push({ label: 'Knowledge, Skills & Abilities', text: d.ksa });
        if (d.preferred_qualifications) sections.push({ label: 'Preferred Qualifications', text: d.preferred_qualifications });
        if (d.licenses)               sections.push({ label: 'Licenses & Certifications', text: d.licenses });
        if (d.notes_to_candidate)     sections.push({ label: 'Notes to Candidate', text: d.notes_to_candidate });

        if (sections.length) {
            detailHtml = '<div class="job-detail-toggle">Details ▾</div>'
                       + '<div class="job-detail-body" style="display:none">';
            for (var i = 0; i < sections.length; i++) {
                detailHtml += '<div class="job-detail-section">'
                            + '<div class="job-detail-label">' + _esc(sections[i].label) + '</div>'
                            + '<div class="job-detail-text">' + _esc(sections[i].text) + '</div>'
                            + '</div>';
            }
            detailHtml += '</div>';
        }

        // Prefer referral_url (earns payout) over source_url (direct link)
        var applyUrl = job.referral_url || job.source_url;
        var apply = applyUrl
            ? '<div class="job-actions"><a class="apply-link" href="' + _esc(applyUrl)
              + '" target="_blank" rel="noopener noreferrer">Apply →</a></div>'
            : '';

        card.innerHTML = emp + title + wage + metaLine + excerpt + detailHtml + apply;

        // Wire toggle
        var toggle = card.querySelector('.job-detail-toggle');
        if (toggle) {
            toggle.addEventListener('click', function () {
                var body = card.querySelector('.job-detail-body');
                if (!body) return;
                var open = body.style.display !== 'none';
                body.style.display = open ? 'none' : 'block';
                toggle.textContent = open ? 'Details ▾' : 'Details ▴';
            });
        }

        // Wire map pin click
        var pin = card.querySelector('.map-pin');
        if (pin) {
            pin.addEventListener('click', function (e) {
                e.stopPropagation();
                var lat = parseFloat(this.dataset.lat);
                var lng = parseFloat(this.dataset.lng);
                var map = window.sharedMap;
                if (map && !isNaN(lat) && !isNaN(lng)) map.flyTo([lat, lng], 15);
            });
        }

        // Hover-to-glow: highlight the hex this job is in
        if (job.h3_r7 || job.h3_r8) {
            card.addEventListener('mouseenter', function () {
                var cellId = _glowCellId(job);
                var poly = cellId && _cellPolys[cellId];
                if (poly) poly.setStyle({ weight: 2.5, opacity: 1.0, fillOpacity: 0.85, color: '#ffffff' });
            });
            card.addEventListener('mouseleave', function () {
                var cellId = _glowCellId(job);
                var poly = cellId && _cellPolys[cellId];
                if (poly && poly._origStyle) poly.setStyle(poly._origStyle);
            });
        }

        return card;
    }

    // ── Sidebar helpers ───────────────────────────────────────────────────────

    var _listPage  = 1;
    var _listPages = 1;

    function _loadList(container, region, category, mode, page, append) {
        var url = '/api/jobs/listings?region=' + encodeURIComponent(region)
                + '&mode='  + encodeURIComponent(mode)
                + '&page='  + page
                + '&limit=20'
                + '&sort='  + encodeURIComponent(_state.sort);
        if (category)  url += '&category=' + encodeURIComponent(category);
        if (_state.q)  url += '&q='        + encodeURIComponent(_state.q);
        if (_state.wageMin) url += '&wage_min_filter=' + encodeURIComponent(_state.wageMin);
        if (_state.wageMax) url += '&wage_max_filter=' + encodeURIComponent(_state.wageMax);
        if (_state.postedWithin) url += '&posted_within=' + encodeURIComponent(_state.postedWithin);
        if (_state.timeType) url += '&time_type=' + encodeURIComponent(_state.timeType);

        if (!append) {
            container.innerHTML = '<div class="job-card"><div class="job-employer">Loading…</div></div>';
        }

        fetch(url)
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (!append) container.innerHTML = '';

                _listPage  = data.page  || 1;
                _listPages = data.pages || 1;

                var jobs = data.jobs || [];
                if (!jobs.length && !append) {
                    container.innerHTML = '<div class="job-card"><div class="job-meta">No jobs found.</div></div>';
                }
                jobs.forEach(function (job) { container.appendChild(_buildCard(job)); });

                var title = document.getElementById('jf-list-title');
                if (title) {
                    var lbl = mode === 'remote' ? 'Remote'
                            : mode === 'local'  ? 'Local'
                            : 'All';
                    title.textContent = lbl + ' Jobs (' + (data.total || 0) + ')';
                }

                var moreBtn = document.getElementById('jf-load-more');
                if (moreBtn) moreBtn.style.display = _listPage < _listPages ? 'block' : 'none';
            })
            .catch(function (err) { console.error('[jobfinder] listings fetch failed:', err); });
    }

    function _loadCellJobs(container, cellId, resolution, region, category) {
        container.innerHTML = '<div class="job-card"><div class="job-employer">Loading…</div></div>';
        var url = '/api/jobs/listings?region=' + encodeURIComponent(region)
                + '&h3_cell='    + encodeURIComponent(cellId)
                + '&resolution=' + resolution
                + '&limit=50'
                + '&sort='       + encodeURIComponent(_state.sort);
        if (category) url += '&category=' + encodeURIComponent(category);
        if (_state.q) url += '&q='        + encodeURIComponent(_state.q);
        if (_state.wageMin) url += '&wage_min_filter=' + encodeURIComponent(_state.wageMin);
        if (_state.wageMax) url += '&wage_max_filter=' + encodeURIComponent(_state.wageMax);
        if (_state.postedWithin) url += '&posted_within=' + encodeURIComponent(_state.postedWithin);
        if (_state.timeType) url += '&time_type=' + encodeURIComponent(_state.timeType);

        fetch(url)
            .then(function (r) { return r.json(); })
            .then(function (data) {
                container.innerHTML = '';
                var jobs = data.jobs || [];
                if (!jobs.length) {
                    container.innerHTML = '<div class="job-card"><div class="job-meta">No jobs found in this area.</div></div>';
                    return;
                }
                jobs.forEach(function (job) { container.appendChild(_buildCard(job)); });
            })
            .catch(function (err) { console.error('[jobfinder] cell fetch failed:', err); });
    }

    // ── Panel switching ───────────────────────────────────────────────────────

    function _showDefaultPanel() {
        var defPanel  = document.getElementById('jf-default-panel');
        var cellPanel = document.getElementById('jf-cell-panel');
        if (defPanel)  defPanel.style.display  = 'block';
        if (cellPanel) cellPanel.style.display  = 'none';

        // Restore previously selected hex to its original style
        if (_selectedCell && _cellPolys[_selectedCell]) {
            var prev = _cellPolys[_selectedCell];
            if (prev._origStyle) prev.setStyle(prev._origStyle);
        }
        _selectedCell = null;

        var container = document.getElementById('jf-remote-list');
        if (!container) return;

        var mode = _state.mode;

        _listPage = 1;
        _loadList(container, _state.region, _state.category, mode, 1, false);
    }

    function _showCellPanel(cellId, resolution, count, isCity) {
        // Restore previous selection
        if (_selectedCell && _cellPolys[_selectedCell]) {
            var prev = _cellPolys[_selectedCell];
            if (prev._origStyle) prev.setStyle(prev._origStyle);
        }

        // Apply selected style to clicked hex
        _selectedCell = cellId;
        var selPoly = _cellPolys[cellId];
        if (selPoly) {
            selPoly.setStyle({ color: '#00e5ff', weight: 3, opacity: 1.0, fillOpacity: 0.9 });
        }
        var defPanel  = document.getElementById('jf-default-panel');
        var cellPanel = document.getElementById('jf-cell-panel');
        if (defPanel)  defPanel.style.display  = 'none';
        if (cellPanel) cellPanel.style.display  = 'block';

        var cellTitle = document.getElementById('jf-cell-title');
        if (cellTitle) {
            if (isCity) {
                cellTitle.textContent = '📍 Austin area — city-geocoded jobs';
            } else if (count != null) {
                cellTitle.textContent = count + ' job' + (count !== 1 ? 's' : '') + ' in this area';
            } else {
                cellTitle.textContent = 'Jobs in this area';
            }
        }

        var container = document.getElementById('jf-cell-list');
        if (container) _loadCellJobs(container, cellId, resolution, _state.region, _state.category);
    }

    // ── Event: back button ────────────────────────────────────────────────────

    document.addEventListener('DOMContentLoaded', function () {
        var backBtn = document.getElementById('jf-back-btn');
        if (backBtn) backBtn.addEventListener('click', _showDefaultPanel);

        var moreBtn = document.getElementById('jf-load-more');
        if (moreBtn) {
            moreBtn.addEventListener('click', function () {
                if (_listPage >= _listPages) return;
                var container = document.getElementById('jf-remote-list');
                if (container) {
                    _listPage++;
                    _loadList(container, _state.region, _state.category, _state.mode, _listPage, true);
                }
            });
        }

        // ── Sidebar search input (debounced, server-side) ─────────────────────
        var searchInput = document.getElementById('jf-search');
        if (searchInput) {
            var _searchTimer = null;
            searchInput.addEventListener('input', function () {
                clearTimeout(_searchTimer);
                var val = this.value;
                _searchTimer = setTimeout(function () {
                    _state.q = val.trim();
                    _listPage = 1;
                    var container = document.getElementById('jf-remote-list');
                    if (container) {
                        _loadList(container, _state.region, _state.category, _state.mode, 1, false);
                    }
                }, 300);
            });
        }

        // ── Sidebar sort select ───────────────────────────────────────────────
        var sortSelect = document.getElementById('jf-sort-select');
        if (sortSelect) {
            sortSelect.addEventListener('change', function () {
                _state.sort = this.value;
                _listPage = 1;
                var container = document.getElementById('jf-remote-list');
                if (container) {
                    _loadList(container, _state.region, _state.category, _state.mode, 1, false);
                }
            });
        }

        // ── Wage range inputs (debounced) ─────────────────────────────────────
        var wageMinInput = document.getElementById('jf-wage-min');
        var wageMaxInput = document.getElementById('jf-wage-max');
        function _onWageChange() {
            var _wageTimer = null;
            return function () {
                clearTimeout(_wageTimer);
                _wageTimer = setTimeout(function () {
                    _state.wageMin = wageMinInput ? wageMinInput.value.trim() : '';
                    _state.wageMax = wageMaxInput ? wageMaxInput.value.trim() : '';
                    _listPage = 1;
                    var container = document.getElementById('jf-remote-list');
                    if (container) _loadList(container, _state.region, _state.category, _state.mode, 1, false);
                }, 400);
            };
        }
        var _wageHandler = _onWageChange();
        if (wageMinInput) wageMinInput.addEventListener('input', _wageHandler);
        if (wageMaxInput) wageMaxInput.addEventListener('input', _wageHandler);

        // ── Posted-within select ──────────────────────────────────────────────
        var postedWithinSelect = document.getElementById('jf-posted-within');
        if (postedWithinSelect) {
            postedWithinSelect.addEventListener('change', function () {
                _state.postedWithin = this.value;
                _listPage = 1;
                var container = document.getElementById('jf-remote-list');
                if (container) _loadList(container, _state.region, _state.category, _state.mode, 1, false);
            });
        }

        // ── Job type chips (toggle) ──────────────────────────────────────────
        var typeChips = document.querySelectorAll('.jf-type-chip');
        typeChips.forEach(function (chip) {
            chip.addEventListener('click', function () {
                var val = this.dataset.type;
                if (_state.timeType === val) {
                    _state.timeType = '';
                    this.classList.remove('active');
                } else {
                    typeChips.forEach(function (c) { c.classList.remove('active'); });
                    _state.timeType = val;
                    this.classList.add('active');
                }
                _listPage = 1;
                var container = document.getElementById('jf-remote-list');
                if (container) _loadList(container, _state.region, _state.category, _state.mode, 1, false);
            });
        });
    });

    // ── Public API ────────────────────────────────────────────────────────────

    window.jobfinder = {
        /**
         * refresh(region, category, mode)
         * Called by app.js whenever mode or a filter changes.
         * Re-renders the hex layer (if relevant) and resets the sidebar.
         */
        refresh: function (region, category, mode) {
            _state.region   = region   || 'austin_tx';
            _state.category = category || '';
            _state.mode     = mode     || 'remote';

            var map = window.sharedMap;
            if (!map) return;

            if (_state.mode !== 'remote') {
                // local or all — show hex layer
                var res = _jobRes(map.getZoom());
                _renderHex(res, _state.region, _state.category, _state.mode);
            } else {
                // remote only — no hex; cancel any in-flight render
                _renderGen++;
                _clearHex();
            }

            _showDefaultPanel();
        },

        /** Remove the hex layer and cancel any in-flight render. */
        clear: function () {
            _renderGen++;
            _clearHex();
        },

        /** Re-render hex at new zoom resolution (called on zoomend). */
        onZoom: function () {
            var map = window.sharedMap;
            if (!map || _state.mode === 'remote') return;
            var res = _jobRes(map.getZoom());
            _renderHex(res, _state.region, _state.category, _state.mode);
        },

        /**
         * setResolution(r)
         * r = 'auto' | 7 | 8 — override zoom-based resolution for hex tiles.
         */
        setResolution: function (r) {
            _resOverride = (r === 'auto') ? null : parseInt(r, 10);
            var map = window.sharedMap;
            if (!map || _state.mode === 'remote') return;
            var res = _jobRes(map.getZoom());
            _renderHex(res, _state.region, _state.category, _state.mode);
        },

        /**
         * selectCityHex()
         * Shows the cell panel for the H3 cell containing Austin city center.
         * This surfaces jobs that were geocoded to "Austin, TX" (no precise address).
         */
        selectCityHex: function () {
            var map = window.sharedMap;
            var res = map ? _jobRes(map.getZoom()) : 7;
            var cityCell = h3.latLngToCell(AUSTIN_LAT, AUSTIN_LNG, res);
            _showCellPanel(cityCell, res, null, true);
        },

        /** Reset search/sort state (called by app.js when entering job finder mode). */
        resetFilters: function () {
            _state.q    = '';
            _state.sort = 'date';
            _state.wageMin = '';
            _state.wageMax = '';
            _state.postedWithin = '';
            _state.timeType = '';
            var searchEl = document.getElementById('jf-search');
            if (searchEl) searchEl.value = '';
            var sortEl = document.getElementById('jf-sort-select');
            if (sortEl) sortEl.value = 'date';
            var wMinEl = document.getElementById('jf-wage-min');
            if (wMinEl) wMinEl.value = '';
            var wMaxEl = document.getElementById('jf-wage-max');
            if (wMaxEl) wMaxEl.value = '';
            var pwEl = document.getElementById('jf-posted-within');
            if (pwEl) pwEl.value = '';
            document.querySelectorAll('.jf-type-chip').forEach(function (c) { c.classList.remove('active'); });
        },
    };

})();

/**
 * jobfinder.js — Job Finder map layer and listing sidebar
 *
 * H3 hex layer: aggregates job_postings by h3_r7/r8 for jobs with coordinates.
 * Sidebar: paginated job cards for remote jobs (default) or a clicked hex cell.
 *
 * Location mode toggle (controlled by app.js via jobfinder.refresh):
 *   local  — hex layer only; clicking a hex loads on-site job listings
 *   remote — sidebar list of remote jobs; no hex layer
 *   all    — hex layer (jobs with coords) + remote sidebar list
 *
 * Exposes window.jobfinder for app.js integration.
 */

(function () {
    'use strict';

    // ── Internal state ────────────────────────────────────────────────────────
    var _state = { region: 'austin_tx', category: '', mode: 'remote' };

    // ── Hex layer ─────────────────────────────────────────────────────────────
    var _hexLayer  = null;
    var _renderGen = 0;

    // JobPosting only has h3_r7 and h3_r8 — clamp zoom-derived resolution
    function _jobRes(zoom) { return zoom >= 12 ? 8 : 7; }

    function _hexOpacity(count, maxCount) {
        var t = maxCount > 0 ? count / maxCount : 0;
        return 0.14 + 0.60 * Math.pow(t, 0.40);
    }

    function _clearHex() {
        var map = window.sharedMap;
        if (_hexLayer && map) map.removeLayer(_hexLayer);
        _hexLayer = null;
    }

    function _renderHex(resolution, region, category, mode) {
        var map = window.sharedMap;
        if (!map) return;

        var url = '/api/jobs/h3-map?resolution=' + resolution
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

                var maxCount = 1;
                data.cells.forEach(function (c) { if (c.count > maxCount) maxCount = c.count; });

                var polys = [];
                data.cells.forEach(function (cell) {
                    var boundary = h3.cellToBoundary(cell.cell_id);
                    var poly = L.polygon(boundary, {
                        fillColor:   '#4ecca3',
                        fillOpacity: _hexOpacity(cell.count, maxCount),
                        color:       '#ffffff',
                        weight:      0.6,
                        opacity:     0.25,
                    });

                    poly.bindTooltip(
                        cell.count + ' job' + (cell.count !== 1 ? 's' : '') + ' · click to view',
                        { sticky: true, className: 'h3-tooltip' }
                    );

                    poly.on('click', function (e) {
                        L.DomEvent.stopPropagation(e);
                        _showCellPanel(cell.cell_id, resolution, cell.count);
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
                    var total = data.cells.reduce(function (s, c) { return s + c.count; }, 0);
                    badge.textContent = data.cell_count + ' areas · ' + total + ' jobs';
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
        'workday_gov':          'City of Austin',
        'careers_api':          'Workday',
        'usajobs':              'USAJobs',
        'rapidapi_activejobs':  'ActiveJobs',
        'juju':                 'Juju',
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

    function _buildCard(job) {
        var card = document.createElement('div');
        card.className = 'job-card';

        var emp = '<div class="job-employer">' + _esc(job.employer || '—');
        if (job.is_remote) emp += '<span class="listing-badge remote">remote</span>';
        var d = job.detail || {};
        if (d.time_type) emp += '<span class="listing-badge time-type">' + _esc(d.time_type) + '</span>';
        var srcLabel = _SOURCE_LABELS[job.source] || job.source;
        if (srcLabel) emp += '<span class="listing-badge source">' + _esc(srcLabel) + '</span>';
        emp += '</div>';

        var title = job.role_title
            ? '<div class="job-title">' + _esc(job.role_title) + '</div>'
            : '';

        // Wage: prefer parsed wage, fall back to raw pay range text
        var wage = '';
        if (job.wage) {
            wage = '<div class="job-wage">' + _esc(job.wage) + '</div>';
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
        var ago = _daysAgo(job.posted_date);
        if (ago) meta.push(ago);
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

        return card;
    }

    // ── Sidebar helpers ───────────────────────────────────────────────────────

    var _listPage  = 1;
    var _listPages = 1;

    function _loadList(container, region, category, mode, page, append) {
        var url = '/api/jobs/listings?region=' + encodeURIComponent(region)
                + '&mode='  + encodeURIComponent(mode)
                + '&page='  + page
                + '&limit=20';
        if (category) url += '&category=' + encodeURIComponent(category);

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
                + '&limit=50';
        if (category) url += '&category=' + encodeURIComponent(category);

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

        var container = document.getElementById('jf-remote-list');
        if (!container) return;

        var mode = _state.mode;

        // Local-only mode: no list panel — guide user to click a hex
        if (mode === 'local') {
            var title = document.getElementById('jf-list-title');
            if (title) title.textContent = 'Local Jobs';
            container.innerHTML =
                '<div class="job-card"><div class="job-meta">' +
                'Click a hex on the map to view local job listings in that area.' +
                '</div></div>';
            var moreBtn = document.getElementById('jf-load-more');
            if (moreBtn) moreBtn.style.display = 'none';
            return;
        }

        _listPage = 1;
        _loadList(container, _state.region, _state.category, mode, 1, false);
    }

    function _showCellPanel(cellId, resolution, count) {
        var defPanel  = document.getElementById('jf-default-panel');
        var cellPanel = document.getElementById('jf-cell-panel');
        if (defPanel)  defPanel.style.display  = 'none';
        if (cellPanel) cellPanel.style.display  = 'block';

        var cellTitle = document.getElementById('jf-cell-title');
        if (cellTitle) {
            cellTitle.textContent = count + ' job' + (count !== 1 ? 's' : '') + ' in this area';
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
    };

})();

/**
 * OpenClaw Dashboard — Real-time agent query monitor
 *
 * Polls the OpenClaw API endpoints every 15 seconds and renders:
 *   - KPI summary cards
 *   - Horizontal bar breakdowns (by intent, source, industry)
 *   - Live request feed with color-coded success/fail
 *   - Agent wishlist with approve/reject controls
 *   - Session launcher
 */

(function () {
    'use strict';

    const API = '';
    const POLL_INTERVAL = 15000; // 15 s
    let pollTimer = null;

    // Color palette matching CSS vars
    const C = {
        green:  '#4ecca3',
        red:    '#e94560',
        yellow: '#f0a500',
        blue:   '#3498db',
        purple: '#6c5ce7',
        muted:  '#555',
    };

    // ── Helpers ─────────────────────────────────────────────────
    function $(sel) { return document.querySelector(sel); }
    function $$(sel) { return document.querySelectorAll(sel); }

    function fmt(n) {
        if (n == null || n === '—') return '—';
        return Number(n).toLocaleString();
    }

    function timeOf(ts) {
        if (!ts) return '';
        const d = new Date(ts);
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    }

    function escHtml(s) {
        const div = document.createElement('div');
        div.textContent = s;
        return div.innerHTML;
    }

    function setKPI(id, value) {
        const el = $(`#${id} .kpi-value`);
        if (el) el.textContent = value;
    }

    // ── Status check ────────────────────────────────────────────
    async function loadStatus() {
        try {
            const r = await fetch(API + '/api/openclaw/status');
            const d = await r.json();
            const dot = $('#status-dot');
            const lbl = $('#status-label');
            const mdl = $('#model-label');

            if (d.openclaw_available) {
                dot.className = 'dot dot-ok';
                lbl.textContent = 'Ollama connected';
            } else {
                dot.className = 'dot dot-error';
                lbl.textContent = 'Ollama offline';
            }
            mdl.textContent = d.configured_model || '';

            // Populate industry checkboxes from /api/meta (source of truth)
            const grid = $('#industry-checkboxes');
            if (grid && grid.children.length === 0) {
                try {
                    const meta = await window.heliosMeta;
                    if (meta && meta.industries) {
                        meta.industries.forEach(function (ind) {
                            const lbl = document.createElement('label');
                            const cb = document.createElement('input');
                            cb.type = 'checkbox';
                            cb.value = ind.key;
                            cb.checked = true;
                            lbl.appendChild(cb);
                            lbl.appendChild(document.createTextNode(' ' + ind.display_name));
                            grid.appendChild(lbl);
                        });
                    }
                } catch (_) {
                    // Fallback: use raw keys from status endpoint
                    if (d.industries) {
                        d.industries.forEach(function (key) {
                            const lbl = document.createElement('label');
                            const cb = document.createElement('input');
                            cb.type = 'checkbox';
                            cb.value = key;
                            cb.checked = true;
                            lbl.appendChild(cb);
                            lbl.appendChild(document.createTextNode(' ' + key.replace(/_/g, ' ')));
                            grid.appendChild(lbl);
                        });
                    }
                }
            }
        } catch (e) {
            $('#status-dot').className = 'dot dot-error';
            $('#status-label').textContent = 'Connection failed';
        }
    }

    // ── Tracker data ────────────────────────────────────────────
    async function loadTracker() {
        try {
            const r = await fetch(API + '/api/openclaw/tracker');
            const d = await r.json();
            if (d.status !== 'ok') return;

            const rl = d.rollup;

            // KPIs
            setKPI('kpi-total', fmt(rl.total_requests));
            setKPI('kpi-success', fmt(rl.successful));
            setKPI('kpi-failed', fmt(rl.failed));
            setKPI('kpi-rejected', fmt(rl.prevalidation_rejected));
            setKPI('kpi-records', fmt(rl.total_records));
            setKPI('kpi-latency', rl.avg_latency_ms != null ? rl.avg_latency_ms.toFixed(1) + ' ms' : '—');

            // Bar charts
            renderBarChart('#intent-chart', rl.by_intent);
            renderBarChart('#source-chart', rl.by_source);
            renderBarChart('#industry-chart', rl.by_industry);

            // Errors
            renderErrors(rl.top_errors || []);

            // Feed
            renderFeed(d.recent_requests || []);
        } catch (e) {
            console.warn('Tracker fetch failed', e);
        }
    }

    // ── Bar chart renderer ──────────────────────────────────────
    function renderBarChart(selector, data) {
        const el = $(selector);
        if (!el) return;

        const entries = Object.entries(data || {});
        if (entries.length === 0) {
            el.innerHTML = '<p class="empty-state">No data yet</p>';
            return;
        }

        // Find max total for scaling
        let maxTotal = 0;
        entries.forEach(function (e) {
            const total = (e[1].success || 0) + (e[1].fail || 0);
            if (total > maxTotal) maxTotal = total;
        });
        if (maxTotal === 0) maxTotal = 1;

        let html = '';
        entries.forEach(function (entry) {
            const key = entry[0];
            const v = entry[1];
            const s = v.success || 0;
            const f = v.fail || 0;
            const total = s + f;
            const records = v.records != null ? v.records : '';
            const sPct = (s / maxTotal * 100).toFixed(1);
            const fPct = (f / maxTotal * 100).toFixed(1);

            html += '<div class="bar-row">'
                + '<span class="bar-label" title="' + escHtml(key) + '">' + escHtml(key) + '</span>'
                + '<div class="bar-track">'
                + '<div class="bar-fill-success" style="width:' + sPct + '%" title="' + s + ' success"></div>'
                + '<div class="bar-fill-fail" style="width:' + fPct + '%" title="' + f + ' failed"></div>'
                + '</div>'
                + '<span class="bar-value" title="' + total + ' total, ' + records + ' records">'
                + total + (records ? ' / ' + fmt(records) : '')
                + '</span>'
                + '</div>';
        });
        el.innerHTML = html;
    }

    // ── Recent request feed ─────────────────────────────────────
    function renderFeed(requests) {
        const list = $('#feed-list');
        const badge = $('#feed-count');
        if (!list) return;
        badge.textContent = requests.length;

        if (requests.length === 0) {
            list.innerHTML = '<p class="empty-state">No requests today — launch a session to start</p>';
            return;
        }

        // Show newest first
        const sorted = requests.slice().sort(function (a, b) {
            return b.timestamp.localeCompare(a.timestamp);
        });

        let html = '';
        sorted.forEach(function (req) {
            const cls = req.prevalidation_passed === false ? 'rejected'
                : req.success ? 'success' : 'fail';

            const detail = [req.industry, req.brand, req.search_term]
                .filter(Boolean).join(' · ');

            html += '<div class="feed-item ' + cls + '">'
                + '<span class="feed-time">' + timeOf(req.timestamp) + '</span>'
                + '<span class="feed-intent">' + escHtml(req.intent || '?')
                + (detail ? ' <span class="feed-detail">' + escHtml(detail) + '</span>' : '')
                + '</span>'
                + '<span class="feed-source">' + escHtml(req.source || '') + '</span>'
                + '<span class="feed-records">'
                + (req.records_returned != null ? fmt(req.records_returned) + ' rec' : '')
                + '</span>'
                + '</div>';
        });
        list.innerHTML = html;
    }

    // ── Top errors ──────────────────────────────────────────────
    function renderErrors(errors) {
        const el = $('#errors-list');
        if (!el) return;

        if (!errors || errors.length === 0) {
            el.innerHTML = '<p class="empty-state">No errors today</p>';
            return;
        }

        let html = '';
        errors.forEach(function (e) {
            html += '<div class="error-row">'
                + '<span class="error-msg" title="' + escHtml(e.message || e) + '">'
                + escHtml(e.message || e)
                + '</span>'
                + (e.count ? '<span class="error-count">×' + e.count + '</span>' : '')
                + '</div>';
        });
        el.innerHTML = html;
    }

    // ── Wishlist ────────────────────────────────────────────────
    async function loadWishlist() {
        try {
            const r = await fetch(API + '/api/openclaw/wishlist');
            const d = await r.json();
            if (d.status !== 'ok') return;

            const badge = $('#wish-count');
            const container = $('#wishlist-items');
            const items = d.items || [];
            badge.textContent = items.length;

            if (items.length === 0) {
                container.innerHTML = '<p class="empty-state">No wishes yet — the agent will add items after a session</p>';
                return;
            }

            let html = '';
            items.forEach(function (w) {
                const catClass = 'wish-cat-' + (w.category || '').toLowerCase();
                const reviewed = w.status === 'approved' || w.status === 'rejected';

                html += '<div class="wish-item">'
                    + '<div class="wish-header">'
                    + '<span class="wish-title">' + escHtml(w.title || '') + '</span>'
                    + '<span class="wish-category ' + catClass + '">' + escHtml(w.category || '') + '</span>'
                    + '</div>'
                    + '<div class="wish-desc">' + escHtml(w.description || '') + '</div>';

                if (w.suggested_value) {
                    html += '<div class="wish-desc">Suggested: <strong>'
                        + escHtml(w.suggested_value) + '</strong></div>';
                }

                if (reviewed) {
                    html += '<div class="wish-status-' + w.status + '">'
                        + (w.status === 'approved' ? '✓ Approved' : '✗ Rejected')
                        + (w.operator_note ? ' — ' + escHtml(w.operator_note) : '')
                        + '</div>';
                } else {
                    html += '<div class="wish-actions">'
                        + '<button class="btn-approve" data-wish="' + escHtml(w.wish_id) + '">✓ Approve</button>'
                        + '<button class="btn-reject" data-wish="' + escHtml(w.wish_id) + '">✗ Reject</button>'
                        + '</div>';
                }

                html += '</div>';
            });
            container.innerHTML = html;

            // Bind wish buttons
            container.querySelectorAll('.btn-approve').forEach(function (btn) {
                btn.addEventListener('click', function () { reviewWish(btn.dataset.wish, true); });
            });
            container.querySelectorAll('.btn-reject').forEach(function (btn) {
                btn.addEventListener('click', function () { reviewWish(btn.dataset.wish, false); });
            });
        } catch (e) {
            console.warn('Wishlist fetch failed', e);
        }
    }

    async function reviewWish(wishId, approved) {
        try {
            await fetch(API + '/api/openclaw/wishlist/review', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    wish_id: wishId,
                    approved: approved,
                    note: approved ? 'Approved via dashboard' : 'Rejected via dashboard',
                }),
            });
            loadWishlist(); // refresh
        } catch (e) {
            console.warn('Wish review failed', e);
        }
    }

    // ── Session launcher ────────────────────────────────────────
    function initSessionForm() {
        const form = $('#session-form');
        if (!form) return;

        form.addEventListener('submit', async function (ev) {
            ev.preventDefault();

            const goal = $('#session-goal').value.trim();
            if (!goal) {
                $('#session-status').textContent = 'Please enter a goal';
                return;
            }

            const region = $('#session-region').value.trim() || 'austin_tx';

            // Gather checked industries
            const checked = [];
            $$('#industry-checkboxes input:checked').forEach(function (cb) {
                checked.push(cb.value);
            });

            const btn = $('#launch-btn');
            btn.disabled = true;
            $('#session-status').textContent = '';

            try {
                const resp = await fetch(API + '/api/openclaw/run', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        model: 'qwen2.5:7b-instruct',
                        region: region,
                        goal: goal,
                        industries: checked.length > 0 ? checked : null,
                    }),
                });
                const data = await resp.json();

                if (data.status === 'ok') {
                    // Redirect to live session view
                    window.location.href = '/openclaw/session';
                    return;
                }

                // Show error inline (e.g. session already running)
                $('#session-status').textContent = data.message || 'Error launching session';
                if (data.message && data.message.includes('already running')) {
                    // Offer to go watch it
                    setTimeout(function () {
                        window.location.href = '/openclaw/session';
                    }, 1500);
                }
            } catch (e) {
                $('#session-status').textContent = 'Request failed: ' + e.message;
            } finally {
                btn.disabled = false;
            }
        });
    }

    // ── Refresh all panels ──────────────────────────────────────
    async function refreshAll() {
        const ts = new Date().toLocaleTimeString();
        const el = $('#last-refresh');
        if (el) el.textContent = 'Last refresh: ' + ts;

        await Promise.all([
            loadStatus(),
            loadTracker(),
            loadWishlist(),
        ]);
    }

    // ── Init ────────────────────────────────────────────────────
    function init() {
        // First load
        refreshAll();

        // Auto-poll
        pollTimer = setInterval(refreshAll, POLL_INTERVAL);

        // Manual refresh button
        const btn = $('#refresh-all');
        if (btn) btn.addEventListener('click', refreshAll);

        // Session form
        initSessionForm();
    }

    // Start on DOMContentLoaded
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();

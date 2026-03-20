/**
 * Data Source Metrics Dashboard — JS controller
 *
 * Fetches from /api/metrics/* and /api/dedup/* endpoints,
 * renders KPIs, rankings table (sortable), sparkline trends,
 * source detail overlay, and dedup controls.
 */

(function () {
    'use strict';

    const POLL_INTERVAL = 30000; // 30 s
    let pollTimer = null;
    let currentSort = { col: 'records_per_query', dir: 'desc' };
    let sourcesData = [];   // cached for sort / click

    // ── Helpers ─────────────────────────────────────────────────
    const $ = sel => document.querySelector(sel);
    const fmt = n => (n == null || n === '—') ? '—' : Number(n).toLocaleString();

    function setKPI(id, value) {
        const el = document.querySelector(`#${id} .kpi-value`);
        if (el) el.textContent = value;
    }

    function gradeClass(g) {
        return 'grade grade-' + (g || 'F');
    }

    function fillColor(pct) {
        if (pct >= 80) return 'fill-green';
        if (pct >= 50) return 'fill-yellow';
        return 'fill-red';
    }

    function timeOf(ts) {
        if (!ts) return '';
        const d = new Date(ts);
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    }

    function dateOf(ts) {
        if (!ts) return '';
        return ts.substring(5); // MM-DD
    }

    function getPeriod() {
        return parseInt($('#period-select').value, 10) || 30;
    }

    // ── KPI + Rankings ──────────────────────────────────────────
    async function loadMetrics() {
        const days = getPeriod();
        try {
            const r = await fetch(`/api/metrics/sources?days=${days}`);
            const d = await r.json();
            if (d.status !== 'ok') return;

            const t = d.totals || {};
            setKPI('kpi-queries', fmt(t.queries));
            setKPI('kpi-records', fmt(t.records));
            setKPI('kpi-success', (t.success_rate || 0) + '%');
            setKPI('kpi-latency', (t.avg_latency_ms || 0) + ' ms');
            setKPI('kpi-sources', fmt((d.sources || []).length));

            // Avg yield
            const avgYield = t.queries ? (t.records / t.queries).toFixed(1) : '0';
            setKPI('kpi-yield', avgYield);

            sourcesData = d.sources || [];
            renderRankings();
        } catch (e) {
            console.error('[Metrics] load failed:', e);
        }
    }

    function renderRankings() {
        const body = $('#rankings-body');
        if (!body) return;

        // Sort
        const col = currentSort.col;
        const dir = currentSort.dir === 'asc' ? 1 : -1;
        sourcesData.sort((a, b) => {
            const av = a[col] ?? '', bv = b[col] ?? '';
            if (typeof av === 'number') return (av - bv) * dir;
            return String(av).localeCompare(String(bv)) * dir;
        });

        // Update header classes
        document.querySelectorAll('#rankings-table th').forEach(th => {
            th.classList.remove('sorted-asc', 'sorted-desc');
            if (th.dataset.col === col) {
                th.classList.add(currentSort.dir === 'asc' ? 'sorted-asc' : 'sorted-desc');
            }
        });

        body.innerHTML = sourcesData.map(s => {
            const spark = buildSparkline(s.daily_trend || []);
            return `<tr data-key="${s.source_key}" style="cursor:pointer">
                <td><span class="${gradeClass(s.grade || computeGrade(s))}">${s.grade || computeGrade(s)}</span></td>
                <td><strong>${esc(s.display_name || s.source_key)}</strong><br>
                    <span style="font-size:0.72rem;color:var(--text-dim)">${esc(s.source_key)}</span></td>
                <td class="num">${fmt(s.queries)}</td>
                <td class="num">${fmt(s.records)}</td>
                <td class="num">${s.records_per_query}</td>
                <td class="num">${s.success_rate}%</td>
                <td class="num">${s.error_rate || 0}%</td>
                <td class="num">${s.avg_latency_ms} ms</td>
                <td>${spark}</td>
            </tr>`;
        }).join('');

        // Row click → detail
        body.querySelectorAll('tr').forEach(tr => {
            tr.addEventListener('click', () => openDetail(tr.dataset.key));
        });
    }

    function computeGrade(s) {
        const rpq = s.records_per_query || 0;
        const sr = s.success_rate || 0;
        if (!s.queries) return 'F';
        if (rpq > 10 && sr >= 90) return 'A';
        if (rpq > 5 && sr >= 80) return 'B';
        if (rpq > 1 && sr >= 60) return 'C';
        if (rpq > 0) return 'D';
        return 'F';
    }

    function buildSparkline(trend) {
        if (!trend || trend.length === 0) return '<span style="color:var(--text-dim)">—</span>';
        const maxQ = Math.max(...trend.map(d => d.queries || 0), 1);
        const bars = trend.slice(-14).map(d => {
            const h = Math.max(2, Math.round((d.queries / maxQ) * 26));
            const title = `${d.date}: ${d.queries} queries, ${d.records} records`;
            return `<div class="bar" style="height:${h}px" title="${title}"></div>`;
        });
        return `<div class="sparkline">${bars.join('')}</div>`;
    }

    function esc(s) {
        const d = document.createElement('div');
        d.textContent = s || '';
        return d.innerHTML;
    }

    // ── Column sort ─────────────────────────────────────────────
    function initSort() {
        document.querySelectorAll('#rankings-table th[data-col]').forEach(th => {
            th.addEventListener('click', () => {
                const col = th.dataset.col;
                if (currentSort.col === col) {
                    currentSort.dir = currentSort.dir === 'asc' ? 'desc' : 'asc';
                } else {
                    currentSort = { col, dir: 'desc' };
                }
                renderRankings();
            });
        });
    }

    // ── Detail overlay ──────────────────────────────────────────
    async function openDetail(sourceKey) {
        const days = getPeriod();
        try {
            const r = await fetch(`/api/metrics/sources/${sourceKey}?days=${days}&log_limit=30`);
            const d = await r.json();
            if (d.status !== 'ok') return;

            $('#detail-title').textContent = (d.source?.display_name || sourceKey) + ' — Detail';

            // Summary
            const s = d.summary || {};
            $('#detail-summary').innerHTML = `
                <div class="dedup-grid" style="margin-bottom:8px">
                    <div class="dedup-card"><div class="val">${fmt(s.total_queries)}</div><div class="lbl">Queries</div></div>
                    <div class="dedup-card"><div class="val">${fmt(s.total_records)}</div><div class="lbl">Records</div></div>
                    <div class="dedup-card"><div class="val">${s.records_per_query}</div><div class="lbl">Yield</div></div>
                    <div class="dedup-card"><div class="val">${s.success_rate}%</div><div class="lbl">Success</div></div>
                    <div class="dedup-card"><div class="val">${s.avg_latency_ms} ms</div><div class="lbl">Latency</div></div>
                </div>`;

            // Daily chart
            const daily = d.daily || [];
            const maxR = Math.max(...daily.map(d => d.records || 0), 1);
            const maxQ = Math.max(...daily.map(d => d.queries || 0), 1);
            $('#detail-daily').innerHTML = daily.map(day => {
                const hR = Math.max(2, Math.round((day.records / maxR) * 60));
                const hQ = Math.max(2, Math.round((day.queries / maxQ) * 60));
                return `<div class="col">
                    <div class="col-bar" style="height:${hR}px;width:14px;background:var(--green)" title="${day.records} records"></div>
                    <div class="col-bar" style="height:${hQ}px;width:14px;background:var(--blue)" title="${day.queries} queries"></div>
                    <div class="col-lbl">${dateOf(day.date)}</div>
                </div>`;
            }).join('');

            // Request types
            const types = d.request_types || {};
            $('#detail-types').innerHTML = Object.entries(types).map(([k, v]) => {
                return `<div class="req-type-card">
                    <div class="label">${esc(k)}</div>
                    <div class="val">${fmt(v.count)} <span style="font-size:0.75rem;color:var(--text-muted)">queries</span></div>
                    <div style="font-size:0.78rem">${fmt(v.records)} records · ${v.success_rate}% ok</div>
                </div>`;
            }).join('') || '<p style="color:var(--text-dim)">No request type data</p>';

            // Recent log
            const logBody = $('#detail-log-body');
            logBody.innerHTML = (d.recent_requests || []).map(r => {
                const cls = r.success ? 'badge-ok' : 'badge-fail';
                const icon = r.success ? '✓' : '✗';
                return `<tr>
                    <td>${timeOf(r.requested_at)}</td>
                    <td>${esc(r.request_type)}</td>
                    <td class="${cls}">${icon} ${r.status_code || '—'}</td>
                    <td>${r.data_items_returned ?? '—'}</td>
                    <td>${r.latency_ms ?? '—'} ms</td>
                </tr>`;
            }).join('') || '<tr><td colspan="5" style="color:var(--text-dim)">No log entries</td></tr>';

            $('#detail-overlay').classList.add('active');
        } catch (e) {
            console.error('[Detail] load failed:', e);
        }
    }

    function closeDetail() {
        $('#detail-overlay').classList.remove('active');
    }

    // ── Dedup panel ─────────────────────────────────────────────
    async function loadDedup() {
        try {
            const r = await fetch('/api/dedup/summary');
            const d = await r.json();
            if (d.status !== 'ok') return;

            const grid = $('#dedup-grid');
            grid.innerHTML = `
                <div class="dedup-card"><div class="val">${fmt(d.active_stores)}</div><div class="lbl">Active Stores</div></div>
                <div class="dedup-card"><div class="val">${fmt(d.inactive_merged)}</div><div class="lbl">Merged (Inactive)</div></div>
                <div class="dedup-card"><div class="val">${fmt(d.aliases)}</div><div class="lbl">Aliases</div></div>
                <div class="dedup-card"><div class="val">${fmt(d.estimated_remaining_duplicates)}</div><div class="lbl">Est. Remaining Dupes</div></div>
            `;
        } catch (e) {
            console.error('[Dedup] load failed:', e);
        }
    }

    async function runDedup(dryRun) {
        const status = $('#dedup-status');
        const result = $('#dedup-result');
        status.textContent = dryRun ? 'Running dry run…' : 'Running dedup…';
        result.style.display = 'none';

        try {
            const r = await fetch('/api/dedup/run', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ dry_run: dryRun }),
            });
            const d = await r.json();
            status.textContent = d.status === 'ok'
                ? `Done: ${d.stores_merged} merged, ${d.signals_reassigned} signals moved`
                : 'Error: ' + (d.message || 'unknown');

            result.style.display = 'block';
            result.textContent = JSON.stringify(d, null, 2);

            // Refresh dedup panel
            loadDedup();
        } catch (e) {
            status.textContent = 'Error: ' + e.message;
        }
    }

    // ── Refresh ─────────────────────────────────────────────────
    function refreshAll() {
        loadMetrics();
        loadDedup();
        $('#last-refresh').textContent = 'Last: ' + new Date().toLocaleTimeString();
    }

    // ── Init ────────────────────────────────────────────────────
    function init() {
        initSort();
        refreshAll();

        // Bind events
        $('#refresh-all').addEventListener('click', refreshAll);
        $('#period-select').addEventListener('change', () => { loadMetrics(); });
        $('#detail-close').addEventListener('click', closeDetail);
        $('#detail-overlay').addEventListener('click', e => {
            if (e.target === $('#detail-overlay')) closeDetail();
        });
        $('#dedup-dry-run-btn').addEventListener('click', () => runDedup(true));
        $('#dedup-run-btn').addEventListener('click', () => {
            if (confirm('Run live dedup? This will merge duplicate stores.')) {
                runDedup(false);
            }
        });

        // Auto-refresh
        pollTimer = setInterval(refreshAll, POLL_INTERVAL);
    }

    document.addEventListener('DOMContentLoaded', init);
})();

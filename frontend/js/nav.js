/**
 * nav.js — Global navigation bar + shared meta loader.
 *
 * Every page includes this script. It:
 *   1. Fetches /api/meta once and caches it in sessionStorage (5 min TTL).
 *   2. Injects the nav bar with page links + live store/brand counts.
 *   3. Exposes window.heliosMeta (Promise) so page-specific JS can await it.
 *
 * Usage in page JS:
 *   const meta = await window.heliosMeta;
 *   meta.industries  — [{key, display_name, brands: [...]}]
 *   meta.brands      — [{key, display_name, industry, store_count}]
 *   meta.pages       — [{path, label, icon}]
 *   meta.store_total — number
 */

(function () {
    'use strict';

    const CACHE_KEY = 'helios_meta';
    const CACHE_TTL = 5 * 60 * 1000; // 5 minutes

    // ── Fetch + cache /api/meta ─────────────────────────────────
    function fetchMeta() {
        // Check cache
        try {
            const raw = sessionStorage.getItem(CACHE_KEY);
            if (raw) {
                const cached = JSON.parse(raw);
                if (Date.now() - cached._ts < CACHE_TTL) {
                    return Promise.resolve(cached.data);
                }
            }
        } catch (_) { /* ignore corrupt cache */ }

        return fetch('/api/meta')
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (d.status === 'ok') {
                    try {
                        sessionStorage.setItem(CACHE_KEY, JSON.stringify({ _ts: Date.now(), data: d }));
                    } catch (_) { /* storage full — fine */ }
                }
                return d;
            })
            .catch(function (err) {
                console.warn('[Nav] Meta fetch failed:', err);
                return { status: 'error', industries: [], brands: [], pages: [], store_total: 0 };
            });
    }

    // Expose the promise globally so page scripts can await it
    window.heliosMeta = fetchMeta();

    // Force-refresh util (called after data changes)
    window.heliosRefreshMeta = function () {
        sessionStorage.removeItem(CACHE_KEY);
        window.heliosMeta = fetchMeta();
        return window.heliosMeta;
    };

    // ── Inject nav bar ──────────────────────────────────────────
    function injectNav(meta) {
        // Don't double-inject
        if (document.getElementById('global-nav')) return;

        var nav = document.createElement('nav');
        nav.id = 'global-nav';

        // Brand
        var brand = document.createElement('a');
        brand.className = 'nav-brand';
        brand.href = '/';
        brand.textContent = 'Helios';
        nav.appendChild(brand);

        // Links container
        var links = document.createElement('div');
        links.className = 'nav-links';

        var currentPath = window.location.pathname;

        var pages = (meta && meta.pages) || [
            { path: '/', label: 'Map', icon: '🗺️' },
            { path: '/openclaw', label: 'OpenClaw', icon: '🦀' },
            { path: '/openclaw/session', label: 'Session', icon: '⚡' },
            { path: '/metrics', label: 'Metrics', icon: '📊' },
        ];

        pages.forEach(function (p) {
            var a = document.createElement('a');
            a.className = 'nav-link';
            a.href = p.path;

            // Determine active: exact match or prefix for sub-paths
            if (currentPath === p.path ||
                (p.path !== '/' && currentPath.startsWith(p.path))) {
                a.classList.add('active');
            }

            a.innerHTML = '<span class="nav-icon">' + (p.icon || '') + '</span> ' + p.label;
            links.appendChild(a);
        });

        nav.appendChild(links);

        // Spacer
        var spacer = document.createElement('div');
        spacer.className = 'nav-spacer';
        nav.appendChild(spacer);

        // Meta counts
        var metaDiv = document.createElement('div');
        metaDiv.className = 'nav-meta';

        if (meta && meta.store_total != null) {
            var countSpan = document.createElement('span');
            countSpan.className = 'nav-count';
            countSpan.textContent = Number(meta.store_total).toLocaleString() + ' stores';
            metaDiv.appendChild(countSpan);
        }

        if (meta && meta.industries) {
            var indSpan = document.createElement('span');
            indSpan.className = 'nav-count';
            indSpan.textContent = meta.industries.length + ' industries · ' +
                (meta.brands ? meta.brands.length : 0) + ' brands';
            metaDiv.appendChild(indSpan);
        }

        nav.appendChild(metaDiv);

        // Insert at top of body
        document.body.insertBefore(nav, document.body.firstChild);
    }

    // Wait for meta then inject
    window.heliosMeta.then(injectNav);

})();

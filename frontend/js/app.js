/**
 * ChainStaffingTracker — Leaflet map application
 *
 * Fetches store scores and targeting data from the Flask API
 * and renders them on a dark-themed Leaflet map centered on Austin, TX.
 */

(function () {
    'use strict';

    const API_BASE = '';
    const AUSTIN_CENTER = [30.2672, -97.7431];
    const DEFAULT_ZOOM = 11;

    // Tier colors
    const TIER_COLORS = {
        critical: '#e94560',
        elevated: '#f0a500',
        adequate: '#4ecca3',
        unknown: '#666',
        prime: '#e94560',
        strong: '#f0a500',
        moderate: '#4ecca3',
    };

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

    let markers = [];

    // ── Fetch and render scores ─────────────────────────────────────
    async function loadScores() {
        const chainFilter = document.getElementById('chain-filter').value;
        const tierFilter = document.getElementById('tier-filter').value;

        let url = API_BASE + '/api/scores?region=austin_tx';
        if (chainFilter) url += '&chain=' + chainFilter;

        try {
            const resp = await fetch(url);
            const data = await resp.json();

            // Clear existing markers
            markers.forEach(m => map.removeLayer(m));
            markers = [];

            let stores = data.stores || [];
            if (tierFilter) {
                stores = stores.filter(s => s.tier === tierFilter);
            }

            stores.forEach(store => {
                if (!store.lat || !store.lng) return;

                const color = TIER_COLORS[store.tier] || TIER_COLORS.unknown;
                const marker = L.circleMarker([store.lat, store.lng], {
                    radius: 8,
                    fillColor: color,
                    color: color,
                    weight: 2,
                    opacity: 0.9,
                    fillOpacity: 0.6,
                }).addTo(map);

                marker.bindPopup(
                    '<strong>' + (store.store_name || store.store_num) + '</strong><br>' +
                    'Score: ' + store.score.toFixed(1) + '<br>' +
                    'Tier: <span style="color:' + color + '">' + store.tier + '</span><br>' +
                    '<small>' + (store.address || '') + '</small>'
                );

                markers.push(marker);
            });
        } catch (err) {
            console.error('Failed to load scores:', err);
        }
    }

    // ── Fetch and render targets ────────────────────────────────────
    async function loadTargets() {
        try {
            const resp = await fetch(API_BASE + '/api/targeting?region=austin_tx&limit=10');
            const data = await resp.json();
            const container = document.getElementById('targets-list');
            container.innerHTML = '';

            (data.targets || []).forEach((target, i) => {
                const color = TIER_COLORS[target.targeting_tier] || '#666';
                const card = document.createElement('div');
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
                    (target.wage_premium_pct !== null ? ' | Premium: ' + target.wage_premium_pct + '%' : '') +
                    '</div>';
                container.appendChild(card);
            });
        } catch (err) {
            console.error('Failed to load targets:', err);
        }
    }

    // ── Event listeners ─────────────────────────────────────────────
    document.getElementById('refresh-btn').addEventListener('click', () => {
        loadScores();
        loadTargets();
    });

    document.getElementById('chain-filter').addEventListener('change', loadScores);
    document.getElementById('tier-filter').addEventListener('change', loadScores);

    // ── Initial load ────────────────────────────────────────────────
    loadScores();
    loadTargets();
})();

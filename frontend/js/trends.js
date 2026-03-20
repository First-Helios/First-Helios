/**
 * trends.js — Chain Staffing Tracker
 * ====================================
 * Fetches scan history from /api/history and renders:
 *   1. A canvas line-chart of critical / low / total stores over time.
 *   2. A "changes" table highlighting stores that shifted status since the
 *      previous snapshot (the key insight: how critical openings move).
 *   3. A per-store history drill-down when you click a row.
 *
 * The panel lives in a slide-out drawer triggered by a button in the
 * sidebar stats card.
 */

const Trends = (() => {
  /* ── State ────────────────────────────────────────────────── */
  let _history   = [];   // raw snapshots from /api/history
  let _expanded  = {};   // storeNum → true  (drill-down open)
  let _chartCtx  = null; // canvas 2D context

  /* ── DOM refs (bound on init) ─────────────────────────────── */
  let $drawer, $overlay, $chart, $changes, $snapCount, $noData, $closeBtn;

  /* Level shorthand → full label */
  const LVL = { c: 'critical', l: 'low', u: 'unknown' };
  const LVL_LABEL = { c: 'Critical', l: 'Low', u: 'Unknown' };
  const LVL_COLOR = {
    c: '#ef4444',   // red
    l: '#f59e0b',   // amber
    u: '#64748b',   // slate
  };
  const TOTAL_COLOR = '#22d3ee'; // cyan

  /* ── Init ─────────────────────────────────────────────────── */
  function init() {
    $drawer    = document.getElementById('trends-drawer');
    $overlay   = document.getElementById('trends-overlay');
    $chart     = document.getElementById('trends-chart');
    $changes   = document.getElementById('trends-changes');
    $snapCount = document.getElementById('trends-snap-count');
    $noData    = document.getElementById('trends-no-data');
    $closeBtn  = document.getElementById('trends-close');

    if (!$drawer) return;

    $closeBtn.addEventListener('click', close);
    $overlay.addEventListener('click', close);

    document.getElementById('trends-open-btn')
      ?.addEventListener('click', open);
  }

  /* ── Open / Close ─────────────────────────────────────────── */
  async function open() {
    $drawer.classList.add('open');
    $overlay.classList.add('visible');
    document.body.classList.add('trends-open');
    await fetchAndRender();
  }

  function close() {
    $drawer.classList.remove('open');
    $overlay.classList.remove('visible');
    document.body.classList.remove('trends-open');
  }

  /* ── Data fetch ───────────────────────────────────────────── */
  async function fetchAndRender() {
    try {
      const resp = await fetch('/api/history', { cache: 'no-cache' });
      if (!resp.ok) { _showEmpty(); return; }
      _history = await resp.json();
    } catch {
      _showEmpty();
      return;
    }
    if (!_history.length) { _showEmpty(); return; }

    $noData.hidden = true;
    $chart.hidden  = false;
    $changes.hidden = false;
    $snapCount.textContent = `${_history.length} scan${_history.length !== 1 ? 's' : ''} recorded`;

    _drawChart();
    _renderChanges();
  }

  function _showEmpty() {
    $noData.hidden = false;
    $chart.hidden  = true;
    $changes.hidden = true;
    $snapCount.textContent = 'No history yet';
  }

  /* ── Chart ────────────────────────────────────────────────── */
  function _drawChart() {
    const canvas = $chart;
    const dpr    = window.devicePixelRatio || 1;
    const rect   = canvas.parentElement.getBoundingClientRect();
    const W      = Math.floor(rect.width) || 600;
    const H      = 220;
    canvas.width  = W * dpr;
    canvas.height = H * dpr;
    canvas.style.width  = W + 'px';
    canvas.style.height = H + 'px';

    const ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, W, H);

    const PAD = { top: 20, right: 20, bottom: 40, left: 40 };
    const cw = W - PAD.left - PAD.right;
    const ch = H - PAD.top  - PAD.bottom;

    // Datasets
    const snaps  = _history;
    const n      = snaps.length;
    if (n < 1) return;

    const series = {
      total:    snaps.map(s => s.summary?.total    || 0),
      critical: snaps.map(s => s.summary?.critical || 0),
      low:      snaps.map(s => s.summary?.low      || 0),
    };
    const maxVal = Math.max(1, ...series.total, ...series.critical, ...series.low);

    // Helper: x/y from index + value
    const xOf = i => PAD.left + (n > 1 ? (i / (n - 1)) * cw : cw / 2);
    const yOf = v => PAD.top + ch - (v / maxVal) * ch;

    // Grid lines
    ctx.strokeStyle = 'rgba(255,255,255,0.06)';
    ctx.lineWidth   = 1;
    const gridLines = 4;
    for (let g = 0; g <= gridLines; g++) {
      const y = PAD.top + (g / gridLines) * ch;
      ctx.beginPath(); ctx.moveTo(PAD.left, y); ctx.lineTo(PAD.left + cw, y); ctx.stroke();
      // Label
      const val = Math.round(maxVal * (1 - g / gridLines));
      ctx.fillStyle = 'rgba(255,255,255,0.35)';
      ctx.font = '10px system-ui, sans-serif';
      ctx.textAlign = 'right';
      ctx.fillText(val, PAD.left - 6, y + 3);
    }

    // X‑axis labels (dates)
    ctx.fillStyle = 'rgba(255,255,255,0.35)';
    ctx.font = '10px system-ui, sans-serif';
    ctx.textAlign = 'center';
    const maxLabels = Math.min(n, Math.floor(cw / 70));
    const step = Math.max(1, Math.floor(n / maxLabels));
    for (let i = 0; i < n; i += step) {
      const d = new Date(snaps[i].ts);
      const lbl = `${d.getMonth()+1}/${d.getDate()}`;
      ctx.fillText(lbl, xOf(i), H - PAD.bottom + 16);
    }

    // Draw lines
    function drawLine(data, color, width = 2) {
      ctx.strokeStyle = color;
      ctx.lineWidth   = width;
      ctx.lineJoin    = 'round';
      ctx.beginPath();
      for (let i = 0; i < data.length; i++) {
        const x = xOf(i), y = yOf(data[i]);
        i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
      }
      ctx.stroke();

      // Dots for each data point
      ctx.fillStyle = color;
      for (let i = 0; i < data.length; i++) {
        ctx.beginPath();
        ctx.arc(xOf(i), yOf(data[i]), 3, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    // Area fill for critical
    ctx.globalAlpha = 0.10;
    ctx.fillStyle   = LVL_COLOR.c;
    ctx.beginPath();
    ctx.moveTo(xOf(0), yOf(0));
    for (let i = 0; i < n; i++) ctx.lineTo(xOf(i), yOf(series.critical[i]));
    ctx.lineTo(xOf(n - 1), yOf(0));
    ctx.closePath();
    ctx.fill();
    ctx.globalAlpha = 1;

    drawLine(series.total,    TOTAL_COLOR,   1.5);
    drawLine(series.low,      LVL_COLOR.l,   2);
    drawLine(series.critical, LVL_COLOR.c,   2.5);

    // Legend
    const legend = [
      { label: 'Total stores',    color: TOTAL_COLOR },
      { label: 'Critical',        color: LVL_COLOR.c },
      { label: 'Low',             color: LVL_COLOR.l },
    ];
    ctx.font = '11px system-ui, sans-serif';
    let lx = PAD.left;
    for (const { label, color } of legend) {
      ctx.fillStyle = color;
      ctx.fillRect(lx, H - 14, 12, 3);
      ctx.fillStyle = 'rgba(255,255,255,0.6)';
      ctx.textAlign = 'left';
      ctx.fillText(label, lx + 16, H - 8);
      lx += ctx.measureText(label).width + 30;
    }
  }

  /* ── Changes table ────────────────────────────────────────── */
  function _renderChanges() {
    $changes.innerHTML = '';

    if (_history.length < 2) {
      $changes.innerHTML = '<p class="changes-note">Need at least 2 scans to show changes.</p>';
      return;
    }

    const prev = _history[_history.length - 2];
    const curr = _history[_history.length - 1];

    // Diff: find stores whose level changed
    const diffs = [];
    const allNums = new Set([...Object.keys(prev.stores || {}), ...Object.keys(curr.stores || {})]);
    for (const num of allNums) {
      const pLvl = prev.stores?.[num]?.l || null;
      const cLvl = curr.stores?.[num]?.l || null;
      if (pLvl !== cLvl) {
        diffs.push({
          num,
          name: curr.stores?.[num]?.n || prev.stores?.[num]?.n || `Store #${num}`,
          from: pLvl,
          to:   cLvl,
          score: curr.stores?.[num]?.s ?? 0,
          roles: curr.stores?.[num]?.r || {},
        });
      }
    }

    // Sort: escalations first (→ critical), then de-escalations
    const lvlRank = { c: 3, l: 2, u: 1, null: 0 };
    diffs.sort((a, b) => {
      const aUp = (lvlRank[a.to] || 0) - (lvlRank[a.from] || 0);
      const bUp = (lvlRank[b.to] || 0) - (lvlRank[b.from] || 0);
      return bUp - aUp || (b.score - a.score);
    });

    // Heading
    const prevDate = new Date(prev.ts);
    const currDate = new Date(curr.ts);
    const fmt = d => `${d.getMonth()+1}/${d.getDate()} ${d.getHours()}:${String(d.getMinutes()).padStart(2,'0')}`;
    const heading = document.createElement('h4');
    heading.className = 'changes-heading';
    heading.innerHTML = `<i class="fa-solid fa-arrow-right-arrow-left"></i> Changes: ` +
      `<span class="changes-date">${fmt(prevDate)}</span> → <span class="changes-date">${fmt(currDate)}</span>` +
      ` <span class="changes-count">(${diffs.length} store${diffs.length !== 1 ? 's' : ''})</span>`;
    $changes.appendChild(heading);

    if (!diffs.length) {
      const note = document.createElement('p');
      note.className = 'changes-note';
      note.textContent = 'No status changes between last two scans.';
      $changes.appendChild(note);
      return;
    }

    // Table
    const table = document.createElement('table');
    table.className = 'changes-table';
    table.innerHTML = `<thead><tr>
      <th>Store</th><th>Name</th><th>Was</th><th></th><th>Now</th><th>Score</th>
    </tr></thead>`;
    const tbody = document.createElement('tbody');

    for (const d of diffs) {
      const tr = document.createElement('tr');
      const isEscalation = (lvlRank[d.to] || 0) > (lvlRank[d.from] || 0);
      tr.className = isEscalation ? 'change-escalation' : 'change-deescalation';

      const fromLabel = d.from ? LVL_LABEL[d.from] : '(new)';
      const toLabel   = d.to   ? LVL_LABEL[d.to]   : '(gone)';
      const fromColor = d.from ? LVL_COLOR[d.from]  : '#475569';
      const toColor   = d.to   ? LVL_COLOR[d.to]    : '#475569';

      tr.innerHTML = `
        <td class="store-num">#${d.num}</td>
        <td class="store-name">${_esc(d.name)}</td>
        <td><span class="level-pill" style="background:${fromColor}">${fromLabel}</span></td>
        <td class="arrow">→</td>
        <td><span class="level-pill" style="background:${toColor}">${toLabel}</span></td>
        <td class="score">${d.score}</td>`;

      // Click to expand store history
      tr.style.cursor = 'pointer';
      tr.addEventListener('click', () => _toggleStoreHistory(d.num, tr));
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    $changes.appendChild(table);

    // Summary sentence
    const esc   = diffs.filter(d => (lvlRank[d.to] || 0) > (lvlRank[d.from] || 0)).length;
    const deesc = diffs.filter(d => (lvlRank[d.to] || 0) < (lvlRank[d.from] || 0)).length;
    const summ = document.createElement('p');
    summ.className = 'changes-summary';
    summ.innerHTML = `<span class="esc-up">▲ ${esc} escalated</span> · <span class="esc-down">▼ ${deesc} de-escalated</span>`;
    $changes.appendChild(summ);
  }

  /* ── Store drill-down ─────────────────────────────────────── */
  function _toggleStoreHistory(storeNum, rowEl) {
    const existingDetail = rowEl.nextElementSibling;
    if (existingDetail?.classList.contains('store-history-row')) {
      existingDetail.remove();
      return;
    }

    // Build timeline for this store across all snapshots
    const entries = [];
    for (const snap of _history) {
      const st = snap.stores?.[storeNum];
      entries.push({
        ts:   snap.ts,
        lvl:  st?.l  || null,
        score: st?.s  ?? 0,
        lc:   st?.lc ?? 0,
        roles: st?.r  || {},
      });
    }

    const detailRow = document.createElement('tr');
    detailRow.className = 'store-history-row';
    const td = document.createElement('td');
    td.colSpan = 6;

    let html = `<div class="store-timeline">
      <div class="timeline-header">Store #${storeNum} — full scan history</div>
      <div class="timeline-entries">`;

    for (const e of entries) {
      const d = new Date(e.ts);
      const dateStr = `${d.getMonth()+1}/${d.getDate()} ${d.getHours()}:${String(d.getMinutes()).padStart(2,'0')}`;
      const lvlFull = e.lvl ? LVL_LABEL[e.lvl] : '—';
      const color   = e.lvl ? LVL_COLOR[e.lvl]  : '#475569';
      const roleStr = Object.entries(e.roles).map(([r, c]) => `${r}: ${c}`).join(', ') || 'none';

      html += `<div class="timeline-entry">
        <span class="tl-date">${dateStr}</span>
        <span class="level-pill" style="background:${color}">${lvlFull}</span>
        <span class="tl-score">Score ${e.score}</span>
        <span class="tl-roles">${_esc(roleStr)}</span>
      </div>`;
    }

    html += '</div></div>';
    td.innerHTML = html;
    detailRow.appendChild(td);
    rowEl.after(detailRow);
  }

  /* ── Helpers ──────────────────────────────────────────────── */
  function _esc(s) {
    const el = document.createElement('span');
    el.textContent = s;
    return el.innerHTML;
  }

  /* ── Public API ───────────────────────────────────────────── */
  return { init, open, close };
})();

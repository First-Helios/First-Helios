/**
 * ui.js — Chain Staffing Tracker
 * Manages the sidebar list, regional stats, alert banner,
 * report modal, toasts, and sidebar toggle.
 */

const UI = (() => {
  /* ── DOM refs ───────────────────────────────────────────────── */
  const $locationList   = document.getElementById('location-list');
  const $locationCount  = document.getElementById('location-count');
  const $statTotal      = document.getElementById('stat-total');
  const $statAdequate   = document.getElementById('stat-adequate');
  const $statLow        = document.getElementById('stat-low');
  const $statCritical   = document.getElementById('stat-critical');
  const $statUnknown    = document.getElementById('stat-unknown');

  const $alertBanner    = document.getElementById('alert-banner');
  const $alertText      = document.getElementById('alert-text');
  const $alertClose     = document.getElementById('alert-close');

  const $mainContent    = document.getElementById('main-content');
  const $mapHint        = document.getElementById('map-overlay-hint');

  const $sidebar        = document.getElementById('sidebar');
  const $sidebarToggle  = document.getElementById('sidebar-toggle');

  const $fetchStatus    = document.getElementById('fetch-status');

  const $modal          = document.getElementById('report-modal');
  const $modalClose     = document.getElementById('modal-close-btn');
  const $modalCancel    = document.getElementById('modal-cancel-btn');
  const $modalSubmit    = document.getElementById('modal-submit-btn');
  const $modalTitle     = document.getElementById('modal-title');
  const $modalLocName   = document.getElementById('modal-location-name');
  const $modalLocAddr   = document.getElementById('modal-location-addr');
  const $levelSelector  = document.getElementById('level-selector');
  const $reportComment  = document.getElementById('report-comment');
  const $formerStaff    = document.getElementById('former-staff-check');
  const $toastContainer = document.getElementById('toast-container');

  /* ── Internal state ─────────────────────────────────────────── */
  let _locations       = [];    // All Location objects for current region
  let _activeFilter    = 'all';
  let _selectedLevel   = null;
  let _activeLocationId = null; // currently focused in sidebar
  let _modalLocation   = null;  // Location being reported on
  let _onFocusLocation = null;  // callback(locationId)
  let _onReportSubmit  = null;  // callback(locationId, level, comment, isFormerStaff)

  /* ================================================================
     STATUS BADGE (header)
     ================================================================ */
  function setStatus(type, text) {
    $fetchStatus.className = `status-badge status-${type}`;
    $fetchStatus.querySelector('i').className = {
      idle:    'fa-solid fa-circle-dot',
      loading: 'fa-solid fa-circle-notch fa-spin',
      ok:      'fa-solid fa-circle-check',
      error:   'fa-solid fa-circle-exclamation',
    }[type] || 'fa-solid fa-circle-dot';
    $fetchStatus.querySelector('span').textContent = text;
  }

  /* ================================================================
     MAP HINT
     ================================================================ */
  function hideMapHint() {
    if ($mapHint) {
      $mapHint.classList.add('fade-out');
      setTimeout(() => $mapHint.classList.add('hidden'), 300);
    }
  }

  /* ================================================================
     SIDEBAR TOGGLE
     ================================================================ */
  (function initSidebarToggle() {
    $sidebarToggle.addEventListener('click', () => {
      const collapsed = $sidebar.classList.toggle('collapsed');
      $sidebarToggle.querySelector('i').className = collapsed
        ? 'fa-solid fa-angles-right'
        : 'fa-solid fa-angles-left';
      // Show/hide the expand button over the map (inserted by map container)
      let expandBtn = document.getElementById('sidebar-expand-btn');
      if (collapsed) {
        if (!expandBtn) {
          expandBtn = document.createElement('button');
          expandBtn.id = 'sidebar-expand-btn';
          expandBtn.innerHTML = '<i class="fa-solid fa-angles-right"></i> Locations';
          document.getElementById('map-container').appendChild(expandBtn);
        }
        expandBtn.style.display = 'flex';
        expandBtn.onclick = () => {
          $sidebar.classList.remove('collapsed');
          $sidebarToggle.querySelector('i').className = 'fa-solid fa-angles-left';
          expandBtn.style.display = 'none';
        };
      } else if (expandBtn) {
        expandBtn.style.display = 'none';
      }
    });
  })();

  /* ================================================================
     ALERT BANNER
     ================================================================ */
  function showAlert(level, text) {
    $alertBanner.className    = `alert-banner level-${level}`;
    $alertText.textContent    = text;
    $alertBanner.classList.remove('hidden');
    $mainContent.classList.add('banner-visible');
  }

  function hideAlert() {
    $alertBanner.classList.add('hidden');
    $mainContent.classList.remove('banner-visible');
  }

  $alertClose.addEventListener('click', hideAlert);

  /**
   * Update regional stats and fire/clear alerts.
   * @param {string[]} locationIds
   */
  function updateStats(locationIds) {
    const stats = Data.getRegionalStats(locationIds);
    $statTotal.textContent    = stats.total    || '—';
    $statAdequate.textContent = stats.adequate || '0';
    $statLow.textContent      = stats.low      || '0';
    $statCritical.textContent = stats.critical || '0';
    $statUnknown.textContent  = stats.unknown  || '0';

    if (stats.alertLevel === 'critical') {
      const pct = Math.round((stats.critical / stats.total) * 100);
      showAlert('critical',
        `⚠ CRITICAL REGIONAL ALERT: ${stats.critical} of ${stats.total} locations (${pct}%) are critically understaffed in this area.`);
    } else if (stats.alertLevel === 'low') {
      const lowTotal = stats.low + stats.critical;
      const pct      = Math.round((lowTotal / stats.total) * 100);
      showAlert('low',
        `⚠ LOW STAFFING ALERT: ${lowTotal} of ${stats.total} locations (${pct}%) are reporting low or critical staffing in this area.`);
    } else {
      hideAlert();
    }
  }

  /* ================================================================
     FILTER BAR
     ================================================================ */
  document.querySelectorAll('.filter-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      _activeFilter = btn.dataset.filter;
      renderList(_locations);
    });
  });

  /* ================================================================
     LOCATION LIST
     ================================================================ */

  /**
   * Render the sidebar location list from an array of Location objects.
   * Respects the active filter and sorts: critical → low → adequate → unknown.
   * @param {Location[]} locations
   */
  function renderList(locations) {
    _locations = locations;

    // Update count badge
    $locationCount.textContent = locations.length;

    if (locations.length === 0) {
      $locationList.innerHTML = `
        <li class="list-placeholder">
          <i class="fa-solid fa-magnifying-glass"></i>
          <p>No Starbucks locations found in this area.</p>
        </li>`;
      return;
    }

    // Compute status + sort
    const statusOrder = { critical: 0, low: 1, adequate: 2, unknown: 3 };
    const withStatus = locations.map(loc => ({
      loc,
      status: Data.getStatus(loc.id),
    }));
    withStatus.sort((a, b) =>
      (statusOrder[a.status] ?? 3) - (statusOrder[b.status] ?? 3)
    );

    // Filter
    const filtered = _activeFilter === 'all'
      ? withStatus
      : withStatus.filter(({ status }) => status === _activeFilter);

    if (filtered.length === 0) {
      $locationList.innerHTML = `
        <li class="list-placeholder">
          <i class="fa-solid fa-filter"></i>
          <p>No locations match the "${_activeFilter}" filter.</p>
        </li>`;
      return;
    }

    $locationList.innerHTML = '';
    for (const { loc, status } of filtered) {
      $locationList.appendChild(buildListItem(loc, status));
    }
  }

  function buildListItem(loc, status) {
    const recentCount = Data.getRecentCount(loc.id);
    const levelLabel  = status.charAt(0).toUpperCase() + status.slice(1);
    const vacancy     = Data.getVacancyInfo(loc.id);
    const li          = document.createElement('li');
    li.className      = `list-item${loc.id === _activeLocationId ? ' active' : ''}`;
    li.dataset.id     = loc.id;

    const vacancyBadge = vacancy && vacancy.listing_count > 0
      ? `<span class="list-item-vacancy" title="${vacancy.listing_count} open listings on Starbucks Careers">` +
        `<i class="fa-solid fa-briefcase-blank"></i> ${vacancy.listing_count} open</span>`
      : '';

    li.innerHTML = `
      <span class="list-item-dot dot-${status}"></span>
      <div class="list-item-info">
        <p class="list-item-name" title="${escapeHtml(loc.name)}">${escapeHtml(loc.name)}</p>
        <p class="list-item-addr" title="${escapeHtml(loc.address)}">${escapeHtml(loc.address || 'Address not available')}</p>
        <div class="list-item-meta">
          <span class="list-item-level level-${status}">${levelLabel}</span>
          <span class="list-item-reports">${recentCount} report${recentCount !== 1 ? 's' : ''}</span>
          ${vacancyBadge}
        </div>
      </div>
      <div class="list-item-actions">
        <button title="Zoom to location" data-action="focus">
          <i class="fa-solid fa-location-dot"></i>
        </button>
        <button title="Report staffing" data-action="report">
          <i class="fa-solid fa-flag"></i>
        </button>
      </div>
    `;

    // Click on the main row → focus on map
    li.addEventListener('click', e => {
      if (e.target.closest('[data-action]')) return;
      setActiveListing(loc.id);
      _onFocusLocation && _onFocusLocation(loc.id);
    });
    li.querySelector('[data-action="focus"]').addEventListener('click', () => {
      setActiveListing(loc.id);
      _onFocusLocation && _onFocusLocation(loc.id);
    });
    li.querySelector('[data-action="report"]').addEventListener('click', () => {
      openReportModal(loc);
    });

    return li;
  }

  function setActiveListing(locationId) {
    _activeLocationId = locationId;
    document.querySelectorAll('#location-list .list-item').forEach(el => {
      el.classList.toggle('active', el.dataset.id === locationId);
    });
    // Scroll this item into view
    const el = document.querySelector(`#location-list .list-item[data-id="${locationId}"]`);
    el?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }

  /** Show a loading skeleton in the list while data loads. */
  function showListLoading() {
    $locationList.innerHTML = `
      <li class="loading-spinner">
        <div class="spinner"></div>
        <span>Fetching Starbucks locations…</span>
      </li>`;
    $locationCount.textContent = '…';
    $statTotal.textContent = '—';
    $statAdequate.textContent = '—';
    $statLow.textContent = '—';
    $statCritical.textContent = '—';
    $statUnknown.textContent = '—';
  }

  /* ================================================================
     REPORT MODAL
     ================================================================ */

  function openReportModal(location) {
    _modalLocation  = location;
    _selectedLevel  = null;

    // Reset UI
    $modalLocName.textContent = location.name;
    $modalLocAddr.textContent = location.address || '';
    $reportComment.value      = '';
    $formerStaff.checked      = false;
    $modalSubmit.disabled     = true;
    document.querySelectorAll('.level-btn').forEach(b => b.classList.remove('selected'));

    $modal.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
  }

  function closeReportModal() {
    $modal.classList.add('hidden');
    document.body.style.overflow = '';
    _modalLocation = null;
    _selectedLevel = null;
  }

  // Level selection
  $levelSelector.querySelectorAll('.level-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.level-btn').forEach(b => b.classList.remove('selected'));
      btn.classList.add('selected');
      _selectedLevel = btn.dataset.level;
      $modalSubmit.disabled = false;
    });
  });

  // Close handlers
  $modalClose.addEventListener('click',  closeReportModal);
  $modalCancel.addEventListener('click', closeReportModal);
  $modal.querySelector('.modal-backdrop').addEventListener('click', closeReportModal);

  // Submit
  $modalSubmit.addEventListener('click', () => {
    if (!_selectedLevel || !_modalLocation) return;
    const comment      = $reportComment.value;
    const isFormerStaff = $formerStaff.checked;
    _onReportSubmit && _onReportSubmit(_modalLocation, _selectedLevel, comment, isFormerStaff);
    closeReportModal();
  });

  // Escape key closes modal
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && !$modal.classList.contains('hidden')) closeReportModal();
  });

  /* ================================================================
     TOASTS
     ================================================================ */
  function showToast(type, message, duration = 3500) {
    const icons = {
      success: 'fa-circle-check',
      error:   'fa-circle-exclamation',
      info:    'fa-circle-info',
    };
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `<i class="fa-solid ${icons[type] || icons.info}"></i><span>${message}</span>`;
    $toastContainer.appendChild(toast);
    setTimeout(() => {
      toast.style.transition = 'opacity 0.35s, transform 0.35s';
      toast.style.opacity    = '0';
      toast.style.transform  = 'translateX(30px)';
      setTimeout(() => toast.remove(), 400);
    }, duration);
  }

  /* ================================================================
     HELPERS
     ================================================================ */
  function escapeHtml(str) {
    return String(str || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  /* ================================================================
     PUBLIC API
     ================================================================ */
  return {
    setStatus,
    hideMapHint,
    renderList,
    showListLoading,
    updateStats,
    openReportModal,
    showToast,
    setActiveListing,
    set onFocusLocation(fn)  { _onFocusLocation = fn; },
    set onReportSubmit(fn)   { _onReportSubmit  = fn; },
  };
})();

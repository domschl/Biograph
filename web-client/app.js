/* ============================================================
   Biograph Web Client — app.js
   Responsive Single Page Application with View Transitions
   ============================================================ */

// ── 1. Application State ─────────────────────────────────────
const state = {
  serverUrl: localStorage.getItem('biograph_server_url') || '',
  token: localStorage.getItem('biograph_token') || '',
  currentView: '',
  
  // Timeline state
  timelineEvents: [],
  timelineTotal: 0,
  timelineOffset: 0,
  timelineLimit: 100,
  
  // Search state
  searchQuery: '',
  searchTypes: [],
  searchFrom: '',
  searchTo: '',
  searchResults: [],
  searchTotal: 0,
  searchOffset: 0,
  searchLimit: 100,
  
  isConnected: null // null = checking, true = connected, false = error
};

// ── 2. Utility Functions ─────────────────────────────────────

/**
 * Escapes unsafe characters for HTML injection.
 */
function escapeHtml(unsafe) {
  if (unsafe === undefined || unsafe === null) return '';
  return String(unsafe)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

/**
 * Normalises a date string to start of local day ISO.
 */
function getFromIsoString(dateStr) {
  if (!dateStr) return '';
  const d = new Date(`${dateStr}T00:00:00`);
  return d.toISOString();
}

/**
 * Normalises a date string to end of local day ISO.
 */
function getToIsoString(dateStr) {
  if (!dateStr) return '';
  const d = new Date(`${dateStr}T23:59:59.999`);
  return d.toISOString();
}

/**
 * Formats YYYY-MM-DD day key into human-friendly relative or absolute dates.
 */
function formatDayLabel(dateStr) {
  const localToday = new Date();
  const todayStr = localToday.getFullYear() + '-' + 
    String(localToday.getMonth() + 1).padStart(2, '0') + '-' + 
    String(localToday.getDate()).padStart(2, '0');
  
  const localYesterday = new Date(localToday);
  localYesterday.setDate(localToday.getDate() - 1);
  const yesterdayStr = localYesterday.getFullYear() + '-' + 
    String(localYesterday.getMonth() + 1).padStart(2, '0') + '-' + 
    String(localYesterday.getDate()).padStart(2, '0');
  
  if (dateStr === todayStr) {
    return 'Today';
  } else if (dateStr === yesterdayStr) {
    return 'Yesterday';
  } else {
    // Parse at midnight local time to prevent off-by-one timezone shifts
    const [year, month, day] = dateStr.split('-').map(Number);
    const d = new Date(year, month - 1, day);
    return d.toLocaleDateString(undefined, { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });
  }
}

// ── 3. API Communication Helpers ─────────────────────────────

/**
 * Resolves the full URL based on the configured server URL.
 */
function getApiUrl(path) {
  const base = state.serverUrl ? state.serverUrl.replace(/\/+$/, '') : window.location.origin;
  return `${base}${path}`;
}

/**
 * Wraps fetch to handle authorization headers and JSON serialization.
 */
async function apiFetch(path, options = {}) {
  const url = getApiUrl(path);
  const headers = {
    ...options.headers,
  };
  
  if (state.token) {
    headers['Authorization'] = `Bearer ${state.token}`;
  }
  
  if (options.body && typeof options.body === 'object' && !(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(options.body);
  }
  
  return fetch(url, { ...options, headers });
}

/**
 * Checks server health and verifies Access Token authentication.
 */
async function checkConnection() {
  const dotEl = document.getElementById('conn-dot');
  const labelEl = document.getElementById('conn-label');
  if (!dotEl || !labelEl) return;
  
  try {
    const resHealth = await apiFetch('/health');
    if (!resHealth.ok) {
      throw new Error('Health check failed');
    }
    
    if (state.token) {
      const resAuth = await apiFetch('/events/?limit=1');
      if (resAuth.status === 401) {
        dotEl.className = 'conn-dot err';
        labelEl.textContent = 'Auth Error';
        state.isConnected = false;
        return;
      }
    } else {
      dotEl.className = 'conn-dot err';
      labelEl.textContent = 'No Token';
      state.isConnected = false;
      return;
    }
    
    dotEl.className = 'conn-dot ok';
    labelEl.textContent = 'Connected';
    state.isConnected = true;
  } catch (err) {
    dotEl.className = 'conn-dot err';
    labelEl.textContent = 'Offline';
    state.isConnected = false;
  }
}

// ── 4. Rendering Engine ──────────────────────────────────────

/**
 * Generates an event card element with the corresponding structure.
 */
function renderEventCard(event) {
  const card = document.createElement('article');
  card.className = 'event-card';
  card.setAttribute('data-id', event.id);
  
  // Icon emoji selection
  let badgeIcon = '•';
  if (event.ev_type === 'note') badgeIcon = '📝';
  else if (event.ev_type === 'shell-cmd') badgeIcon = '$';
  else if (event.ev_type === 'web-visit') badgeIcon = '🌐';
  else if (event.ev_type === 'kindle-highlight') badgeIcon = '“';
  else if (event.ev_type === 'kindle-book') badgeIcon = '📖';
  else if (event.ev_type === 'photo') badgeIcon = '📷';
  
  const badgeClass = `ev-badge ev-badge-${event.ev_type}`;
  
  // Time formatting (local 24h)
  const time = new Date(event.timestamp);
  const formattedTime = time.toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false
  });
  
  // Host and App info
  const sourceText = `${escapeHtml(event.source_host || 'local')} / ${escapeHtml(event.source_app || 'unknown')}`;
  
  // Build content area depending on type
  let contentHtml = '';
  const c = event.content || {};
  
  if (event.ev_type === 'shell-cmd') {
    contentHtml = `
      <code>${escapeHtml(c.cmd || '')}</code>
      ${c.cwd ? `<div class="ev-book-meta">in <code>${escapeHtml(c.cwd)}</code></div>` : ''}
    `;
  } else if (event.ev_type === 'web-visit') {
    const title = c.title ? escapeHtml(c.title) : 'Web Visit';
    const url = c.url ? escapeHtml(c.url) : '#';
    contentHtml = `
      <div class="ev-title">
        <a href="${url}" target="_blank" rel="noopener noreferrer" style="color: var(--text-1); font-weight: 500; text-decoration: underline; text-underline-offset: 3px;">${title}</a>
      </div>
      <a href="${url}" target="_blank" rel="noopener noreferrer" class="ev-url">${url}</a>
    `;
  } else if (event.ev_type === 'kindle-highlight') {
    contentHtml = `
      <div class="ev-quote">“${escapeHtml(c.highlight || '')}”</div>
      <div class="ev-book-meta">
        — <strong>${escapeHtml(c.book_title || 'Unknown Book')}</strong> by ${escapeHtml(c.author || 'Unknown')}
        ${c.location ? `· Location ${c.location}` : ''}
      </div>
    `;
  } else if (event.ev_type === 'kindle-book') {
    contentHtml = `
      <div class="ev-title">Started or read book: <strong>${escapeHtml(c.book_title || 'Unknown Book')}</strong></div>
      <div class="ev-book-meta">
        by ${escapeHtml(c.author || 'Unknown')}
        ${c.asin ? `· ASIN: ${escapeHtml(c.asin)}` : ''}
        ${c.last_read ? `· Last read: ${new Date(c.last_read).toLocaleDateString()}` : ''}
      </div>
    `;
  } else if (event.ev_type === 'note') {
    const formattedText = escapeHtml(c.text || '').replace(/\n/g, '<br>');
    contentHtml = `
      <div style="white-space: pre-wrap;">${formattedText}</div>
      ${c.mood ? `<div class="ev-book-meta">Mood: <strong>${escapeHtml(c.mood)}</strong></div>` : ''}
    `;
  } else if (event.ev_type === 'photo') {
    contentHtml = `
      <div class="ev-title">${escapeHtml(c.caption || 'Photo Upload')}</div>
      <div class="ev-book-meta">Path: <code>${escapeHtml(c.path || '')}</code></div>
    `;
  } else {
    // General fallback
    const summary = event.summary ? escapeHtml(event.summary) : `Event of type ${event.ev_type}`;
    contentHtml = `
      <div>${summary}</div>
      <pre style="font-size: 11px; color: var(--text-3); margin-top: 5px; max-height: 150px; overflow: auto; background: rgba(0,0,0,0.2); padding: 5px; border-radius: 4px;">${escapeHtml(JSON.stringify(c, null, 2))}</pre>
    `;
  }
  
  // Render tags
  let tagsHtml = '';
  if (event.tags && event.tags.length > 0) {
    const pills = event.tags.map(t => `<span class="tag-pill">${escapeHtml(t)}</span>`).join('');
    tagsHtml = `<div class="event-tags">${pills}</div>`;
  } else {
    tagsHtml = `<div class="event-tags"><span class="tag-pill-placeholder" style="font-size: 10.5px; opacity: 0.3; cursor: pointer;">+ add tags</span></div>`;
  }
  
  card.innerHTML = `
    <div class="${badgeClass}">${badgeIcon}</div>
    <div class="card-body" style="width: 100%;">
      <div class="event-meta" style="display: flex; align-items: center; width: 100%;">
        <span class="event-time">${formattedTime}</span>
        <span class="event-source">${sourceText}</span>
        
        <button class="card-edit-btn" aria-label="Edit tags" style="margin-left: auto; opacity: 0; background: none; border: none; color: var(--text-3); padding: 4px; cursor: pointer; display: flex; align-items: center; justify-content: center; border-radius: 4px; transition: opacity var(--dur-fast), color var(--dur-fast);">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 20h9"/>
            <path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/>
          </svg>
        </button>
        <button class="card-delete-btn" aria-label="Delete event" style="opacity: 0; background: none; border: none; color: var(--danger); padding: 4px; cursor: pointer; display: flex; align-items: center; justify-content: center; border-radius: 4px; transition: opacity var(--dur-fast);">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 6h18"/>
            <path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/>
            <path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>
          </svg>
        </button>
      </div>
      <div class="event-content" style="margin-top: 4px;">
        ${contentHtml}
      </div>
      ${tagsHtml}
    </div>
  `;
  
  // Hover effect to reveal buttons smoothly
  card.addEventListener('mouseenter', () => {
    const editBtn = card.querySelector('.card-edit-btn');
    const deleteBtn = card.querySelector('.card-delete-btn');
    if (editBtn) editBtn.style.opacity = '0.7';
    if (deleteBtn) deleteBtn.style.opacity = '0.7';
  });
  
  card.addEventListener('mouseleave', () => {
    const editBtn = card.querySelector('.card-edit-btn');
    const deleteBtn = card.querySelector('.card-delete-btn');
    if (editBtn) editBtn.style.opacity = '0';
    if (deleteBtn) deleteBtn.style.opacity = '0';
  });
  
  return card;
}

/**
 * Groups events by day and renders them inside the list container.
 */
function renderEventList(events, container) {
  container.innerHTML = '';
  
  const groups = {};
  for (const event of events) {
    const date = new Date(event.timestamp);
    const y = date.getFullYear();
    const m = String(date.getMonth() + 1).padStart(2, '0');
    const d = String(date.getDate()).padStart(2, '0');
    const dayKey = `${y}-${m}-${d}`;
    
    if (!groups[dayKey]) {
      groups[dayKey] = [];
    }
    groups[dayKey].push(event);
  }
  
  const sortedDayKeys = Object.keys(groups).sort((a, b) => b.localeCompare(a));
  
  for (const dayKey of sortedDayKeys) {
    const dayEvents = groups[dayKey];
    
    const dayGroupEl = document.createElement('section');
    dayGroupEl.className = 'day-group';
    
    const dayHeaderEl = document.createElement('header');
    dayHeaderEl.className = 'day-header';
    
    const dayLabel = formatDayLabel(dayKey);
    const countText = dayEvents.length === 1 ? '1 event' : `${dayEvents.length} events`;
    
    dayHeaderEl.innerHTML = `
      <span class="day-label">${dayLabel}</span>
      <span class="day-count">${countText}</span>
    `;
    
    dayGroupEl.appendChild(dayHeaderEl);
    
    for (const event of dayEvents) {
      const cardEl = renderEventCard(event);
      dayGroupEl.appendChild(cardEl);
    }
    
    container.appendChild(dayGroupEl);
  }
}

// ── 5. View Managers ─────────────────────────────────────────

/**
 * Initialise and load the Timeline View.
 */
function renderTimelineView(container) {
  container.innerHTML = `
    <header class="view-header">
      <h1>Timeline</h1>
      <div class="view-meta" id="timeline-meta">Loading events…</div>
    </header>
    <div id="timeline-alerts"></div>
    <div id="timeline-events-list"></div>
    <button class="load-more-btn" id="timeline-load-more" style="display: none;">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="m6 9 6 6 6-6"/>
      </svg>
      <span>Load More</span>
    </button>
  `;
  
  state.timelineEvents = [];
  state.timelineOffset = 0;
  
  loadTimelineEvents();
}

/**
 * Fetch and append timeline events from the server.
 */
async function loadTimelineEvents() {
  const alertsEl = document.getElementById('timeline-alerts');
  const listEl = document.getElementById('timeline-events-list');
  const loadMoreBtn = document.getElementById('timeline-load-more');
  const metaEl = document.getElementById('timeline-meta');
  
  if (!state.token) {
    if (alertsEl) {
      alertsEl.innerHTML = `
        <div class="alert alert-warn">
          Please configure your Access Token in <a href="#settings">Settings</a> to load the timeline.
        </div>
      `;
    }
    if (metaEl) metaEl.textContent = 'Configuration required';
    return;
  }
  
  const isFirstPage = state.timelineOffset === 0;
  if (isFirstPage) {
    listEl.innerHTML = `
      <div class="spinner-wrap">
        <div class="spinner"></div>
      </div>
    `;
  } else if (loadMoreBtn) {
    loadMoreBtn.disabled = true;
    loadMoreBtn.querySelector('span').textContent = 'Loading…';
  }
  
  try {
    const response = await apiFetch(`/events/?limit=${state.timelineLimit}&offset=${state.timelineOffset}`);
    if (response.status === 401) {
      throw new Error('Unauthorized');
    }
    if (!response.ok) {
      throw new Error(`Server returned HTTP ${response.status}`);
    }
    
    const data = await response.json();
    state.timelineTotal = data.total;
    state.timelineEvents = state.timelineEvents.concat(data.items);
    
    if (isFirstPage && state.timelineEvents.length === 0) {
      listEl.innerHTML = `
        <div class="empty-state">
          <div class="empty-icon">📂</div>
          <h2 class="empty-title">No events found</h2>
          <p class="empty-desc">Your timeline is empty. Use sensors or the CLI logger to send events to this server.</p>
        </div>
      `;
      if (loadMoreBtn) loadMoreBtn.style.display = 'none';
      if (metaEl) metaEl.textContent = '0 events';
      return;
    }
    
    if (isFirstPage) {
      listEl.innerHTML = '';
    }
    
    renderEventList(state.timelineEvents, listEl);
    
    if (metaEl) {
      metaEl.textContent = `Showing ${state.timelineEvents.length} of ${state.timelineTotal} events`;
    }
    
    if (loadMoreBtn) {
      if (state.timelineEvents.length < state.timelineTotal) {
        loadMoreBtn.style.display = 'flex';
        loadMoreBtn.disabled = false;
        loadMoreBtn.querySelector('span').textContent = 'Load More';
      } else {
        loadMoreBtn.style.display = 'none';
      }
    }
    
    attachEventCardListeners(listEl);
    
  } catch (err) {
    console.error('Failed to load timeline events', err);
    if (isFirstPage) {
      listEl.innerHTML = '';
    }
    if (alertsEl) {
      if (err.message === 'Unauthorized') {
        alertsEl.innerHTML = `
          <div class="alert alert-err">
            Invalid access token. Please update it in <a href="#settings">Settings</a>.
          </div>
        `;
      } else {
        alertsEl.innerHTML = `
          <div class="alert alert-err">
            Failed to connect to the server: ${escapeHtml(err.message)}. Check your settings or server status.
          </div>
        `;
      }
    }
    if (metaEl) metaEl.textContent = 'Error loading events';
    if (loadMoreBtn) loadMoreBtn.style.display = 'none';
  }
}

/**
 * Initialise and load the Search View.
 */
function renderSearchView(container) {
  // Checkboxes are dynamically checked based on state
  const isChecked = (type) => state.searchTypes.includes(type) ? 'checked' : '';
  const isActive = (type) => state.searchTypes.includes(type) ? 'chip-active' : '';
  
  container.innerHTML = `
    <header class="view-header">
      <h1>Search</h1>
      <div class="view-meta">Query and filter your life events</div>
    </header>
    
    <div class="search-bar">
      <svg class="search-bar-icon" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
        <circle cx="8" cy="8" r="5"/>
        <path d="M13 13l2.5 2.5" stroke-linecap="round"/>
      </svg>
      <input type="search" class="search-input" id="search-q" placeholder="Search events..." value="${escapeHtml(state.searchQuery)}">
    </div>
    
    <div class="filter-bar">
      <span class="filter-lbl">Types</span>
      <label class="filter-chip ${isActive('note')}">
        <input type="checkbox" value="note" class="filter-type-checkbox" ${isChecked('note')}> Note
      </label>
      <label class="filter-chip ${isActive('shell-cmd')}">
        <input type="checkbox" value="shell-cmd" class="filter-type-checkbox" ${isChecked('shell-cmd')}> Shell
      </label>
      <label class="filter-chip ${isActive('web-visit')}">
        <input type="checkbox" value="web-visit" class="filter-type-checkbox" ${isChecked('web-visit')}> Web
      </label>
      <label class="filter-chip ${isActive('kindle-highlight')}">
        <input type="checkbox" value="kindle-highlight" class="filter-type-checkbox" ${isChecked('kindle-highlight')}> Highlight
      </label>
      <label class="filter-chip ${isActive('kindle-book')}">
        <input type="checkbox" value="kindle-book" class="filter-type-checkbox" ${isChecked('kindle-book')}> Book
      </label>
      <label class="filter-chip ${isActive('photo')}">
        <input type="checkbox" value="photo" class="filter-type-checkbox" ${isChecked('photo')}> Photo
      </label>
      
      <div class="filter-sep"></div>
      
      <span class="filter-lbl">From</span>
      <input type="date" class="date-input" id="search-from-date" value="${escapeHtml(state.searchFrom)}">
      
      <span class="filter-lbl">To</span>
      <input type="date" class="date-input" id="search-to-date" value="${escapeHtml(state.searchTo)}">
    </div>
    
    <div class="result-meta" id="search-result-meta" style="display: none;"></div>
    <div id="search-results-list"></div>
    <button class="load-more-btn" id="search-load-more" style="display: none;">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="m6 9 6 6 6-6"/>
      </svg>
      <span>Load More</span>
    </button>
  `;
  
  // Event listeners
  const qInput = document.getElementById('search-q');
  const fromInput = document.getElementById('search-from-date');
  const toInput = document.getElementById('search-to-date');
  
  let searchDebounceTimeout = null;
  qInput.addEventListener('input', () => {
    clearTimeout(searchDebounceTimeout);
    searchDebounceTimeout = setTimeout(() => {
      state.searchQuery = qInput.value.trim();
      state.searchOffset = 0;
      state.searchResults = [];
      executeSearch();
    }, 250);
  });
  
  container.querySelectorAll('.filter-type-checkbox').forEach(cb => {
    cb.addEventListener('change', (e) => {
      const chip = e.target.closest('.filter-chip');
      if (e.target.checked) {
        chip.classList.add('chip-active');
      } else {
        chip.classList.remove('chip-active');
      }
      
      state.searchTypes = Array.from(container.querySelectorAll('.filter-type-checkbox:checked'))
        .map(el => el.value);
        
      state.searchOffset = 0;
      state.searchResults = [];
      executeSearch();
    });
  });
  
  const handleDateChange = () => {
    state.searchFrom = fromInput.value;
    state.searchTo = toInput.value;
    state.searchOffset = 0;
    state.searchResults = [];
    executeSearch();
  };
  
  fromInput.addEventListener('change', handleDateChange);
  toInput.addEventListener('change', handleDateChange);
  
  // Trigger initial search if inputs are pre-populated
  executeSearch();
}

/**
 * Execute the backend search query with current filters.
 */
async function executeSearch() {
  const listEl = document.getElementById('search-results-list');
  const metaEl = document.getElementById('search-result-meta');
  const loadMoreBtn = document.getElementById('search-load-more');
  
  if (!listEl) return;
  
  const isFirstPage = state.searchOffset === 0;
  
  if (!state.token) {
    listEl.innerHTML = `
      <div class="alert alert-warn">
        Please configure your Access Token in <a href="#settings">Settings</a> to search.
      </div>
    `;
    if (metaEl) metaEl.style.display = 'none';
    if (loadMoreBtn) loadMoreBtn.style.display = 'none';
    return;
  }
  
  if (isFirstPage) {
    listEl.innerHTML = `
      <div class="spinner-wrap">
        <div class="spinner"></div>
      </div>
    `;
  } else if (loadMoreBtn) {
    loadMoreBtn.disabled = true;
    loadMoreBtn.querySelector('span').textContent = 'Searching…';
  }
  
  try {
    const params = new URLSearchParams();
    params.append('limit', state.searchLimit);
    params.append('offset', state.searchOffset);
    
    if (state.searchQuery) {
      params.append('q', state.searchQuery);
    }
    
    if (state.searchTypes && state.searchTypes.length > 0) {
      for (const t of state.searchTypes) {
        params.append('ev_type', t);
      }
    }
    
    const fromIso = getFromIsoString(state.searchFrom);
    if (fromIso) {
      params.append('from', fromIso);
    }
    
    const toIso = getToIsoString(state.searchTo);
    if (toIso) {
      params.append('to', toIso);
    }
    
    const response = await apiFetch(`/events/?${params.toString()}`);
    if (response.status === 401) {
      throw new Error('Unauthorized');
    }
    if (!response.ok) {
      throw new Error(`Server returned HTTP ${response.status}`);
    }
    
    const data = await response.json();
    state.searchTotal = data.total;
    state.searchResults = state.searchResults.concat(data.items);
    
    if (isFirstPage && state.searchResults.length === 0) {
      listEl.innerHTML = `
        <div class="empty-state">
          <div class="empty-icon">🔍</div>
          <h2 class="empty-title">No events match search</h2>
          <p class="empty-desc">Try widening your search terms, modifying your filters, or resetting dates.</p>
        </div>
      `;
      if (metaEl) {
        metaEl.style.display = 'block';
        metaEl.textContent = 'Found 0 events';
      }
      if (loadMoreBtn) loadMoreBtn.style.display = 'none';
      return;
    }
    
    if (isFirstPage) {
      listEl.innerHTML = '';
    }
    
    renderEventList(state.searchResults, listEl);
    
    if (metaEl) {
      metaEl.style.display = 'block';
      metaEl.textContent = `Found ${state.searchTotal} events (showing ${state.searchResults.length})`;
    }
    
    if (loadMoreBtn) {
      if (state.searchResults.length < state.searchTotal) {
        loadMoreBtn.style.display = 'flex';
        loadMoreBtn.disabled = false;
        loadMoreBtn.querySelector('span').textContent = 'Load More';
      } else {
        loadMoreBtn.style.display = 'none';
      }
    }
    
    attachEventCardListeners(listEl);
    
  } catch (err) {
    console.error('Failed to execute search', err);
    if (isFirstPage) {
      listEl.innerHTML = '';
    }
    if (metaEl) metaEl.style.display = 'none';
    if (loadMoreBtn) loadMoreBtn.style.display = 'none';
    
    listEl.innerHTML = `
      <div class="alert alert-err">
        Search failed: ${err.message === 'Unauthorized' ? 'Invalid Access Token' : escapeHtml(err.message)}.
      </div>
    `;
  }
}

/**
 * Initialise and load the Settings View.
 */
function renderSettingsView(container) {
  const urlVal = state.serverUrl;
  const tokenVal = state.token;
  
  container.innerHTML = `
    <header class="view-header">
      <h1>Settings</h1>
      <div class="view-meta">Configure connection to the Biograph server</div>
    </header>
    
    <div class="settings-card">
      <h2>Server Connection</h2>
      <form id="settings-form">
        <div class="field">
          <label class="field-label" for="setting-url">Server URL</label>
          <input class="field-input" type="url" id="setting-url" placeholder="http://127.0.0.1:8000" value="${escapeHtml(urlVal)}">
          <div class="field-hint">The base URL of your Biograph backend server. Leave blank to use the current host (default for self-hosted setup).</div>
        </div>
        
        <div class="field">
          <label class="field-label" for="setting-token">Access Token</label>
          <input class="field-input" type="password" id="setting-token" placeholder="Enter your bearer token" value="${escapeHtml(tokenVal)}">
          <div class="field-hint">The static bearer token configured in your server's <code>config.toml</code>. Required for authentication.</div>
        </div>
        
        <div class="actions-row">
          <button type="submit" class="btn btn-primary" id="save-settings-btn">Save Settings</button>
          <button type="button" class="btn btn-secondary" id="test-connection-btn">Test Connection</button>
          <span class="status-badge" id="test-status" style="display: none;"></span>
        </div>
      </form>
    </div>
  `;
  
  const form = document.getElementById('settings-form');
  const testBtn = document.getElementById('test-connection-btn');
  const statusBadge = document.getElementById('test-status');
  
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    const newUrl = document.getElementById('setting-url').value.trim();
    const newToken = document.getElementById('setting-token').value.trim();
    
    state.serverUrl = newUrl;
    state.token = newToken;
    
    localStorage.setItem('biograph_server_url', newUrl);
    localStorage.setItem('biograph_token', newToken);
    
    checkConnection();
    
    const saveBtn = document.getElementById('save-settings-btn');
    const originalText = saveBtn.textContent;
    saveBtn.textContent = 'Saved!';
    saveBtn.disabled = true;
    setTimeout(() => {
      saveBtn.textContent = originalText;
      saveBtn.disabled = false;
    }, 1500);
  });
  
  testBtn.addEventListener('click', async () => {
    const testUrl = document.getElementById('setting-url').value.trim();
    const testToken = document.getElementById('setting-token').value.trim();
    
    testBtn.disabled = true;
    statusBadge.style.display = 'inline-flex';
    statusBadge.className = 'status-badge';
    statusBadge.textContent = 'Testing…';
    
    try {
      const base = testUrl ? testUrl.replace(/\/+$/, '') : window.location.origin;
      // First verify health
      const resHealth = await fetch(`${base}/health`);
      if (!resHealth.ok) {
        throw new Error(`Server returned HTTP ${resHealth.status}`);
      }
      
      // Then verify token via /events?limit=1
      const headers = {};
      if (testToken) {
        headers['Authorization'] = `Bearer ${testToken}`;
      }
      const resEvents = await fetch(`${base}/events/?limit=1`, { headers });
      if (resEvents.status === 401) {
        statusBadge.className = 'status-badge err';
        statusBadge.textContent = 'Invalid Token';
        return;
      }
      if (!resEvents.ok) {
        throw new Error(`Auth failed with HTTP ${resEvents.status}`);
      }
      
      statusBadge.className = 'status-badge ok';
      statusBadge.textContent = 'Success!';
    } catch (err) {
      statusBadge.className = 'status-badge err';
      statusBadge.textContent = `Error: ${err.message}`;
    } finally {
      testBtn.disabled = false;
    }
  });
}

// ── 6. Event Card Interactions ──────────────────────────────

/**
 * Binds edit and delete buttons to their actions inside an event list container.
 */
function attachEventCardListeners(container) {
  container.querySelectorAll('.event-card').forEach(card => {
    const id = parseInt(card.getAttribute('data-id'), 10);
    
    const editBtn = card.querySelector('.card-edit-btn');
    if (editBtn) {
      editBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        editEventTags(id, card);
      });
    }
    
    // Also bind click to the placeholder "+ add tags" pill if tags are empty
    const addPlaceholder = card.querySelector('.tag-pill-placeholder');
    if (addPlaceholder) {
      addPlaceholder.addEventListener('click', (e) => {
        e.stopPropagation();
        editEventTags(id, card);
      });
      
      // Show placeholder on card hover for discoverability
      card.addEventListener('mouseenter', () => {
        addPlaceholder.style.display = 'inline-block';
      });
      card.addEventListener('mouseleave', () => {
        addPlaceholder.style.display = 'none';
      });
    }
    
    const deleteBtn = card.querySelector('.card-delete-btn');
    if (deleteBtn) {
      deleteBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        deleteEvent(id, card);
      });
    }
  });
}

/**
 * Prompts user to edit tags and updates the event via PATCH.
 */
async function editEventTags(id, card) {
  let event = state.timelineEvents.find(e => e.id === id);
  if (!event) {
    event = state.searchResults.find(e => e.id === id);
  }
  if (!event) return;
  
  const currentTags = event.tags || [];
  const newTagsStr = prompt('Edit tags (comma-separated):', currentTags.join(', '));
  if (newTagsStr === null) return;
  
  const newTags = newTagsStr.split(',')
    .map(t => t.trim())
    .filter(t => t.length > 0);
    
  try {
    const response = await apiFetch(`/events/${id}`, {
      method: 'PATCH',
      body: { tags: newTags }
    });
    
    if (!response.ok) {
      throw new Error(`Server returned HTTP ${response.status}`);
    }
    
    const updated = await response.json();
    
    // Update local state arrays
    const updateInArray = (arr) => {
      const idx = arr.findIndex(e => e.id === id);
      if (idx !== -1) arr[idx].tags = updated.tags;
    };
    updateInArray(state.timelineEvents);
    updateInArray(state.searchResults);
    
    // Smoothly morph card tags via View Transitions
    const updateCardTagsDOM = () => {
      const tagsContainer = card.querySelector('.event-tags');
      if (tagsContainer) {
        if (updated.tags.length > 0) {
          tagsContainer.innerHTML = updated.tags.map(t => `<span class="tag-pill">${escapeHtml(t)}</span>`).join('');
        } else {
          tagsContainer.innerHTML = `<span class="tag-pill-placeholder" style="font-size: 10.5px; opacity: 0.3; cursor: pointer;">+ add tags</span>`;
          // Re-bind click to new placeholder
          const placeholder = tagsContainer.querySelector('.tag-pill-placeholder');
          placeholder.addEventListener('click', (e) => {
            e.stopPropagation();
            editEventTags(id, card);
          });
        }
      }
    };
    
    if (!document.startViewTransition) {
      updateCardTagsDOM();
    } else {
      document.startViewTransition(() => updateCardTagsDOM());
    }
    
  } catch (err) {
    alert(`Failed to update tags: ${err.message}`);
  }
}

/**
 * Prompts user to confirm deletion and updates backend via DELETE.
 */
async function deleteEvent(id, card) {
  if (!confirm('Are you sure you want to delete this event? This action cannot be undone.')) {
    return;
  }
  
  try {
    const response = await apiFetch(`/events/${id}`, {
      method: 'DELETE'
    });
    
    if (!response.ok) {
      throw new Error(`Server returned HTTP ${response.status}`);
    }
    
    // Remove from state arrays
    state.timelineEvents = state.timelineEvents.filter(e => e.id !== id);
    state.searchResults = state.searchResults.filter(e => e.id !== id);
    
    // Smoothly animate the card deletion
    const removeCardDOM = () => {
      const dayGroup = card.closest('.day-group');
      card.remove();
      
      // Clean up empty day groups
      if (dayGroup && dayGroup.querySelectorAll('.event-card').length === 0) {
        dayGroup.remove();
      }
      
      // Update meta information totals
      if (state.currentView === 'timeline') {
        state.timelineTotal = Math.max(0, state.timelineTotal - 1);
        const metaEl = document.getElementById('timeline-meta');
        if (metaEl) {
          metaEl.textContent = `Showing ${state.timelineEvents.length} of ${state.timelineTotal} events`;
        }
        if (state.timelineEvents.length === 0) {
          const listEl = document.getElementById('timeline-events-list');
          if (listEl) {
            listEl.innerHTML = `
              <div class="empty-state">
                <div class="empty-icon">📂</div>
                <h2 class="empty-title">No events found</h2>
                <p class="empty-desc">Your timeline is empty. Use sensors or the CLI logger to send events to this server.</p>
              </div>
            `;
          }
        }
      } else if (state.currentView === 'search') {
        state.searchTotal = Math.max(0, state.searchTotal - 1);
        const metaEl = document.getElementById('search-result-meta');
        if (metaEl) {
          metaEl.textContent = `Found ${state.searchTotal} events (showing ${state.searchResults.length})`;
        }
        if (state.searchResults.length === 0) {
          const listEl = document.getElementById('search-results-list');
          if (listEl) {
            listEl.innerHTML = `
              <div class="empty-state">
                <div class="empty-icon">🔍</div>
                <h2 class="empty-title">No events match search</h2>
                <p class="empty-desc">Try widening your search terms, modifying your filters, or resetting dates.</p>
              </div>
            `;
          }
        }
      }
    };
    
    if (!document.startViewTransition) {
      removeCardDOM();
    } else {
      document.startViewTransition(() => removeCardDOM());
    }
    
  } catch (err) {
    alert(`Failed to delete event: ${err.message}`);
  }
}

// ── 7. SPA Navigation & Routing ──────────────────────────────

/**
 * Updates active states for links in the navigation list.
 */
function updateSidebarActiveLink(viewName) {
  document.querySelectorAll('.nav-link').forEach(link => {
    if (link.getAttribute('data-view') === viewName) {
      link.classList.add('active');
      link.setAttribute('aria-current', 'page');
    } else {
      link.classList.remove('active');
      link.removeAttribute('aria-current');
    }
  });
}

/**
 * Switches the active view in the main content container.
 */
function navigateToView(viewName) {
  if (state.currentView === viewName) return;
  
  updateSidebarActiveLink(viewName);
  
  const updateDOM = () => {
    state.currentView = viewName;
    const mainEl = document.getElementById('main');
    if (!mainEl) return;
    
    if (viewName === 'timeline') {
      renderTimelineView(mainEl);
    } else if (viewName === 'search') {
      renderSearchView(mainEl);
    } else if (viewName === 'settings') {
      renderSettingsView(mainEl);
    }
  };
  
  if (!document.startViewTransition) {
    updateDOM();
    focusViewHeader();
  } else {
    const transition = document.startViewTransition(() => updateDOM());
    transition.finished.finally(() => {
      focusViewHeader();
    });
  }
}

/**
 * Routes keyboard focus to the new page heading to preserve standard accessibility flow.
 */
function focusViewHeader() {
  const heading = document.querySelector('#main h1');
  if (heading) {
    heading.setAttribute('tabindex', '-1');
    heading.focus();
  }
}

/**
 * Inspects URL hash and triggers navigation.
 */
function handleRouting() {
  const hash = window.location.hash || '#timeline';
  
  if (hash === '#timeline') {
    navigateToView('timeline');
  } else if (hash === '#search') {
    navigateToView('search');
  } else if (hash === '#settings') {
    navigateToView('settings');
  } else {
    window.location.hash = '#timeline';
  }
}

// ── 8. Global Event Delegation ───────────────────────────────

document.addEventListener('click', (e) => {
  // Timeline Load More
  const timelineLoadMore = e.target.closest('#timeline-load-more');
  if (timelineLoadMore) {
    state.timelineOffset += state.timelineLimit;
    loadTimelineEvents();
    return;
  }
  
  // Search Load More
  const searchLoadMore = e.target.closest('#search-load-more');
  if (searchLoadMore) {
    state.searchOffset += state.searchLimit;
    executeSearch();
    return;
  }
});

// ── 9. Initialisation ────────────────────────────────────────

window.addEventListener('hashchange', handleRouting);

document.addEventListener('DOMContentLoaded', () => {
  checkConnection();
  
  // Start connection checker cycle (15s interval)
  setInterval(checkConnection, 15000);
  
  // UX: If there's no configuration token saved, guide them directly to Settings
  if (!state.token && !window.location.hash) {
    window.location.hash = '#settings';
  } else {
    handleRouting();
  }
});

/* ============================================================
   Biograph Web Client — app.js (v2)
   Single Page Application with Canvas Charts and Tag Manager
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

// Intersection observer for infinite scrolling
let timelineObserver = null;
let searchObserver = null;

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
  card.className = `event-card ev-card-${event.ev_type}`;
  card.setAttribute('data-id', event.id);
  if (event.isMergedZshGroup && event.commands) {
    const ids = event.commands.map(item => item.id).join(',');
    card.setAttribute('data-merged-ids', ids);
  } else if (event.isMergedWebGroup && event.visits) {
    const ids = event.visits.map(item => item.id).join(',');
    card.setAttribute('data-merged-ids', ids);
  }
  
  // Icon emoji selection
  let badgeIcon = '•';
  if (event.ev_type === 'note') badgeIcon = '📝';
  else if (event.ev_type === 'shell-cmd') badgeIcon = '$';
  else if (event.ev_type === 'web-visit') badgeIcon = '🌐';
  else if (event.ev_type === 'kindle-highlight' || event.ev_type === 'tolino-highlight' || event.ev_type === 'pocketbook-highlight') badgeIcon = '“';
  else if (event.ev_type === 'kindle-book' || event.ev_type === 'tolino-book' || event.ev_type === 'pocketbook-book') badgeIcon = '📖';
  else if (event.ev_type === 'kodi-movie') badgeIcon = '🎬';
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
    if (event.isMergedZshGroup) {
      const commandItems = event.commands.map(item => {
        const itemTime = new Date(item.timestamp);
        const itemFormattedTime = itemTime.toLocaleTimeString(undefined, {
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
          hour12: false
        });
        return `
          <div class="merged-command-item" style="margin-bottom: 6px; display: flex; align-items: baseline; flex-wrap: wrap;">
            <span style="font-size: 11px; color: var(--text-3); margin-right: 8px; font-family: monospace;">${itemFormattedTime}</span>
            <code style="word-break: break-all;">${escapeHtml(item.cmd || '')}</code>
            ${item.cwd ? `<span class="ev-book-meta" style="display:inline; margin-left: 8px; font-size: 11px;">in <code>${escapeHtml(item.cwd)}</code></span>` : ''}
          </div>
        `;
      }).join('');
      
      contentHtml = `
        <div class="merged-commands-list" style="border-left: 2px solid var(--border); padding-left: 10px; margin-top: 5px;">
          ${commandItems}
        </div>
      `;
    } else {
      contentHtml = `
        <code>${escapeHtml(c.cmd || '')}</code>
        ${c.cwd ? `<div class="ev-book-meta">in <code>${escapeHtml(c.cwd)}</code></div>` : ''}
      `;
    }
  } else if (event.ev_type === 'web-visit') {
    if (event.isMergedWebGroup) {
      const visitItems = event.visits.map(item => {
        const itemTime = new Date(item.timestamp);
        const itemFormattedTime = itemTime.toLocaleTimeString(undefined, {
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
          hour12: false
        });
        const url = item.url ? escapeHtml(item.url) : '#';
        const title = item.title ? escapeHtml(item.title) : 'Web Visit';
        return `
          <div class="merged-web-visit-item" style="margin-bottom: 8px;">
            <div style="display: flex; align-items: baseline; flex-wrap: wrap;">
              <span style="font-size: 11px; color: var(--text-3); margin-right: 8px; font-family: monospace; min-width: 50px;">${itemFormattedTime}</span>
              <a href="${url}" target="_blank" rel="noopener noreferrer" style="color: var(--text-1); font-weight: 500; text-decoration: underline; text-underline-offset: 3px;">${title}</a>
            </div>
            <a href="${url}" target="_blank" rel="noopener noreferrer" class="ev-url" style="display: block; margin-left: 58px; margin-top: 1px; font-size: 11px; color: var(--text-3); font-family: monospace; word-break: break-all;">${url}</a>
          </div>
        `;
      }).join('');
      
      contentHtml = `
        <div class="ev-title" style="margin-bottom: 6px;">
          Visits to <strong>${escapeHtml(event.websiteHost)}</strong>
        </div>
        <div class="merged-web-visits-list" style="border-left: 2px solid var(--border); padding-left: 10px; margin-top: 5px;">
          ${visitItems}
        </div>
      `;
    } else {
      const title = c.title ? escapeHtml(c.title) : 'Web Visit';
      const url = c.url ? escapeHtml(c.url) : '#';
      contentHtml = `
        <div class="ev-title">
          <a href="${url}" target="_blank" rel="noopener noreferrer" style="color: var(--text-1); font-weight: 500; text-decoration: underline; text-underline-offset: 3px;">${title}</a>
        </div>
        <a href="${url}" target="_blank" rel="noopener noreferrer" class="ev-url">${url}</a>
      `;
    }
  } else if (event.ev_type === 'kindle-highlight' || event.ev_type === 'tolino-highlight' || event.ev_type === 'pocketbook-highlight') {
    contentHtml = `
      <div class="ev-quote">“${escapeHtml(c.highlight || '')}”</div>
      ${c.annotation ? `<div class="ev-note" style="margin-top: 5px; font-style: italic; color: var(--text-2);">Note: ${escapeHtml(c.annotation)}</div>` : ''}
      <div class="ev-book-meta">
        — <strong>${escapeHtml(c.book_title || 'Unknown Book')}</strong> by ${escapeHtml(c.author || 'Unknown')}
        ${c.location ? `· Location ${c.location}` : ''}
      </div>
    `;
  } else if (event.ev_type === 'kindle-book' || event.ev_type === 'tolino-book' || event.ev_type === 'pocketbook-book') {
    const isFinished = c.read_status === 2 || c.percent_read === 100;
    const progressText = c.percent_read !== undefined && c.percent_read !== null ? `· Progress: ${c.percent_read}%` : '';
    const statusText = isFinished ? 'Finished book:' : 'Started or read book:';
    contentHtml = `
      <div class="ev-title">${statusText} <strong>${escapeHtml(c.book_title || 'Unknown Book')}</strong></div>
      <div class="ev-book-meta">
        by ${escapeHtml(c.author || 'Unknown')}
        ${c.asin ? `· ASIN: ${escapeHtml(c.asin)}` : ''}
        ${progressText}
        ${c.last_read ? `· Last read: ${new Date(c.last_read).toLocaleDateString()}` : ''}
      </div>
    `;
  } else if (event.ev_type === 'kodi-movie') {
    const isFinished = c.finished !== false;
    const progressText = c.progress_percent !== undefined && c.progress_percent !== null && c.progress_percent !== 100 ? `· Progress: ${c.progress_percent}%` : '';
    const statusText = isFinished ? 'Finished movie:' : 'Watched movie:';
    const yearText = c.year ? ` (${c.year})` : '';
    contentHtml = `
      <div class="ev-title">${statusText} <strong>${escapeHtml(c.title || 'Unknown Movie')}</strong>${yearText}</div>
      <div class="ev-book-meta">
        ${c.duration_seconds ? `· Duration: ${Math.round(c.duration_seconds / 60)} min` : ''}
        ${progressText}
        ${c.imdb_id ? `· IMDb: <a href="https://www.imdb.com/title/${escapeHtml(c.imdb_id)}/" target="_blank" style="color: var(--text-2); text-decoration: underline;">${escapeHtml(c.imdb_id)}</a>` : ''}
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
 * Groups consecutive events if they belong to the same category:
 * 1. consecutive zsh shell-cmd events on the same host (within 5 minutes)
 * 2. consecutive web visits to the same website host (no timeout)
 */
function preprocessEvents(events) {
  if (!events || events.length === 0) return [];
  
  const merged = [];
  let currentZshGroup = null;
  let currentWebGroup = null;
  
  function getWebsiteHost(url) {
    try {
      const u = new URL(url);
      return u.hostname.replace(/^www\./i, '');
    } catch (e) {
      return url || '';
    }
  }

  for (const event of events) {
    const isZshCmd = event.ev_type === 'shell-cmd' && event.source_app === 'zsh';
    const isWebVisit = event.ev_type === 'web-visit';
    
    // Close Zsh group if we hit any non-zsh-command
    if (!isZshCmd && currentZshGroup) {
      merged.push(currentZshGroup);
      currentZshGroup = null;
    }
    
    // Close Web group if we hit any non-web-visit
    if (!isWebVisit && currentWebGroup) {
      merged.push(currentWebGroup);
      currentWebGroup = null;
    }
    
    if (isZshCmd) {
      if (currentZshGroup) {
        const timeDiffMs = Math.abs(new Date(event.timestamp) - new Date(currentZshGroup.timestamp));
        const sameHost = event.source_host === currentZshGroup.source_host;
        
        if (sameHost && timeDiffMs <= 5 * 60 * 1000) {
          currentZshGroup.commands.push({
            cmd: event.content.cmd,
            cwd: event.content.cwd,
            timestamp: event.timestamp,
            id: event.id
          });
          if (event.tags) {
            for (const tag of event.tags) {
              if (!currentZshGroup.tags.includes(tag)) {
                currentZshGroup.tags.push(tag);
              }
            }
          }
        } else {
          merged.push(currentZshGroup);
          currentZshGroup = startNewZshGroup(event);
        }
      } else {
        currentZshGroup = startNewZshGroup(event);
      }
    } else if (isWebVisit) {
      const eventHost = getWebsiteHost(event.content.url || '');
      if (currentWebGroup) {
        const groupHost = currentWebGroup.websiteHost;
        
        if (eventHost === groupHost) {
          currentWebGroup.visits.push({
            url: event.content.url,
            title: event.content.title,
            browser: event.content.browser,
            timestamp: event.timestamp,
            id: event.id
          });
          if (event.tags) {
            for (const tag of event.tags) {
              if (!currentWebGroup.tags.includes(tag)) {
                currentWebGroup.tags.push(tag);
              }
            }
          }
        } else {
          merged.push(currentWebGroup);
          currentWebGroup = startNewWebGroup(event, eventHost);
        }
      } else {
        currentWebGroup = startNewWebGroup(event, eventHost);
      }
    } else {
      merged.push({ ...event });
    }
  }
  
  if (currentZshGroup) {
    merged.push(currentZshGroup);
  }
  if (currentWebGroup) {
    merged.push(currentWebGroup);
  }
  
  return merged;
}

function startNewZshGroup(event) {
  return {
    ...event,
    tags: [...(event.tags || [])],
    commands: [{
      cmd: event.content.cmd,
      cwd: event.content.cwd,
      timestamp: event.timestamp,
      id: event.id
    }],
    isMergedZshGroup: true
  };
}

function startNewWebGroup(event, websiteHost) {
  return {
    ...event,
    tags: [...(event.tags || [])],
    visits: [{
      url: event.content.url,
      title: event.content.title,
      browser: event.content.browser,
      timestamp: event.timestamp,
      id: event.id
    }],
    websiteHost: websiteHost,
    isMergedWebGroup: true
  };
}

/**
 * Groups events by day and renders them inside the list container.
 */
function renderEventList(events, container) {
  container.innerHTML = '';
  
  const preprocessed = preprocessEvents(events);
  
  const groups = {};
  for (const event of preprocessed) {
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
    
    let actualCount = 0;
    for (const event of dayEvents) {
      if (event.isMergedZshGroup && event.commands) {
        actualCount += event.commands.length;
      } else {
        actualCount += 1;
      }
    }
    
    const countText = actualCount === 1 ? '1 event' : `${actualCount} events`;
    
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

/**
 * Monitors list elements and sets up infinite scroll trigger.
 */
function setupInfiniteScroll(buttonId, callback) {
  const loadMoreBtn = document.getElementById(buttonId);
  if (!loadMoreBtn) return;
  
  const observer = new IntersectionObserver((entries) => {
    const entry = entries[0];
    if (entry.isIntersecting && !loadMoreBtn.disabled && loadMoreBtn.style.display !== 'none') {
      loadMoreBtn.disabled = true;
      callback();
    }
  }, {
    rootMargin: '200px'
  });
  
  observer.observe(loadMoreBtn);
  return observer;
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
        
        // Initialise virtual infinite scroll trigger
        if (isFirstPage) {
          if (timelineObserver) timelineObserver.disconnect();
          timelineObserver = setupInfiniteScroll('timeline-load-more', () => {
            state.timelineOffset += state.timelineLimit;
            loadTimelineEvents();
          });
        }
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
      <label class="filter-chip ${isActive('highlight')}">
        <input type="checkbox" value="highlight" class="filter-type-checkbox" ${isChecked('highlight')}> Highlight
      </label>
      <label class="filter-chip ${isActive('book')}">
        <input type="checkbox" value="book" class="filter-type-checkbox" ${isChecked('book')}> Book
      </label>
      <label class="filter-chip ${isActive('kodi-movie')}">
        <input type="checkbox" value="kodi-movie" class="filter-type-checkbox" ${isChecked('kodi-movie')}> Movie
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
        if (t === 'highlight') {
          params.append('ev_type', 'kindle-highlight');
          params.append('ev_type', 'tolino-highlight');
          params.append('ev_type', 'pocketbook-highlight');
        } else if (t === 'book') {
          params.append('ev_type', 'kindle-book');
          params.append('ev_type', 'tolino-book');
          params.append('ev_type', 'pocketbook-book');
        } else {
          params.append('ev_type', t);
        }
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
        
        // Initialise virtual infinite scroll trigger
        if (isFirstPage) {
          if (searchObserver) searchObserver.disconnect();
          searchObserver = setupInfiniteScroll('search-load-more', () => {
            state.searchOffset += state.searchLimit;
            executeSearch();
          });
        }
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
      const resHealth = await fetch(`${base}/health`);
      if (!resHealth.ok) {
        throw new Error(`Server returned HTTP ${resHealth.status}`);
      }
      
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

/**
 * Initialise and load the Stats Dashboard View.
 */
async function renderStatsView(container) {
  container.innerHTML = `
    <header class="view-header">
      <h1>Stats</h1>
      <div class="view-meta" id="stats-meta">Analyzing your timeline…</div>
    </header>
    <div id="stats-alerts"></div>
    
    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 20px; margin-bottom: 24px;">
      <!-- Donut Chart -->
      <div class="settings-card" style="display: flex; flex-direction: column; align-items: center;">
        <h2>Event Type Breakdown</h2>
        <canvas id="donut-canvas" width="220" height="220" style="margin: 15px 0; max-width: 100%;"></canvas>
        <div id="donut-legend" style="width: 100%; display: flex; flex-wrap: wrap; gap: 8px 12px; justify-content: center; font-size: 11.5px; margin-top: 10px;"></div>
      </div>
      
      <!-- Bar Chart -->
      <div class="settings-card" style="display: flex; flex-direction: column;">
        <h2>Daily Activity (Last 14 Days)</h2>
        <canvas id="bar-canvas" width="300" height="220" style="margin: 15px 0; max-width: 100%;"></canvas>
      </div>
    </div>
    
    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 20px;">
      <!-- Top Commands -->
      <div class="settings-card" id="top-commands-card" style="display: none;">
        <h2>Top Shell Commands</h2>
        <div id="top-commands-list" style="display: flex; flex-direction: column; gap: 12px; margin-top: 15px;"></div>
      </div>
      
      <!-- Top Websites -->
      <div class="settings-card" id="top-websites-card" style="display: none;">
        <h2>Top Visited Websites</h2>
        <div id="top-websites-list" style="display: flex; flex-direction: column; gap: 12px; margin-top: 15px;"></div>
      </div>
    </div>
  `;
  
  const alertsEl = document.getElementById('stats-alerts');
  const metaEl = document.getElementById('stats-meta');
  
  if (!state.token) {
    if (alertsEl) {
      alertsEl.innerHTML = `
        <div class="alert alert-warn">
          Please configure your Access Token in <a href="#settings">Settings</a> to load stats.
        </div>
      `;
    }
    if (metaEl) metaEl.textContent = 'Configuration required';
    return;
  }
  
  try {
    // 1. Fetch aggregate metrics
    const statsResponse = await apiFetch('/stats/');
    if (!statsResponse.ok) throw new Error(`Stats endpoint failed: HTTP ${statsResponse.status}`);
    const statsData = await statsResponse.json();
    
    // 2. Fetch recent events for detailed analysis
    const eventsResponse = await apiFetch('/events/?limit=1000');
    if (!eventsResponse.ok) throw new Error(`Events fetch failed: HTTP ${eventsResponse.status}`);
    const eventsData = await eventsResponse.json();
    const events = eventsData.items;
    
    if (metaEl) {
      metaEl.textContent = `Analyzing ${statsData.total_events} total events (including detail review of recent ${events.length})`;
    }
    
    // Render Donut Chart
    const donutCanvas = document.getElementById('donut-canvas');
    if (donutCanvas) {
      drawDonutChart(donutCanvas, statsData.by_type);
      
      const legendEl = document.getElementById('donut-legend');
      if (legendEl) {
        const typeColors = {
          'note': '#60a5fa',
          'shell-cmd': '#4ade80',
          'web-visit': '#fb923c',
          'kindle-highlight': '#fbbf24',
          'kindle-book': '#c084fc',
          'tolino-highlight': '#f59e0b',
          'tolino-book': '#a855f7',
          'pocketbook-highlight': '#ec4899',
          'pocketbook-book': '#f43f5e',
          'kodi-movie': '#06b6d4',
          'photo': '#f472b6',
          'default': '#8a9ab5'
        };
        legendEl.innerHTML = statsData.by_type.map(item => {
          const color = typeColors[item.ev_type] || typeColors.default;
          return `
            <div style="display: flex; align-items: center; gap: 5px;">
              <div style="width: 10px; height: 10px; border-radius: 2px; background: ${color};"></div>
              <span style="text-transform: capitalize;">${escapeHtml(item.ev_type)} (${item.count})</span>
            </div>
          `;
        }).join('');
      }
    }
    
    // Render Bar Chart (Daily activity for last 14 days)
    const barCanvas = document.getElementById('bar-canvas');
    if (barCanvas) {
      const dailyCounts = {};
      const now = new Date();
      for (let i = 13; i >= 0; i--) {
        const d = new Date(now);
        d.setDate(now.getDate() - i);
        const yStr = d.getFullYear();
        const mStr = String(d.getMonth() + 1).padStart(2, '0');
        const dStr = String(d.getDate()).padStart(2, '0');
        const dayKey = `${yStr}-${mStr}-${dStr}`;
        dailyCounts[dayKey] = 0;
      }
      
      events.forEach(e => {
        const date = new Date(e.timestamp);
        const y = date.getFullYear();
        const m = String(date.getMonth() + 1).padStart(2, '0');
        const day = String(date.getDate()).padStart(2, '0');
        const dayKey = `${y}-${m}-${day}`;
        if (dayKey in dailyCounts) {
          dailyCounts[dayKey]++;
        }
      });
      
      drawBarChart(barCanvas, dailyCounts);
    }
    
    // Aggregate Top Shell Commands & Websites
    const shellCommands = {};
    const webSites = {};
    events.forEach(e => {
      if (e.ev_type === 'shell-cmd' && e.content?.cmd) {
        const bin = e.content.cmd.trim().split(/\s+/)[0];
        shellCommands[bin] = (shellCommands[bin] || 0) + 1;
      } else if (e.ev_type === 'web-visit' && e.content?.url) {
        try {
          const url = new URL(e.content.url);
          const host = url.hostname.replace('www.', '');
          webSites[host] = (webSites[host] || 0) + 1;
        } catch (_) {}
      }
    });
    
    const topCommands = Object.keys(shellCommands)
      .map(k => ({ name: k, count: shellCommands[k] }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 5);
      
    const topSites = Object.keys(webSites)
      .map(k => ({ name: k, count: webSites[k] }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 5);
      
    // Render Top Commands progress bars
    const commandsCard = document.getElementById('top-commands-card');
    const commandsList = document.getElementById('top-commands-list');
    if (topCommands.length > 0 && commandsCard && commandsList) {
      commandsCard.style.display = 'block';
      const maxCount = topCommands[0].count;
      commandsList.innerHTML = topCommands.map(cmd => {
        const pct = (cmd.count / maxCount) * 100;
        return `
          <div>
            <div style="display: flex; justify-content: space-between; font-size: 12.5px; margin-bottom: 3px;">
              <code>${escapeHtml(cmd.name)}</code>
              <span>${cmd.count} runs</span>
            </div>
            <div style="height: 6px; background: var(--surface-2); border-radius: 3px; overflow: hidden; border: 1px solid var(--border);">
              <div style="width: ${pct}%; height: 100%; background: var(--success); border-radius: 3px;"></div>
            </div>
          </div>
        `;
      }).join('');
    }
    
    // Render Top Sites progress bars
    const sitesCard = document.getElementById('top-websites-card');
    const sitesList = document.getElementById('top-websites-list');
    if (topSites.length > 0 && sitesCard && sitesList) {
      sitesCard.style.display = 'block';
      const maxCount = topSites[0].count;
      sitesList.innerHTML = topSites.map(site => {
        const pct = (site.count / maxCount) * 100;
        return `
          <div>
            <div style="display: flex; justify-content: space-between; font-size: 12.5px; margin-bottom: 3px;">
              <span style="font-weight: 500;">${escapeHtml(site.name)}</span>
              <span>${site.count} visits</span>
            </div>
            <div style="height: 6px; background: var(--surface-2); border-radius: 3px; overflow: hidden; border: 1px solid var(--border);">
              <div style="width: ${pct}%; height: 100%; background: var(--ev-web-visit); border-radius: 3px;"></div>
            </div>
          </div>
        `;
      }).join('');
    }
    
  } catch (err) {
    console.error('Failed to load stats details', err);
    if (alertsEl) {
      alertsEl.innerHTML = `
        <div class="alert alert-err">
          Failed to load stats details: ${escapeHtml(err.message)}
        </div>
      `;
    }
  }
}

/**
 * Draws a donut chart onto a target canvas using custom coordinates.
 */
function drawDonutChart(canvas, data) {
  const ctx = canvas.getContext('2d');
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);
  
  const total = data.reduce((sum, item) => sum + item.count, 0);
  if (total === 0) {
    ctx.fillStyle = '#8a9ab5';
    ctx.font = '13px Inter, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('No data available', width / 2, height / 2);
    return;
  }
  
  const typeColors = {
    'note': '#60a5fa',
    'shell-cmd': '#4ade80',
    'web-visit': '#fb923c',
    'kindle-highlight': '#fbbf24',
    'kindle-book': '#c084fc',
    'tolino-highlight': '#f59e0b',
    'tolino-book': '#a855f7',
    'pocketbook-highlight': '#ec4899',
    'pocketbook-book': '#f43f5e',
    'kodi-movie': '#06b6d4',
    'photo': '#f472b6',
    'default': '#8a9ab5'
  };
  
  const centerX = width / 2;
  const centerY = height / 2;
  const outerRadius = Math.min(width, height) * 0.45;
  const innerRadius = outerRadius * 0.6;
  
  let startAngle = -Math.PI / 2;
  
  data.forEach(item => {
    const sliceAngle = (item.count / total) * 2 * Math.PI;
    const color = typeColors[item.ev_type] || typeColors.default;
    
    ctx.beginPath();
    ctx.arc(centerX, centerY, outerRadius, startAngle, startAngle + sliceAngle);
    ctx.arc(centerX, centerY, innerRadius, startAngle + sliceAngle, startAngle, true);
    ctx.closePath();
    
    ctx.fillStyle = color;
    ctx.fill();
    
    startAngle += sliceAngle;
  });
  
  // Cut out center to create the donut shape matching --surface-1
  ctx.beginPath();
  ctx.arc(centerX, centerY, innerRadius, 0, 2 * Math.PI);
  ctx.fillStyle = '#0d1117';
  ctx.fill();
}

/**
 * Draws a bar chart onto a target canvas with gradients and axis lines.
 */
function drawBarChart(canvas, dailyCounts) {
  const ctx = canvas.getContext('2d');
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);
  
  const days = Object.keys(dailyCounts).sort();
  if (days.length === 0) {
    ctx.fillStyle = '#8a9ab5';
    ctx.font = '13px Inter, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('No historical data', width / 2, height / 2);
    return;
  }
  
  const paddingLeft = 32;
  const paddingRight = 12;
  const paddingTop = 12;
  const paddingBottom = 26;
  
  const graphWidth = width - paddingLeft - paddingRight;
  const graphHeight = height - paddingTop - paddingBottom;
  
  const counts = days.map(d => dailyCounts[d]);
  const maxCount = Math.max(...counts, 4);
  
  ctx.strokeStyle = 'rgba(96, 128, 200, 0.08)';
  ctx.lineWidth = 1;
  
  const numGridLines = 4;
  for (let i = 0; i <= numGridLines; i++) {
    const y = paddingTop + (graphHeight * i / numGridLines);
    ctx.beginPath();
    ctx.moveTo(paddingLeft, y);
    ctx.lineTo(width - paddingRight, y);
    ctx.stroke();
    
    const val = Math.round(maxCount * (numGridLines - i) / numGridLines);
    ctx.fillStyle = '#445168';
    ctx.font = '10px monospace';
    ctx.textAlign = 'right';
    ctx.fillText(String(val), paddingLeft - 6, y + 3);
  }
  
  const barWidth = (graphWidth / days.length) * 0.55;
  const barSpacing = (graphWidth / days.length) * 0.45;
  
  days.forEach((day, idx) => {
    const count = dailyCounts[day];
    const barHeight = (count / maxCount) * graphHeight;
    const x = paddingLeft + (idx * (barWidth + barSpacing)) + (barSpacing / 2);
    const y = height - paddingBottom - barHeight;
    
    if (barHeight > 0) {
      const grad = ctx.createLinearGradient(x, y, x, y + barHeight);
      grad.addColorStop(0, '#7c6ef5');
      grad.addColorStop(1, 'rgba(124, 110, 245, 0.2)');
      
      ctx.fillStyle = grad;
      ctx.beginPath();
      const radius = Math.min(3, barHeight);
      ctx.roundRect(x, y, barWidth, barHeight, [radius, radius, 0, 0]);
      ctx.fill();
    }
    
    const d = new Date(day + 'T00:00:00');
    const label = d.getDate();
    
    ctx.fillStyle = '#8a9ab5';
    ctx.font = '10px Inter, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(String(label), x + (barWidth / 2), height - paddingBottom + 16);
  });
}

/**
 * Initialise and load the Tag Manager View.
 */
async function loadTagsView(container) {
  container.innerHTML = `
    <header class="view-header">
      <h1>Tags</h1>
      <div class="view-meta" id="tags-meta">Scanning events…</div>
    </header>
    <div id="tags-alerts"></div>
    <div id="tags-list"></div>
  `;
  
  const alertsEl = document.getElementById('tags-alerts');
  const listEl = document.getElementById('tags-list');
  const metaEl = document.getElementById('tags-meta');
  
  if (!state.token) {
    if (alertsEl) {
      alertsEl.innerHTML = `
        <div class="alert alert-warn">
          Please configure your Access Token in <a href="#settings">Settings</a> to scan tags.
        </div>
      `;
    }
    if (metaEl) metaEl.textContent = 'Configuration required';
    return;
  }
  
  listEl.innerHTML = `
    <div class="spinner-wrap">
      <div class="spinner"></div>
    </div>
  `;
  
  try {
    const response = await apiFetch('/events/?limit=1000');
    if (!response.ok) {
      throw new Error(`Server returned HTTP ${response.status}`);
    }
    
    const data = await response.json();
    const events = data.items;
    
    const tagsCount = {};
    events.forEach(e => {
      if (e.tags) {
        e.tags.forEach(t => {
          tagsCount[t] = (tagsCount[t] || 0) + 1;
        });
      }
    });
    
    const sortedTags = Object.keys(tagsCount).sort((a, b) => b.localeCompare(a));
    
    if (sortedTags.length === 0) {
      listEl.innerHTML = `
        <div class="empty-state">
          <div class="empty-icon">🏷️</div>
          <h2 class="empty-title">No tags found</h2>
          <p class="empty-desc">Your logged events do not contain any tags. Add tags in the timeline to see them here.</p>
        </div>
      `;
      if (metaEl) metaEl.textContent = '0 tags';
      return;
    }
    
    if (metaEl) {
      metaEl.textContent = `Showing ${sortedTags.length} unique tags scanned from recent events`;
    }
    
    listEl.innerHTML = '';
    
    sortedTags.forEach(tag => {
      const count = tagsCount[tag];
      const card = document.createElement('div');
      card.className = 'settings-card';
      card.style.marginBottom = '10px';
      card.style.padding = '14px 20px';
      
      card.innerHTML = `
        <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
          <div>
            <strong style="font-size: 14px; color: var(--primary);">#${escapeHtml(tag)}</strong>
            <span style="font-size: 11.5px; color: var(--text-3); margin-left: 6px;">(${count} events)</span>
          </div>
          <div style="display: flex; gap: 8px;">
            <button class="btn btn-secondary rename-tag-btn" data-tag="${escapeHtml(tag)}" style="padding: 5px 12px; font-size: 12px;">Rename</button>
            <button class="btn btn-secondary delete-tag-btn" data-tag="${escapeHtml(tag)}" style="padding: 5px 12px; font-size: 12px; color: var(--danger);">Delete</button>
          </div>
        </div>
      `;
      
      card.querySelector('.rename-tag-btn').addEventListener('click', () => {
        renameTag(tag, sortedTags);
      });
      
      card.querySelector('.delete-tag-btn').addEventListener('click', () => {
        deleteTag(tag);
      });
      
      listEl.appendChild(card);
    });
    
  } catch (err) {
    console.error('Failed to load tag database', err);
    listEl.innerHTML = `
      <div class="alert alert-err">
        Failed to load tag database: ${escapeHtml(err.message)}
      </div>
    `;
  }
}

/**
 * Prompts to rename a tag, handling merges if the target tag already exists.
 */
async function renameTag(oldName, existingTags) {
  const newName = prompt(`Rename tag '#${oldName}' to:`, oldName);
  if (newName === null) return;
  const cleanedNewName = newName.trim();
  if (!cleanedNewName || cleanedNewName === oldName) return;
  
  if (existingTags.includes(cleanedNewName)) {
    if (!confirm(`Tag '#${cleanedNewName}' already exists. Do you want to merge '#${oldName}' into '#${cleanedNewName}'? This will update all associated events.`)) {
      return;
    }
  }
  
  const listEl = document.getElementById('tags-list');
  listEl.innerHTML = `
    <div class="spinner-wrap" style="flex-direction: column; gap: 10px;">
      <div class="spinner"></div>
      <div style="color: var(--text-2); font-size: 13px;">Updating matching events...</div>
    </div>
  `;
  
  try {
    const response = await apiFetch(`/events/?limit=1000&tags=${encodeURIComponent(oldName)}`);
    if (!response.ok) throw new Error(`Query failed: HTTP ${response.status}`);
    const data = await response.json();
    const events = data.items;
    
    let successCount = 0;
    for (const e of events) {
      let nextTags = e.tags.filter(t => t !== oldName);
      if (!nextTags.includes(cleanedNewName)) {
        nextTags.push(cleanedNewName);
      }
      
      const patch = await apiFetch(`/events/${e.id}`, {
        method: 'PATCH',
        body: { tags: nextTags }
      });
      if (patch.ok) successCount++;
    }
    
    alert(`Successfully updated ${successCount} event(s).`);
    loadTagsView(document.getElementById('main'));
  } catch (err) {
    alert(`Failed to rename tag: ${err.message}`);
    loadTagsView(document.getElementById('main'));
  }
}

/**
 * Confirms and deletes a tag from all matching events.
 */
async function deleteTag(tagName) {
  if (!confirm(`Are you sure you want to delete the tag '#${tagName}' from all events? This cannot be undone.`)) {
    return;
  }
  
  const listEl = document.getElementById('tags-list');
  listEl.innerHTML = `
    <div class="spinner-wrap" style="flex-direction: column; gap: 10px;">
      <div class="spinner"></div>
      <div style="color: var(--text-2); font-size: 13px;">Stripping tag from events...</div>
    </div>
  `;
  
  try {
    const response = await apiFetch(`/events/?limit=1000&tags=${encodeURIComponent(tagName)}`);
    if (!response.ok) throw new Error(`Query failed: HTTP ${response.status}`);
    const data = await response.json();
    const events = data.items;
    
    let successCount = 0;
    for (const e of events) {
      let nextTags = e.tags.filter(t => t !== tagName);
      const patch = await apiFetch(`/events/${e.id}`, {
        method: 'PATCH',
        body: { tags: nextTags }
      });
      if (patch.ok) successCount++;
    }
    
    alert(`Removed tag from ${successCount} event(s).`);
    loadTagsView(document.getElementById('main'));
  } catch (err) {
    alert(`Failed to delete tag: ${err.message}`);
    loadTagsView(document.getElementById('main'));
  }
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
    
    const addPlaceholder = card.querySelector('.tag-pill-placeholder');
    if (addPlaceholder) {
      addPlaceholder.addEventListener('click', (e) => {
        e.stopPropagation();
        editEventTags(id, card);
      });
      
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
  const mergedIdsStr = card.getAttribute('data-merged-ids');
  const ids = mergedIdsStr ? mergedIdsStr.split(',').map(Number) : [id];
  
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
    // Update all events in the group in parallel
    await Promise.all(ids.map(async (currId) => {
      const response = await apiFetch(`/events/${currId}`, {
        method: 'PATCH',
        body: { tags: newTags }
      });
      if (!response.ok) {
        throw new Error(`Server returned HTTP ${response.status} for event ${currId}`);
      }
      
      const updated = await response.json();
      const updateInArray = (arr) => {
        const idx = arr.findIndex(e => e.id === currId);
        if (idx !== -1) arr[idx].tags = updated.tags;
      };
      updateInArray(state.timelineEvents);
      updateInArray(state.searchResults);
    }));
    
    // Update local group memory for prompt display next time
    event.tags = newTags;
    
    const updateCardTagsDOM = () => {
      const tagsContainer = card.querySelector('.event-tags');
      if (tagsContainer) {
        if (newTags.length > 0) {
          tagsContainer.innerHTML = newTags.map(t => `<span class="tag-pill">${escapeHtml(t)}</span>`).join('');
        } else {
          tagsContainer.innerHTML = `<span class="tag-pill-placeholder" style="font-size: 10.5px; opacity: 0.3; cursor: pointer;">+ add tags</span>`;
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
  const mergedIdsStr = card.getAttribute('data-merged-ids');
  const ids = mergedIdsStr ? mergedIdsStr.split(',').map(Number) : [id];
  
  const confirmMsg = ids.length > 1
    ? `Are you sure you want to delete this block of ${ids.length} grouped items? This action cannot be undone.`
    : 'Are you sure you want to delete this event? This action cannot be undone.';
    
  if (!confirm(confirmMsg)) {
    return;
  }
  
  try {
    // Delete all events in the group in parallel
    await Promise.all(ids.map(async (currId) => {
      const response = await apiFetch(`/events/${currId}`, {
        method: 'DELETE'
      });
      if (!response.ok) {
        throw new Error(`Server returned HTTP ${response.status} for event ${currId}`);
      }
      state.timelineEvents = state.timelineEvents.filter(e => e.id !== currId);
      state.searchResults = state.searchResults.filter(e => e.id !== currId);
    }));
    
    const removeCardDOM = () => {
      const dayGroup = card.closest('.day-group');
      card.remove();
      
      if (dayGroup && dayGroup.querySelectorAll('.event-card').length === 0) {
        dayGroup.remove();
      }
      
      if (state.currentView === 'timeline') {
        state.timelineTotal = Math.max(0, state.timelineTotal - ids.length);
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
        state.searchTotal = Math.max(0, state.searchTotal - ids.length);
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
  
  // Clear any existing infinite scroll observers to avoid leaks
  if (timelineObserver) {
    timelineObserver.disconnect();
    timelineObserver = null;
  }
  if (searchObserver) {
    searchObserver.disconnect();
    searchObserver = null;
  }
  
  updateSidebarActiveLink(viewName);
  
  const updateDOM = () => {
    state.currentView = viewName;
    const mainEl = document.getElementById('main');
    if (!mainEl) return;
    
    if (viewName === 'timeline') {
      renderTimelineView(mainEl);
    } else if (viewName === 'search') {
      renderSearchView(mainEl);
    } else if (viewName === 'stats') {
      renderStatsView(mainEl);
    } else if (viewName === 'tags') {
      loadTagsView(mainEl);
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
  } else if (hash === '#stats') {
    navigateToView('stats');
  } else if (hash === '#tags') {
    navigateToView('tags');
  } else if (hash === '#settings') {
    navigateToView('settings');
  } else {
    window.location.hash = '#timeline';
  }
}

// ── 8. Global Event Delegation ───────────────────────────────

document.addEventListener('click', (e) => {
  // Timeline manual trigger load button fallback
  const timelineLoadMore = e.target.closest('#timeline-load-more');
  if (timelineLoadMore && !timelineLoadMore.disabled) {
    timelineLoadMore.disabled = true;
    state.timelineOffset += state.timelineLimit;
    loadTimelineEvents();
    return;
  }
  
  // Search manual trigger load button fallback
  const searchLoadMore = e.target.closest('#search-load-more');
  if (searchLoadMore && !searchLoadMore.disabled) {
    searchLoadMore.disabled = true;
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
  
  if (!state.token && !window.location.hash) {
    window.location.hash = '#settings';
  } else {
    handleRouting();
  }
});

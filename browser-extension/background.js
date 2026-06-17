/* ============================================================
   Biograph Web Sensor — background.js
   Manifest V3 Background Service Worker
   ============================================================ */

let isFlushing = false;
let lastLoggedUrl = '';
let lastLoggedTime = 0;

/**
 * Listens for tab updates (both full loads and SPA URL changes).
 */
// Track pending tab visits to handle SPA dynamic titles and fast navigation
const pendingVisits = new Map();

/**
 * Commits a pending visit event to the offline queue.
 */
async function commitVisit(tabId) {
  const pending = pendingVisits.get(tabId);
  if (!pending) return;

  const now = Date.now();
  
  // If the website is YouTube and the title is generic, let's wait a bit longer for it to load/settle
  const isYouTube = pending.url.includes('youtube.com');
  const isGenericTitle = !pending.title || 
                         pending.title === 'YouTube' || 
                         pending.title === 'YouTube Movies' || 
                         pending.title === 'Movies & TV' || 
                         pending.title === 'Movies & TV - YouTube';
  
  if (isYouTube && isGenericTitle && (!pending.retryCount || pending.retryCount < 3)) {
    pending.retryCount = (pending.retryCount || 0) + 1;
    pending.timeoutId = setTimeout(() => commitVisit(tabId), 2000);
    return;
  }

  // Done with this tab's pending visit
  pendingVisits.delete(tabId);

  // Deduplication: prevent logging the same URL repeatedly if loaded within 10 seconds
  if (pending.url === lastLoggedUrl && (now - lastLoggedTime) < 10000) {
    return;
  }

  lastLoggedUrl = pending.url;
  lastLoggedTime = now;

  await queueEvent({
    timestamp: new Date(pending.timestamp).toISOString(),
    ev_type: 'web-visit',
    content: {
      url: pending.url,
      title: pending.title || '',
      browser: 'Chrome'
    },
    tags: ['web']
  });
}

/**
 * Listens for tab updates (handles initial loading, reloads, and dynamic SPA transitions).
 */
chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
  // Filter out any pages that are not http:// or https:// (exclude chrome://, etc.)
  if (tab.url && !tab.url.startsWith('http://') && !tab.url.startsWith('https://')) {
    if (pendingVisits.has(tabId)) {
      clearTimeout(pendingVisits.get(tabId).timeoutId);
      pendingVisits.delete(tabId);
    }
    return;
  }

  // 1. URL changed or page load started/reloaded
  if (changeInfo.url || changeInfo.status === 'loading') {
    const targetUrl = changeInfo.url || tab.url;
    if (!targetUrl) return;

    // If we already have a pending visit for this tab with the same URL, don't reset the timeout
    const existing = pendingVisits.get(tabId);
    if (existing && existing.url === targetUrl) {
      return;
    }

    if (pendingVisits.has(tabId)) {
      clearTimeout(pendingVisits.get(tabId).timeoutId);
    }

    const timeoutId = setTimeout(() => {
      commitVisit(tabId);
    }, 3000); // 3 seconds initial delay to let the page load/title settle

    pendingVisits.set(tabId, {
      url: targetUrl,
      title: tab.title || '',
      timestamp: Date.now(),
      timeoutId: timeoutId,
      retryCount: 0
    });
    return;
  }

  // 2. Title changed dynamically (critical for SPA routers like YouTube)
  if (changeInfo.title) {
    const pending = pendingVisits.get(tabId);
    if (pending) {
      pending.title = changeInfo.title;
    }
    return;
  }

  // 3. Page load completed
  if (changeInfo.status === 'complete') {
    const pending = pendingVisits.get(tabId);
    if (pending) {
      clearTimeout(pending.timeoutId);
      pending.title = tab.title || pending.title;
      pending.url = tab.url || pending.url;
      await commitVisit(tabId);
    }
  }
});

/**
 * Cleans up pending visits when a tab is closed.
 */
chrome.tabs.onRemoved.addListener((tabId, removeInfo) => {
  if (pendingVisits.has(tabId)) {
    clearTimeout(pendingVisits.get(tabId).timeoutId);
    pendingVisits.delete(tabId);
  }
});

/**
 * Cleans up pending visits when a tab is replaced (e.g. prerendering).
 */
chrome.tabs.onReplaced.addListener((addedTabId, removedTabId) => {
  if (pendingVisits.has(removedTabId)) {
    clearTimeout(pendingVisits.get(removedTabId).timeoutId);
    pendingVisits.delete(removedTabId);
  }
});

/**
 * Appends a new event to the offline queue and schedules a flush.
 */
async function queueEvent(event) {
  const config = await chrome.storage.local.get(['serverUrl', 'token', 'hostName', 'offlineQueue']);
  const hostName = config.hostName || 'browser';
  
  event.source_host = hostName;
  event.source_app = 'chrome';
  
  const queue = config.offlineQueue || [];
  queue.push(event);
  
  await chrome.storage.local.set({ offlineQueue: queue });
  await updateBadge(queue.length);
  
  await flushQueue();
}

/**
 * Updates the extension badge text and colour to signal pending unsent logs.
 */
async function updateBadge(count) {
  try {
    if (count > 0) {
      await chrome.action.setBadgeText({ text: String(count) });
      await chrome.action.setBadgeBackgroundColor({ color: '#fb923c' }); // warning orange
    } else {
      await chrome.action.setBadgeText({ text: '' });
    }
  } catch (err) {
    console.error('Failed to update extension action badge:', err);
  }
}

/**
 * Sends all buffered events to the backend in a single batch post request.
 */
async function flushQueue() {
  if (isFlushing) return;
  isFlushing = true;
  
  try {
    const config = await chrome.storage.local.get(['serverUrl', 'token', 'offlineQueue']);
    const queue = config.offlineQueue || [];
    
    if (queue.length === 0) {
      isFlushing = false;
      return;
    }
    
    if (!config.serverUrl || !config.token) {
      // Configuration details not loaded/available yet
      isFlushing = false;
      return;
    }
    
    const base = config.serverUrl.replace(/\/+$/, '');
    const url = `${base}/events/batch`;
    
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${config.token}`
      },
      body: JSON.stringify(queue)
    });
    
    if (response.ok) {
      // Empty the queue on successful flush
      await chrome.storage.local.set({ offlineQueue: [] });
      await updateBadge(0);
    } else {
      console.warn(`Server rejected event batch flush: HTTP ${response.status}`);
    }
  } catch (err) {
    console.error('Connection failure during event flush:', err);
  } finally {
    isFlushing = false;
  }
}

// Flush queue on extension startup (e.g. if browser restarted after being offline)
chrome.runtime.onStartup.addListener(async () => {
  await flushQueue();
});

// Allow manual flush triggers via message passing (e.g. from Options page)
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.action === 'flush') {
    flushQueue().then(() => sendResponse({ success: true }));
    return true; // keep message channel open
  }
});

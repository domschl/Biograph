/* ============================================================
   Biograph Web Sensor — background.js
   Manifest V3 Background Service Worker
   ============================================================ */

let isFlushing = false;
let lastLoggedUrl = '';
let lastLoggedTime = 0;

/**
 * Listens for completed tab updates to trigger event capture.
 */
chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
  if (changeInfo.status !== 'complete') return;
  if (!tab.url) return;
  
  // Log only HTTP and HTTPS websites (exclude chrome://, file://, extension pages, etc.)
  if (!tab.url.startsWith('http://') && !tab.url.startsWith('https://')) {
    return;
  }
  
  const now = Date.now();
  // Deduplication: prevent logging the same URL repeatedly if loaded within 10 seconds
  if (tab.url === lastLoggedUrl && (now - lastLoggedTime) < 10000) {
    return;
  }
  
  lastLoggedUrl = tab.url;
  lastLoggedTime = now;
  
  await queueEvent({
    timestamp: new Date(now).toISOString(),
    ev_type: 'web-visit',
    content: {
      url: tab.url,
      title: tab.title || '',
      browser: 'Chrome'
    },
    tags: ['web']
  });
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

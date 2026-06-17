/* ============================================================
   Biograph Web Sensor — options.js
   Options page controller using MV3 async storage API
   ============================================================ */

document.addEventListener('DOMContentLoaded', async () => {
  const form = document.getElementById('options-form');
  const serverUrlInput = document.getElementById('server-url');
  const tokenInput = document.getElementById('token');
  const hostNameInput = document.getElementById('host-name');
  
  const saveBtn = document.getElementById('save-btn');
  const testBtn = document.getElementById('test-btn');
  const statusBadge = document.getElementById('test-status');
  
  const queueSection = document.getElementById('queue-section');
  const queueCountEl = document.getElementById('queue-count');
  const flushBtn = document.getElementById('flush-btn');
  const clearBtn = document.getElementById('clear-btn');

  // Load saved configuration from storage
  const config = await chrome.storage.local.get(['serverUrl', 'token', 'hostName', 'offlineQueue']);
  
  if (config.serverUrl) serverUrlInput.value = config.serverUrl;
  if (config.token) tokenInput.value = config.token;
  if (config.hostName) {
    hostNameInput.value = config.hostName;
  } else {
    hostNameInput.value = 'browser';
  }

  // Update UI for queue status
  const updateQueueUI = (queue) => {
    const len = queue ? queue.length : 0;
    if (len > 0) {
      queueSection.style.display = 'block';
      queueCountEl.textContent = String(len);
    } else {
      queueSection.style.display = 'none';
    }
  };

  updateQueueUI(config.offlineQueue);

  // Monitor storage changes in real-time
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === 'local' && changes.offlineQueue) {
      updateQueueUI(changes.offlineQueue.newValue);
    }
  });

  // Handle Form Submission (Saving Settings)
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const serverUrl = serverUrlInput.value.trim().replace(/\/+$/, '');
    const token = tokenInput.value.trim();
    const hostName = hostNameInput.value.trim() || 'browser';
    
    saveBtn.disabled = true;
    const originalText = saveBtn.textContent;
    saveBtn.textContent = 'Saving...';
    
    try {
      await chrome.storage.local.set({ serverUrl, token, hostName });
      
      // Notify service worker to try flushing any queued events with the new credentials
      chrome.runtime.sendMessage({ action: 'flush' });
      
      saveBtn.textContent = 'Saved!';
      setTimeout(() => {
        saveBtn.textContent = originalText;
        saveBtn.disabled = false;
      }, 1500);
    } catch (err) {
      console.error('Failed to save settings:', err);
      saveBtn.textContent = 'Error';
      saveBtn.disabled = false;
    }
  });

  // Handle Connection Testing
  testBtn.addEventListener('click', async () => {
    const url = serverUrlInput.value.trim().replace(/\/+$/, '');
    const token = tokenInput.value.trim();
    
    testBtn.disabled = true;
    statusBadge.style.display = 'inline-flex';
    statusBadge.className = 'status-badge';
    statusBadge.textContent = 'Testing...';
    
    try {
      // 1. Perform health check first (unauthenticated)
      const resHealth = await fetch(`${url}/health`);
      if (!resHealth.ok) {
        throw new Error(`Health check returned HTTP ${resHealth.status}`);
      }
      
      // 2. Perform authentication check (fetch first event)
      const headers = {};
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }
      
      const resEvents = await fetch(`${url}/events/?limit=1`, { headers });
      if (resEvents.status === 401) {
        statusBadge.className = 'status-badge err';
        statusBadge.textContent = 'Invalid token';
        return;
      }
      if (!resEvents.ok) {
        throw new Error(`Auth check returned HTTP ${resEvents.status}`);
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

  // Handle Queue Flush Trigger
  flushBtn.addEventListener('click', () => {
    flushBtn.disabled = true;
    const originalText = flushBtn.textContent;
    flushBtn.textContent = 'Flushing...';
    
    chrome.runtime.sendMessage({ action: 'flush' }, (response) => {
      flushBtn.textContent = originalText;
      flushBtn.disabled = false;
    });
  });

  // Handle Queue Reset/Clear
  clearBtn.addEventListener('click', async () => {
    if (confirm('Are you sure you want to discard all offline events? This cannot be undone.')) {
      await chrome.storage.local.set({ offlineQueue: [] });
      await chrome.action.setBadgeText({ text: '' });
    }
  });
});

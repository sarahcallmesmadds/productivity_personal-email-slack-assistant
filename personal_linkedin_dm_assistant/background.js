/**
 * Background service worker — handles API calls to the Railway app
 * and manages extension state.
 */

// Listen for messages from the content script
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === 'DRAFT_REQUEST') {
    handleDraftRequest(message.payload)
      .then(sendResponse)
      .catch((err) => sendResponse({ error: err.message }));
    return true; // Keep the message channel open for async response
  }

  if (message.type === 'CHECK_STATUS') {
    checkApiStatus()
      .then(sendResponse)
      .catch((err) => sendResponse({ status: 'disconnected', error: err.message }));
    return true;
  }
});

async function getSettings() {
  const result = await chrome.storage.sync.get({
    apiUrl: '',
    apiSecret: '',
    enabled: true,
  });
  return result;
}

async function handleDraftRequest(payload) {
  const settings = await getSettings();

  if (!settings.enabled) {
    return { error: 'Extension is disabled' };
  }

  if (!settings.apiUrl || !settings.apiSecret) {
    return { error: 'API URL and secret not configured. Open extension settings.' };
  }

  const url = `${settings.apiUrl.replace(/\/$/, '')}/api/linkedin/draft`;

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${settings.apiSecret}`,
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const text = await response.text();
      throw new Error(`API error ${response.status}: ${text}`);
    }

    const data = await response.json();

    // Track last successful call
    await chrome.storage.local.set({
      lastDraftTime: new Date().toISOString(),
      lastDraftSender: payload.sender_name,
    });

    return data;
  } catch (err) {
    console.error('[LinkedIn Assistant] API call failed:', err);
    return { error: err.message };
  }
}

async function checkApiStatus() {
  const settings = await getSettings();

  if (!settings.apiUrl) {
    return { status: 'not_configured' };
  }

  try {
    const response = await fetch(`${settings.apiUrl.replace(/\/$/, '')}/health`, {
      method: 'GET',
      signal: AbortSignal.timeout(5000),
    });

    if (response.ok) {
      return { status: 'connected' };
    }
    return { status: 'error', code: response.status };
  } catch (err) {
    return { status: 'disconnected', error: err.message };
  }
}

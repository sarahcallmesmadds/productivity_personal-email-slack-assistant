document.addEventListener('DOMContentLoaded', async () => {
  const apiUrlInput = document.getElementById('apiUrl');
  const apiSecretInput = document.getElementById('apiSecret');
  const enabledInput = document.getElementById('enabled');
  const saveBtn = document.getElementById('saveBtn');
  const statusBar = document.getElementById('status-bar');
  const statusText = document.getElementById('status-text');
  const lastDraftDiv = document.getElementById('lastDraft');
  const lastDraftInfo = document.getElementById('lastDraftInfo');
  const errorMsg = document.getElementById('errorMsg');

  // Load saved settings
  const settings = await chrome.storage.sync.get({
    apiUrl: '',
    apiSecret: '',
    enabled: true,
  });

  apiUrlInput.value = settings.apiUrl;
  apiSecretInput.value = settings.apiSecret;
  enabledInput.checked = settings.enabled;

  // Check API status
  checkStatus();

  // Load last draft info
  const localData = await chrome.storage.local.get(['lastDraftTime', 'lastDraftSender']);
  if (localData.lastDraftTime) {
    const ago = timeAgo(new Date(localData.lastDraftTime));
    lastDraftInfo.textContent = `${localData.lastDraftSender || 'Unknown'} — ${ago}`;
    lastDraftDiv.style.display = 'block';
  }

  // Save settings
  saveBtn.addEventListener('click', async () => {
    await chrome.storage.sync.set({
      apiUrl: apiUrlInput.value.trim(),
      apiSecret: apiSecretInput.value.trim(),
      enabled: enabledInput.checked,
    });

    errorMsg.style.display = 'none';
    saveBtn.textContent = 'Saved';
    setTimeout(() => {
      saveBtn.textContent = 'Save Settings';
    }, 1500);

    checkStatus();
  });

  async function checkStatus() {
    if (!apiUrlInput.value.trim()) {
      setStatus('not_configured', 'API URL not set');
      return;
    }

    setStatus('disconnected', 'Checking...');

    try {
      const response = await chrome.runtime.sendMessage({ type: 'CHECK_STATUS' });

      if (response.status === 'connected') {
        setStatus('connected', 'Connected');
      } else if (response.status === 'not_configured') {
        setStatus('not_configured', 'API URL not set');
      } else {
        setStatus('disconnected', response.error || 'Cannot reach API');
      }
    } catch (err) {
      setStatus('disconnected', 'Extension error');
    }
  }

  function setStatus(status, text) {
    statusBar.className = `status ${status}`;
    statusText.textContent = text;
  }

  function timeAgo(date) {
    const seconds = Math.floor((Date.now() - date.getTime()) / 1000);
    if (seconds < 60) return 'just now';
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    return `${Math.floor(seconds / 86400)}d ago`;
  }
});

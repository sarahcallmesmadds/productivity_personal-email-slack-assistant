/**
 * Content script — runs on LinkedIn messaging pages.
 * Reads DM conversations, sends to API for drafting, injects drafts into composer.
 */

(function () {
  'use strict';

  const LOG_PREFIX = '[LinkedIn Assistant]';
  let currentConversationId = null;
  let observer = null;
  let processingLock = false;

  // --- Initialization ---

  function init() {
    console.log(LOG_PREFIX, 'Content script loaded on LinkedIn messaging');
    waitForMessagingPage().then(() => {
      console.log(LOG_PREFIX, 'Messaging page ready, starting observer');
      observeConversationChanges();
    });
  }

  function waitForMessagingPage() {
    return new Promise((resolve) => {
      const check = () => {
        const container =
          document.querySelector(SELECTORS.conversationList) ||
          document.querySelector(SELECTORS.threadContainer);
        if (container) {
          resolve();
        } else {
          setTimeout(check, 500);
        }
      };
      check();
    });
  }

  // --- Conversation observation ---

  function observeConversationChanges() {
    // Watch for URL changes (LinkedIn is a SPA)
    let lastUrl = location.href;
    const urlObserver = new MutationObserver(() => {
      if (location.href !== lastUrl) {
        lastUrl = location.href;
        console.log(LOG_PREFIX, 'URL changed:', lastUrl);
        handleConversationChange();
      }
    });
    urlObserver.observe(document.body, { childList: true, subtree: true });

    // Watch for thread container changes (new messages, conversation switches)
    const watchThread = () => {
      const threadContainer = document.querySelector(SELECTORS.threadContainer);
      if (!threadContainer) {
        setTimeout(watchThread, 1000);
        return;
      }

      if (observer) observer.disconnect();

      observer = new MutationObserver((mutations) => {
        // Debounce — only process after mutations settle
        clearTimeout(observer._debounceTimer);
        observer._debounceTimer = setTimeout(() => {
          handleConversationChange();
        }, 800);
      });

      observer.observe(threadContainer, {
        childList: true,
        subtree: true,
        characterData: true,
      });

      // Process the current conversation immediately
      handleConversationChange();
    };

    watchThread();
  }

  // --- Message extraction ---

  async function handleConversationChange() {
    if (processingLock) return;
    processingLock = true;

    try {
      // Check if extension is enabled
      const settings = await chrome.storage.sync.get({ enabled: true });
      if (!settings.enabled) {
        processingLock = false;
        return;
      }

      const conversationData = extractConversation();
      if (!conversationData) {
        processingLock = false;
        return;
      }

      // Skip if we already processed this exact message
      const convId = conversationData.conversation_id;
      if (convId === currentConversationId) {
        processingLock = false;
        return;
      }

      // Check if already drafted
      const stored = await chrome.storage.local.get(convId);
      if (stored[convId]) {
        console.log(LOG_PREFIX, 'Already drafted for', convId);
        currentConversationId = convId;
        processingLock = false;
        return;
      }

      console.log(LOG_PREFIX, 'New conversation detected:', conversationData.sender_name);
      currentConversationId = convId;

      // Request draft from API
      const response = await chrome.runtime.sendMessage({
        type: 'DRAFT_REQUEST',
        payload: conversationData,
      });

      if (response.error) {
        console.error(LOG_PREFIX, 'Draft request failed:', response.error);
        processingLock = false;
        return;
      }

      // Mark as processed
      await chrome.storage.local.set({ [convId]: { drafted: true, timestamp: Date.now() } });

      // Inject draft or show "no response needed"
      if (response.needs_response) {
        injectDraft(response.draft_text);
      } else {
        showNoResponseBadge(response.summary);
      }
    } catch (err) {
      console.error(LOG_PREFIX, 'Error handling conversation:', err);
    }

    processingLock = false;
  }

  function extractConversation() {
    // Get all message groups in the thread
    const messageGroups = document.querySelectorAll(SELECTORS.messageGroup);
    if (!messageGroups.length) return null;

    // Find the last inbound message (not from me)
    let lastInboundGroup = null;
    for (let i = messageGroups.length - 1; i >= 0; i--) {
      const group = messageGroups[i];
      if (!group.matches(SELECTORS.ownMessageIndicator)) {
        lastInboundGroup = group;
        break;
      }
    }

    if (!lastInboundGroup) return null; // No inbound messages, or I sent the last message

    // Check if I already replied after this message
    const allGroups = Array.from(messageGroups);
    const inboundIndex = allGroups.indexOf(lastInboundGroup);
    const hasMyReplyAfter = allGroups
      .slice(inboundIndex + 1)
      .some((g) => g.matches(SELECTORS.ownMessageIndicator));

    if (hasMyReplyAfter) return null; // Already replied

    // Extract sender info
    const senderNameEl =
      lastInboundGroup.querySelector(SELECTORS.senderName) ||
      document.querySelector(SELECTORS.activeHeaderName);
    const senderName = senderNameEl ? senderNameEl.textContent.trim() : 'Unknown';

    const headlineEl = document.querySelector(SELECTORS.activeHeaderHeadline);
    const senderHeadline = headlineEl ? headlineEl.textContent.trim() : null;

    // Extract message text from the last inbound group
    const messageBubbles = lastInboundGroup.querySelectorAll(SELECTORS.messageText);
    const lastBubble = messageBubbles[messageBubbles.length - 1];
    const messageText = lastBubble ? lastBubble.textContent.trim() : '';

    if (!messageText) return null;

    // Extract conversation context (up to 5 previous messages)
    const context = [];
    const contextGroups = allGroups.slice(Math.max(0, inboundIndex - 5), inboundIndex);
    for (const group of contextGroups) {
      const isOwn = group.matches(SELECTORS.ownMessageIndicator);
      const prefix = isOwn ? 'Me' : senderName;
      const bubbles = group.querySelectorAll(SELECTORS.messageText);
      for (const bubble of bubbles) {
        const text = bubble.textContent.trim();
        if (text) context.push(`${prefix}: ${text}`);
      }
    }

    // Generate a stable conversation ID from the URL or content
    const urlMatch = location.href.match(/messaging\/thread\/([^/?]+)/);
    const conversationId = urlMatch
      ? urlMatch[1]
      : hashString(`${senderName}-${messageText.slice(0, 50)}`);

    return {
      sender_name: senderName,
      sender_headline: senderHeadline,
      message_text: messageText,
      conversation_context: context,
      conversation_id: conversationId,
    };
  }

  // --- Draft injection ---

  function injectDraft(draftText) {
    const composer =
      document.querySelector(SELECTORS.replyComposer) ||
      document.querySelector(SELECTORS.replyComposerFallback);

    if (!composer) {
      console.warn(LOG_PREFIX, 'Reply composer not found');
      return;
    }

    // Set the draft text
    composer.focus();
    composer.textContent = draftText;

    // Dispatch input event so LinkedIn's internal state updates
    composer.dispatchEvent(new Event('input', { bubbles: true }));

    // Show the draft badge
    showDraftBadge(composer);

    console.log(LOG_PREFIX, 'Draft injected into composer');
  }

  function showDraftBadge(composer) {
    // Remove any existing badge
    const existing = document.getElementById('li-assistant-badge');
    if (existing) existing.remove();

    const badge = document.createElement('div');
    badge.id = 'li-assistant-badge';
    badge.textContent = 'Draft by assistant — edit and send';
    Object.assign(badge.style, {
      position: 'absolute',
      top: '-28px',
      left: '8px',
      background: '#0a66c2',
      color: '#fff',
      fontSize: '11px',
      padding: '3px 10px',
      borderRadius: '4px',
      zIndex: '9999',
      fontFamily: '-apple-system, BlinkMacSystemFont, sans-serif',
      opacity: '0.9',
      transition: 'opacity 0.3s',
      pointerEvents: 'none',
    });

    // Position relative to composer
    const parent = composer.closest('.msg-form') || composer.parentElement;
    if (parent) {
      parent.style.position = 'relative';
      parent.appendChild(badge);
    }

    // Fade when user starts typing
    composer.addEventListener(
      'keydown',
      () => {
        badge.style.opacity = '0';
        setTimeout(() => badge.remove(), 300);
      },
      { once: true }
    );
  }

  function showNoResponseBadge(summary) {
    const composer =
      document.querySelector(SELECTORS.replyComposer) ||
      document.querySelector(SELECTORS.replyComposerFallback);

    if (!composer) return;

    const existing = document.getElementById('li-assistant-badge');
    if (existing) existing.remove();

    const badge = document.createElement('div');
    badge.id = 'li-assistant-badge';
    badge.textContent = `No response needed — ${summary || 'informational message'}`;
    Object.assign(badge.style, {
      position: 'absolute',
      top: '-28px',
      left: '8px',
      background: '#666',
      color: '#fff',
      fontSize: '11px',
      padding: '3px 10px',
      borderRadius: '4px',
      zIndex: '9999',
      fontFamily: '-apple-system, BlinkMacSystemFont, sans-serif',
      opacity: '0.7',
      pointerEvents: 'none',
    });

    const parent = composer.closest('.msg-form') || composer.parentElement;
    if (parent) {
      parent.style.position = 'relative';
      parent.appendChild(badge);
    }

    // Auto-remove after 10 seconds
    setTimeout(() => {
      badge.style.opacity = '0';
      setTimeout(() => badge.remove(), 300);
    }, 10000);
  }

  // --- Utilities ---

  function hashString(str) {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
      const char = str.charCodeAt(i);
      hash = (hash << 5) - hash + char;
      hash |= 0;
    }
    return 'conv-' + Math.abs(hash).toString(36);
  }

  // --- Start ---
  init();
})();

/**
 * LinkedIn DOM selectors — isolated here so they're easy to update
 * when LinkedIn changes their markup.
 *
 * If any critical selector stops matching, the extension will
 * gracefully disable and show an error in the popup.
 */
const SELECTORS = {
  // Messaging page structure
  conversationList: '.msg-conversations-container__conversations-list',
  conversationItem: '.msg-conversation-listitem',
  activeConversation: '.msg-conversation-card--active',
  unreadBadge: '.msg-conversation-card__unread-count',

  // Conversation thread
  threadContainer: '.msg-s-message-list-container',
  messageList: '.msg-s-message-list',
  messageGroup: '.msg-s-message-group',
  messageItem: '.msg-s-message-list__event',
  messageBody: '.msg-s-event-listitem__body',
  messageText: '.msg-s-event-listitem__message-bubble',

  // Sender info
  senderName: '.msg-s-message-group__name',
  senderProfileLink: '.msg-s-message-group__profile-link',
  conversationHeader: '.msg-conversation-card__content--selectable',
  headerName: '.msg-conversation-listitem__participant-names',
  headerHeadline: '.msg-conversation-card__message-snippet-body',

  // Active conversation header (top of thread)
  activeHeader: '.msg-overlay-conversation-bubble__header',
  activeHeaderName: '.msg-thread__link-to-profile',
  activeHeaderHeadline: '.msg-thread__headline',

  // Reply composer
  replyComposer: '.msg-form__contenteditable[contenteditable="true"]',
  replyComposerFallback: '[role="textbox"][contenteditable="true"]',
  sendButton: '.msg-form__send-button',

  // Your own messages (to distinguish inbound vs outbound)
  ownMessageIndicator: '.msg-s-message-group--is-sender',
};

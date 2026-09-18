// frontend/js/state.js
// Purpose: In-memory conversation for this page. Do not persist to localStorage.

import { currentUserId } from './config.js';
import {
    clearLiveChat,
    purgeLegacyUnscopedKeys,
    wipeForeignLiveChats,
    setLastShownUserId,
} from './user_storage.js';

let conversation = []; // [{ role: "user"|"assistant", content: string, ai?: string }]

export function getConversation() {
    return conversation;
}

export function setConversation(newConversation) {
    conversation = newConversation;
    saveConversation();
}

export function addMessage(message) {
    conversation.push(message);
    saveConversation();
}

export function clearConversation() {
    conversation = [];
    const uid = currentUserId();
    if (uid) clearLiveChat(uid);
}

/** Drop in-memory messages without touching storage (login / identity switch). */
export function resetConversationMemory() {
    conversation = [];
}

/**
 * Undo a just-sent user turn (stop/cancel).
 * Removes the last message if it is a user message with the given content.
 * Also drops any trailing assistant message that was incomplete/saved after it.
 */
export function removeLastUserTurn(content) {
    if (!conversation.length || content == null) return false;
    // Walk back past any trailing assistant (e.g. partial save edge case)
    while (conversation.length && conversation[conversation.length - 1].role === 'assistant') {
        conversation.pop();
    }
    const last = conversation[conversation.length - 1];
    if (last && last.role === 'user' && last.content === content) {
        conversation.pop();
        saveConversation();
        return true;
    }
    return false;
}

export function loadConversation(renderCallback, showWelcomeCallback) {
    purgeLegacyUnscopedKeys();
    const uid = currentUserId();
    wipeForeignLiveChats(uid);
    conversation = [];
    if (uid) {
        clearLiveChat(uid);
        setLastShownUserId(uid);
    }
    // Never paint a cached live thread. Shared-family browsers must not show
    // the previous user's message blocks. Persist with Store conversation.
    showWelcomeCallback();
}

export function saveConversation() {
    // Live transcript stays in memory only for this page. Writing it to
    // localStorage is how admin chats leaked onto bill's screen.
}

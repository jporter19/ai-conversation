// frontend/js/state.js
// Purpose: Manage conversation state (array of messages) + persistence via localStorage

import { STORAGE_KEY } from './config.js';

let conversation = []; // [{ role: "user"|"assistant", content: string, ai?: string }]

export function getConversation() {
    return conversation;
}

export function setConversation(newConversation) {
    conversation = newConversation;
    saveConversation(); // Ensure any set also saves
}

export function addMessage(message) {
    conversation.push(message);
    saveConversation();
}

export function clearConversation() {
    conversation = [];
    localStorage.removeItem(STORAGE_KEY);
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
    try {
        const saved = localStorage.getItem(STORAGE_KEY);
        if (saved) {
            let parsed = JSON.parse(saved);

            // Backfill ai field for old assistant messages (one-time upgrade)
            let needsSave = false;
            parsed = parsed.map(msg => {
                if (msg.role === 'assistant' && !msg.ai) {
                    msg.ai = 'grok'; // fallback (change to 'chatgpt' if most old chats were ChatGPT)
                    needsSave = true;
                }
                return msg;
            });

            conversation = parsed;

            // If we backfilled anything, save the updated version immediately
            if (needsSave) {
                console.log('[state.js] Backfilled ai fields — saving updated conversation');
                saveConversation();
            }

            renderCallback();
        } else {
            showWelcomeCallback();
        }
    } catch (e) {
        console.error('Failed to load conversation:', e);
        localStorage.removeItem(STORAGE_KEY);
        showWelcomeCallback();
    }
}

export function saveConversation() {
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(conversation));
        console.log('[state.js] Conversation saved successfully');
    } catch (e) {
        console.warn('[state.js] localStorage save failed:', e);
    }
}
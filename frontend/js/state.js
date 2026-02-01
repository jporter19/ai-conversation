// frontend/js/state.js
// Purpose: Manage conversation state (array of messages) + persistence via localStorage

import { STORAGE_KEY } from './config.js';

let conversation = []; // [{ role: "user"|"assistant", content: string }]

export function getConversation() {
    return conversation;
}

export function setConversation(newConversation) {
    conversation = newConversation;
}

export function addMessage(message) {
    conversation.push(message);
    saveConversation();
}

export function clearConversation() {
    conversation = [];
    localStorage.removeItem(STORAGE_KEY);
}

export function loadConversation(renderCallback, showWelcomeCallback) {
    try {
        const saved = localStorage.getItem(STORAGE_KEY);
        if (saved) {
            conversation = JSON.parse(saved);
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
    } catch (e) {
        console.warn('localStorage save failed:', e);
    }
}
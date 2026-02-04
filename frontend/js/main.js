// frontend/js/main.js
// Purpose: Entry point — imports modules and wires everything together
// At top of main.js, update imports:
import {
    STORAGE_KEY,
    STORAGE_AI_KEY,
    STORAGE_MODEL_KEY,
    grokModels,
    openaiModels,
    populateModels   
} from './config.js';

import {
    getConversation,
    loadConversation,
    saveConversation,
    clearConversation,
    addMessage
} from './state.js';

import { renderHistory, showWelcome } from './ui.js';

import { initChat } from './chat.js';

// ── DOM Elements ────────────────────────────────────────────────────────────────
let aiSelect;
let modelSelect;

function cacheDOMElements() {
    aiSelect = document.getElementById('ai-select');
    modelSelect = document.getElementById('model-select');
}

// ── Set default AI and model ───────────────────────────────────────────────────
// Add this function if not present
function setDefaultSelection() {
    if (aiSelect) {
        aiSelect.value = 'grok';
        populateModels(grokModels);
        if (modelSelect) {
            modelSelect.value = 'grok-4-1-fast-reasoning';
        }
        localStorage.setItem(STORAGE_AI_KEY, 'grok');
        localStorage.setItem(STORAGE_MODEL_KEY, 'grok-4-1-fast-reasoning');
    }
}

// ── Initialization ───────────────────────────────────────────────────────────────
function initApp() {
    cacheDOMElements();

    // Load saved conversation
    loadConversation(renderHistory, showWelcome);

    // Initialize chat actions
    initChat();

    // Attach AI change listener
    aiSelect.addEventListener('change', () => {
        const ai = aiSelect.value;
        if (ai === 'grok') {
            populateModels(grokModels);
            // Default model for Grok
            if (!modelSelect.value) modelSelect.value = 'grok-4-1-fast-reasoning';
        } else if (ai === 'chatgpt') {
            populateModels(openaiModels);
        } else {
            modelSelect.innerHTML = '<option value="" selected disabled>Select model after choosing AI</option>';
            modelSelect.disabled = true;
        }

        localStorage.setItem(STORAGE_AI_KEY, ai);
        localStorage.setItem(STORAGE_MODEL_KEY, modelSelect.value || '');
    });

    // On first load (no saved AI) or after reset → set defaults
    const savedAI = localStorage.getItem(STORAGE_AI_KEY);
    if (!savedAI || savedAI === '') {
        setDefaultSelection();
    } else {
        aiSelect.value = savedAI;
        if (savedAI === 'grok') {
            populateModels(grokModels);
            const savedModel = localStorage.getItem(STORAGE_MODEL_KEY);
            modelSelect.value = savedModel || 'grok-4-1-fast-reasoning';
        } else if (savedAI === 'chatgpt') {
            populateModels(openaiModels);
        }
    }
}

// ── Run when DOM is ready ───────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', initApp);


// frontend/js/main.js
// Purpose: Entry point — imports modules and wires everything together

import {
    STORAGE_KEY,
    STORAGE_AI_KEY,
    STORAGE_MODEL_KEY,
    grokModels,
    openaiModels
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

    if (!aiSelect) console.error('ai-select element not found');
    if (!modelSelect) console.error('model-select element not found');
}

// ── Populate model dropdown ─────────────────────────────────────────────────────
function populateModels(models) {
    console.log('[populateModels] Called with', models.length, 'models');

    if (!modelSelect) {
        console.error('[populateModels] modelSelect not found');
        return;
    }

    modelSelect.innerHTML = '';

    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = 'Select model';
    placeholder.disabled = true;
    placeholder.selected = true;
    modelSelect.appendChild(placeholder);

    models.forEach(m => {
        const opt = document.createElement('option');
        opt.value = m.value;
        opt.textContent = m.label;
        modelSelect.appendChild(opt);
    });

    modelSelect.disabled = false;
    modelSelect.removeAttribute('disabled'); // Force remove attribute
    console.log('[populateModels] Dropdown populated — options:', modelSelect.options.length);
    console.log('[populateModels] Disabled status:', modelSelect.disabled);
}

// ── AI selection handler ────────────────────────────────────────────────────────
function handleAIChange(e) {
    console.log('[handleAIChange] Event fired — new value:', aiSelect.value);

    if (!aiSelect || !modelSelect) {
        console.error('[handleAIChange] Required elements missing');
        return;
    }

    const ai = aiSelect.value.trim();

    if (ai === 'grok') {
        populateModels(grokModels);
    } else if (ai === 'chatgpt') {
        populateModels(openaiModels);
    } else {
        modelSelect.innerHTML = '<option value="" selected disabled>Select model after choosing AI</option>';
        modelSelect.disabled = true;
        console.log('[handleAIChange] No valid AI — dropdown disabled');
    }

    localStorage.setItem(STORAGE_AI_KEY, ai);
    localStorage.setItem(STORAGE_MODEL_KEY, modelSelect.value || '');
}

// ── Initialization ───────────────────────────────────────────────────────────────
function initApp() {
    console.log('[initApp] Starting initialization');

    cacheDOMElements();

    // Load saved conversation and render
    loadConversation(renderHistory, showWelcome);

    // Initialize chat actions
    initChat();

    // Attach AI change listener
    if (aiSelect) {
        aiSelect.addEventListener('change', handleAIChange);
        console.log('[initApp] AI change listener attached');
    } else {
        console.error('[initApp] Could not attach listener — aiSelect missing');
    }

    // Auto-restore saved AI and force population
    const savedAI = localStorage.getItem(STORAGE_AI_KEY);
    if (savedAI && aiSelect) {
        console.log('[initApp] Restoring saved AI:', savedAI);
        aiSelect.value = savedAI;
        handleAIChange(); // Force population
    } else {
        console.log('[initApp] No saved AI found');
    }

    console.log('[initApp] Initialization finished');
}

// ── Run when DOM is ready ───────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    console.log('[DOMContentLoaded] DOM ready — starting initApp');
    initApp();
});
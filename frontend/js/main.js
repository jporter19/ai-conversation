// frontend/js/main.js
// Purpose: Entry point — catalog load, selectors, chat, admin, theme

import {
    STORAGE_AI_KEY,
    STORAGE_MODEL_KEY,
    STORAGE_THEME_KEY,
    DEFAULT_AI,
    DEFAULT_GROK_MODEL,
    loadCatalog,
    catalog,
    populateProviders,
    populateModels,
    applyTheme,
    getModelsForProvider,
    logout,
} from './config.js';

import { loadConversation } from './state.js';
import { renderHistory, showWelcome } from './ui.js';
import { initChat, updateComposerForCapability } from './chat.js';
import { initAdmin } from './admin.js';

let aiSelect;
let modelSelect;

function cacheDOMElements() {
    aiSelect = document.getElementById('ai-select');
    modelSelect = document.getElementById('model-select');
}

function setDefaultSelection() {
    if (!aiSelect || !catalog) return;
    const prefs = catalog.preferences || {};
    const ai = prefs.default_ai || DEFAULT_AI;
    const model = prefs.default_model || DEFAULT_GROK_MODEL;
    populateProviders(aiSelect, ai);
    populateModels(getModelsForProvider(aiSelect.value), model);
    localStorage.setItem(STORAGE_AI_KEY, aiSelect.value);
    localStorage.setItem(STORAGE_MODEL_KEY, modelSelect.value || model);
}

function onAiChange() {
    const ai = aiSelect.value;
    const models = getModelsForProvider(ai);
    const prefs = catalog?.preferences || {};
    let preferred = localStorage.getItem(STORAGE_MODEL_KEY) || prefs.default_model || '';
    if (!models.some(m => m.value === preferred)) {
        preferred = models[0]?.value || '';
    }
    populateModels(models, preferred);
    localStorage.setItem(STORAGE_AI_KEY, ai);
    localStorage.setItem(STORAGE_MODEL_KEY, modelSelect.value || preferred || '');
    updateComposerForCapability();
}

async function initApp() {
    cacheDOMElements();

    document.getElementById('logout-btn')?.addEventListener('click', () => {
        logout();
    });

    // Theme: localStorage first, then server prefs after catalog load
    const localTheme = localStorage.getItem(STORAGE_THEME_KEY);
    if (localTheme) applyTheme(localTheme);

    try {
        await loadCatalog();
    } catch (e) {
        console.error('Catalog load failed', e);
        if (String(e.message || e).includes('Not authenticated')) return;
        showWelcome();
        initChat();
        initAdmin();
        return;
    }

    const prefs = catalog.preferences || {};
    applyTheme(localTheme || prefs.theme || 'light');

    loadConversation(renderHistory, showWelcome);
    initChat();
    initAdmin();

    aiSelect.addEventListener('change', onAiChange);
    modelSelect.addEventListener('change', () => {
        localStorage.setItem(STORAGE_MODEL_KEY, modelSelect.value || '');
        updateComposerForCapability();
    });

    const savedAI = localStorage.getItem(STORAGE_AI_KEY);
    if (!savedAI) {
        setDefaultSelection();
    } else {
        populateProviders(aiSelect, savedAI);
        if (!aiSelect.value) {
            setDefaultSelection();
        } else {
            const models = getModelsForProvider(aiSelect.value);
            const savedModel = localStorage.getItem(STORAGE_MODEL_KEY);
            const valid = models.some(m => m.value === savedModel);
            populateModels(models, valid ? savedModel : (models[0]?.value || ''));
        }
    }
    updateComposerForCapability();
}

document.addEventListener('DOMContentLoaded', initApp);

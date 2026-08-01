// frontend/js/admin/shared.js
import {
    loadCatalog,
    applyTheme,
    catalog,
    populateProviders,
    populateModels,
    STORAGE_AI_KEY,
    STORAGE_MODEL_KEY,
    DEFAULT_AI,
    DEFAULT_GROK_MODEL,
} from '../config.js';

export { catalog, applyTheme, populateProviders, populateModels, STORAGE_AI_KEY, STORAGE_MODEL_KEY, DEFAULT_AI, DEFAULT_GROK_MODEL, loadCatalog };

export let adminModal = null;
export let statusEl = null;
/** @type {object|null} */
export let lastProposal = null;

export function setAdminModal(el) { adminModal = el; }
export function setStatusEl(el) { statusEl = el; }
export function setLastProposal(p) { lastProposal = p; }

export function setStatus(msg, isError = false) {
    if (!statusEl) return;
    statusEl.textContent = msg || '';
    statusEl.classList.toggle('error', !!isError);
}

export function switchTab(tabId) {
    document.querySelectorAll('.admin-tab').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tabId);
    });
    document.querySelectorAll('.admin-panel').forEach(panel => {
        panel.classList.toggle('active', panel.id === `admin-panel-${tabId}`);
    });
}

export function escapeHtml(str) {
    return String(str ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

export async function refreshCatalogUI() {
    await loadCatalog();
    const aiSelect = document.getElementById('ai-select');
    const modelSelect = document.getElementById('model-select');
    let savedAI = localStorage.getItem(STORAGE_AI_KEY) || catalog?.preferences?.default_ai || DEFAULT_AI;
    // If saved AI was removed/disabled, fall back to first available
    const available = catalog?.providers || [];
    if (savedAI && !available.some(p => p.id === savedAI)) {
        savedAI = available[0]?.id || '';
        if (savedAI) localStorage.setItem(STORAGE_AI_KEY, savedAI);
        else localStorage.removeItem(STORAGE_AI_KEY);
    }
    populateProviders(aiSelect, savedAI);
    const models = catalog?.providers?.find(p => p.id === aiSelect.value)?.models || [];
    let savedModel = localStorage.getItem(STORAGE_MODEL_KEY)
        || catalog?.preferences?.default_model
        || DEFAULT_GROK_MODEL;
    if (savedModel && !models.some(m => m.value === savedModel)) {
        savedModel = models[0]?.value || '';
        if (savedModel) localStorage.setItem(STORAGE_MODEL_KEY, savedModel);
        else localStorage.removeItem(STORAGE_MODEL_KEY);
    }
    populateModels(models, savedModel);

    if (typeof globalThis.__refreshAdminPanels === 'function') {
        await globalThis.__refreshAdminPanels();
    }
}


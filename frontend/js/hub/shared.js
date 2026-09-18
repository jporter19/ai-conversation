// frontend/js/hub/shared.js
import {
    loadCatalog,
    applyTheme,
    catalog,
    currentUserId,
    populateProviders,
    populateModels,
    DEFAULT_AI,
    DEFAULT_GROK_MODEL,
} from '../config.js';
import { readItem, writeItem, removeItem, SUFFIX_AI, SUFFIX_MODEL } from '../user_storage.js';

export { catalog, applyTheme, populateProviders, populateModels, DEFAULT_AI, DEFAULT_GROK_MODEL, loadCatalog };

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
    const uid = currentUserId();
    let savedAI = (uid && readItem(uid, SUFFIX_AI)) || catalog?.preferences?.default_ai || DEFAULT_AI;
    // If saved AI was removed/disabled, fall back to first available
    const available = catalog?.providers || [];
    if (savedAI && !available.some(p => p.id === savedAI)) {
        savedAI = available[0]?.id || '';
        if (uid) {
            if (savedAI) writeItem(uid, SUFFIX_AI, savedAI);
            else removeItem(uid, SUFFIX_AI);
        }
    }
    populateProviders(aiSelect, savedAI);
    const models = catalog?.providers?.find(p => p.id === aiSelect.value)?.models || [];
    let savedModel = (uid && readItem(uid, SUFFIX_MODEL))
        || catalog?.preferences?.default_model
        || DEFAULT_GROK_MODEL;
    if (savedModel && !models.some(m => m.value === savedModel)) {
        const flagged = models.find(m => m.roster_slot === 'flagship_chat')
            || models.find(m => (m.tags || []).includes('flagship'));
        savedModel = flagged?.value || models[0]?.value || '';
        if (uid) {
            if (savedModel) writeItem(uid, SUFFIX_MODEL, savedModel);
            else removeItem(uid, SUFFIX_MODEL);
        }
    }
    populateModels(models, savedModel);

    if (typeof globalThis.__refreshAdminPanels === 'function') {
        await globalThis.__refreshAdminPanels();
    }
}


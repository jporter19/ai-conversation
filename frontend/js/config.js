// frontend/js/config.js
// Purpose: Constants, catalog cache, and dropdown helpers.
// Models/providers load from /api/v1/admin/catalog (Admin Tools editable).

export const STORAGE_KEY = 'ai-conversation-hub-current-chat';
export const STORAGE_AI_KEY = 'ai-conversation-hub-selected-ai';
export const STORAGE_MODEL_KEY = 'ai-conversation-hub-selected-model';
export const STORAGE_THEME_KEY = 'ai-conversation-hub-theme';

export const DEFAULT_AI = 'grok';
export const DEFAULT_GROK_MODEL = 'grok-4.5';

/** @type {{ providers: Array, preferences: object, secrets_status: Array } | null} */
export let catalog = null;

export function getProvider(id) {
    return catalog?.providers?.find(p => p.id === id) || null;
}

export function getModelsForProvider(id) {
    const p = getProvider(id);
    return p?.models || [];
}

/**
 * Resolve model capability from catalog (source of truth).
 * Returns 'chat' | 'image' | 'transcript' | 'stt' | 'tts'.
 * Name heuristics only if catalog omits capability (migration).
 */
export function getModelCapability(model, providerId) {
    if (!model) return 'chat';
    const found = getModelsForProvider(providerId).find(m => m.value === model);
    if (found?.capability) {
        return found.capability;
    }
    const provider = getProvider(providerId);
    if (provider?.type === 'tool') return 'transcript';
    // Temporary fallbacks — prefer setting capability in Admin catalog
    const mid = String(model).toLowerCase();
    if (!/vision/i.test(mid) && /imagine-image|dall-e|gpt-image|(^|-)image/i.test(mid)) {
        return 'image';
    }
    if (/whisper|-stt|transcribe|speech-to-text/i.test(mid)) return 'stt';
    if (/-tts|text-to-speech|tts-1/i.test(mid)) return 'tts';
    if (/transcript/i.test(mid)) return 'transcript';
    return 'chat';
}

export function isImageGenerationModel(model, providerId) {
    return getModelCapability(model, providerId) === 'image';
}

export function isTranscriptModel(model, providerId) {
    return getModelCapability(model, providerId) === 'transcript';
}

export async function loadCatalog() {
    const res = await fetch('/api/v1/admin/catalog', { credentials: 'same-origin' });
    if (res.status === 401) {
        window.location.replace('/login');
        throw new Error('Not authenticated');
    }
    if (!res.ok) {
        throw new Error(`Failed to load catalog: ${res.status}`);
    }
    catalog = await res.json();
    return catalog;
}

export async function logout() {
    try {
        await fetch('/api/v1/auth/logout', {
            method: 'POST',
            credentials: 'same-origin',
        });
    } catch (_) { /* ignore */ }
    window.location.replace('/login');
}

export function applyTheme(theme) {
    const t = theme === 'dark' ? 'dark' : 'light';
    document.documentElement.setAttribute('data-theme', t);
    localStorage.setItem(STORAGE_THEME_KEY, t);
}

export function populateProviders(selectEl, selectedId) {
    if (!selectEl || !catalog) return;
    selectEl.innerHTML = '';
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = 'Select AI';
    placeholder.disabled = true;
    selectEl.appendChild(placeholder);

    (catalog.providers || []).forEach(p => {
        const opt = document.createElement('option');
        opt.value = p.id;
        opt.textContent = p.label;
        selectEl.appendChild(opt);
    });

    if (selectedId && (catalog.providers || []).some(p => p.id === selectedId)) {
        selectEl.value = selectedId;
    } else {
        placeholder.selected = true;
    }
    selectEl.disabled = false;
}

export function populateModels(models, selectedValue) {
    const modelSelect = document.getElementById('model-select');
    if (!modelSelect) {
        console.error('[populateModels] model-select element not found');
        return;
    }

    modelSelect.innerHTML = '';

    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = 'Select model';
    placeholder.disabled = true;
    placeholder.selected = true;
    placeholder.dataset.tooltip = 'Choose a model after selecting an AI';
    modelSelect.appendChild(placeholder);

    // Prefer keep/flagship first in the main dropdown
    const recOrder = { keep: 0, review: 1, remove: 2 };
    const ordered = [...(models || [])]
        .filter(m => m.recommendation !== 'remove') // hide remove-recommended from main picker
        .sort((a, b) => {
            const ra = recOrder[a.recommendation] ?? 1;
            const rb = recOrder[b.recommendation] ?? 1;
            if (ra !== rb) return ra - rb;
            const fa = (a.tags || []).includes('flagship') ? 0 : 1;
            const fb = (b.tags || []).includes('flagship') ? 0 : 1;
            if (fa !== fb) return fa - fb;
            return 0;
        });

    ordered.forEach(m => {
        const opt = document.createElement('option');
        opt.value = m.value;
        const tagBits = (m.tags || []).slice(0, 3).join(', ');
        opt.textContent = tagBits
            ? `${m.label || m.value} · ${tagBits}`
            : (m.label || m.value);
        const desc = (m.description || m.tooltip || '').trim()
            || (m.capability ? `${m.capability} model` : 'No description available');
        const reason = (m.recommendation_reason || '').trim();
        const tip = reason ? `${desc}\n\n${reason}` : desc;
        opt.dataset.tooltip = tip;
        opt.dataset.description = desc;
        opt.dataset.tags = (m.tags || []).join(',');
        opt.title = tip;
        modelSelect.appendChild(opt);
    });

    modelSelect.disabled = false;

    if (selectedValue && (models || []).some(m => m.value === selectedValue)) {
        modelSelect.value = selectedValue;
    }

    // Keep select.title in sync with the highlighted / selected model
    const sel = modelSelect.options[modelSelect.selectedIndex];
    modelSelect.title = (sel?.dataset?.tooltip || sel?.title || '').trim();
}

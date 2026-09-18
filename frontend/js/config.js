// frontend/js/config.js
// Purpose: Constants, catalog cache, and dropdown helpers.
// Models/providers load from /api/v1/hub/catalog (Admin Tools editable).
// Prefer "hub" not "admin" — Brave adblock often blocks URLs containing /admin/.

import { writeItem, SUFFIX_THEME } from './user_storage.js';
import { readJsonResponse } from './http.js';

/** Canonical hub API prefix (adblock-safe). */
export const HUB_API = '/api/v1/hub';

export const DEFAULT_AI = 'grok';
export const DEFAULT_GROK_MODEL = 'grok-4.6';

const SLOT_GROUP = {
    flagship_chat: 'Current',
    cheap_chat: 'Current',
    coding: 'Current',
    flagship_image: 'Media',
    cheap_image: 'Media',
    video: 'Media',
    stt: 'Voice',
    tts: 'Voice',
};
const SLOT_ORDER = [
    'flagship_chat', 'cheap_chat', 'coding',
    'flagship_image', 'cheap_image', 'video',
    'stt', 'tts',
];

/** Shared catalog object — mutate in place so all importers see updates. */
export let catalog = {
    providers: [],
    preferences: {},
    secrets_status: [],
};

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
    if (/sora|imagine-video/i.test(mid) || (/video/i.test(mid) && /imagine/i.test(mid))) {
        return 'video';
    }
    if (/whisper|-stt|transcribe|speech-to-text/i.test(mid)) return 'stt';
    if (/-tts|text-to-speech|tts-1/i.test(mid)) return 'tts';
    if (/transcript/i.test(mid)) return 'transcript';
    return 'chat';
}

export function inferRosterSlot(model) {
    if (!model) return '';
    if (model.roster_slot) return model.roster_slot;
    const tags = model.tags || [];
    const cap = model.capability || 'chat';
    if (cap === 'stt') return 'stt';
    if (cap === 'tts') return 'tts';
    if (cap === 'video') return 'video';
    if (cap === 'image') {
        if (tags.includes('cheap')) return 'cheap_image';
        return 'flagship_image';
    }
    if (tags.includes('flagship')) return 'flagship_chat';
    if (tags.includes('coding')) return 'coding';
    if (tags.includes('cheap') || tags.includes('fast')) return 'cheap_chat';
    return '';
}

/** Flagship chat id for a provider, or DEFAULT_GROK_MODEL. */
export function flagshipModelId(providerId) {
    const models = getModelsForProvider(providerId);
    const slotted = models.find(m => inferRosterSlot(m) === 'flagship_chat' && m.value);
    if (slotted?.value) return slotted.value;
    const tagged = models.find(m => (m.tags || []).includes('flagship')
        && (m.capability || 'chat') === 'chat' && m.value);
    if (tagged?.value) return tagged.value;
    return providerId === 'grok' ? DEFAULT_GROK_MODEL : (models[0]?.value || DEFAULT_GROK_MODEL);
}

export function isImageGenerationModel(model, providerId) {
    return getModelCapability(model, providerId) === 'image';
}

export function isTranscriptModel(model, providerId) {
    return getModelCapability(model, providerId) === 'transcript';
}

/**
 * Identity comes only from the Porter Family Portal cookie (portal_session).
 * This app has no username/password login of its own.
 * @type {{ authenticated?: boolean, username?: string, user_id?: string, role?: string, is_app_admin?: boolean, login_url?: string } | null}
 */
export let currentUser = null;

/** Portal user_id for the signed-in session, or null. */
export function currentUserId() {
    const uid = currentUser?.user_id ? String(currentUser.user_id).trim() : '';
    return uid || null;
}

/** Load the portal user currently signed in (from portal_session). */
export async function loadCurrentUser() {
    const res = await fetch('/api/v1/auth/me', { credentials: 'same-origin' });
    if (res.status === 401) {
        await redirectToPortalLogin();
        throw new Error('Not authenticated');
    }
    if (!res.ok) {
        throw new Error(`Failed to load portal session: ${res.status}`);
    }
    currentUser = await res.json();
    if (currentUser && currentUser.authenticated === false) {
        await redirectToPortalLogin(currentUser.login_url);
        throw new Error('Not authenticated');
    }
    return currentUser;
}

export function showAuthRedirectMessage(message) {
    const el = document.getElementById('chat-history') || document.body;
    if (!el) return;
    el.innerHTML = `
      <div style="padding:2rem;text-align:center;max-width:28rem;margin:3rem auto;line-height:1.5">
        <p style="margin:0 0 1rem">${message || 'Opening the family portal…'}</p>
        <p style="margin:0"><a href="/admin/login?next=${encodeURIComponent('/chat/')}">Continue at portal</a>
        · <a href="/">Portal home</a></p>
      </div>`;
}

/**
 * No AI login — send the browser to the portal (login if needed, then back to /chat/).
 */
export async function redirectToPortalLogin(loginUrl) {
    let url = loginUrl;
    if (!url) {
        try {
            const res = await fetch('/api/v1/auth/me', { credentials: 'same-origin' });
            const data = await res.json().catch(() => ({}));
            url = data.login_url;
        } catch (_) { /* ignore */ }
    }
    if (!url) {
        const path = window.location.pathname.startsWith('/chat')
            ? (window.location.pathname + window.location.search)
            : '/chat/';
        url = `/admin/login?next=${encodeURIComponent(path || '/chat/')}`;
    }
    showAuthRedirectMessage('Use the family portal to continue. AI Conversation uses your portal sign-in — there is no separate app login.');
    window.location.replace(url);
}

export async function loadCatalog() {
    const res = await fetch(`${HUB_API}/catalog`, {
        credentials: 'same-origin',
        cache: 'no-store',
        headers: { Accept: 'application/json' },
    });
    if (!res) {
        throw new Error('Failed to load catalog: network blocked');
    }
    if (res.status === 401) {
        await redirectToPortalLogin();
        throw new Error('Not authenticated');
    }
    if (res.status === 403) {
        showAuthRedirectMessage('Your portal account does not have access to AI Conversation yet. Ask a family admin to grant access.');
        window.location.replace('/');
        throw new Error('No app grant');
    }
    const data = await readJsonResponse(res);
    // Mutate shared object (do not replace export binding — safer for re-exports)
    catalog.providers = Array.isArray(data.providers) ? data.providers : [];
    catalog.preferences = data.preferences && typeof data.preferences === 'object' ? data.preferences : {};
    catalog.secrets_status = Array.isArray(data.secrets_status) ? data.secrets_status : [];
    if (!catalog.providers.length) {
        console.warn(
            '[catalog] API returned zero providers. Check secrets.json / Admin keys. Raw keys:',
            Object.keys(data || {}),
        );
    }
    return catalog;
}

/**
 * Leave AI Conversation for the family portal home.
 * Prefer the Exit link (href="/") in the header — this is a fallback only.
 * Does NOT clear portal_session.
 */
export function goToPortalHome() {
    window.location.assign(`${window.location.origin}/`);
}

export function applyTheme(theme) {
    const t = theme === 'dark' ? 'dark' : 'light';
    document.documentElement.setAttribute('data-theme', t);
    const uid = currentUserId();
    if (uid) writeItem(uid, SUFFIX_THEME, t);
}

export function populateProviders(selectEl, selectedId) {
    if (!selectEl) return;
    const providers = catalog?.providers || [];
    selectEl.innerHTML = '';
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = providers.length ? 'Select AI' : 'No AIs available — open Admin Tools → keys';
    placeholder.disabled = true;
    selectEl.appendChild(placeholder);

    providers.forEach(p => {
        if (!p?.id) return;
        const opt = document.createElement('option');
        opt.value = p.id;
        opt.textContent = p.label || p.id;
        selectEl.appendChild(opt);
    });

    if (selectedId && providers.some(p => p.id === selectedId)) {
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

    const groups = { Current: [], Media: [], Voice: [], Older: [] };
    (models || []).forEach((m) => {
        if (!m?.value) return;
        const slot = inferRosterSlot(m);
        const group = SLOT_GROUP[slot] || 'Older';
        groups[group].push(m);
    });
    const slotRank = (m) => {
        const i = SLOT_ORDER.indexOf(inferRosterSlot(m));
        return i === -1 ? 99 : i;
    };
    ['Current', 'Media', 'Voice'].forEach((name) => {
        groups[name].sort((a, b) => slotRank(a) - slotRank(b));
    });

    const addOption = (parent, m) => {
        const opt = document.createElement('option');
        opt.value = m.value;
        opt.textContent = m.label || m.value;
        const desc = (m.description || m.tooltip || '').trim()
            || (m.capability ? `${m.capability} model` : 'No description available');
        const reason = (m.recommendation_reason || '').trim();
        const tip = reason ? `${desc}\n\n${reason}` : desc;
        opt.dataset.tooltip = tip;
        opt.dataset.description = desc;
        opt.dataset.tags = (m.tags || []).join(',');
        opt.title = tip;
        parent.appendChild(opt);
    };

    let usedGroups = 0;
    ['Current', 'Media', 'Voice', 'Older'].forEach((name) => {
        const list = groups[name];
        if (!list.length) return;
        usedGroups += 1;
        const og = document.createElement('optgroup');
        og.label = name;
        list.forEach((m) => addOption(og, m));
        modelSelect.appendChild(og);
    });
    if (usedGroups === 0) {
        // keep placeholder only
    }

    modelSelect.disabled = false;

    if (selectedValue && (models || []).some(m => m.value === selectedValue)) {
        modelSelect.value = selectedValue;
    }

    // Keep select.title in sync with the highlighted / selected model
    const sel = modelSelect.options[modelSelect.selectedIndex];
    modelSelect.title = (sel?.dataset?.tooltip || sel?.title || '').trim();
}

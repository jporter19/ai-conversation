// frontend/js/main.js
// Purpose: Entry point — catalog load, selectors, chat, admin, theme

import {
    DEFAULT_AI,
    DEFAULT_GROK_MODEL,
    loadCatalog,
    loadCurrentUser,
    currentUser,
    currentUserId,
    catalog,
    populateProviders,
    populateModels,
    applyTheme,
    getModelsForProvider,
    showAuthRedirectMessage,
} from './config.js';

import { loadConversation, resetConversationMemory } from './state.js';
import {
    readItem,
    writeItem,
    purgeLegacyUnscopedKeys,
    SUFFIX_AI,
    SUFFIX_MODEL,
    SUFFIX_THEME,
} from './user_storage.js';
import { renderHistory, showWelcome } from './ui.js';
import { initChat, updateComposerForCapability } from './chat.js';
// hub-ui is lazy-loaded so a blocked Admin Tools module cannot break the AI list
import { initContexts, getSelectedContextId, loadContexts } from './contexts.js';

let aiSelect;
let modelSelect;

function cacheDOMElements() {
    aiSelect = document.getElementById('ai-select');
    modelSelect = document.getElementById('model-select');
}

function setDefaultSelection() {
    if (!aiSelect) return;
    const prefs = catalog.preferences || {};
    const ai = prefs.default_ai || DEFAULT_AI;
    const model = prefs.default_model || DEFAULT_GROK_MODEL;
    populateProviders(aiSelect, ai);
    populateModels(getModelsForProvider(aiSelect.value), model);
    const uid = currentUserId();
    if (uid) {
        writeItem(uid, SUFFIX_AI, aiSelect.value);
        writeItem(uid, SUFFIX_MODEL, modelSelect.value || model);
    }
}

function onAiChange() {
    const ai = aiSelect.value;
    const models = getModelsForProvider(ai);
    const prefs = catalog?.preferences || {};
    const uid = currentUserId();
    let preferred = (uid && readItem(uid, SUFFIX_MODEL)) || prefs.default_model || '';
    if (!models.some(m => m.value === preferred)) {
        preferred = models.find(m => m.roster_slot === 'flagship_chat')?.value
            || models.find(m => (m.tags || []).includes('flagship'))?.value
            || models[0]?.value || '';
    }
    populateModels(models, preferred);
    if (uid) {
        writeItem(uid, SUFFIX_AI, ai);
        writeItem(uid, SUFFIX_MODEL, modelSelect.value || preferred || '');
    }
    updateComposerForCapability();
}

function initToolsMenu() {
    const root = document.getElementById('tools-menu');
    const btn = document.getElementById('tools-menu-btn');
    const panel = document.getElementById('tools-menu-panel');
    if (!root || !btn || !panel) return;

    const close = () => {
        panel.hidden = true;
        btn.setAttribute('aria-expanded', 'false');
    };
    const open = () => {
        panel.hidden = false;
        btn.setAttribute('aria-expanded', 'true');
    };
    const toggle = () => (panel.hidden ? open() : close());

    btn.addEventListener('click', (e) => {
        e.stopPropagation();
        toggle();
    });
    // Choosing an action closes the menu
    panel.querySelectorAll('.tools-menu-item').forEach((item) => {
        item.addEventListener('click', () => {
            // Defer close so click handlers on reset/store/admin still fire first
            setTimeout(close, 0);
        });
    });
    document.addEventListener('click', (e) => {
        if (!root.contains(e.target)) close();
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') close();
    });
}

function blankChatScreen() {
    resetConversationMemory();
    const el = document.getElementById('chat-history');
    if (el) el.innerHTML = '';
}

async function initApp() {
    blankChatScreen();
    cacheDOMElements();
    initToolsMenu();

    // Exit is a plain <a href="/"> — no JS required (portal home, keep session).
    // Force absolute origin path in case a relative base ever appears.
    const exitBtn = document.getElementById('exit-btn');
    if (exitBtn) {
        exitBtn.setAttribute('href', `${window.location.origin}/`);
    }

    purgeLegacyUnscopedKeys();

    try {
        const { mountPortalApp } = await import('/portal-assets/sdk/portal-app.js');
        const { user, denied } = await mountPortalApp({
            appId: 'ai-conversation',
            homePath: '/chat/',
        });
        if (!user || denied) return;
    } catch (e) {
        const msg = String(e?.message || e);
        if (msg.includes('Failed to fetch') || msg.includes('error loading dynamically imported module')) {
            window.location.replace('/admin/login?next=' + encodeURIComponent('/chat/'));
            return;
        }
        console.warn('portal chrome unavailable', e);
    }

    // Product identity stays /api/v1/auth/me (is_app_admin, hub). Do not use portal /me for that.
    try {
        await loadCurrentUser();
        await loadCatalog();
    } catch (e) {
        console.error('Portal session/catalog load failed', e);
        const msg = String(e.message || e);
        if (msg.includes('Not authenticated') || msg.includes('grant') || msg.includes('No access')) {
            showAuthRedirectMessage('Continue from the family portal…');
            return;
        }
        showWelcome();
        initChat();
        initContexts();
        return;
    }

    // Show portal username (no separate AI account)
    const userLabel = document.getElementById('user-label');
    if (userLabel && currentUser?.username) {
        userLabel.textContent = currentUser.username;
        userLabel.hidden = false;
        userLabel.title = `Portal user ${currentUser.user_id || ''}`.trim();
    }
    // Admin Tools: app grant admin, portal admin, or AUTH_DISABLED
    const isAppAdmin = Boolean(
        currentUser?.is_app_admin
        || currentUser?.is_portal_admin
        || currentUser?.auth_disabled
        || currentUser?.role === 'admin'
    );
    const adminBtn = document.getElementById('admin-btn');
    if (adminBtn && !isAppAdmin) {
        adminBtn.hidden = true;
        adminBtn.disabled = true;
    }

    const prefs = catalog?.preferences || {};
    const uid = currentUserId();
    const localTheme = uid ? readItem(uid, SUFFIX_THEME) : null;
    applyTheme(localTheme || prefs.theme || 'light');

    loadConversation(renderHistory, showWelcome);
    initIdentityWatch();
    initChat();
    // Lazy-load Admin Tools UI (path must not contain "admin" — Brave blocks those URLs)
    if (isAppAdmin) {
        import('./hub-ui.js')
            .then((m) => m.initAdmin())
            .catch((err) => console.error('[init] Admin Tools module failed to load', err));
    }
    initContexts();
    loadContexts().catch(() => {});

    if (!(catalog?.providers || []).length) {
        console.error('[init] Catalog loaded with 0 providers — check /api/v1/hub/catalog and secrets.json');
    }

    aiSelect.addEventListener('change', onAiChange);
    modelSelect.addEventListener('change', () => {
        const id = currentUserId();
        if (id) writeItem(id, SUFFIX_MODEL, modelSelect.value || '');
        updateComposerForCapability();
    });

    const savedAI = uid ? readItem(uid, SUFFIX_AI) : null;
    if (!savedAI) {
        setDefaultSelection();
    } else {
        populateProviders(aiSelect, savedAI);
        if (!aiSelect.value) {
            setDefaultSelection();
        } else {
            const models = getModelsForProvider(aiSelect.value);
            const savedModel = uid ? readItem(uid, SUFFIX_MODEL) : null;
            const valid = models.some(m => m.value === savedModel);
            populateModels(models, valid ? savedModel : (models[0]?.value || ''));
        }
    }
    updateComposerForCapability();
}

/**
 * If the portal user changes while this tab is cached (bfcache / another login),
 * drop in-memory chat and reload so we never send the previous user's messages.
 */
function initIdentityWatch() {
    const expected = currentUserId();
    if (!expected) return;

    let checking = false;
    const check = async () => {
        if (checking) return;
        checking = true;
        try {
            const res = await fetch('/api/v1/auth/me', {
                credentials: 'same-origin',
                cache: 'no-store',
            });
            const data = await res.json().catch(() => ({}));
            const now = (data.user_id || '').trim();
            if (!data.authenticated || !now || now !== expected) {
                blankChatScreen();
                window.location.reload();
            }
        } catch {
            /* ignore transient errors */
        } finally {
            checking = false;
        }
    };

    window.addEventListener('pageshow', (e) => {
        if (e.persisted) check();
    });
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') check();
    });
}

document.addEventListener('DOMContentLoaded', initApp);

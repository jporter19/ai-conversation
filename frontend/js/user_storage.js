// frontend/js/user_storage.js
// Purpose: Per-portal-user localStorage. Never restore another user's live chat.

export const PORTAL_UID_KEY = 'portal_uid';
export const PORTAL_LOGIN_UID_KEY = 'portal_login_uid';
export const SHOWN_UID_KEY = 'ai-hub:shown-uid';

/** Pre-isolation keys shared across all users on porterfamily.us — delete, never migrate. */
export const LEGACY_UNSCOPED_KEYS = [
    'ai-conversation-hub-current-chat',
    'ai-conversation-hub-selected-ai',
    'ai-conversation-hub-selected-model',
    'ai-conversation-hub-theme',
    'ai-conversation-hub-selected-context',
];

export const SUFFIX_CHAT = 'chat';
export const SUFFIX_AI = 'ai';
export const SUFFIX_MODEL = 'model';
export const SUFFIX_THEME = 'theme';
export const SUFFIX_CONTEXT = 'context';

/**
 * @param {string} userId
 * @param {string} name
 * @returns {string}
 */
export function storageKey(userId, name) {
    const uid = String(userId || '').trim();
    const suffix = String(name || '').trim();
    if (!uid) {
        throw new Error('user_id required for storage key');
    }
    if (!suffix || suffix.includes(':')) {
        throw new Error('invalid storage suffix');
    }
    return `ai-hub:${uid}:${suffix}`;
}

export function purgeLegacyUnscopedKeys() {
    for (const key of LEGACY_UNSCOPED_KEYS) {
        try {
            localStorage.removeItem(key);
        } catch {
            /* ignore quota / private mode */
        }
    }
}

/**
 * Delete live-chat bodies that are not keepUserId's.
 * Empty keepUserId deletes every ai-hub:*:chat key (logout).
 * @param {string|null|undefined} keepUserId
 */
export function wipeForeignLiveChats(keepUserId) {
    const keep = String(keepUserId || '').trim();
    const toRemove = [];
    try {
        toRemove.push(...LEGACY_UNSCOPED_KEYS);
        for (let i = 0; i < localStorage.length; i++) {
            const key = localStorage.key(i);
            if (!key) continue;
            const m = /^ai-hub:(.+):chat$/.exec(key);
            if (m && (!keep || m[1] !== keep)) {
                toRemove.push(key);
            }
        }
        for (const key of toRemove) {
            localStorage.removeItem(key);
        }
        if (!keep) localStorage.removeItem(SHOWN_UID_KEY);
    } catch {
        /* ignore */
    }
}

export function lastShownUserId() {
    try {
        return (localStorage.getItem(SHOWN_UID_KEY) || '').trim() || null;
    } catch {
        return null;
    }
}

export function setLastShownUserId(userId) {
    const uid = String(userId || '').trim();
    try {
        if (uid) localStorage.setItem(SHOWN_UID_KEY, uid);
        else localStorage.removeItem(SHOWN_UID_KEY);
    } catch {
        /* ignore */
    }
}

export function loginUidHint() {
    try {
        return (sessionStorage.getItem(PORTAL_LOGIN_UID_KEY) || '').trim() || null;
    } catch {
        return null;
    }
}

/**
 * Restore a live draft only when this browser already painted this same user.
 * A portal login / user switch must start from a blank canvas.
 */
export function shouldRestoreLiveChat(userId) {
    const uid = String(userId || '').trim();
    if (!uid) return false;
    const shown = lastShownUserId();
    if (!shown || shown !== uid) return false;
    const login = loginUidHint();
    if (login && login !== uid) return false;
    return true;
}

export function hintPortalUid() {
    try {
        return (localStorage.getItem(PORTAL_UID_KEY) || '').trim() || null;
    } catch {
        return null;
    }
}

/**
 * @param {string|null|undefined} userId
 * @param {string} name
 * @returns {string|null}
 */
export function readItem(userId, name) {
    const uid = String(userId || '').trim();
    if (!uid) return null;
    try {
        return localStorage.getItem(storageKey(uid, name));
    } catch {
        return null;
    }
}

/**
 * @param {string|null|undefined} userId
 * @param {string} name
 * @param {string} value
 */
export function writeItem(userId, name, value) {
    const uid = String(userId || '').trim();
    if (!uid) return;
    try {
        localStorage.setItem(storageKey(uid, name), value);
    } catch (e) {
        console.warn('[user_storage] write failed:', e);
    }
}

/**
 * @param {string|null|undefined} userId
 * @param {string} name
 */
export function removeItem(userId, name) {
    const uid = String(userId || '').trim();
    if (!uid) return;
    try {
        localStorage.removeItem(storageKey(uid, name));
    } catch {
        /* ignore */
    }
}

/**
 * Parse a live-chat payload. Refuse mismatched owner. Never treat an unscoped
 * raw array as belonging to this user (callers must not pass unscoped blobs).
 * A raw array is accepted only when it came from this user's namespaced key
 * (legacy format written after namespacing but before the envelope).
 *
 * @param {string|null} raw
 * @param {string} userId
 * @param {{allowBareArray?: boolean}} [opts]
 * @returns {Array}
 */
export function parseLiveChat(raw, userId, opts = {}) {
    const uid = String(userId || '').trim();
    if (!uid || !raw) return [];
    try {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) {
            return opts.allowBareArray ? parsed : [];
        }
        if (
            parsed
            && typeof parsed === 'object'
            && parsed.user_id === uid
            && Array.isArray(parsed.messages)
        ) {
            return parsed.messages;
        }
        return [];
    } catch {
        return [];
    }
}

export function serializeLiveChat(userId, messages) {
    return JSON.stringify({
        user_id: String(userId || '').trim(),
        messages: Array.isArray(messages) ? messages : [],
    });
}

export function readLiveChat(userId) {
    const uid = String(userId || '').trim();
    if (!uid) return [];
    // Bare arrays under THIS user's key are this user's old format, not a leak.
    return parseLiveChat(readItem(uid, SUFFIX_CHAT), uid, { allowBareArray: true });
}

export function writeLiveChat(userId, messages) {
    const uid = String(userId || '').trim();
    if (!uid) return;
    writeItem(uid, SUFFIX_CHAT, serializeLiveChat(uid, messages));
}

export function clearLiveChat(userId) {
    removeItem(userId, SUFFIX_CHAT);
}

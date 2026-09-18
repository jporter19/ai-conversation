// frontend/js/http.js — JSON fetch helper (never JSON.parse HTML error pages).

const JSON_TIMEOUT_MS = 120_000;

export async function readJsonResponse(res) {
    const ct = (res.headers.get('content-type') || '').toLowerCase();
    const text = await res.text();
    const snippet = (text || '').slice(0, 120).replace(/\s+/g, ' ').trim();
    if (!ct.includes('application/json')) {
        if (/^\s*</.test(text) || /<!DOCTYPE/i.test(text)) {
            throw new Error(
                `The server returned a page instead of data (HTTP ${res.status}). `
                + 'This is often a timeout, a login redirect, or Brave Shields blocking a URL that contains /admin/.',
            );
        }
        throw new Error(`Unexpected response (HTTP ${res.status}): ${snippet || 'empty body'}`);
    }
    let data = {};
    try {
        data = text ? JSON.parse(text) : {};
    } catch (_) {
        throw new Error(`Invalid JSON (HTTP ${res.status})`);
    }
    if (!res.ok) {
        const detail = data.detail || data.message || data.error;
        const msg = typeof detail === 'string'
            ? detail
            : (detail ? JSON.stringify(detail) : `Request failed (HTTP ${res.status})`);
        throw new Error(msg);
    }
    return data;
}

export async function hubFetch(url, options = {}) {
    const controller = new AbortController();
    const { timeoutMs = JSON_TIMEOUT_MS, signal, ...fetchOpts } = options;
    const t = setTimeout(() => controller.abort(), timeoutMs);
    try {
        const res = await fetch(url, {
            credentials: 'same-origin',
            cache: 'no-store',
            ...fetchOpts,
            signal: signal || controller.signal,
            headers: {
                Accept: 'application/json',
                ...(fetchOpts.headers || {}),
            },
        });
        return await readJsonResponse(res);
    } catch (e) {
        if (e?.name === 'AbortError') {
            throw new Error('The request timed out. Try again. Auto-Update should finish in a few seconds.');
        }
        throw e;
    } finally {
        clearTimeout(t);
    }
}

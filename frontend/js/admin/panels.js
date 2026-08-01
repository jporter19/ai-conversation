// frontend/js/admin/panels.js — models, keys, prefs, providers panels
import {
    catalog,
    setStatus,
    escapeHtml,
    refreshCatalogUI,
    DEFAULT_AI,
} from './shared.js';

export function renderModelsAdmin() {
    const list = document.getElementById('admin-models-list');
    const providerSelect = document.getElementById('admin-model-provider');
    if (!list || !providerSelect || !catalog) return;

    const current = providerSelect.value;
    providerSelect.innerHTML = '';
    (catalog.providers || []).forEach(p => {
        const opt = document.createElement('option');
        opt.value = p.id;
        opt.textContent = p.label;
        providerSelect.appendChild(opt);
    });
    if (current && [...providerSelect.options].some(o => o.value === current)) {
        providerSelect.value = current;
    }

    const provider = catalog.providers.find(p => p.id === providerSelect.value);
    list.innerHTML = '';
    if (!provider) {
        list.innerHTML = '<p class="admin-muted">No API selected.</p>';
        return;
    }

    (provider.models || []).forEach(m => {
        const row = document.createElement('div');
        row.className = 'admin-row';
        row.innerHTML = `
            <div class="admin-row-main">
                <strong>${escapeHtml(m.label || m.value)}</strong>
                <code>${escapeHtml(m.value)}</code>
                <span class="admin-tag">${escapeHtml(m.capability || 'chat')}</span>
            </div>
            <button type="button" class="modal-btn secondary admin-row-remove"
                data-provider="${escapeHtml(provider.id)}" data-model="${escapeHtml(m.value)}">Remove</button>
        `;
        list.appendChild(row);
    });

    list.querySelectorAll('.admin-row-remove').forEach(btn => {
        btn.addEventListener('click', async () => {
            const pid = btn.dataset.provider;
            const mid = btn.dataset.model;
            if (!confirm(`Remove model ${mid}?`)) return;
            try {
                const res = await fetch(
                    `/api/v1/admin/providers/${encodeURIComponent(pid)}/models/${encodeURIComponent(mid)}`,
                    { method: 'DELETE' },
                );
                if (!res.ok) throw new Error(await res.text());
                setStatus(`Removed ${mid}`);
                await refreshCatalogUI();
            } catch (e) {
                setStatus(String(e.message || e), true);
            }
        });
    });
}

// ── Keys tab ──────────────────────────────────────────────────────────────────

export function renderKeysAdmin() {
    const container = document.getElementById('admin-keys-list');
    if (!container || !catalog) return;
    container.innerHTML = '';

    (catalog.secrets_status || []).forEach(s => {
        const providerNames = (s.providers || []).map(p => p.label).join(', ');
        const optional = !!s.optional;
        const row = document.createElement('div');
        row.className = 'admin-key-row';
        row.innerHTML = `
            <label>
                <span class="admin-key-name">
                    ${escapeHtml(s.label || s.name)}
                    <code class="admin-key-code">${escapeHtml(s.name)}</code>
                </span>
                <span class="admin-key-status ${s.configured ? 'ok' : (optional ? 'optional' : 'missing')}"
                      data-status-for="${escapeHtml(s.name)}">
                    ${s.configured
                        ? `Configured (${escapeHtml(s.hint || '••••')})`
                        : (optional ? 'Optional — not set' : 'Required — not set')}
                </span>
            </label>
            ${providerNames ? `<p class="admin-key-providers">Used by: ${escapeHtml(providerNames)}</p>` : ''}
            ${optional ? '<p class="admin-muted admin-key-hint">YouTube public captions work without a key.</p>' : ''}
            <div class="admin-key-actions">
                <input type="password" class="admin-key-input" data-key="${escapeHtml(s.name)}"
                       placeholder="${s.configured ? 'Enter new key to replace…' : 'Paste API key…'}"
                       autocomplete="off" spellcheck="false">
                <button type="button" class="modal-btn secondary admin-test-key-btn" data-key="${escapeHtml(s.name)}">
                    Test key
                </button>
            </div>
            <p class="admin-key-test-result" data-result-for="${escapeHtml(s.name)}" hidden></p>
        `;
        container.appendChild(row);
    });

    container.querySelectorAll('.admin-test-key-btn').forEach(btn => {
        btn.addEventListener('click', () => testKey(btn.dataset.key, { buttonEl: btn }));
    });
}

/**
 * Dry-run key probe. Never persists providers or secrets.
 * Call as testKey(name, { buttonEl, apiKey, baseUrl, model, label, keyTest, ... })
 */
export async function testKey(keyName, opts = {}) {
    const buttonEl = opts.buttonEl;
    const input = opts.inputEl
        || document.querySelector(`.admin-key-input[data-key="${CSS.escape(keyName)}"]`);
    const result = opts.resultEl
        || document.querySelector(`.admin-key-test-result[data-result-for="${CSS.escape(keyName)}"]`);
    const pasted = (opts.apiKey != null ? opts.apiKey : (input?.value || '')).trim();

    if (buttonEl) {
        buttonEl.disabled = true;
        buttonEl.textContent = 'Testing…';
    }
    if (result) {
        result.hidden = false;
        result.className = 'admin-key-test-result pending';
        result.textContent = 'Contacting provider… (not saving)';
    }
    setStatus(`Testing ${keyName}… (dry-run, nothing saved)`);

    try {
        const body = {
            key_name: keyName,
            api_key: pasted || null,
        };
        if (opts.baseUrl) body.base_url = opts.baseUrl;
        if (opts.model) body.model = opts.model;
        if (opts.label) body.label = opts.label;
        if (opts.keyTest) body.key_test = opts.keyTest;

        const res = await fetch('/api/v1/admin/setup/test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const data = await res.json();
        const ok = !!data.ok;
        const msg = data.message || (ok ? 'OK' : 'Failed');
        if (result) {
            result.className = `admin-key-test-result ${ok ? 'ok' : 'fail'}`;
            result.textContent = msg;
        }
        setStatus(msg, !ok);
        return data;
    } catch (e) {
        const msg = String(e.message || e);
        if (result) {
            result.className = 'admin-key-test-result fail';
            result.textContent = msg;
        }
        setStatus(msg, true);
        return { ok: false, message: msg };
    } finally {
        if (buttonEl) {
            buttonEl.disabled = false;
            buttonEl.textContent = 'Test key';
        }
    }
}

// ── Preferences ───────────────────────────────────────────────────────────────

export function renderPrefsAdmin() {
    const themeSelect = document.getElementById('admin-theme');
    const defaultAi = document.getElementById('admin-default-ai');
    if (!catalog) return;
    const prefs = catalog.preferences || {};
    if (themeSelect) themeSelect.value = prefs.theme || 'light';
    if (defaultAi) {
        defaultAi.innerHTML = '';
        (catalog.providers || []).forEach(p => {
            const opt = document.createElement('option');
            opt.value = p.id;
            opt.textContent = p.label;
            defaultAi.appendChild(opt);
        });
        defaultAi.value = prefs.default_ai || DEFAULT_AI;
    }
}

// ── My APIs ───────────────────────────────────────────────────────────────────

export function renderProvidersAdmin() {
    const list = document.getElementById('admin-providers-list');
    if (!list || !catalog) return;
    list.innerHTML = '<p class="admin-muted">Loading…</p>';

    fetch('/api/v1/admin/providers')
        .then(r => r.json())
        .then(data => {
            list.innerHTML = '';
            const secrets = Object.fromEntries(
                (catalog.secrets_status || []).map(s => [s.name, s]),
            );
            const providers = data.providers || [];
            if (!providers.length) {
                list.innerHTML = '<p class="admin-muted">No APIs configured. Use <strong>Add API</strong> to add one.</p>';
                return;
            }
            providers.forEach(p => {
                const keyName = p.api_key_name;
                const keyInfo = keyName ? secrets[keyName] : null;
                const optional = !!p.api_key_optional || p.type === 'tool';
                const disabled = p.enabled === false;
                let keyBadge;
                if (!keyName) {
                    keyBadge = '<span class="admin-tag">no key field</span>';
                } else if (keyInfo?.configured) {
                    keyBadge = `<span class="admin-tag tag-ok">key set</span>`;
                } else if (optional) {
                    keyBadge = `<span class="admin-tag tag-optional">key optional</span>`;
                } else {
                    keyBadge = `<span class="admin-tag tag-missing">key missing</span>`;
                }

                const row = document.createElement('div');
                row.className = `admin-row admin-provider-row${disabled ? ' is-disabled' : ''}`;
                row.innerHTML = `
                    <div class="admin-row-main">
                        <strong>${escapeHtml(p.label)}</strong>
                        <code>${escapeHtml(p.id)}</code>
                        <span class="admin-tag">${escapeHtml(p.type || '')}</span>
                        <span class="admin-tag">${(p.models || []).length} models</span>
                        <span class="admin-tag ${disabled ? 'tag-missing' : 'tag-ok'}">${disabled ? 'hidden from AI list' : 'in AI list'}</span>
                        ${keyBadge}
                        ${keyName ? `<code class="admin-key-code">${escapeHtml(keyName)}</code>` : ''}
                        ${p.base_url ? `<code class="admin-base-url" title="Base URL">${escapeHtml(p.base_url)}</code>` : ''}
                        ${optional && p.id === 'youtube'
                            ? '<p class="admin-muted">Works without a key for public video captions.</p>'
                            : ''}
                    </div>
                    <div class="restore-row-actions provider-actions">
                        ${keyName ? `<button type="button" class="modal-btn secondary provider-set-key-btn"
                            data-key="${escapeHtml(keyName)}" data-label="${escapeHtml(p.label)}">Set / test key</button>` : ''}
                        ${disabled
                            ? `<button type="button" class="modal-btn primary provider-enable-btn"
                                data-id="${escapeHtml(p.id)}" data-label="${escapeHtml(p.label)}">Enable</button>`
                            : `<button type="button" class="modal-btn secondary provider-remove-btn"
                                data-id="${escapeHtml(p.id)}" data-label="${escapeHtml(p.label)}">Remove from list</button>`
                        }
                        ${!['grok', 'chatgpt'].includes(p.id)
                            ? `<button type="button" class="modal-btn secondary provider-delete-btn"
                                data-id="${escapeHtml(p.id)}" data-label="${escapeHtml(p.label)}"
                                title="Permanently delete this API">Delete forever</button>`
                            : ''}
                    </div>
                `;
                list.appendChild(row);
            });

            list.querySelectorAll('.provider-set-key-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    switchTab('keys');
                    const key = btn.dataset.key;
                    const input = document.querySelector(`.admin-key-input[data-key="${CSS.escape(key)}"]`);
                    input?.focus();
                    setStatus(`Paste the key for ${btn.dataset.label} (${key}), then Test / Save.`);
                });
            });

            list.querySelectorAll('.provider-remove-btn').forEach(btn => {
                btn.addEventListener('click', async () => {
                    const id = btn.dataset.id;
                    const label = btn.dataset.label;
                    if (!confirm(`Remove “${label}” from the main AI dropdown?\n\nIt will be disabled (not permanently deleted). You can Enable it again later.`)) {
                        return;
                    }
                    try {
                        const res = await fetch(`/api/v1/admin/providers/${encodeURIComponent(id)}`, {
                            method: 'DELETE',
                        });
                        const data = await res.json().catch(() => ({}));
                        if (!res.ok) throw new Error(data.detail || 'Remove failed');
                        setStatus(`Removed “${label}” from the AI list.`);
                        await refreshCatalogUI();
                    } catch (e) {
                        setStatus(String(e.message || e), true);
                    }
                });
            });

            list.querySelectorAll('.provider-enable-btn').forEach(btn => {
                btn.addEventListener('click', async () => {
                    const id = btn.dataset.id;
                    const label = btn.dataset.label;
                    try {
                        const res = await fetch(`/api/v1/admin/providers/${encodeURIComponent(id)}/enable`, {
                            method: 'POST',
                        });
                        const data = await res.json().catch(() => ({}));
                        if (!res.ok) throw new Error(data.detail || 'Enable failed');
                        setStatus(`Enabled “${label}” — it is back in the AI list.`);
                        await refreshCatalogUI();
                    } catch (e) {
                        setStatus(String(e.message || e), true);
                    }
                });
            });

            list.querySelectorAll('.provider-delete-btn').forEach(btn => {
                btn.addEventListener('click', async () => {
                    const id = btn.dataset.id;
                    const label = btn.dataset.label;
                    if (!confirm(`Permanently delete “${label}” (${id})?\n\nThis cannot be undone (you can re-add via Add API).`)) {
                        return;
                    }
                    try {
                        const res = await fetch(
                            `/api/v1/admin/providers/${encodeURIComponent(id)}?hard=true`,
                            { method: 'DELETE' },
                        );
                        const data = await res.json().catch(() => ({}));
                        if (!res.ok) throw new Error(data.detail || 'Delete failed');
                        setStatus(`Deleted “${label}”.`);
                        await refreshCatalogUI();
                    } catch (e) {
                        setStatus(String(e.message || e), true);
                    }
                });
            });
        })
        .catch(e => {
            list.innerHTML = `<p class="admin-muted">Failed to load APIs: ${escapeHtml(e.message || e)}</p>`;
        });
}


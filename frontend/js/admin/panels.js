// frontend/js/admin/panels.js — models, keys, prefs, providers panels
import {
    catalog,
    setStatus,
    escapeHtml,
    refreshCatalogUI,
    DEFAULT_AI,
    switchTab,
} from './shared.js';

/** Secrets map name → status row */
function secretsMap() {
    return Object.fromEntries(
        (catalog?.secrets_status || []).map(s => [s.name, s]),
    );
}

function providerKeyActive(p, secrets) {
    if (!p) return false;
    if (p.api_key_optional || p.type === 'tool') return true;
    const kn = p.api_key_name;
    if (!kn) return true;
    return !!(secrets[kn]?.configured);
}

// ── Models tab ────────────────────────────────────────────────────────────────

export function renderModelsAdmin() {
    const list = document.getElementById('admin-models-list');
    const providerSelect = document.getElementById('admin-model-provider');
    if (!list || !providerSelect || !catalog) return;

    const secrets = secretsMap();
    // Models for active (keyed) providers only — same set as My APIs
    const activeProviders = (catalog.providers || []).filter(p => providerKeyActive(p, secrets));

    const current = providerSelect.value;
    providerSelect.innerHTML = '';
    if (!activeProviders.length) {
        providerSelect.innerHTML = '<option value="">No APIs with keys</option>';
        list.innerHTML = '<p class="admin-muted">Add an API with a key first (Add API tab). Then all of its models appear here.</p>';
        return;
    }
    activeProviders.forEach(p => {
        const opt = document.createElement('option');
        opt.value = p.id;
        opt.textContent = p.label;
        providerSelect.appendChild(opt);
    });
    if (current && [...providerSelect.options].some(o => o.value === current)) {
        providerSelect.value = current;
    }

    const provider = activeProviders.find(p => p.id === providerSelect.value)
        || activeProviders[0];
    if (provider && providerSelect.value !== provider.id) {
        providerSelect.value = provider.id;
    }

    list.innerHTML = '';
    if (!provider) {
        list.innerHTML = '<p class="admin-muted">No API selected.</p>';
        return;
    }

    const models = provider.models || [];
    if (!models.length) {
        list.innerHTML = '<p class="admin-muted">No models yet. Run <strong>Auto-Update</strong> or add a model below.</p>';
    }

    // Sort: keep → review → remove (matches backend), flagship first within keep
    const recOrder = { keep: 0, review: 1, remove: 2 };
    const sorted = [...models].sort((a, b) => {
        const ra = recOrder[a.recommendation] ?? 1;
        const rb = recOrder[b.recommendation] ?? 1;
        if (ra !== rb) return ra - rb;
        const ta = a.tags || [];
        const tb = b.tags || [];
        const fa = ta.includes('flagship') ? 0 : 1;
        const fb = tb.includes('flagship') ? 0 : 1;
        if (fa !== fb) return fa - fb;
        return String(a.label || a.value).localeCompare(String(b.label || b.value));
    });

    const removeCount = sorted.filter(m => m.recommendation === 'remove').length;
    if (removeCount > 0) {
        const ban = document.createElement('div');
        ban.className = 'admin-rec-banner';
        ban.innerHTML = `
            <p><strong>${removeCount}</strong> model(s) recommended for removal
            (superseded / redundant). Specialized models and one cheap+effective chat model are kept.</p>
            <button type="button" class="modal-btn secondary" id="admin-apply-removals-btn"
                data-provider="${escapeHtml(provider.id)}">Remove recommended</button>
        `;
        list.appendChild(ban);
        ban.querySelector('#admin-apply-removals-btn')?.addEventListener('click', async () => {
            if (!confirm(`Remove ${removeCount} recommended model(s) from ${provider.label}?`)) return;
            try {
                const res = await fetch('/api/v1/admin/models/recommend', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        provider_id: provider.id,
                        use_ai: false,
                        apply_removals: true,
                    }),
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || 'Apply removals failed');
                setStatus(`Removed ${(data.removed || []).length} model(s).`);
                await refreshCatalogUI();
            } catch (e) {
                setStatus(String(e.message || e), true);
            }
        });
    }

    sorted.forEach(m => {
        const row = document.createElement('div');
        const rec = m.recommendation || '';
        row.className = `admin-row admin-model-row${rec === 'remove' ? ' is-remove' : ''}${rec === 'keep' ? ' is-keep' : ''}`;
        const desc = (m.description || m.tooltip || '').trim();
        const recReason = (m.recommendation_reason || '').trim();
        const modelTags = (m.tags || []).map(t => {
            const cls = t === 'flagship' || t === 'cheap' || t === 'specialized'
                ? 'tag-ok'
                : (t === 'legacy' ? 'tag-missing' : '');
            return `<span class="admin-tag model-tag ${cls}">${escapeHtml(t)}</span>`;
        }).join('');
        const recBadge = rec
            ? `<span class="admin-tag rec-tag rec-${escapeHtml(rec)}">${escapeHtml(rec)}</span>`
            : '';
        const tags = [
            `<span class="admin-tag">${escapeHtml(m.capability || 'chat')}</span>`,
            modelTags,
            recBadge,
            m.manual ? '<span class="admin-tag">manual</span>' : '',
        ].filter(Boolean).join(' ');
        row.title = [desc, recReason].filter(Boolean).join(' — ')
            || 'No description yet — run Refresh model descriptions';
        row.innerHTML = `
            <div class="admin-row-main">
                <strong title="${escapeHtml(desc)}">${escapeHtml(m.label || m.value)}</strong>
                <code title="${escapeHtml(desc)}">${escapeHtml(m.value)}</code>
                ${tags}
                ${desc
                    ? `<p class="admin-model-desc" title="${escapeHtml(desc)}">${escapeHtml(desc)}</p>`
                    : '<p class="admin-muted admin-model-desc">No description yet</p>'}
                ${recReason
                    ? `<p class="admin-rec-reason rec-${escapeHtml(rec || 'review')}">${escapeHtml(recReason)}</p>`
                    : ''}
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

    // Only keys that belong to an existing provider (API Keys = update, not invent)
    const rows = (catalog.secrets_status || []).filter(s => (s.providers || []).length > 0);
    if (!rows.length) {
        container.innerHTML = '<p class="admin-muted">No APIs yet. Use <strong>Add API</strong> to add one — its key slot will show up here.</p>';
        return;
    }

    rows.forEach(s => {
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
                        ? `Active (${escapeHtml(s.hint || '••••')})`
                        : (optional ? 'Optional — not set' : 'No key — paste to activate')}
                </span>
            </label>
            ${providerNames ? `<p class="admin-key-providers">API: ${escapeHtml(providerNames)}</p>` : ''}
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
            const secrets = secretsMap();
            const all = data.providers || [];
            // My APIs = enabled providers with an active key (or key-optional tools)
            const shown = all.filter(p => {
                if (p.enabled === false) return false;
                if (p.api_key_optional || p.type === 'tool') return true;
                const kn = p.api_key_name;
                if (!kn) return true;
                return !!(secrets[kn]?.configured);
            });

            if (!shown.length) {
                list.innerHTML = `
                    <p class="admin-muted">
                        No APIs with an active key yet.
                        Use <strong>Add API</strong> (e.g. type <em>add ChatGPT</em>), paste a key, and click Find &amp; add.
                    </p>`;
                return;
            }

            shown.forEach(p => {
                const keyName = p.api_key_name;
                const keyInfo = keyName ? secrets[keyName] : null;
                const optional = !!p.api_key_optional || p.type === 'tool';
                const nModels = (p.models || []).length;
                let keyBadge;
                if (!keyName) {
                    keyBadge = '<span class="admin-tag">no key field</span>';
                } else if (keyInfo?.configured) {
                    keyBadge = '<span class="admin-tag tag-ok">active key</span>';
                } else if (optional) {
                    keyBadge = '<span class="admin-tag tag-optional">key optional</span>';
                } else {
                    keyBadge = '<span class="admin-tag tag-missing">key missing</span>';
                }

                const row = document.createElement('div');
                row.className = 'admin-row admin-provider-row';
                row.innerHTML = `
                    <div class="admin-row-main">
                        <strong>${escapeHtml(p.label)}</strong>
                        <code>${escapeHtml(p.id)}</code>
                        <span class="admin-tag">${nModels} models</span>
                        ${keyBadge}
                        ${p.auto_update ? '<span class="admin-tag tag-ok">auto-update</span>' : ''}
                        ${keyName ? `<code class="admin-key-code">${escapeHtml(keyName)}</code>` : ''}
                    </div>
                    <div class="restore-row-actions provider-actions">
                        ${keyName ? `<button type="button" class="modal-btn secondary provider-set-key-btn"
                            data-key="${escapeHtml(keyName)}" data-label="${escapeHtml(p.label)}">Update key</button>` : ''}
                        <button type="button" class="modal-btn secondary provider-models-btn"
                            data-id="${escapeHtml(p.id)}">Models</button>
                        <button type="button" class="modal-btn secondary provider-delete-btn"
                            data-id="${escapeHtml(p.id)}" data-label="${escapeHtml(p.label)}"
                            title="Permanently delete this API and its key if unused">Remove</button>
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
                    setStatus(`Update the key for ${btn.dataset.label}, then Save API Keys.`);
                });
            });

            list.querySelectorAll('.provider-models-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    switchTab('models');
                    const sel = document.getElementById('admin-model-provider');
                    if (sel) {
                        sel.value = btn.dataset.id;
                        renderModelsAdmin();
                    }
                });
            });

            list.querySelectorAll('.provider-delete-btn').forEach(btn => {
                btn.addEventListener('click', async () => {
                    const id = btn.dataset.id;
                    const label = btn.dataset.label;
                    if (!confirm(
                        `Remove “${label}” completely?\n\n`
                        + `This deletes the API from My APIs, its models, and its stored key `
                        + `(if nothing else uses that key). You can re-add later via Add API.`,
                    )) {
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

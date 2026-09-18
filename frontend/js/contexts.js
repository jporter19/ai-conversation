// frontend/js/contexts.js — header Context dropdown + manage modal CRUD

import { currentUserId } from './config.js';
import { readItem, writeItem, removeItem, SUFFIX_CONTEXT } from './user_storage.js';

/** @type {Array<{id:string,name:string,description?:string,content:string}>} */
let contextsCache = [];

function escapeHtml(str) {
    return String(str ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function setModalStatus(msg, isError = false) {
    const el = document.getElementById('context-modal-status');
    if (!el) return;
    if (!msg) {
        el.hidden = true;
        el.textContent = '';
        return;
    }
    el.hidden = false;
    el.textContent = msg;
    el.classList.toggle('error', !!isError);
}

export function getSelectedContextId() {
    const sel = document.getElementById('context-select');
    return (sel?.value || '').trim();
}

export function getSelectedContext() {
    const id = getSelectedContextId();
    if (!id) return null;
    return contextsCache.find(c => c.id === id) || null;
}

export function populateContextSelect(selectedId) {
    const sel = document.getElementById('context-select');
    if (!sel) return;
    const want = selectedId != null
        ? selectedId
        : (readItem(currentUserId(), SUFFIX_CONTEXT) || sel.value || '');

    sel.innerHTML = '';
    const none = document.createElement('option');
    none.value = '';
    none.textContent = 'None';
    none.title = 'No extra persona or guidelines';
    sel.appendChild(none);

    contextsCache.forEach(c => {
        const opt = document.createElement('option');
        opt.value = c.id;
        opt.textContent = c.name || c.id;
        opt.title = c.description || (c.content || '').slice(0, 160);
        sel.appendChild(opt);
    });

    if (want && contextsCache.some(c => c.id === want)) {
        sel.value = want;
    } else {
        sel.value = '';
    }
    writeItem(currentUserId(), SUFFIX_CONTEXT, sel.value || '');
    updateContextSelectTitle();
}

function updateContextSelectTitle() {
    const sel = document.getElementById('context-select');
    if (!sel) return;
    const c = getSelectedContext();
    if (!c) {
        sel.title = 'No context — model uses default behavior';
        return;
    }
    const bits = [c.name, c.description, (c.content || '').slice(0, 200)].filter(Boolean);
    sel.title = bits.join(' — ');
}

export async function loadContexts() {
    const res = await fetch('/api/v1/contexts', { credentials: 'same-origin' });
    if (res.status === 401 || res.status === 403) {
        const { redirectToPortalLogin } = await import('./config.js');
        await redirectToPortalLogin();
        throw new Error('Not authenticated');
    }
    if (!res.ok) throw new Error(`Failed to load contexts: ${res.status}`);
    const data = await res.json();
    contextsCache = data.contexts || [];
    populateContextSelect();
    return contextsCache;
}

function renderContextList(selectedId) {
    const list = document.getElementById('context-list');
    if (!list) return;
    list.innerHTML = '';
    if (!contextsCache.length) {
        list.innerHTML = '<p class="admin-muted">No contexts yet. Create one on the right.</p>';
        return;
    }
    contextsCache.forEach(c => {
        const row = document.createElement('button');
        row.type = 'button';
        row.className = `admin-row context-list-item${c.id === selectedId ? ' is-selected' : ''}`;
        row.dataset.id = c.id;
        row.innerHTML = `
            <div class="admin-row-main">
                <strong>${escapeHtml(c.name)}</strong>
                ${c.description ? `<span class="admin-muted">${escapeHtml(c.description)}</span>` : ''}
            </div>
        `;
        row.addEventListener('click', () => fillForm(c));
        list.appendChild(row);
    });
}

function fillForm(c) {
    document.getElementById('context-edit-id').value = c?.id || '';
    document.getElementById('context-name-input').value = c?.name || '';
    document.getElementById('context-desc-input').value = c?.description || '';
    document.getElementById('context-content-input').value = c?.content || '';
    const title = document.getElementById('context-form-title');
    if (title) title.textContent = c?.id ? `Edit: ${c.name}` : 'New context';
    const del = document.getElementById('context-delete-btn');
    if (del) del.disabled = !c?.id;
    renderContextList(c?.id || '');
    setModalStatus('');
}

function clearForm() {
    fillForm(null);
    document.getElementById('context-form-title').textContent = 'New context';
}

async function saveContext() {
    const id = document.getElementById('context-edit-id')?.value?.trim() || '';
    const name = document.getElementById('context-name-input')?.value?.trim() || '';
    const description = document.getElementById('context-desc-input')?.value?.trim() || '';
    const content = document.getElementById('context-content-input')?.value?.trim() || '';
    if (!name || !content) {
        setModalStatus('Name and content are required.', true);
        return;
    }
    setModalStatus(id ? 'Saving…' : 'Creating…');
    try {
        const res = await fetch(id ? `/api/v1/contexts/${encodeURIComponent(id)}` : '/api/v1/contexts', {
            method: id ? 'PUT' : 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, description, content }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || 'Save failed');
        contextsCache = data.contexts || [];
        const saved = data.context || {};
        populateContextSelect(saved.id || getSelectedContextId());
        fillForm(saved);
        setModalStatus(`Saved “${saved.name || name}”.`);
    } catch (e) {
        setModalStatus(String(e.message || e), true);
    }
}

async function deleteContext() {
    const id = document.getElementById('context-edit-id')?.value?.trim() || '';
    const name = document.getElementById('context-name-input')?.value?.trim() || id;
    if (!id) return;
    if (!confirm(`Delete context “${name}”?`)) return;
    setModalStatus('Deleting…');
    try {
        const res = await fetch(`/api/v1/contexts/${encodeURIComponent(id)}`, {
            method: 'DELETE',
            credentials: 'same-origin',
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || 'Delete failed');
        contextsCache = data.contexts || [];
        if (getSelectedContextId() === id) {
            removeItem(currentUserId(), SUFFIX_CONTEXT);
        }
        populateContextSelect();
        clearForm();
        setModalStatus(`Deleted “${name}”.`);
    } catch (e) {
        setModalStatus(String(e.message || e), true);
    }
}

export function openContextManager() {
    const modal = document.getElementById('context-modal');
    if (!modal) return;
    clearForm();
    renderContextList('');
    setModalStatus('');
    modal.showModal();
}

export function initContexts() {
    const sel = document.getElementById('context-select');
    sel?.addEventListener('change', () => {
        writeItem(currentUserId(), SUFFIX_CONTEXT, sel.value || '');
        updateContextSelectTitle();
    });

    document.getElementById('context-manage-btn')?.addEventListener('click', async () => {
        try {
            await loadContexts();
        } catch (e) {
            console.error(e);
        }
        openContextManager();
    });

    const modal = document.getElementById('context-modal');
    document.getElementById('context-modal-close-btn')?.addEventListener('click', () => modal?.close());
    modal?.addEventListener('click', (e) => {
        if (e.target === modal) modal.close();
    });

    document.getElementById('context-new-btn')?.addEventListener('click', () => clearForm());
    document.getElementById('context-save-btn')?.addEventListener('click', () => saveContext());
    document.getElementById('context-delete-btn')?.addEventListener('click', () => deleteContext());

    // Initial load (non-blocking for chat)
    loadContexts().catch(e => console.warn('[contexts]', e));
}

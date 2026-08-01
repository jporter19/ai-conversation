// frontend/js/admin.js — Admin Tools entry (tabs + event wiring)
import {
    catalog,
    setStatus,
    setStatusEl,
    setAdminModal,
    switchTab,
    refreshCatalogUI,
    applyTheme,
    DEFAULT_AI,
} from './admin/shared.js';
import {
    renderModelsAdmin,
    renderKeysAdmin,
    renderPrefsAdmin,
    renderProvidersAdmin,
    testKey,
} from './admin/panels.js';
import { renderVoiceAdmin, stopVoicePreview } from './admin/voice.js';
import {
    loadPresetChips,
    runDiscover,
    resetDiscover,
    readProposalFromForm,
    showEl,
} from './admin/setup.js';

// re-export refresh for any external use
export { refreshCatalogUI } from './admin/shared.js';

async function refreshAdminPanels() {
    renderModelsAdmin();
    renderKeysAdmin();
    renderPrefsAdmin();
    renderProvidersAdmin();
    await renderVoiceAdmin();
}
globalThis.__refreshAdminPanels = refreshAdminPanels;

export function initAdmin() {
    const modal = document.getElementById('admin-modal');
    setAdminModal(modal);
    setStatusEl(document.getElementById('admin-status'));
    const adminModal = modal;
    const openBtn = document.getElementById('admin-btn');
    const closeBtn = document.getElementById('admin-close-btn');

    if (!adminModal || !openBtn) {
        console.warn('[admin] Admin UI elements missing');
        return;
    }

    openBtn.addEventListener('click', async () => {
        adminModal.showModal();
        setStatus('');
        try {
            await refreshCatalogUI();
            await loadPresetChips();
            switchTab('add');
        } catch (e) {
            setStatus(String(e.message || e), true);
        }
    });

    closeBtn?.addEventListener('click', () => adminModal.close());
    adminModal.addEventListener('click', e => {
        if (e.target === adminModal) adminModal.close();
    });

    document.querySelectorAll('.admin-tab').forEach(btn => {
        btn.addEventListener('click', () => switchTab(btn.dataset.tab));
    });

    document.getElementById('admin-model-provider')?.addEventListener('change', renderModelsAdmin);

    document.getElementById('admin-add-model-btn')?.addEventListener('click', async () => {
        const providerId = document.getElementById('admin-model-provider')?.value;
        const value = document.getElementById('admin-new-model-value')?.value?.trim();
        const label = document.getElementById('admin-new-model-label')?.value?.trim() || value;
        const capability = document.getElementById('admin-new-model-capability')?.value || 'chat';
        const tooltip = document.getElementById('admin-new-model-tooltip')?.value?.trim() || '';
        if (!providerId || !value) {
            setStatus('API and model id are required', true);
            return;
        }
        try {
            const res = await fetch(`/api/v1/admin/providers/${encodeURIComponent(providerId)}/models`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ value, label, tooltip, capability, manual: true }),
            });
            if (!res.ok) throw new Error(await res.text());
            document.getElementById('admin-new-model-value').value = '';
            document.getElementById('admin-new-model-label').value = '';
            document.getElementById('admin-new-model-tooltip').value = '';
            setStatus(`Added model ${value} to ${providerId}`);
            await refreshCatalogUI();
        } catch (e) {
            setStatus(String(e.message || e), true);
        }
    });

    document.getElementById('admin-save-keys-btn')?.addEventListener('click', async () => {
        const inputs = document.querySelectorAll('#admin-keys-list .admin-key-input');
        const secrets = {};
        let any = false;
        inputs.forEach(inp => {
            const v = inp.value.trim();
            if (v) {
                secrets[inp.dataset.key] = v;
                any = true;
            }
        });
        if (!any) {
            setStatus('Paste at least one key to save', true);
            return;
        }
        try {
            const res = await fetch('/api/v1/admin/secrets', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ secrets }),
            });
            if (!res.ok) throw new Error(await res.text());
            inputs.forEach(inp => { inp.value = ''; });
            setStatus('API keys saved (app/data/secrets.json)');
            await refreshCatalogUI();
        } catch (e) {
            setStatus(String(e.message || e), true);
        }
    });

    document.getElementById('admin-auto-update-btn')?.addEventListener('click', async () => {
        setStatus('Updating models from OpenAI & xAI…');
        try {
            const res = await fetch('/api/v1/admin/models/auto-update', { method: 'POST' });
            const data = await res.json();
            if (!res.ok) throw new Error(JSON.stringify(data));
            const lines = (data.results || []).map(r =>
                `${r.provider_id}: ${r.ok ? 'OK' : 'FAIL'} — ${r.message}`,
            );
            setStatus(lines.join(' | ') || 'Done');
            await refreshCatalogUI();
        } catch (e) {
            setStatus(String(e.message || e), true);
        }
    });

    document.getElementById('admin-save-prefs-btn')?.addEventListener('click', async () => {
        const theme = document.getElementById('admin-theme')?.value || 'light';
        const default_ai = document.getElementById('admin-default-ai')?.value || DEFAULT_AI;
        try {
            const res = await fetch('/api/v1/admin/preferences', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ theme, default_ai }),
            });
            if (!res.ok) throw new Error(await res.text());
            applyTheme(theme);
            setStatus('Preferences saved');
            await refreshCatalogUI();
        } catch (e) {
            setStatus(String(e.message || e), true);
        }
    });

    document.getElementById('admin-save-voice-btn')?.addEventListener('click', async () => {
        const tts_voice = document.getElementById('admin-tts-voice')?.value?.trim() || 'eve';
        const tts_language = document.getElementById('admin-tts-language')?.value?.trim() || 'en';
        try {
            const res = await fetch('/api/v1/admin/preferences', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ tts_voice, tts_language }),
            });
            if (!res.ok) throw new Error(await res.text());
            setStatus(`Voice preferences saved — default “${tts_voice}” (${tts_language}).`);
            await refreshCatalogUI();
        } catch (e) {
            setStatus(String(e.message || e), true);
        }
    });

    document.getElementById('admin-theme')?.addEventListener('change', (e) => {
        applyTheme(e.target.value);
    });

    // Wizard — conversational discover
    document.getElementById('setup-discover-btn')?.addEventListener('click', () => runDiscover());
    document.getElementById('setup-reset-btn')?.addEventListener('click', () => resetDiscover());

    document.getElementById('setup-description')?.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            runDiscover();
        }
    });

    document.getElementById('setup-test-btn')?.addEventListener('click', async () => {
        const form = readProposalFromForm();
        if (!form.api_key_name) {
            setStatus('Key name is required — run Find & add first or fill Advanced details.', true);
            return;
        }
        if (!form.base_url) {
            setStatus('Base URL is required to test.', true);
            return;
        }
        // Prefer a chat model for probe when capability is stt/tts
        let modelValue = form.models?.[0]?.value || '';
        const cap = form.models?.[0]?.capability || 'chat';
        let keyTest = form.key_test || 'auto';
        if (cap === 'stt' || cap === 'tts') {
            keyTest = 'models';
        }
        showEl('setup-result-card', true);
        await testKey(form.api_key_name, {
            buttonEl: document.getElementById('setup-test-btn'),
            inputEl: document.getElementById('setup-api-key'),
            resultEl: document.getElementById('setup-test-result'),
            apiKey: form.api_key,
            baseUrl: form.base_url,
            model: modelValue,
            label: form.label,
            keyTest,
        });
    });

    document.getElementById('setup-apply-btn')?.addEventListener('click', async () => {
        const form = readProposalFromForm();
        if (!form.id) {
            setStatus('Internal id is required. Run Find & add or fill Advanced details.', true);
            return;
        }
        if (!form.base_url) {
            setStatus('Base URL is required for API providers.', true);
            return;
        }
        if (!form.api_key_name) {
            setStatus('Key storage name is required (e.g. XAI_API_KEY).', true);
            return;
        }
        if (!form.models.length) {
            setStatus('Model id is required.', true);
            return;
        }
        setStatus('Saving API…');
        try {
            const res = await fetch('/api/v1/admin/setup/apply', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(form),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || JSON.stringify(data));

            const test = data.test;
            let msg = `Saved “${form.label}”`;
            if (data.key_saved) msg += ' with API key';
            if (test) {
                msg += test.ok ? ` — ${test.message}` : ` — key test: ${test.message}`;
            } else if (!form.api_key) {
                msg += ' — using stored key if available';
            }
            setStatus(msg, test ? !test.ok : false);

            showEl('setup-result-card', true);
            const resultMsg = document.getElementById('setup-result-msg');
            if (resultMsg) {
                resultMsg.textContent = msg;
                resultMsg.className = `setup-result-msg status-${test && !test.ok ? 'error' : 'applied'}`;
            }
            const result = document.getElementById('setup-test-result');
            if (result && test) {
                result.hidden = false;
                result.className = `admin-key-test-result ${test.ok ? 'ok' : 'fail'}`;
                result.textContent = test.message;
            }

            const keyInput = document.getElementById('setup-api-key');
            if (keyInput) keyInput.value = '';
            await refreshCatalogUI();
        } catch (e) {
            setStatus(String(e.message || e), true);
        }
    });
}

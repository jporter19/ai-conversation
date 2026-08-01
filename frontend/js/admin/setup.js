// frontend/js/admin/setup.js — guided Add API discover wizard
import {
    catalog,
    setStatus,
    escapeHtml,
    lastProposal,
    setLastProposal,
    refreshCatalogUI,
} from './shared.js';
import { testKey } from './panels.js';

export function plainMsg(s) {
    return String(s || '').replace(/\*\*/g, '');
}

export function fillProposalForm(proposal) {
    setLastProposal(proposal);
    if (!proposal) return;
    const idEl = document.getElementById('setup-id');
    const labelEl = document.getElementById('setup-label');
    const baseEl = document.getElementById('setup-base-url');
    const keyEl = document.getElementById('setup-key-name');
    const modelValEl = document.getElementById('setup-model-value');
    const modelLabelEl = document.getElementById('setup-model-label');
    const capEl = document.getElementById('setup-capability');
    const notesEl = document.getElementById('setup-notes');

    if (idEl) idEl.value = proposal.id || '';
    if (labelEl) labelEl.value = proposal.label || '';
    if (baseEl) baseEl.value = proposal.base_url || '';
    if (keyEl) keyEl.value = proposal.api_key_name || '';
    const model = (proposal.models && proposal.models[0]) || {};
    if (modelValEl) modelValEl.value = model.value || '';
    if (modelLabelEl) modelLabelEl.value = model.label || model.value || '';
    if (capEl) {
        const cap = model.capability || proposal.capability || 'chat';
        capEl.value = cap;
    }
    if (notesEl) notesEl.textContent = proposal.notes || '';

    const chips = document.getElementById('setup-model-suggestions');
    if (chips) {
        chips.innerHTML = '';
        (proposal.suggested_models || []).forEach(m => {
            const b = document.createElement('button');
            b.type = 'button';
            b.className = 'preset-chip';
            b.textContent = m.label || m.value;
            b.title = `${m.value}${m.capability ? ` (${m.capability})` : ''}`;
            b.addEventListener('click', () => {
                if (modelValEl) modelValEl.value = m.value;
                if (modelLabelEl) modelLabelEl.value = m.label || m.value;
                if (capEl && m.capability) capEl.value = m.capability;
            });
            chips.appendChild(b);
        });
    }

    const suggestMsg = document.getElementById('setup-suggest-msg');
    if (suggestMsg) {
        suggestMsg.textContent = proposal.already_exists
            ? 'Provider already exists — this will add/update the model on it.'
            : 'New or custom provider details (edit if needed).';
    }
}

export function readProposalFromForm() {
    const id = document.getElementById('setup-id')?.value?.trim();
    const label = document.getElementById('setup-label')?.value?.trim() || id;
    let base_url = document.getElementById('setup-base-url')?.value?.trim() || '';
    base_url = base_url.replace(/\/+$/, '').replace(/\/chat\/completions$/i, '');
    const api_key_name = document.getElementById('setup-key-name')?.value?.trim();
    const model_value = document.getElementById('setup-model-value')?.value?.trim();
    const model_label = document.getElementById('setup-model-label')?.value?.trim() || model_value;
    const capability = document.getElementById('setup-capability')?.value || 'chat';
    const api_key = document.getElementById('setup-api-key')?.value?.trim() || '';

    return {
        id,
        label,
        base_url,
        api_key_name,
        api_key: api_key || null,
        key_test: lastProposal?.key_test || (capability === 'stt' || capability === 'tts' ? 'models' : 'auto'),
        type: lastProposal?.type || 'openai_compatible',
        supports_tools: !!lastProposal?.supports_tools,
        supports_image_gen: !!lastProposal?.supports_image_gen || capability === 'image',
        badge_color: lastProposal?.badge_color || '#555555',
        models: model_value
            ? [{ value: model_value, label: model_label, tooltip: '', capability, manual: true }]
            : [],
        run_test: true,
    };
}

export function showEl(id, visible) {
    const el = document.getElementById(id);
    if (el) el.hidden = !visible;
}

export function renderQuestions(questions, message) {
    const card = document.getElementById('setup-clarify-card');
    const host = document.getElementById('setup-questions');
    const msgEl = document.getElementById('setup-clarify-msg');
    if (!card || !host) return;

    if (msgEl) msgEl.textContent = plainMsg(message);
    host.innerHTML = '';
    (questions || []).forEach(q => {
        const block = document.createElement('div');
        block.className = 'setup-question';
        const title = document.createElement('p');
        title.className = 'setup-question-prompt';
        title.textContent = q.prompt || q.id || 'Choose';
        block.appendChild(title);
        const chips = document.createElement('div');
        chips.className = 'preset-chips';
        (q.options || []).forEach(opt => {
            const b = document.createElement('button');
            b.type = 'button';
            b.className = 'preset-chip';
            if (setupAnswers[q.id] === opt.value) b.classList.add('selected');
            b.textContent = opt.label || opt.value;
            b.title = opt.value;
            b.addEventListener('click', async () => {
                setupAnswers[q.id] = opt.value;
                // For "example" chips, put text into the description box
                if (q.id === 'example' || q.id === 'model') {
                    const desc = document.getElementById('setup-description');
                    if (desc && q.id === 'example') desc.value = opt.value;
                }
                chips.querySelectorAll('.preset-chip').forEach(c => c.classList.remove('selected'));
                b.classList.add('selected');
                // Auto-continue when an option is chosen
                await runDiscover({ fromAnswer: true });
            });
            chips.appendChild(b);
        });
        block.appendChild(chips);
        host.appendChild(block);
    });
    card.hidden = !(questions && questions.length);
}

export function renderDiscoverResult(data) {
    const status = data.status || (data.applied ? 'applied' : 'ready');
    const resultCard = document.getElementById('setup-result-card');
    const resultMsg = document.getElementById('setup-result-msg');
    const keyStatus = document.getElementById('setup-key-status');
    const testEl = document.getElementById('setup-test-result');

    if (resultCard) resultCard.hidden = false;
    if (resultMsg) {
        resultMsg.textContent = plainMsg(data.message);
        resultMsg.className = `setup-result-msg status-${status}`;
    }

    if (keyStatus) {
        if (data.key) {
            keyStatus.hidden = false;
            keyStatus.innerHTML = data.key.configured
                ? `Key <code>${escapeHtml(data.key.name)}</code> on file (${escapeHtml(data.key.hint || '••••')})`
                : `Key <code>${escapeHtml(data.key.name)}</code> not configured — paste below if needed`;
            keyStatus.className = `setup-key-status ${data.key.configured ? 'ok' : 'missing'}`;
        } else {
            keyStatus.hidden = true;
        }
    }

    if (testEl) {
        if (data.test) {
            testEl.hidden = false;
            testEl.className = `admin-key-test-result ${data.test.ok ? 'ok' : 'fail'}`;
            testEl.textContent = data.test.message || (data.test.ok ? 'OK' : 'Failed');
        } else {
            testEl.hidden = true;
        }
    }

    // Show key card when ready but no key / test failed needing new key
    const needKey = status === 'ready'
        && data.proposal
        && (!data.key?.configured || (data.test && !data.test.ok));
    showEl('setup-key-card', !!needKey || status === 'ready');

    if (data.proposal) fillProposalForm(data.proposal);

    if (status === 'needs_clarification') {
        renderQuestions(data.questions || [], data.message);
        showEl('setup-result-card', true);
    } else {
        showEl('setup-clarify-card', false);
    }

    if (status === 'applied') {
        setStatus(plainMsg(data.message) || 'Model added and ready.', false);
    } else if (status === 'needs_clarification') {
        setStatus(plainMsg(data.message) || 'Please answer the questions above.', false);
    } else if (status === 'ready') {
        setStatus(plainMsg(data.message) || 'Proposal ready.', !data.test?.ok && data.key && !data.key.configured);
    } else {
        setStatus(plainMsg(data.message) || 'Something went wrong', true);
    }
}

export function resetDiscover() {
    setupAnswers = {};
    setupHistory = [];
    setLastProposal(null);
    const desc = document.getElementById('setup-description');
    if (desc) desc.value = '';
    const key = document.getElementById('setup-api-key');
    if (key) key.value = '';
    showEl('setup-clarify-card', false);
    showEl('setup-result-card', false);
    showEl('setup-key-card', false);
    const questions = document.getElementById('setup-questions');
    if (questions) questions.innerHTML = '';
    ['setup-id', 'setup-label', 'setup-base-url', 'setup-key-name',
        'setup-model-value', 'setup-model-label', 'setup-notes', 'setup-suggest-msg'].forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            if ('value' in el) el.value = '';
            else el.textContent = '';
        }
    });
    const cap = document.getElementById('setup-capability');
    if (cap) cap.value = 'chat';
    setStatus('');
}

export async function runDiscover({ fromAnswer = false } = {}) {
    const description = document.getElementById('setup-description')?.value?.trim() || '';
    if (!description && !Object.keys(setupAnswers).length) {
        setStatus('Describe what you want to add first.', true);
        return;
    }

    const btn = document.getElementById('setup-discover-btn');
    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Working…';
    }
    setStatus(fromAnswer ? 'Using your answer…' : 'Searching providers & models…');

    const api_key = document.getElementById('setup-api-key')?.value?.trim() || null;

    try {
        if (!fromAnswer && description) {
            setupHistory.push({ role: 'user', content: description });
        }

        const res = await fetch('/api/v1/admin/setup/discover', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: description || Object.values(setupAnswers).join(' '),
                answers: setupAnswers,
                history: setupHistory.slice(-8),
                api_key,
                auto_apply: true,
                use_ai: true,
            }),
        });
        const data = await res.json();
        if (!res.ok) {
            throw new Error(typeof data.detail === 'string' ? data.detail : (data.message || 'Discover failed'));
        }

        if (data.message) {
            setupHistory.push({ role: 'assistant', content: plainMsg(data.message) });
        }

        renderDiscoverResult(data);

        if (data.status === 'applied') {
            await refreshCatalogUI();
            // Clear answers after success so a new request starts clean
            setupAnswers = {};
        }
    } catch (e) {
        setStatus(String(e.message || e), true);
        showEl('setup-result-card', true);
        const resultMsg = document.getElementById('setup-result-msg');
        if (resultMsg) {
            resultMsg.textContent = String(e.message || e);
            resultMsg.className = 'setup-result-msg status-error';
        }
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = 'Find & add';
        }
    }
}

export async function loadPresetChips() {
    const host = document.getElementById('setup-preset-chips');
    if (!host) return;
    // Quick-start examples (capability-oriented), not just vendor names
    const examples = [
        { label: 'Grok speech to text', value: 'Grok speech to text' },
        { label: 'Grok image gen', value: 'Grok image generation' },
        { label: 'OpenAI Whisper', value: 'OpenAI whisper speech to text' },
        { label: 'Groq Llama 8B', value: 'Groq Llama 8B' },
        { label: 'Magisterium', value: 'Magisterium AI chat' },
    ];
    host.innerHTML = '';
    examples.forEach(ex => {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'preset-chip';
        b.textContent = ex.label;
        b.addEventListener('click', () => {
            const desc = document.getElementById('setup-description');
            if (desc) desc.value = ex.value;
            setupAnswers = {};
            runDiscover();
        });
        host.appendChild(b);
    });
}


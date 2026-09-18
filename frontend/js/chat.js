// frontend/js/chat.js
// Purpose: Chat send/reset/store orchestration (STT + stream helpers extracted).

import {
    getConversation,
    setConversation,
    addMessage,
    clearConversation,
    saveConversation,
    removeLastUserTurn,
} from './state.js';

import {
    renderHistory,
    scrollToBottom,
    createStreamRenderer,
} from './ui.js';

import {
    DEFAULT_AI,
    DEFAULT_GROK_MODEL,
    catalog,
    currentUserId,
    populateProviders,
    populateModels,
    getModelsForProvider,
    getProvider,
    getModelCapability,
} from './config.js';

import { getSelectedContextId } from './contexts.js';
import { writeItem, SUFFIX_AI, SUFFIX_MODEL } from './user_storage.js';
import { readChatStream, finalizeStreamText } from './chat/stream.js';
import {
    initSttControls,
    updateComposerForCapability,
    getIsRecording,
    getIsDictating,
    getRecordPurpose,
    stopMicDictation,
    fromRecordLabel,
    discardStagedAudio,
    openProcessAudioModal,
    setComposerStatus,
    startBusyTimer,
    stopBusyTimer,
    syncSttControlDisabled,
} from './chat/stt.js';

export { updateComposerForCapability };

const userInput       = document.getElementById('user-input');
const sendBtn         = document.getElementById('send-btn');
const chatHistory     = document.getElementById('chat-history');
const resetBtn        = document.getElementById('reset-btn');
const storeBtn        = document.getElementById('store-btn');
const storeModal      = document.getElementById('store-modal');
const storeWholeBtn   = document.getElementById('store-whole-btn');
const storeSummaryBtn = document.getElementById('store-summary-btn');
const storeNameInput  = document.getElementById('store-name-input');
const storeStatusEl   = document.getElementById('store-status');
const modalCancelBtn  = document.getElementById('modal-cancel-btn');
const restoreBtn      = document.getElementById('restore-btn');
const restoreModal    = document.getElementById('restore-modal');
const restoreCloseBtn = document.getElementById('restore-close-btn');
const restoreListEl   = document.getElementById('restore-list');
const restoreStatusEl = document.getElementById('restore-status');
const resetModal      = document.getElementById('reset-modal');
const resetConfirmBtn = document.getElementById('reset-confirm-btn');
const resetCancelBtn  = document.getElementById('reset-cancel-btn');
const aiSelect        = document.getElementById('ai-select');
const modelSelect     = document.getElementById('model-select');
const storeTranscriptBtn = document.getElementById('store-transcript-btn');
const storeAudioBtn   = document.getElementById('store-audio-btn');
const storePhotosBtn  = document.getElementById('store-photos-btn');

/** In-flight guard: only one stream at a time. */
let sending = false;
/** @type {AbortController|null} */
let activeAbort = null;
let lastSentPrompt = '';
let lastSentUserContent = '';
let userRequestedStop = false;

const STOP_BTN_HTML = '<span class="stop-square" aria-hidden="true"></span>';

function setSending(on) {
    sending = !!on;
    if (sendBtn) {
        sendBtn.disabled = false;
        sendBtn.classList.toggle('is-stop', sending);
        sendBtn.setAttribute('aria-busy', sending ? 'true' : 'false');
        if (sending) {
            sendBtn.innerHTML = STOP_BTN_HTML;
            sendBtn.title = 'Stop generating';
            sendBtn.setAttribute('aria-label', 'Stop generating');
        } else {
            sendBtn.textContent = 'Send';
            sendBtn.title = 'Send message';
            sendBtn.setAttribute('aria-label', 'Send message');
        }
    }
    if (userInput) {
        userInput.disabled = false;
        userInput.setAttribute('aria-busy', sending ? 'true' : 'false');
    }
    if (aiSelect) aiSelect.disabled = sending;
    if (modelSelect) modelSelect.disabled = sending;
    syncSttControlDisabled(sending);
}

function abortActiveRequest() {
    if (activeAbort) {
        try { activeAbort.abort(); } catch (_) { /* ignore */ }
        activeAbort = null;
    }
    setSending(false);
}

function stopGeneration() {
    if (!sending) return;
    userRequestedStop = true;
    const prompt = lastSentPrompt;
    const turn = lastSentUserContent || prompt;
    abortActiveRequest();
    if (turn) {
        removeLastUserTurn(turn);
        renderHistory();
        if (userInput) {
            userInput.value = prompt || '';
            userInput.focus();
            const len = userInput.value.length;
            userInput.setSelectionRange(len, len);
        }
    } else {
        renderHistory();
    }
}

function badgeForAi(aiId) {
    const p = getProvider(aiId);
    return {
        text: (p?.label || aiId || 'AI').toUpperCase().slice(0, 18),
        color: p?.badge_color || '#555555',
    };
}

function setStoreStatus(msg, isError = false) {
    if (!storeStatusEl) return;
    storeStatusEl.hidden = !msg;
    storeStatusEl.textContent = msg || '';
    storeStatusEl.classList.toggle('error', !!isError);
}

function setRestoreStatus(msg, isError = false) {
    if (!restoreStatusEl) return;
    restoreStatusEl.hidden = !msg;
    restoreStatusEl.textContent = msg || '';
    restoreStatusEl.classList.toggle('error', !!isError);
}

function formatStoredDate(iso) {
    if (!iso) return 'Unknown date';
    try {
        const d = new Date(iso);
        if (Number.isNaN(d.getTime())) return iso;
        return d.toLocaleString(undefined, {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            hour: 'numeric',
            minute: '2-digit',
        });
    } catch {
        return iso;
    }
}

function messageLooksLikeTranscript(content) {
    const c = String(content || '');
    // Text transcripts only (STT results, YouTube, etc.) — not playable audio.
    return (
        /###\s*transcript/i.test(c)
        || /\*\*youtube transcript\*\*/i.test(c)
        || /youtube transcript/i.test(c)
        || /\[voice recording\]/i.test(c)
        || /\[audio:/i.test(c)
        || /transcribing\s+`/i.test(c)
        || /<!--\s*stt via/i.test(c)
        || /speech-to-text|transcription failed|no speech detected/i.test(c)
        || /\bgrok-stt\b/i.test(c)
        || /\/v1\/stt|\/audio\/transcriptions/i.test(c)
    );
}

/**
 * True only when the turn has storeable/playable audio (TTS output, media player URL).
 * STT turns that merely mention an input filename (e.g. Transcribing `recording-….webm`)
 * must NOT count — that audio is not in the chat and is not playable.
 */
function messageLooksLikeAudio(content) {
    const c = String(content || '');
    return (
        /\/api\/v1\/media\/[a-f0-9]+/i.test(c)
        || /data:audio\//i.test(c)
        || (/blob:[^\s)"']+/i.test(c) && /audio|speech|play/i.test(c))
        || /<audio[\s>]/i.test(c)
        || /###\s*speech\b/i.test(c)
        || /\[play speech\]/i.test(c)
        || /generated speech/i.test(c)
        // Markdown or bare URL to an audio file — not a bare filename in backticks
        || /\[[^\]]*\]\([^)]*\.(?:mp3|wav|ogg|m4a|flac|webm)(?:\?[^)]*)?\)/i.test(c)
        || /https?:\/\/[^\s)"']+\.(?:mp3|wav|ogg|m4a|flac|webm)\b/i.test(c)
    );
}

function messageLooksLikePhoto(content) {
    const c = String(content || '');
    return (
        /!\[[^\]]*\]\([^)]+\)/.test(c)
        || /<img[\s>]/i.test(c)
        || /data:image\//i.test(c)
        || /imgen\.x\.ai|generated with.*image|dall-e|imagine-image/i.test(c)
        // Image file URL (not a bare extension mention in prose)
        || /\[[^\]]*\]\([^)]*\.(?:png|jpe?g|webp|gif|svg)(?:\?[^)]*)?\)/i.test(c)
        || /https?:\/\/[^\s)"']+\.(?:png|jpe?g|webp|gif|svg)\b/i.test(c)
        || /\/api\/v1\/media\/[a-f0-9]+\.(?:png|jpe?g|webp|gif|svg)\b/i.test(c)
    );
}

function filterMessagesForStore(kind, messages) {
    const k = (kind || 'whole').toLowerCase();
    if (k === 'whole' || k === 'summary') return messages;
    if (k === 'transcript') return messages.filter(m => messageLooksLikeTranscript(m.content));
    if (k === 'audio') return messages.filter(m => messageLooksLikeAudio(m.content));
    if (k === 'photos') return messages.filter(m => messageLooksLikePhoto(m.content));
    return messages;
}

/** Green + enabled when content exists; grey + disabled when not. */
function updateStoreOptionAvailability() {
    const messages = getConversation() || [];
    const hasTranscript = messages.some(m => messageLooksLikeTranscript(m?.content));
    const hasAudio = messages.some(m => messageLooksLikeAudio(m?.content));
    const hasPhotos = messages.some(m => messageLooksLikePhoto(m?.content));

    const apply = (btn, available, emptyHint) => {
        if (!btn) return;
        btn.disabled = !available;
        btn.classList.remove('store-opt-available', 'store-opt-empty');
        btn.classList.add(available ? 'store-opt-available' : 'store-opt-empty');
        btn.setAttribute('aria-disabled', available ? 'false' : 'true');
        btn.title = available
            ? `${btn.textContent.trim()} — available in this chat`
            : (emptyHint || 'Nothing of this type in the current chat');
    };

    apply(storeTranscriptBtn, hasTranscript, 'No transcript found in this chat');
    apply(storeAudioBtn, hasAudio, 'No audio found in this chat');
    apply(storePhotosBtn, hasPhotos, 'No photos found in this chat');
}

function setStoreButtonsDisabled(on) {
    // Whole/summary always available when modal is open with messages
    if (storeWholeBtn) storeWholeBtn.disabled = !!on;
    if (storeSummaryBtn) storeSummaryBtn.disabled = !!on;
    if (on) {
        // Saving in progress — lock content-type buttons too
        if (storeTranscriptBtn) storeTranscriptBtn.disabled = true;
        if (storeAudioBtn) storeAudioBtn.disabled = true;
        if (storePhotosBtn) storePhotosBtn.disabled = true;
    } else {
        // Restore green/grey state from chat content
        updateStoreOptionAvailability();
    }
}

async function storeCurrentConversation(kind) {
    const name = (storeNameInput?.value || '').trim();
    if (!name) {
        setStoreStatus('Please enter a name for this conversation.', true);
        storeNameInput?.focus();
        return;
    }
    const all = getConversation();
    if (!all.length) {
        setStoreStatus('Nothing to store.', true);
        return;
    }

    const messages = filterMessagesForStore(kind, all);
    if (!messages.length) {
        const labels = {
            transcript: 'No transcript turns found in this chat.',
            audio: 'No audio links found in this chat.',
            photos: 'No images found in this chat.',
        };
        setStoreStatus(labels[kind] || 'Nothing matched that store type.', true);
        return;
    }

    // summary still uses full thread; server builds summary
    const payloadMessages = kind === 'summary' ? all : messages;
    const saveKind = ['transcript', 'audio', 'photos'].includes(kind) ? 'whole' : kind;

    setStoreStatus('Saving…');
    setStoreButtonsDisabled(true);
    try {
        const res = await fetch('/api/v1/conversations', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify({
                name: kind === 'whole' || kind === 'summary' ? name : `${name} (${kind})`,
                kind: saveKind,
                messages: payloadMessages,
            }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            throw new Error(data.detail || res.statusText || 'Save failed');
        }
        const saved = data.conversation || {};
        setStoreStatus(
            `Saved “${saved.name || name}” (${formatStoredDate(saved.stored_at)}) — ${saved.message_count ?? payloadMessages.length} messages`
        );
        setTimeout(() => storeModal.close(), 900);
    } catch (e) {
        setStoreStatus(String(e.message || e), true);
    } finally {
        setStoreButtonsDisabled(false);
    }
}

async function openRestoreModal() {
    if (!restoreModal) return;
    setRestoreStatus('');
    if (restoreListEl) {
        restoreListEl.innerHTML = '<p class="admin-muted">Loading saved conversations…</p>';
    }
    restoreModal.showModal();
    await refreshRestoreList();
}

async function refreshRestoreList() {
    if (!restoreListEl) return;
    try {
        const res = await fetch('/api/v1/conversations');
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Failed to load list');

        const items = data.conversations || [];
        if (!items.length) {
            restoreListEl.innerHTML = '<p class="admin-muted">No stored conversations yet. Use <strong>Store Conversation</strong> to save one.</p>';
            return;
        }

        restoreListEl.innerHTML = '';
        items.forEach(item => {
            const row = document.createElement('div');
            row.className = 'restore-row';
            row.innerHTML = `
                <div class="restore-row-main">
                    <strong class="restore-name"></strong>
                    <div class="restore-meta">
                        <span class="restore-date"></span>
                        <span class="admin-tag restore-kind"></span>
                        <span class="admin-tag restore-count"></span>
                    </div>
                    <p class="restore-preview"></p>
                </div>
                <div class="restore-row-actions">
                    <button type="button" class="modal-btn primary restore-load-btn">Restore</button>
                    <button type="button" class="modal-btn secondary restore-delete-btn">Delete</button>
                </div>
            `;
            row.querySelector('.restore-name').textContent = item.name || 'Untitled';
            row.querySelector('.restore-date').textContent = formatStoredDate(item.stored_at);
            row.querySelector('.restore-kind').textContent = item.kind || 'whole';
            row.querySelector('.restore-count').textContent = `${item.message_count ?? 0} msgs`;
            row.querySelector('.restore-preview').textContent = item.preview || '';

            row.querySelector('.restore-load-btn').addEventListener('click', () => {
                restoreConversationById(item.id, item.name);
            });
            row.querySelector('.restore-delete-btn').addEventListener('click', async () => {
                if (!confirm(`Delete stored conversation “${item.name}”?`)) return;
                try {
                    const del = await fetch(`/api/v1/conversations/${encodeURIComponent(item.id)}`, {
                        method: 'DELETE',
                    });
                    if (!del.ok) throw new Error('Delete failed');
                    setRestoreStatus(`Deleted “${item.name}”`);
                    await refreshRestoreList();
                } catch (e) {
                    setRestoreStatus(String(e.message || e), true);
                }
            });
            restoreListEl.appendChild(row);
        });
    } catch (e) {
        restoreListEl.innerHTML = '';
        setRestoreStatus(String(e.message || e), true);
    }
}

async function restoreConversationById(id, name) {
    setRestoreStatus(`Loading “${name || id}”…`);
    try {
        const res = await fetch(`/api/v1/conversations/${encodeURIComponent(id)}`);
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Restore failed');

        const messages = data.messages || [];
        if (!messages.length) {
            throw new Error('That conversation has no messages');
        }

        setConversation(messages.map(m => ({
            role: m.role,
            content: m.content,
            ...(m.ai ? { ai: m.ai } : {}),
        })));
        renderHistory();
        scrollToBottom();
        // Composer chrome follows the *current* model (not the restored messages)
        updateComposerForCapability();
        setRestoreStatus(`Restored “${data.name || name}” (${messages.length} messages)`);
        setTimeout(() => restoreModal?.close(), 600);
    } catch (e) {
        setRestoreStatus(String(e.message || e), true);
    }
}

export function initChat() {
    sendBtn.addEventListener('click', () => {
        if (sending) stopGeneration();
        else sendMessage();
    });
    userInput.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            if (sending) return;
            sendMessage();
        }
    });

    initSttControls({
        getSending: () => sending,
        sendWithAudio: (file) => sendMessage({ audioFile: file }),
    });

    resetBtn.addEventListener('click', () => {
        resetModal.showModal();
    });

    resetConfirmBtn.addEventListener('click', () => {
        abortActiveRequest();
        clearConversation();
        renderHistory();
        const prefs = catalog?.preferences || {};
        const ai = prefs.default_ai || DEFAULT_AI;
        const model = prefs.default_model || DEFAULT_GROK_MODEL;
        populateProviders(aiSelect, ai);
        populateModels(getModelsForProvider(aiSelect.value), model);
        const uid = currentUserId();
        if (uid) {
            writeItem(uid, SUFFIX_AI, aiSelect.value || ai);
            writeItem(uid, SUFFIX_MODEL, modelSelect.value || model);
        }
        renderHistory();
        updateComposerForCapability();
        resetModal.close();
    });

    resetCancelBtn.addEventListener('click', () => resetModal.close());
    resetModal.addEventListener('click', e => {
        if (e.target === resetModal) resetModal.close();
    });

    storeBtn.addEventListener('click', () => {
        if (getConversation().length === 0) {
            alert("Nothing to store yet — start a conversation first!");
            return;
        }
        if (storeStatusEl) {
            storeStatusEl.hidden = true;
            storeStatusEl.textContent = '';
        }
        if (storeNameInput) {
            const firstUser = getConversation().find(m => m.role === 'user');
            const suggestion = (firstUser?.content || 'Conversation')
                .replace(/\s+/g, ' ')
                .trim()
                .slice(0, 60);
            storeNameInput.value = suggestion;
            storeNameInput.focus();
            storeNameInput.select();
        }
        updateStoreOptionAvailability();
        storeModal.showModal();
    });

    storeWholeBtn.addEventListener('click', () => storeCurrentConversation('whole'));
    storeSummaryBtn.addEventListener('click', () => storeCurrentConversation('summary'));
    storeTranscriptBtn?.addEventListener('click', () => storeCurrentConversation('transcript'));
    storeAudioBtn?.addEventListener('click', () => storeCurrentConversation('audio'));
    storePhotosBtn?.addEventListener('click', () => storeCurrentConversation('photos'));
    modalCancelBtn.addEventListener('click', () => storeModal.close());
    storeModal.addEventListener('click', e => {
        if (e.target === storeModal) storeModal.close();
    });
    storeNameInput?.addEventListener('keydown', e => {
        if (e.key === 'Enter') {
            e.preventDefault();
            storeCurrentConversation('whole');
        }
    });

    restoreBtn?.addEventListener('click', () => openRestoreModal());
    restoreCloseBtn?.addEventListener('click', () => restoreModal?.close());
    restoreModal?.addEventListener('click', e => {
        if (e.target === restoreModal) restoreModal.close();
    });

    const noModelModal = document.getElementById('no-model-modal');
    const noModelOkBtn = document.getElementById('no-model-ok-btn');
    noModelOkBtn.addEventListener('click', () => noModelModal.close());
    noModelModal.addEventListener('click', e => {
        if (e.target === noModelModal) noModelModal.close();
    });
}

async function sendMessage(opts = {}) {
    if (sending) return;

    if (getIsRecording() && !opts.audioFile) {
        alert('Recording in progress — click Stop when you finish speaking.');
        return;
    }

    const text = userInput.value.trim();
    const selectedAI = aiSelect.value.trim();
    const selectedModel = modelSelect.value.trim();

    if (!selectedAI || !getProvider(selectedAI)) {
        alert("Please select a valid AI from the dropdown first.");
        return;
    }

    if (!selectedModel) {
        document.getElementById('no-model-modal')?.showModal();
        return;
    }

    const capability = getModelCapability(selectedModel, selectedAI);
    const audioForRequest = opts.audioFile || null;

    if (capability === 'stt') {
        if (!audioForRequest) {
            alert('Use Record or Attach audio. After you finish, confirm “Yes, process” to transcribe.');
            return;
        }
    } else if (!text) {
        return;
    }

    const statusText =
        capability === 'image' ? 'Generating image…'
        : capability === 'video' ? 'Video generation is not enabled yet…'
        : capability === 'transcript' ? 'Fetching transcript…'
        : capability === 'stt' ? '⏳ Grok is transcribing your audio — this can take a while…'
        : capability === 'tts' ? 'Generating speech…'
        : 'Thinking…';

    let userContent = text;
    if (capability === 'stt' && audioForRequest) {
        userContent = fromRecordLabel(audioForRequest);
        if (text) userContent += `\n${text}`;
    }

    const abort = new AbortController();
    activeAbort = abort;
    userRequestedStop = false;
    lastSentPrompt = text;
    lastSentUserContent = userContent;
    if (getIsDictating() || (getIsRecording() && getRecordPurpose() === 'mic')) {
        stopMicDictation({ discard: true });
    }
    setSending(true);
    if (capability === 'stt') {
        startBusyTimer('Grok is processing your speech');
    } else {
        setComposerStatus(statusText, 'busy');
    }

    addMessage({ role: 'user', content: userContent });
    renderHistory();

    userInput.value = '';
    if (capability === 'stt') discardStagedAudio();

    const assistantDiv = document.createElement('div');
    assistantDiv.classList.add('message', 'ai-message');
    const badgeInfo = badgeForAi(selectedAI);
    const badge = document.createElement('div');
    badge.className = 'ai-badge';
    badge.textContent = badgeInfo.text;
    badge.style.backgroundColor = badgeInfo.color;
    badge.style.color = 'white';
    assistantDiv.prepend(badge);

    const contentBody = document.createElement('div');
    contentBody.className = 'message-body is-streaming';
    contentBody.textContent = statusText;
    assistantDiv.appendChild(contentBody);
    chatHistory.appendChild(assistantDiv);
    scrollToBottom();

    try {
        let response;
        if (capability === 'stt' && audioForRequest) {
            const form = new FormData();
            form.append('ai', selectedAI);
            form.append('model', selectedModel);
            form.append('file', audioForRequest, audioForRequest.name);
            if (text) form.append('notes', text);
            response = await fetch('/api/v1/transcribe', {
                method: 'POST',
                credentials: 'same-origin',
                signal: abort.signal,
                body: form,
            });
        } else {
            response = await fetch('/api/v1/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                signal: abort.signal,
                body: JSON.stringify({
                    ai: selectedAI,
                    model: selectedModel,
                    context_id: getSelectedContextId() || undefined,
                    messages: getConversation(),
                }),
            });
        }

        if (!response.ok) {
            const errorText = await response.text();
            contentBody.classList.remove('is-streaming');
            contentBody.innerHTML = `Error: ${response.status} — ${errorText}`;
            stopBusyTimer();
            setComposerStatus('Request failed.', '');
            return;
        }
        if (capability === 'stt') {
            setComposerStatus('Receiving transcript…', 'busy');
        }

        const stream = createStreamRenderer(contentBody);
        stream.set('');

        const result = await readChatStream(response, {
            signal: abort.signal,
            controller: abort,
            isUserStop: () => userRequestedStop,
            onChunk: (chunk) => stream.append(chunk),
        });

        if (userRequestedStop || result.reason === 'aborted') {
            return;
        }

        if (result.reason === 'error' && !result.text) {
            throw result.error || new Error('Stream failed');
        }

        const finalText = finalizeStreamText(result.text, result.reason, statusText);
        contentBody.classList.remove('is-streaming');
        stream.set(finalText);
        const rawContent = stream.finish();

        if (result.reason === 'idle') {
            setComposerStatus('Reply stalled or timed out.', '');
        } else if (result.reason === 'hard_timeout') {
            setComposerStatus('Reply timed out.', '');
        }

        addMessage({
            role: 'assistant',
            content: rawContent,
            ai: selectedAI,
        });
        lastSentPrompt = '';
        lastSentUserContent = '';
    } catch (err) {
        if (err?.name === 'AbortError' || abort.signal.aborted || userRequestedStop) {
            console.info('Chat request cancelled');
            return;
        }
        console.error('Chat request failed:', err);
        contentBody.classList.remove('is-streaming');
        contentBody.textContent = `Error: ${err.message || 'Could not connect to AI. Check console.'}`;
        if (capability === 'stt' && audioForRequest) {
            openProcessAudioModal(audioForRequest, {
                fromRecord: /^recording-/i.test(audioForRequest.name || ''),
            });
        }
    } finally {
        if (activeAbort === abort) activeAbort = null;
        stopBusyTimer();
        if (!getIsDictating()) setComposerStatus('', '');
        if (sending || sendBtn?.classList.contains('is-stop')) {
            setSending(false);
        }
        userRequestedStop = false;
    }
}

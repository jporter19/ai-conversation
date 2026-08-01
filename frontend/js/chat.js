// frontend/js/chat.js
// Purpose: Handles send message, reset, and store modal logic

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
    STORAGE_KEY,
    STORAGE_AI_KEY,
    STORAGE_MODEL_KEY,
    DEFAULT_AI,
    DEFAULT_GROK_MODEL,
    catalog,
    populateProviders,
    populateModels,
    getModelsForProvider,
    getProvider,
    getModelCapability,
} from './config.js';

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
const audioAttachBar  = document.getElementById('audio-attach-bar');
const audioFileInput  = document.getElementById('audio-file-input');
const audioPickBtn    = document.getElementById('audio-pick-btn');
const audioRecordBtn  = document.getElementById('audio-record-btn');
const audioRecordingHint = document.getElementById('audio-recording-hint');
const micBtn          = document.getElementById('mic-btn');
const composerStatus  = document.getElementById('composer-status');
const sttProcessModal = document.getElementById('stt-process-modal');
const sttProcessTitle = document.getElementById('stt-process-title');
const sttProcessDetail = document.getElementById('stt-process-detail');
const sttProcessMeta = document.getElementById('stt-process-meta');
const sttProcessYes = document.getElementById('stt-process-yes');
const sttProcessNo = document.getElementById('stt-process-no');
const storeTranscriptBtn = document.getElementById('store-transcript-btn');
const storeAudioBtn   = document.getElementById('store-audio-btn');
const storePhotosBtn  = document.getElementById('store-photos-btn');

/** In-flight guard: only one stream at a time (issue #7). */
let sending = false;
/** @type {AbortController|null} */
let activeAbort = null;
/** Last prompt sent — restored into the box if user stops generation. */
let lastSentPrompt = '';
/** Full user turn content (may include [Audio: …] prefix for STT). */
let lastSentUserContent = '';
/** True when the user clicked Stop (square); sendMessage cleanup uses this. */
let userRequestedStop = false;

/** @type {File|null} audio waiting for process-confirm modal (not yet sent) */
let stagedAudioFile = null;
/** @type {MediaRecorder|null} */
let mediaRecorder = null;
/** @type {MediaStream|null} */
let mediaStream = null;
/** @type {Blob[]} */
let recordChunks = [];
/** 'clip' = STT model full transcript in chat; 'mic' = dictate into input via STT API */
let recordPurpose = null;
let isRecording = false;
/** Mic session active (listening or transcribing for input box) */
let isDictating = false;
/** Text already in the input when mic session started */
let dictationBaseText = '';
/** @type {ReturnType<typeof setInterval>|null} */
let busyTimer = null;
let busyStartedAt = 0;
/** Avoid overlapping partial STT requests while mic is open */
let micPartialBusy = false;

const STOP_BTN_HTML = '<span class="stop-square" aria-hidden="true"></span>';

function setSending(on) {
    sending = !!on;
    if (sendBtn) {
        // Stay clickable while sending so user can hit Stop
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
        // Keep input enabled so user can keep typing; we still block double-send via `sending`
        userInput.disabled = false;
        userInput.setAttribute('aria-busy', sending ? 'true' : 'false');
    }
    // Avoid mid-stream provider/model switches (request already in flight)
    if (aiSelect) aiSelect.disabled = sending;
    if (modelSelect) modelSelect.disabled = sending;
    if (audioPickBtn) audioPickBtn.disabled = sending || isRecording || isDictating;
    if (audioRecordBtn) audioRecordBtn.disabled = sending || isDictating;
    // Mic stays clickable while dictating so user can stop; disabled only for chat stream or clip capture
    if (micBtn) micBtn.disabled = sending || (isRecording && recordPurpose === 'clip');
}

function formatBytes(n) {
    if (!n || n < 1024) return `${n || 0} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
    return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function fromRecordLabel(file) {
    const name = file?.name || 'audio';
    if (/^recording-/i.test(name)) return '[Voice recording]';
    return `[Audio: ${name}]`;
}

function isSttMode() {
    const ai = aiSelect?.value?.trim() || '';
    const model = modelSelect?.value?.trim() || '';
    return getModelCapability(model, ai) === 'stt';
}

/**
 * Resolve an STT backend for API calls without changing the UI dropdowns.
 * Prefers STT models under the currently selected provider, then any provider.
 */
function resolveSttBackend() {
    const providers = catalog?.providers || [];
    const currentAi = aiSelect?.value?.trim() || '';
    const order = [
        ...providers.filter(p => p.id === currentAi && p.enabled !== false),
        ...providers.filter(p => p.id !== currentAi && p.enabled !== false),
    ];
    for (const p of order) {
        const models = p.models || [];
        const stt = models.find(m => (m.capability || getModelCapability(m.value, p.id)) === 'stt');
        if (stt) {
            return {
                ai: p.id,
                model: stt.value,
                label: p.label || p.id,
                modelLabel: stt.label || stt.value,
            };
        }
    }
    return null;
}

/** Find first STT model for UI selection (scenario 2 only). */
function findSttSelection() {
    const backend = resolveSttBackend();
    if (!backend) return null;
    return { ai: backend.ai, model: backend.model, label: backend.modelLabel };
}

/**
 * Switch dropdowns to an STT model (only when user explicitly uses Record clip / Attach).
 * @param {{ silent?: boolean }} [opts]
 */
function ensureSttModelSelected(opts = {}) {
    if (isSttMode()) return true;
    const pick = findSttSelection();
    if (!pick) {
        if (!opts.silent) {
            alert(
                'No Speech-to-Text model is configured.\n\n'
                + 'Open Admin Tools → Models and add a model with capability “stt” '
                + '(e.g. Grok Speech-to-Text).'
            );
        }
        return false;
    }
    if (aiSelect) {
        aiSelect.value = pick.ai;
        localStorage.setItem(STORAGE_AI_KEY, pick.ai);
        const models = getModelsForProvider(pick.ai);
        populateModels(models, pick.model);
    }
    if (modelSelect) {
        modelSelect.value = pick.model;
        localStorage.setItem(STORAGE_MODEL_KEY, pick.model);
    }
    updateComposerForCapability();
    return true;
}

/**
 * Call STT API without changing the selected chat AI/model in the UI.
 * Returns transcript text or throws.
 */
async function transcribeWithSttApi(file, { signal } = {}) {
    const backend = resolveSttBackend();
    if (!backend) {
        throw new Error(
            'No Speech-to-Text model is configured. Add one under Admin → Models (capability “stt”).'
        );
    }
    const form = new FormData();
    form.append('ai', backend.ai);
    form.append('model', backend.model);
    form.append('file', file, file.name || 'audio.webm');
    const res = await fetch('/api/v1/transcribe', {
        method: 'POST',
        credentials: 'same-origin',
        signal,
        body: form,
    });
    if (!res.ok) {
        const errText = await res.text();
        throw new Error(errText || `STT failed (${res.status})`);
    }
    // Handler streams markdown; pull plain transcript text out
    const raw = await res.text();
    return extractTranscriptFromSttResponse(raw);
}

function extractTranscriptFromSttResponse(raw) {
    const text = String(raw || '');
    // Prefer ### Transcript section from SttHandler
    const m = text.match(/###\s*Transcript\s*\n+([\s\S]*?)(?:\n---|\n_|\n<!--|$)/i);
    if (m) {
        const body = m[1].trim();
        if (body && !/^_No speech/i.test(body)) return body;
        return '';
    }
    // Fallback: strip status line and markdown chrome
    return text
        .replace(/\*\*Transcription[^*]*\*\*[^\n]*/gi, '')
        .replace(/Transcribing[\s\S]*?\n\n/i, '')
        .replace(/<!--[\s\S]*?-->/g, '')
        .replace(/^#+\s*.*$/gm, '')
        .trim();
}

function setComposerStatus(msg, kind = '') {
    if (!composerStatus) return;
    if (!msg) {
        composerStatus.hidden = true;
        composerStatus.textContent = '';
        composerStatus.className = 'composer-status';
        return;
    }
    composerStatus.hidden = false;
    composerStatus.textContent = msg;
    composerStatus.className = 'composer-status'
        + (kind === 'listening' ? ' is-listening' : '')
        + (kind === 'busy' ? ' is-busy' : '');
}

function startBusyTimer(label) {
    stopBusyTimer();
    busyStartedAt = Date.now();
    const tick = () => {
        const sec = Math.floor((Date.now() - busyStartedAt) / 1000);
        setComposerStatus(`${label} (${sec}s)`, 'busy');
    };
    tick();
    busyTimer = setInterval(tick, 1000);
}

function stopBusyTimer() {
    if (busyTimer) {
        clearInterval(busyTimer);
        busyTimer = null;
    }
}

function discardStagedAudio() {
    stagedAudioFile = null;
    if (audioFileInput) audioFileInput.value = '';
}

function setRecordingUi(on) {
    if (audioRecordBtn) {
        audioRecordBtn.classList.toggle('is-recording', on);
        audioRecordBtn.textContent = on ? '⏹ Stop clip' : '⏺ Record clip';
        audioRecordBtn.title = on ? 'Stop recording' : 'Record a full clip to transcribe';
    }
    if (audioRecordingHint) audioRecordingHint.hidden = !on;
    if (audioPickBtn) audioPickBtn.disabled = on || sending || isDictating;
}

// ── Scenario 1: Mic → STT API → text in input (keeps selected AI) ─────────────

function setMicUi(on) {
    micBtn?.classList.toggle('is-listening', on);
    userInput?.classList.toggle('is-dictating', on);
    if (micBtn) {
        micBtn.title = on
            ? 'Stop listening (will transcribe into the box)'
            : 'Speak instead of typing (uses STT API, keeps your selected AI)';
    }
}

/**
 * Start mic capture. Does NOT change AI/model dropdowns.
 * Click again to stop → STT API fills the input box.
 */
async function startMicDictation() {
    if (isDictating || sending || isRecording) return;
    if (!resolveSttBackend()) {
        alert(
            'No Speech-to-Text model is configured for the API.\n\n'
            + 'Add one under Admin → Models with capability “stt” '
            + '(e.g. Grok Speech-to-Text). Your chat AI can stay selected — '
            + 'only the mic uses STT in the background.'
        );
        return;
    }
    if (!navigator.mediaDevices?.getUserMedia) {
        alert('Microphone is not available in this browser.');
        return;
    }

    dictationBaseText = (userInput?.value || '').replace(/\s+$/, '');
    isDictating = true;
    recordPurpose = 'mic';
    setMicUi(true);
    startBusyTimer('Listening');
    if (micBtn) micBtn.disabled = false;

    try {
        await beginMediaCapture({
            purpose: 'mic',
            onStop: async (file, discarded) => {
                isDictating = false;
                setMicUi(false);
                if (discarded || !file?.size) {
                    stopBusyTimer();
                    setComposerStatus('Mic cancelled.', '');
                    setTimeout(() => setComposerStatus('', ''), 2500);
                    return;
                }
                startBusyTimer('Transcribing with STT API (your chat AI stays selected)');
                try {
                    const transcript = await transcribeWithSttApi(file);
                    const spoken = (transcript || '').trim();
                    if (userInput) {
                        if (spoken) {
                            const sep = dictationBaseText && !/\s$/.test(dictationBaseText) ? ' ' : '';
                            userInput.value = `${dictationBaseText}${sep}${spoken}`.trim();
                            userInput.focus();
                        }
                    }
                    stopBusyTimer();
                    setComposerStatus(
                        spoken
                            ? 'Transcript ready in the box — edit if needed, then Send to your selected AI.'
                            : 'No speech detected. Try again closer to the mic.',
                        ''
                    );
                    setTimeout(() => {
                        if (!isDictating && !sending) setComposerStatus('', '');
                    }, 5000);
                } catch (e) {
                    stopBusyTimer();
                    setComposerStatus(`Transcription failed: ${e.message || e}`, '');
                }
            },
        });
    } catch (e) {
        isDictating = false;
        recordPurpose = null;
        setMicUi(false);
        stopBusyTimer();
        setComposerStatus(`Could not start mic: ${e.message || e}`, '');
    }
}

function stopMicDictation({ discard = false } = {}) {
    if (!isDictating && recordPurpose !== 'mic') return;
    // stopRecording triggers onStop which transcribes (unless discard)
    stopRecording({ discard });
}

function toggleDictation() {
    if (isDictating || (isRecording && recordPurpose === 'mic')) {
        stopMicDictation({ discard: false });
    } else {
        void startMicDictation();
    }
}

/**
 * Shared MediaRecorder start for mic (dictate) and clip (STT model).
 * @param {{ purpose: 'mic'|'clip', onStop: (file: File|null, discarded: boolean) => void }} opts
 */
async function beginMediaCapture(opts) {
    const { purpose, onStop } = opts;
    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    recordChunks = [];
    recordPurpose = purpose;
    const mime = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : (MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : '');
    mediaRecorder = mime
        ? new MediaRecorder(mediaStream, { mimeType: mime })
        : new MediaRecorder(mediaStream);
    mediaRecorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) recordChunks.push(e.data);
    };
    const chosenType = mediaRecorder.mimeType || mime || 'audio/webm';
    mediaRecorder.onstop = () => {
        const discarded = mediaRecorder?.__discard === true;
        const blob = new Blob(recordChunks, { type: chosenType });
        cleanupMediaStream();
        isRecording = false;
        recordPurpose = null;
        setRecordingUi(false);
        if (discarded || !blob.size) {
            onStop?.(null, true);
            return;
        }
        const ext = chosenType.includes('ogg') ? 'ogg' : 'webm';
        const file = new File([blob], `recording-${Date.now()}.${ext}`, { type: chosenType });
        onStop?.(file, false);
    };
    // 1s timeslices so we always have data if user stops quickly
    mediaRecorder.start(1000);
    isRecording = true;
    if (purpose === 'clip') setRecordingUi(true);
}

/**
 * After record/attach: ask user whether to process. Yes → submit STT. No → discard.
 */
function openProcessAudioModal(file, { fromRecord = false } = {}) {
    if (!file || !sttProcessModal) return;
    stagedAudioFile = file;
    if (sttProcessTitle) {
        sttProcessTitle.textContent = fromRecord
            ? 'Process this recording?'
            : 'Process this audio file?';
    }
    if (sttProcessDetail) {
        sttProcessDetail.textContent = fromRecord
            ? 'Transcribe what you just recorded and show the result in the chat.'
            : 'Transcribe the selected audio file and show the result in the chat.';
    }
    if (sttProcessMeta) {
        const kind = fromRecord ? 'Recording' : 'File';
        sttProcessMeta.textContent = `${kind}: ${file.name || 'audio'} · ${formatBytes(file.size)}`;
    }
    if (typeof sttProcessModal.showModal === 'function') {
        sttProcessModal.showModal();
    } else {
        // Fallback without <dialog>
        if (confirm(`${sttProcessTitle?.textContent || 'Process audio?'}\n\n${sttProcessMeta?.textContent || ''}`)) {
            void submitStagedAudio();
        } else {
            discardStagedAudio();
        }
    }
}

function closeProcessAudioModal() {
    try {
        sttProcessModal?.close();
    } catch (_) { /* ignore */ }
}

async function submitStagedAudio() {
    const file = stagedAudioFile;
    closeProcessAudioModal();
    if (!file) return;
    if (!ensureSttModelSelected()) {
        discardStagedAudio();
        return;
    }
    // sendMessage reads stagedAudioFile for STT
    await sendMessage({ audioFile: file });
    discardStagedAudio();
}

/**
 * Show/hide STT composer chrome based on selected model capability.
 * Call when AI or model changes.
 */
export function updateComposerForCapability() {
    const ai = aiSelect?.value?.trim() || '';
    const model = modelSelect?.value?.trim() || '';
    const cap = getModelCapability(model, ai);
    // Strict: only show clip tools when capability is exactly STT
    const isStt = cap === 'stt' && !!model;

    // Scenario 2 only: Record clip + Attach when STT model is selected
    if (audioAttachBar) {
        audioAttachBar.hidden = !isStt;
        audioAttachBar.classList.toggle('is-visible', isStt);
        // Defense: if not STT, force-hide even if CSS fights [hidden]
        audioAttachBar.style.display = isStt ? '' : 'none';
    }
    if (audioPickBtn) {
        audioPickBtn.hidden = !isStt;
        audioPickBtn.style.display = isStt ? '' : 'none';
    }
    if (audioRecordBtn) {
        audioRecordBtn.hidden = !isStt;
        audioRecordBtn.style.display = isStt ? '' : 'none';
    }

    if (userInput) {
        if (isDictating) {
            userInput.placeholder = 'Listening… click the mic again when done — text will appear after STT finishes';
            userInput.classList.add('is-dictating');
            userInput.classList.remove('composer-stt');
        } else if (isStt) {
            userInput.placeholder = 'Optional notes… then Record clip or Attach — confirm to save transcript in chat';
            userInput.classList.add('composer-stt');
            userInput.classList.remove('is-dictating');
        } else {
            userInput.placeholder = 'Type your message, or click 🎤 to speak (keeps this AI selected)…';
            userInput.classList.remove('composer-stt');
            userInput.classList.remove('is-dictating');
            // Leaving STT model: stop clip capture only (not mic — mic doesn't change model)
            if (isRecording && recordPurpose === 'clip') stopRecording({ discard: true });
            if (!sttProcessModal?.open) discardStagedAudio();
        }
    }
}

async function startRecording() {
    // Scenario 2 only — requires STT model already selected (bar is hidden otherwise)
    if (isRecording || sending || isDictating) return;
    if (!isSttMode()) {
        alert('Select a Speech-to-Text model first to record a full transcript clip.');
        return;
    }
    if (!navigator.mediaDevices?.getUserMedia) {
        alert('Microphone recording is not supported in this browser. Use Attach audio instead.');
        return;
    }
    try {
        await beginMediaCapture({
            purpose: 'clip',
            onStop: (file, discarded) => {
                if (discarded || !file) return;
                openProcessAudioModal(file, { fromRecord: true });
            },
        });
        setComposerStatus('Recording clip… click Stop when finished', 'listening');
    } catch (e) {
        cleanupMediaStream();
        isRecording = false;
        setRecordingUi(false);
        alert(`Could not access microphone: ${e.message || e}`);
    }
}

function cleanupMediaStream() {
    if (mediaStream) {
        mediaStream.getTracks().forEach(t => t.stop());
        mediaStream = null;
    }
    mediaRecorder = null;
    recordChunks = [];
}

/**
 * @param {{ discard?: boolean }} [opts]
 */
function stopRecording(opts = {}) {
    const discard = !!opts.discard;
    if (!isRecording || !mediaRecorder) {
        cleanupMediaStream();
        isRecording = false;
        recordPurpose = null;
        setRecordingUi(false);
        setMicUi(false);
        return;
    }
    try {
        mediaRecorder.__discard = discard;
        if (mediaRecorder.state !== 'inactive') {
            mediaRecorder.stop();
        } else {
            cleanupMediaStream();
            isRecording = false;
            recordPurpose = null;
            setRecordingUi(false);
            setMicUi(false);
        }
    } catch (_) {
        cleanupMediaStream();
        isRecording = false;
        recordPurpose = null;
        setRecordingUi(false);
        setMicUi(false);
    }
}

function toggleRecording() {
    if (isRecording && recordPurpose === 'clip') stopRecording({ discard: false });
    else if (!isRecording) void startRecording();
}

function initAudioControls() {
    // Scenario 1: mic → STT API → text in input (does not change selected AI)
    micBtn?.addEventListener('click', () => toggleDictation());

    // Scenario 2: Record clip / Attach only when STT model is selected (bar is hidden otherwise)
    audioPickBtn?.addEventListener('click', () => {
        if (!isSttMode()) return;
        audioFileInput?.click();
    });
    audioFileInput?.addEventListener('change', () => {
        const f = audioFileInput.files?.[0];
        if (audioFileInput) audioFileInput.value = '';
        if (!f || !isSttMode()) return;
        openProcessAudioModal(f, { fromRecord: false });
    });
    audioRecordBtn?.addEventListener('click', () => {
        if (!isSttMode()) return;
        toggleRecording();
    });

    sttProcessYes?.addEventListener('click', () => {
        void submitStagedAudio();
    });
    sttProcessNo?.addEventListener('click', () => {
        discardStagedAudio();
        closeProcessAudioModal();
    });
    sttProcessModal?.addEventListener('cancel', (e) => {
        e.preventDefault();
        discardStagedAudio();
        closeProcessAudioModal();
    });

    // Drag & drop audio only in STT (clip) mode
    const dropTarget = document.querySelector('.input-area');
    if (dropTarget) {
        ['dragenter', 'dragover'].forEach(ev => {
            dropTarget.addEventListener(ev, (e) => {
                if (!isSttMode()) return;
                e.preventDefault();
                dropTarget.classList.add('drag-over');
            });
        });
        ['dragleave', 'drop'].forEach(ev => {
            dropTarget.addEventListener(ev, () => {
                dropTarget.classList.remove('drag-over');
            });
        });
        dropTarget.addEventListener('drop', (e) => {
            if (!isSttMode()) return;
            e.preventDefault();
            const f = e.dataTransfer?.files?.[0];
            if (f) openProcessAudioModal(f, { fromRecord: false });
        });
    }
}

function abortActiveRequest() {
    if (activeAbort) {
        try {
            activeAbort.abort();
        } catch (_) {
            /* ignore */
        }
        activeAbort = null;
    }
    setSending(false);
}

/**
 * Stop generation: abort stream, restore last prompt to the box, remove the
 * aborted user turn from conversation history.
 */
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
            // Place caret at end
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

export function initChat() {
    sendBtn.addEventListener('click', () => {
        if (sending) {
            stopGeneration();
        } else {
            sendMessage();
        }
    });
    userInput.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            // While generating, Enter does not send again (use Stop square)
            if (sending) return;
            sendMessage();
        }
    });

    initAudioControls();
    updateComposerForCapability();

    // Reset with nice modal
    resetBtn.addEventListener('click', () => {
        resetModal.showModal();
    });

    resetConfirmBtn.addEventListener('click', () => {
        // Cancel any in-flight stream so it cannot append after clear
        abortActiveRequest();

        clearConversation();
        renderHistory();

        // Clear stored AI/model selection
        localStorage.removeItem(STORAGE_KEY);
        localStorage.removeItem(STORAGE_AI_KEY);
        localStorage.removeItem(STORAGE_MODEL_KEY);

        // Restore defaults from catalog preferences
        const prefs = catalog?.preferences || {};
        const ai = prefs.default_ai || DEFAULT_AI;
        const model = prefs.default_model || DEFAULT_GROK_MODEL;
        populateProviders(aiSelect, ai);
        populateModels(getModelsForProvider(aiSelect.value), model);

        localStorage.setItem(STORAGE_AI_KEY, aiSelect.value || ai);
        localStorage.setItem(STORAGE_MODEL_KEY, modelSelect.value || model);

        renderHistory();
        updateComposerForCapability();

        resetModal.close();
    });

    resetCancelBtn.addEventListener('click', () => {
        resetModal.close();
    });

    resetModal.addEventListener('click', e => {
        if (e.target === resetModal) resetModal.close();
    });

    // Store modal
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
            // Suggest a name from first user message
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

    modalCancelBtn.addEventListener('click', () => {
        storeModal.close();
    });

    storeModal.addEventListener('click', e => {
        if (e.target === storeModal) storeModal.close();
    });

    storeNameInput?.addEventListener('keydown', e => {
        if (e.key === 'Enter') {
            e.preventDefault();
            storeCurrentConversation('whole');
        }
    });

    // Restore modal
    restoreBtn?.addEventListener('click', () => {
        openRestoreModal();
    });
    restoreCloseBtn?.addEventListener('click', () => restoreModal?.close());
    restoreModal?.addEventListener('click', e => {
        if (e.target === restoreModal) restoreModal.close();
    });

    // No model selected modal
    const noModelModal = document.getElementById('no-model-modal');
    const noModelOkBtn = document.getElementById('no-model-ok-btn');

    noModelOkBtn.addEventListener('click', () => {
        noModelModal.close();
    });

    noModelModal.addEventListener('click', e => {
        if (e.target === noModelModal) noModelModal.close();
    });
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

// Complete sendMessage() — single in-flight request (sending guard + AbortController)
// opts.audioFile: when set (from process modal), run STT with that file.

async function sendMessage(opts = {}) {
    // Issue #7: ignore re-entrant Send / Enter while a response is streaming
    if (sending) return;

    // Don't intercept an in-progress recording with Send — user should Stop first
    if (isRecording && !opts.audioFile) {
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
        const noModelModal = document.getElementById('no-model-modal');
        noModelModal.showModal();
        return;
    }

    // Capability is authoritative on the server (catalog); UI only adjusts status text.
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
        : capability === 'transcript' ? 'Fetching transcript…'
        : capability === 'stt' ? '⏳ Grok is transcribing your audio — this can take a while…'
        : capability === 'tts' ? 'Generating speech…'
        : 'Thinking…';

    // User-visible content for history
    let userContent = text;
    if (capability === 'stt' && audioForRequest) {
        userContent = fromRecordLabel(audioForRequest);
        if (text) userContent += `\n${text}`;
    }

    // Lock UI before mutating conversation so a second click cannot interleave
    const abort = new AbortController();
    activeAbort = abort;
    userRequestedStop = false;
    lastSentPrompt = text;
    lastSentUserContent = userContent;
    if (isDictating || (isRecording && recordPurpose === 'mic')) {
        stopMicDictation({ discard: true });
    }
    setSending(true);
    if (capability === 'stt') {
        startBusyTimer('Grok is processing your speech');
    } else {
        setComposerStatus(statusText, 'busy');
    }

    // Add user message to conversation and re-render
    addMessage({ role: 'user', content: userContent });
    renderHistory();

    // Clear input — restored if user hits Stop
    userInput.value = '';
    if (capability === 'stt') {
        discardStagedAudio();
    }

    // Create assistant message bubble immediately (with badge)
    const assistantDiv = document.createElement('div');
    assistantDiv.classList.add('message', 'ai-message');

    // Add AI badge
    const badgeInfo = badgeForAi(selectedAI);
    const badge = document.createElement('div');
    badge.className = 'ai-badge';
    badge.textContent = badgeInfo.text;
    badge.style.backgroundColor = badgeInfo.color;
    badge.style.color = 'white';
    assistantDiv.prepend(badge);

    // Live-formatted message body — one path for chat / image / transcript / stt
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
            // Backend dispatches by model capability from the provider catalog.
            response = await fetch('/api/v1/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                signal: abort.signal,
                body: JSON.stringify({
                    ai: selectedAI,
                    model: selectedModel,
                    messages: getConversation()
                })
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

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        const stream = createStreamRenderer(contentBody);

        stream.set('');

        try {
            while (true) {
                if (abort.signal.aborted) {
                    await reader.cancel().catch(() => {});
                    break;
                }
                const { done, value } = await reader.read();
                if (done) break;
                const chunk = decoder.decode(value, { stream: true });
                if (chunk) stream.append(chunk);
            }
        } catch (readErr) {
            if (readErr?.name === 'AbortError' || abort.signal.aborted) {
                throw readErr;
            }
            throw readErr;
        }

        if (abort.signal.aborted || userRequestedStop) {
            // stopGeneration already restored the prompt + rewound conversation
            return;
        }

        const tail = decoder.decode();
        if (tail) stream.append(tail);

        const rawContent = stream.finish();

        addMessage({
            role: 'assistant',
            content: rawContent,
            ai: selectedAI
        });
        lastSentPrompt = '';
        lastSentUserContent = '';
    } catch (err) {
        if (err?.name === 'AbortError' || abort.signal.aborted || userRequestedStop) {
            // User hit Stop — prompt already restored by stopGeneration()
            console.info('Chat request cancelled');
            return;
        }
        console.error('Chat request failed:', err);
        contentBody.classList.remove('is-streaming');
        contentBody.textContent = `Error: ${err.message || 'Could not connect to AI. Check console.'}`;
        // Offer to retry the same audio
        if (capability === 'stt' && audioForRequest) {
            stagedAudioFile = audioForRequest;
            openProcessAudioModal(audioForRequest, {
                fromRecord: /^recording-/i.test(audioForRequest.name || ''),
            });
        }
    } finally {
        if (activeAbort === abort) {
            activeAbort = null;
        }
        stopBusyTimer();
        if (!isDictating) setComposerStatus('', '');
        // Only reset the button if stopGeneration didn't already (or request finished)
        if (sending || sendBtn?.classList.contains('is-stop')) {
            setSending(false);
        }
        userRequestedStop = false;
    }
}
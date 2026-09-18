// frontend/js/chat/stt.js
// Purpose: Mic dictation, clip record/attach, STT process modal, composer chrome.

import {
    catalog,
    currentUserId,
    populateModels,
    getModelsForProvider,
    getModelCapability,
} from '../config.js';
import { writeItem, SUFFIX_AI, SUFFIX_MODEL } from '../user_storage.js';

/** @typedef {{
 *   getSending: () => boolean,
 *   sendWithAudio: (file: File) => Promise<void>,
 * }} SttDeps
 */

/** @type {SttDeps|null} */
let deps = null;

const audioAttachBar = () => document.getElementById('audio-attach-bar');
const audioFileInput = () => document.getElementById('audio-file-input');
const audioPickBtn = () => document.getElementById('audio-pick-btn');
const audioRecordBtn = () => document.getElementById('audio-record-btn');
const audioRecordingHint = () => document.getElementById('audio-recording-hint');
const micBtn = () => document.getElementById('mic-btn');
const composerStatus = () => document.getElementById('composer-status');
const sttProcessModal = () => document.getElementById('stt-process-modal');
const sttProcessTitle = () => document.getElementById('stt-process-title');
const sttProcessDetail = () => document.getElementById('stt-process-detail');
const sttProcessMeta = () => document.getElementById('stt-process-meta');
const sttProcessYes = () => document.getElementById('stt-process-yes');
const sttProcessNo = () => document.getElementById('stt-process-no');
const userInput = () => document.getElementById('user-input');
const aiSelect = () => document.getElementById('ai-select');
const modelSelect = () => document.getElementById('model-select');

/** @type {File|null} */
let stagedAudioFile = null;
/** @type {MediaRecorder|null} */
let mediaRecorder = null;
/** @type {MediaStream|null} */
let mediaStream = null;
/** @type {Blob[]} */
let recordChunks = [];
/** @type {'clip'|'mic'|null} */
let recordPurpose = null;
let isRecording = false;
let isDictating = false;
let dictationBaseText = '';
/** @type {ReturnType<typeof setInterval>|null} */
let busyTimer = null;
let busyStartedAt = 0;

export function getIsRecording() { return isRecording; }
export function getIsDictating() { return isDictating; }
export function getRecordPurpose() { return recordPurpose; }
export function getStagedAudioFile() { return stagedAudioFile; }

export function formatBytes(n) {
    if (!n || n < 1024) return `${n || 0} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
    return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export function fromRecordLabel(file) {
    const name = file?.name || 'audio';
    if (/^recording-/i.test(name)) return '[Voice recording]';
    return `[Audio: ${name}]`;
}

export function isSttMode() {
    const ai = aiSelect()?.value?.trim() || '';
    const model = modelSelect()?.value?.trim() || '';
    return getModelCapability(model, ai) === 'stt';
}

export function setComposerStatus(msg, kind = '') {
    const el = composerStatus();
    if (!el) return;
    if (!msg) {
        el.hidden = true;
        el.textContent = '';
        el.className = 'composer-status';
        return;
    }
    el.hidden = false;
    el.textContent = msg;
    el.className = 'composer-status'
        + (kind === 'listening' ? ' is-listening' : '')
        + (kind === 'busy' ? ' is-busy' : '');
}

export function startBusyTimer(label) {
    stopBusyTimer();
    busyStartedAt = Date.now();
    const tick = () => {
        const sec = Math.floor((Date.now() - busyStartedAt) / 1000);
        setComposerStatus(`${label} (${sec}s)`, 'busy');
    };
    tick();
    busyTimer = setInterval(tick, 1000);
}

export function stopBusyTimer() {
    if (busyTimer) {
        clearInterval(busyTimer);
        busyTimer = null;
    }
}

export function discardStagedAudio() {
    stagedAudioFile = null;
    const input = audioFileInput();
    if (input) input.value = '';
}

function setRecordingUi(on) {
    const btn = audioRecordBtn();
    if (btn) {
        btn.classList.toggle('is-recording', on);
        btn.textContent = on ? '⏹ Stop clip' : '⏺ Record clip';
        btn.title = on ? 'Stop recording' : 'Record a full clip to transcribe';
    }
    const hint = audioRecordingHint();
    if (hint) hint.hidden = !on;
    const pick = audioPickBtn();
    if (pick) pick.disabled = on || !!deps?.getSending() || isDictating;
}

function setMicUi(on) {
    micBtn()?.classList.toggle('is-listening', on);
    userInput()?.classList.toggle('is-dictating', on);
    const btn = micBtn();
    if (btn) {
        btn.title = on
            ? 'Stop listening (will transcribe into the box)'
            : 'Speak instead of typing (uses STT API, keeps your selected AI)';
    }
}

/**
 * Resolve an STT backend without changing UI dropdowns.
 */
export function resolveSttBackend() {
    const providers = catalog?.providers || [];
    const currentAi = aiSelect()?.value?.trim() || '';
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

function findSttSelection() {
    const backend = resolveSttBackend();
    if (!backend) return null;
    return { ai: backend.ai, model: backend.model, label: backend.modelLabel };
}

export function ensureSttModelSelected(opts = {}) {
    if (isSttMode()) return true;
    const pick = findSttSelection();
    if (!pick) {
        if (!opts.silent) {
            alert(
                'No Speech-to-Text model is configured.\n\n'
                + 'Open Admin Tools → Models and add a model with capability “stt” '
                + '(e.g. Grok Speech-to-Text).',
            );
        }
        return false;
    }
    const aiEl = aiSelect();
    if (aiEl) {
        aiEl.value = pick.ai;
        const uid = currentUserId();
        if (uid) writeItem(uid, SUFFIX_AI, pick.ai);
        const models = getModelsForProvider(pick.ai);
        populateModels(models, pick.model);
    }
    const modelEl = modelSelect();
    if (modelEl) {
        modelEl.value = pick.model;
        const uid = currentUserId();
        if (uid) writeItem(uid, SUFFIX_MODEL, pick.model);
    }
    updateComposerForCapability();
    return true;
}

async function transcribeWithSttApi(file, { signal } = {}) {
    const backend = resolveSttBackend();
    if (!backend) {
        throw new Error(
            'No Speech-to-Text model is configured. Add one under Admin → Models (capability “stt”).',
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
    const raw = await res.text();
    return extractTranscriptFromSttResponse(raw);
}

function extractTranscriptFromSttResponse(raw) {
    const text = String(raw || '');
    const m = text.match(/###\s*Transcript\s*\n+([\s\S]*?)(?:\n---|\n_|\n<!--|$)/i);
    if (m) {
        const body = m[1].trim();
        if (body && !/^_No speech/i.test(body)) return body;
        return '';
    }
    return text
        .replace(/\*\*Transcription[^*]*\*\*[^\n]*/gi, '')
        .replace(/Transcribing[\s\S]*?\n\n/i, '')
        .replace(/<!--[\s\S]*?-->/g, '')
        .replace(/^#+\s*.*$/gm, '')
        .trim();
}

async function startMicDictation() {
    if (isDictating || deps?.getSending() || isRecording) return;
    if (!resolveSttBackend()) {
        alert(
            'No Speech-to-Text model is configured for the API.\n\n'
            + 'Add one under Admin → Models with capability “stt” '
            + '(e.g. Grok Speech-to-Text). Your chat AI can stay selected — '
            + 'only the mic uses STT in the background.',
        );
        return;
    }
    if (!navigator.mediaDevices?.getUserMedia) {
        alert('Microphone is not available in this browser.');
        return;
    }

    dictationBaseText = (userInput()?.value || '').replace(/\s+$/, '');
    isDictating = true;
    recordPurpose = 'mic';
    setMicUi(true);
    startBusyTimer('Listening');
    const btn = micBtn();
    if (btn) btn.disabled = false;

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
                    const input = userInput();
                    if (input) {
                        if (spoken) {
                            const sep = dictationBaseText && !/\s$/.test(dictationBaseText) ? ' ' : '';
                            input.value = `${dictationBaseText}${sep}${spoken}`.trim();
                            input.focus();
                        }
                    }
                    stopBusyTimer();
                    setComposerStatus(
                        spoken
                            ? 'Transcript ready in the box — edit if needed, then Send to your selected AI.'
                            : 'No speech detected. Try again closer to the mic.',
                        '',
                    );
                    setTimeout(() => {
                        if (!isDictating && !deps?.getSending()) setComposerStatus('', '');
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

export function stopMicDictation({ discard = false } = {}) {
    if (!isDictating && recordPurpose !== 'mic') return;
    stopRecording({ discard });
}

function toggleDictation() {
    if (isDictating || (isRecording && recordPurpose === 'mic')) {
        stopMicDictation({ discard: false });
    } else {
        void startMicDictation();
    }
}

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
    mediaRecorder.start(1000);
    isRecording = true;
    if (purpose === 'clip') setRecordingUi(true);
}

export function openProcessAudioModal(file, { fromRecord = false } = {}) {
    const modal = sttProcessModal();
    if (!file || !modal) return;
    stagedAudioFile = file;
    const title = sttProcessTitle();
    if (title) {
        title.textContent = fromRecord
            ? 'Process this recording?'
            : 'Process this audio file?';
    }
    const detail = sttProcessDetail();
    if (detail) {
        detail.textContent = fromRecord
            ? 'Transcribe what you just recorded and show the result in the chat.'
            : 'Transcribe the selected audio file and show the result in the chat.';
    }
    const meta = sttProcessMeta();
    if (meta) {
        const kind = fromRecord ? 'Recording' : 'File';
        meta.textContent = `${kind}: ${file.name || 'audio'} · ${formatBytes(file.size)}`;
    }
    if (typeof modal.showModal === 'function') {
        modal.showModal();
    } else if (confirm(`${title?.textContent || 'Process audio?'}\n\n${meta?.textContent || ''}`)) {
        void submitStagedAudio();
    } else {
        discardStagedAudio();
    }
}

function closeProcessAudioModal() {
    try {
        sttProcessModal()?.close();
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
    await deps?.sendWithAudio?.(file);
    discardStagedAudio();
}

export function updateComposerForCapability() {
    const ai = aiSelect()?.value?.trim() || '';
    const model = modelSelect()?.value?.trim() || '';
    const cap = getModelCapability(model, ai);
    const isStt = cap === 'stt' && !!model;

    const bar = audioAttachBar();
    if (bar) {
        bar.hidden = !isStt;
        bar.classList.toggle('is-visible', isStt);
        bar.style.display = isStt ? '' : 'none';
    }
    const pick = audioPickBtn();
    if (pick) {
        pick.hidden = !isStt;
        pick.style.display = isStt ? '' : 'none';
    }
    const rec = audioRecordBtn();
    if (rec) {
        rec.hidden = !isStt;
        rec.style.display = isStt ? '' : 'none';
    }

    const input = userInput();
    if (input) {
        if (isDictating) {
            input.placeholder = 'Listening… click the mic again when done — text will appear after STT finishes';
            input.classList.add('is-dictating');
            input.classList.remove('composer-stt');
        } else if (isStt) {
            input.placeholder = 'Optional notes… then Record clip or Attach — confirm to save transcript in chat';
            input.classList.add('composer-stt');
            input.classList.remove('is-dictating');
        } else if (cap === 'video') {
            input.placeholder = 'Video generation is not enabled yet — pick a chat or image model';
            input.classList.remove('composer-stt', 'is-dictating');
        } else {
            input.placeholder = 'Type your message, or click 🎤 to speak (keeps this AI selected)…';
            input.classList.remove('composer-stt');
            input.classList.remove('is-dictating');
            if (isRecording && recordPurpose === 'clip') stopRecording({ discard: true });
            if (!sttProcessModal()?.open) discardStagedAudio();
        }
    }
}

async function startRecording() {
    if (isRecording || deps?.getSending() || isDictating) return;
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

export function stopRecording(opts = {}) {
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

/** Update disabled state of STT buttons from parent setSending. */
export function syncSttControlDisabled(sending) {
    const pick = audioPickBtn();
    if (pick) pick.disabled = sending || isRecording || isDictating;
    const rec = audioRecordBtn();
    if (rec) rec.disabled = sending || isDictating;
    const mic = micBtn();
    if (mic) mic.disabled = sending || (isRecording && recordPurpose === 'clip');
}

/**
 * @param {SttDeps} sttDeps
 */
export function initSttControls(sttDeps) {
    deps = sttDeps;

    micBtn()?.addEventListener('click', () => toggleDictation());

    audioPickBtn()?.addEventListener('click', () => {
        if (!isSttMode()) return;
        audioFileInput()?.click();
    });
    audioFileInput()?.addEventListener('change', () => {
        const input = audioFileInput();
        const f = input?.files?.[0];
        if (input) input.value = '';
        if (!f || !isSttMode()) return;
        openProcessAudioModal(f, { fromRecord: false });
    });
    audioRecordBtn()?.addEventListener('click', () => {
        if (!isSttMode()) return;
        toggleRecording();
    });

    sttProcessYes()?.addEventListener('click', () => {
        void submitStagedAudio();
    });
    sttProcessNo()?.addEventListener('click', () => {
        discardStagedAudio();
        closeProcessAudioModal();
    });
    sttProcessModal()?.addEventListener('cancel', (e) => {
        e.preventDefault();
        discardStagedAudio();
        closeProcessAudioModal();
    });

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

    updateComposerForCapability();
}

// frontend/js/admin/voice.js — TTS voice preferences + preview
import {
    catalog,
    setStatus,
    escapeHtml,
} from './shared.js';

// ── Voice / TTS preferences ───────────────────────────────────────────────────

/** @type {HTMLAudioElement|null} */
let voicePreviewAudio = null;
/** @type {string|null} */
let voicePreviewObjectUrl = null;
/** @type {string|null} voice id currently loading/playing */
let voicePreviewActiveId = null;
/** Bumps on every stop/new preview so in-flight fetches cannot start orphan audio. */
let voicePreviewGeneration = 0;
/** @type {AbortController|null} */
let voicePreviewAbort = null;

function _detachVoicePreviewAudio() {
    if (voicePreviewAudio) {
        try {
            voicePreviewAudio.onplaying = null;
            voicePreviewAudio.onended = null;
            voicePreviewAudio.onerror = null;
            voicePreviewAudio.pause();
            voicePreviewAudio.removeAttribute('src');
            voicePreviewAudio.load();
        } catch (_) { /* ignore */ }
        voicePreviewAudio = null;
    }
    if (voicePreviewObjectUrl) {
        try { URL.revokeObjectURL(voicePreviewObjectUrl); } catch (_) { /* ignore */ }
        voicePreviewObjectUrl = null;
    }
}

export function stopVoicePreview() {
    voicePreviewGeneration += 1;
    if (voicePreviewAbort) {
        try { voicePreviewAbort.abort(); } catch (_) { /* ignore */ }
        voicePreviewAbort = null;
    }
    _detachVoicePreviewAudio();
    voicePreviewActiveId = null;
    document.querySelectorAll('.voice-row.is-playing, .voice-row.is-loading').forEach(el => {
        el.classList.remove('is-playing', 'is-loading');
    });
}

/**
 * Speak a short sample with the given voice — no on-screen player, just speakers.
 * Only one preview can play at a time; switching voices aborts the previous fetch/audio.
 */
export async function previewVoice(voiceId, displayName) {
    if (!voiceId) return;
    const lang = document.getElementById('admin-tts-language')?.value?.trim() || 'en';
    const select = document.getElementById('admin-tts-voice');
    const name = displayName || voiceId;

    // Click same active voice (loading or playing) → stop
    if (voicePreviewActiveId === voiceId) {
        stopVoicePreview();
        setStatus(`Stopped preview of “${name}”.`);
        return;
    }

    stopVoicePreview();
    // Capture generation after stop so this request is invalidated by any later stop/switch
    const gen = voicePreviewGeneration;
    voicePreviewActiveId = voiceId;

    const row = document.querySelector(`.voice-row[data-id="${CSS.escape(voiceId)}"]`);
    row?.classList.add('is-loading');
    if (select) select.value = voiceId;
    document.querySelectorAll('.voice-row').forEach(r => {
        r.classList.toggle('is-selected', r.dataset.id === voiceId);
    });

    setStatus(`Playing preview of “${name}”…`);

    const controller = new AbortController();
    voicePreviewAbort = controller;

    try {
        const res = await fetch('/api/v1/admin/tts/preview', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            signal: controller.signal,
            body: JSON.stringify({
                voice_id: voiceId,
                language: lang,
                provider_id: 'grok',
            }),
        });
        if (gen !== voicePreviewGeneration) return;

        if (!res.ok) {
            let detail = `Preview failed (${res.status})`;
            try {
                const err = await res.json();
                detail = err.detail || detail;
            } catch (_) {
                try {
                    detail = (await res.text()) || detail;
                } catch (_) { /* ignore */ }
            }
            throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
        }

        const blob = await res.blob();
        if (gen !== voicePreviewGeneration) return;

        if (!blob || blob.size < 100) {
            throw new Error('Empty audio response from server');
        }

        // Defensive: never leave a previous element playing (TOCTOU with rapid clicks)
        _detachVoicePreviewAudio();
        if (gen !== voicePreviewGeneration) return;

        const objectUrl = URL.createObjectURL(blob);
        const audio = new Audio(objectUrl);
        voicePreviewObjectUrl = objectUrl;
        voicePreviewAudio = audio;

        audio.addEventListener('playing', () => {
            if (gen !== voicePreviewGeneration) return;
            row?.classList.remove('is-loading');
            row?.classList.add('is-playing');
            setStatus(`Hearing “${name}” — click again to stop, or pick another voice.`);
        });
        audio.addEventListener('ended', () => {
            if (gen !== voicePreviewGeneration) return;
            if (voicePreviewActiveId === voiceId) {
                row?.classList.remove('is-playing', 'is-loading');
                voicePreviewActiveId = null;
                _detachVoicePreviewAudio();
                setStatus(`Selected “${name}” — Save voice preferences to make it the default.`);
            }
        });
        audio.addEventListener('error', () => {
            if (gen !== voicePreviewGeneration) return;
            stopVoicePreview();
            setStatus(`Could not play preview for “${name}”.`, true);
        });

        await audio.play();

        // Superseded while play() was pending — stop this orphan immediately
        if (gen !== voicePreviewGeneration) {
            try {
                audio.pause();
                audio.removeAttribute('src');
                audio.load();
            } catch (_) { /* ignore */ }
            try { URL.revokeObjectURL(objectUrl); } catch (_) { /* ignore */ }
            return;
        }
    } catch (e) {
        if (e?.name === 'AbortError') return;
        if (gen !== voicePreviewGeneration) return;
        stopVoicePreview();
        setStatus(String(e.message || e), true);
    }
}

export async function renderVoiceAdmin() {
    const select = document.getElementById('admin-tts-voice');
    const langInput = document.getElementById('admin-tts-language');
    const list = document.getElementById('admin-voice-list');
    const sourceEl = document.getElementById('admin-voice-source');
    if (!select || !list) return;

    stopVoicePreview();
    list.innerHTML = '<p class="admin-muted">Loading voices…</p>';
    try {
        const res = await fetch('/api/v1/admin/tts/voices?provider_id=grok');
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Failed to load voices');

        const prefs = catalog?.preferences || {};
        const preferred = data.preferred_voice || prefs.tts_voice || 'eve';
        const preferredLang = data.preferred_language || prefs.tts_language || 'en';
        if (langInput) langInput.value = preferredLang;

        if (sourceEl) {
            sourceEl.textContent = (
                (data.message || (data.source === 'xai' ? 'Voices from xAI API.' : 'Built-in voice list.'))
                + ' Click a voice to hear a short sample (no player — audio goes to your speakers).'
            );
        }

        select.innerHTML = '';
        const voices = data.voices || [];
        voices.forEach(v => {
            const opt = document.createElement('option');
            opt.value = v.voice_id;
            const tone = v.tone ? ` — ${v.tone}` : '';
            opt.textContent = `${v.name || v.voice_id}${tone}`;
            select.appendChild(opt);
        });
        if (voices.some(v => v.voice_id === preferred)) {
            select.value = preferred;
        } else if (voices.length) {
            select.value = voices[0].voice_id;
        }

        list.innerHTML = '';
        if (!voices.length) {
            list.innerHTML = '<p class="admin-muted">No voices available.</p>';
            return;
        }
        voices.forEach(v => {
            const row = document.createElement('div');
            row.className = 'admin-row voice-row';
            row.dataset.id = v.voice_id;
            row.dataset.name = v.name || v.voice_id;
            row.setAttribute('role', 'button');
            row.tabIndex = 0;
            row.title = `Click to hear ${v.name || v.voice_id}`;
            if (v.voice_id === select.value) row.classList.add('is-selected');
            row.innerHTML = `
                <div class="admin-row-main">
                    <span class="voice-play-hint" aria-hidden="true">▶</span>
                    <strong>${escapeHtml(v.name || v.voice_id)}</strong>
                    <code>${escapeHtml(v.voice_id)}</code>
                    ${v.gender ? `<span class="admin-tag">${escapeHtml(v.gender)}</span>` : ''}
                    ${v.language ? `<span class="admin-tag">${escapeHtml(v.language)}</span>` : ''}
                    ${v.tone ? `<span class="admin-muted">${escapeHtml(v.tone)}</span>` : ''}
                </div>
                <button type="button" class="modal-btn secondary voice-pick-btn"
                    data-id="${escapeHtml(v.voice_id)}" data-name="${escapeHtml(v.name || v.voice_id)}">
                    Preview
                </button>
            `;
            list.appendChild(row);
        });

        const selectVoice = (id, name) => {
            if (select) select.value = id;
            list.querySelectorAll('.voice-row').forEach(r => {
                r.classList.toggle('is-selected', r.dataset.id === id);
            });
            previewVoice(id, name);
        };

        list.querySelectorAll('.voice-row').forEach(row => {
            row.addEventListener('click', (e) => {
                // Let the Preview button handle its own click
                if (e.target.closest('.voice-pick-btn')) return;
                selectVoice(row.dataset.id, row.dataset.name);
            });
            row.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    selectVoice(row.dataset.id, row.dataset.name);
                }
            });
        });

        list.querySelectorAll('.voice-pick-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                selectVoice(btn.dataset.id, btn.dataset.name);
            });
        });

        // Dropdown change also previews
        select.onchange = () => {
            const id = select.value;
            const opt = select.selectedOptions?.[0];
            const name = (opt?.textContent || id).split('—')[0].trim();
            list.querySelectorAll('.voice-row').forEach(r => {
                r.classList.toggle('is-selected', r.dataset.id === id);
            });
            previewVoice(id, name);
        };
    } catch (e) {
        list.innerHTML = `<p class="admin-muted">Failed to load voices: ${escapeHtml(e.message || e)}</p>`;
    }
}

// ── Add API wizard (conversational discover) ──────────────────────────────────

/** @type {Record<string, string>} answers to clarifying questions */
let setupAnswers = {};
/** @type {Array<{role: string, content: string}>} */
let setupHistory = [];


// frontend/js/ui.js
// Purpose: DOM rendering, shared markdown renderer, live stream formatting

import { getConversation } from './state.js';
import { getProvider } from './config.js';

const chatHistory = document.getElementById('chat-history');

if (!chatHistory) {
    console.error('[ui.js] chat-history element not found');
}

/** Shared markdown-it instance (created lazily once globals exist). */
let _md = null;

function getMarkdown() {
    if (_md) return _md;
    if (typeof markdownit === 'undefined') {
        console.error('[ui.js] markdown-it not loaded');
        return null;
    }
    _md = markdownit({
        html: false, // safer; stream may include partial tags
        linkify: true,
        typographer: true,
        breaks: false,
        highlight(str, lang) {
            if (typeof hljs !== 'undefined' && lang && hljs.getLanguage(lang)) {
                try {
                    return (
                        '<pre class="hljs"><code>' +
                        hljs.highlight(str, { language: lang, ignoreIllegals: true }).value +
                        '</code></pre>'
                    );
                } catch (e) {
                    console.warn('[ui.js] Highlight failed:', lang, e);
                }
            }
            const esc = _md.utils.escapeHtml(str);
            return `<pre class="hljs"><code>${esc}</code></pre>`;
        },
    });
    return _md;
}

/**
 * Stabilize incomplete markdown while streaming (open fences, half tables).
 * Does not change the stored raw text — only the preview string.
 */
export function previewMarkdownSource(raw) {
    let text = raw || '';
    // Close unclosed fenced code blocks so highlight/pre still render
    const fenceCount = (text.match(/^```/gm) || []).length;
    if (fenceCount % 2 === 1) {
        text += '\n```';
    }
    return text;
}

const AUDIO_EXT_RE = /\.(mp3|wav|ogg|oga|m4a|aac|flac|opus|weba)(\?|#|$)/i;
const VIDEO_EXT_RE = /\.(mp4|webm|mov|mkv|m4v|ogv)(\?|#|$)/i;
const IMAGE_EXT_RE = /\.(png|jpg|jpeg|gif|webp|svg|bmp|avif)(\?|#|$)/i;
const BARE_URL_RE = /^(https?:\/\/\S+|data:(?:audio|video)\/[a-z0-9.+-]+;base64,\S+|blob:\S+)$/i;

/**
 * @param {string} url
 * @returns {'audio'|'video'|null}
 */
export function mediaKindFromUrl(url) {
    if (!url || typeof url !== 'string') return null;
    const u = url.trim();
    if (!u) return null;
    if (/^data:audio\//i.test(u)) return 'audio';
    if (/^data:video\//i.test(u)) return 'video';
    // blob: unknown — prefer video element (plays both)
    if (/^blob:/i.test(u)) return 'video';
    // Our local media store (TTS, etc.)
    if (/\/api\/v1\/media\//i.test(u)) {
        if (VIDEO_EXT_RE.test(u)) return 'video';
        return 'audio';
    }
    // Strip query for extension check but keep full url for matching
    const path = u.split(/[?#]/)[0];
    if (AUDIO_EXT_RE.test(path) || AUDIO_EXT_RE.test(u)) return 'audio';
    if (VIDEO_EXT_RE.test(path) || VIDEO_EXT_RE.test(u)) return 'video';
    // Common host paths without clean extensions
    if (/\/(audio|speech|tts|voice|sound)\//i.test(u) && /^https?:\/\//i.test(u)) {
        return 'audio';
    }
    if (/\/(video|stream|clip)\//i.test(u) && /^https?:\/\//i.test(u) && !IMAGE_EXT_RE.test(path)) {
        return 'video';
    }
    return null;
}

function formatMediaTime(sec) {
    if (!Number.isFinite(sec) || sec < 0) return '0:00';
    const s = Math.floor(sec % 60);
    const m = Math.floor(sec / 60) % 60;
    const h = Math.floor(sec / 3600);
    const pad = (n) => String(n).padStart(2, '0');
    if (h > 0) return `${h}:${pad(m)}:${pad(s)}`;
    return `${m}:${pad(s)}`;
}

function _filenameFromMediaUrl(url) {
    try {
        const path = String(url).split('?')[0];
        const base = path.split('/').pop() || 'speech.mp3';
        return base.includes('.') ? base : `${base}.mp3`;
    } catch (_) {
        return 'speech.mp3';
    }
}

/**
 * Build an in-chat media player (native controls + Stop).
 * Native <audio controls> is the reliable path for play/pause/mute/seek;
 * we add an explicit Stop button on top.
 * @param {string} url
 * @param {'audio'|'video'} kind
 */
function buildMediaPlayer(url, kind) {
    const wrap = document.createElement('div');
    wrap.className = `media-player media-player-${kind}`;
    wrap.dataset.mediaSrc = url;

    const media = document.createElement(kind === 'video' ? 'video' : 'audio');
    media.className = 'media-player-el';
    media.preload = 'metadata';
    media.controls = true; // play / pause / seek / mute (browser chrome)
    media.setAttribute('playsinline', '');
    try {
        media.src = new URL(url, window.location.origin).href;
    } catch (_) {
        media.src = url;
    }

    const toolbar = document.createElement('div');
    toolbar.className = 'media-player-controls';

    const playBtn = document.createElement('button');
    playBtn.type = 'button';
    playBtn.className = 'media-ctrl media-play';
    playBtn.title = 'Play / Pause';
    playBtn.setAttribute('aria-label', 'Play');
    playBtn.textContent = '▶';

    const stopBtn = document.createElement('button');
    stopBtn.type = 'button';
    stopBtn.className = 'media-ctrl media-stop';
    stopBtn.title = 'Stop (reset to start)';
    stopBtn.setAttribute('aria-label', 'Stop');
    stopBtn.textContent = '■';

    const muteBtn = document.createElement('button');
    muteBtn.type = 'button';
    muteBtn.className = 'media-ctrl media-mute';
    muteBtn.title = 'Mute';
    muteBtn.setAttribute('aria-label', 'Mute');
    muteBtn.textContent = '🔊';

    const timeEl = document.createElement('span');
    timeEl.className = 'media-time';
    timeEl.textContent = '0:00 / 0:00';

    const downloadBtn = document.createElement('a');
    downloadBtn.className = 'media-ctrl media-download';
    downloadBtn.href = media.src || url;
    downloadBtn.download = _filenameFromMediaUrl(url);
    downloadBtn.title = 'Download audio';
    downloadBtn.setAttribute('aria-label', 'Download audio');
    downloadBtn.textContent = '⬇';
    downloadBtn.addEventListener('click', (e) => e.stopPropagation());

    toolbar.append(playBtn, stopBtn, muteBtn, downloadBtn, timeEl);

    const setPlayingUi = (playing) => {
        playBtn.textContent = playing ? '❚❚' : '▶';
        playBtn.title = playing ? 'Pause' : 'Play';
        playBtn.setAttribute('aria-label', playing ? 'Pause' : 'Play');
        wrap.classList.toggle('is-playing', playing);
    };

    const setMutedUi = (muted) => {
        muteBtn.textContent = muted ? '🔇' : '🔊';
        muteBtn.title = muted ? 'Unmute' : 'Mute';
        muteBtn.setAttribute('aria-label', muted ? 'Unmute' : 'Mute');
        wrap.classList.toggle('is-muted', muted);
    };

    const updateTime = () => {
        const cur = media.currentTime || 0;
        const dur = Number.isFinite(media.duration) ? media.duration : 0;
        timeEl.textContent = `${formatMediaTime(cur)} / ${formatMediaTime(dur)}`;
    };

    playBtn.addEventListener('click', async (e) => {
        e.preventDefault();
        e.stopPropagation();
        try {
            if (media.paused) await media.play();
            else media.pause();
        } catch (err) {
            console.warn('[ui.js] Media play failed:', err);
            wrap.classList.add('media-error');
            playBtn.title = `Playback failed: ${err?.message || err}`;
        }
    });

    stopBtn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        media.pause();
        try { media.currentTime = 0; } catch (_) { /* ignore */ }
        setPlayingUi(false);
        updateTime();
    });

    muteBtn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        media.muted = !media.muted;
        setMutedUi(media.muted);
    });

    media.addEventListener('play', () => setPlayingUi(true));
    media.addEventListener('pause', () => setPlayingUi(false));
    media.addEventListener('ended', () => {
        setPlayingUi(false);
        updateTime();
    });
    media.addEventListener('timeupdate', updateTime);
    media.addEventListener('loadedmetadata', updateTime);
    media.addEventListener('durationchange', updateTime);
    media.addEventListener('volumechange', () => setMutedUi(media.muted || media.volume === 0));
    media.addEventListener('error', () => {
        wrap.classList.add('media-error');
        if (!wrap.querySelector('.media-error-msg')) {
            const err = document.createElement('p');
            err.className = 'media-error-msg';
            err.textContent = 'Could not load audio. Try again or check the media URL.';
            wrap.appendChild(err);
        }
    });

    // Only trap toolbar clicks — never the native <audio> controls
    toolbar.addEventListener('click', (e) => e.stopPropagation());

    // Native media element first so controls are always visible/clickable
    wrap.appendChild(media);
    wrap.appendChild(toolbar);

    return wrap;
}

function replaceWithPlayer(node, url, kind, caption) {
    const player = buildMediaPlayer(url, kind);
    if (caption) {
        const block = document.createElement('div');
        block.className = 'media-block';
        const cap = document.createElement('div');
        cap.className = 'media-caption';
        cap.textContent = caption;
        block.appendChild(cap);
        block.appendChild(player);
        node.replaceWith(block);
    } else {
        node.replaceWith(player);
    }
}

/**
 * Replace media links / bare media URLs in a rendered message with players.
 * Skipped while streaming so re-paints don't reset playback.
 */
function attachMediaPlayers(root) {
    if (!root) return;

    // 1) <a href="media-url"> → player (including /api/v1/media/*.mp3)
    root.querySelectorAll('a[href]').forEach(link => {
        if (link.closest('.media-player, .media-block')) return;
        if (link.classList.contains('media-open-link')) return;
        const href = link.getAttribute('href') || '';
        const kind = mediaKindFromUrl(href);
        if (!kind) return;

        // Stop the browser from navigating/downloading this href
        link.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
        });

        const label = (link.textContent || '').trim();
        const keepCaption = label
            && label !== href
            && !/^https?:\/\//i.test(label)
            && !label.startsWith('data:')
            && !label.startsWith('/api/');
        // Prefer a clean caption; "▶ Play speech" is redundant with the player
        const caption = keepCaption && !/play\s*speech/i.test(label) ? label : null;
        replaceWithPlayer(link, href, kind, caption);
    });

    // 2) Bare media URL as sole content of a paragraph
    root.querySelectorAll('p').forEach(p => {
        if (p.closest('.media-player, .media-block') || p.querySelector('.media-player')) return;
        const text = (p.textContent || '').trim();
        // Relative media paths too
        const isRelMedia = /^\/api\/v1\/media\/\S+\.(mp3|wav|ogg|m4a|webm|mp4)$/i.test(text);
        if (!BARE_URL_RE.test(text) && !isRelMedia) return;
        const kind = mediaKindFromUrl(text);
        if (!kind) return;
        if (p.querySelector('img, video, audio, .media-player')) return;
        replaceWithPlayer(p, text, kind, null);
    });

    // 3) Native <audio>/<video> without our chrome → wrap
    root.querySelectorAll('audio:not(.media-player-el), video:not(.media-player-el)').forEach(el => {
        if (el.closest('.media-player')) return;
        const src = el.getAttribute('src') || el.currentSrc || el.querySelector('source')?.src;
        if (!src) return;
        const kind = el.tagName.toLowerCase() === 'video' ? 'video' : 'audio';
        replaceWithPlayer(el, src, kind, null);
    });

    // 4) Markdown images that are actually media files
    root.querySelectorAll('img[src]').forEach(img => {
        if (img.closest('.media-player, .media-block')) return;
        const src = img.getAttribute('src') || '';
        const kind = mediaKindFromUrl(src);
        if (!kind) return;
        const alt = (img.getAttribute('alt') || '').trim();
        const caption = alt && alt.toLowerCase() !== 'image' && !/play\s*speech/i.test(alt) ? alt : null;
        replaceWithPlayer(img, src, kind, caption);
    });
}

/**
 * Render markdown string to HTML.
 * @param {string} content
 * @param {{ streaming?: boolean }} [opts]
 */
export function renderMarkdown(content, opts = {}) {
    const md = getMarkdown();
    if (!md) {
        const div = document.createElement('div');
        div.textContent = content || '';
        return div.innerHTML;
    }
    const source = opts.streaming ? previewMarkdownSource(content) : (content || '');
    // Plain image / media URL shortcuts
    const trimmed = (content || '').trim();
    if (trimmed.match(/^https?:\/\/.+\.(png|jpg|jpeg|gif|webp)(\?.*)?$/i)) {
        return `<img src="${md.utils.escapeHtml(trimmed)}" alt="image" loading="eager">`;
    }
    const mediaKind = mediaKindFromUrl(trimmed);
    if (mediaKind && BARE_URL_RE.test(trimmed)) {
        // Defer to enhanceMessageDom so we get full custom player
        const esc = md.utils.escapeHtml(trimmed);
        return `<p><a href="${esc}">${esc}</a></p>`;
    }
    return md.render(source);
}

const COPY_ICON = `
<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
     stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
  <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
  <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
</svg>`.trim();

const CHECK_ICON = `
<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
     stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
  <polyline points="20 6 9 17 4 12"></polyline>
</svg>`.trim();

async function copyTextToClipboard(text) {
    if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
        return;
    }
    // Fallback for older browsers / non-secure contexts
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
}

function attachCopyButton(pre) {
    if (pre.parentElement?.classList.contains('code-block')) return;

    const wrap = document.createElement('div');
    wrap.className = 'code-block';
    pre.parentNode.insertBefore(wrap, pre);
    wrap.appendChild(pre);

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'code-copy-btn';
    btn.title = 'Copy code';
    btn.setAttribute('aria-label', 'Copy code to clipboard');
    btn.innerHTML = COPY_ICON;

    btn.addEventListener('click', async (e) => {
        e.preventDefault();
        e.stopPropagation();
        const codeEl = pre.querySelector('code');
        const text = codeEl ? codeEl.textContent : pre.textContent;
        try {
            await copyTextToClipboard(text || '');
            btn.classList.add('copied');
            btn.innerHTML = CHECK_ICON;
            btn.title = 'Copied!';
            setTimeout(() => {
                btn.classList.remove('copied');
                btn.innerHTML = COPY_ICON;
                btn.title = 'Copy code';
            }, 1600);
        } catch (err) {
            console.warn('[ui.js] Copy failed:', err);
            btn.title = 'Copy failed';
        }
    });

    wrap.appendChild(btn);
}

/**
 * Post-process a rendered message root: links, images, tables, copy buttons, media.
 * @param {HTMLElement} root
 * @param {{ streaming?: boolean }} [opts]
 */
export function enhanceMessageDom(root, opts = {}) {
    if (!root) return;
    root.querySelectorAll('a').forEach(link => {
        if (link.classList.contains('media-open-link')) return;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.classList.add('msg-link');
    });
    root.querySelectorAll('img').forEach(img => {
        img.loading = 'eager';
        img.addEventListener('click', () => window.open(img.src, '_blank'));
    });
    // Wrap tables for content-sized columns + overflow if needed
    root.querySelectorAll('table').forEach(table => {
        if (table.parentElement?.classList.contains('table-wrap')) return;
        const wrap = document.createElement('div');
        wrap.className = 'table-wrap';
        table.parentNode.insertBefore(wrap, table);
        wrap.appendChild(table);
    });
    // Code blocks: copy control
    root.querySelectorAll('pre').forEach(pre => attachCopyButton(pre));
    // Media players — only on final render so stream re-paints don't reset playback
    if (!opts.streaming) {
        attachMediaPlayers(root);
    }
}

/**
 * Fill an element with formatted markdown (used for stream + final).
 */
export function setMarkdownContent(el, content, opts = {}) {
    if (!el) return;
    el.innerHTML = renderMarkdown(content, opts);
    enhanceMessageDom(el, opts);
    if (opts.streaming) {
        el.classList.add('is-streaming');
    } else {
        el.classList.remove('is-streaming');
    }
}

/**
 * Throttled live markdown updater for streaming responses.
 *
 * Important: a pending requestAnimationFrame paint must not run after
 * finish() — it would re-render with streaming:true and wipe media players.
 */
export function createStreamRenderer(targetEl) {
    let raw = '';
    let scheduled = false;
    let lastPaint = 0;
    let finished = false;
    let rafId = 0;
    const MIN_MS = 40; // ~25fps max re-parse

    const paint = (force = false) => {
        scheduled = false;
        rafId = 0;
        if (finished) return;
        const now = performance.now();
        if (!force && now - lastPaint < MIN_MS) {
            scheduled = true;
            rafId = requestAnimationFrame(() => paint(false));
            return;
        }
        lastPaint = now;
        setMarkdownContent(targetEl, raw, { streaming: true });
        scrollToBottom();
    };

    return {
        append(chunk) {
            if (finished) return;
            raw += chunk;
            if (!scheduled) {
                scheduled = true;
                rafId = requestAnimationFrame(() => paint(false));
            }
        },
        set(text) {
            if (finished) return;
            raw = text || '';
            paint(true);
        },
        finish() {
            finished = true;
            scheduled = false;
            if (rafId) {
                try { cancelAnimationFrame(rafId); } catch (_) { /* ignore */ }
                rafId = 0;
            }
            setMarkdownContent(targetEl, raw, { streaming: false });
            // Second pass on next frame in case first paint raced anything else
            requestAnimationFrame(() => {
                if (targetEl && !targetEl.querySelector('.media-player')) {
                    attachMediaPlayers(targetEl);
                }
                scrollToBottom();
            });
            scrollToBottom();
            return raw;
        },
        getText() {
            return raw;
        },
    };
}

export function scrollToBottom() {
    if (!chatHistory) return;
    const pin = () => {
        const last = chatHistory.lastElementChild;
        if (last && typeof last.scrollIntoView === 'function') {
            last.scrollIntoView({ block: 'end', behavior: 'auto' });
        }
        chatHistory.scrollTop = chatHistory.scrollHeight;
    };
    pin();
    requestAnimationFrame(() => {
        pin();
        requestAnimationFrame(pin);
    });
}

export function renderHistory() {
    if (!chatHistory) return;

    chatHistory.innerHTML = '';

    const conversation = getConversation();
    if (conversation.length === 0) {
        showWelcome();
        return;
    }

    conversation.forEach(msg => {
        const div = document.createElement('div');
        div.classList.add('message');
        div.classList.add(msg.role === 'user' ? 'user-message' : 'ai-message');

        if (msg.role === 'assistant' && msg.ai) {
            const badge = document.createElement('div');
            badge.className = 'ai-badge';
            const aiName = msg.ai;
            const provider = getProvider(aiName);
            badge.textContent = (provider?.label || aiName).toUpperCase().slice(0, 18);
            badge.style.backgroundColor = provider?.badge_color
                || (aiName === 'grok' ? '#1a535c' : aiName === 'chatgpt' ? '#10a37f' : '#555555');
            badge.style.color = 'white';
            div.appendChild(badge);
        }

        const body = document.createElement('div');
        body.className = 'message-body';
        setMarkdownContent(body, msg.content || '', { streaming: false });
        div.appendChild(body);
        chatHistory.appendChild(div);
    });

    scrollToBottom();
}

export function showWelcome() {
    if (!chatHistory) return;

    const welcome = document.createElement('div');
    welcome.className = 'welcome-message';
    welcome.innerHTML = `
        <p>Welcome to AI Conversation Hub!</p>
        <p>Choose an AI and model above, then start typing your message.</p>
        <p>Conversations are saved in browser storage for now.</p>
    `;
    chatHistory.appendChild(welcome);
}

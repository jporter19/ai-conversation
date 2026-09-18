// frontend/js/chat/stream.js
// Purpose: Read a streaming chat response with idle/hard timeouts.
// Pure transport helper — no DOM, no conversation state.

/**
 * @typedef {'ok'|'idle'|'aborted'|'hard_timeout'|'error'} StreamReason
 * @typedef {{
 *   text: string,
 *   reason: StreamReason,
 *   gotBytes: boolean,
 *   error?: Error,
 * }} StreamReadResult
 */

/**
 * Read a fetch Response body as text stream with watchdog timers.
 *
 * @param {Response} response
 * @param {object} opts
 * @param {AbortSignal} opts.signal
 * @param {AbortController} [opts.controller] — aborted on idle/hard timeout
 * @param {(chunk: string) => void} [opts.onChunk]
 * @param {() => boolean} [opts.isUserStop] — true if abort was user-initiated Stop
 * @param {number} [opts.idleMs=90000]
 * @param {number} [opts.hardMs=300000]
 * @returns {Promise<StreamReadResult>}
 */
export async function readChatStream(response, opts = {}) {
    const {
        signal,
        controller,
        onChunk,
        isUserStop = () => false,
        idleMs = 90_000,
        hardMs = 300_000,
    } = opts;

    if (!response?.body) {
        return {
            text: '',
            reason: 'error',
            gotBytes: false,
            error: new Error('Empty response body'),
        };
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let text = '';
    let lastByteAt = Date.now();
    const startedAt = Date.now();
    let gotBytes = false;
    let idleTimer = null;
    /** @type {'idle'|'hard'|null} */
    let timeoutKind = null;

    const clearIdle = () => {
        if (idleTimer) {
            clearTimeout(idleTimer);
            idleTimer = null;
        }
    };

    const tripAbort = (kind) => {
        timeoutKind = kind;
        try {
            controller?.abort();
        } catch (_) { /* ignore */ }
        try {
            reader.cancel();
        } catch (_) { /* ignore */ }
    };

    const armIdle = () => {
        clearIdle();
        idleTimer = setTimeout(() => {
            if (!signal?.aborted) {
                console.warn('[chat/stream] idle timeout — aborting');
                tripAbort('idle');
            }
        }, idleMs);
    };

    armIdle();

    try {
        while (true) {
            if (signal?.aborted) {
                await reader.cancel().catch(() => {});
                break;
            }
            if (Date.now() - startedAt > hardMs) {
                tripAbort('hard');
                break;
            }

            const { done, value } = await reader.read();
            if (done) break;

            if (value && value.length) {
                gotBytes = true;
                lastByteAt = Date.now();
                armIdle();
            }
            const chunk = decoder.decode(value, { stream: true });
            if (chunk) {
                text += chunk;
                onChunk?.(chunk);
            }
        }

        const tail = decoder.decode();
        if (tail) {
            text += tail;
            onChunk?.(tail);
        }

        clearIdle();

        if (timeoutKind === 'hard' || (signal?.aborted && timeoutKind === 'hard')) {
            return {
                text,
                reason: 'hard_timeout',
                gotBytes,
                error: new Error('Reply timed out after 5 minutes.'),
            };
        }

        if (signal?.aborted || timeoutKind === 'idle') {
            if (isUserStop()) {
                return { text, reason: 'aborted', gotBytes };
            }
            if (timeoutKind === 'idle' || !gotBytes || Date.now() - lastByteAt >= idleMs - 500) {
                return { text, reason: 'idle', gotBytes };
            }
            return { text, reason: 'aborted', gotBytes };
        }

        return { text, reason: 'ok', gotBytes };
    } catch (err) {
        clearIdle();
        if (timeoutKind === 'hard') {
            return {
                text,
                reason: 'hard_timeout',
                gotBytes,
                error: new Error('Reply timed out after 5 minutes.'),
            };
        }
        if (err?.name === 'AbortError' || signal?.aborted || timeoutKind === 'idle') {
            if (isUserStop()) {
                return { text, reason: 'aborted', gotBytes, error: err };
            }
            return {
                text,
                reason: 'idle',
                gotBytes,
                error: err instanceof Error ? err : undefined,
            };
        }
        return {
            text,
            reason: 'error',
            gotBytes,
            error: err instanceof Error ? err : new Error(String(err)),
        };
    } finally {
        clearIdle();
    }
}

/**
 * Apply idle/empty stream UX messages (pure string helper).
 * @param {string} text
 * @param {StreamReason} reason
 * @param {string} [statusPlaceholder]
 */
export function finalizeStreamText(text, reason, statusPlaceholder = '') {
    let raw = text || '';
    if (reason === 'idle') {
        const note = (
            '\n\n_[Connection stalled — the reply may have been cut off. '
            + 'This often happens when the model tries to search the web. '
            + 'Try again, or rephrase without needing live data.]_'
        );
        if (raw && statusPlaceholder && raw === statusPlaceholder) {
            return note.trim();
        }
        return (raw && raw !== statusPlaceholder ? raw : '') + note;
    }
    if (reason === 'hard_timeout') {
        return (raw ? `${raw}\n\n` : '')
            + '_[Reply timed out after 5 minutes. Please try again.]_';
    }
    if (!raw || raw === statusPlaceholder || /^Thinking/i.test(raw.trim())) {
        return (raw && raw !== statusPlaceholder ? `${raw}\n\n` : '')
            + '_[No complete answer was returned. Please try sending again.]_';
    }
    return raw;
}

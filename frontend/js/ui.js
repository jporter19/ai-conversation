// frontend/js/ui.js
// Purpose: All DOM rendering logic — chat history, welcome message, message bubbles

import { getConversation } from './state.js';

const chatHistory = document.getElementById('chat-history');

if (!chatHistory) {
    console.error('[ui.js] chat-history element not found');
}

/**
 * Renders the full conversation history.
 */
export function renderHistory() {
    console.log('[ui.js] renderHistory called');

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

        if (msg.role === 'user') {
            div.textContent = msg.content;
        } else {
            // Use global markdownit from CDN + direct highlight.js
            const md = markdownit({
                html: true,
                linkify: true,
                typographer: true,
                highlight: function (str, lang) {
                    if (lang && hljs.getLanguage(lang)) {
                        try {
                            return '<pre><code class="hljs">' +
                                   hljs.highlight(str, { language: lang }).value +
                                   '</code></pre>';
                        } catch (e) {
                            console.warn('[ui.js] Highlight failed for language:', lang, e);
                        }
                    }
                    // Fallback: plain escaped code block
                    return '<pre><code>' + md.utils.escapeHtml(str) + '</code></pre>';
                }
            });

            div.innerHTML = md.render(msg.content);
        }

        chatHistory.appendChild(div);
    });

    chatHistory.scrollTop = chatHistory.scrollHeight;
}

/**
 * Shows the welcome message when conversation is empty
 */
export function showWelcome() {
    console.log('[ui.js] showWelcome called');

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
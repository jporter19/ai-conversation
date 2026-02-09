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

        // Add AI badge for assistant messages
        if (msg.role === 'assistant' && msg.ai) {
            const badge = document.createElement('div');
            badge.className = 'ai-badge';

            const aiName = msg.ai;
            badge.textContent = aiName.toUpperCase();
            badge.style.backgroundColor = aiName === 'grok' ? '#1a535c' : '#10a37f';
            badge.style.color = 'white';

            div.prepend(badge);
        }

        if (msg.role === 'user') {
            const md = markdownit({
                html: true,
                linkify: true,
                typographer: true,
                // No need for highlight here unless you want code highlighting in user messages
            });

            let rendered = md.render(msg.content);

            // Optional: same image detection logic as assistant if you want
            const imageUrl = msg.content.trim();
            if (imageUrl.match(/^https?:\/\/.*\.(png|jpg|jpeg|gif|webp)$/i)) {
                rendered = `<img src="${imageUrl}" alt="User uploaded image" loading="eager" style="max-width:100%; border-radius:8px;">`;
            }

            div.innerHTML = rendered;
            div.querySelectorAll('a').forEach(link => {
                link.target = '_blank';                     // Open in new tab
                link.rel = 'noopener noreferrer';           // Security best practice
                link.style.color = 'var(--primary)';        // Optional: match your primary color
                link.style.textDecoration = 'underline';    // Ensure visible
            });
            // Make images clickable (same as assistant)
            div.querySelectorAll('img').forEach(img => {
                img.addEventListener('click', () => {
                    window.open(img.src, '_blank');
                });
            });
        }
         else {
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
                    return '<pre><code>' + md.utils.escapeHtml(str) + '</code></pre>';
                }
            });

            let rendered = md.render(msg.content);

            // If content is a plain image URL, render as img
            const imageUrl = msg.content.trim();
            if (imageUrl.match(/^https?:\/\/.*\.(png|jpg|jpeg|gif|webp)$/i)) {
                rendered = `<img src="${imageUrl}" alt="AI generated image" loading="eager" style="max-width:100%; border-radius:8px;">`;
            }

            div.innerHTML = rendered;
            div.querySelectorAll('a').forEach(link => {
                link.target = '_blank';                     // Open in new tab
                link.rel = 'noopener noreferrer';           // Security best practice
                link.style.color = 'var(--primary)';        // Optional: match your primary color
                link.style.textDecoration = 'underline';    // Ensure visible
            });

            // Make images clickable to open full size
            div.querySelectorAll('img').forEach(img => {
                img.addEventListener('click', () => {
                    window.open(img.src, '_blank');
                });
            });
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
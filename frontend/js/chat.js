// frontend/js/chat.js
// Purpose: Handles send message, reset, and store modal logic

import { getConversation, addMessage, clearConversation, saveConversation } from './state.js';
import { renderHistory } from './ui.js';

const userInput       = document.getElementById('user-input');
const sendBtn         = document.getElementById('send-btn');
const chatHistory     = document.getElementById('chat-history');
const resetBtn        = document.getElementById('reset-btn');
const storeBtn        = document.getElementById('store-btn');
const storeModal      = document.getElementById('store-modal');
const storeWholeBtn   = document.getElementById('store-whole-btn');
const storeSummaryBtn = document.getElementById('store-summary-btn');
const modalCancelBtn  = document.getElementById('modal-cancel-btn');

export function initChat() {
    sendBtn.addEventListener('click', sendMessage);
    userInput.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    resetBtn.addEventListener('click', () => {
        if (confirm('Reset the current conversation?')) {
            clearConversation();
            renderHistory();
            const aiSelect = document.getElementById('ai-select');
            const modelSelect = document.getElementById('model-select');
            aiSelect.value = '';
            modelSelect.disabled = true;
            modelSelect.innerHTML = '<option value="" selected disabled>Select model after choosing AI</option>';
            localStorage.removeItem('ai-conversation-hub-selected-ai');
            localStorage.removeItem('ai-conversation-hub-selected-model');
        }
    });

    storeBtn.addEventListener('click', () => {
        if (getConversation().length === 0) {
            alert("Nothing to store yet — start a conversation first!");
            return;
        }
        storeModal.showModal();
    });

    storeWholeBtn.addEventListener('click', () => {
        storeModal.close();
        alert("Whole conversation would be stored with AI-generated title.\n(Backend coming soon)");
    });

    storeSummaryBtn.addEventListener('click', () => {
        storeModal.close();
        alert("Conversation would be summarized and stored.\n(Backend + summarization coming soon)");
    });

    modalCancelBtn.addEventListener('click', () => {
        storeModal.close();
    });

    storeModal.addEventListener('click', e => {
        if (e.target === storeModal) storeModal.close();
    });
}

async function sendMessage() {
    const text = userInput.value.trim();
    if (!text) return;

    const selectedAI = document.getElementById('ai-select').value.trim();
    const selectedModel = document.getElementById('model-select').value.trim();

    if (!selectedAI || !["grok", "chatgpt"].includes(selectedAI)) {
        alert("Please select a valid AI (Grok or ChatGPT) first.");
        return;
    }

    if (!selectedModel) {
        alert("Please select a model first.");
        return;
    }

    addMessage({ role: 'user', content: text });
    renderHistory();

    userInput.value = '';

    const thinkingDiv = document.createElement('div');
    thinkingDiv.classList.add('message', 'ai-message');
    thinkingDiv.textContent = 'Thinking...';
    chatHistory.appendChild(thinkingDiv);
    chatHistory.scrollTop = chatHistory.scrollHeight;

    try {
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                ai: selectedAI,
                model: selectedModel,
                messages: getConversation()
            })
        });

        if (!response.ok) {
            const errorText = await response.text();
            thinkingDiv.innerHTML = `Error: ${response.status} — ${errorText}`;
            return;
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();

        let rawContent = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            let chunk = decoder.decode(value, { stream: true });

            if (chunk.startsWith('data: ')) {
                chunk = chunk.slice(6).trim();
            }
            if (chunk === '[DONE]') break;

            rawContent += chunk;

            thinkingDiv.textContent = rawContent;
            chatHistory.scrollTop = chatHistory.scrollHeight;
        }

        // Use global markdownit + direct hljs highlighting
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
                        console.warn('Highlight failed for language:', lang, e);
                    }
                }
                // Fallback: plain escaped code block
                return '<pre><code>' + md.utils.escapeHtml(str) + '</code></pre>';
            }
        });

        thinkingDiv.innerHTML = md.render(rawContent);

        chatHistory.scrollTop = chatHistory.scrollHeight;

        addMessage({ role: 'assistant', content: rawContent });

    } catch (err) {
        console.error('Chat request failed:', err);
        thinkingDiv.innerHTML = 'Error: Could not connect to AI. Check console.';
    }
}
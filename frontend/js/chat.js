// frontend/js/chat.js
// Purpose: Handles send message, reset, and store modal logic

import { 
    getConversation, 
    addMessage, 
    clearConversation, 
    saveConversation 
} from './state.js';

import { renderHistory } from './ui.js';

import { 
    STORAGE_KEY,
    STORAGE_AI_KEY,
    STORAGE_MODEL_KEY,
    grokModels 
} from './config.js';

import { populateModels } from './config.js';  // populateModels is in config.js

const userInput       = document.getElementById('user-input');
const sendBtn         = document.getElementById('send-btn');
const chatHistory     = document.getElementById('chat-history');
const resetBtn        = document.getElementById('reset-btn');
const storeBtn        = document.getElementById('store-btn');
const storeModal      = document.getElementById('store-modal');
const storeWholeBtn   = document.getElementById('store-whole-btn');
const storeSummaryBtn = document.getElementById('store-summary-btn');
const modalCancelBtn  = document.getElementById('modal-cancel-btn');
const resetModal      = document.getElementById('reset-modal');
const resetConfirmBtn = document.getElementById('reset-confirm-btn');
const resetCancelBtn  = document.getElementById('reset-cancel-btn');
const aiSelect        = document.getElementById('ai-select');
const modelSelect     = document.getElementById('model-select');

function isImageGenerationModel(model) {
    return model === 'dall-e-3' ||
           model === 'grok-2-image-1212' ||
           model === 'grok-imagine-image';
}

export function initChat() {
    sendBtn.addEventListener('click', sendMessage);
    userInput.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    // Reset with nice modal
    resetBtn.addEventListener('click', () => {
        resetModal.showModal();
    });

    resetConfirmBtn.addEventListener('click', () => {
        clearConversation();
        renderHistory();

        // Clear stored AI/model selection
        localStorage.removeItem(STORAGE_KEY);
        localStorage.removeItem(STORAGE_AI_KEY);
        localStorage.removeItem(STORAGE_MODEL_KEY);

        // Restore defaults
        aiSelect.value = 'grok';
        populateModels(grokModels);
        modelSelect.value = 'grok-4-1-fast-reasoning';

        localStorage.setItem(STORAGE_AI_KEY, 'grok');
        localStorage.setItem(STORAGE_MODEL_KEY, 'grok-4-1-fast-reasoning');

        renderHistory();

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

// frontend/js/chat.js
// Complete sendMessage() implementation with text streaming + image generation support

async function sendMessage() {
    const text = userInput.value.trim();
    if (!text) return;

    const selectedAI = aiSelect.value.trim();
    const selectedModel = modelSelect.value.trim();

    if (!selectedAI || !["grok", "chatgpt"].includes(selectedAI)) {
        alert("Please select a valid AI (Grok or ChatGPT) first.");
        return;
    }

   if (!selectedModel) {
        const noModelModal = document.getElementById('no-model-modal');
        noModelModal.showModal();
        return;
    }

    const isImageGen = isImageGenerationModel(selectedModel);

    // Add user message to conversation and re-render
    addMessage({ role: 'user', content: text });
    renderHistory();

    // Clear input
    userInput.value = '';

    // Create assistant message bubble immediately (with badge)
    const assistantDiv = document.createElement('div');
    assistantDiv.classList.add('message', 'ai-message');

    // Add AI badge
    const badge = document.createElement('div');
    badge.className = 'ai-badge';
    badge.textContent = selectedAI === 'grok' ? 'GROK' : 'CHATGPT';
    badge.style.backgroundColor = selectedAI === 'grok' ? '#1a535c' : '#10a37f';
    badge.style.color = 'white';
    assistantDiv.prepend(badge);

    // Initial status text
    const contentSpan = document.createElement('span');
    contentSpan.textContent = isImageGen ? 'Generating image...' : 'Thinking...';
    assistantDiv.appendChild(contentSpan);

    chatHistory.appendChild(assistantDiv);
    chatHistory.scrollTop = chatHistory.scrollHeight;

    try {
        if (isImageGen) {
            // ── IMAGE GENERATION PATH ───────────────────────────────────────
            const res = await fetch('/api/v1/generate-image', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    ai: selectedAI,
                    model: selectedModel,
                    prompt: text
                })
            });

            if (!res.ok) {
                const errorText = await res.text();
                throw new Error(`Image generation failed: ${res.status} - ${errorText}`);
            }

            const data = await res.json();
            const imageUrl = data.url;

            if (!imageUrl) {
                throw new Error("No image URL returned from server");
            }

            // Create nice markdown with caption
            const shortPrompt = text.substring(0, 120) + (text.length > 120 ? '...' : '');
            const markdown = `![${shortPrompt}](${imageUrl})\n\n*Generated with ${selectedModel} from prompt: "${shortPrompt}"*`;

            // Render with markdown-it
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
                        } catch (__) {}
                    }
                    return '<pre><code>' + md.utils.escapeHtml(str) + '</code></pre>';
                }
            });

            // Replace the "Generating..." content with final rendered image + caption
            assistantDiv.innerHTML = '';
            assistantDiv.prepend(badge);
            assistantDiv.innerHTML += md.render(markdown);

            // Save the assistant message (we store the markdown)
            addMessage({
                role: 'assistant',
                content: markdown,
                ai: selectedAI
            });

            chatHistory.scrollTop = chatHistory.scrollHeight;
        } else {
            // ── ORIGINAL TEXT STREAMING PATH ─────────────────────────────────
            const response = await fetch('/api/v1/chat', {
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
                contentSpan.innerHTML = `Error: ${response.status} — ${errorText}`;
                return;
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();

            let rawContent = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                let chunk = decoder.decode(value, { stream: true });

                // Handle SSE-style chunks if your backend uses them
                if (chunk.startsWith('data: ')) {
                    chunk = chunk.slice(6).trim();
                }
                if (chunk === '[DONE]') break;

                rawContent += chunk;

                // Live update
                contentSpan.textContent = rawContent;
                chatHistory.scrollTop = chatHistory.scrollHeight;
            }

            // Final full render with markdown + syntax highlighting
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
                        } catch (__) {}
                    }
                    return '<pre><code>' + md.utils.escapeHtml(str) + '</code></pre>';
                }
            });

            assistantDiv.innerHTML = '';           // Clear streaming content
            assistantDiv.prepend(badge);           // Re-attach badge
            const finalContent = document.createElement('div');
            finalContent.innerHTML = md.render(rawContent);
            assistantDiv.appendChild(finalContent);

            chatHistory.scrollTop = chatHistory.scrollHeight;

            // Save complete assistant message
            addMessage({
                role: 'assistant',
                content: rawContent,
                ai: selectedAI
            });
        }
    } catch (err) {
        console.error('Chat / image request failed:', err);
        contentSpan.innerHTML = `Error: ${err.message || 'Could not connect to AI. Check console.'}`;
    }
}
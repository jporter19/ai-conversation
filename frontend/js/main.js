// frontend/js/main.js
// Purpose: Client-side logic for AI Conversation Hub
//          Manages conversation state, renders history, handles input/send/reset

document.addEventListener('DOMContentLoaded', () => {
    // ── DOM Elements ────────────────────────────────────────────────────────
    const aiSelect       = document.getElementById('ai-select');
    const modelSelect    = document.getElementById('model-select');
    const userInput      = document.getElementById('user-input');
    const sendBtn        = document.getElementById('send-btn');
    const chatHistory    = document.getElementById('chat-history');
    const resetBtn       = document.getElementById('reset-btn');
        // Add to DOM Elements section
    const storeBtn      = document.getElementById('store-btn');
    const storeModal    = document.getElementById('store-modal');
    const storeWholeBtn = document.getElementById('store-whole-btn');
    const storeSummaryBtn = document.getElementById('store-summary-btn');
    const modalCancelBtn = document.getElementById('modal-cancel-btn');

    // ── Conversation State ──────────────────────────────────────────────────
    let conversation = []; // Array of { role: "user"|"assistant", content: string }

    const STORAGE_KEY = 'ai-conversation-hub-current-chat';

    // ── Model Lists (Jan 2026 snapshot) ─────────────────────────────────────
    const grokModels = [
        { value: 'grok-4-1-fast-reasoning', label: 'Grok 4.1 Fast (Reasoning)' },
        { value: 'grok-4-1-fast-non-reasoning', label: 'Grok 4.1 Fast (Non-Reasoning)' },
        { value: 'grok-code-fast-1', label: 'Grok Code Fast 1 (Coding-Optimized)' },
        // ... rest of your list ...
    ];

    const openaiModels = [
        { value: 'gpt-5.2', label: 'GPT-5.2 (Flagship)' },
        // ... rest of your list ...
    ];

    // ── Load from localStorage on page load ────────────────────────────────
    function loadConversation() {
        const saved = localStorage.getItem(STORAGE_KEY);
        if (saved) {
            conversation = JSON.parse(saved);
            renderHistory();
        } else {
            showWelcome();
        }
    }

    // ── Save to localStorage ────────────────────────────────────────────────
    function saveConversation() {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(conversation));
    }

    // ── Render full chat history ────────────────────────────────────────────
    function renderHistory() {
        chatHistory.innerHTML = ''; // Clear

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
                const html = marked.parse(msg.content, {
                    gfm: true,
                    breaks: true,
                    headerIds: false
                });
                div.innerHTML = html;

                // Highlight code blocks
                div.querySelectorAll('pre code').forEach(block => {
                    hljs.highlightElement(block);
                });
            }

            chatHistory.appendChild(div);
        });

        chatHistory.scrollTop = chatHistory.scrollHeight;
    }

    function showWelcome() {
        const welcome = document.createElement('div');
        welcome.className = 'welcome-message';
        welcome.innerHTML = `
            <p>Welcome to AI Conversation Hub!</p>
            <p>Choose an AI and model above, then start typing your message.</p>
            <p>Conversations are saved in browser storage for now.</p>
        `;
        chatHistory.appendChild(welcome);
    }

    // ── Populate Models (unchanged from before) ─────────────────────────────
    function populateModels(models) {
        modelSelect.innerHTML = '';
        const placeholder = document.createElement('option');
        placeholder.value = '';
        placeholder.textContent = 'Select model';
        placeholder.disabled = true;
        placeholder.selected = true;
        modelSelect.appendChild(placeholder);

        models.forEach(m => {
            const opt = document.createElement('option');
            opt.value = m.value;
            opt.textContent = m.label;
            modelSelect.appendChild(opt);
        });

        modelSelect.disabled = false;
    }

    aiSelect.addEventListener('change', () => {
        const ai = aiSelect.value;
        if (ai === 'grok') populateModels(grokModels);
        else if (ai === 'chatgpt') populateModels(openaiModels);
        else {
            modelSelect.innerHTML = '<option value="" selected disabled>Select model after choosing AI</option>';
            modelSelect.disabled = true;
        }
    });

    // ── Send Message ────────────────────────────────────────────────────────
    function sendMessage() {
        const text = userInput.value.trim();
        if (!text) return;

        // Add user message to state
        conversation.push({ role: 'user', content: text });
        renderHistory();
        saveConversation();

        // Clear input
        userInput.value = '';

        // Mock AI response
        setTimeout(() => {
            const hasCodeKeywords = text.toLowerCase().includes('code') ||
                                    text.toLowerCase().includes('python') ||
                                    text.toLowerCase().includes('function') ||
                                    text.toLowerCase().includes('write');

            const mockReply = hasCodeKeywords
                ? `**Here's a quick example** in Python:

\`\`\`python
def reverse_string(s):
    return s[::-1]

print(reverse_string("hello"))  # → olleh
\`\`\`

You can copy the code block easily. Want me to improve it or add error handling?`
                : `You said: *${text}*

I'm a mock response for now.

- Bullet point 1
- Bullet point 2

**Real integration coming soon!**`;

            conversation.push({ role: 'assistant', content: mockReply });
            renderHistory();
            saveConversation();
        }, 800);
    }

    sendBtn.addEventListener('click', sendMessage);

    userInput.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    resetBtn.addEventListener('click', () => {
        if (confirm('Reset the current conversation?')) {
            conversation = [];
            localStorage.removeItem(STORAGE_KEY);
            renderHistory();
        }
    });
        // Store Conversation Modal
    storeBtn.addEventListener('click', () => {
        if (conversation.length === 0) {
            alert("Nothing to store yet — start a conversation first!");
            return;
        }
        storeModal.showModal();
    });

    storeWholeBtn.addEventListener('click', () => {
        storeModal.close();
        alert("Whole conversation would be stored with an AI-generated title.\n(Backend storage coming in next tasks)");
        // Later: call backend endpoint with conversation array + "whole"
    });

    storeSummaryBtn.addEventListener('click', () => {
        storeModal.close();
        alert("Conversation would be summarized by AI and stored.\n(Backend + summarization coming soon)");
        // Later: call backend with conversation + "summary"
    });

    modalCancelBtn.addEventListener('click', () => {
        storeModal.close();
    });

    // Optional: Close modal when clicking backdrop (nice UX)
    storeModal.addEventListener('click', (e) => {
        if (e.target === storeModal) {
            storeModal.close();
        }
    });
    // ── Initialize ──────────────────────────────────────────────────────────
    loadConversation();
});
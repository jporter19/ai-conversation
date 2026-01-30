// frontend/js/main.js
// Purpose: Client-side interactivity for AI Conversation Hub
//          Handles AI/model selection + chat message display (user + mock AI)

document.addEventListener('DOMContentLoaded', () => {
    // ── DOM Elements ────────────────────────────────────────────────────────
    const aiSelect       = document.getElementById('ai-select');
    const modelSelect    = document.getElementById('model-select');
    const userInput      = document.getElementById('user-input');
    const sendBtn        = document.getElementById('send-btn');
    const chatHistory    = document.getElementById('chat-history');
    const resetBtn       = document.getElementById('reset-btn');

    // ── Model Lists (Jan 2026 snapshot) ─────────────────────────────────────
    const grokModels = [
        { value: 'grok-4-1-fast-reasoning',        label: 'Grok 4.1 Fast (Reasoning)' },
        { value: 'grok-4-1-fast-non-reasoning',    label: 'Grok 4.1 Fast (Non-Reasoning)' },
        { value: 'grok-code-fast-1',               label: 'Grok Code Fast 1 (Coding-Optimized)' },
        { value: 'grok-4-fast-reasoning',          label: 'Grok 4 Fast (Reasoning)' },
        { value: 'grok-4-fast-non-reasoning',      label: 'Grok 4 Fast (Non-Reasoning)' },
        { value: 'grok-4-0709',                    label: 'Grok 4 (0709 snapshot)' },
        { value: 'grok-3',                         label: 'Grok 3' },
        { value: 'grok-3-mini',                    label: 'Grok 3 Mini' },
        { value: 'grok-2-vision-1212',             label: 'Grok 2 Vision (1212 - Multimodal)' }
    ];

    const openaiModels = [
        { value: 'gpt-5.2',         label: 'GPT-5.2 (Flagship)' },
        { value: 'gpt-5.2-pro',     label: 'GPT-5.2 Pro (Extended reasoning)' },
        { value: 'gpt-5-mini',      label: 'GPT-5 Mini (Faster)' },
        { value: 'gpt-5-nano',      label: 'GPT-5 Nano (Fastest, cheapest)' },
        { value: 'gpt-5',           label: 'GPT-5 (Previous flagship)' }
    ];

    // ── Populate Models ─────────────────────────────────────────────────────
    function populateModels(models) {
        modelSelect.innerHTML = '';
        const placeholder = document.createElement('option');
        placeholder.value = '';
        placeholder.textContent = models.length ? 'Select model' : 'No models available';
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
        if (ai === 'grok')      populateModels(grokModels);
        else if (ai === 'chatgpt') populateModels(openaiModels);
        else {
            modelSelect.innerHTML = '<option value="" selected disabled>Select model after choosing AI</option>';
            modelSelect.disabled = true;
        }
    });

    // ── Chat Message Rendering ──────────────────────────────────────────────
        // ── Chat Message Rendering ──────────────────────────────────────────────
    function addMessage(content, isUser = false) {
        const div = document.createElement('div');
        div.classList.add('message');
        div.classList.add(isUser ? 'user-message' : 'ai-message');

        if (isUser) {
            // User messages: plain text, escaped for safety
            div.textContent = content;
        } else {
            // AI messages: render as markdown + highlight code
            const html = marked.parse(content, {
                gfm: true,           // GitHub-flavored markdown
                breaks: true,        // line breaks → <br>
                headerIds: false     // no auto IDs on headings
            });

            div.innerHTML = html;

            // Highlight code blocks after rendering
            div.querySelectorAll('pre code').forEach((block) => {
                hljs.highlightElement(block);
            });
        }

        chatHistory.appendChild(div);

        // Scroll to bottom
        chatHistory.scrollTop = chatHistory.scrollHeight;
    }

    function sendMessage() {
        const text = userInput.value.trim();
        if (!text) return;

        // Show user message
        addMessage(text, true);

        // Clear input
        userInput.value = '';

        // Mock AI response (for now)
setTimeout(() => {
    const hasCodeKeywords = /* your conditions */;

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

**Real Grok/ChatGPT integration coming soon!**`;

    addMessage(mockReply, false);
}, 800);

    // ── Event Listeners ─────────────────────────────────────────────────────
    sendBtn.addEventListener('click', sendMessage);

    userInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {  // Enter without Shift = send
            e.preventDefault();
            sendMessage();
        }
    });

    resetBtn.addEventListener('click', () => {
        if (confirm('Reset the current conversation?')) {
            chatHistory.innerHTML = `
                <div class="welcome-message">
                    <p>Conversation reset.</p>
                    <p>Type your next message to begin again.</p>
                </div>
            `;
        }
    });
});
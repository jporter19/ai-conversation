// frontend/js/main.js
// Purpose: Client-side interactivity for the AI Conversation Hub frontend
//          Handles AI selection → model population, future chat logic, etc.

document.addEventListener('DOMContentLoaded', () => {
    // DOM elements
    const aiSelect = document.getElementById('ai-select');
    const modelSelect = document.getElementById('model-select');

    // Hardcoded model lists (based on public API availability as of Jan 2026)
    // Grok / xAI models - from docs.x.ai and recent announcements
    const grokModels = [
        { value: 'grok-4-1-fast-reasoning', label: 'Grok 4.1 Fast (Reasoning)' },
        { value: 'grok-4-1-fast-non-reasoning', label: 'Grok 4.1 Fast (Non-Reasoning)' },
        { value: 'grok-4-fast-reasoning', label: 'Grok 4 Fast (Reasoning)' },
        { value: 'grok-4-fast-non-reasoning', label: 'Grok 4 Fast (Non-Reasoning)' },
        { value: 'grok-4-0709', label: 'Grok 4 (0709 snapshot)' },
        { value: 'grok-3', label: 'Grok 3' },
        { value: 'grok-3-mini', label: 'Grok 3 Mini' }
    ];

    // OpenAI / ChatGPT models - from platform.openai.com/docs/models Jan 2026
    const openaiModels = [
        { value: 'gpt-5.2', label: 'GPT-5.2 (Flagship - Best for coding/agentic)' },
        { value: 'gpt-5.2-pro', label: 'GPT-5.2 Pro (Extended reasoning)' },
        { value: 'gpt-5-mini', label: 'GPT-5 Mini (Faster, cost-efficient)' },
        { value: 'gpt-5-nano', label: 'GPT-5 Nano (Fastest, cheapest)' },
        { value: 'gpt-5', label: 'GPT-5 (Previous flagship)' }
    ];

    // Function to populate model dropdown
    function populateModels(models) {
        modelSelect.innerHTML = ''; // Clear existing options
        const placeholder = document.createElement('option');
        placeholder.value = '';
        placeholder.textContent = models.length ? 'Select model' : 'No models available';
        placeholder.disabled = true;
        placeholder.selected = true;
        modelSelect.appendChild(placeholder);

        models.forEach(model => {
            const option = document.createElement('option');
            option.value = model.value;
            option.textContent = model.label;
            modelSelect.appendChild(option);
        });

        modelSelect.disabled = false; // Enable once populated
    }

    // Event listener: When AI changes
    aiSelect.addEventListener('change', () => {
        const selectedAI = aiSelect.value;

        if (selectedAI === 'grok') {
            populateModels(grokModels);
        } else if (selectedAI === 'chatgpt') {
            populateModels(openaiModels);
        } else {
            // Reset to disabled/empty
            modelSelect.innerHTML = '<option value="" selected disabled>Select model after choosing AI</option>';
            modelSelect.disabled = true;
        }
    });
});
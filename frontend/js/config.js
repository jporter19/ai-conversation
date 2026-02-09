// frontend/js/config.js
// Purpose: Central place for constants, configuration, model lists, and shared helpers

export const STORAGE_KEY = 'ai-conversation-hub-current-chat';
export const STORAGE_AI_KEY = 'ai-conversation-hub-selected-ai';
export const STORAGE_MODEL_KEY = 'ai-conversation-hub-selected-model';

export const grokModels = [
    { value: 'grok-4-1-fast-reasoning', label: 'Grok 4.1 Fast (Reasoning)', tooltip: 'Fast reasoning model – excellent for complex problem solving, logic, math, and agentic tasks' },
    { value: 'grok-4-1-fast-non-reasoning', label: 'Grok 4.1 Fast (Non-Reasoning)', tooltip: 'Fast non-reasoning model – quick general-purpose responses, creative writing, casual chat' },
    { value: 'grok-code-fast-1', label: 'Grok Code Fast 1 (Coding-Optimized)', tooltip: 'Coding-optimized model – best for programming, debugging, code generation, and technical tasks' },
    { value: 'grok-4-fast-reasoning', label: 'Grok 4 Fast (Reasoning)', tooltip: 'Balanced fast reasoning – strong all-rounder with good speed and logic' },
    { value: 'grok-4-fast-non-reasoning', label: 'Grok 4 Fast (Non-Reasoning)', tooltip: 'Fast general model – quick answers, conversations, creative content' },
    { value: 'grok-4-0709', label: 'Grok 4 (0709 snapshot)', tooltip: 'Previous flagship version of Grok 4 – very capable' },
    { value: 'grok-3', label: 'Grok 3', tooltip: 'Solid general-purpose model, good balance of speed and quality' },
    { value: 'grok-3-mini', label: 'Grok 3 Mini', tooltip: 'Fast & lightweight – great for quick replies and lower latency' },
    { value: 'grok-2-vision-1212', label: 'Grok 2 Vision (1212 - Multimodal)', tooltip: 'Multimodal model – handles text + image understanding' },
    { value: 'grok-2-image-1212', label: 'Grok Image (Flux)', tooltip: 'Text-to-image generation – fast & high quality' },
    { value: 'grok-imagine-image', label: 'Grok Imagine', tooltip: 'xAI\'s latest creative image generator' }
];

export const openaiModels = [
    { value: 'gpt-5.2', label: 'GPT-5.2 (Flagship)', tooltip: 'Best overall for coding, reasoning, agentic tasks, and complex problems' },
    { value: 'gpt-5.2-pro', label: 'GPT-5.2 Pro (Extended reasoning)', tooltip: 'Extended reasoning – ideal for deep analysis and long-chain thinking' },
    { value: 'gpt-5-mini', label: 'GPT-5 Mini (Faster)', tooltip: 'Cost-efficient – excellent for everyday use and quick coding' },
    { value: 'gpt-5-nano', label: 'GPT-5 Nano (Fastest)', tooltip: 'Fast & cheapest – good for simple tasks and low-latency responses' },
    { value: 'gpt-5', label: 'GPT-5 (Previous flagship)', tooltip: 'Previous flagship – still very capable for most uses' },
    { value: 'dall-e-3', label: 'DALL·E 3', tooltip: 'OpenAI flagship image generator – excellent quality' }
];

// Shared helper: populate model dropdown with tooltips
export function populateModels(models) {
    const modelSelect = document.getElementById('model-select');

    if (!modelSelect) {
        console.error('[populateModels] model-select element not found');
        return;
    }

    modelSelect.innerHTML = '';

    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = 'Select model';
    placeholder.disabled = true;
    placeholder.selected = true;
    placeholder.dataset.tooltip = 'Choose a model after selecting an AI';
    modelSelect.appendChild(placeholder);

    models.forEach(m => {
        const opt = document.createElement('option');
        opt.value = m.value;
        opt.textContent = m.label;
        opt.dataset.tooltip = m.tooltip || 'No description available';
        modelSelect.appendChild(opt);
    });

    modelSelect.disabled = false;
    console.log('[populateModels] Dropdown populated and enabled');
}
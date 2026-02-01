// frontend/js/config.js
export const STORAGE_KEY = 'ai-conversation-hub-current-chat';
export const STORAGE_AI_KEY = 'ai-conversation-hub-selected-ai';
export const STORAGE_MODEL_KEY = 'ai-conversation-hub-selected-model';

export const grokModels = [
    { value: 'grok-4-1-fast-reasoning', label: 'Grok 4.1 Fast (Reasoning)' },
    { value: 'grok-4-1-fast-non-reasoning', label: 'Grok 4.1 Fast (Non-Reasoning)' },
    { value: 'grok-code-fast-1', label: 'Grok Code Fast 1 (Coding-Optimized)' },
    { value: 'grok-4-fast-reasoning', label: 'Grok 4 Fast (Reasoning)' },
    { value: 'grok-4-fast-non-reasoning', label: 'Grok 4 Fast (Non-Reasoning)' },
    { value: 'grok-4-0709', label: 'Grok 4 (0709 snapshot)' },
    { value: 'grok-3', label: 'Grok 3' },
    { value: 'grok-3-mini', label: 'Grok 3 Mini' },
    { value: 'grok-2-vision-1212', label: 'Grok 2 Vision (1212 - Multimodal)' }
];

export const openaiModels = [
    { value: 'gpt-5.2', label: 'GPT-5.2 (Flagship - Best for coding/agentic)' },
    { value: 'gpt-5.2-pro', label: 'GPT-5.2 Pro (Extended reasoning)' },
    { value: 'gpt-5-mini', label: 'GPT-5 Mini (Faster, cost-efficient)' },
    { value: 'gpt-5-nano', label: 'GPT-5 Nano (Fastest, cheapest)' },
    { value: 'gpt-5', label: 'GPT-5 (Previous flagship)' }
];
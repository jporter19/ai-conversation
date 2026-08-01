# app/services/setup/presets.py — curated provider presets for discovery.
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple

# ── Knowledge base ─────────────────────────────────────────────────────────────
# Curated facts used for rule-based discovery. Model ids are best-effort defaults.

PRESETS: List[Dict[str, Any]] = [
    {
        "id": "groq",
        "label": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "api_key_name": "GROQ_API_KEY",
        "key_test": "auto",
        "supports_tools": True,
        "badge_color": "#f55036",
        "keywords": ["groq"],
        "models": [
            {
                "value": "llama-3.1-8b-instant",
                "label": "Llama 3.1 8B Instant",
                "aliases": ["llama 8b", "llama3.1 8b", "8b"],
                "capability": "chat",
            },
            {
                "value": "llama-3.3-70b-versatile",
                "label": "Llama 3.3 70B Versatile",
                "aliases": ["llama 70b", "70b"],
                "capability": "chat",
            },
            {
                "value": "llama-3.1-70b-versatile",
                "label": "Llama 3.1 70B Versatile",
                "aliases": [],
                "capability": "chat",
            },
            {
                "value": "mixtral-8x7b-32768",
                "label": "Mixtral 8x7B",
                "aliases": ["mixtral"],
                "capability": "chat",
            },
            {
                "value": "gemma2-9b-it",
                "label": "Gemma 2 9B",
                "aliases": ["gemma"],
                "capability": "chat",
            },
            {
                "value": "whisper-large-v3",
                "label": "Whisper Large v3 (STT)",
                "aliases": ["whisper", "speech to text", "stt", "transcribe"],
                "capability": "stt",
            },
            {
                "value": "whisper-large-v3-turbo",
                "label": "Whisper Large v3 Turbo (STT)",
                "aliases": ["whisper turbo", "turbo whisper"],
                "capability": "stt",
            },
        ],
        "notes": "Groq uses an OpenAI-compatible API. Get a key at console.groq.com.",
    },
    {
        "id": "openai",
        "label": "OpenAI / ChatGPT",
        "base_url": "https://api.openai.com/v1",
        "api_key_name": "OPENAI_API_KEY",
        "key_test": "auto",
        "supports_tools": True,
        "supports_image_gen": True,
        "badge_color": "#10a37f",
        "keywords": ["openai", "chatgpt", "gpt", "whisper"],
        "models": [
            {
                "value": "gpt-4o",
                "label": "GPT-4o",
                "aliases": ["4o"],
                "capability": "chat",
            },
            {
                "value": "gpt-4o-mini",
                "label": "GPT-4o Mini",
                "aliases": ["4o mini", "mini"],
                "capability": "chat",
            },
            {
                "value": "gpt-image-1",
                "label": "GPT Image 1",
                "aliases": ["image", "dall-e", "dalle"],
                "capability": "image",
            },
            {
                "value": "whisper-1",
                "label": "Whisper 1 (STT)",
                "aliases": ["whisper", "speech to text", "stt", "transcribe", "transcription"],
                "capability": "stt",
            },
            {
                "value": "gpt-4o-transcribe",
                "label": "GPT-4o Transcribe (STT)",
                "aliases": ["4o transcribe", "gpt transcribe"],
                "capability": "stt",
            },
            {
                "value": "tts-1",
                "label": "TTS-1",
                "aliases": ["text to speech", "tts"],
                "capability": "tts",
            },
            {
                "value": "tts-1-hd",
                "label": "TTS-1 HD",
                "aliases": ["tts hd", "hd tts"],
                "capability": "tts",
            },
        ],
        "notes": "Maps to the built-in ChatGPT provider if it already exists.",
        "maps_to_existing": "chatgpt",
    },
    {
        "id": "xai",
        "label": "Grok (xAI)",
        "base_url": "https://api.x.ai/v1",
        "api_key_name": "XAI_API_KEY",
        "key_test": "auto",
        "supports_tools": True,
        "supports_image_gen": True,
        "badge_color": "#1a535c",
        "keywords": ["xai", "x.ai", "grok"],
        "models": [
            {
                "value": "grok-4.5",
                "label": "Grok 4.5",
                "aliases": ["4.5", "chat", "flagship"],
                "capability": "chat",
            },
            {
                "value": "grok-4.3",
                "label": "Grok 4.3",
                "aliases": ["4.3"],
                "capability": "chat",
            },
            {
                "value": "grok-imagine-image",
                "label": "Grok Imagine (Fast)",
                "aliases": ["imagine", "image gen", "image generation"],
                "capability": "image",
            },
            {
                "value": "grok-imagine-image-quality",
                "label": "Grok Imagine (Quality)",
                "aliases": ["imagine quality", "image quality"],
                "capability": "image",
            },
            {
                "value": "grok-stt",
                "label": "Grok Speech-to-Text",
                "aliases": [
                    "speech to text",
                    "speech-to-text",
                    "stt",
                    "transcribe",
                    "transcription",
                    "voice to text",
                    "audio to text",
                ],
                "capability": "stt",
                "endpoint_hint": "POST https://api.x.ai/v1/stt (multipart file or URL)",
            },
            {
                "value": "grok-tts",
                "label": "Grok Text-to-Speech",
                "aliases": ["text to speech", "text-to-speech", "tts", "speak"],
                "capability": "tts",
                "endpoint_hint": "POST https://api.x.ai/v1/tts",
            },
        ],
        "notes": "Maps to the built-in Grok provider if it already exists. STT uses /v1/stt; chat uses /v1/chat/completions.",
        "maps_to_existing": "grok",
    },
    {
        "id": "magisterium",
        "label": "Magisterium AI",
        "base_url": "https://www.magisterium.com/api/v1",
        "api_key_name": "MAGISTERIUM_API_KEY",
        "key_test": "chat",
        "supports_tools": False,
        "badge_color": "#6b4c9a",
        "keywords": ["magisterium", "catholic"],
        "models": [
            {
                "value": "magisterium-1",
                "label": "Magisterium 1",
                "aliases": [],
                "capability": "chat",
            },
        ],
        "notes": "OpenAI-compatible chat only (no /models list).",
        "maps_to_existing": "magisterium",
    },
    {
        "id": "openrouter",
        "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_name": "OPENROUTER_API_KEY",
        "key_test": "auto",
        "supports_tools": True,
        "badge_color": "#6566f1",
        "keywords": ["openrouter"],
        "models": [
            {
                "value": "openai/gpt-4o-mini",
                "label": "GPT-4o Mini (via OpenRouter)",
                "aliases": ["gpt-4o-mini"],
                "capability": "chat",
            },
            {
                "value": "meta-llama/llama-3.1-8b-instruct",
                "label": "Llama 3.1 8B",
                "aliases": ["llama 8b", "8b"],
                "capability": "chat",
            },
        ],
        "notes": "Many models available; model ids are vendor/model.",
    },
    {
        "id": "together",
        "label": "Together AI",
        "base_url": "https://api.together.xyz/v1",
        "api_key_name": "TOGETHER_API_KEY",
        "key_test": "auto",
        "supports_tools": False,
        "badge_color": "#0f6fff",
        "keywords": ["together"],
        "models": [
            {
                "value": "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
                "label": "Llama 3.1 8B Turbo",
                "aliases": ["llama 8b", "8b"],
                "capability": "chat",
            },
        ],
        "notes": "OpenAI-compatible. Confirm exact model id in Together docs.",
    },
    {
        "id": "deepseek",
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "api_key_name": "DEEPSEEK_API_KEY",
        "key_test": "auto",
        "supports_tools": True,
        "badge_color": "#4d6bfe",
        "keywords": ["deepseek"],
        "models": [
            {
                "value": "deepseek-chat",
                "label": "DeepSeek Chat",
                "aliases": ["chat"],
                "capability": "chat",
            },
            {
                "value": "deepseek-reasoner",
                "label": "DeepSeek Reasoner",
                "aliases": ["reasoner", "r1"],
                "capability": "chat",
            },
        ],
        "notes": "OpenAI-compatible API.",
    },
    {
        "id": "fireworks",
        "label": "Fireworks AI",
        "base_url": "https://api.fireworks.ai/inference/v1",
        "api_key_name": "FIREWORKS_API_KEY",
        "key_test": "auto",
        "supports_tools": False,
        "badge_color": "#7c3aed",
        "keywords": ["fireworks"],
        "models": [
            {
                "value": "accounts/fireworks/models/llama-v3p1-8b-instruct",
                "label": "Llama 3.1 8B",
                "aliases": ["llama 8b", "8b"],
                "capability": "chat",
            },
        ],
        "notes": "OpenAI-compatible inference API.",
    },
]


# Capability keywords for free-text intent detection
_CAP_HINTS: List[Tuple[str, List[str]]] = [
    ("stt", [
        "speech to text", "speech-to-text", "stt", "transcribe", "transcription",
        "voice to text", "audio to text", "dictation", "asr",
    ]),
    ("tts", [
        "text to speech", "text-to-speech", "tts", "speak", "voice synthesis",
        "read aloud", "speech synthesis",
    ]),
    ("image", [
        "image gen", "image generation", "imagine", "dall-e", "dalle",
        "draw", "picture", "generate image", "flux",
    ]),
    ("transcript", [
        "youtube transcript", "youtube captions", "video transcript",
    ]),
    ("chat", [
        "chat", "llm", "conversation", "reasoning", "coding model",
    ]),
]




def list_presets_public() -> List[Dict[str, Any]]:
    out = []
    for p in PRESETS:
        out.append({
            "id": p["id"],
            "label": p["label"],
            "keywords": p.get("keywords") or [],
            "notes": p.get("notes") or "",
            "models": [
                {
                    "value": m["value"],
                    "label": m.get("label") or m["value"],
                    "capability": m.get("capability") or "chat",
                }
                for m in (p.get("models") or [])
            ],
        })
    return out

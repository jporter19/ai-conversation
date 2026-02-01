# app/api/v1/chat.py
# Purpose: API router for the /api/chat endpoint
#          Handles streaming chat requests to Grok (xAI) or ChatGPT (OpenAI)
#          Acts as a secure proxy — API keys never leave the backend

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, AsyncGenerator
import httpx
import json
import os
from dotenv import load_dotenv

load_dotenv()

router = APIRouter()

# API keys from .env
XAI_API_KEY = os.getenv("XAI_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    ai: str
    model: str
    messages: List[ChatMessage]

# ── Streaming helpers ───────────────────────────────────────────────────────────

async def stream_grok_response(messages: List[Dict], model: str) -> AsyncGenerator[str, None]:
    """Stream response from xAI Grok API"""
    if not XAI_API_KEY:
        yield "Error: xAI API key not configured in .env\n"
        return

    url = "https://api.x.ai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {XAI_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "temperature": 0.7
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            async with client.stream("POST", url, json=payload, headers=headers) as response:
                if response.status_code != 200:
                    error = await response.aread()
                    yield f"xAI error {response.status_code}: {error.decode('utf-8', errors='ignore')}\n"
                    return

                async for line in response.aiter_lines():
                    # line is already str in modern httpx — no decode needed
                    if line.startswith('data: '):
                        data = line[6:].strip()
                        if data == '[DONE]':
                            break
                        try:
                            parsed = json.loads(data)
                            content = parsed["choices"][0]["delta"].get("content", "")
                            if content:
                                yield content
                        except Exception as e:
                            yield f"[JSON parse error: {str(e)}]\n"
        except Exception as e:
            yield f"Stream error (Grok): {str(e)}\n"


async def stream_openai_response(messages: List[Dict], model: str) -> AsyncGenerator[str, None]:
    """Stream response from OpenAI API"""
    if not OPENAI_API_KEY:
        yield "Error: OpenAI API key not configured in .env\n"
        return

    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
    }

    reasoning_keywords = ["o1", "gpt-5.2", "gpt-5.2-pro"]
    if not any(k in model.lower() for k in reasoning_keywords):
        payload["temperature"] = 0.7

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            async with client.stream("POST", url, json=payload, headers=headers) as response:
                if response.status_code != 200:
                    error = await response.aread()
                    yield f"OpenAI error {response.status_code}: {error.decode('utf-8', errors='ignore')}\n"
                    return

                async for line in response.aiter_lines():
                    if line.startswith('data: '):
                        data = line[6:].strip()
                        if data == '[DONE]':
                            break
                        try:
                            parsed = json.loads(data)
                            content = parsed["choices"][0]["delta"].get("content", "")
                            if content:
                                yield content
                        except Exception as e:
                            yield f"[JSON parse error: {str(e)}]\n"
        except Exception as e:
            yield f"Stream error (OpenAI): {str(e)}\n"

# ── Chat endpoint ───────────────────────────────────────────────────────────────
@router.post("/chat")
async def chat(request: ChatRequest):
    """
    Proxy endpoint for chatting with Grok or ChatGPT.
    Streams response tokens in real-time.
    """
    if request.ai not in ["grok", "chatgpt"]:
        raise HTTPException(status_code=400, detail="Invalid AI")

    api_messages = [{"role": m.role, "content": m.content} for m in request.messages]

    if request.ai == "grok":
        return StreamingResponse(
            stream_grok_response(api_messages, request.model),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive"
            }
        )
    else:
        return StreamingResponse(
            stream_openai_response(api_messages, request.model),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive"
            }
        )
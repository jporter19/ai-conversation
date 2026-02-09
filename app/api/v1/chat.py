# app/api/v1/chat.py
# Purpose: API router for chat, image generation, and tool calling
#          - Handles text streaming for Grok and ChatGPT
#          - Separate image generation endpoint (preserves existing feature)
#          - Web search tool calling with reliable triggering for current info
#          - Modular: web_search logic in tools.py

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI
from pydantic import BaseModel
from typing import List
import httpx  # Required for Grok image generation
import json
import re
import asyncio
from app.config import settings  # For API keys

# Centralized tools
from app.api.v1.tools import WEB_SEARCH_TOOL, execute_web_search

router = APIRouter()

# API keys from config (assumed imported elsewhere or use directly)
# XAI_API_KEY, OPENAI_API_KEY from app.config.settings

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    ai: str
    model: str
    messages: List[ChatMessage]

# ── Endpoints ───────────────────────────────────────────────────────────────────

@router.post("/chat")
async def chat(request: ChatRequest):
    if request.ai not in ["grok", "chatgpt"]:
        raise HTTPException(status_code=400, detail="Invalid AI: must be 'grok' or 'chatgpt'")

    if not request.model:
        raise HTTPException(status_code=400, detail="Model is required")

    messages = [{"role": m.role, "content": m.content} for m in request.messages]

    # Strong system prompt to force tool use
    system_prompt = {
        "role": "system",
        "content": "You MUST use the web_search tool for ANY question about current prices, news, events, weather, stocks, or data after January 2025. "
                   "Never guess or use old knowledge. Always search first and base response on results."
    }
    messages = [system_prompt] + messages

    # Detect current-info keywords in last user message
    user_query = request.messages[-1].content.lower() if request.messages else ""
    needs_search = bool(re.search(r"\b(current|today|latest|price|news|weather|stock|score|event|live)\b", user_query))

    tool_choice = (
        {"type": "function", "function": {"name": "web_search"}}
        if needs_search
        else "auto"
    )

    client = AsyncOpenAI(
        api_key=settings.XAI_API_KEY if request.ai == "grok" else settings.OPENAI_API_KEY,
        base_url="https://api.x.ai/v1" if request.ai == "grok" else "https://api.openai.com/v1"
    )

    # First call
    response = await client.chat.completions.create(
        model=request.model,
        messages=messages,
        tools=[WEB_SEARCH_TOOL],
        tool_choice=tool_choice,
        stream=True
    )

    async def event_generator():
        tool_call = None
        async for chunk in response:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta:
                if delta.content:
                    yield delta.content
                if delta.tool_calls:
                    tool_call = delta.tool_calls[0]

        if tool_call and tool_call.function.name == "web_search":
            args = json.loads(tool_call.function.arguments)
            query = args["query"]
            snippet = await asyncio.to_thread(execute_web_search, query)  # Non-blocking
            
            messages.append({"role": "assistant", "tool_calls": [tool_call.model_dump()]})
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": snippet
            })
            
            second_response = await client.chat.completions.create(
                model=request.model,
                messages=messages,
                stream=True
            )
            async for chunk in second_response:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@router.post("/generate-image")
async def generate_image(request: Request):
    body = await request.json()
    ai = body.get("ai")
    model = body.get("model")
    prompt = body.get("prompt")

    if not prompt:
        raise HTTPException(400, "Missing prompt")

    try:
        if ai == "chatgpt":
            print(f"DEBUG: OPENAI_API_KEY for DALL-E: {settings.OPENAI_API_KEY[:10] if settings.OPENAI_API_KEY else 'None'}...")
            if not settings.OPENAI_API_KEY:
                raise HTTPException(500, "OPENAI_API_KEY not configured")
            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            resp = await client.images.generate(
                model=model,
                prompt=prompt,
                n=1,
                size="1024x1024",
                response_format="url"
            )
            url = resp.data[0].url

        elif ai == "grok":
            async with httpx.AsyncClient(timeout=60.0) as client:
                r = await client.post(
                    "https://api.x.ai/v1/images/generations",
                    headers={"Authorization": f"Bearer {settings.XAI_API_KEY}"},
                    json={
                        "model": model,
                        "prompt": prompt,
                        "n": 1,
                        "image_format": "url"
                    }
                )
                r.raise_for_status()
                data = r.json()
                url = data["data"][0]["url"]
        else:
            raise HTTPException(400, "Unsupported AI for image generation")

        return {"url": url}

    except Exception as e:
        print("Image gen error:", e)
        raise HTTPException(500, str(e))
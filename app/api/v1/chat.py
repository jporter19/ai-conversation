# app/api/v1/chat.py
# Purpose: API router for chat and image generation endpoints
#          Proxies requests to xAI (Grok) or OpenAI (ChatGPT/DALL·E)
#          API keys loaded centrally from app.config.settings

from fastapi import APIRouter, HTTPException, Request
from app.api.v1.tools import WEB_SEARCH_TOOL, execute_web_search
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI
from pydantic import BaseModel
from typing import List, Dict, AsyncGenerator
import httpx
import json
import re  # For keyword matching

# Centralized settings (API keys, etc.)
from app.config import settings

router = APIRouter()

@router.get("/test")
def test_endpoint():
    return {"status": "chat router is alive"}

# Use centralized keys — raises clear error if missing
XAI_API_KEY = settings.XAI_API_KEY
OPENAI_API_KEY = settings.OPENAI_API_KEY

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    ai: str
    model: str
    messages: List[ChatMessage]

# ── Streaming helpers ───────────────────────────────────────────────────────────

async def stream_grok_response(messages: List[Dict], model: str) -> AsyncGenerator[str, None]:
    if not XAI_API_KEY:
        yield "Error: xAI API key not configured (check .env and app.config)\n"
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
                    line_str = line.decode('utf-8') if isinstance(line, bytes) else line
                    if line_str.startswith('data: '):
                        data = line_str[6:].strip()
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
    if not OPENAI_API_KEY:
        yield "Error: OpenAI API key not configured (check .env and app.config)\n"
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

    # Avoid temperature for reasoning/o1 models
    no_temperature_models = [
        "o1", "o1-preview", "o1-mini", "o1-pro",
        "gpt-5", "gpt-5.2", "gpt-5.2-pro", "reasoning"
    ]
    if not any(keyword in model.lower() for keyword in no_temperature_models):
        payload["temperature"] = 0.7

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            async with client.stream("POST", url, json=payload, headers=headers) as response:
                if response.status_code != 200:
                    error = await response.aread()
                    yield f"OpenAI error {response.status_code}: {error.decode('utf-8', errors='ignore')}\n"
                    return

                async for line in response.aiter_lines():
                    line_str = line.decode('utf-8') if isinstance(line, bytes) else line
                    if line_str.startswith('data: '):
                        data = line_str[6:].strip()
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
# ── Endpoints ───────────────────────────────────────────────────────────────────

@router.post("/chat")
async def chat(request: ChatRequest):
    if request.ai not in ["grok", "chatgpt"]:
        raise HTTPException(status_code=400, detail="Invalid AI: must be 'grok' or 'chatgpt'")

    if not request.model:
        raise HTTPException(status_code=400, detail="Model is required")

    messages = [{"role": m.role, "content": m.content} for m in request.messages]

    # Strong system prompt to force tool use for current data
    system_prompt = {
        "role": "system",
        "content": "You are a helpful assistant with access to a web_search tool. "
                   "For ANY question involving current or recent information (prices, news, events, weather, sports scores, stock prices, or data after January 2025), "
                   "you MUST use the web_search tool. Do not guess or use old knowledge. "
                   "Always search first for up-to-date facts."
    }
    messages = [system_prompt] + messages

    print(f"DEBUG: Messages sent to API (length: {len(messages)})")  # Log message count
    
    # Unified client (OpenAI compat for Grok)
    client = AsyncOpenAI(
        api_key=XAI_API_KEY if request.ai == "grok" else OPENAI_API_KEY,
        base_url="https://api.x.ai/v1" if request.ai == "grok" else "https://api.openai.com/v1"
    )

    # Tools
    tools = [WEB_SEARCH_TOOL]

    # First call with tools
    response = await client.chat.completions.create(
        model=request.model,
        messages=messages,
        tools=tools,
        tool_choice="auto",
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
            print("DEBUG: Tool call DETECTED - executing web_search")
            args = json.loads(tool_call.function.arguments)
            query = args["query"]
            snippet = execute_web_search(query)
            print(f"DEBUG: Search query: {query}")
            print(f"DEBUG: Search results snippet: {snippet[:200]}...")
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
        else:
            print("DEBUG: No tool call - direct response")
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
            client = AsyncOpenAI(api_key=OPENAI_API_KEY)
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
                    headers={"Authorization": f"Bearer {XAI_API_KEY}"},
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

# app/api/v1/chat.py
# Purpose: Thin HTTP entrypoint. Capability dispatch lives in app.services.handlers.

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.core.auth import request_user_id
from app.services.handlers import stream_response
from app.services.handlers.context_builder import build_context, require_provider, require_model
from app.services.image_gen import ImageGenError, generate_image_url
from app.services.media_store import resolve_media_file

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_AUDIO_BYTES = 50 * 1024 * 1024


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    ai: str
    model: str
    messages: List[ChatMessage]
    context_id: Optional[str] = None


@router.post("/chat")
async def chat(body: ChatRequest, request: Request):
    uid = request_user_id(request)
    ctx = build_context(
        ai=body.ai,
        model=body.model,
        messages=[{"role": m.role, "content": m.content} for m in body.messages],
        context_id=body.context_id,
        user_id=uid,
    )
    return await stream_response(ctx)


@router.get("/media/{token}")
async def get_media(token: str, request: Request):
    uid = request_user_id(request)
    resolved = resolve_media_file(token, user_id=uid)
    if not resolved:
        raise HTTPException(404, "Media not found")
    path, content_type = resolved
    return FileResponse(
        path,
        media_type=content_type or "audio/mpeg",
        headers={
            "Cache-Control": "private, max-age=86400",
            "Accept-Ranges": "bytes",
            "Content-Disposition": f'inline; filename="{path.name}"',
        },
    )


@router.post("/transcribe")
async def transcribe(
    request: Request,
    ai: str = Form(...),
    model: str = Form(...),
    file: UploadFile = File(...),
    notes: Optional[str] = Form(None),
    language: Optional[str] = Form(None),
):
    uid = request_user_id(request)
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Empty audio file")
    if len(raw) > MAX_AUDIO_BYTES:
        raise HTTPException(
            413,
            f"Audio too large ({len(raw)} bytes). Max is {MAX_AUDIO_BYTES // (1024 * 1024)} MB.",
        )

    filename = file.filename or "audio.wav"
    notes_text = (notes or "").strip()
    user_content = f"[Audio: {filename}]"
    if notes_text:
        user_content = f"{user_content}\n{notes_text}"

    ctx = build_context(
        ai=ai,
        model=model,
        messages=[{"role": "user", "content": user_content}],
        require_capability="stt",
        user_id=uid,
        audio_bytes=raw,
        audio_filename=filename,
        audio_content_type=file.content_type,
        audio_language=(language or "").strip() or None,
    )
    return await stream_response(ctx)


@router.post("/generate-image")
async def generate_image(request: Request):
    """Legacy JSON image endpoint; prefer POST /chat with an image model."""
    body = await request.json()
    ai = body.get("ai")
    model = body.get("model")
    prompt = body.get("prompt")
    if not prompt:
        raise HTTPException(400, "Missing prompt")
    model = require_model(model)
    provider = require_provider(ai)
    # capability check via builder without streaming
    build_context(
        ai=ai,
        model=model,
        messages=[{"role": "user", "content": prompt}],
        require_capability="image",
        user_id=request_user_id(request),
    )
    try:
        url = await generate_image_url(provider, model, prompt)
        return {"url": url}
    except ImageGenError as e:
        raise HTTPException(e.status_code, str(e))
    except Exception as e:
        logger.exception("Image gen error")
        raise HTTPException(500, str(e))

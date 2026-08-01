# app/api/v1/conversations.py
# Purpose: Store / list / restore / delete named conversations

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services import conversation_store

router = APIRouter(prefix="/conversations", tags=["conversations"])


class MessageIn(BaseModel):
    role: str
    content: str
    ai: Optional[str] = None


class StoreConversationIn(BaseModel):
    name: str
    kind: str = "whole"  # whole | summary
    messages: List[MessageIn] = Field(default_factory=list)


@router.get("")
async def list_conversations():
    return {"conversations": conversation_store.list_conversations()}


@router.get("/{conv_id}")
async def get_conversation(conv_id: str):
    data = conversation_store.get_conversation(conv_id)
    if not data:
        raise HTTPException(404, "Conversation not found")
    return data


@router.post("")
async def store_conversation(body: StoreConversationIn):
    messages = [m.model_dump(exclude_none=True) for m in body.messages]
    kind = (body.kind or "whole").lower()
    if kind == "summary":
        messages = conversation_store.build_summary_messages(messages)
    try:
        saved = conversation_store.save_conversation(
            name=body.name,
            messages=messages,
            kind=kind,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"conversation": saved}


@router.delete("/{conv_id}")
async def delete_conversation(conv_id: str):
    ok = conversation_store.delete_conversation(conv_id)
    if not ok:
        raise HTTPException(404, "Conversation not found")
    return {"ok": True}

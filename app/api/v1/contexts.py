# app/api/v1/contexts.py
# Purpose: CRUD API for conversation contexts (personas / guidelines).

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.auth import request_user_id
from app.services import context_store

router = APIRouter(prefix="/contexts", tags=["contexts"])


class ContextIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    content: str = Field(..., min_length=1, max_length=20000)
    description: str = Field("", max_length=400)
    id: Optional[str] = Field(None, max_length=80)


class ContextUpdateIn(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    content: Optional[str] = Field(None, min_length=1, max_length=20000)
    description: Optional[str] = Field(None, max_length=400)


@router.get("")
async def list_contexts(request: Request):
    uid = request_user_id(request)
    return {"contexts": context_store.list_contexts(user_id=uid)}


@router.get("/{context_id}")
async def get_context(context_id: str, request: Request):
    uid = request_user_id(request)
    c = context_store.get_context(context_id, user_id=uid)
    if not c:
        raise HTTPException(404, "Context not found")
    return {"context": c}


@router.post("")
async def create_context(body: ContextIn, request: Request):
    uid = request_user_id(request)
    try:
        item = context_store.create_context(
            name=body.name,
            content=body.content,
            description=body.description or "",
            context_id=body.id,
            user_id=uid,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"context": item, "contexts": context_store.list_contexts(user_id=uid)}


@router.put("/{context_id}")
async def update_context(context_id: str, body: ContextUpdateIn, request: Request):
    uid = request_user_id(request)
    try:
        item = context_store.update_context(
            context_id,
            name=body.name,
            content=body.content,
            description=body.description,
            user_id=uid,
        )
    except ValueError as e:
        msg = str(e)
        raise HTTPException(404 if "not found" in msg.lower() else 400, msg)
    return {"context": item, "contexts": context_store.list_contexts(user_id=uid)}


@router.delete("/{context_id}")
async def delete_context(context_id: str, request: Request):
    uid = request_user_id(request)
    ok = context_store.delete_context(context_id, user_id=uid)
    if not ok:
        raise HTTPException(404, "Context not found")
    return {"ok": True, "contexts": context_store.list_contexts(user_id=uid)}

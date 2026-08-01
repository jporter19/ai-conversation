# app/api/v1/auth.py
# Purpose: Login / logout / session status for the shared hub account.

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core.auth import (
    auth_disabled,
    clear_login_failures,
    current_username,
    login_rate_limited,
    login_user,
    logout_user,
    record_login_failure,
)
from app.services.auth_store import authenticate

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginBody(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=256)


@router.post("/login")
async def login(body: LoginBody, request: Request):
    if auth_disabled():
        login_user(request, "dev")
        return {"ok": True, "username": "dev", "auth_disabled": True}

    if login_rate_limited(request):
        return JSONResponse(
            {"detail": "Too many failed attempts. Try again later."},
            status_code=429,
        )

    user = authenticate(body.username.strip(), body.password)
    if not user:
        record_login_failure(request)
        return JSONResponse(
            {"detail": "Invalid username or password."},
            status_code=401,
        )

    clear_login_failures(request)
    login_user(request, user)
    return {"ok": True, "username": user}


@router.post("/logout")
async def logout(request: Request):
    logout_user(request)
    return {"ok": True}


@router.get("/me")
async def me(request: Request):
    if auth_disabled():
        return {"authenticated": True, "username": "dev", "auth_disabled": True}
    user = current_username(request)
    if not user:
        return {"authenticated": False, "username": None}
    return {"authenticated": True, "username": user}

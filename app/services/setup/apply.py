# app/services/setup/apply.py — persist setup proposals to settings_store.
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional

from app.services import settings_store
from app.services.key_test import test_api_key
from app.services.setup.rules import _key_info

async def apply_setup(
    proposal: Dict[str, Any],
    api_key: Optional[str] = None,
    run_test: bool = True,
) -> Dict[str, Any]:
    """
    Create/update provider, attach model(s), save API key, optionally test.
    """
    pid = (proposal.get("id") or "").strip()
    if not pid:
        raise ValueError("Provider id is required")

    label = (proposal.get("label") or pid).strip()
    base_url = (proposal.get("base_url") or "").strip().rstrip("/")
    base_url = re.sub(r"/chat/completions$", "", base_url, flags=re.I)
    api_key_name = (proposal.get("api_key_name") or f"{pid.upper()}_API_KEY").strip()
    key_optional = bool(proposal.get("api_key_optional"))

    existing = settings_store.get_provider(pid) or {}
    models_in = proposal.get("models") or []
    merged_models = list(existing.get("models") or [])
    seen = {m.get("value") for m in merged_models}
    for m in models_in:
        val = (m.get("value") or "").strip()
        if not val:
            continue
        if val in seen:
            for old in merged_models:
                if old.get("value") == val:
                    if m.get("label"):
                        old["label"] = m["label"]
                    if m.get("capability"):
                        old["capability"] = m["capability"]
                    if m.get("tooltip"):
                        old["tooltip"] = m["tooltip"]
            continue
        merged_models.append({
            "value": val,
            "label": m.get("label") or val,
            "tooltip": m.get("tooltip") or "",
            "capability": m.get("capability") or "chat",
            "manual": True,
        })
        seen.add(val)

    if not base_url and existing.get("base_url"):
        base_url = existing["base_url"]
    if not base_url and proposal.get("type") != "tool":
        if proposal.get("type") != "tool" and not key_optional:
            raise ValueError("base_url is required for chat providers")

    cap = (models_in[0].get("capability") if models_in else None) or "chat"
    supports_image = bool(
        proposal.get("supports_image_gen", existing.get("supports_image_gen", False))
        or cap == "image"
    )

    provider = {
        "id": pid,
        "label": label,
        "enabled": True,
        "type": proposal.get("type") or existing.get("type") or "openai_compatible",
        "base_url": base_url or existing.get("base_url"),
        "api_key_name": api_key_name,
        "api_key_optional": key_optional or bool(existing.get("api_key_optional")),
        "supports_tools": bool(proposal.get("supports_tools", existing.get("supports_tools", False))),
        "supports_image_gen": supports_image,
        "auto_update": bool(existing.get("auto_update", False)),
        "auto_update_source": existing.get("auto_update_source"),
        "key_test": proposal.get("key_test") or existing.get("key_test") or "auto",
        "badge_color": proposal.get("badge_color") or existing.get("badge_color") or "#555555",
        "models": merged_models,
    }
    if existing.get("image_api"):
        provider["image_api"] = existing["image_api"]
    if existing.get("tool_handler"):
        provider["tool_handler"] = existing["tool_handler"]

    settings_store.upsert_provider(provider)

    key_saved = False
    if api_key and str(api_key).strip():
        settings_store.save_secrets({api_key_name: str(api_key).strip()}, merge=True)
        key_saved = True

    test_result = None
    if run_test and not key_optional:
        probe_model = None
        for m in merged_models:
            if (m.get("capability") or "chat") == "chat" and m.get("value"):
                probe_model = m["value"]
                break
        if not probe_model and models_in:
            probe_model = models_in[0].get("value")
        preferred = provider.get("key_test") or "auto"
        if cap in ("stt", "tts") and not probe_model:
            preferred = "models"

        if api_key and str(api_key).strip():
            test_result = await test_api_key(
                api_key_name,
                str(api_key).strip(),
                base_url=provider.get("base_url"),
                model=probe_model or "default",
                label=label,
                key_test=preferred,
            )
        elif settings_store.get_secret(api_key_name):
            test_result = await test_api_key(
                api_key_name,
                None,
                base_url=provider.get("base_url"),
                model=probe_model or "default",
                label=label,
                key_test=preferred,
            )
        else:
            test_result = {
                "ok": False,
                "key_name": api_key_name,
                "message": f"No API key provided for {api_key_name}. Paste a key to test.",
            }

    return {
        "provider": settings_store.get_provider(pid),
        "key_saved": key_saved,
        "api_key_name": api_key_name,
        "test": test_result,
        "catalog": settings_store.public_catalog(),
    }



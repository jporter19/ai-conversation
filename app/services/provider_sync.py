# app/services/provider_sync.py
# Purpose: Single pipeline to refresh a provider's model catalog.
#          fetch remote list → describe → recommend → persist once.

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.settings_store import get_provider, get_secret, set_provider_models


async def sync_provider(
    provider_id: str,
    *,
    fetch_remote: bool = True,
    describe: bool = True,
    recommend: bool = True,
    use_ai_recommend: bool = True,
    force_describe: bool = False,
) -> Dict[str, Any]:
    """
    Canonical provider catalog refresh.

    Returns:
      {
        "provider": <updated provider dict>,
        "message": str,
        "steps": { "fetch": str|None, "describe": str|None, "recommend": str|None },
      }
    """
    provider = get_provider(provider_id)
    if not provider:
        raise ValueError(f"Unknown provider: {provider_id}")

    steps: Dict[str, Optional[str]] = {
        "fetch": None,
        "describe": None,
        "recommend": None,
    }
    models: List[Dict[str, Any]] = list(provider.get("models") or [])
    label = str(provider.get("label") or provider_id)

    # ── 1) Remote model list ─────────────────────────────────────────────────
    if fetch_remote:
        if not provider.get("auto_update"):
            steps["fetch"] = "skipped (auto_update disabled)"
        else:
            source = provider.get("auto_update_source")
            key_name = provider.get("api_key_name")
            api_key = get_secret(key_name) if key_name else None
            if not api_key:
                raise ValueError(f"API key {key_name} is not configured")
            if source not in ("openai", "xai"):
                raise ValueError(f"Unknown auto_update_source: {source}")

            from app.services.model_catalog import (
                fetch_openai_models,
                fetch_xai_models,
                maybe_bump_default_model,
            )

            remote = (
                await fetch_openai_models(api_key)
                if source == "openai"
                else await fetch_xai_models(api_key)
            )
            previous = list(provider.get("models") or [])
            prev_chat = [
                m for m in previous
                if (m.get("capability") or "chat") == "chat" and m.get("value")
            ]
            if not remote:
                if prev_chat:
                    steps["fetch"] = "remote returned no models; kept previous catalog"
                    models = previous
                else:
                    raise ValueError("Provider returned no usable models")
            else:
                from app.services.model_roster import apply_roster, roster_summary

                models = apply_roster(remote, previous, source=source)
                new_chat = [
                    m for m in models
                    if (m.get("capability") or "chat") == "chat" and m.get("value")
                ]
                if prev_chat and not new_chat:
                    models = previous
                    steps["fetch"] = (
                        f"remote had {len(remote)} ids but no chat models; "
                        "kept previous catalog"
                    )
                else:
                    filled = [s for s, v in roster_summary(models).items() if v]
                    steps["fetch"] = (
                        f"fetched {len(remote)} ids → {len(models)} in catalog "
                        f"(slots: {', '.join(filled) or 'none'})"
                    )
                    bumped = maybe_bump_default_model(provider_id, models)
                    if bumped:
                        steps["fetch"] += f"; default model → {bumped}"

    # ── 2) Descriptions ──────────────────────────────────────────────────────
    if describe and models:
        try:
            from app.services.model_descriptions import enrich_models

            models, n_desc = await enrich_models(
                models,
                provider_label=label,
                force=force_describe,
            )
            steps["describe"] = f"updated {n_desc} description(s)"
        except Exception as e:
            steps["describe"] = f"skipped: {e}"

    # ── 3) Tags + keep/remove ────────────────────────────────────────────────
    if recommend and models:
        try:
            from app.services.model_recommendations import recommend_models

            models, rec_msg = await recommend_models(
                models,
                provider_label=label,
                use_ai=use_ai_recommend,
            )
            steps["recommend"] = rec_msg
        except Exception as e:
            steps["recommend"] = f"skipped: {e}"

    # ── Persist once ─────────────────────────────────────────────────────────
    updated = set_provider_models(provider_id, models)
    parts = [f"{provider_id}: {len(models)} models"]
    for key in ("fetch", "describe", "recommend"):
        if steps[key]:
            parts.append(str(steps[key]))
    return {
        "provider": updated,
        "message": "; ".join(parts),
        "steps": steps,
    }


async def sync_all_auto_providers(
    *,
    describe: bool = True,
    recommend: bool = True,
    use_ai_recommend: bool = True,
) -> List[Dict[str, Any]]:
    """Run sync_provider for every auto_update-enabled provider."""
    from app.services.settings_store import get_providers

    results = []
    for p in get_providers():
        if not p.get("auto_update"):
            continue
        pid = p.get("id")
        if not pid:
            continue
        try:
            out = await sync_provider(
                pid,
                fetch_remote=True,
                describe=describe,
                recommend=recommend,
                use_ai_recommend=use_ai_recommend,
            )
            results.append({
                "provider_id": pid,
                "ok": True,
                "message": out["message"],
            })
        except Exception as e:
            results.append({
                "provider_id": pid,
                "ok": False,
                "message": str(e),
            })
    return results

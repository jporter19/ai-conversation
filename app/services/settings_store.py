# app/services/settings_store.py
# Purpose: Persist providers/models, API keys, and user preferences on disk.
#          Secrets live in a gitignored file; public config is versioned defaults.

from __future__ import annotations

import json
import os
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.paths import get_data_dir


def data_dir() -> Path:
    return get_data_dir()


def providers_path() -> Path:
    return data_dir() / "providers.json"


def secrets_path() -> Path:
    return data_dir() / "secrets.json"


def preferences_path() -> Path:
    return data_dir() / "preferences.json"


# Back-compat names used as call-time properties via module getattr would break
# assignments; keep thin aliases that resolve at use sites after we rewrite.

_lock = threading.RLock()

# Known key slots shown in Admin even before first save
KNOWN_SECRET_KEYS = [
    "XAI_API_KEY",
    "OPENAI_API_KEY",
    "MAGISTERIUM_API_KEY",
    "YOUTUBE_API_KEY",
]


def _ensure_data_dir() -> None:
    data_dir().mkdir(parents=True, exist_ok=True)


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return deepcopy(default)
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return deepcopy(default)


def _write_json(path: Path, data: Any) -> None:
    _ensure_data_dir()
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    tmp.replace(path)


def load_providers_config() -> Dict[str, Any]:
    with _lock:
        data = _read_json(providers_path(), {"version": 1, "providers": [], "preferences": {}})
        # Merge preferences from separate file if present
        prefs = _read_json(preferences_path(), None)
        if isinstance(prefs, dict):
            data["preferences"] = {**(data.get("preferences") or {}), **prefs}
        return data


def save_providers_config(data: Dict[str, Any]) -> None:
    with _lock:
        # Keep preferences in both places for simplicity; dedicated file wins on load
        prefs = data.get("preferences") or {}
        payload = {
            "version": data.get("version", 1),
            "providers": data.get("providers") or [],
            "preferences": prefs,
        }
        _write_json(providers_path(), payload)
        _write_json(preferences_path(), prefs)


def get_providers(enabled_only: bool = False) -> List[Dict[str, Any]]:
    cfg = load_providers_config()
    providers = cfg.get("providers") or []
    if enabled_only:
        return [p for p in providers if p.get("enabled", True)]
    return providers


def get_provider(provider_id: str) -> Optional[Dict[str, Any]]:
    for p in get_providers():
        if p.get("id") == provider_id:
            return p
    return None


def upsert_provider(provider: Dict[str, Any]) -> Dict[str, Any]:
    with _lock:
        cfg = load_providers_config()
        providers = cfg.get("providers") or []
        pid = provider.get("id")
        if not pid:
            raise ValueError("Provider id is required")
        replaced = False
        for i, p in enumerate(providers):
            if p.get("id") == pid:
                providers[i] = provider
                replaced = True
                break
        if not replaced:
            providers.append(provider)
        cfg["providers"] = providers
        save_providers_config(cfg)
        return provider


def delete_provider(provider_id: str) -> bool:
    with _lock:
        cfg = load_providers_config()
        providers = cfg.get("providers") or []
        new_list = [p for p in providers if p.get("id") != provider_id]
        if len(new_list) == len(providers):
            return False
        cfg["providers"] = new_list
        save_providers_config(cfg)
        return True


def set_provider_models(provider_id: str, models: List[Dict[str, Any]]) -> Dict[str, Any]:
    provider = get_provider(provider_id)
    if not provider:
        raise ValueError(f"Unknown provider: {provider_id}")
    provider = deepcopy(provider)
    provider["models"] = models
    return upsert_provider(provider)


def add_model(provider_id: str, model: Dict[str, Any]) -> Dict[str, Any]:
    provider = get_provider(provider_id)
    if not provider:
        raise ValueError(f"Unknown provider: {provider_id}")
    provider = deepcopy(provider)
    models = provider.get("models") or []
    value = model.get("value")
    if not value:
        raise ValueError("Model value is required")
    models = [m for m in models if m.get("value") != value]
    models.append(model)
    provider["models"] = models
    return upsert_provider(provider)


def remove_model(provider_id: str, model_value: str) -> Dict[str, Any]:
    provider = get_provider(provider_id)
    if not provider:
        raise ValueError(f"Unknown provider: {provider_id}")
    provider = deepcopy(provider)
    models = [m for m in (provider.get("models") or []) if m.get("value") != model_value]
    provider["models"] = models
    return upsert_provider(provider)


def load_secrets() -> Dict[str, str]:
    with _lock:
        raw = _read_json(secrets_path(), {})
        if not isinstance(raw, dict):
            return {}
        # Also absorb env vars so existing .env keeps working
        secrets = {k: str(v) for k, v in raw.items() if v}
        for key in KNOWN_SECRET_KEYS:
            if key not in secrets or not secrets[key]:
                env_val = os.getenv(key)
                if env_val:
                    secrets[key] = env_val
        # Include any other provider key names from config
        for p in get_providers():
            kn = p.get("api_key_name")
            if kn and kn not in secrets:
                env_val = os.getenv(kn)
                if env_val:
                    secrets[kn] = env_val
        return secrets


def save_secrets(updates: Dict[str, Optional[str]], merge: bool = True) -> Dict[str, str]:
    """Save API keys. Empty string / null clears a key when merge=True."""
    with _lock:
        current = _read_json(secrets_path(), {})
        if not isinstance(current, dict):
            current = {}
        if not merge:
            current = {}
        for k, v in updates.items():
            if not k:
                continue
            if v is None or str(v).strip() == "":
                current.pop(k, None)
            else:
                current[k] = str(v).strip()
        _write_json(secrets_path(), current)
        return {k: v for k, v in current.items() if v}


def get_secret(name: str) -> Optional[str]:
    secrets = load_secrets()
    if name in secrets and secrets[name]:
        return secrets[name]
    return os.getenv(name)


def secrets_status() -> List[Dict[str, Any]]:
    """Public status for admin UI — never returns full keys.

    Includes every provider's api_key_name so newly added APIs appear
    on the Keys list immediately.
    """
    secrets = load_secrets()
    # key_name -> meta
    meta: Dict[str, Dict[str, Any]] = {}
    for key in KNOWN_SECRET_KEYS:
        meta[key] = {
            "name": key,
            "providers": [],
            "optional": key == "YOUTUBE_API_KEY",
            "required": key != "YOUTUBE_API_KEY",
        }
    for p in get_providers():
        kn = p.get("api_key_name")
        if not kn:
            continue
        if kn not in meta:
            meta[kn] = {
                "name": kn,
                "providers": [],
                "optional": bool(p.get("api_key_optional")) or p.get("type") == "tool",
                "required": not (bool(p.get("api_key_optional")) or p.get("type") == "tool"),
            }
        else:
            if p.get("api_key_optional") or p.get("type") == "tool":
                meta[kn]["optional"] = True
                meta[kn]["required"] = False
        meta[kn]["providers"].append({
            "id": p.get("id"),
            "label": p.get("label") or p.get("id"),
        })

    status = []
    for key in sorted(meta.keys()):
        val = secrets.get(key) or ""
        info = meta[key]
        status.append({
            "name": key,
            "configured": bool(val),
            "hint": (val[:4] + "…" + val[-4:]) if len(val) >= 12 else ("••••" if val else ""),
            "providers": info.get("providers") or [],
            "optional": bool(info.get("optional")),
            "required": bool(info.get("required", True)),
            "label": (
                ", ".join(pr["label"] for pr in info.get("providers") or [])
                or key
            ),
        })
    return status


def get_preferences() -> Dict[str, Any]:
    cfg = load_providers_config()
    defaults = {
        "theme": "light",
        "default_ai": "grok",
        "default_model": "grok-4.5",
        "tts_voice": "eve",
        "tts_language": "en",
    }
    prefs = cfg.get("preferences") or {}
    return {**defaults, **prefs}


def save_preferences(prefs: Dict[str, Any]) -> Dict[str, Any]:
    with _lock:
        cfg = load_providers_config()
        merged = {**(cfg.get("preferences") or {}), **prefs}
        cfg["preferences"] = merged
        save_providers_config(cfg)
        return merged


def public_catalog() -> Dict[str, Any]:
    """Safe payload for the chat UI (no secrets)."""
    cfg = load_providers_config()
    providers = []
    for p in cfg.get("providers") or []:
        if not p.get("enabled", True):
            continue
        providers.append({
            "id": p.get("id"),
            "label": p.get("label"),
            "type": p.get("type"),
            "badge_color": p.get("badge_color", "#555"),
            "supports_tools": p.get("supports_tools", False),
            "supports_image_gen": p.get("supports_image_gen", False),
            "models": p.get("models") or [],
        })
    return {
        "providers": providers,
        "preferences": get_preferences(),
        "secrets_status": secrets_status(),
    }

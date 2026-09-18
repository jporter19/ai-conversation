# app/services/model_roster.py
# Purpose: Curate a family picker roster from a provider's live model ids.
#          Deterministic — no LLM, no web search.

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

# Slot ids used on model.roster_slot and for grouping the chat picker.
SLOT_FLAGSHIP_CHAT = "flagship_chat"
SLOT_CHEAP_CHAT = "cheap_chat"
SLOT_CODING = "coding"
SLOT_FLAGSHIP_IMAGE = "flagship_image"
SLOT_CHEAP_IMAGE = "cheap_image"
SLOT_STT = "stt"
SLOT_TTS = "tts"
SLOT_VIDEO = "video"

SLOT_ORDER = (
    SLOT_FLAGSHIP_CHAT,
    SLOT_CHEAP_CHAT,
    SLOT_CODING,
    SLOT_FLAGSHIP_IMAGE,
    SLOT_CHEAP_IMAGE,
    SLOT_VIDEO,
    SLOT_STT,
    SLOT_TTS,
)

SLOT_ROLE = {
    SLOT_FLAGSHIP_CHAT: "Flagship",
    SLOT_CHEAP_CHAT: "Cheap",
    SLOT_CODING: "Coding",
    SLOT_FLAGSHIP_IMAGE: "Flagship image",
    SLOT_CHEAP_IMAGE: "Cheap image",
    SLOT_STT: "Speech to Text",
    SLOT_TTS: "Text to Speech",
    SLOT_VIDEO: "Video",
}

SLOT_CAPABILITY = {
    SLOT_FLAGSHIP_CHAT: "chat",
    SLOT_CHEAP_CHAT: "chat",
    SLOT_CODING: "chat",
    SLOT_FLAGSHIP_IMAGE: "image",
    SLOT_CHEAP_IMAGE: "image",
    SLOT_STT: "stt",
    SLOT_TTS: "tts",
    SLOT_VIDEO: "video",
}

SLOT_TAGS = {
    SLOT_FLAGSHIP_CHAT: ["flagship"],
    SLOT_CHEAP_CHAT: ["cheap", "fast"],
    SLOT_CODING: ["coding"],
    SLOT_FLAGSHIP_IMAGE: ["flagship", "images"],
    SLOT_CHEAP_IMAGE: ["cheap", "images"],
    SLOT_STT: ["stt", "specialized"],
    SLOT_TTS: ["tts", "specialized"],
    SLOT_VIDEO: ["video", "specialized"],
}

# Known ids that work even when /v1/models omits them (Grok STT/TTS endpoints).
FALLBACK_IDS = {
    "xai": {
        SLOT_FLAGSHIP_CHAT: "grok-4.6",
        SLOT_CHEAP_CHAT: "grok-4.1-fast-non-reasoning",
        SLOT_CODING: "grok-code-fast-1",
        SLOT_FLAGSHIP_IMAGE: "grok-imagine-image-quality",
        SLOT_CHEAP_IMAGE: "grok-imagine-image",
        SLOT_STT: "grok-stt",
        SLOT_TTS: "grok-tts",
        SLOT_VIDEO: "grok-imagine-video",
    },
    "openai": {
        SLOT_FLAGSHIP_CHAT: "gpt-4o",
        SLOT_CHEAP_CHAT: "gpt-4o-mini",
        SLOT_CODING: "gpt-4o",
        SLOT_FLAGSHIP_IMAGE: "gpt-image-1",
        SLOT_CHEAP_IMAGE: "dall-e-2",
        SLOT_STT: "whisper-1",
        SLOT_TTS: "tts-1",
        SLOT_VIDEO: "sora-2",
    },
}

# Friendly names for ids we always show.
SPECIAL_NAMES = {
    "grok-stt": "Grok STT",
    "grok-tts": "Grok TTS",
    "grok-imagine-image": "Grok Imagine",
    "grok-imagine-image-quality": "Grok Imagine Quality",
    "grok-imagine-video": "Grok Imagine Video",
    "grok-code-fast-1": "Grok Code Fast",
    "grok-build-0.1": "Grok Build",
    "whisper-1": "Whisper",
    "tts-1": "TTS-1",
    "tts-1-hd": "TTS-1 HD",
    "gpt-image-1": "GPT Image",
    "dall-e-2": "DALL-E 2",
    "dall-e-3": "DALL-E 3",
    "gpt-4o": "GPT-4o",
    "gpt-4o-mini": "GPT-4o Mini",
    "gpt-4o-transcribe": "GPT-4o Transcribe",
    "sora-2": "Sora",
    "sora": "Sora",
}

_CANONICAL_GROK = re.compile(r"^grok-(\d+)(?:\.(\d+))?$")
_CANONICAL_GPT = re.compile(r"^gpt-(\d+)(?:\.(\d+))?$")
_CANONICAL_GPT_O = re.compile(r"^gpt-(\d+)o$")  # gpt-4o
_ROLE_SUFFIX_RE = re.compile(r"\s*\([^)]*\)\s*$")


def _mid(model_id: str) -> str:
    return (model_id or "").strip().lower()


def canonical_version(model_id: str) -> Optional[Tuple[int, int, int]]:
    """
    Version for canonical flagship ids only.
    grok-4.6 → (4, 6, 0); gpt-4o → (4, 0, 1)  (the trailing 1 ranks 4o above gpt-4).
    Dated / specialty ids return None so they cannot beat a real flagship.
    """
    mid = _mid(model_id)
    m = _CANONICAL_GROK.match(mid)
    if m:
        return (int(m.group(1)), int(m.group(2) or 0), 0)
    m = _CANONICAL_GPT.match(mid)
    if m:
        return (int(m.group(1)), int(m.group(2) or 0), 0)
    m = _CANONICAL_GPT_O.match(mid)
    if m:
        return (int(m.group(1)), 0, 1)
    return None


def is_canonical_flagship_id(model_id: str) -> bool:
    return canonical_version(model_id) is not None


def _is_video_id(mid: str) -> bool:
    return "sora" in mid or "imagine-video" in mid or (
        "video" in mid and "imagine" in mid
    )


def _is_image_id(mid: str) -> bool:
    if _is_video_id(mid):
        return False
    if "vision" in mid:
        return False
    return any(
        tok in mid
        for tok in ("imagine-image", "dall-e", "gpt-image", "-image")
    ) or (mid.endswith("-image"))


def _is_stt_id(mid: str) -> bool:
    return any(tok in mid for tok in ("whisper", "-stt", "transcribe", "speech-to-text"))


def _is_tts_id(mid: str) -> bool:
    return mid.startswith("tts-") or mid.endswith("-tts") or "text-to-speech" in mid or mid in (
        "grok-tts",
        "tts-1",
        "tts-1-hd",
    )


def _is_coding_id(mid: str) -> bool:
    return any(tok in mid for tok in ("build", "code-fast", "codex", "composer"))


def _is_cheap_chat_id(mid: str) -> bool:
    if _is_image_id(mid) or _is_video_id(mid) or _is_stt_id(mid) or _is_tts_id(mid):
        return False
    if _is_coding_id(mid):
        return False
    return any(
        tok in mid
        for tok in ("mini", "nano", "lite", "fast", "instant", "turbo", "small")
    )


def _is_reasoning_id(mid: str) -> bool:
    return "reasoning" in mid and "non-reasoning" not in mid


def _is_specialty_chat(mid: str) -> bool:
    if _is_reasoning_id(mid) or "multi-agent" in mid:
        return True
    return any(tok in mid for tok in ("batch", "preview", "legacy"))


def classify_slot(model_id: str) -> Optional[str]:
    """Best single slot for this id, or None if it is an extra/older model."""
    mid = _mid(model_id)
    if not mid:
        return None
    if _is_video_id(mid):
        return SLOT_VIDEO
    if _is_stt_id(mid):
        return SLOT_STT
    if _is_tts_id(mid):
        return SLOT_TTS
    if _is_image_id(mid):
        if any(tok in mid for tok in ("quality", "hd", "pro", "dall-e-3", "gpt-image-1")):
            return SLOT_FLAGSHIP_IMAGE
        if any(tok in mid for tok in ("fast", "dall-e-2", "mini")):
            return SLOT_CHEAP_IMAGE
        # Bare imagine-image / gpt-image → cheap unless it is the quality variant
        if "quality" not in mid:
            return SLOT_CHEAP_IMAGE
        return SLOT_FLAGSHIP_IMAGE
    if _is_coding_id(mid):
        return SLOT_CODING
    if _is_cheap_chat_id(mid):
        return SLOT_CHEAP_CHAT
    if is_canonical_flagship_id(mid) and not _is_specialty_chat(mid):
        return SLOT_FLAGSHIP_CHAT
    return None


def friendly_name(model_id: str) -> str:
    mid = (model_id or "").strip()
    key = mid.lower()
    if key in SPECIAL_NAMES:
        return SPECIAL_NAMES[key]
    if key.startswith("grok-build"):
        return "Grok Build"
    if "code-fast" in key:
        return "Grok Code Fast"
    if key.startswith("sora"):
        return "Sora"
    if _CANONICAL_GROK.match(key):
        rest = mid.split("-", 1)[1]
        return f"Grok {rest}"
    if _CANONICAL_GPT.match(key) or _CANONICAL_GPT_O.match(key):
        rest = mid[4:]  # strip gpt-
        if rest.endswith("o") and rest[:-1].replace(".", "").isdigit():
            return f"GPT-{rest}"
        return f"GPT-{rest}"
    parts = []
    for p in re.split(r"[-_]", mid):
        if not p:
            continue
        low = p.lower()
        if low in ("stt", "tts", "hd", "gpt"):
            parts.append(low.upper() if low != "gpt" else "GPT")
        elif re.fullmatch(r"\d+(?:\.\d+)?", p):
            parts.append(p)
        else:
            parts.append(p[:1].upper() + p[1:])
    name = " ".join(parts)
    name = re.sub(r"^Gpt ", "GPT-", name)
    return name or mid


def apply_role_label(model_id: str, role: str, existing_label: str = "") -> str:
    base = _ROLE_SUFFIX_RE.sub("", (existing_label or "").strip())
    if not base or _looks_like_raw_id_label(base, model_id):
        base = friendly_name(model_id)
    role = (role or "").strip()
    if not role:
        return base
    return f"{base} ({role})"


def _looks_like_raw_id_label(label: str, model_id: str) -> bool:
    compact = re.sub(r"[\s._-]+", "", label).lower()
    mid = re.sub(r"[\s._-]+", "", model_id or "").lower()
    return compact == mid


def _slot_rank(model_id: str, slot: str) -> Tuple:
    """Higher is better within a slot."""
    mid = _mid(model_id)
    ver = canonical_version(mid) or (0, 0, 0)
    if slot == SLOT_FLAGSHIP_CHAT:
        return (1 if is_canonical_flagship_id(mid) else 0, ver)
    if slot == SLOT_CHEAP_CHAT:
        non_reason = 0 if _is_reasoning_id(mid) else 1
        return (non_reason, ver, len(mid))
    if slot == SLOT_CODING:
        # Prefer dedicated code-fast / codex over generic build
        dedicated = 2 if ("code-fast" in mid or "codex" in mid) else 1
        return (dedicated, ver)
    if slot == SLOT_FLAGSHIP_IMAGE:
        quality = 1 if any(t in mid for t in ("quality", "hd", "dall-e-3", "gpt-image-1")) else 0
        return (quality, ver)
    if slot == SLOT_CHEAP_IMAGE:
        cheap = 1 if any(t in mid for t in ("fast", "dall-e-2", "mini")) else 0
        return (cheap, ver)
    if slot == SLOT_TTS:
        hd = 1 if "hd" in mid else 0
        return (hd, ver)
    if slot == SLOT_STT:
        # Prefer dedicated grok-stt / whisper-1 over dated transcribe snapshots
        stable = 1 if mid in ("grok-stt", "whisper-1") else 0
        return (stable, ver)
    if slot == SLOT_VIDEO:
        return (ver, len(mid))
    return (ver,)


def _decorate(row: Dict[str, Any], slot: str) -> Dict[str, Any]:
    out = dict(row)
    mid = str(out.get("value") or "")
    cap = SLOT_CAPABILITY[slot]
    role = SLOT_ROLE[slot]
    out["capability"] = cap
    out["roster_slot"] = slot
    out["tags"] = list(SLOT_TAGS[slot])
    out["recommendation"] = "keep"
    out["recommendation_reason"] = f"Required {role} model"
    out["recommendation_source"] = "roster"
    out["label"] = apply_role_label(mid, role, str(out.get("label") or ""))
    if not (out.get("tooltip") or out.get("description")):
        out["tooltip"] = out["label"]
    return out


def _decorate_extra(row: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(row)
    mid = str(out.get("value") or "")
    if not out.get("label") or _looks_like_raw_id_label(str(out.get("label") or ""), mid):
        out["label"] = friendly_name(mid)
    out["recommendation"] = out.get("recommendation") or "review"
    out["recommendation_reason"] = out.get("recommendation_reason") or "Older / extra model"
    out.pop("roster_slot", None)
    if not out.get("tags"):
        out["tags"] = []
    return out


def apply_roster(
    remote: List[Dict[str, Any]],
    previous: Optional[List[Dict[str, Any]]] = None,
    *,
    source: str = "",
) -> List[Dict[str, Any]]:
    """
    Build a catalog list: one winner per required slot, then extras.

    remote: models fetched from the vendor (value/label/capability/tooltip).
    previous: last saved catalog (manual STT/TTS, descriptions).
    source: openai | xai — selects fallback ids.
    """
    prev_list = list(previous or [])
    prev_by_id = {str(m.get("value")): dict(m) for m in prev_list if m.get("value")}
    remote_by_id: Dict[str, Dict[str, Any]] = {}
    for m in remote or []:
        vid = str(m.get("value") or "").strip()
        if not vid:
            continue
        remote_by_id[vid] = dict(m)

    # Candidate pools per slot (remote first, then previous).
    pools: Dict[str, List[str]] = {s: [] for s in SLOT_ORDER}
    for vid in list(remote_by_id.keys()) + [v for v in prev_by_id if v not in remote_by_id]:
        slot = classify_slot(vid)
        if slot:
            pools[slot].append(vid)

    winners: Dict[str, str] = {}
    used: set[str] = set()
    for slot in SLOT_ORDER:
        candidates = [v for v in pools.get(slot) or [] if v not in used]
        if slot == SLOT_FLAGSHIP_CHAT:
            canon = [v for v in candidates if is_canonical_flagship_id(v)]
            if canon:
                candidates = canon
        if candidates:
            best = max(candidates, key=lambda v: _slot_rank(v, slot))
            winners[slot] = best
            used.add(best)
            continue
        fb = (FALLBACK_IDS.get(source) or {}).get(slot)
        if not fb or fb in used:
            continue
        # Voice endpoints are often missing from /v1/models; other fallbacks
        # only apply when that id was already in the saved catalog.
        is_voice = slot in (SLOT_STT, SLOT_TTS)
        if is_voice or fb in prev_by_id:
            winners[slot] = fb
            used.add(fb)

    # openai fallback uses gpt-4o for coding and flagship — keep flagship only.
    if winners.get(SLOT_CODING) and winners.get(SLOT_CODING) == winners.get(SLOT_FLAGSHIP_CHAT):
        winners.pop(SLOT_CODING, None)

    out: List[Dict[str, Any]] = []
    slotted_ids: set[str] = set()
    for slot in SLOT_ORDER:
        vid = winners.get(slot)
        if not vid:
            continue
        base = remote_by_id.get(vid) or prev_by_id.get(vid) or {"value": vid}
        # Preserve researched blurbs / manual flag from previous
        old = prev_by_id.get(vid) or {}
        if old.get("description_source") == "web_search" and old.get("tooltip"):
            base["tooltip"] = old.get("tooltip")
            base["description"] = old.get("description") or old.get("tooltip")
            base["description_source"] = old.get("description_source")
            if old.get("description_updated_at"):
                base["description_updated_at"] = old["description_updated_at"]
        if old.get("manual"):
            base["manual"] = True
        if slot in (SLOT_STT, SLOT_TTS) and vid in ("grok-stt", "grok-tts"):
            base["manual"] = True
        out.append(_decorate(base, slot))
        slotted_ids.add(vid)

    extra_ids: List[str] = []
    for vid, row in remote_by_id.items():
        if vid not in slotted_ids:
            extra_ids.append(vid)
    for old in prev_list:
        vid = str(old.get("value") or "")
        if not vid or vid in slotted_ids or vid in remote_by_id:
            continue
        if old.get("manual"):
            extra_ids.append(vid)

    seen_extra = set()
    for vid in extra_ids:
        if vid in seen_extra:
            continue
        seen_extra.add(vid)
        base = remote_by_id.get(vid) or prev_by_id.get(vid) or {"value": vid}
        old = prev_by_id.get(vid) or {}
        if old.get("manual"):
            base["manual"] = True
        if old.get("description_source") == "web_search" and old.get("tooltip"):
            base["tooltip"] = old.get("tooltip")
            base["description"] = old.get("description") or old.get("tooltip")
            base["description_source"] = old.get("description_source")
        # Keep previous capability for extras when remote omitted it
        if not base.get("capability") and old.get("capability"):
            base["capability"] = old["capability"]
        out.append(_decorate_extra(base))

    return out


def roster_summary(models: Iterable[Dict[str, Any]]) -> Dict[str, Optional[str]]:
    found: Dict[str, Optional[str]] = {s: None for s in SLOT_ORDER}
    for m in models or []:
        slot = m.get("roster_slot")
        if slot in found and m.get("value"):
            found[slot] = str(m.get("value"))
    return found


def preserve_roster_rows(models: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep slot labels/tags/keep after a later AI-recommend pass."""
    out = []
    for m in models or []:
        row = dict(m)
        slot = row.get("roster_slot")
        if slot in SLOT_ROLE:
            row = _decorate(row, slot)
        out.append(row)
    return out


def pick_flagship_chat_id(models: List[Dict[str, Any]]) -> Optional[str]:
    for m in models or []:
        if m.get("roster_slot") == SLOT_FLAGSHIP_CHAT and m.get("value"):
            return str(m["value"])
    for m in models or []:
        tags = m.get("tags") or []
        if "flagship" in tags and (m.get("capability") or "chat") == "chat" and m.get("value"):
            return str(m["value"])
    chat = [
        m for m in (models or [])
        if (m.get("capability") or "chat") == "chat" and m.get("value")
        and is_canonical_flagship_id(str(m.get("value")))
    ]
    if chat:
        return max(chat, key=lambda m: canonical_version(str(m.get("value"))) or (0, 0, 0)).get("value")
    return None

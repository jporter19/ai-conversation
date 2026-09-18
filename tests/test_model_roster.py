# tests/test_model_roster.py
from app.services.model_catalog import _filter_openai_models
from app.services.model_roster import (
    SLOT_CHEAP_CHAT,
    SLOT_CHEAP_IMAGE,
    SLOT_CODING,
    SLOT_FLAGSHIP_CHAT,
    SLOT_FLAGSHIP_IMAGE,
    SLOT_STT,
    SLOT_TTS,
    SLOT_VIDEO,
    apply_roster,
    apply_role_label,
    canonical_version,
    classify_slot,
    friendly_name,
    is_canonical_flagship_id,
    roster_summary,
)
from app.services.handlers.chat_handler import ChatHandler


def test_canonical_flagship_beats_dated_snapshot():
    assert is_canonical_flagship_id("grok-4.6")
    assert not is_canonical_flagship_id("grok-4.20-0309-reasoning")
    assert canonical_version("grok-4.6") > canonical_version("grok-4.5")
    assert canonical_version("gpt-5") > canonical_version("gpt-4o")


def test_classify_slots():
    assert classify_slot("grok-4.6") == SLOT_FLAGSHIP_CHAT
    assert classify_slot("grok-4.1-fast-non-reasoning") == SLOT_CHEAP_CHAT
    assert classify_slot("grok-code-fast-1") == SLOT_CODING
    assert classify_slot("grok-imagine-image-quality") == SLOT_FLAGSHIP_IMAGE
    assert classify_slot("grok-imagine-image") == SLOT_CHEAP_IMAGE
    assert classify_slot("grok-stt") == SLOT_STT
    assert classify_slot("grok-tts") == SLOT_TTS
    assert classify_slot("grok-imagine-video") == SLOT_VIDEO
    assert classify_slot("whisper-1") == SLOT_STT
    assert classify_slot("tts-1") == SLOT_TTS
    assert classify_slot("sora-2") == SLOT_VIDEO
    assert classify_slot("gpt-4o-mini") == SLOT_CHEAP_CHAT
    assert classify_slot("grok-4.20-0309-reasoning") is None


def test_labels():
    assert apply_role_label("grok-4.6", "Flagship") == "Grok 4.6 (Flagship)"
    assert apply_role_label("grok-tts", "Text to Speech") == "Grok TTS (Text to Speech)"
    assert friendly_name("gpt-4o-mini") == "GPT-4o Mini"


def test_apply_roster_fills_required_slots():
    remote = [
        {"value": "grok-4.6", "capability": "chat"},
        {"value": "grok-4.20-0309-reasoning", "capability": "chat"},
        {"value": "grok-4.5", "capability": "chat"},
        {"value": "grok-4.1-fast-non-reasoning", "capability": "chat"},
        {"value": "grok-code-fast-1", "capability": "chat"},
        {"value": "grok-imagine-image-quality", "capability": "image"},
        {"value": "grok-imagine-image", "capability": "image"},
        {"value": "grok-imagine-video", "capability": "video"},
    ]
    previous = [
        {"value": "grok-stt", "capability": "stt", "manual": True, "label": "Grok Speech-to-Text"},
        {"value": "grok-tts", "capability": "tts", "manual": True},
    ]
    out = apply_roster(remote, previous, source="xai")
    summary = roster_summary(out)
    assert summary[SLOT_FLAGSHIP_CHAT] == "grok-4.6"
    assert summary[SLOT_CHEAP_CHAT] == "grok-4.1-fast-non-reasoning"
    assert summary[SLOT_CODING] == "grok-code-fast-1"
    assert summary[SLOT_FLAGSHIP_IMAGE] == "grok-imagine-image-quality"
    assert summary[SLOT_CHEAP_IMAGE] == "grok-imagine-image"
    assert summary[SLOT_VIDEO] == "grok-imagine-video"
    assert summary[SLOT_STT] == "grok-stt"
    assert summary[SLOT_TTS] == "grok-tts"

    by_id = {m["value"]: m for m in out}
    assert by_id["grok-4.6"]["label"] == "Grok 4.6 (Flagship)"
    assert by_id["grok-tts"]["label"] == "Grok TTS (Text to Speech)"
    assert by_id["grok-stt"]["manual"] is True
    assert "grok-4.20-0309-reasoning" in by_id
    assert by_id["grok-4.20-0309-reasoning"].get("roster_slot") is None


def test_empty_remote_does_not_apply_here():
    # provider_sync keeps previous; roster with empty remote still keeps voice fallbacks
    previous = [
        {"value": "grok-4.6", "capability": "chat", "roster_slot": "flagship_chat"},
        {"value": "grok-stt", "capability": "stt", "manual": True},
    ]
    out = apply_roster([], previous, source="xai")
    summary = roster_summary(out)
    assert summary[SLOT_FLAGSHIP_CHAT] == "grok-4.6"
    assert summary[SLOT_STT] == "grok-stt"


def test_openai_filter_keeps_voice_and_video():
    ids = [
        "gpt-4o",
        "gpt-4o-mini",
        "whisper-1",
        "tts-1",
        "sora-2",
        "text-embedding-3-large",
        "omni-moderation-latest",
    ]
    kept = _filter_openai_models(ids)
    assert "whisper-1" in kept
    assert "tts-1" in kept
    assert "sora-2" in kept
    assert "gpt-4o" in kept
    assert "text-embedding-3-large" not in kept


def test_sync_all_auto_update_skips_describe(monkeypatch):
    import asyncio

    from app.services import provider_sync, settings_store

    captured = {}

    async def fake_sync(pid, **kwargs):
        captured[pid] = kwargs
        return {"provider": {"id": pid, "models": []}, "message": "ok", "steps": {}}

    monkeypatch.setattr(
        settings_store,
        "get_providers",
        lambda: [{"id": "grok", "auto_update": True}, {"id": "youtube", "auto_update": False}],
    )
    monkeypatch.setattr(provider_sync, "sync_provider", fake_sync)

    asyncio.run(
        provider_sync.sync_all_auto_providers(describe=False, recommend=False)
    )
    assert "grok" in captured
    assert captured["grok"]["describe"] is False
    assert captured["grok"]["recommend"] is False
    assert captured["grok"]["fetch_remote"] is True


def test_tools_skipped_for_reasoning_not_flagship():
    assert ChatHandler._model_allows_tools("grok-4.6") is True
    assert ChatHandler._model_allows_tools("grok-4.1-fast-non-reasoning") is True
    assert ChatHandler._model_allows_tools("grok-4.20-0309-reasoning") is False
    assert ChatHandler._model_allows_tools("grok-4.20-multi-agent-0309") is False
    assert ChatHandler._model_allows_tools("o3-mini") is False


def test_tools_skipped_for_gpt6_astra_and_gpt54_plus():
    assert ChatHandler._model_allows_tools("gpt-6-astra") is False
    assert ChatHandler._model_allows_tools("gpt-6-astra-2026-09-01") is False
    assert ChatHandler._model_allows_tools("gpt-5.6") is False
    assert ChatHandler._model_allows_tools("gpt-5.4") is False
    assert ChatHandler._model_allows_tools("gpt-4o") is True
    assert ChatHandler._model_allows_tools("gpt-5") is True
    assert ChatHandler._model_allows_tools("gpt-5.1") is True


def test_chat_completions_rejects_tools_detects_astra_400():
    err = Exception(
        "Error code: 400 - {'error': {'message': "
        "\"Function tools with reasoning_effort are not supported for gpt-6-astra "
        "in /v1/chat/completions. To use function tools, use /v1/responses or set "
        "reasoning_effort to 'none'.\"}}"
    )
    assert ChatHandler._chat_completions_rejects_tools(err) is True
    assert ChatHandler._chat_completions_rejects_tools(Exception("rate limit")) is False


def test_retries_without_tools_after_astra_style_400():
    import asyncio

    from app.services.handlers.types import RequestContext

    calls = []

    class FakeCompletions:
        async def create(self, **kwargs):
            calls.append(kwargs)
            if kwargs.get("tools"):
                raise Exception(
                    "Function tools with reasoning_effort are not supported for "
                    "gpt-6-astra in /v1/chat/completions"
                )

            class Chunk:
                class Choice:
                    class Delta:
                        content = "Hello from Astra"
                        tool_calls = None
                    delta = Delta()
                    choices = None
                choices = [Choice()]

            class Stream:
                def __init__(self):
                    self._sent = False

                def __aiter__(self):
                    return self

                async def __anext__(self):
                    if self._sent:
                        raise StopAsyncIteration
                    self._sent = True
                    return Chunk()

            return Stream()

    class FakeClient:
        def __init__(self):
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    handler = ChatHandler()
    handler._client = lambda _provider: FakeClient()  # type: ignore[method-assign]
    ctx = RequestContext(
        ai="chatgpt",
        model="gpt-4o",
        messages=[{"role": "user", "content": "hi"}],
        provider={
            "supports_tools": True,
            "api_key_name": "OPENAI_API_KEY",
            "base_url": "https://api.openai.com/v1",
        },
    )

    async def collect() -> str:
        bits = []
        async for part in handler._stream_turn(ctx):
            bits.append(part)
        return "".join(bits)

    text = asyncio.run(collect())
    assert "Hello from Astra" in text
    assert len(calls) == 2
    assert "tools" in calls[0]
    assert "tools" not in calls[1]

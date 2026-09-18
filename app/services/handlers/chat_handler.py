# LLM chat completions (+ optional web_search tool loop).

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, AsyncIterator, Dict, List

import httpx
from openai import AsyncOpenAI

from app.config import resolve_api_key
from app.services.handlers.types import RequestContext
from app.services.tools import WEB_SEARCH_TOOL, execute_web_search_async

logger = logging.getLogger(__name__)

# Bound upstream waits so Cloudflare/nginx idle limits don't silently kill the stream.
LLM_TIMEOUT = httpx.Timeout(180.0, connect=20.0, read=120.0, write=30.0)
SEARCH_TIMEOUT_SEC = 18.0
# Soft ceiling for an entire chat turn (tool loop included).
TURN_TIMEOUT_SEC = 240.0

_TOOL_SYSTEM = (
    "You have a web_search tool for current prices, news, weather, stocks, "
    "or events after January 2025. "
    "Use it when live data is needed; otherwise answer directly. "
    "If you search, keep any preamble short — do not stop after saying you will check."
)


class ChatHandler:
    name = "chat"

    async def stream(self, ctx: RequestContext) -> AsyncIterator[str]:
        try:
            async for chunk in self._stream_turn(ctx):
                yield chunk
        except asyncio.TimeoutError:
            yield (
                "\n\n[Error: This reply timed out while waiting on the model or web search. "
                "Try again, or rephrase without needing live web data.]"
            )
        except Exception as e:
            logger.exception("chat stream failed")
            yield f"\n\n[Error: {e}]"

    async def _stream_turn(self, ctx: RequestContext) -> AsyncIterator[str]:
        provider = ctx.provider
        model = ctx.model

        supports_tools = bool(provider.get("supports_tools")) and self._model_allows_tools(model)
        messages = self._messages_for_turn(ctx, with_tools=supports_tools)
        client = self._client(provider)

        create_kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
        }
        if supports_tools:
            create_kwargs["tools"] = [WEB_SEARCH_TOOL]
            create_kwargs["tool_choice"] = "auto"

        # First model pass (may stream text and/or tool calls)
        try:
            response = await asyncio.wait_for(
                client.chat.completions.create(**create_kwargs),
                timeout=TURN_TIMEOUT_SEC,
            )
        except asyncio.TimeoutError:
            raise
        except Exception as e:
            if not (supports_tools and self._chat_completions_rejects_tools(e)):
                raise
            logger.info(
                "Retrying %s without function tools (Chat Completions rejected tools+reasoning)",
                model,
            )
            supports_tools = False
            messages = self._messages_for_turn(ctx, with_tools=False)
            create_kwargs = {
                "model": model,
                "messages": messages,
                "stream": True,
            }
            response = await asyncio.wait_for(
                client.chat.completions.create(**create_kwargs),
                timeout=TURN_TIMEOUT_SEC,
            )
        tool_calls_acc: Dict[int, Dict[str, Any]] = {}
        saw_text = False

        async for chunk in response:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if not delta:
                continue
            if delta.content:
                saw_text = True
                yield delta.content
            if supports_tools and delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    self._accumulate_tool_call(tool_calls_acc, tc_delta)

        if not tool_calls_acc:
            if not saw_text:
                yield (
                    "\n\n_[No response text from the model. "
                    "Try again or pick a different model.]_"
                )
            return

        # Tool path — keep the stream alive (Cloudflare ~100s idle can drop silent streams)
        if not saw_text:
            yield "Looking that up…\n\n"
        else:
            yield "\n\n"

        ordered = [tool_calls_acc[i] for i in sorted(tool_calls_acc.keys())]
        messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": ordered,
        })

        for call in ordered:
            name = call["function"]["name"]
            call_id = call["id"] or f"call_{name}"
            raw_args = call["function"]["arguments"] or "{}"
            if name != "web_search":
                tool_content = f"Unsupported tool: {name}"
            else:
                try:
                    args = json.loads(raw_args) if raw_args.strip() else {}
                    query = (args.get("query") or "").strip()
                    if not query:
                        tool_content = "web_search error: missing query"
                    else:
                        yield f"_Searching: {query}_\n\n"
                        tool_content = await execute_web_search_async(
                            query,
                            timeout=SEARCH_TIMEOUT_SEC,
                        )
                except json.JSONDecodeError as e:
                    tool_content = f"web_search error: invalid arguments JSON ({e})"
                except Exception as e:
                    tool_content = f"web_search error: {e}"

            messages.append({
                "role": "tool",
                "tool_call_id": call_id,
                "content": tool_content,
            })

        yield "_Compiling answer…_\n\n"

        try:
            second = await asyncio.wait_for(
                client.chat.completions.create(
                    model=model,
                    messages=messages,
                    stream=True,
                ),
                timeout=TURN_TIMEOUT_SEC,
            )
        except Exception as e:
            yield (
                f"[Error: model did not continue after search ({e}). "
                "Search results were obtained; try asking again.]"
            )
            return

        second_text = False
        async for chunk in second:
            if not chunk.choices:
                continue
            content = chunk.choices[0].delta.content if chunk.choices[0].delta else None
            if content:
                second_text = True
                yield content

        if not second_text:
            yield (
                "_[The model returned no final answer after searching. "
                "Try rephrasing the question.]_"
            )

    @staticmethod
    def _messages_for_turn(ctx: RequestContext, *, with_tools: bool) -> List[Dict[str, Any]]:
        messages: List[Dict[str, Any]] = list(ctx.messages)
        parts: List[str] = []
        if ctx.system_prompt:
            parts.append(ctx.system_prompt.strip())
        if with_tools:
            parts.append(_TOOL_SYSTEM)
        if not parts:
            return messages
        return [{"role": "system", "content": "\n\n".join(parts)}, *messages]

    @staticmethod
    def _chat_completions_rejects_tools(err: BaseException) -> bool:
        text = str(err).lower()
        if "function tools" not in text:
            return False
        return any(
            tok in text
            for tok in ("reasoning_effort", "/v1/responses", "v1/responses", "chat/completions")
        )

    @staticmethod
    def _model_allows_tools(model: str) -> bool:
        """False when Chat Completions cannot take function tools for this id."""
        mid = (model or "").lower()
        if "multi-agent" in mid or "deepthink" in mid:
            return False
        if "reasoning" in mid and "non-reasoning" not in mid:
            return False
        if re.search(r"(^|-)o[1-4]($|-)", mid):
            return False
        # GPT-6 Astra (and snapshots): tools require /v1/responses; effort cannot be "none".
        if "astra" in mid or mid.startswith("gpt-6"):
            return False
        # GPT-5.4+ same Chat Completions restriction unless reasoning_effort is none.
        m = re.match(r"^gpt-5\.(\d+)", mid)
        if m and int(m.group(1)) >= 4:
            return False
        return True

    def _client(self, provider: Dict[str, Any]) -> AsyncOpenAI:
        key_name = provider.get("api_key_name")
        api_key = resolve_api_key(key_name) if key_name else None
        if not api_key:
            raise RuntimeError(
                f"API key {key_name or '(missing)'} not configured. Open Admin Tools to paste it."
            )
        base_url = provider.get("base_url") or "https://api.openai.com/v1"
        return AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=LLM_TIMEOUT,
            max_retries=1,
        )

    @staticmethod
    def _accumulate_tool_call(acc: Dict[int, Dict[str, Any]], tool_call_delta: Any) -> None:
        idx = tool_call_delta.index if tool_call_delta.index is not None else 0
        if idx not in acc:
            acc[idx] = {
                "id": "",
                "type": "function",
                "function": {"name": "", "arguments": ""},
            }
        entry = acc[idx]
        if tool_call_delta.id:
            entry["id"] = tool_call_delta.id
        if tool_call_delta.type:
            entry["type"] = tool_call_delta.type
        fn = tool_call_delta.function
        if fn is None:
            return
        if fn.name:
            entry["function"]["name"] = fn.name
        if fn.arguments:
            entry["function"]["arguments"] += fn.arguments

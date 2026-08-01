# LLM chat completions (+ optional web_search tool loop).

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, AsyncIterator, Dict, List

from openai import AsyncOpenAI

from app.services.tools import WEB_SEARCH_TOOL, execute_web_search
from app.config import resolve_api_key
from app.services.handlers.types import RequestContext


class ChatHandler:
    name = "chat"

    async def stream(self, ctx: RequestContext) -> AsyncIterator[str]:
        provider = ctx.provider
        messages: List[Dict[str, Any]] = list(ctx.messages)

        supports_tools = bool(provider.get("supports_tools"))
        if supports_tools:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You MUST use the web_search tool for ANY question about current prices, news, "
                        "events, weather, stocks, or data after January 2025. "
                        "Never guess or use old knowledge. Always search first and base response on results."
                    ),
                },
                *messages,
            ]

        client = self._client(provider)
        model = ctx.model
        user_query = ctx.last_user_text().lower()
        tool_choice = self._tool_choice(user_query) if supports_tools else None

        try:
            create_kwargs: Dict[str, Any] = {
                "model": model,
                "messages": messages,
                "stream": True,
            }
            if supports_tools:
                create_kwargs["tools"] = [WEB_SEARCH_TOOL]
                create_kwargs["tool_choice"] = tool_choice

            response = await client.chat.completions.create(**create_kwargs)
            tool_calls_acc: Dict[int, Dict[str, Any]] = {}

            async for chunk in response:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if not delta:
                    continue
                if delta.content:
                    yield delta.content
                if supports_tools and delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        self._accumulate_tool_call(tool_calls_acc, tc_delta)

            if not tool_calls_acc:
                return

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
                        args = json.loads(raw_args)
                        query = args.get("query", "")
                        if not query:
                            tool_content = "web_search error: missing query"
                        else:
                            tool_content = await asyncio.to_thread(execute_web_search, query)
                    except json.JSONDecodeError as e:
                        tool_content = f"web_search error: invalid arguments JSON ({e})"
                    except Exception as e:
                        tool_content = f"web_search error: {e}"

                messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": tool_content,
                })

            second = await client.chat.completions.create(
                model=model,
                messages=messages,
                stream=True,
            )
            async for chunk in second:
                if not chunk.choices:
                    continue
                content = chunk.choices[0].delta.content if chunk.choices[0].delta else None
                if content:
                    yield content
        except Exception as e:
            yield f"\n\n[Error: {e}]"

    def _client(self, provider: Dict[str, Any]) -> AsyncOpenAI:
        key_name = provider.get("api_key_name")
        api_key = resolve_api_key(key_name) if key_name else None
        if not api_key:
            raise RuntimeError(
                f"API key {key_name or '(missing)'} not configured. Open Admin Tools to paste it."
            )
        base_url = provider.get("base_url") or "https://api.openai.com/v1"
        return AsyncOpenAI(api_key=api_key, base_url=base_url)

    @staticmethod
    def _tool_choice(user_query: str) -> Any:
        needs = bool(
            re.search(
                r"\b(current|today|latest|price|news|weather|stock|score|event|live)\b",
                user_query,
            )
        )
        if needs:
            return {"type": "function", "function": {"name": "web_search"}}
        return "auto"

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

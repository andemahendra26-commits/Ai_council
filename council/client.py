"""Thin async wrapper over the NVIDIA OpenAI-compatible endpoint."""

from __future__ import annotations

import os
from typing import Any, AsyncIterator

from openai import APIStatusError, AsyncOpenAI

from .config import DEFAULT_BASE_URL, Seat

# Per-request timeout — skip any model that can't respond in 30s.
REQUEST_TIMEOUT = 30.0


class MissingAPIKey(RuntimeError):
    pass


def make_client(base_url: str | None = None) -> AsyncOpenAI:
    key = os.environ.get("NVIDIA_API_KEY")
    if not key:
        raise MissingAPIKey(
            "NVIDIA_API_KEY is not set. Copy .env.example to .env and put your "
            "key in it (get one at https://build.nvidia.com)."
        )
    return AsyncOpenAI(
        base_url=base_url or os.environ.get("NVIDIA_BASE_URL", DEFAULT_BASE_URL),
        api_key=key,
        timeout=REQUEST_TIMEOUT,
        max_retries=2,
    )


def build_messages(seat: Seat, system: str, user: str) -> list[dict[str, str]]:
    """Assemble messages, honouring the seat's `detailed thinking on` prefix."""
    messages: list[dict[str, str]] = []
    if seat.system_prefix:
        messages.append({"role": "system", "content": seat.system_prefix})
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user})
    return messages


async def stream_chat(
    client: AsyncOpenAI,
    seat: Seat,
    messages: list[dict[str, str]],
) -> AsyncIterator[tuple[str, str]]:
    """Yield ("reasoning" | "content" | "finish", text) deltas for one seat's turn.

    Reasoning models on NIM emit their chain of thought on `reasoning_content`
    and the answer on `content`; models without thinking only ever emit the
    latter. Two endpoint quirks are handled here:

    * a seat flagged for thinking whose model rejects the knobs is retried once
      plain, so it degrades instead of dropping out of the session;
    * when a thinking response is cut off by max_tokens, NIM mirrors the chain of
      thought into `content` as well — that mirrored text is chain of thought,
      not an answer, so it is dropped and the turn reported as truncated.
    """
    kwargs: dict[str, Any] = {
        "model": seat.model,
        "messages": messages,
        "temperature": seat.temperature,
        "top_p": seat.top_p,
        "max_tokens": seat.max_tokens,
        "stream": True,
    }
    extra = seat.extra_body()
    if extra:
        kwargs["extra_body"] = extra

    try:
        stream = await client.chat.completions.create(**kwargs)
    except APIStatusError as exc:
        if not extra or exc.status_code not in (400, 422):
            raise
        kwargs.pop("extra_body", None)
        stream = await client.chat.completions.create(**kwargs)

    async for chunk in stream:
        if not chunk.choices:
            continue
        choice = chunk.choices[0]
        delta = choice.delta
        if delta is not None:
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                yield "reasoning", reasoning
            if delta.content and delta.content != reasoning:
                yield "content", delta.content
        if choice.finish_reason:
            yield "finish", choice.finish_reason


async def list_models(client: AsyncOpenAI) -> list[str]:
    """Model IDs this API key can actually reach, chat-capable ones first."""
    page = await client.models.list()
    ids = sorted(m.id for m in page.data)
    return ids

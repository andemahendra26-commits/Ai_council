"""Run the council under a chosen coordination pattern, streaming events out.

`deliberate()` is an async generator of plain-dict events. The server turns them
into NDJSON for the browser; anything else can consume them directly.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncIterator

from openai import AsyncOpenAI

from .config import Seat
from .patterns import DEFAULT_PATTERN, PATTERNS
from .runtime import Ctx, Event, label_for

# A whole session's ceiling. The per-request timeout in client.py is httpx's
# read timeout, so it only fires when a stream goes quiet - a slow-but-alive
# roster can otherwise run unbounded. Override with options["session_timeout"].
DEFAULT_SESSION_TIMEOUT = 900.0


async def _orchestrate(ctx: Ctx, pattern_id: str) -> None:
    pattern = PATTERNS.get(pattern_id) or PATTERNS[DEFAULT_PATTERN]
    started = time.perf_counter()

    await ctx.emit(
        {
            "type": "run_start",
            "question": ctx.question,
            "pattern": pattern.to_dict(),
            "seats": [{**s.to_dict(), "label": ctx.label(s)} for s in ctx.seats],
            "chair": {**ctx.chair.to_dict(), "label": "Leader", "rank": "leader"},
        }
    )

    verdict = await pattern.run(ctx)

    usage = ctx.usage_report()
    await ctx.emit(
        {
            "type": "run_end",
            "elapsed": round(time.perf_counter() - started, 2),
            "usage": usage,
            "transcript": {
                "question": ctx.question,
                "pattern": pattern.to_dict(),
                "seats": [{**s.to_dict(), "label": ctx.label(s)} for s in ctx.seats],
                "chair": {**ctx.chair.to_dict(), "label": "Leader", "rank": "leader"},
                "log": ctx.log,
                "verdict": verdict,
                "usage": usage,
                "elapsed": round(time.perf_counter() - started, 2),
            },
        }
    )


async def deliberate(
    client: AsyncOpenAI,
    question: str,
    seats: list[Seat],
    chair: Seat,
    pattern_id: str = DEFAULT_PATTERN,
    options: dict[str, Any] | None = None,
) -> AsyncIterator[Event]:
    """Run the council, yielding events as they happen."""
    queue: asyncio.Queue[Event | None] = asyncio.Queue()
    ctx = Ctx(client, question, seats, chair, queue, options)

    timeout = float((options or {}).get("session_timeout") or DEFAULT_SESSION_TIMEOUT)

    async def runner() -> None:
        try:
            await asyncio.wait_for(_orchestrate(ctx, pattern_id), timeout=timeout)
        except asyncio.TimeoutError:
            await queue.put(
                {
                    "type": "fatal",
                    "message": (
                        f"Session exceeded its {timeout:.0f}s budget and was stopped. "
                        "Seat a smaller roster, pick a cheaper protocol, or raise "
                        "options.session_timeout."
                    ),
                }
            )
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            await queue.put({"type": "fatal", "message": f"{type(exc).__name__}: {exc}"})
        finally:
            await queue.put(None)

    task = asyncio.create_task(runner())
    try:
        while True:
            event = await queue.get()
            if event is None:
                break
            yield event
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


__all__ = ["deliberate", "label_for"]

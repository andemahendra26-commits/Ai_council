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

    await ctx.emit(
        {
            "type": "run_end",
            "elapsed": round(time.perf_counter() - started, 2),
            "transcript": {
                "question": ctx.question,
                "pattern": pattern.to_dict(),
                "seats": [{**s.to_dict(), "label": ctx.label(s)} for s in ctx.seats],
                "chair": {**ctx.chair.to_dict(), "label": "Chair"},
                "log": ctx.log,
                "verdict": verdict,
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

    async def runner() -> None:
        try:
            await _orchestrate(ctx, pattern_id)
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

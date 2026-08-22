"""Shared machinery every coordination pattern is built from.

`Ctx` owns the client, the roster and the event queue, and gives patterns three
verbs: open/close a round, make one seat speak (streamed), and fan several seats
out at once. Everything a pattern does shows up in the UI through these.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, Iterable

from openai import AsyncOpenAI

from .client import build_messages, stream_chat
from .config import Seat

Event = dict[str, Any]

LABELS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

STYLE = (
    "Be concrete and specific: name the trade-offs, the numbers, the failure modes. "
    "State any assumption explicitly. No preamble, no restating of the question, no "
    "flattery, no filler. Markdown."
)


RANK_TITLE = {"leader": "Leader", "minister": "Minister", "member": "Member"}

# How many seats may stream at once. A full roster fanning out unthrottled is
# the quickest way to trip NIM's per-key rate limit, and a 429 costs a whole
# seat's turn - far more than the few seconds queueing adds.
DEFAULT_CONCURRENCY = 6

# Bytes-per-token used only for the fallback estimate, when the endpoint does
# not report real usage. Good enough for "roughly what did this session cost".
CHARS_PER_TOKEN = 4


def letter_for(index: int) -> str:
    """A, B, … Z, then AA, AB, … — letters must stay unique or seats collide."""
    if index < len(LABELS):
        return LABELS[index]
    return LABELS[index // len(LABELS) - 1] + LABELS[index % len(LABELS)]


def label_for(index: int, rank: str = "member") -> str:
    return f"{RANK_TITLE.get(rank, 'Member')} {letter_for(index)}"


# Marks the placeholder speak() returns when a seat burns its whole budget on
# reasoning and never reaches an answer (see speak() below). Anything else
# checking "did this seat actually answer" should use is_usable(), not len().
_UNUSABLE_MARKER = "never reached an answer"


def is_usable(text: str, min_chars: int = 40) -> bool:
    text = (text or "").strip()
    return len(text) >= min_chars and _UNUSABLE_MARKER not in text


def extract_json(text: str) -> dict[str, Any] | None:
    """Pull the last JSON object out of a model reply (fenced or bare)."""
    if not text:
        return None
    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidates = list(reversed(fenced))
    depth, start = 0, None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                candidates.append(text[start : i + 1])
    for blob in reversed(candidates):
        try:
            parsed = json.loads(blob)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


class Ctx:
    """Execution context handed to a pattern."""

    def __init__(
        self,
        client: AsyncOpenAI,
        question: str,
        seats: list[Seat],
        chair: Seat,
        queue: asyncio.Queue[Event | None],
        options: dict[str, Any] | None = None,
    ) -> None:
        self.client = client
        self.question = question
        self.seats = seats
        self.chair = chair
        self.queue = queue
        self.options = options or {}
        self._letters = {s.id: letter_for(i) for i, s in enumerate(seats)}
        self._labels = {s.id: label_for(i, s.rank) for i, s in enumerate(seats)}
        self._labels[chair.id] = "the Council Leader"
        self._letters[chair.id] = "L"
        self.log: list[dict[str, str]] = []  # everything said, in order
        self.timings: dict[str, float] = {}  # seat id -> seconds, successful turns only
        gate = int(self.options.get("concurrency") or DEFAULT_CONCURRENCY)
        self._gate = asyncio.Semaphore(max(1, gate))
        # Session accounting, reported on run_end.
        self.calls = 0     # model calls attempted
        self.failures = 0  # calls that raised
        self.chars_in = 0  # prompt characters sent
        self.chars_out = 0  # answer + reasoning characters received
        self.usage: dict[str, int] = {}  # real token counts, when reported

    def usage_report(self) -> dict[str, Any]:
        """What this session cost, as far as the endpoint lets us tell."""
        report: dict[str, Any] = {
            "calls": self.calls,
            "failures": self.failures,
            "chars_in": self.chars_in,
            "chars_out": self.chars_out,
        }
        if self.usage:
            report["tokens"] = dict(self.usage)
            report["tokens_estimated"] = False
        else:
            report["tokens"] = {
                "prompt_tokens": self.chars_in // CHARS_PER_TOKEN,
                "completion_tokens": self.chars_out // CHARS_PER_TOKEN,
                "total_tokens": (self.chars_in + self.chars_out) // CHARS_PER_TOKEN,
            }
            report["tokens_estimated"] = True
        return report

    # -- roster helpers -------------------------------------------------
    def label(self, seat: Seat) -> str:
        return self._labels.get(seat.id, seat.name)

    def ministers(self) -> list[Seat]:
        return [s for s in self.seats if s.rank == "minister"]

    def members(self) -> list[Seat]:
        return [s for s in self.seats if s.rank != "minister"]

    def fastest_seat(self, exclude: str | None = None) -> Seat | None:
        """The quickest seat that has already answered successfully this
        session — used to stand in when the primary choice for a turn fails."""
        ranked = sorted(
            (s for s in self.seats if s.id in self.timings and s.id != exclude),
            key=lambda s: self.timings[s.id],
        )
        if ranked:
            return ranked[0]
        return next((s for s in self.seats if s.id != exclude), None)

    def by_label(self, label: str | None) -> Seat | None:
        """Resolve 'B' / 'Minister B' / 'Member D' / a seat id / a name to a seat."""
        if not label:
            return None
        want = str(label).strip().lower()
        bare = re.sub(r"^(the\s+)?(council\s+)?(leader|minister|member|advisor|chair)\s*", "", want)
        for seat in self.seats:
            if want in (self._labels[seat.id].lower(), seat.id.lower(), seat.name.lower()):
                return seat
            if bare and bare == self._letters[seat.id].lower():
                return seat
        return None

    def roster_text(self, seats: Iterable[Seat] | None = None) -> str:
        return "\n".join(
            f"- {self.label(s)} — {s.name} (`{s.model}`)" for s in (seats or self.seats)
        )

    def rank_brief(self, seat: Seat) -> str:
        """The standing that goes into a seat's system prompt."""
        if seat.rank == "minister":
            return (
                f"You are {self.label(seat)}, one of the council's ministers — a senior "
                "seat. You are expected to take positions the members cannot, and the "
                "Leader weighs your judgement heavily."
            )
        return (
            f"You are {self.label(seat)}, a member of the council. Rank does not protect "
            "a bad argument: contradict a minister when the evidence is on your side."
        )

    def transcript(self, entries: Iterable[dict[str, str]] | None = None) -> str:
        rows = list(entries if entries is not None else self.log)
        if not rows:
            return "(nothing on the record yet)"
        return "\n\n".join(f"--- {r['who']} ({r['stage']}) ---\n\n{r['text']}" for r in rows if r["text"])

    def block(
        self,
        answers: dict[str, str],
        seats: list[Seat] | None = None,
        skip: str | None = None,
    ) -> str:
        """Answers laid out one labelled section per seat, ready for a prompt."""
        out = []
        for seat in seats if seats is not None else self.seats:
            if seat.id == skip:
                continue
            text = (answers.get(seat.id) or "").strip()
            if text:
                out.append(f"--- {self.label(seat)} — {seat.name} ---\n\n{text}")
        return "\n\n".join(out) if out else "(no statements were returned)"

    # -- event verbs ----------------------------------------------------
    async def emit(self, event: Event) -> None:
        await self.queue.put(event)

    async def note(self, text: str, round_name: str | None = None) -> None:
        """A line of narration under a round heading (routing decisions, plans…)."""
        await self.emit({"type": "note", "round": round_name, "text": text})

    async def open_round(self, name: str, title: str, solo: bool = False) -> None:
        await self.emit({"type": "round_start", "round": name, "title": title, "solo": solo})

    async def close_round(self, name: str) -> None:
        await self.emit({"type": "round_end", "round": name})

    async def speak(self, seat: Seat, round_name: str, system: str, user: str) -> str:
        """Stream one seat's turn into the UI and onto the record."""
        messages = build_messages(seat, system, user)
        parts: list[str] = []
        reasoning: list[str] = []
        finish = ""

        # Queue behind the concurrency gate before starting the clock, so
        # `elapsed` measures the model rather than the wait for a free slot.
        async with self._gate:
            started = time.perf_counter()
            self.calls += 1
            self.chars_in += sum(len(m.get("content") or "") for m in messages)
            try:
                async for kind, text in stream_chat(self.client, seat, messages):
                    if kind == "finish":
                        finish = text
                        continue
                    if kind == "usage":
                        for field, value in (text or {}).items():
                            if isinstance(value, int):
                                self.usage[field] = self.usage.get(field, 0) + value
                        continue
                    (parts if kind == "content" else reasoning).append(text)
                    await self.emit(
                        {"type": "delta", "seat": seat.id, "round": round_name, "kind": kind, "text": text}
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # one seat failing must not end the session
                self.failures += 1
                await self.emit(
                    {
                        "type": "seat_error",
                        "seat": seat.id,
                        "round": round_name,
                        "message": f"{type(exc).__name__}: {exc}",
                    }
                )
                return ""
            elapsed = time.perf_counter() - started

        answer = "".join(parts).strip()
        self.chars_out += len(answer) + len("".join(reasoning))
        if not answer and finish == "length":
            # The whole budget went on thinking — say so rather than returning
            # an empty turn that the next round would silently work from.
            answer = (
                f"_({seat.name} spent its entire {seat.max_tokens}-token budget "
                f"reasoning and {_UNUSABLE_MARKER} — raise max_tokens or lower "
                "reasoning_budget for this seat.)_"
            )
        if is_usable(answer):
            self.timings[seat.id] = elapsed
        await self.emit(
            {
                "type": "seat_done",
                "seat": seat.id,
                "round": round_name,
                "elapsed": round(elapsed, 2),
                "chars": len(answer),
                "truncated": finish == "length",
                "reasoned": len("".join(reasoning)),
            }
        )
        self.log.append({"who": f"{self.label(seat)} — {seat.name}", "stage": round_name, "text": answer})
        return answer

    async def fanout(self, round_name: str, jobs: list[tuple[Seat, str, str]]) -> dict[str, str]:
        """Several seats speak at once; returns {seat_id: answer}."""
        tasks = [
            asyncio.create_task(self.speak(seat, round_name, system, user))
            for seat, system, user in jobs
        ]
        try:
            answers = await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            for t in tasks:
                t.cancel()
            raise
        return {job[0].id: ans for job, ans in zip(jobs, answers)}

    async def stage(
        self, name: str, title: str, jobs: list[tuple[Seat, str, str]], solo: bool = False
    ) -> dict[str, str]:
        """open_round + fanout + close_round, the shape most patterns want."""
        await self.open_round(name, title, solo=solo or len(jobs) == 1)
        answers = await self.fanout(name, jobs)
        await self.close_round(name)
        return answers

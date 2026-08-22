"""The protocol registry, and the behaviours patterns promise under failure.

These drive real `Ctx` objects with `stream_chat` replaced by a scripted fake,
so the pattern code, the prompts and the event stream all run for real without
touching the network.
"""

from __future__ import annotations

import asyncio

import pytest

from council import runtime as runtime_mod
from council.config import Seat
from council.patterns import DEFAULT_PATTERN, PATTERNS
from council.runtime import Ctx


# --- a scripted stand-in for the streaming endpoint ------------------------

class FakeEndpoint:
    """Replays canned replies, per seat id, and records what it was asked.

    A seat's reply is replayed for *every* turn that seat takes, the chair's
    verdict included, so canned replies have to clear the usability bar or the
    verdict fallback fires and the seat speaks twice. Real models are asked for
    prose followed by JSON, so the fixtures below are written that way too.
    """

    def __init__(self, replies=None, default="A perfectly adequate answer. " * 4,
                 fail=(), truncate=()):
        self.replies = replies or {}
        self.default = default
        self.fail = set(fail)
        self.truncate = set(truncate)
        self.calls = []  # (seat_id, system, user)

    def install(self, monkeypatch):
        async def fake_stream_chat(client, seat, messages):
            system = "\n".join(m["content"] for m in messages if m["role"] == "system")
            user = "\n".join(m["content"] for m in messages if m["role"] == "user")
            self.calls.append((seat.id, system, user))
            if seat.id in self.fail:
                raise RuntimeError("simulated endpoint failure")
            if seat.id in self.truncate:
                yield "finish", "length"
                return
            yield "content", self.replies.get(seat.id, self.default)
            yield "finish", "stop"

        monkeypatch.setattr(runtime_mod, "stream_chat", fake_stream_chat)
        return self

    def seats_that_spoke(self):
        return [seat_id for seat_id, _, _ in self.calls]


# Long enough to be "usable", and carrying the JSON the pattern parses.
ROUTE_TO_A = 'Member A owns this area and can close it quickly.\n{"advisor": "A", "why": "closest fit"}'
RESOLVED = 'I have answered this in full and am closing the ticket.\n{"resolved": true, "handoff_to": null}'


def hand_to(letter, note="I got part of the way; the rest is not mine."):
    return f'{note}\n{{"resolved": false, "handoff_to": "{letter}"}}'


def build_ctx(n=3, **options):
    seats = [
        Seat(id=f"s{i}", name=f"Model {i}", model=f"vendor/m{i}",
             rank="minister" if i == 0 else "member")
        for i in range(n)
    ]
    chair = Seat(id="chair", name="Chair", model="vendor/chair", rank="leader")
    return Ctx(None, "Should we ship on Friday?", seats, chair, asyncio.Queue(), options or None)


def run(coro):
    return asyncio.run(coro)


# --- registry ---------------------------------------------------------------

def test_all_eleven_protocols_are_registered():
    assert len(PATTERNS) == 11


def test_default_pattern_exists():
    assert DEFAULT_PATTERN in PATTERNS


def test_registry_keys_match_pattern_ids():
    for key, pattern in PATTERNS.items():
        assert key == pattern.id


def test_every_pattern_is_describable_and_runnable():
    for pattern in PATTERNS.values():
        assert callable(pattern.run)
        data = pattern.to_dict()
        assert data["name"] and data["what"] and data["best_for"] and data["shape"]


def test_recommended_patterns_are_a_small_subset():
    recommended = [p for p in PATTERNS.values() if p.recommended]
    assert 0 < len(recommended) < len(PATTERNS)


# --- fan-out: the simplest topology ----------------------------------------

def test_fanout_asks_every_seat_then_the_chair(monkeypatch):
    fake = FakeEndpoint().install(monkeypatch)
    verdict = run(PATTERNS["fanout"].run(build_ctx(3)))
    assert fake.seats_that_spoke() == ["s0", "s1", "s2", "chair"]
    assert verdict


def test_a_failing_seat_does_not_stop_the_session(monkeypatch):
    fake = FakeEndpoint(fail={"s1"}).install(monkeypatch)
    ctx = build_ctx(3)
    verdict = run(PATTERNS["fanout"].run(ctx))
    assert verdict
    assert "s2" in fake.seats_that_spoke()
    assert ctx.failures == 1


def test_every_turn_is_written_to_the_record(monkeypatch):
    FakeEndpoint().install(monkeypatch)
    ctx = build_ctx(3)
    run(PATTERNS["fanout"].run(ctx))
    assert len(ctx.log) == 4  # three seats plus the verdict
    assert all(entry["who"] and entry["stage"] for entry in ctx.log)


# --- the verdict fallback ---------------------------------------------------

def test_a_failed_chair_hands_the_verdict_to_the_fastest_seat(monkeypatch):
    fake = FakeEndpoint(fail={"chair"}).install(monkeypatch)
    verdict = run(PATTERNS["fanout"].run(build_ctx(3)))
    spoke = fake.seats_that_spoke()
    assert spoke.count("chair") == 1
    assert spoke[-1] != "chair", "a seat should have stood in for the leader"
    assert verdict


def test_a_chair_that_burns_its_budget_also_triggers_the_fallback(monkeypatch):
    fake = FakeEndpoint(truncate={"chair"}).install(monkeypatch)
    verdict = run(PATTERNS["fanout"].run(build_ctx(3)))
    assert fake.seats_that_spoke()[-1] != "chair"
    assert verdict


# --- handoff: the regression this suite exists for -------------------------

def test_handoff_reroutes_past_a_seat_that_fails(monkeypatch):
    """A dead holder used to end the chain instantly, handing the leader an
    empty ticket and calling it resolved."""
    fake = FakeEndpoint(replies={"chair": ROUTE_TO_A}, fail={"s0"}).install(monkeypatch)
    run(PATTERNS["handoff"].run(build_ctx(3)))
    spoke = fake.seats_that_spoke()
    assert "s0" in spoke, "the routed seat should have been tried"
    assert any(s in spoke for s in ("s1", "s2")), "the ticket should have been re-routed"


def test_handoff_stops_when_a_seat_declares_it_resolved(monkeypatch):
    fake = FakeEndpoint(replies={"chair": ROUTE_TO_A, "s0": RESOLVED}).install(monkeypatch)
    run(PATTERNS["handoff"].run(build_ctx(3)))
    spoke = fake.seats_that_spoke()
    assert spoke.count("s0") == 1
    assert "s1" not in spoke and "s2" not in spoke


def test_handoff_follows_an_explicit_handoff_target(monkeypatch):
    fake = FakeEndpoint(replies={
        "chair": ROUTE_TO_A,
        "s0": hand_to("C"),
        "s2": RESOLVED,
    }).install(monkeypatch)
    run(PATTERNS["handoff"].run(build_ctx(3)))
    spoke = fake.seats_that_spoke()
    assert spoke.index("s0") < spoke.index("s2")
    assert "s1" not in spoke


def test_handoff_never_revisits_a_seat(monkeypatch):
    fake = FakeEndpoint(replies={
        "chair": ROUTE_TO_A,
        "s0": hand_to("B"),
        "s1": hand_to("A"),  # back to a seat that already held it
    }).install(monkeypatch)
    run(PATTERNS["handoff"].run(build_ctx(3)))
    spoke = [s for s in fake.seats_that_spoke() if s != "chair"]
    assert len(spoke) == len(set(spoke))


def test_handoff_terse_replies_are_not_mistaken_for_failures(monkeypatch):
    """Only an error or an out-of-budget placeholder counts as dropping the
    ticket - a short but real answer must still resolve it."""
    fake = FakeEndpoint(replies={
        "chair": ROUTE_TO_A,
        "s0": '{"resolved": true, "handoff_to": null}',
    }).install(monkeypatch)
    run(PATTERNS["handoff"].run(build_ctx(3)))
    spoke = fake.seats_that_spoke()
    assert "s1" not in spoke and "s2" not in spoke


# --- orchestration degrades when the plan does not parse -------------------

def test_orchestration_gives_everyone_work_even_without_a_usable_plan(monkeypatch):
    fake = FakeEndpoint(replies={"chair": "no json here at all, sorry, just prose"}).install(monkeypatch)
    run(PATTERNS["orchestration"].run(build_ctx(3)))
    for seat_id in ("s0", "s1", "s2"):
        assert seat_id in fake.seats_that_spoke()


# --- protocol option knobs actually take effect ----------------------------

def test_a2a_sweeps_option_changes_the_number_of_rounds(monkeypatch):
    fake_one = FakeEndpoint().install(monkeypatch)
    run(PATTERNS["a2a"].run(build_ctx(2, sweeps=1)))
    one = len(fake_one.seats_that_spoke())

    fake_three = FakeEndpoint().install(monkeypatch)
    run(PATTERNS["a2a"].run(build_ctx(2, sweeps=3)))
    assert len(fake_three.seats_that_spoke()) > one


def test_swarm_respects_its_step_budget(monkeypatch):
    fake = FakeEndpoint(replies={
        "s0": 'Did the first slice of the work.\n{"done": false, "next": "B"}',
        "s1": 'Did the next slice of the work.\n{"done": false, "next": "A"}',
    }).install(monkeypatch)
    run(PATTERNS["swarm"].run(build_ctx(2, max_steps=2)))
    assert len([s for s in fake.seats_that_spoke() if s != "chair"]) == 2


def test_blackboard_passes_option(monkeypatch):
    fake = FakeEndpoint().install(monkeypatch)
    run(PATTERNS["blackboard"].run(build_ctx(2, passes=1)))
    assert len([s for s in fake.seats_that_spoke() if s != "chair"]) == 2


# --- every protocol survives whatever the roster does ----------------------

@pytest.mark.parametrize("pattern_id", sorted(PATTERNS))
def test_every_protocol_runs_with_a_single_seat(monkeypatch, pattern_id):
    FakeEndpoint().install(monkeypatch)
    verdict = run(PATTERNS[pattern_id].run(build_ctx(1)))
    assert isinstance(verdict, str) and verdict


@pytest.mark.parametrize("pattern_id", sorted(PATTERNS))
def test_every_protocol_survives_a_total_endpoint_outage(monkeypatch, pattern_id):
    FakeEndpoint(fail={"s0", "s1", "s2", "chair"}).install(monkeypatch)
    verdict = run(PATTERNS[pattern_id].run(build_ctx(3)))
    assert isinstance(verdict, str)  # empty is fine; crashing is not


# --- the concurrency gate is actually enforced -----------------------------

def test_fanout_never_exceeds_the_concurrency_limit(monkeypatch):
    peak = {"now": 0, "max": 0}

    async def counting_stream(client, seat, messages):
        peak["now"] += 1
        peak["max"] = max(peak["max"], peak["now"])
        await asyncio.sleep(0.01)
        peak["now"] -= 1
        yield "content", "An answer long enough to count as usable output here."
        yield "finish", "stop"

    monkeypatch.setattr(runtime_mod, "stream_chat", counting_stream)
    run(PATTERNS["fanout"].run(build_ctx(8, concurrency=3)))
    assert peak["max"] <= 3

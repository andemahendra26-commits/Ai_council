"""The verbs and helpers every coordination pattern is built from."""

from __future__ import annotations

import asyncio

import pytest

from council.config import Seat
from council.runtime import (
    Ctx,
    extract_json,
    is_usable,
    label_for,
    letter_for,
)


def make_ctx(n: int = 3, **options) -> Ctx:
    seats = [
        Seat(id=f"s{i}", name=f"Model {i}", model=f"vendor/model-{i}",
             rank="minister" if i == 0 else "member")
        for i in range(n)
    ]
    chair = Seat(id="chair", name="Chair Model", model="vendor/chair", rank="leader")
    return Ctx(None, "the question", seats, chair, asyncio.Queue(), options or None)


# --- seat letters must stay unique past Z ----------------------------------

def test_letters_are_sequential():
    assert [letter_for(i) for i in range(3)] == ["A", "B", "C"]


def test_letter_25_is_z_and_26_wraps_to_aa():
    assert letter_for(25) == "Z"
    assert letter_for(26) == "AA"
    assert letter_for(27) == "AB"


def test_letters_stay_unique_across_the_wrap():
    seen = [letter_for(i) for i in range(60)]
    assert len(seen) == len(set(seen))


def test_label_includes_the_rank_title():
    assert label_for(1, "minister") == "Minister B"
    assert label_for(0, "member") == "Member A"
    assert label_for(0, "nonsense") == "Member A"


# --- resolving what a model called a seat ----------------------------------

def test_by_label_accepts_every_form_a_model_might_use():
    ctx = make_ctx(3)
    target = ctx.seats[1]
    for form in ["B", "Member B", "member b", "s1", "Model 1", "  Member B  "]:
        assert ctx.by_label(form) is target, form


def test_by_label_strips_honorifics_it_does_not_own():
    ctx = make_ctx(3)
    assert ctx.by_label("Advisor B") is ctx.seats[1]
    assert ctx.by_label("the Council Minister A") is ctx.seats[0]


def test_by_label_returns_none_for_unknown_or_empty():
    ctx = make_ctx(3)
    assert ctx.by_label("Minister Z") is None
    assert ctx.by_label(None) is None
    assert ctx.by_label("") is None


# --- pulling a decision out of a model reply -------------------------------

def test_extract_json_from_a_fenced_block():
    assert extract_json('prose\n```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_from_a_bare_object():
    assert extract_json('here you go {"a": 1} done') == {"a": 1}


def test_extract_json_takes_the_last_object_when_there_are_several():
    text = '{"first": true}\nthen\n{"second": true}'
    assert extract_json(text) == {"second": True}


def test_extract_json_handles_nesting():
    assert extract_json('{"a": {"b": [1, 2]}}') == {"a": {"b": [1, 2]}}


def test_extract_json_ignores_malformed_and_non_objects():
    assert extract_json("{not json at all}") is None
    assert extract_json("[1, 2, 3]") is None
    assert extract_json("") is None
    assert extract_json(None) is None


def test_extract_json_skips_a_broken_block_for_a_valid_earlier_one():
    assert extract_json('{"good": 1}\nlater {"bad": ') == {"good": 1}


# --- did a seat actually answer? -------------------------------------------

def test_is_usable_rejects_short_and_empty():
    assert not is_usable("")
    assert not is_usable("   ")
    assert not is_usable("too short")
    assert is_usable("x" * 40)


def test_is_usable_rejects_the_out_of_budget_placeholder():
    placeholder = (
        "_(Model spent its entire 16384-token budget reasoning and never "
        "reached an answer - raise max_tokens.)_"
    )
    assert len(placeholder) > 40
    assert not is_usable(placeholder)


# --- prompt assembly --------------------------------------------------------

def test_block_labels_each_seat_and_skips_empties():
    ctx = make_ctx(3)
    text = ctx.block({"s0": "alpha", "s1": "   ", "s2": "gamma"})
    assert "alpha" in text and "gamma" in text
    assert "Minister A" in text and "Member C" in text
    assert "Member B" not in text


def test_block_can_skip_a_named_seat():
    ctx = make_ctx(3)
    text = ctx.block({"s0": "alpha", "s1": "beta"}, skip="s0")
    assert "beta" in text and "alpha" not in text


def test_block_accepts_an_explicit_seat_subset():
    ctx = make_ctx(3)
    text = ctx.block({"s0": "alpha", "s1": "beta"}, [ctx.seats[1]])
    assert "beta" in text and "alpha" not in text


def test_block_says_so_when_nothing_came_back():
    ctx = make_ctx(3)
    assert ctx.block({}) == "(no statements were returned)"


def test_transcript_reports_an_empty_record():
    assert make_ctx().transcript([]) == "(nothing on the record yet)"


# --- fallback selection -----------------------------------------------------

def test_fastest_seat_prefers_the_quickest_successful_turn():
    ctx = make_ctx(3)
    ctx.timings = {"s0": 9.0, "s1": 2.0, "s2": 5.0}
    assert ctx.fastest_seat().id == "s1"
    assert ctx.fastest_seat(exclude="s1").id == "s2"


def test_fastest_seat_falls_back_when_nobody_has_answered():
    ctx = make_ctx(3)
    assert ctx.fastest_seat() is ctx.seats[0]
    assert ctx.fastest_seat(exclude="s0") is ctx.seats[1]


# --- concurrency gate -------------------------------------------------------

def test_concurrency_defaults_and_honours_the_option():
    assert make_ctx()._gate._value > 0
    assert make_ctx(3, concurrency=2)._gate._value == 2


def test_concurrency_is_never_zero_or_negative():
    assert make_ctx(3, concurrency=0)._gate._value >= 1
    assert make_ctx(3, concurrency=-5)._gate._value >= 1


# --- usage accounting -------------------------------------------------------

def test_usage_report_estimates_when_the_endpoint_says_nothing():
    ctx = make_ctx()
    ctx.calls, ctx.chars_in, ctx.chars_out = 3, 400, 800
    report = ctx.usage_report()
    assert report["tokens_estimated"] is True
    assert report["calls"] == 3
    assert report["tokens"]["total_tokens"] == 300


def test_usage_report_prefers_real_numbers_when_reported():
    ctx = make_ctx()
    ctx.usage = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
    report = ctx.usage_report()
    assert report["tokens_estimated"] is False
    assert report["tokens"]["total_tokens"] == 30

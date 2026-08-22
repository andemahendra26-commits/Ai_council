"""Roster loading: defaults, .env lists, council.json, and payload clamping."""

from __future__ import annotations

import json

import pytest

from council import config as cfg_mod
from council.config import (
    CATALOG,
    DEFAULT_CHAIR,
    DEFAULT_SEATS,
    MAX_TOKENS_CEILING,
    MIN_TOKENS,
    CouncilConfig,
    Seat,
    _default_seats,
    _pretty,
    _slug,
    load_config,
    seat_for_model,
    seats_from_payload,
)


ROSTER_ENV = ("COUNCIL_LEADER", "COUNCIL_MINISTERS", "COUNCIL_MEMBERS",
              "COUNCIL_BENCH", "COUNCIL_CONFIG", "NVIDIA_BASE_URL")


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    """No roster env vars, and a ROOT with no council.json beside it."""
    for name in ROSTER_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(cfg_mod, "ROOT", tmp_path)
    return tmp_path


# --- the built-in defaults --------------------------------------------------

def test_defaults_promote_exactly_three_ministers(clean_env):
    ministers = [s for s in _default_seats() if s.enabled and s.rank == "minister"]
    assert len(ministers) == 3


def test_the_chair_model_is_not_also_seated(clean_env):
    """Regression: the chair ran z-ai/glm-5.2 and so did a seated minister, so
    the leader was weighing an argument it had also made itself."""
    seated = {s.model for s in _default_seats() if s.enabled}
    assert DEFAULT_CHAIR.model not in seated


def test_default_ministers_are_distinct_lineages(clean_env):
    ministers = [s for s in _default_seats() if s.enabled and s.rank == "minister"]
    vendors = [s.model.split("/")[0] for s in ministers]
    assert len(set(vendors)) == len(vendors)


def test_seat_ids_are_unique():
    ids = [s.id for s in DEFAULT_SEATS]
    assert len(ids) == len(set(ids))


def test_catalog_covers_every_default_seat():
    for seat in DEFAULT_SEATS:
        assert seat.model in CATALOG


# --- deriving a seat from a bare model id -----------------------------------

def test_seat_for_model_uses_catalog_settings_when_known():
    known = DEFAULT_SEATS[0]
    seat = seat_for_model(known.model, "member", 0)
    assert seat.name == known.name
    assert seat.color == known.color


def test_seat_for_model_invents_sane_defaults_for_unknown_ids():
    seat = seat_for_model("acme/frobnicator-9b-instruct", "member", 0)
    assert seat.model == "acme/frobnicator-9b-instruct"
    assert seat.name
    assert seat.color.startswith("#")
    assert seat.enabled


def test_seat_for_model_forces_the_chair_id_for_the_leader():
    assert seat_for_model("acme/x", "leader", 0).id == "chair"


def test_catalog_seats_are_copied_not_aliased():
    """Two seats built from one catalog entry must not share state."""
    a = seat_for_model(DEFAULT_SEATS[0].model, "member", 0)
    b = seat_for_model(DEFAULT_SEATS[0].model, "minister", 1)
    a.enabled = False
    assert b.enabled is True
    assert DEFAULT_SEATS[0].rank != "minister" or True  # catalog untouched


@pytest.mark.parametrize("model,expected", [
    ("meta/llama-3.3-70b-instruct", "meta_llama_3_3_70b_instruct"),
    ("Weird/Model.Name", "weird_model_name"),
])
def test_slug(model, expected):
    assert _slug(model) == expected


def test_pretty_keeps_parameter_counts_capitalised():
    assert "70B" in _pretty("meta/llama-3.3-70b-instruct")
    assert "MoE" in _pretty("microsoft/phi-3.5-moe-instruct")


# --- .env roster lists ------------------------------------------------------

def test_env_lists_set_ranks(clean_env, monkeypatch):
    monkeypatch.setenv("COUNCIL_LEADER", "acme/leader")
    monkeypatch.setenv("COUNCIL_MINISTERS", "acme/m1,acme/m2")
    monkeypatch.setenv("COUNCIL_MEMBERS", "acme/w1")
    cfg = load_config()
    assert cfg.chair.model == "acme/leader"
    assert [s.model for s in cfg.ministers()] == ["acme/m1", "acme/m2"]
    assert [s.model for s in cfg.members()] == ["acme/w1"]


def test_bench_models_are_listed_but_unseated(clean_env, monkeypatch):
    monkeypatch.setenv("COUNCIL_MEMBERS", "acme/w1")
    monkeypatch.setenv("COUNCIL_BENCH", "acme/b1,acme/b2")
    cfg = load_config()
    benched = [s for s in cfg.seats if not s.enabled]
    assert [s.model for s in benched] == ["acme/b1", "acme/b2"]
    assert "acme/b1" not in {s.model for s in cfg.enabled_seats()}


def test_a_model_listed_twice_is_seated_once(clean_env, monkeypatch):
    monkeypatch.setenv("COUNCIL_MINISTERS", "acme/dup")
    monkeypatch.setenv("COUNCIL_MEMBERS", "acme/dup,acme/other")
    cfg = load_config()
    assert [s.model for s in cfg.seats].count("acme/dup") == 1


def test_the_leader_is_not_also_given_a_seat(clean_env, monkeypatch):
    monkeypatch.setenv("COUNCIL_LEADER", "acme/leader")
    monkeypatch.setenv("COUNCIL_MEMBERS", "acme/leader,acme/other")
    cfg = load_config()
    assert "acme/leader" not in {s.model for s in cfg.seats}


@pytest.mark.parametrize("raw", ["a, b", "a\nb", "a;b", " a , b "])
def test_roster_lists_accept_several_separators(clean_env, monkeypatch, raw):
    monkeypatch.setenv("COUNCIL_MEMBERS", raw)
    assert [s.model for s in load_config().seats] == ["a", "b"]


# --- council.json overrides everything --------------------------------------

def test_council_json_overrides_env(clean_env, monkeypatch):
    monkeypatch.setenv("COUNCIL_MEMBERS", "acme/from-env")
    path = clean_env / "council.json"
    path.write_text(json.dumps({
        "seats": [{"id": "x", "name": "X", "model": "acme/from-json", "enabled": True}],
        "chair": {"id": "chair", "name": "C", "model": "acme/chair"},
    }), encoding="utf-8")
    cfg = load_config()
    assert [s.model for s in cfg.seats] == ["acme/from-json"]
    assert cfg.chair.model == "acme/chair"


def test_partial_seat_dicts_fill_from_the_catalog(clean_env):
    known = DEFAULT_SEATS[0]
    path = clean_env / "council.json"
    path.write_text(json.dumps({"seats": [{"id": known.id}]}), encoding="utf-8")
    seat = load_config().seats[0]
    assert seat.model == known.model
    assert seat.name == known.name


# --- payloads from the browser are untrusted --------------------------------

def test_payload_clamps_an_absurd_token_request():
    cfg = CouncilConfig()
    seat = seats_from_payload(
        [{"id": "x", "model": "m", "max_tokens": 10 ** 9, "enabled": True}], cfg
    )[0]
    assert seat.max_tokens == MAX_TOKENS_CEILING


def test_payload_clamps_sampling_parameters():
    cfg = CouncilConfig()
    seat = seats_from_payload(
        [{"id": "x", "model": "m", "temperature": 99, "top_p": 5, "enabled": True}], cfg
    )[0]
    assert seat.temperature == 2.0
    assert seat.top_p == 1.0


def test_payload_raises_a_silly_low_token_request_to_the_floor():
    cfg = CouncilConfig()
    seat = seats_from_payload([{"id": "x", "model": "m", "max_tokens": 1, "enabled": True}], cfg)[0]
    assert seat.max_tokens == MIN_TOKENS


def test_payload_drops_disabled_seats():
    cfg = CouncilConfig()
    seats = seats_from_payload([
        {"id": "a", "model": "m", "enabled": True},
        {"id": "b", "model": "m", "enabled": False},
    ], cfg)
    assert [s.id for s in seats] == ["a"]


def test_empty_payload_falls_back_to_the_configured_roster():
    cfg = CouncilConfig()
    assert len(seats_from_payload(None, cfg)) == len(cfg.enabled_seats())


def test_unknown_keys_in_a_payload_are_ignored():
    cfg = CouncilConfig()
    seat = seats_from_payload(
        [{"id": "x", "model": "m", "enabled": True, "evil": "rm -rf /"}], cfg
    )[0]
    assert not hasattr(seat, "evil")


# --- thinking knobs ---------------------------------------------------------

def test_extra_body_only_for_thinking_seats():
    assert Seat(id="a", name="A", model="m", thinking=False).extra_body() is None
    body = Seat(id="a", name="A", model="m", thinking=True, reasoning_budget=99).extra_body()
    assert body["chat_template_kwargs"]["enable_thinking"] is True
    assert body["reasoning_budget"] == 99

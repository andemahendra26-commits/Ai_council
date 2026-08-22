"""Council roster: who sits at the table, and how each seat is called."""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"

ROOT = Path(__file__).resolve().parent.parent


RANKS = ("leader", "minister", "member")

# The browser sends whole seat dicts back, so max_tokens is attacker-controlled
# on any non-loopback bind. Clamp it: without a ceiling a caller could bill the
# operator's API key for an arbitrarily long generation on every seat.
MAX_TOKENS_CEILING = 32768
MIN_TOKENS = 64


@dataclass
class Seat:
    """One member of the council."""

    id: str
    name: str
    model: str
    color: str = "#7aa2f7"
    # leader = chairs the council; minister = senior seat; member = base seat
    rank: str = "member"
    temperature: float = 1.0
    top_p: float = 0.95
    max_tokens: int = 16384
    # Nemotron / Qwen3-style toggle: sends chat_template_kwargs.enable_thinking
    thinking: bool = False
    reasoning_budget: int = 16384
    # Nemotron-1.x style toggle: prepends a "detailed thinking on" system line
    system_prefix: str = ""
    # Optional flavour added to the system prompt ("", or e.g. "You lean sceptical.")
    persona: str = ""
    enabled: bool = True

    def extra_body(self) -> dict[str, Any] | None:
        if not self.thinking:
            return None
        return {
            "chat_template_kwargs": {"enable_thinking": True},
            "reasoning_budget": self.reasoning_budget,
        }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Every flagship chat model reachable on build.nvidia.com, across vendors, so the
# council genuinely disagrees instead of echoing one lineage. The five strongest
# and most different sit by default; the rest are one tick away in the UI.
# `python -m council.models` prints what your key can actually reach, and every
# seat's model can be re-pointed at any of them from the browser.
DEFAULT_SEATS: list[Seat] = [
    # -- seated by default: 13 flagships, one per lineage ------------------
    Seat(
        id="gptoss120",
        name="GPT-OSS 120B",
        model="openai/gpt-oss-120b",
        color="#8b95ff",
        temperature=0.7, top_p=0.95, max_tokens=12288,
    ),
    # Benched by default *because* it is the chair's model (see DEFAULT_CHAIR).
    # Seating it too would put the same model on both sides of the verdict —
    # the leader would be weighing an argument it had also made itself, which
    # defeats the point of a mixed-lineage council. Tick it on only if you
    # re-point the chair at something else.
    Seat(
        id="glm52",
        name="GLM-5.2",
        model="z-ai/glm-5.2",
        color="#5ad1c8",
        temperature=0.7, top_p=0.95, max_tokens=12288, enabled=False,
    ),
    Seat(
        id="super120",
        name="Nemotron 3 Super 120B",
        model="nvidia/nemotron-3-super-120b-a12b",
        color="#9ece6a",
        temperature=0.7, top_p=0.95, max_tokens=16384,
        thinking=True, reasoning_budget=12288,
    ),
    Seat(
        id="kimi",
        name="Kimi K2.6",
        model="moonshotai/kimi-k2.6",
        color="#bb9af7",
        temperature=0.6, top_p=0.9, max_tokens=12288,
    ),
    Seat(
        id="deepseek",
        name="DeepSeek V4 Flash",
        model="deepseek-ai/deepseek-v4-flash-0731",
        color="#4d9dff",
        temperature=0.6, top_p=0.95, max_tokens=12288,
    ),

    Seat(
        id="minimax",
        name="MiniMax M3",
        model="minimaxai/minimax-m3",
        color="#ff7ab8",
        temperature=0.7, top_p=0.95, max_tokens=12288,
    ),
    Seat(
        id="step37",
        name="Step 3.7 Flash",
        model="stepfun-ai/step-3.7-flash",
        color="#f2a65a",
        temperature=0.7, top_p=0.95, max_tokens=12288,
    ),
    Seat(
        id="inkling",
        name="Inkling",
        model="thinkingmachines/inkling",
        color="#c9d1ff",
        temperature=0.7, top_p=0.95, max_tokens=12288,
    ),
    Seat(
        id="llama33",
        name="Llama 3.3 70B",
        model="meta/llama-3.3-70b-instruct",
        color="#4aa3ff",
        temperature=0.8, top_p=0.95, max_tokens=8192,
    ),
    Seat(
        id="muse",
        name="Muse Glimmer 30B",
        model="meta/muse-glimmer-30b",
        color="#7cc4ff",
        temperature=0.8, top_p=0.95, max_tokens=8192,
    ),
    Seat(
        id="gemma4",
        name="Gemma 4 31B",
        model="google/gemma-4-31b-it",
        color="#ffd166",
        temperature=0.8, top_p=0.95, max_tokens=8192,
    ),
    Seat(
        id="mistrallarge",
        name="Mistral Large 2",
        model="mistralai/mistral-large-2-instruct",
        color="#ff8a3d",
        temperature=0.7, top_p=0.95, max_tokens=8192,
    ),
    Seat(
        id="lightning",
        name="Nemotron 3.5 Lightning 30B",
        model="nvidia/nemotron-3.5-lightning-30b-a3b",
        color="#76b900",
        temperature=1.0, top_p=0.95, max_tokens=16384,
        thinking=True, reasoning_budget=12288,
    ),

    # -- on the bench: tick them in the roster to seat them ----------------
    Seat(
        id="ultra550",
        name="Nemotron 3 Ultra 550B",
        model="nvidia/nemotron-3-ultra-550b-a55b",
        color="#76b900",
        temperature=0.6, top_p=0.95, max_tokens=16384,
        thinking=True, reasoning_budget=12288, enabled=False,
    ),
    Seat(
        id="lnsuper49",
        name="Llama 3.3 Nemotron Super 49B v1.5",
        model="nvidia/llama-3.3-nemotron-super-49b-v1.5",
        color="#a3d977",
        temperature=0.6, top_p=0.95, max_tokens=8192,
        system_prefix="detailed thinking on", enabled=False,
    ),
    Seat(
        id="nemoultra253",
        name="Llama 3.1 Nemotron Ultra 253B",
        model="nvidia/llama-3.1-nemotron-ultra-253b-v1",
        color="#8fce4a",
        temperature=0.6, top_p=0.95, max_tokens=8192,
        system_prefix="detailed thinking on", enabled=False,
    ),
    Seat(
        id="nemotron340",
        name="Nemotron 4 340B",
        model="nvidia/nemotron-4-340b-instruct",
        color="#5f9e2f",
        temperature=0.7, top_p=0.95, max_tokens=4096, enabled=False,
    ),
    Seat(
        id="nano30",
        name="Nemotron 3 Nano 30B",
        model="nvidia/nemotron-3-nano-30b-a3b",
        color="#2ac3de",
        temperature=0.8, top_p=0.95, max_tokens=8192,
        thinking=True, reasoning_budget=8192, enabled=False,
    ),
    Seat(
        id="jamba",
        name="Jamba 1.5 Large",
        model="ai21labs/jamba-1.5-large-instruct",
        color="#e07be0",
        temperature=0.7, top_p=0.95, max_tokens=4096, enabled=False,
    ),
    Seat(
        id="palmyra",
        name="Palmyra Creative 122B",
        model="writer/palmyra-creative-122b",
        color="#ffb0c8",
        temperature=0.9, top_p=0.95, max_tokens=4096, enabled=False,
    ),
    Seat(
        id="phimoe",
        name="Phi-3.5 MoE",
        model="microsoft/phi-3.5-moe-instruct",
        color="#5bc0eb",
        temperature=0.8, top_p=0.95, max_tokens=4096, enabled=False,
    ),
    Seat(
        id="yi",
        name="Yi Large",
        model="01-ai/yi-large",
        color="#9be3a0",
        temperature=0.8, top_p=0.95, max_tokens=4096, enabled=False,
    ),
    Seat(
        id="dbrx",
        name="DBRX Instruct",
        model="databricks/dbrx-instruct",
        color="#ff5f4d",
        temperature=0.8, top_p=0.95, max_tokens=4096, enabled=False,
    ),
    Seat(
        id="laguna",
        name="Laguna XS 2.1",
        model="poolside/laguna-xs-2.1",
        color="#00d1b2",
        temperature=0.7, top_p=0.95, max_tokens=8192, enabled=False,
    ),
    Seat(
        id="gptoss20",
        name="GPT-OSS 20B",
        model="openai/gpt-oss-20b",
        color="#b0b7ff",
        temperature=0.8, top_p=0.95, max_tokens=8192, enabled=False,
    ),
    Seat(
        id="mistralnemotron",
        name="Mistral Nemotron",
        model="mistralai/mistral-nemotron",
        color="#ffa64d",
        temperature=0.7, top_p=0.95, max_tokens=8192, enabled=False,
    ),
    Seat(
        id="nemotron70",
        name="Llama 3.1 Nemotron 70B",
        model="nvidia/llama-3.1-nemotron-70b-instruct",
        color="#6fae3a",
        temperature=0.7, top_p=0.95, max_tokens=4096, enabled=False,
    ),
    Seat(
        id="nano9",
        name="Nemotron Nano 9B v2",
        model="nvidia/nvidia-nemotron-nano-9b-v2",
        color="#3fbf8f",
        temperature=0.8, top_p=0.95, max_tokens=8192, enabled=False,
    ),
    # Found via a catalog probe on 2026-08-13 that also 404'd 11 other
    # untested models for this account — these are the ones that actually
    # answered.
    Seat(
        id="llama31_70b",
        name="Llama 3.1 70B",
        model="meta/llama-3.1-70b-instruct",
        color="#4aa3ff",
        temperature=0.8, top_p=0.95, max_tokens=8192, enabled=False,
    ),
    Seat(
        id="llama31_8b",
        name="Llama 3.1 8B",
        model="meta/llama-3.1-8b-instruct",
        color="#7cc4ff",
        temperature=0.8, top_p=0.95, max_tokens=8192, enabled=False,
    ),
    Seat(
        id="nemonano8",
        name="Llama 3.1 Nemotron Nano 8B",
        model="nvidia/llama-3.1-nemotron-nano-8b-v1",
        color="#5f9e2f",
        # Answered correctly in testing but took ~35s for a 48-token reply -
        # noticeably slower than the other small models on this account.
        temperature=0.7, top_p=0.95, max_tokens=8192, enabled=False,
    ),
    Seat(
        id="nemomini4",
        name="Nemotron Mini 4B",
        model="nvidia/nemotron-mini-4b-instruct",
        color="#8fce4a",
        # NVIDIA's catalog listed this "Deprecation in 13d" as of 2026-08-13.
        temperature=0.8, top_p=0.95, max_tokens=4096, enabled=False,
    ),
]

# nemotron-3-ultra-550b-a55b was the original leader but proved unreliable in
# testing on 2026-08-13 — an outright connection failure under load, and a
# live run where it burned its whole token budget reasoning and returned
# nothing. glm-5.2 answered fast (7-20s) and well in every test that day, so
# it chairs instead; the old leader is a minister now, where a slow or failed
# turn costs one round instead of the whole session (and the verdict step
# itself also has a same-session fallback if the chair ever fails outright —
# see patterns.py's _verdict()).
DEFAULT_CHAIR = Seat(
    id="chair",
    name="GLM-5.2",
    model="z-ai/glm-5.2",
    color="#ffb648",
    temperature=0.6,
    top_p=0.95,
    max_tokens=12288,
)


def _default_seats() -> list[Seat]:
    """Defaults with ranks applied: the first three seated models are ministers."""
    seats = [Seat(**s.to_dict()) for s in DEFAULT_SEATS]
    promoted = 0
    for seat in seats:
        if seat.enabled and promoted < 3:
            seat.rank = "minister"
            promoted += 1
    return seats


# Every model the roster knows how to configure, keyed by model id, so a bare
# id listed in .env still gets its proper name, colour and thinking settings.
CATALOG: dict[str, Seat] = {s.model: s for s in [*DEFAULT_SEATS, DEFAULT_CHAIR]}

PALETTE = ["#7fe9ff", "#9ece6a", "#bb9af7", "#ffb648", "#ff7ab8", "#5ad1c8",
           "#8b95ff", "#f2a65a", "#4d9dff", "#c9d1ff", "#76b900", "#ff8a3d"]


def _slug(model: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", model.lower()).strip("_")


def _pretty(model: str) -> str:
    tail = model.split("/")[-1].replace("-", " ").replace("_", " ")
    return re.sub(r"\b(\d+(?:\.\d+)?)b\b", lambda m: m.group(1) + "B", tail).title().replace("Moe", "MoE")


def seat_for_model(model: str, rank: str, index: int) -> Seat:
    """Build a seat for a model id, using catalog settings when we know it."""
    model = model.strip()
    known = CATALOG.get(model)
    seat = Seat(**known.to_dict()) if known else Seat(
        id=_slug(model), name=_pretty(model), model=model, color=PALETTE[index % len(PALETTE)]
    )
    seat.rank = rank
    seat.enabled = True
    if rank == "leader":
        seat.id = "chair"
    return seat


def _split_models(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [m.strip() for m in re.split(r"[,\n;]+", raw) if m.strip()]


@dataclass
class CouncilConfig:
    seats: list[Seat] = field(default_factory=_default_seats)
    chair: Seat = field(default_factory=lambda: Seat(**{**DEFAULT_CHAIR.to_dict(), "rank": "leader"}))
    base_url: str = DEFAULT_BASE_URL

    def enabled_seats(self) -> list[Seat]:
        return [s for s in self.seats if s.enabled]

    def ministers(self) -> list[Seat]:
        return [s for s in self.enabled_seats() if s.rank == "minister"]

    def members(self) -> list[Seat]:
        return [s for s in self.enabled_seats() if s.rank != "minister"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "seats": [s.to_dict() for s in self.seats],
            "chair": self.chair.to_dict(),
            "base_url": self.base_url,
        }


def _seat_from(data: dict[str, Any], fallback: Seat | None = None) -> Seat:
    """Build a Seat from a partial dict, filling gaps from `fallback` or defaults."""
    base = fallback.to_dict() if fallback else {}
    known = {f for f in Seat.__dataclass_fields__}
    base.update({k: v for k, v in data.items() if k in known})
    base.setdefault("id", data.get("model", "seat").replace("/", "_"))
    base.setdefault("name", base["id"])
    return Seat(**base)


def load_config(path: str | os.PathLike[str] | None = None) -> CouncilConfig:
    """Load the roster.

    Precedence: council.json (or $COUNCIL_CONFIG) > the COUNCIL_LEADER /
    COUNCIL_MINISTERS / COUNCIL_MEMBERS model lists in .env > built-in defaults.
    """
    cfg = CouncilConfig(base_url=os.environ.get("NVIDIA_BASE_URL", DEFAULT_BASE_URL))

    leader = _split_models(os.environ.get("COUNCIL_LEADER"))
    ministers = _split_models(os.environ.get("COUNCIL_MINISTERS"))
    members = _split_models(os.environ.get("COUNCIL_MEMBERS"))
    bench = _split_models(os.environ.get("COUNCIL_BENCH"))
    if leader or ministers or members:
        if leader:
            cfg.chair = seat_for_model(leader[0], "leader", 0)
        seats: list[Seat] = []
        seen: set[str] = set()
        for rank, models in (("minister", ministers), ("member", members), ("member", bench)):
            for model in models:
                if model in seen or model == cfg.chair.model:
                    continue
                seen.add(model)
                seat = seat_for_model(model, rank, len(seats))
                seat.enabled = models is not bench
                seats.append(seat)
        if seats:
            cfg.seats = seats

    candidate = path or os.environ.get("COUNCIL_CONFIG") or ROOT / "council.json"
    candidate = Path(candidate)
    if not candidate.is_file():
        return cfg

    raw = json.loads(candidate.read_text(encoding="utf-8"))
    by_id = {s.id: s for s in DEFAULT_SEATS}
    if "seats" in raw:
        cfg.seats = [_seat_from(s, by_id.get(s.get("id", ""))) for s in raw["seats"]]
    if "chair" in raw:
        cfg.chair = _seat_from(raw["chair"], DEFAULT_CHAIR)
    if "base_url" in raw:
        cfg.base_url = raw["base_url"]
    return cfg


def clamp_seat(seat: Seat) -> Seat:
    """Bring a client-supplied seat back inside sane generation limits."""
    seat.max_tokens = max(MIN_TOKENS, min(int(seat.max_tokens), MAX_TOKENS_CEILING))
    seat.reasoning_budget = max(0, min(int(seat.reasoning_budget), MAX_TOKENS_CEILING))
    seat.temperature = max(0.0, min(float(seat.temperature), 2.0))
    seat.top_p = max(0.01, min(float(seat.top_p), 1.0))
    return seat


def seats_from_payload(payload: list[dict[str, Any]] | None, cfg: CouncilConfig) -> list[Seat]:
    """Turn a UI payload (possibly partial seat dicts) into Seats."""
    if not payload:
        return [clamp_seat(s) for s in cfg.enabled_seats()]
    by_id = {s.id: s for s in cfg.seats}
    seats = [_seat_from(s, by_id.get(s.get("id", ""))) for s in payload]
    return [clamp_seat(s) for s in seats if s.enabled]

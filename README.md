# Alfredo Council

An AI council: **a dozen different models** from the NVIDIA NIM catalog
deliberate on your question under one of **11 multi-agent coordination
protocols**, and a council leader delivers the verdict. Everything streams live
to a HUD-style web UI — every model's reasoning as it forms, drawn as a topology
of the protocol actually being run.

```
run_council.bat          # first run installs everything, then opens the browser
```

---

## The council

Rank comes from `.env`, not from code:

| Rank | Count | Role |
| --- | --- | --- |
| **Leader** | 1 | Chairs every session and writes the final verdict |
| **Ministers** | 3 | Senior seats — the leader weighs their judgement heavily |
| **Members** | 9 | The base of the council |
| **Bench** | 20 | Listed in the UI roster, unseated until you tick them |

```dotenv
COUNCIL_LEADER=z-ai/glm-5.2
COUNCIL_MINISTERS=openai/gpt-oss-120b,nvidia/nemotron-3-super-120b-a12b,moonshotai/kimi-k2.6
COUNCIL_MEMBERS=deepseek-ai/deepseek-v4-flash-0731,minimaxai/minimax-m3,...
COUNCIL_BENCH=nvidia/nemotron-3-ultra-550b-a55b,...
```

Move a model between lists to change its rank. Any id from
`python -m council.models` works, and every seat's model can also be re-pointed
from the browser without touching a file.

**The leader is not the biggest model on the catalog, deliberately.**
`nemotron-3-ultra-550b` was the original chair and proved unreliable under load
— an outright connection failure, and a live run where it spent its whole token
budget reasoning and returned nothing. GLM-5.2 answered fast and well in every
test, so it chairs; the 550B sits on the bench. A model must never be both the
leader and a seat, or the verdict weighs an argument the leader itself made.

## The 11 protocols

You pick one when the app opens; each card shows a live diagram of its topology.

| Protocol | What happens | Best for |
| --- | --- | --- |
| **Orchestration** | Leader splits the task, assigns one subtask per seat, assembles | Most common production pattern |
| **A2A** | Seats message each other directly, no manager in the loop | Independent agents collaborating |
| **Handoff** | A router picks an owner; each seat resolves or hands the ticket on | Support, routing |
| **Sequential / Pipeline** | Draft → correct → deepen → tighten, each seat reworking the last | Fixed workflows |
| **Parallel / Fan-out** | Everyone answers at once, leader merges | Research, comparison |
| **Supervisor** | Leader briefs specialists, reviews, sends thin work back | Complex tasks |
| **Debate / Critic** | Openings, then everyone attacks everyone, then the leader rules | Reasoning & quality |
| **Hierarchical** | Leader → ministers run workstreams → members dig, consolidating up | Large agent systems |
| **Swarm** | Whoever holds the task does a piece and picks who takes it next | Dynamic workflows |
| **Blackboard** | Nobody addresses anybody — all read/write one shared board | Collaborative systems |
| **Event-driven** | The question becomes events; handlers react and emit more events | Async systems |

Each one is a real implementation, not a relabelled loop: handoff genuinely
re-routes on the model's own JSON decision, swarm lets the current holder choose
its successor, hierarchical uses the council's own org chart, and the event bus
dispatches follow-up events emitted by handlers.

Four of them loop, and the protocol strip shows a knob for how many times:
A2A **sweeps**, swarm **steps**, blackboard **passes**, event-driven **waves**.
More is slower and usually better.

## The council floor

Send a question and the UI becomes a live topology of the chosen protocol:

- every node carries its vendor logo, its rank, and its own streaming thoughts;
- output travels the edges as packets as each seat reports;
- in tiered protocols the members fade out once done and the view zooms to the
  ministers, then to the leader for the verdict;
- click any node to jump to that seat's full text in the transcript below.

Past sessions are listed under **Archive**; click one to read it back.

## Setup

`run_council.bat` does all of this for you. By hand:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env        # then paste your key from https://build.nvidia.com
.venv\Scripts\python.exe -m council
```

Useful commands:

```powershell
python -m council.models              # every model your key can reach
python -m council.models nemotron     # filtered, and flags any seat pointing at a dead id
python -m council --port 9000 --reload
```

## Tests

```powershell
pip install -r requirements-dev.txt
python -m pytest
```

The suite covers the pure logic — artifact extraction, JSON recovery from model
replies, seat labelling, roster loading, payload clamping — plus every protocol
driven end to end against a scripted fake endpoint, so no test touches the
network. The protocol tests assert the failure behaviour the council promises:
a dead seat never ends a session, a failed leader hands the verdict to the
fastest seat that did answer, and the handoff chain re-routes past a seat that
drops the ticket.

## Layout

| Path | What it is |
| --- | --- |
| `council/config.py` | Seats, ranks, the model catalog, `.env` and `council.json` loading |
| `council/client.py` | NVIDIA OpenAI-compatible streaming, thinking kwargs, truncation guard |
| `council/runtime.py` | `Ctx` — the verbs every protocol is built from (speak, fan out, stage) |
| `council/patterns.py` | The 11 protocols and their prompts |
| `council/protocol.py` | Runs a protocol, emits the event stream |
| `council/server.py` | FastAPI: config, model list, NDJSON deliberation stream, transcripts |
| `council/static/` | The UI: HUD page, protocol diagrams, live council floor |
| `tests/` | pytest suite, no network |
| `transcripts/` | Every session, saved as JSON + Markdown |

## Notes

- **Thinking models.** Seats flagged `thinking` send NVIDIA's
  `chat_template_kwargs.enable_thinking` plus a `reasoning_budget`; their chain
  of thought arrives on `reasoning_content` and is shown separately from the
  answer. A seat whose model rejects those knobs is retried once without them
  rather than dropped from the session.
- **Truncation.** If a model spends its whole token budget reasoning, NIM mirrors
  the chain of thought into `content`. That is caught and reported as
  "token limit hit" instead of being passed off as an answer.
- **Failures are contained.** One seat erroring does not end the session; its
  card shows the error and the council continues without it. If the leader
  itself fails, the fastest seat that already answered writes the verdict.
- **Concurrency.** At most 6 seats stream at once. Fanning a full roster out
  unthrottled is the quickest way to trip the per-key rate limit, and a 429
  costs a whole seat's turn.
- **Cost and time.** 12 seats under Debate is ~25 model calls; fan-out is 13.
  The footer reports calls and tokens for every session (estimated from
  characters when the endpoint does not report usage). Untick seats in the
  roster, or pick a cheaper protocol, when you just want a quick answer.
- **A session is capped at 15 minutes**, after which it is stopped and reported.

## Security

There is **no authentication on any route**. It binds `127.0.0.1` by default,
which is the only configuration you should treat as safe. Anyone who can reach
the port can spend your `NVIDIA_API_KEY`, and because the roster is sent by the
browser, they also choose which models it is spent on. `max_tokens`,
`reasoning_budget`, `temperature` and `top_p` are clamped server-side to bound
the damage, but that is a backstop, not a control. Passing `--host 0.0.0.0`
prints a warning; do it only on a network you trust.

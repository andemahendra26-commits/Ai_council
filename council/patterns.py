"""The eleven multi-agent coordination patterns the council can run under.

Each pattern is a function `run(ctx) -> final answer text`, driving the roster
through a different communication topology. Registered at the bottom.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from .config import Seat
from .runtime import STYLE, Ctx, extract_json, is_usable

# --- JSON contracts (kept out of f-strings so braces stay literal) ----------

J_ASSIGN = """```json
{"plan": "one sentence", "assignments": [{"advisor": "A", "task": "what A must produce"}]}
```"""

J_ROUTE = """```json
{"advisor": "A", "why": "one sentence"}
```"""

J_HANDOFF = """```json
{"resolved": true, "handoff_to": null, "reason": "one sentence"}
```"""

J_REVIEW = """```json
{"verdict": [{"advisor": "A", "accept": false, "feedback": "what must change"}]}
```"""

J_STREAMS = """```json
{"streams": [{"title": "...", "goal": "...", "lead": "A", "workers": ["B"]}]}
```"""

J_SWARM = """```json
{"done": false, "next": "B", "handoff_note": "what B should pick up and why"}
```"""

J_EVENTS = """```json
{"events": [{"topic": "risk.assess", "payload": "what the handler must decide"}]}
```"""

J_EMIT = """```json
{"emit": [{"topic": "cost.model", "payload": "what still needs deciding"}]}
```"""


def _adv(ctx: Ctx, seat: Seat, extra: str = "") -> str:
    # A seat's persona, when it has one, goes in right after its standing, so
    # the flavour colours the whole turn rather than trailing the instructions.
    persona = f" {seat.persona.strip()}" if seat.persona and seat.persona.strip() else ""
    return (
        f"{ctx.rank_brief(seat)}{persona} The council exists to answer one question as "
        f"well as it can possibly be answered. {extra} {STYLE}"
    )


def _chair(ctx: Ctx, role: str) -> str:
    return (
        "You are the Council Leader, chairing an AI council of ministers (senior seats) "
        f"and members. {role} {STYLE}"
    )


async def _verdict(ctx: Ctx, system: str, user: str, title: str = "Verdict") -> str:
    await ctx.open_round("verdict", title, solo=True)
    text = await ctx.speak(ctx.chair, "verdict", system, user)
    await ctx.close_round("verdict")

    if is_usable(text):
        return text

    # The leader failed outright, or burned its whole budget without ever
    # answering — the council must still hand back a real verdict, so the
    # fastest seat that has already answered successfully this session steps
    # in and takes the same brief.
    fallback = ctx.fastest_seat(exclude=ctx.chair.id)
    if not fallback:
        return text  # nothing else has ever answered — nothing left to fall back to

    await ctx.note(
        f"The Leader ({ctx.chair.name}) failed to produce a usable verdict — "
        f"{fallback.name} is stepping in instead.",
        "verdict",
    )
    await ctx.open_round("verdict-fallback", f"Verdict — {fallback.name} stands in for the Leader", solo=True)
    fallback_text = await ctx.speak(fallback, "verdict-fallback", system, user)
    await ctx.close_round("verdict-fallback")
    return fallback_text if is_usable(fallback_text) else (fallback_text or text)


FINAL_SHAPE = (
    "Write exactly these sections: **Verdict** (the direct answer, 2-4 sentences, no "
    "hedging); **Reasoning** (why it wins, citing the load-bearing arguments and who "
    "made them); **Where the council split** (the real disagreements and how you "
    "resolved each — say plainly who was wrong and why); **Confidence** (high/medium/low, "
    "one sentence, plus the one fact that would change your answer). You are the "
    "decision-maker, not a summariser: popularity is not evidence."
)


# --- 1. Orchestration -------------------------------------------------------

async def run_orchestration(ctx: Ctx) -> str:
    plan = await ctx.stage(
        "plan",
        "Step 1 — Orchestrator decomposes the task",
        [(
            ctx.chair,
            _chair(ctx, "You are the orchestrator. Split the question into independent "
                        "subtasks and assign exactly one to each seat, playing to the "
                        "model each is running on. Every seat gets work."),
            f"QUESTION:\n\n{ctx.question}\n\nTHE COUNCIL:\n{ctx.roster_text()}\n\n"
            f"Give one short paragraph of plan, then this JSON block:\n{J_ASSIGN}",
        )],
        solo=True,
    )
    parsed = extract_json(plan.get(ctx.chair.id, "")) or {}
    tasks: dict[str, str] = {}
    for row in parsed.get("assignments", []):
        seat = ctx.by_label(row.get("advisor"))
        if seat and seat.id not in tasks:
            tasks[seat.id] = str(row.get("task", "")).strip()
    for seat in ctx.seats:  # nobody sits idle if the orchestrator under-assigned
        tasks.setdefault(seat.id, "Answer the question in full from your own angle.")
    await ctx.note(
        "Assignments: " + " · ".join(
            f"{ctx.label(s)}: {tasks[s.id][:70]}" for s in ctx.seats
        ),
        "work",
    )

    work = await ctx.stage(
        "work",
        "Step 2 — Workers execute in parallel",
        [(
            s,
            _adv(ctx, s, "The orchestrator has assigned you one subtask. Do only that "
                         "subtask, completely. Do not answer the whole question."),
            f"OVERALL QUESTION:\n\n{ctx.question}\n\nYOUR ASSIGNED SUBTASK:\n\n{tasks[s.id]}",
        ) for s in ctx.seats],
    )

    return await _verdict(
        ctx,
        _chair(ctx, "Your workers have returned. Assemble their output into the answer, "
                    "fixing any gap or contradiction between them. " + FINAL_SHAPE),
        f"QUESTION:\n\n{ctx.question}\n\nYOUR PLAN:\n\n{plan.get(ctx.chair.id, '')}\n\n"
        f"WORKER OUTPUT:\n\n{ctx.block(work)}",
        "Step 3 — Orchestrator assembles",
    )


# --- 2. A2A -----------------------------------------------------------------

async def run_a2a(ctx: Ctx) -> str:
    sweeps = int(ctx.options.get("sweeps", 2))
    thread: list[dict[str, str]] = []

    for sweep in range(1, sweeps + 1):
        name = f"a2a{sweep}"
        await ctx.open_round(name, f"Sweep {sweep} — Seats message each other")
        for seat in ctx.seats:  # sequential: each agent must see what was just said
            said = await ctx.speak(
                seat,
                name,
                _adv(ctx, seat,
                     "There is no manager. You talk directly to the other seats. "
                     "Address them by name, answer what was put to you, challenge what "
                     "you think is wrong, and put a concrete question or claim to a "
                     "named seat. Move the group toward an answer — do not "
                     "summarise the thread."),
                f"QUESTION:\n\n{ctx.question}\n\nMESSAGE THREAD SO FAR:\n\n"
                f"{ctx.transcript(thread)}\n\nYour message to the group:",
            )
            if said:
                thread.append({"who": f"{ctx.label(seat)} — {seat.name}", "stage": name, "text": said})
        await ctx.close_round(name)

    return await _verdict(
        ctx,
        _chair(ctx, "The council talked among themselves without a manager. Record what "
                    "the exchange actually established. " + FINAL_SHAPE),
        f"QUESTION:\n\n{ctx.question}\n\nFULL THREAD:\n\n{ctx.transcript(thread)}",
        "Consensus record",
    )


# --- 3. Handoff -------------------------------------------------------------

async def run_handoff(ctx: Ctx) -> str:
    routed = await ctx.stage(
        "route",
        "Front desk — routing the question",
        [(
            ctx.chair,
            _chair(ctx, "You are the front desk. Route this question to the single "
                        "best-suited advisor. Two sentences, then the JSON."),
            f"QUESTION:\n\n{ctx.question}\n\nTHE COUNCIL:\n{ctx.roster_text()}\n\nJSON:\n{J_ROUTE}",
        )],
        solo=True,
    )
    choice = extract_json(routed.get(ctx.chair.id, "")) or {}
    current = ctx.by_label(choice.get("advisor")) or ctx.seats[0]

    seen: set[str] = set()
    answer, holder = "", current
    # `held` counts seats that actually worked the ticket; `attempt` counts
    # every seat it was offered to. A seat that errors out costs an attempt but
    # not a hop, so one dead model cannot spend the whole routing budget.
    max_hops = min(len(ctx.seats), 3)
    held = attempt = 0
    while held < max_hops and current is not None and current.id not in seen:
        attempt += 1
        seen.add(current.id)
        await ctx.note(f"Handed to {ctx.label(current)} — {current.name}", f"hop{attempt}")
        got = await ctx.stage(
            f"hop{attempt}",
            f"Hop {attempt} — {ctx.label(current)} holds the ticket",
            [(
                current,
                _adv(ctx, current,
                     "The ticket has been handed to you. If it is yours, answer it in "
                     "full and close it. If another seat is genuinely better placed, "
                     "answer what you can, then hand off — state what you have "
                     "established and what they must finish. End with the JSON block."),
                f"QUESTION:\n\n{ctx.question}\n\nOTHER SEATS:\n"
                f"{ctx.roster_text([s for s in ctx.seats if s.id != current.id])}\n\n"
                f"WHAT YOU WERE HANDED:\n\n{answer or '(the original question, unworked)'}\n\n"
                f"End with:\n{J_HANDOFF}",
            )],
            solo=True,
        )
        worked = got.get(current.id, "")
        # A terse reply is still a reply; only an outright error (speak returns
        # "") or an out-of-budget placeholder counts as the holder dropping it.
        if not is_usable(worked, min_chars=1):
            # The holder failed outright, or never reached an answer. Breaking
            # here would hand the leader an empty ticket and call it resolved,
            # so pass it to a seat that has not held it yet instead.
            nxt = next((s for s in ctx.seats if s.id not in seen), None)
            if nxt is None:
                break
            await ctx.note(
                f"{ctx.label(current)} did not answer - re-routing to {ctx.label(nxt)}.",
                f"hop{attempt}",
            )
            current = nxt
            continue

        held += 1
        answer, holder = worked, current
        decision = extract_json(answer) or {}
        nxt = ctx.by_label(decision.get("handoff_to"))
        if decision.get("resolved", True) or not nxt or nxt.id in seen:
            break
        current = nxt

    return await _verdict(
        ctx,
        _chair(ctx, f"The ticket was routed and finally resolved by {ctx.label(holder)}. "
                    "Close it out for the reader, dropping the routing JSON. " + FINAL_SHAPE),
        f"QUESTION:\n\n{ctx.question}\n\nHANDOFF CHAIN:\n\n{ctx.transcript()}",
        "Resolution",
    )


# --- 4. Sequential / Pipeline ----------------------------------------------

PIPELINE_ROLES = [
    ("Draft", "You are stage 1. Produce the first complete draft answer."),
    ("Correct", "You are stage 2. Fact-check and repair stage 1: fix errors, kill "
                "unsupported claims, fill the gaps. Output the improved answer in full."),
    ("Deepen", "You are stage 3. The answer is roughly right but shallow. Add the "
               "specifics, edge cases and trade-offs it is missing. Output it in full."),
    ("Tighten", "You are the last stage. Cut everything that does not earn its place, "
                "sharpen the recommendation. Output the final answer in full."),
]


async def run_pipeline(ctx: Ctx) -> str:
    carried = ""
    n = len(ctx.seats)
    for i, seat in enumerate(ctx.seats):
        # Spread the four roles evenly over however many seats there are — a long
        # roster must not become ten consecutive "tighten" passes.
        role, brief = PIPELINE_ROLES[min(i * len(PIPELINE_ROLES) // max(n, 1), len(PIPELINE_ROLES) - 1)]
        if i == n - 1:
            role, brief = PIPELINE_ROLES[-1]
        got = await ctx.stage(
            f"stage{i + 1}",
            f"Stage {i + 1} — {role} ({ctx.label(seat)})",
            [(
                seat,
                _adv(ctx, seat, brief + " Never reply with a diff or a critique: your "
                                "output is passed straight to the next stage and must "
                                "stand alone."),
                f"QUESTION:\n\n{ctx.question}\n\n"
                + (f"WHAT THE PREVIOUS STAGE HANDED YOU:\n\n{carried}" if carried
                   else "You are first — nothing has been written yet."),
            )],
            solo=True,
        )
        carried = got.get(seat.id) or carried

    return await _verdict(
        ctx,
        _chair(ctx, "You are final QA on a pipeline. The last stage's output is below. "
                    "Ship it — correct anything the pipeline broke. " + FINAL_SHAPE),
        f"QUESTION:\n\n{ctx.question}\n\nPIPELINE OUTPUT:\n\n{carried}",
        "Final QA",
    )


# --- 5. Parallel / Fan-out --------------------------------------------------

async def run_fanout(ctx: Ctx) -> str:
    answers = await ctx.stage(
        "fanout",
        "Fan-out — every advisor answers independently",
        [(
            s,
            _adv(ctx, s, "You are answering independently and in parallel with the "
                         "others. You cannot see their work. Give your own complete "
                         "answer and commit to a recommendation. ~400 words."),
            f"QUESTION:\n\n{ctx.question}",
        ) for s in ctx.seats],
    )
    return await _verdict(
        ctx,
        _chair(ctx, "Independent answers came back in parallel. Merge them into one. "
                    "Where they collide, decide. " + FINAL_SHAPE),
        f"QUESTION:\n\n{ctx.question}\n\nINDEPENDENT ANSWERS:\n\n{ctx.block(answers)}",
    )


# --- 6. Supervisor / Manager ------------------------------------------------

async def run_supervisor(ctx: Ctx) -> str:
    brief = await ctx.stage(
        "brief",
        "Step 1 — Manager writes the brief",
        [(
            ctx.chair,
            _chair(ctx, "You manage these specialists. Write the brief: what a good "
                        "answer must contain, and the specialist role each advisor "
                        "should take. Assign every advisor a distinct role."),
            f"QUESTION:\n\n{ctx.question}\n\nSPECIALISTS:\n{ctx.roster_text()}\n\n"
            f"Then this JSON:\n{J_ASSIGN}",
        )],
        solo=True,
    )
    brief_text = brief.get(ctx.chair.id, "")
    parsed = extract_json(brief_text) or {}
    roles = {}
    for row in parsed.get("assignments", []):
        seat = ctx.by_label(row.get("advisor"))
        if seat:
            roles[seat.id] = str(row.get("task", "")).strip()

    work = await ctx.stage(
        "work",
        "Step 2 — Specialists report",
        [(
            s,
            _adv(ctx, s, "Your manager assigned you a specialist role. Report against "
                         "the brief from that role only."),
            f"QUESTION:\n\n{ctx.question}\n\nMANAGER'S BRIEF:\n\n{brief_text}\n\n"
            f"YOUR ROLE:\n\n{roles.get(s.id, 'Take the angle the brief left uncovered.')}",
        ) for s in ctx.seats],
    )

    review = await ctx.stage(
        "review",
        "Step 3 — Manager reviews the work",
        [(
            ctx.chair,
            _chair(ctx, "Review each specialist's report against your brief. Be hard: "
                        "accept only what is actually usable, and send back anything "
                        "thin, wrong or off-brief with specific feedback."),
            f"BRIEF:\n\n{brief_text}\n\nREPORTS:\n\n{ctx.block(work)}\n\n"
            f"Short review per specialist, then:\n{J_REVIEW}",
        )],
        solo=True,
    )
    verdicts = (extract_json(review.get(ctx.chair.id, "")) or {}).get("verdict", [])
    redo = [
        (ctx.by_label(v.get("advisor")), str(v.get("feedback", "")))
        for v in verdicts
        if not v.get("accept", True)
    ]
    redo = [(s, f) for s, f in redo if s]

    if redo:
        await ctx.note(
            "Sent back for revision: " + ", ".join(ctx.label(s) for s, _ in redo), "revise"
        )
        revised = await ctx.stage(
            "revise",
            "Step 4 — Specialists revise",
            [(
                s,
                _adv(ctx, s, "Your manager rejected your report. Address the feedback "
                             "and resubmit in full."),
                f"QUESTION:\n\n{ctx.question}\n\nYOUR REPORT:\n\n{work.get(s.id, '')}\n\n"
                f"MANAGER'S FEEDBACK:\n\n{fb}",
            ) for s, fb in redo],
        )
        work.update({k: v for k, v in revised.items() if v})

    return await _verdict(
        ctx,
        _chair(ctx, "Your specialists have delivered. Write the answer you are "
                    "accountable for. " + FINAL_SHAPE),
        f"QUESTION:\n\n{ctx.question}\n\nBRIEF:\n\n{brief_text}\n\n"
        f"ACCEPTED WORK:\n\n{ctx.block(work)}",
        "Manager's answer",
    )


# --- 7. Debate / Critic -----------------------------------------------------

async def run_debate(ctx: Ctx) -> str:
    n = len(ctx.seats)
    openings = await ctx.stage(
        "opening",
        "Round 1 — Opening statements",
        [(
            s,
            _adv(ctx, s, f"You are one of {n} independent advisors. This is your opening "
                         "statement. Commit to a position; if it depends, say precisely "
                         "on what and then call it anyway. Say where you might be wrong — "
                         "the others will attack it. ~400 words."),
            f"QUESTION FOR THE COUNCIL:\n\n{ctx.question}",
        ) for s in ctx.seats],
    )

    critiques: dict[str, str] = {}
    if n > 1:
        critiques = await ctx.stage(
            "critique",
            "Round 2 — Cross-examination",
            [(
                s,
                _adv(ctx, s,
                     "Cross-examination. Write exactly three sections. "
                     "**Strongest point I missed** — the most valuable thing another "
                     "advisor said that you did not; name them and quote it (if truly "
                     "nothing, say so in one line). "
                     "**Where the others are wrong** — the most serious error or weak "
                     "assumption in the other openings; quote it, name them, say why it "
                     "fails. Attack reasoning, not style. "
                     "**My revised answer** — your final position, standing alone as a "
                     "complete answer. Change your mind where the argument warrants and "
                     "say what changed; hold your ground where it does not and say why "
                     "the objection fails."),
                f"QUESTION:\n\n{ctx.question}\n\nYOUR OPENING:\n\n{openings.get(s.id, '')}\n\n"
                f"THE OTHER SEATS' OPENINGS:\n\n{ctx.block(openings, skip=s.id)}",
            ) for s in ctx.seats],
        )

    return await _verdict(
        ctx,
        _chair(ctx, "The council opened and then cross-examined each other. " + FINAL_SHAPE),
        f"QUESTION:\n\n{ctx.question}\n\n=== ROUND 1 — OPENINGS ===\n\n"
        f"{ctx.block(openings)}\n\n=== ROUND 2 — CROSS-EXAMINATION ===\n\n"
        f"{ctx.block(critiques) if critiques else '(skipped)'}",
        "Round 3 — Verdict",
    )


# --- 8. Hierarchical --------------------------------------------------------

async def run_hierarchical(ctx: Ctx) -> str:
    if len(ctx.seats) < 3:
        return await run_supervisor(ctx)

    # The council's own hierarchy is the org chart: Leader → ministers → members.
    leads = ctx.ministers() or ctx.seats[: max(1, len(ctx.seats) // 3)]
    workers = [s for s in ctx.seats if s.id not in {l.id for l in leads}]

    brief = await ctx.stage(
        "brief",
        "Tier 1 — Leader sets the workstreams",
        [(
            ctx.chair,
            _chair(ctx, f"Give each of your {len(leads)} ministers one workstream: a "
                        "title and a goal, each covering a different part of the "
                        "question. Their members will do the digging."),
            f"QUESTION:\n\n{ctx.question}\n\nMINISTERS:\n{ctx.roster_text(leads)}\n\n"
            f"MEMBERS AVAILABLE TO THEM:\n{ctx.roster_text(workers) or '(none)'}\n\nThen:\n{J_STREAMS}",
        )],
        solo=True,
    )
    parsed = extract_json(brief.get(ctx.chair.id, "")) or {}
    by_lead = {}
    for row in parsed.get("streams", []):
        seat = ctx.by_label(row.get("lead"))
        if seat and seat.id not in by_lead:
            by_lead[seat.id] = (str(row.get("title", "")), str(row.get("goal", "")))

    streams = []
    for i, lead in enumerate(leads):
        title, goal = by_lead.get(lead.id, ("", ""))
        streams.append({
            "title": title or f"Workstream {i + 1}",
            "goal": goal or "Cover the question from your ministry's angle.",
            "lead": lead,
            "workers": workers[i :: len(leads)],  # deal the members round-robin
        })

    await ctx.note(
        " · ".join(
            f"{st['title']}: lead {ctx.label(st['lead'])}"
            + (f", workers {', '.join(ctx.label(w) for w in st['workers'])}" if st["workers"] else "")
            for st in streams
        ),
        "workers",
    )

    jobs = []
    for st in streams:
        for w in st["workers"]:
            jobs.append((
                w,
                _adv(ctx, w, f"You are a worker on the '{st['title']}' workstream, "
                             f"reporting to {ctx.label(st['lead'])}. Deliver only your "
                             "stream's piece, in depth."),
                f"QUESTION:\n\n{ctx.question}\n\nSTREAM GOAL:\n\n{st['goal']}",
            ))
    worker_out = await ctx.stage("workers", "Tier 3 — Workers deliver", jobs) if jobs else {}

    lead_out = await ctx.stage(
        "leads",
        "Tier 2 — Leads consolidate their stream",
        [(
            st["lead"],
            _adv(ctx, st["lead"], f"You lead the '{st['title']}' workstream. Consolidate "
                                  "your workers' output into one stream report for the "
                                  "director: findings, what you rejected, and the open "
                                  "risk you are escalating."),
            f"QUESTION:\n\n{ctx.question}\n\nSTREAM GOAL:\n\n{st['goal']}\n\n"
            f"YOUR WORKERS' OUTPUT:\n\n"
            f"{ctx.block(worker_out, st['workers']) if st['workers'] else '(you have no workers — do the work yourself)'}",
        ) for st in streams],
    )

    return await _verdict(
        ctx,
        _chair(ctx, "Your leads have reported up. Decide. " + FINAL_SHAPE),
        f"QUESTION:\n\n{ctx.question}\n\nSTREAM REPORTS:\n\n"
        f"{ctx.block(lead_out, [st['lead'] for st in streams])}",
        "Tier 1 — Director's decision",
    )


# --- 9. Swarm ---------------------------------------------------------------

async def run_swarm(ctx: Ctx) -> str:
    max_steps = int(ctx.options.get("max_steps", 5))
    current = ctx.seats[0]
    handoff = "You are first. Start the work."
    resolved = False

    for step in range(1, max_steps + 1):
        await ctx.note(f"{ctx.label(current)} picks up the task — {handoff[:120]}", f"swarm{step}")
        got = await ctx.stage(
            f"swarm{step}",
            f"Step {step} — {ctx.label(current)} has the task",
            [(
                current,
                _adv(ctx, current,
                     "This is a swarm: no manager, and you decide who works next. Do the "
                     "most valuable next piece of work yourself — do not plan, do not "
                     "delegate the thinking. Then either declare the task done, or hand "
                     "it to whichever advisor should take the next step and say exactly "
                     "what they must do. End with the JSON block."),
                f"QUESTION:\n\n{ctx.question}\n\nOTHER SEATS:\n"
                f"{ctx.roster_text([s for s in ctx.seats if s.id != current.id])}\n\n"
                f"WHY IT CAME TO YOU:\n\n{handoff}\n\n"
                f"WORK SO FAR:\n\n{ctx.transcript()}\n\nEnd with:\n{J_SWARM}",
            )],
            solo=True,
        )
        decision = extract_json(got.get(current.id, "")) or {}
        if decision.get("done"):
            resolved = True
            await ctx.note(f"{ctx.label(current)} declared the task done at step {step}.", f"swarm{step}")
            break
        nxt = ctx.by_label(decision.get("next"))
        if not nxt or nxt.id == current.id:
            nxt = ctx.seats[step % len(ctx.seats)]
        handoff = str(decision.get("handoff_note") or "Continue the work.")
        current = nxt

    return await _verdict(
        ctx,
        _chair(ctx, ("The swarm converged." if resolved else
                     f"The swarm ran out its {max_steps}-step budget without declaring done.")
               + " Write up what it produced, dropping the handoff JSON. " + FINAL_SHAPE),
        f"QUESTION:\n\n{ctx.question}\n\nSWARM TRACE:\n\n{ctx.transcript()}",
        "Swarm result",
    )


# --- 10. Blackboard / Shared state -----------------------------------------

async def run_blackboard(ctx: Ctx) -> str:
    board: list[str] = []

    posts = await ctx.stage(
        "post",
        "Pass 1 — Advisors post to the blackboard",
        [(
            s,
            _adv(ctx, s, "You write to a shared blackboard, not to a person. Post only "
                         "entries the others can build on, each on its own line, tagged "
                         "[FACT], [CLAIM], [RISK], [OPEN QUESTION] or [ANSWER]. No prose "
                         "around them."),
            f"QUESTION:\n\n{ctx.question}\n\nBLACKBOARD:\n\n(empty)",
        ) for s in ctx.seats],
    )
    for s in ctx.seats:
        if posts.get(s.id):
            board.append(f"[{ctx.label(s)}]\n{posts[s.id]}")

    passes = int(ctx.options.get("passes", 2))
    for p in range(2, passes + 1):
        current = "\n\n".join(board)
        updates = await ctx.stage(
            f"post{p}",
            f"Pass {p} — Advisors revise the shared board",
            [(
                s,
                _adv(ctx, s, "Read the whole blackboard. Resolve the open questions you "
                             "can, contradict entries you believe are wrong (quote the "
                             "entry and say why), and add what is still missing. Same "
                             "tagged-line format. Do not repeat entries already there."),
                f"QUESTION:\n\n{ctx.question}\n\nBLACKBOARD:\n\n{current}",
            ) for s in ctx.seats],
        )
        for s in ctx.seats:
            if updates.get(s.id):
                board.append(f"[{ctx.label(s)} — pass {p}]\n{updates[s.id]}")

    return await _verdict(
        ctx,
        _chair(ctx, "The council worked through a shared blackboard rather than talking "
                    "to each other. Read the whole board and write the answer it "
                    "supports, discarding entries that were contradicted. " + FINAL_SHAPE),
        f"QUESTION:\n\n{ctx.question}\n\nBLACKBOARD:\n\n" + "\n\n".join(board),
        "Board resolution",
    )


# --- 11. Event-driven -------------------------------------------------------

async def run_event_driven(ctx: Ctx) -> str:
    bus = await ctx.stage(
        "bus",
        "Bus — the question is decomposed into events",
        [(
            ctx.chair,
            _chair(ctx, "You are the event bus. Turn the question into 3-5 independent "
                        "events, each a topic plus a payload stating exactly what its "
                        "handler must decide. Nothing else."),
            f"QUESTION:\n\n{ctx.question}\n\nEmit:\n{J_EVENTS}",
        )],
        solo=True,
    )
    events = [
        {"topic": str(e.get("topic", "event")), "payload": str(e.get("payload", ""))}
        for e in (extract_json(bus.get(ctx.chair.id, "")) or {}).get("events", [])
    ][:6]
    if not events:
        events = [{"topic": "question.answer", "payload": ctx.question}]

    handled: list[str] = []
    waves = int(ctx.options.get("waves", 2))
    for wave in range(1, waves + 1):
        if not events:
            break
        await ctx.note(
            f"Wave {wave}: dispatching " + ", ".join(f"`{e['topic']}`" for e in events), f"wave{wave}"
        )
        jobs, owners = [], []
        for i, ev in enumerate(events):
            seat = ctx.seats[i % len(ctx.seats)]
            owners.append((seat, ev))
            jobs.append((
                seat,
                _adv(ctx, seat, f"You are the subscriber for the `{ev['topic']}` event. "
                                "Handle only this event. If handling it reveals something "
                                "another handler must decide, emit follow-up events; "
                                "otherwise emit none. End with the JSON block."),
                f"ORIGINAL QUESTION (context only):\n\n{ctx.question}\n\n"
                f"EVENT `{ev['topic']}`:\n\n{ev['payload']}\n\nEnd with:\n{J_EMIT}",
            ))
        # One seat may own several events in a wave; run them as separate rounds
        # only when they collide, so the UI keeps one card per handler.
        results: dict[str, str] = {}
        seen_seats: set[str] = set()
        batch, overflow = [], []
        for job in jobs:
            (overflow if job[0].id in seen_seats else batch).append(job)
            seen_seats.add(job[0].id)
        results.update(await ctx.stage(f"wave{wave}", f"Wave {wave} — Handlers react", batch))
        if overflow:
            results.update(await ctx.stage(f"wave{wave}b", f"Wave {wave} — Handlers react (cont.)", overflow))

        next_events: list[dict[str, str]] = []
        for seat, ev in owners:
            text = results.get(seat.id, "")
            if text:
                handled.append(f"### `{ev['topic']}` — handled by {ctx.label(seat)}\n\n{text}")
            for new in (extract_json(text) or {}).get("emit", [])[:2]:
                topic = str(new.get("topic", "")).strip()
                if topic and topic not in {e["topic"] for e in events}:
                    next_events.append({"topic": topic, "payload": str(new.get("payload", ""))})
        events = next_events[:4]

    return await _verdict(
        ctx,
        _chair(ctx, "Every event on the bus has been handled. Reduce the event log into "
                    "the answer, dropping the emit JSON. " + FINAL_SHAPE),
        f"QUESTION:\n\n{ctx.question}\n\nEVENT LOG:\n\n" + "\n\n".join(handled),
        "Reducer — final state",
    )


# --- registry ---------------------------------------------------------------

@dataclass
class Pattern:
    id: str
    name: str
    what: str
    best_for: str
    shape: str  # tiny ascii topology sketch for the picker
    run: Callable[[Ctx], Awaitable[str]]
    recommended: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "what": self.what,
            "best_for": self.best_for, "shape": self.shape, "recommended": self.recommended,
        }


PATTERNS: dict[str, Pattern] = {
    p.id: p
    for p in [
        Pattern("orchestration", "Orchestration",
                "The leader splits the task and assigns each seat its own subtask.",
                "Most common production pattern", "leader → ⟨all seats⟩ → leader",
                run_orchestration, recommended=True),
        Pattern("a2a", "A2A (Agent-to-Agent)",
                "Seats message each other directly, with no manager in the loop.",
                "Independent agents collaborating", "A ⇄ B ⇄ C ⇄ D", run_a2a),
        Pattern("handoff", "Handoff",
                "A router picks an owner; each agent either resolves or hands the ticket on.",
                "Customer support, routing", "route → A → B → done", run_handoff),
        Pattern("pipeline", "Sequential / Pipeline",
                "Draft → correct → deepen → tighten, each agent reworking the last output.",
                "Fixed workflows", "A → B → C → D", run_pipeline),
        Pattern("fanout", "Parallel / Fan-out",
                "Every seat answers independently at once, then the leader merges them.",
                "Fastest with a large roster", "⟨all seats⟩ → leader", run_fanout, recommended=True),
        Pattern("supervisor", "Supervisor / Manager",
                "The leader briefs specialists, reviews their work and sends back what is thin.",
                "Complex tasks", "leader ⇄ ⟨all seats⟩", run_supervisor),
        Pattern("debate", "Debate / Critic",
                "Openings, then every seat attacks the others, then the leader rules.",
                "Reasoning & quality — 2x the rounds, 2x the wait", "⟨all⟩ ⇄ ⟨all⟩ → leader",
                run_debate),
        Pattern("hierarchical", "Hierarchical",
                "Leader → ministers run workstreams → members do the digging, consolidating up.",
                "Large agent systems", "leader → ministers → members", run_hierarchical),
        Pattern("swarm", "Swarm",
                "Whoever holds the task does a piece and picks who takes it next.",
                "Dynamic workflows", "A ↝ C ↝ B ↝ done", run_swarm),
        Pattern("blackboard", "Blackboard / Shared state",
                "Agents never address each other — they read and write one shared board.",
                "Collaborative systems", "⟨A B C D⟩ ⇄ [board]", run_blackboard),
        Pattern("event_driven", "Event-driven",
                "The question becomes events; handlers react and can emit further events.",
                "Large asynchronous systems", "bus → handlers ↻ bus", run_event_driven),
    ]
}

DEFAULT_PATTERN = "fanout"

"""FastAPI app: serves the council UI and streams deliberations as NDJSON."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .buildzip import extract_files, is_substantial, wants_build
from .client import MissingAPIKey, list_models, make_client
from .config import ROOT, load_config, seats_from_payload
from .patterns import DEFAULT_PATTERN, PATTERNS
from .protocol import deliberate

load_dotenv(ROOT / ".env")

STATIC = Path(__file__).resolve().parent / "static"
TRANSCRIPTS = ROOT / "transcripts"

app = FastAPI(title="Alfredo Council")


@app.middleware("http")
async def no_cache_static(request: Request, call_next):
    # This app's own JS/CSS changes across restarts during development; a
    # browser caching an old tree.js/index.html silently would be far more
    # confusing than the cost of always revalidating a few small files.
    response = await call_next(request)
    if request.url.path.startswith("/static/") or request.url.path == "/":
        response.headers["Cache-Control"] = "no-cache"
    return response


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/api/config")
async def api_config() -> JSONResponse:
    cfg = load_config()
    return JSONResponse({**cfg.to_dict(), "key_present": _key_present()})


@app.get("/api/patterns")
async def api_patterns() -> JSONResponse:
    return JSONResponse(
        {"patterns": [p.to_dict() for p in PATTERNS.values()], "default": DEFAULT_PATTERN}
    )


@app.get("/api/models")
async def api_models() -> JSONResponse:
    """Live list of model IDs this key can reach, so seats can be re-pointed."""
    try:
        client = make_client(load_config().base_url)
    except MissingAPIKey as exc:
        return JSONResponse({"error": str(exc), "models": []}, status_code=400)
    try:
        return JSONResponse({"models": await list_models(client)})
    except Exception as exc:
        return JSONResponse({"error": f"{type(exc).__name__}: {exc}", "models": []}, status_code=502)
    finally:
        await client.close()


@app.post("/api/deliberate")
async def api_deliberate(request: Request) -> StreamingResponse:
    body: dict[str, Any] = await request.json()
    question = (body.get("question") or "").strip()
    cfg = load_config()

    if not question:
        return _error_stream("Ask the council something first.")
    try:
        client = make_client(cfg.base_url)
    except MissingAPIKey as exc:
        return _error_stream(str(exc))

    seats = seats_from_payload(body.get("seats"), cfg)
    if not seats:
        return _error_stream("No council members are enabled.")
    chair_payload = dict(body.get("chair") or cfg.chair.to_dict())
    chair_payload["enabled"] = True  # the chair always sits, whatever the roster says
    chair = seats_from_payload([chair_payload], cfg)[0]
    pattern = body.get("pattern") or DEFAULT_PATTERN
    if pattern not in PATTERNS:
        return _error_stream(f"Unknown coordination pattern: {pattern!r}")
    options = body.get("options") or {}
    save = bool(body.get("save", True))

    async def stream() -> AsyncIterator[bytes]:
        try:
            async for event in deliberate(client, question, seats, chair, pattern, options):
                if event.get("type") == "run_end":
                    if save:
                        try:
                            event["saved_to"] = _save_transcript(event["transcript"])
                        except OSError as exc:
                            event["saved_to"] = f"(not saved: {exc})"
                    # Only offer a zip when the question actually asked for something
                    # to be built — not for a plain-text answer that quotes a snippet.
                    if wants_build(question):
                        files = extract_files(event["transcript"].get("verdict", ""))
                        if files and is_substantial(files):
                            event["build_files"] = files
                yield (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8")
        finally:
            await client.close()

    return StreamingResponse(
        stream(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


def _key_present() -> bool:
    import os

    return bool(os.environ.get("NVIDIA_API_KEY"))


def _error_stream(message: str) -> StreamingResponse:
    payload = json.dumps({"type": "fatal", "message": message}) + "\n"

    async def one() -> AsyncIterator[bytes]:
        yield payload.encode("utf-8")

    return StreamingResponse(one(), media_type="application/x-ndjson")


def _save_transcript(transcript: dict[str, Any]) -> str:
    """Write the deliberation to transcripts/ as both JSON and Markdown."""
    TRANSCRIPTS.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = re.sub(r"[^a-z0-9]+", "-", transcript["question"].lower())[:48].strip("-") or "question"
    base = TRANSCRIPTS / f"{stamp}-{slug}"

    base.with_suffix(".json").write_text(
        json.dumps(transcript, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    pattern = transcript.get("pattern") or {}
    lines = [f"# Council: {transcript['question']}", ""]
    lines += [f"**Pattern:** {pattern.get('name', '?')} — {pattern.get('what', '')}", ""]
    lines += ["| Seat | Model |", "| --- | --- |"]
    lines += [f"| {s['label']} — {s['name']} | `{s['model']}` |" for s in transcript["seats"]]
    lines += [f"| Chair — {transcript['chair']['name']} | `{transcript['chair']['model']}` |", ""]
    lines += ["---", "", "## Verdict", "", transcript["verdict"] or "_(no verdict)_", ""]
    lines += ["---", "", "## Full record", ""]
    for entry in transcript.get("log", []):
        if entry.get("text"):
            lines += [f"### {entry['who']}  ·  _{entry['stage']}_", "", entry["text"], ""]

    base.with_suffix(".md").write_text("\n".join(lines), encoding="utf-8")
    return str(base.with_suffix(".md").relative_to(ROOT))

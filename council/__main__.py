"""Start the council web app:  python -m council  [--port 8000] [--no-reload]"""

from __future__ import annotations

import argparse
import os
import threading
import webbrowser

import uvicorn
from dotenv import load_dotenv

from .config import ROOT, load_config


def main() -> None:
    load_dotenv(ROOT / ".env")

    parser = argparse.ArgumentParser(prog="council", description="Run the AI council web app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="auto-reload on code changes")
    parser.add_argument("--no-open", action="store_true", help="don't open a browser")
    args = parser.parse_args()

    cfg = load_config()
    url = f"http://{'127.0.0.1' if args.host == '0.0.0.0' else args.host}:{args.port}"

    print(f"\n  AI COUNCIL  ·  {url}")
    print(f"  {cfg.chair.name} chairs · {len(cfg.ministers())} ministers · "
          f"{len([s for s in cfg.enabled_seats() if s.rank != 'minister'])} members · "
          f"{len([s for s in cfg.seats if not s.enabled])} benched\n")
    if not os.environ.get("NVIDIA_API_KEY"):
        print("  !  NVIDIA_API_KEY is not set - put your key in .env before convening.\n")

    if not args.no_open:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    uvicorn.run(
        "council.server:app", host=args.host, port=args.port, reload=args.reload, log_level="warning"
    )


if __name__ == "__main__":
    main()

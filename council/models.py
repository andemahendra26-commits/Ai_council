"""List the models this API key can actually reach:  python -m council.models [filter]"""

from __future__ import annotations

import asyncio
import sys

from dotenv import load_dotenv

from .client import MissingAPIKey, list_models, make_client
from .config import ROOT, load_config


async def _main() -> int:
    load_dotenv(ROOT / ".env")
    needle = sys.argv[1].lower() if len(sys.argv) > 1 else ""

    cfg = load_config()
    try:
        client = make_client(cfg.base_url)
    except MissingAPIKey as exc:
        print(exc)
        return 1

    try:
        ids = await list_models(client)
    finally:
        await client.close()

    shown = [m for m in ids if needle in m.lower()]
    for model_id in shown:
        print(model_id)

    configured = {s.model for s in cfg.seats} | {cfg.chair.model}
    missing = sorted(configured - set(ids))
    print(f"\n{len(shown)}/{len(ids)} models listed.")
    if missing:
        print("\nConfigured but NOT in the catalog for this key:")
        for model_id in missing:
            print(f"  - {model_id}")
        print("Re-point those seats in council.json or from the web UI.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))

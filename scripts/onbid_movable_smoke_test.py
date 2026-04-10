#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

ROOT = Path("/home/ubuntu/auction-bot")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.onbid_movable import OnbidMovableAlertConfig, fetch_movable_candidates


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fp:
        return yaml.safe_load(fp)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    args = parser.parse_args()

    cfg = load_config(Path(args.config))
    raw = dict(cfg.get("onbid_movable_alerts") or {})
    config = OnbidMovableAlertConfig(**raw)

    print(f"[onbid_movable] enabled={config.enabled}")
    print(f"[onbid_movable] notes={config.notes}")
    print(f"[onbid_movable] start_url={config.start_url}")
    print(f"[onbid_movable] list_url={config.list_url or '(unset)'}")
    print(f"[onbid_movable] data_url_candidate={config.data_url_candidate or '(unset)'}")
    print(f"[onbid_movable] alternate_urls={config.alternate_urls or []}")

    try:
        items = fetch_movable_candidates(config)
    except Exception as exc:
        print(f"[onbid_movable] smoke_test_failed={type(exc).__name__}: {exc}")
        return 1

    print(f"[onbid_movable] matched_items={len(items)}")
    for idx, item in enumerate(items[:10], start=1):
        print(f"[onbid_movable] item#{idx}: {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

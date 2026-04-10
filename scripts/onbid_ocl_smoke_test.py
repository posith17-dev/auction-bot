#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

ROOT = Path("/home/ubuntu/auction-bot")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.onbid_movable import fetch_candidates_from_url_with_playwright


DEFAULT_URL = "https://medu.onbid.co.kr/mo/cta/cltr/cltrSearch.do?searchType=OCL"


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fp:
        return yaml.safe_load(fp)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    parser.add_argument("--url", default=DEFAULT_URL)
    args = parser.parse_args()

    cfg = load_config(Path(args.config))
    raw = dict(cfg.get("onbid_movable_alerts") or {})

    print(f"[onbid_ocl] url={args.url}")
    print(f"[onbid_ocl] include_categories={raw.get('include_categories') or []}")
    print(f"[onbid_ocl] keywords={raw.get('keywords') or []}")

    try:
        items = fetch_candidates_from_url_with_playwright(
            args.url,
            max_items=int(raw.get("max_items") or 10),
            keywords=list(raw.get("keywords") or []),
            exclude_keywords=list(raw.get("exclude_keywords") or []),
            include_categories=list(raw.get("include_categories") or []),
            exclude_categories=list(raw.get("exclude_categories") or []),
        )
    except Exception as exc:
        print(f"[onbid_ocl] smoke_test_failed={type(exc).__name__}: {exc}")
        return 1

    print(f"[onbid_ocl] matched_items={len(items)}")
    for idx, item in enumerate(items[:10], start=1):
        print(f"[onbid_ocl] item#{idx}: {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

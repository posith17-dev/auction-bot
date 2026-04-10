#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from urllib.parse import urlencode

import requests


BASE_URL = "https://medu.onbid.co.kr/mo/cta/cltr/data/cltrSearchList.do"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
)


@dataclass
class ProbePreset:
    name: str
    params: dict[str, str]


PRESETS = {
    "ocl": ProbePreset(
        name="자동차/운송장비(온카랜드)",
        params={
            "searchOrderBy": "08",
            "searchBegnDtm": "2026-03-01",
            "searchClsDtm": "2026-04-30",
            "collateralGbnCd": "0002",
            "searchType": "OCL",
            "searchCtgrId1": "0002",
            "searchCtgrId2": "12100",
            "searchCtgrId3": "12101,12102,12103,12105",
        },
    ),
    "machine": ProbePreset(
        name="물품(기계)",
        params={
            "searchOrderBy": "08",
            "searchBegnDtm": "2026-03-01",
            "searchClsDtm": "2026-04-30",
            "collateralGbnCd": "0003",
            "bizDvsnCd": "0003",
        },
    ),
    "other": ProbePreset(
        name="물품(기타)",
        params={
            "searchOrderBy": "08",
            "searchBegnDtm": "2026-03-01",
            "searchClsDtm": "2026-04-30",
            "collateralGbnCd": "0004",
            "bizDvsnCd": "0004",
        },
    ),
}


def fetch_json(params: dict[str, str]) -> dict:
    resp = requests.get(
        BASE_URL,
        params=params,
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--preset",
        choices=sorted(PRESETS),
        nargs="*",
        default=["ocl", "machine", "other"],
    )
    args = parser.parse_args()

    for key in args.preset:
        preset = PRESETS[key]
        print(f"[onbid_data_probe] preset={key} name={preset.name}")
        print(f"[onbid_data_probe] url={BASE_URL}?{urlencode(preset.params)}")
        try:
            data = fetch_json(preset.params)
        except Exception as exc:
            print(f"[onbid_data_probe] error={type(exc).__name__}: {exc}")
            continue

        result = data.get("result", {})
        items = list(result.get("rtnList") or [])
        print(f"[onbid_data_probe] count={len(items)}")
        for idx, item in enumerate(items[:5], start=1):
            sample = {
                "title": item.get("cltrNm"),
                "category": item.get("ctgrNm") or item.get("ctgrFullNm"),
                "min_bid_price": item.get("minBidPrc"),
                "cltr_no": item.get("cltrNo"),
                "pbct_no": item.get("pbctNo"),
            }
            print(f"[onbid_data_probe] item#{idx}={json.dumps(sample, ensure_ascii=False)}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

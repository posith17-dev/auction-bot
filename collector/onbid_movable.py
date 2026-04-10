#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass
class OnbidMovableAlertConfig:
    enabled: bool = False
    notes: str = ""
    telegram_enabled: bool = False
    telegram_chat_id: str = ""
    start_url: str = "https://www.onbid.co.kr"
    list_url: str = ""
    data_url_candidate: str = ""
    alternate_urls: list[str] | None = None
    json_data_url: str = "https://medu.onbid.co.kr/mo/cta/cltr/data/cltrSearchList.do"
    json_presets: list[str] | None = None
    max_items: int = 10
    keywords: list[str] | None = None
    exclude_keywords: list[str] | None = None
    include_categories: list[str] | None = None
    exclude_categories: list[str] | None = None


JSON_PRESETS: dict[str, dict[str, str]] = {
    "ocl": {
        "searchOrderBy": "08",
        "searchBegnDtm": "2026-03-01",
        "searchClsDtm": "2026-04-30",
        "collateralGbnCd": "0002",
        "searchType": "OCL",
        "searchCtgrId1": "0002",
        "searchCtgrId2": "12100",
        "searchCtgrId3": "12101,12102,12103,12105",
    },
    "machine": {
        "searchOrderBy": "08",
        "searchBegnDtm": "2026-03-01",
        "searchClsDtm": "2026-04-30",
        "collateralGbnCd": "0003",
        "bizDvsnCd": "0003",
    },
    "other": {
        "searchOrderBy": "08",
        "searchBegnDtm": "2026-03-01",
        "searchClsDtm": "2026-04-30",
        "collateralGbnCd": "0004",
        "bizDvsnCd": "0004",
    },
}

PRESET_CATEGORY_LABELS = {
    "ocl": "자동차/운송장비",
    "machine": "물품(기계)",
    "other": "물품(기타)",
}

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
)


def _matches_keywords(text: str, keywords: list[str], exclude_keywords: list[str]) -> bool:
    if exclude_keywords and any(_contains_keyword(text, keyword) for keyword in exclude_keywords):
        return False
    if not keywords:
        return True
    return any(_contains_keyword(text, keyword) for keyword in keywords)


def _contains_keyword(text: str, keyword: str) -> bool:
    if not keyword:
        return False
    if re.search(r"[가-힣]", keyword):
        pattern = rf"(?<![가-힣A-Za-z0-9]){re.escape(keyword)}(?![가-힣A-Za-z0-9])"
        return re.search(pattern, text) is not None
    return keyword in text


def _matches_categories(category: str, include_categories: list[str], exclude_categories: list[str]) -> bool:
    if exclude_categories and any(name and name in category for name in exclude_categories):
        return False
    if not include_categories:
        return True
    return any(name and name in category for name in include_categories)


def filter_candidate_items(
    items: list[dict[str, Any]],
    *,
    keywords: list[str] | None,
    exclude_keywords: list[str] | None,
    include_categories: list[str] | None,
    exclude_categories: list[str] | None,
) -> list[dict[str, Any]]:
    keywords = keywords or []
    exclude_keywords = exclude_keywords or []
    include_categories = include_categories or []
    exclude_categories = exclude_categories or []
    matched = []
    for item in items:
        haystack = " ".join(
            [
                str(item.get("title") or ""),
                str(item.get("category") or ""),
                str(item.get("raw_text") or ""),
            ]
        )
        category = str(item.get("category") or "")
        if not _matches_categories(category, include_categories, exclude_categories):
            continue
        if not _matches_keywords(haystack, keywords, exclude_keywords):
            continue
        matched.append(item)
    return matched


def _build_detail_url(detail_args: list[str]) -> str:
    if len(detail_args) < 6:
        return ""
    cltr_no, plnm_no, pbct_no, scrn_grp_cd, pbct_cdtn_no, cltr_hstr_no = detail_args[:6]
    return (
        "https://medu.onbid.co.kr/mo/cta/cltr/baseInfo.do"
        f"?cltrNo={cltr_no}"
        f"&plnmNo={plnm_no}"
        f"&pbctNo={pbct_no}"
        f"&scrnGrpCd={scrn_grp_cd}"
        f"&pbctCdtnNo={pbct_cdtn_no}"
        f"&cltrHstrNo={cltr_hstr_no}"
    )


def _build_detail_args_from_json_item(item: dict[str, Any]) -> list[str]:
    fields = [
        item.get("cltrNo"),
        item.get("plnmNo"),
        item.get("pbctNo"),
        item.get("scrnGrpCd"),
        item.get("pbctCdtnNo"),
        item.get("cltrHstrNo"),
    ]
    if any(value in (None, "") for value in fields):
        return []
    return [str(value) for value in fields]


def _extract_onclick_args(onclick: str) -> list[str]:
    match = re.search(r"clrtDetail\((.*)\)", onclick)
    if not match:
        return []
    inner = match.group(1)
    return [part.strip().strip("'").strip('"') for part in inner.split(",")]


def _extract_price(text: str) -> int | None:
    match = re.search(r"최저입찰가\s*:?\s*([\d,]+)원", text)
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


def _normalize_row_text(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _parse_movable_items(page) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    rows = page.locator(".stuff-search-list li.list-group-item")
    count = rows.count()
    for idx in range(count):
        row = rows.nth(idx)
        text = row.inner_text().strip()
        if not text:
            continue
        lines = _normalize_row_text(text)
        link = row.locator("a.list-group-item-link").first
        if link.count() == 0:
            continue
        onclick = link.get_attribute("onclick") or ""
        detail_args = _extract_onclick_args(onclick)
        category = lines[1] if len(lines) > 1 else ""
        title = lines[2] if len(lines) > 2 else (lines[0] if lines else "")
        rank = lines[0] if lines else ""
        min_bid_price = _extract_price(text)
        items.append(
            {
                "title": title,
                "category": category,
                "rank_label": rank,
                "min_bid_price": min_bid_price,
                "raw_text": text,
                "source_url": page.url,
                "detail_args": detail_args,
                "detail_onclick": onclick,
                "detail_url": _build_detail_url(detail_args),
            }
        )
    return items


def normalize_onbid_movable_listing(item: dict[str, Any], *, search_name: str) -> dict[str, Any]:
    detail_args = list(item.get("detail_args") or [])
    detail_key = "-".join(detail_args) if detail_args else str(item.get("title") or "")
    title = str(item.get("title") or "").strip()
    category = str(item.get("category") or "").strip()
    rank_label = str(item.get("rank_label") or "").strip()
    return {
        "source": "onbid_movable",
        "listing_id": f"onbid_movable:{detail_key}",
        "search_name": search_name,
        "title": title,
        "address": "",
        "region": "온비드",
        "property_type": category or "동산/기타자산",
        "appraisal_price": None,
        "min_bid_price": item.get("min_bid_price"),
        "discount_rate": None,
        "discount_score": None,
        "bid_round": None,
        "round_score": None,
        "opportunity_score": None,
        "price_bucket": "onbid_movable",
        "auction_date": None,
        "area_m2": None,
        "status": rank_label,
        "source_url": item.get("detail_url") or item.get("source_url") or "",
        "raw_json": json.dumps(item, ensure_ascii=False),
    }


def _fetch_json(url: str, params: dict[str, str]) -> dict[str, Any]:
    full_url = f"{url}?{urlencode(params, doseq=True)}"
    req = Request(full_url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _normalize_json_items(
    items: list[dict[str, Any]],
    *,
    preset_name: str,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    parent_category = PRESET_CATEGORY_LABELS.get(preset_name, preset_name)
    for item in items:
        detail_args = _build_detail_args_from_json_item(item)
        leaf_category = str(item.get("ctgrNm") or item.get("ctgrFullNm") or "").strip()
        category = f"{parent_category} / {leaf_category}" if leaf_category else parent_category
        title = str(item.get("cltrNm") or "").strip()
        raw_parts = [
            title,
            category,
            parent_category,
            leaf_category,
            str(item.get("nrtpNm") or ""),
            str(item.get("drvDstcNm") or ""),
        ]
        min_bid_price = item.get("minBidPrc")
        try:
            min_bid_price = int(min_bid_price) if min_bid_price not in (None, "") else None
        except Exception:
            min_bid_price = None
        normalized.append(
            {
                "title": title,
                "category": category,
                "rank_label": preset_name,
                "min_bid_price": min_bid_price,
                "raw_text": " ".join(part for part in raw_parts if part),
                "source_url": "",
                "detail_args": detail_args,
                "detail_onclick": "",
                "detail_url": _build_detail_url(detail_args),
            }
        )
    return normalized


def fetch_candidates_from_json_presets(
    config: OnbidMovableAlertConfig,
    *,
    preset_names: list[str] | None = None,
) -> list[dict[str, Any]]:
    preset_names = preset_names or list(config.json_presets or [])
    if not preset_names:
        return []

    items: list[dict[str, Any]] = []
    for preset_name in preset_names:
        params = JSON_PRESETS.get(preset_name)
        if not params:
            continue
        data = _fetch_json(config.json_data_url, params)
        raw_items = list(((data.get("result") or {}).get("rtnList") or []))
        items.extend(_normalize_json_items(raw_items, preset_name=preset_name))

    return filter_candidate_items(
        items[: config.max_items],
        keywords=config.keywords,
        exclude_keywords=config.exclude_keywords,
        include_categories=config.include_categories,
        exclude_categories=config.exclude_categories,
    )


def fetch_movable_candidates_with_playwright(config: OnbidMovableAlertConfig) -> list[dict[str, Any]]:
    """
    Experimental helper for Onbid movable-item alert MVP.

    This is intentionally conservative:
    - We do not wire it into run_daily.py yet.
    - We require a verified `list_url` before trying real collection.
    - The browser automation layer is a smoke-test, not an operational collector.
    """
    if not config.list_url:
        raise ValueError("list_url is empty; capture a verified Onbid movable listing URL first")

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "Playwright is not installed in the current environment. "
            "Install it only when we move Onbid movable alerts beyond the planning stage."
        ) from exc

    items = fetch_candidates_from_url_with_playwright(
        config.list_url,
        max_items=config.max_items,
        keywords=config.keywords,
        exclude_keywords=config.exclude_keywords,
        include_categories=config.include_categories,
        exclude_categories=config.exclude_categories,
    )

    return items


def fetch_movable_candidates(config: OnbidMovableAlertConfig) -> list[dict[str, Any]]:
    if config.json_presets:
        items = fetch_candidates_from_json_presets(config)
        if items:
            return items
    return fetch_movable_candidates_with_playwright(config)


def fetch_candidates_from_url_with_playwright(
    url: str,
    *,
    max_items: int = 10,
    keywords: list[str] | None = None,
    exclude_keywords: list[str] | None = None,
    include_categories: list[str] | None = None,
    exclude_categories: list[str] | None = None,
) -> list[dict[str, Any]]:
    if not url:
        raise ValueError("url is empty")

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "Playwright is not installed in the current environment. "
            "Install it only when we move Onbid movable alerts beyond the planning stage."
        ) from exc

    items: list[dict[str, Any]] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)
        page.wait_for_selector(".stuff-search-list, .mo-alert, .mo-alert-large", timeout=30000)
        items = _parse_movable_items(page)[:max_items]
        browser.close()

    return filter_candidate_items(
        items,
        keywords=keywords,
        exclude_keywords=exclude_keywords,
        include_categories=include_categories,
        exclude_categories=exclude_categories,
    )


__all__ = [
    "OnbidMovableAlertConfig",
    "fetch_candidates_from_json_presets",
    "fetch_candidates_from_url_with_playwright",
    "fetch_movable_candidates",
    "fetch_movable_candidates_with_playwright",
    "filter_candidate_items",
    "normalize_onbid_movable_listing",
]

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://www.customs.go.kr"
LIST_PATH = "/kcs/ad/go/gongMeList.do"
DEFAULT_LIST_URL = f"{BASE_URL}{LIST_PATH}"
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/146.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": f"{BASE_URL}/",
}


@dataclass
class CustomsNoticeSearchConfig:
    mi: str = "2898"
    tcd: str = "1"
    page_index: int | None = None
    page_unit: int | None = None
    search_option: str = ""
    search_keyword: str = ""


def _clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _parse_date(value: str | None) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return text


def _extract_seq(url: str) -> str | None:
    parsed = urlparse(url)
    seq = parse_qs(parsed.query).get("seq")
    return seq[0] if seq else None


def _build_detail_url(mi: str, tcd: str, seq: str | None) -> str:
    if not seq:
        return DEFAULT_LIST_URL
    return f"{BASE_URL}/kcs/ad/go/gongMeInfo.do?mi={mi}&seq={seq}&tcd={tcd}"


def normalize_notice(item: dict[str, Any]) -> dict[str, Any]:
    listing_id = item.get("seq") or item.get("detail_url") or item.get("title")
    department = item.get("department") or ""
    title = item.get("title") or ""
    published_date = item.get("published_date")
    return {
        "source": "customs_notice",
        "listing_id": f"customs_notice:{listing_id}",
        "title": title,
        "address": "",
        "region": department,
        "property_type": "공매공고",
        "appraisal_price": None,
        "min_bid_price": None,
        "discount_rate": None,
        "discount_score": 0.0,
        "bid_round": 0,
        "round_score": 0.0,
        "opportunity_score": 0.0,
        "price_bucket": "unknown",
        "auction_date": published_date,
        "area_m2": None,
        "status": "notice",
        "source_url": item.get("detail_url") or DEFAULT_LIST_URL,
        "raw_json": item,
        "search_name": "customs_notice_board",
    }


class CustomsNoticeCollector:
    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)

    def build_params(self, search: CustomsNoticeSearchConfig) -> dict[str, str]:
        params = {
            "mi": search.mi,
            "tcd": search.tcd,
        }
        # The public board is sensitive to paging params; omit them unless we
        # have explicitly verified a working pagination flow.
        if search.page_index is not None:
            params["pageIndex"] = str(search.page_index)
        if search.page_unit is not None:
            params["pageUnit"] = str(search.page_unit)
        if search.search_option:
            params["searchCnd"] = search.search_option
        if search.search_keyword:
            params["searchKrwd"] = search.search_keyword
        return params

    def fetch_list_html(self, search: CustomsNoticeSearchConfig) -> str:
        resp = self.session.get(DEFAULT_LIST_URL, params=self.build_params(search), timeout=20)
        resp.raise_for_status()
        return resp.text

    def parse_list_html(self, html_text: str, search: CustomsNoticeSearchConfig | None = None) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html_text, "html.parser")
        notices: list[dict[str, Any]] = []
        search = search or CustomsNoticeSearchConfig()

        table = soup.select_one("table.bbsList")
        if table is None:
            return notices

        for row in table.select("tbody tr"):
            number_cell = row.select_one('td[data-table="number"]')
            title_cell = row.select_one('td[data-table="subject"]')
            department_cell = row.select_one('td[data-table="write"]')
            date_cell = row.select_one('td[data-table="date"]')
            if not all([number_cell, title_cell, department_cell, date_cell]):
                continue

            link = title_cell.find("a", href=True)
            seq = None
            if link is not None:
                seq = link.get("data-id") or _extract_seq(link.get("href", ""))
            title = _clean_text(link.get_text(" ", strip=True) if link else title_cell.get_text(" ", strip=True))
            if not title:
                continue

            detail_url = _build_detail_url(search.mi, search.tcd, seq)
            notices.append(
                {
                    "number": _clean_text(number_cell.get_text(" ", strip=True)),
                    "title": title,
                    "department": _clean_text(department_cell.get_text(" ", strip=True)),
                    "published_date": _parse_date(date_cell.get_text(" ", strip=True)),
                    "detail_url": detail_url,
                    "seq": seq,
                }
            )

        return notices

    def fetch_notices(self, search: CustomsNoticeSearchConfig | None = None) -> list[dict[str, Any]]:
        search = search or CustomsNoticeSearchConfig()
        html_text = self.fetch_list_html(search)
        return self.parse_list_html(html_text, search=search)

    def fetch_detail_text(self, detail_url: str) -> str:
        resp = self.session.get(detail_url, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        content_candidates = [
            soup.select_one(".board_view"),
            soup.select_one(".conBox"),
            soup.select_one(".cont"),
            soup.select_one("#content"),
        ]
        for node in content_candidates:
            if node:
                return _clean_text(node.get_text("\n", strip=True))
        return _clean_text(soup.get_text("\n", strip=True))

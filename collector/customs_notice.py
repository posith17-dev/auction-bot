from __future__ import annotations

import json
import re
import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://www.customs.go.kr"
LIST_PATH = "/kcs/ad/go/gongMeList.do"
DETAIL_PATH = "/kcs/ad/go/gongMeInfo.do"
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
    search_name: str = "customs_notice_board"
    office_name: str = "관세청"
    base_url: str = BASE_URL
    list_path: str = LIST_PATH
    detail_path: str = DETAIL_PATH
    referer_url: str | None = None
    mi: str = ""
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


def _build_detail_url(search: CustomsNoticeSearchConfig, seq: str | None) -> str:
    if not seq:
        return f"{search.base_url}{search.list_path}"
    query_parts = []
    if search.mi:
        query_parts.append(f"mi={search.mi}")
    query_parts.append(f"seq={seq}")
    if search.tcd:
        query_parts.append(f"tcd={search.tcd}")
    return f"{search.base_url}{search.detail_path}?{'&'.join(query_parts)}"


def _default_referer_url(search: CustomsNoticeSearchConfig) -> str:
    if search.referer_url:
        return search.referer_url
    parts = [part for part in search.list_path.split("/") if part]
    if parts:
        return f"{search.base_url}/{parts[0]}/"
    return f"{search.base_url}/"


def _extract_detail_summary(text: str) -> str:
    cleaned = _clean_text(text)
    if not cleaned:
        return ""
    match = re.search(r"조회수\s*[0-9,]+\s*(.*?)\s*첨부파일", cleaned)
    if match:
        return _clean_text(match.group(1))[:300]
    return cleaned[:300]


def _normalize_attachment_href(detail_url: str, href: str | None) -> str:
    if not href:
        return ""
    if href.startswith("http://") or href.startswith("https://"):
        return href
    parsed = urlparse(detail_url)
    return f"{parsed.scheme}://{parsed.netloc}{href}"


def normalize_notice(item: dict[str, Any], search: CustomsNoticeSearchConfig | None = None) -> dict[str, Any]:
    search = search or CustomsNoticeSearchConfig()
    department = item.get("department") or search.office_name or ""
    title = item.get("title") or ""
    published_date = item.get("published_date")
    stable_key = "|".join([department, str(published_date or ""), title])
    listing_id = hashlib.sha1(stable_key.encode("utf-8")).hexdigest()[:16]
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
        "source_url": item.get("detail_url") or f"{search.base_url}{search.list_path}",
        "raw_json": json.dumps(item, ensure_ascii=False),
        "search_name": search.search_name,
    }


class CustomsNoticeCollector:
    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)

    def build_params(self, search: CustomsNoticeSearchConfig) -> dict[str, str]:
        params: dict[str, str] = {}
        if search.mi:
            params["mi"] = search.mi
        if search.tcd:
            params["tcd"] = search.tcd
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
        headers = {"Referer": _default_referer_url(search)}
        headers["Connection"] = "close"
        url = f"{search.base_url}{search.list_path}"
        params = self.build_params(search)
        try:
            resp = self.session.get(
                url,
                params=params,
                headers=headers,
                timeout=20,
            )
        except requests.RequestException:
            # Some customs sub-sites intermittently reset pooled TLS connections.
            fallback_headers = dict(DEFAULT_HEADERS)
            fallback_headers.update(headers)
            resp = requests.get(
                url,
                params=params,
                headers=fallback_headers,
                timeout=20,
            )
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

            detail_url = _build_detail_url(search, seq)
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

    def fetch_detail_data(self, detail_url: str) -> dict[str, Any]:
        try:
            resp = self.session.get(detail_url, headers={"Connection": "close"}, timeout=20)
        except requests.RequestException:
            fallback_headers = dict(DEFAULT_HEADERS)
            fallback_headers["Connection"] = "close"
            resp = requests.get(detail_url, headers=fallback_headers, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        detail_node = soup.select_one(".bbsView")
        detail_text = _clean_text(detail_node.get_text(" ", strip=True) if detail_node else soup.get_text(" ", strip=True))
        title_node = soup.select_one("h4") or soup.select_one("h3")
        attachments = [
            {
                "name": _clean_text(link.get_text(" ", strip=True)),
                "url": _normalize_attachment_href(detail_url, link.get("href")),
            }
            for link in (detail_node.select("a") if detail_node else [])
            if _clean_text(link.get_text(" ", strip=True))
            and _clean_text(link.get_text(" ", strip=True)) != "바로보기"
        ]
        created_match = re.search(r"작성일\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", detail_text)
        views_match = re.search(r"조회수\s*([0-9,]+)", detail_text)
        return {
            "detail_title": _clean_text(title_node.get_text(" ", strip=True) if title_node else ""),
            "detail_created_date": created_match.group(1) if created_match else "",
            "detail_views": views_match.group(1) if views_match else "",
            "detail_summary": _extract_detail_summary(detail_text),
            "attachments": attachments,
        }

    def fetch_detail_text(self, detail_url: str) -> str:
        detail = self.fetch_detail_data(detail_url)
        return detail.get("detail_summary", "")

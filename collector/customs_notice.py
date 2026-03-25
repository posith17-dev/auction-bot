from __future__ import annotations

import json
import re
import hashlib
import io
import statistics
import subprocess
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlparse
import xml.etree.ElementTree as ET

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
XLSX_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
CUSTOMS_ITEM_LIMIT = 5
CUSTOMS_ITEM_PREVIEW_LIMIT = 3
CUSTOMS_MARKET_RESULT_LIMIT = 5
APPAREL_HINT_KEYWORDS = {
    "jacket",
    "jumper",
    "coat",
    "parka",
    "hoodie",
    "hood",
    "sweatshirt",
    "shirt",
    "tshirt",
    "tee",
    "pants",
    "jeans",
    "denim",
    "skirt",
    "dress",
    "shoes",
    "shoe",
    "slingback",
    "mary jane",
    "loafer",
    "mule",
    "ballet",
    "sneaker",
    "sneakers",
    "loafer",
    "loafers",
    "slipper",
    "sandals",
    "boot",
    "boots",
    "bag",
    "cap",
    "hat",
    "rashguard",
    "reshguard",
    "neoprene",
    "outer",
    "sportswear",
    "apparel",
    "footwear",
    "의류",
    "신발",
    "구두",
    "운동화",
    "슬링백",
    "메리제인",
    "로퍼",
    "발레리나",
    "샌들",
    "자켓",
    "재킷",
    "코트",
    "후드",
    "티셔츠",
    "바지",
    "치마",
    "가방",
    "래쉬가드",
}
LIQUOR_HINT_KEYWORDS = {
    "wine",
    "whisky",
    "whiskey",
    "vodka",
    "rum",
    "gin",
    "beer",
    "brandy",
    "liqueur",
    "liquor",
    "champagne",
    "sparkling",
    "tequila",
    "cognac",
    "포도주",
    "와인",
    "주류",
    "양주",
    "위스키",
    "맥주",
    "보드카",
    "럼",
    "진",
    "브랜디",
    "샴페인",
    "데킬라",
    "코냑",
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


def _parse_int(value: str | None) -> int | None:
    text = re.sub(r"[^0-9-]", "", str(value or ""))
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _parse_float(value: str | None) -> float | None:
    text = re.sub(r"[^0-9.\-]", "", str(value or ""))
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _xlsx_col_letters(ref: str) -> str:
    out = ""
    for ch in ref:
        if ch.isalpha():
            out += ch
        else:
            break
    return out


def _xlsx_read_rows(content: bytes, limit: int = 300) -> list[dict[str, str]]:
    workbook = zipfile.ZipFile(io.BytesIO(content))
    shared: list[str] = []
    if "xl/sharedStrings.xml" in workbook.namelist():
        root = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
        for si in root.findall(f"{XLSX_NS}si"):
            shared.append("".join(node.text or "" for node in si.iter(f"{XLSX_NS}t")))
    sheet_path = next((name for name in workbook.namelist() if name.startswith("xl/worksheets/sheet")), None)
    if not sheet_path:
        return []
    sheet = ET.fromstring(workbook.read(sheet_path))
    rows: list[dict[str, str]] = []
    for row in sheet.findall(f".//{XLSX_NS}row")[:limit]:
        values: dict[str, str] = {}
        for cell in row.findall(f"{XLSX_NS}c"):
            ref = cell.attrib.get("r", "")
            cell_type = cell.attrib.get("t")
            value = ""
            node_v = cell.find(f"{XLSX_NS}v")
            if node_v is not None and node_v.text is not None:
                value = node_v.text
                if cell_type == "s" and value.isdigit():
                    idx = int(value)
                    if idx < len(shared):
                        value = shared[idx]
            node_is = cell.find(f"{XLSX_NS}is")
            if node_is is not None:
                value = "".join(text_node.text or "" for text_node in node_is.iter(f"{XLSX_NS}t"))
            values[_xlsx_col_letters(ref)] = _clean_text(value)
        rows.append(values)
    return rows


def _detect_header_row(rows: list[dict[str, str]]) -> tuple[int | None, dict[str, str]]:
    required = {"품명", "공매예정가격(원)"}
    optional = {
        "규격",
        "HS부호명",
        "가격산출수량",
        "수량단위",
        "공매번호",
        "란번호",
    }
    for idx, row in enumerate(rows):
        header_map = {value: col for col, value in row.items() if value}
        if required.issubset(header_map):
            for key in optional:
                header_map.setdefault(key, "")
            return idx, header_map
    return None, {}


def _extract_market_query(item_name: str, spec: str, hs_name: str) -> str:
    spec_hint = spec.split(",")[0][:40]
    query = " ".join(part for part in [item_name, spec_hint, hs_name] if part).strip()
    return re.sub(r"\s+", " ", query)[:120]


def _extract_liquor_query(item_name: str, spec: str, hs_name: str) -> str:
    candidates = [part.strip() for part in re.split(r"[,/;]+", spec or "") if part.strip()]
    for candidate in candidates:
        cleaned = re.sub(r"-?\s*alc\.?\s*[0-9.]+%?", "", candidate, flags=re.IGNORECASE)
        cleaned = re.sub(r"\([^)]*\)", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" -")
        if len(cleaned) >= 5:
            return cleaned[:120]
    fallback = " ".join(part for part in [item_name, hs_name] if part).strip()
    return re.sub(r"\s+", " ", fallback)[:120]


def _extract_escaped_int(text: str, pattern: str) -> int | None:
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return None
    return _parse_int(match.group(1))


def _normalize_market_query(query: str) -> str:
    normalized = query.lower()
    replacements = {
        "reshguard": "rashguard",
        "rash guard": "rashguard",
        "tee shirt": "tshirt",
    }
    for before, after in replacements.items():
        normalized = normalized.replace(before, after)
    return normalized


def _tokenize_compare(text: str) -> list[str]:
    stop = {
        "alc",
        "kg",
        "bag",
        "box",
        "set",
        "the",
        "and",
        "with",
        "red",
        "white",
        "sparkling",
        "주식회사",
        "용량",
    }
    tokens = re.findall(r"[0-9a-zA-Z가-힣]+", text.lower())
    return [token for token in tokens if len(token) >= 2 and token not in stop]


def _score_title_match(query_tokens: list[str], candidate_title: str) -> float:
    if not query_tokens:
        return 0.0
    candidate_tokens = set(_tokenize_compare(candidate_title))
    if not candidate_tokens:
        return 0.0
    overlap = sum(1 for token in query_tokens if token in candidate_tokens)
    return overlap / len(query_tokens)


def _is_apparel_candidate(item_name: str, spec: str, hs_name: str) -> bool:
    text = " ".join(part for part in [item_name, spec, hs_name] if part).lower()
    return any(keyword in text for keyword in APPAREL_HINT_KEYWORDS)


def _is_liquor_candidate(item_name: str, spec: str, hs_name: str) -> bool:
    text = " ".join(part for part in [item_name, spec, hs_name] if part).lower()
    return any(keyword in text for keyword in LIQUOR_HINT_KEYWORDS)


def classify_notice_type(title: str | None, summary: str | None = None) -> str:
    text = f"{title or ''} {summary or ''}"
    checks = [
        ("수의계약", ["수의계약"]),
        ("매각결과", ["매각결과", "낙찰결과"]),
        ("재공고", ["재공고", "재입찰"]),
        ("유찰", ["유찰"]),
        ("공매공고", ["공매", "매각", "입찰", "불용품"]),
    ]
    for label, keywords in checks:
        if any(keyword in text for keyword in keywords):
            return label
    return "기타공고"


def normalize_notice(item: dict[str, Any], search: CustomsNoticeSearchConfig | None = None) -> dict[str, Any]:
    search = search or CustomsNoticeSearchConfig()
    department = item.get("department") or search.office_name or ""
    title = item.get("title") or ""
    published_date = item.get("published_date")
    notice_type = item.get("notice_type") or classify_notice_type(
        title,
        item.get("detail_summary") or item.get("summary") or "",
    )
    stable_key = "|".join([department, str(published_date or ""), title])
    listing_id = hashlib.sha1(stable_key.encode("utf-8")).hexdigest()[:16]
    return {
        "source": "customs_notice",
        "listing_id": f"customs_notice:{listing_id}",
        "title": title,
        "address": "",
        "region": department,
        "property_type": notice_type,
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
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                resp = self.session.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=20,
                )
                resp.raise_for_status()
                return resp.text
            except requests.RequestException as exc:
                last_error = exc
                try:
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
                except requests.RequestException as fallback_exc:
                    last_error = fallback_exc
                    if attempt < 2:
                        time.sleep(0.5 * (attempt + 1))
        if last_error:
            raise last_error
        raise RuntimeError(f"Failed to fetch customs notice list: {url}")

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

    def fetch_attachment_bytes(self, attachment_url: str, *, referer_url: str) -> bytes:
        headers = {"Referer": referer_url, "Connection": "close"}
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                resp = self.session.get(attachment_url, headers=headers, timeout=30)
                resp.raise_for_status()
                return resp.content
            except requests.RequestException as exc:
                last_error = exc
                try:
                    fallback_headers = dict(DEFAULT_HEADERS)
                    fallback_headers.update(headers)
                    resp = requests.get(attachment_url, headers=fallback_headers, timeout=30)
                    resp.raise_for_status()
                    return resp.content
                except requests.RequestException as fallback_exc:
                    last_error = fallback_exc
                    if attempt < 2:
                        time.sleep(0.5 * (attempt + 1))
        if last_error:
            raise last_error
        raise RuntimeError(f"Failed to fetch customs attachment: {attachment_url}")

    def extract_items_from_attachment(self, attachment_url: str, *, referer_url: str) -> list[dict[str, Any]]:
        content = self.fetch_attachment_bytes(attachment_url, referer_url=referer_url)
        rows = _xlsx_read_rows(content)
        header_idx, header_map = _detect_header_row(rows)
        if header_idx is None:
            return []
        items: list[dict[str, Any]] = []
        for row in rows[header_idx + 1 :]:
            item_name = row.get(header_map["품명"], "")
            if not item_name:
                continue
            total_price = _parse_int(row.get(header_map["공매예정가격(원)"], ""))
            quantity = _parse_float(row.get(header_map.get("가격산출수량", ""), ""))
            unit_price = None
            if total_price is not None and quantity and quantity > 0:
                unit_price = round(total_price / quantity, 2)
            items.append(
                {
                    "item_name": item_name,
                    "spec": row.get(header_map.get("규격", ""), ""),
                    "hs_name": row.get(header_map.get("HS부호명", ""), ""),
                    "auction_no": row.get(header_map.get("공매번호", ""), ""),
                    "item_no": row.get(header_map.get("란번호", ""), ""),
                    "quantity": quantity,
                    "unit": row.get(header_map.get("수량단위", ""), ""),
                    "auction_total_price": total_price,
                    "auction_unit_price": unit_price,
                }
            )
        items.sort(key=lambda item: item.get("auction_total_price") or 0, reverse=True)
        return items[:CUSTOMS_ITEM_LIMIT]

    def search_market_price_danawa(self, query: str) -> dict[str, Any] | None:
        if not query:
            return None
        resp = self.session.get(
            "https://search.danawa.com/dsearch.php",
            params={"query": query},
            headers={"Connection": "close"},
            timeout=10,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        query_tokens = _tokenize_compare(query)
        matches: list[dict[str, Any]] = []
        for item in soup.select("li.prod_item")[:CUSTOMS_MARKET_RESULT_LIMIT]:
            title_node = item.select_one("p.prod_name a")
            if title_node is None:
                continue
            title = _clean_text(title_node.get_text(" ", strip=True))
            hidden_price = item.select_one('input[id^="min_price_"]')
            min_price = _parse_int(hidden_price.get("value") if hidden_price else "")
            if not title or min_price is None:
                continue
            match_score = _score_title_match(query_tokens, title)
            if match_score < 0.34:
                continue
            matches.append(
                {
                    "title": title,
                    "min_price": min_price,
                    "match_score": round(match_score, 3),
                }
            )
        if not matches:
            return None
        prices = [item["min_price"] for item in matches]
        best = max(matches, key=lambda item: (item["match_score"], -item["min_price"]))
        return {
            "query": query,
            "min_price": min(prices),
            "median_price": int(statistics.median(prices)),
            "best_title": best["title"],
            "match_score": best["match_score"],
            "source": "danawa",
        }

    def search_market_price_musinsa(self, query: str) -> dict[str, Any] | None:
        if not query:
            return None
        request_query = _normalize_market_query(query)
        resp = self.session.get(
            "https://api.musinsa.com/api2/dp/v2/plp/goods",
            params={
                "caller": "SEARCH",
                "keyword": request_query,
                "page": 1,
                "size": CUSTOMS_MARKET_RESULT_LIMIT,
            },
            headers={"Connection": "close"},
            timeout=10,
        )
        resp.raise_for_status()
        payload = resp.json()
        items = payload.get("data", {}).get("list") or []
        query_tokens = _tokenize_compare(query)
        matches: list[dict[str, Any]] = []
        for item in items[:CUSTOMS_MARKET_RESULT_LIMIT]:
            title = _clean_text(item.get("goodsName"))
            price = item.get("price") or item.get("normalPrice")
            if not title or price in (None, ""):
                continue
            match_score = _score_title_match(query_tokens, title)
            if match_score < 0.34:
                continue
            matches.append(
                {
                    "title": title,
                    "price": int(price),
                    "goods_link_url": item.get("goodsLinkUrl") or "",
                    "match_score": round(match_score, 3),
                }
            )
        if not matches:
            fallback_matches = [
                {
                    "title": _clean_text(item.get("goodsName")),
                    "price": int(item.get("price") or item.get("normalPrice")),
                    "goods_link_url": item.get("goodsLinkUrl") or "",
                }
                for item in items[:3]
                if item.get("goodsName") and (item.get("price") or item.get("normalPrice"))
            ]
            if not fallback_matches:
                return None
            prices = [item["price"] for item in fallback_matches]
            best = fallback_matches[0]
            return {
                "query": query,
                "min_price": min(prices),
                "median_price": int(statistics.median(prices)),
                "best_title": best["title"],
                "best_url": best["goods_link_url"],
                "match_score": 0.0,
                "source": "musinsa_fallback",
            }
        prices = [item["price"] for item in matches]
        best = max(matches, key=lambda item: (item["match_score"], -item["price"]))
        return {
            "query": query,
            "min_price": min(prices),
            "median_price": int(statistics.median(prices)),
            "best_title": best["title"],
            "best_url": best["goods_link_url"],
            "match_score": best["match_score"],
            "source": "musinsa",
        }

    def search_market_price_vivino(self, query: str) -> dict[str, Any] | None:
        if not query:
            return None
        html_text = ""
        try:
            resp = self.session.get(
                "https://www.vivino.com/search/wines",
                params={"q": query},
                headers={"Connection": "close"},
                timeout=12,
            )
            resp.raise_for_status()
            html_text = resp.text
        except Exception:
            try:
                result = subprocess.run(
                    [
                        "curl",
                        "-L",
                        "-sS",
                        f"https://www.vivino.com/search/wines?q={requests.utils.quote(query)}",
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
                html_text = result.stdout
            except Exception:
                html_text = ""
        if not html_text:
            return None
        unescaped = html_text.replace("&quot;", '"')
        query_tokens = _tokenize_compare(query)
        pattern = re.compile(
            r'"name":"(?P<title>[^"]+)".{0,1200}?"price":(?P<price>[0-9]{3,})',
            re.IGNORECASE | re.DOTALL,
        )
        matches: list[dict[str, Any]] = []
        for found in pattern.finditer(unescaped):
            title = _clean_text(found.group("title"))
            price = _parse_int(found.group("price"))
            if not title or price is None:
                continue
            match_score = _score_title_match(query_tokens, title)
            if match_score < 0.25:
                continue
            matches.append(
                {
                    "title": title,
                    "price": price,
                    "match_score": round(match_score, 3),
                }
            )
        if not matches:
            range_min = (
                _extract_escaped_int(html_text, r'&quot;defaults&quot;:\{&quot;minimum&quot;:([0-9]+)')
                or _extract_escaped_int(html_text, r'"defaults":\{"minimum":([0-9]+)')
                or _extract_escaped_int(html_text, r'&quot;price_range&quot;:\{&quot;minimum&quot;:([0-9]+)')
                or _extract_escaped_int(html_text, r'"price_range":\{"minimum":([0-9]+)')
            )
            range_max = (
                _extract_escaped_int(html_text, r'&quot;defaults&quot;:\{&quot;minimum&quot;:[0-9]+,&quot;maximum&quot;:([0-9]+)')
                or _extract_escaped_int(html_text, r'"defaults":\{"minimum":[^0-9]*[0-9]+,"maximum":([0-9]+)')
                or _extract_escaped_int(html_text, r'&quot;price_range&quot;:\{&quot;minimum&quot;:[0-9]+,&quot;maximum&quot;:([0-9]+)')
                or _extract_escaped_int(html_text, r'"price_range":\{"minimum":[^0-9]*[0-9]+,"maximum":([0-9]+)')
            )
            if range_min and range_max and range_max >= range_min:
                return {
                    "query": query,
                    "range_min": int(range_min),
                    "range_max": int(range_max),
                    "best_title": query,
                    "best_url": f"https://www.vivino.com/search/wines?q={requests.utils.quote(query)}",
                    "match_score": 0.0,
                    "source": "vivino_band",
                }
            return None
        prices = [item["price"] for item in matches]
        best = max(matches, key=lambda item: (item["match_score"], -item["price"]))
        return {
            "query": query,
            "min_price": min(prices),
            "median_price": int(statistics.median(prices)),
            "best_title": best["title"],
            "best_url": f"https://www.vivino.com/search/wines?q={requests.utils.quote(query)}",
            "match_score": best["match_score"],
            "source": "vivino",
        }

    def enrich_notice_items(self, detail_url: str, attachments: list[dict[str, Any]]) -> dict[str, Any]:
        xlsx_attachment = next(
            (
                attachment
                for attachment in attachments
                if str(attachment.get("name", "")).lower().endswith(".xlsx")
            ),
            None,
        )
        if not xlsx_attachment:
            return {"item_samples": [], "market_compare": None}
        attachment_url = str(xlsx_attachment.get("url") or "")
        if not attachment_url:
            return {"item_samples": [], "market_compare": None}
        try:
            items = self.extract_items_from_attachment(attachment_url, referer_url=detail_url)
        except Exception:
            return {"item_samples": [], "market_compare": None}
        market_compare = None
        market_status: dict[str, Any] | None = None
        selected_item_name: str | None = None
        for item in items[:3]:
            is_apparel_item = _is_apparel_candidate(item["item_name"], item["spec"], item["hs_name"])
            is_liquor_item = _is_liquor_candidate(item["item_name"], item["spec"], item["hs_name"])
            if is_apparel_item:
                query = item["item_name"].strip()
            elif is_liquor_item:
                query = _extract_liquor_query(item["item_name"], item["spec"], item["hs_name"])
            else:
                query = _extract_market_query(item["item_name"], item["spec"], item["hs_name"])
            if not query:
                continue
            market = None
            try:
                if is_apparel_item:
                    market = self.search_market_price_musinsa(query)
                elif is_liquor_item:
                    market = self.search_market_price_vivino(query)
            except Exception:
                market = None
            if market is None:
                try:
                    market = self.search_market_price_danawa(query)
                except Exception:
                    market = None
            item["market_query"] = query
            item["market_price"] = market
            if market and item.get("auction_unit_price"):
                if market.get("source") == "vivino_band":
                    market_status = {
                        "category": "liquor",
                        "query": query,
                        "status": "search_band",
                        "source": "vivino_band",
                        "note": f"Vivino 검색가 {int(market['range_min']):,}~{int(market['range_max']):,}원",
                        "search_url": market.get("best_url") or "",
                        "item_name": item["item_name"],
                    }
                    break
                auction_unit_price = float(item["auction_unit_price"])
                market_price = float(market["median_price"])
                discount_vs_market = round((1 - (auction_unit_price / market_price)) * 100, 1) if market_price > 0 else None
                market_compare = {
                    "item_name": item["item_name"],
                    "query": query,
                    "auction_unit_price": auction_unit_price,
                    "market_median_price": int(market_price),
                    "market_min_price": int(market["min_price"]),
                    "discount_vs_market_pct": discount_vs_market,
                    "best_title": market["best_title"],
                    "best_url": market.get("best_url") or "",
                    "source": market["source"],
                }
                selected_item_name = item["item_name"]
                break
            if market is None and is_liquor_item and market_status is None:
                market_status = {
                    "category": "liquor",
                    "query": query,
                    "status": "manual_review",
                    "source": "vivino_search",
                    "note": "주류 시세 자동확인 미완료",
                    "search_url": f"https://www.vivino.com/search/wines?q={requests.utils.quote(query)}",
                    "item_name": item["item_name"],
                }
                selected_item_name = item["item_name"]

        display_items = items[:CUSTOMS_ITEM_LIMIT]
        if selected_item_name:
            prioritized = [item for item in display_items if item.get("item_name") == selected_item_name]
            remainder = [item for item in display_items if item.get("item_name") != selected_item_name]
            display_items = prioritized + remainder
        return {
            "item_samples": display_items[:CUSTOMS_ITEM_PREVIEW_LIMIT],
            "market_compare": market_compare,
            "market_status": market_status,
        }

    def fetch_detail_data(self, detail_url: str) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                resp = self.session.get(detail_url, headers={"Connection": "close"}, timeout=20)
                resp.raise_for_status()
                break
            except requests.RequestException as exc:
                last_error = exc
                try:
                    fallback_headers = dict(DEFAULT_HEADERS)
                    fallback_headers["Connection"] = "close"
                    resp = requests.get(detail_url, headers=fallback_headers, timeout=20)
                    resp.raise_for_status()
                    break
                except requests.RequestException as fallback_exc:
                    last_error = fallback_exc
                    if attempt < 2:
                        time.sleep(0.5 * (attempt + 1))
        else:
            if last_error:
                raise last_error
            raise RuntimeError(f"Failed to fetch customs detail: {detail_url}")
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
            "notice_type": classify_notice_type(
                _clean_text(title_node.get_text(" ", strip=True) if title_node else ""),
                _extract_detail_summary(detail_text),
            ),
            "attachments": attachments,
        }

    def fetch_detail_text(self, detail_url: str) -> str:
        detail = self.fetch_detail_data(detail_url)
        return detail.get("detail_summary", "")

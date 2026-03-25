from __future__ import annotations

import copy
import json
import re
import urllib.parse
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests


URL = "https://www.courtauction.go.kr/pgj/pgjsearch/searchControllerMain.on"
SOURCE_URL = "https://www.courtauction.go.kr/pgj/index.on?w2xPath=/pgj/ui/pgj100/PGJ151F00.xml"
DETAIL_PATH = "/pgj/index.on"

HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json;charset=UTF-8",
    "Origin": "https://www.courtauction.go.kr",
    "Referer": SOURCE_URL,
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/146.0.0.0 Safari/537.36"
    ),
    "submissionid": "mf_wfm_mainFrame_sbm_selectGdsDtlSrch",
    "sc-userid": "SYSTEM",
}


@dataclass
class SearchConfig:
    name: str
    region_name: str
    cort_ofc_cd: str
    cort_st_dvs: str
    bid_dvs_cd: str
    bid_begin_ymd: str
    bid_end_ymd: str
    lcl_dspsl_gds_lst_usg_cd: str
    mcl_dspsl_gds_lst_usg_cd: str
    scl_dspsl_gds_lst_usg_cd: str
    cort_auctn_srch_cond_cd: str
    mvprp_rlet_dvs_cd: str
    page_size: int
    appraisal_min: str = ""
    appraisal_max: str = ""
    min_bid_min: str = ""
    min_bid_max: str = ""


def _base_payload(search: SearchConfig, page_no: int) -> dict[str, Any]:
    return {
        "dma_pageInfo": {
            "pageNo": page_no,
            "pageSize": search.page_size,
            "bfPageNo": "",
            "startRowNo": "",
            "totalCnt": "",
            "totalYn": "Y",
            "groupTotalCount": "",
        },
        "dma_srchGdsDtlSrchInfo": {
            "rletDspslSpcCondCd": "",
            "bidDvsCd": search.bid_dvs_cd,
            "mvprpRletDvsCd": search.mvprp_rlet_dvs_cd,
            "cortAuctnSrchCondCd": search.cort_auctn_srch_cond_cd,
            "aeeEvlAmtMax": search.appraisal_max,
            "aeeEvlAmtMin": search.appraisal_min,
            "bidBgngYmd": search.bid_begin_ymd,
            "bidEndYmd": search.bid_end_ymd,
            "carMdlNm": "",
            "carMdyrMax": "",
            "carMdyrMin": "",
            "cortAuctnMbrsId": "",
            "cortOfcCd": search.cort_ofc_cd,
            "cortStDvs": search.cort_st_dvs,
            "csNo": "",
            "dspslDxdyYmd": "",
            "dspslPlcNm": "",
            "execrOfcDvsCd": "",
            "flbdNcntMax": "",
            "flbdNcntMin": "",
            "fothDspslHm": "",
            "fstDspslHm": "",
            "fuelKndCd": "",
            "gdsVendNm": "",
            "grbxTypCd": "",
            "jdbnCd": "",
            "lafjOrderBy": "",
            "lclDspslGdsLstUsgCd": search.lcl_dspsl_gds_lst_usg_cd,
            "lwsDspslPrcMax": search.min_bid_max,
            "lwsDspslPrcMin": search.min_bid_min,
            "lwsDspslPrcRateMax": "",
            "lwsDspslPrcRateMin": "",
            "mclDspslGdsLstUsgCd": search.mcl_dspsl_gds_lst_usg_cd,
            "mvprpArtclKndCd": "",
            "mvprpArtclNm": "",
            "mvprpAtchmPlcTypCd": "",
            "mvprpDspslPlcAdongEmdCd": "",
            "mvprpDspslPlcAdongSdCd": "",
            "mvprpDspslPlcAdongSggCd": "",
            "notifyLoc": "off",
            "objctArDtsMax": "",
            "objctArDtsMin": "",
            "pgmId": "PGJ151F01",
            "rdDspslPlcAdongEmdCd": "",
            "rdDspslPlcAdongSdCd": "",
            "rdDspslPlcAdongSggCd": "",
            "rdnmNo": "",
            "rdnmSdCd": "",
            "rdnmSggCd": "",
            "rprsAdongEmdCd": "",
            "rprsAdongSdCd": "",
            "rprsAdongSggCd": "",
            "sclDspslGdsLstUsgCd": search.scl_dspsl_gds_lst_usg_cd,
            "scndDspslHm": "",
            "sideDvsCd": "",
            "statNum": 1,
            "thrdDspslHm": "",
        },
    }


def _parse_ymd(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y%m%d")
    except ValueError:
        return None


def _to_int(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(str(value).replace(",", ""))
    except ValueError:
        return None


def _to_float(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def _extract_area_m2(item: dict[str, Any]) -> float | None:
    for key in ["maxArea", "minArea"]:
        val = _to_float(item.get(key))
        if val:
            return val
    text = item.get("pjbBuldList") or ""
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)㎡", text)
    return float(match.group(1)) if match else None


def _discount_rate(appraisal_price: int | None, min_bid_price: int | None) -> float | None:
    if not appraisal_price or not min_bid_price or appraisal_price <= 0:
        return None
    return round((1 - (min_bid_price / appraisal_price)) * 100, 4)


def _discount_score(discount_rate: float | None) -> float:
    return round(discount_rate or 0.0, 4)


def _round_score(bid_round: int | None) -> float:
    return float(min((bid_round or 0) * 5, 20))


def _price_bucket(appraisal_price: int | None) -> str:
    if appraisal_price is None:
        return "unknown"
    if appraisal_price <= 100_000_000:
        return "under_1eok"
    if appraisal_price <= 300_000_000:
        return "1to3eok"
    if appraisal_price <= 500_000_000:
        return "3to5eok"
    return "over_5eok"


def _opportunity_score(discount_rate: float | None, bid_round: int | None) -> float:
    return round(_discount_score(discount_rate) + _round_score(bid_round), 4)


def _build_source_url(item: dict[str, Any]) -> str:
    # Courtauction does not expose a stable public permalink in list responses.
    # We keep a deterministic case-level deep-link candidate so the alert points
    # to a page keyed by the same identifiers used by the detail POST request.
    query = urllib.parse.urlencode(
        {
            "w2xPath": "/pgj/ui/pgj100/PGJ151F00.xml",
            "cortOfcCd": item.get("boCd", ""),
            "csNo": item.get("srnSaNo", ""),
            "dspslGdsSeq": item.get("maemulSer", ""),
        }
    )
    return f"https://www.courtauction.go.kr{DETAIL_PATH}?{query}"


def normalize_listing(item: dict[str, Any], *, search_name: str) -> dict[str, Any]:
    appraisal_price = _to_int(item.get("gamevalAmt"))
    min_bid_price = _to_int(item.get("minmaePrice"))
    auction_date = _parse_ymd(item.get("maeGiil"))
    address = " ".join(
        x
        for x in [
            item.get("hjguSido"),
            item.get("hjguSigu"),
            item.get("hjguDong"),
            item.get("rdNm"),
            item.get("buldNo"),
            item.get("rdAddrSub"),
        ]
        if x
    ).strip()
    title = " ".join(x for x in [item.get("buldNm"), item.get("buldList")] if x).strip()
    property_type = item.get("dspslUsgNm") or item.get("sclsUtilCd") or ""
    bid_round = _to_int(item.get("maeGiilCnt")) or _to_int(item.get("yuchalCnt")) or 0
    discount_rate = _discount_rate(appraisal_price, min_bid_price)
    return {
        "source": "courtauction",
        "listing_id": item.get("docid"),
        "search_name": search_name,
        "title": title or item.get("srnSaNo") or "",
        "address": address,
        "region": " ".join(x for x in [item.get("hjguSido"), item.get("hjguSigu")] if x),
        "property_type": property_type,
        "appraisal_price": appraisal_price,
        "min_bid_price": min_bid_price,
        "discount_rate": discount_rate,
        "discount_score": _discount_score(discount_rate),
        "bid_round": bid_round,
        "round_score": _round_score(bid_round),
        "opportunity_score": _opportunity_score(discount_rate, bid_round),
        "price_bucket": _price_bucket(appraisal_price),
        "auction_date": auction_date.date().isoformat() if auction_date else None,
        "area_m2": _extract_area_m2(item),
        "status": item.get("mulStatcd") or "",
        "source_url": _build_source_url(item),
        "raw_json": json.dumps(item, ensure_ascii=False),
    }


class CourtAuctionCollector:
    def __init__(self, cookie: str | None = None) -> None:
        self.headers = dict(HEADERS)
        if cookie:
            self.headers["Cookie"] = cookie

    def fetch_page(self, search: SearchConfig, page_no: int) -> dict[str, Any]:
        payload = _base_payload(search, page_no)
        resp = requests.post(URL, headers=self.headers, json=payload, timeout=20)
        resp.raise_for_status()
        return resp.json()

    def fetch_all(self, search: SearchConfig) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        first = self.fetch_page(search, 1)
        data = first.get("data") or {}
        page_info = data.get("dma_pageInfo") or {}
        total_cnt = int(page_info.get("totalCnt") or 0)
        page_size = int(page_info.get("pageSize") or search.page_size)
        total_pages = max(1, (total_cnt + page_size - 1) // page_size)

        raw_items = list(data.get("dlt_srchResult") or [])
        for page_no in range(2, total_pages + 1):
            payload = self.fetch_page(search, page_no)
            raw_items.extend((payload.get("data") or {}).get("dlt_srchResult") or [])

        listings = [normalize_listing(item, search_name=search.name) for item in raw_items]
        meta = {
            "total_cnt": total_cnt,
            "total_pages": total_pages,
            "items_fetched": len(listings),
            "region_name": search.region_name,
            "search_name": search.name,
        }
        return listings, meta

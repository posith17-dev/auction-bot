#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import os
from pathlib import Path

import yaml

from alerts.telegram import send_message
from collector.court_auction import CourtAuctionCollector, SearchConfig
from collector.customs_notice import CustomsNoticeCollector, CustomsNoticeSearchConfig, normalize_notice
from reports.daily_report import write_daily_report
from storage.schema import connect, prune_old_data, upsert_listings


ROOT = Path("/home/ubuntu/auction-bot")
ENV_CANDIDATES = [
    Path("/home/ubuntu/trading-bot/.env"),
    Path("/home/ubuntu/trading-system/config/secrets.env"),
]


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fp:
        return yaml.safe_load(fp)


def build_search_config(raw: dict) -> SearchConfig:
    return SearchConfig(**dict(raw))


def build_customs_search_config(raw: dict) -> CustomsNoticeSearchConfig:
    return CustomsNoticeSearchConfig(**dict(raw))


def _load_env_file_values(*keys: str) -> dict[str, str]:
    values = {key: "" for key in keys}
    for path in ENV_CANDIDATES:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if "=" not in line or line.strip().startswith("#"):
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key in values and not values[key]:
                values[key] = value.strip().strip('"').strip("'")
        if all(values.values()):
            break
    return values


def resolve_telegram_config(raw: dict | None) -> dict:
    telegram_cfg = dict(raw or {})
    bot_token = telegram_cfg.get("bot_token", "").strip()
    chat_id = telegram_cfg.get("chat_id", "").strip()
    bot_token_env = telegram_cfg.get("bot_token_env", "TELEGRAM_BOT_TOKEN")
    chat_id_env = telegram_cfg.get("chat_id_env", "TELEGRAM_CHAT_ID")

    if not bot_token and bot_token_env:
        bot_token = os.getenv(bot_token_env, "").strip()
    if not chat_id and chat_id_env:
        chat_id = os.getenv(chat_id_env, "").strip()
    if (not bot_token and bot_token_env) or (not chat_id and chat_id_env):
        file_values = _load_env_file_values(bot_token_env, chat_id_env)
        if not bot_token and bot_token_env:
            bot_token = file_values.get(bot_token_env, "")
        if not chat_id and chat_id_env:
            chat_id = file_values.get(chat_id_env, "")

    telegram_cfg["bot_token"] = bot_token
    telegram_cfg["chat_id"] = chat_id
    return telegram_cfg


def _threshold_to_percent(value: float | int | None) -> float | None:
    if value is None:
        return None
    threshold = float(value)
    if threshold <= 1:
        return threshold * 100
    return threshold


def _matches_any(value: str, candidates: list[str]) -> bool:
    if not candidates:
        return True
    return any(candidate and candidate in value for candidate in candidates)


def filter_alert_listings(
    listings: list[dict],
    *,
    new_listing_ids: list[str],
    conditions: dict | None,
) -> list[dict]:
    if not conditions or not new_listing_ids:
        return []

    new_ids = set(new_listing_ids)
    min_discount_rate = _threshold_to_percent(conditions.get("min_discount_rate"))
    property_types = conditions.get("property_types") or []
    regions = conditions.get("regions") or []
    max_appraisal_price = conditions.get("max_appraisal_price")

    matched = []
    for item in listings:
        if item.get("listing_id") not in new_ids:
            continue
        discount_rate = item.get("discount_rate")
        appraisal_price = item.get("appraisal_price")
        property_type = item.get("property_type") or ""
        region = item.get("region") or item.get("address") or ""

        if min_discount_rate is not None and (discount_rate is None or discount_rate < min_discount_rate):
            continue
        if max_appraisal_price is not None and (appraisal_price is None or appraisal_price > int(max_appraisal_price)):
            continue
        if not _matches_any(property_type, property_types):
            continue
        if not _matches_any(region, regions):
            continue
        matched.append(item)
    return sorted(
        matched,
        key=lambda row: (
            -(row.get("opportunity_score") or 0),
            -(row.get("discount_rate") or 0),
            str(row.get("auction_date") or ""),
        ),
    )


def filter_new_customs_notices(
    listings: list[dict],
    *,
    new_listing_ids: list[str],
) -> list[dict]:
    if not new_listing_ids:
        return []
    new_ids = set(new_listing_ids)
    matched = [
        item
        for item in listings
        if item.get("listing_id") in new_ids and item.get("source") == "customs_notice"
    ]
    return sorted(
        matched,
        key=lambda row: (
            str(row.get("auction_date") or ""),
            str(row.get("region") or ""),
            str(row.get("title") or ""),
        ),
        reverse=True,
    )


def _resolve_searches(cfg: dict) -> list[dict]:
    if cfg.get("searches"):
        return list(cfg["searches"])
    return [cfg["search"]]


def _resolve_customs_searches(cfg: dict) -> list[dict]:
    return list(cfg.get("customs_searches") or [])


def _merge_listings(listings: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    for item in listings:
        listing_id = item["listing_id"]
        if listing_id not in merged:
            merged[listing_id] = dict(item)
            continue

        existing = merged[listing_id]
        existing_names = [x for x in str(existing.get("search_name", "")).split(",") if x]
        incoming_names = [x for x in str(item.get("search_name", "")).split(",") if x]
        merged_names = ",".join(sorted(set(existing_names + incoming_names)))
        if (item.get("opportunity_score") or 0) > (existing.get("opportunity_score") or 0):
            for key, value in item.items():
                if key != "listing_id":
                    existing[key] = value
        existing["search_name"] = merged_names
    return list(merged.values())


def _fmt_krw(value: int | None) -> str:
    if value is None:
        return "-"
    if value % 100000000 == 0:
        return f"{value // 100000000}억"
    return f"{value:,}원"


def build_listing_message(item: dict) -> str:
    if item.get("source") == "customs_notice":
        title = html.escape(str(item.get("title") or "공매공고"))
        region = html.escape(str(item.get("region") or ""))
        auction_date = html.escape(str(item.get("auction_date") or "-"))
        source_url = html.escape(str(item.get("source_url") or ""))
        attachments = ""
        summary = ""
        raw_json = item.get("raw_json") or ""
        if isinstance(raw_json, str):
            import json

            try:
                raw = json.loads(raw_json)
                attachments = ", ".join((raw.get("attachments") or [])[:2])
                summary = str(raw.get("detail_summary") or "")
            except Exception:
                attachments = ""
                summary = ""
        attachment_line = ""
        if attachments:
            attachment_line = f"\n📎 {html.escape(attachments[:120])}"
        summary_line = ""
        if summary:
            summary_line = f"\n📝 {html.escape(summary[:160])}"
        return (
            f"📢 <b>[공매공고]</b> {region} {title}\n"
            f"📅 공고일: {auction_date}\n"
            f"{attachment_line}"
            f"{summary_line}\n"
            f"🔗 <a href=\"{source_url}\">상세보기</a>"
        )

    title = html.escape(str(item.get("title") or item.get("property_type") or "경매 물건"))
    region = html.escape(str(item.get("region") or ""))
    address = html.escape(str(item.get("address") or "-"))
    discount_rate = item.get("discount_rate")
    discount_text = "-" if discount_rate is None else f"{discount_rate:.1f}% 할인"
    auction_date = html.escape(str(item.get("auction_date") or "-"))
    source_url = html.escape(str(item.get("source_url") or ""))
    return (
        f"🏠 <b>[신규]</b> {region} {title}\n"
        f"📍 {address}\n"
        f"💰 감정가: {_fmt_krw(item.get('appraisal_price'))} / "
        f"최저가: {_fmt_krw(item.get('min_bid_price'))} ({discount_text})\n"
        f"📅 매각기일: {auction_date}\n"
        f"🔗 <a href=\"{source_url}\">상세보기</a>"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    args = parser.parse_args()

    cfg = load_config(Path(args.config))
    env_cfg = cfg["environment"]
    telegram_cfg = resolve_telegram_config(cfg.get("telegram"))

    collector = CourtAuctionCollector()
    customs_collector = CustomsNoticeCollector()
    search_summaries = []
    collected_listings = []
    raw_searches = _resolve_searches(cfg)
    for raw_search in raw_searches:
        search_cfg = build_search_config(raw_search)
        listings, meta = collector.fetch_all(search_cfg)
        collected_listings.extend(listings)
        meta["source"] = "courtauction"
        search_summaries.append(meta)

    raw_customs_searches = _resolve_customs_searches(cfg)
    for raw_search in raw_customs_searches:
        search_cfg = build_customs_search_config(raw_search)
        notices = customs_collector.fetch_notices(search_cfg)
        normalized = []
        for item in notices:
            detail = {}
            if item.get("detail_url"):
                try:
                    detail = customs_collector.fetch_detail_data(item["detail_url"])
                except Exception:
                    detail = {}
            enriched = dict(item)
            enriched.update(detail)
            normalized.append(normalize_notice(enriched, search=search_cfg))
        collected_listings.extend(normalized)
        search_summaries.append(
            {
                "source": "customs_notice",
                "total_cnt": len(normalized),
                "total_pages": 1,
                "items_fetched": len(normalized),
                "region_name": search_cfg.office_name,
                "search_name": search_cfg.search_name,
            }
        )

    listings = _merge_listings(collected_listings)
    total_cnt = sum(int(item.get("total_cnt", 0)) for item in search_summaries)
    total_pages = sum(int(item.get("total_pages", 0)) for item in search_summaries)
    items_fetched = len(listings)

    db_path = Path(env_cfg["duckdb_path"])
    con = connect(db_path)
    upsert_result = upsert_listings(con, listings)
    alert_matches = filter_alert_listings(
        listings,
        new_listing_ids=upsert_result["new_listing_ids"],
        conditions=cfg.get("alert_conditions"),
    )
    customs_notice_matches = filter_new_customs_notices(
        listings,
        new_listing_ids=upsert_result["new_listing_ids"],
    )
    pruned_count = prune_old_data(con, months=int(env_cfg.get("retain_months", 3)))

    report_name = "multi_source" if len(search_summaries) > 1 else search_summaries[0]["search_name"]
    if raw_searches:
        first_search = build_search_config(raw_searches[0])
        stamp = report_name + "_" + first_search.bid_begin_ymd + "_" + first_search.bid_end_ymd
    else:
        stamp = report_name
    report_path = ROOT / "reports" / f"daily_report_{stamp}.md"
    latest_report = ROOT / "reports" / "daily_report_latest.md"
    write_daily_report(
        report_path,
        report_name=report_name,
        total_cnt=total_cnt,
        pages=total_pages,
        fetched=items_fetched,
        new_count=upsert_result["new_count"],
        alert_match_count=len(alert_matches),
        pruned_count=pruned_count,
        db_path=db_path,
        listings=listings,
        search_summaries=search_summaries,
        alert_matches=alert_matches,
    )
    latest_report.write_text(report_path.read_text(encoding="utf-8"), encoding="utf-8")

    if telegram_cfg.get("enabled"):
        for item in alert_matches:
            send_message(
                telegram_cfg.get("bot_token", ""),
                telegram_cfg.get("chat_id", ""),
                build_listing_message(item),
                parse_mode="HTML",
            )
        for item in customs_notice_matches:
            send_message(
                telegram_cfg.get("bot_token", ""),
                telegram_cfg.get("chat_id", ""),
                build_listing_message(item),
                parse_mode="HTML",
            )

    print(f"total_cnt={total_cnt}")
    print(f"items_fetched={items_fetched}")
    print(f"new_count={upsert_result['new_count']}")
    print(f"alert_match_count={len(alert_matches)}")
    print(f"customs_alert_count={len(customs_notice_matches)}")
    print(f"pruned_count={pruned_count}")
    print(f"duckdb_path={db_path}")
    print(f"report_path={report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


def _fmt_number(value) -> str:
    if value is None:
        return ""
    return str(value)


def _md_cell(value) -> str:
    text = str(value or "")
    return text.replace("|", "/").replace("\n", " ").strip()


def write_daily_report(
    report_path: Path,
    *,
    report_name: str,
    total_cnt: int,
    pages: int,
    fetched: int,
    new_count: int,
    alert_match_count: int,
    pruned_count: int,
    db_path: Path,
    listings: list[dict],
    search_summaries: list[dict],
    alert_matches: list[dict],
) -> None:
    customs_listings = [item for item in listings if item.get("source") == "customs_notice"]
    court_listings = [item for item in listings if item.get("source") != "customs_notice"]

    lines = [
        "# auction-bot daily report",
        "",
        f"- generated_at_utc: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}",
        f"- report_name: `{report_name}`",
        f"- total_cnt: `{total_cnt}`",
        f"- pages: `{pages}`",
        f"- fetched: `{fetched}`",
        f"- new_count: `{new_count}`",
        f"- alert_match_count: `{alert_match_count}`",
        f"- pruned_count: `{pruned_count}`",
        f"- duckdb: `{db_path}`",
        "",
        "## search summaries",
        "",
        "| source | profile | region | total_cnt | pages | fetched |",
        "|---|---|---|---:|---:|---:|",
    ]

    for item in search_summaries:
        lines.append(
            f"| {item.get('source','courtauction')} | {item.get('search_name','')} | {item.get('region_name','')} | "
            f"{item.get('total_cnt',0)} | {item.get('total_pages',0)} | {item.get('items_fetched',0)} |"
        )

    lines.extend(
        [
            "",
            "## customs notices",
            "",
            "| type | title | office | 공고일 | attachments | item preview | market compare | summary |",
            "|---|---|---|---|---|---|---|---|",
        ]
    )
    if customs_listings:
        for item in sorted(
            customs_listings,
            key=lambda row: str(row.get("auction_date") or ""),
            reverse=True,
        )[:10]:
            raw_json = item.get("raw_json") or ""
            attachments = ""
            summary = ""
            item_preview = ""
            market_compare = ""
            if isinstance(raw_json, str):
                try:
                    raw = json.loads(raw_json)
                    attachment_items = raw.get("attachments") or []
                    if attachment_items and isinstance(attachment_items[0], dict):
                        attachments = ", ".join(
                            str(item.get("name") or "")
                            for item in attachment_items
                            if str(item.get("name") or "")
                        )
                    else:
                        attachments = ", ".join(str(item) for item in attachment_items if str(item))
                    summary = str(raw.get("detail_summary") or "")
                    item_samples = raw.get("item_samples") or []
                    if item_samples:
                        item_preview = " | ".join(
                            str(sample.get("item_name") or "")
                            for sample in item_samples[:2]
                            if str(sample.get("item_name") or "")
                        )
                    compare = raw.get("market_compare") or {}
                    if compare:
                        market_compare = (
                            f"{int(compare.get('auction_unit_price') or 0):,}원 vs "
                            f"{int(compare.get('market_median_price') or 0):,}원"
                        )
                except Exception:
                    attachments = ""
                    summary = ""
                    item_preview = ""
                    market_compare = ""
            lines.append(
                f"| {_md_cell(item.get('property_type',''))} | {_md_cell(item.get('title',''))} | {_md_cell(item.get('region',''))} | {_md_cell(item.get('auction_date') or '')} | "
                f"{_md_cell(attachments[:120])} | {_md_cell(item_preview[:120])} | {_md_cell(market_compare[:80])} | {_md_cell(summary[:160])} |"
            )
    else:
        lines.append("| customs notice 0건 |  |  |  |  |  |  |  |")

    lines.extend(
        [
            "",
            "## alert matches",
            "",
            "| source | title | region | type | 감정가 | 최저매각가 | 할인율(%) | score | 매각기일 |",
            "|---|---|---|---|---:|---:|---:|---:|---|",
        ]
    )
    if alert_matches:
        for item in alert_matches[:10]:
            lines.append(
                f"| {item.get('source','')} | {item.get('title','')} | {item.get('region','')} | {item.get('property_type','')} | "
                f"{_fmt_number(item.get('appraisal_price'))} | {_fmt_number(item.get('min_bid_price'))} | "
                f"{_fmt_number(item.get('discount_rate'))} | {_fmt_number(item.get('opportunity_score'))} | "
                f"{item.get('auction_date') or ''} |"
            )
    else:
        lines.append("| - | 신규 조건 매칭 0건 |  |  |  |  |  |  |  |")

    lines.extend(
        [
            "",
            "## top discount listings",
            "",
            "| source | 사건번호 | 제목 | 지역 | 감정가 | 최저매각가 | 할인율(%) | score | 매각기일 |",
            "|---|---|---|---|---:|---:|---:|---:|---|",
        ]
    )
    for item in sorted(
        court_listings,
        key=lambda row: (
            -(row.get("discount_rate") or 0),
            -(row.get("opportunity_score") or 0),
            str(row.get("auction_date") or ""),
        ),
    )[:10]:
        lines.append(
            f"| {item.get('source','')} | {item.get('listing_id','')} | {item.get('title','')} | {item.get('region','')} | "
            f"{_fmt_number(item.get('appraisal_price'))} | {_fmt_number(item.get('min_bid_price'))} | "
            f"{_fmt_number(item.get('discount_rate'))} | {_fmt_number(item.get('opportunity_score'))} | "
            f"{item.get('auction_date') or ''} |"
        )

    lines.extend(
        [
            "",
            "## top opportunity listings",
            "",
            "| source | 사건번호 | 제목 | 지역 | 할인율(%) | round_score | score | 매각기일 |",
            "|---|---|---|---|---:|---:|---:|---|",
        ]
    )
    for item in sorted(
        court_listings,
        key=lambda row: (
            -(row.get("opportunity_score") or 0),
            -(row.get("discount_rate") or 0),
            str(row.get("auction_date") or ""),
        ),
    )[:10]:
        lines.append(
            f"| {item.get('source','')} | {item.get('listing_id','')} | {item.get('title','')} | {item.get('region','')} | "
            f"{_fmt_number(item.get('discount_rate'))} | {_fmt_number(item.get('round_score'))} | "
            f"{_fmt_number(item.get('opportunity_score'))} | {item.get('auction_date') or ''} |"
        )

    lines.extend(
        [
            "",
            "## fetched listings",
            "",
            "| source | 사건번호 | 제목 | 지역 | 감정가 | 최저매각가 | 할인율(%) | score | 매각기일 |",
            "|---|---|---|---|---:|---:|---:|---:|---|",
        ]
    )
    for item in listings[:10]:
        lines.append(
            f"| {item.get('source','')} | {item.get('listing_id','')} | {item.get('title','')} | {item.get('region','')} | "
            f"{_fmt_number(item.get('appraisal_price'))} | {_fmt_number(item.get('min_bid_price'))} | "
            f"{_fmt_number(item.get('discount_rate'))} | {_fmt_number(item.get('opportunity_score'))} | "
            f"{item.get('auction_date') or ''} |"
        )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

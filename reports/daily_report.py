from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


def _fmt_number(value) -> str:
    if value is None:
        return ""
    return str(value)


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
        "| profile | region | total_cnt | pages | fetched |",
        "|---|---|---:|---:|---:|",
    ]

    for item in search_summaries:
        lines.append(
            f"| {item.get('search_name','')} | {item.get('region_name','')} | "
            f"{item.get('total_cnt',0)} | {item.get('total_pages',0)} | {item.get('items_fetched',0)} |"
        )

    lines.extend(
        [
            "",
            "## alert matches",
            "",
            "| title | region | type | 감정가 | 최저매각가 | 할인율(%) | score | 매각기일 |",
            "|---|---|---|---:|---:|---:|---:|---|",
        ]
    )
    if alert_matches:
        for item in alert_matches[:10]:
            lines.append(
                f"| {item.get('title','')} | {item.get('region','')} | {item.get('property_type','')} | "
                f"{_fmt_number(item.get('appraisal_price'))} | {_fmt_number(item.get('min_bid_price'))} | "
                f"{_fmt_number(item.get('discount_rate'))} | {_fmt_number(item.get('opportunity_score'))} | "
                f"{item.get('auction_date') or ''} |"
            )
    else:
        lines.append("| 신규 조건 매칭 0건 |  |  |  |  |  |  |  |")

    lines.extend(
        [
            "",
            "## top discount listings",
            "",
            "| 사건번호 | 제목 | 지역 | 감정가 | 최저매각가 | 할인율(%) | score | 매각기일 |",
            "|---|---|---|---:|---:|---:|---:|---|",
        ]
    )
    for item in sorted(
        listings,
        key=lambda row: (
            -(row.get("discount_rate") or 0),
            -(row.get("opportunity_score") or 0),
            str(row.get("auction_date") or ""),
        ),
    )[:10]:
        lines.append(
            f"| {item.get('listing_id','')} | {item.get('title','')} | {item.get('region','')} | "
            f"{_fmt_number(item.get('appraisal_price'))} | {_fmt_number(item.get('min_bid_price'))} | "
            f"{_fmt_number(item.get('discount_rate'))} | {_fmt_number(item.get('opportunity_score'))} | "
            f"{item.get('auction_date') or ''} |"
        )

    lines.extend(
        [
            "",
            "## top opportunity listings",
            "",
            "| 사건번호 | 제목 | 지역 | 할인율(%) | round_score | score | 매각기일 |",
            "|---|---|---|---:|---:|---:|---|",
        ]
    )
    for item in sorted(
        listings,
        key=lambda row: (
            -(row.get("opportunity_score") or 0),
            -(row.get("discount_rate") or 0),
            str(row.get("auction_date") or ""),
        ),
    )[:10]:
        lines.append(
            f"| {item.get('listing_id','')} | {item.get('title','')} | {item.get('region','')} | "
            f"{_fmt_number(item.get('discount_rate'))} | {_fmt_number(item.get('round_score'))} | "
            f"{_fmt_number(item.get('opportunity_score'))} | {item.get('auction_date') or ''} |"
        )

    lines.extend(
        [
            "",
            "## fetched listings",
            "",
            "| 사건번호 | 제목 | 지역 | 감정가 | 최저매각가 | 할인율(%) | score | 매각기일 |",
            "|---|---|---|---:|---:|---:|---:|---|",
        ]
    )
    for item in listings[:10]:
        lines.append(
            f"| {item.get('listing_id','')} | {item.get('title','')} | {item.get('region','')} | "
            f"{_fmt_number(item.get('appraisal_price'))} | {_fmt_number(item.get('min_bid_price'))} | "
            f"{_fmt_number(item.get('discount_rate'))} | {_fmt_number(item.get('opportunity_score'))} | "
            f"{item.get('auction_date') or ''} |"
        )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

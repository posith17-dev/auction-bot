from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb


DDL = """
CREATE TABLE IF NOT EXISTS listings (
  source VARCHAR,
  listing_id VARCHAR PRIMARY KEY,
  search_name VARCHAR,
  title VARCHAR,
  address VARCHAR,
  region VARCHAR,
  property_type VARCHAR,
  appraisal_price BIGINT,
  min_bid_price BIGINT,
  discount_rate DOUBLE,
  discount_score DOUBLE,
  bid_round INTEGER,
  round_score DOUBLE,
  opportunity_score DOUBLE,
  price_bucket VARCHAR,
  auction_date DATE,
  area_m2 DOUBLE,
  status VARCHAR,
  source_url VARCHAR,
  raw_json VARCHAR,
  created_at TIMESTAMP DEFAULT now(),
  updated_at TIMESTAMP DEFAULT now()
);
"""


REQUIRED_COLUMNS = {
    "search_name": "VARCHAR",
    "discount_score": "DOUBLE",
    "round_score": "DOUBLE",
    "opportunity_score": "DOUBLE",
    "price_bucket": "VARCHAR",
}


UPSERT_SQL = """
INSERT INTO listings (
  source, listing_id, search_name, title, address, region, property_type,
  appraisal_price, min_bid_price, discount_rate, discount_score, bid_round, round_score, opportunity_score, price_bucket,
  auction_date, area_m2, status, source_url, raw_json
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(listing_id) DO UPDATE SET
  source = excluded.source,
  search_name = excluded.search_name,
  title = excluded.title,
  address = excluded.address,
  region = excluded.region,
  property_type = excluded.property_type,
  appraisal_price = excluded.appraisal_price,
  min_bid_price = excluded.min_bid_price,
  discount_rate = excluded.discount_rate,
  discount_score = excluded.discount_score,
  bid_round = excluded.bid_round,
  round_score = excluded.round_score,
  opportunity_score = excluded.opportunity_score,
  price_bucket = excluded.price_bucket,
  auction_date = excluded.auction_date,
  area_m2 = excluded.area_m2,
  status = excluded.status,
  source_url = excluded.source_url,
  raw_json = excluded.raw_json,
  updated_at = now();
"""


def connect(db_path: Path) -> duckdb.DuckDBPyConnection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    con.execute(DDL)
    for column, column_type in REQUIRED_COLUMNS.items():
        con.execute(f"ALTER TABLE listings ADD COLUMN IF NOT EXISTS {column} {column_type}")
    return con


def upsert_listings(con: duckdb.DuckDBPyConnection, listings: list[dict[str, Any]]) -> dict[str, int]:
    if not listings:
        return {
            "new_count": 0,
            "new_listing_ids": [],
            "total_after_upsert": int(con.execute("SELECT COUNT(*) FROM listings").fetchone()[0]),
        }

    listing_ids = [item["listing_id"] for item in listings]
    placeholders = ",".join("?" for _ in listing_ids)
    existing = {
        row[0]
        for row in con.execute(
            f"SELECT listing_id FROM listings WHERE listing_id IN ({placeholders})",
            listing_ids,
        ).fetchall()
    }
    rows = [
        (
            item["source"],
            item["listing_id"],
            item.get("search_name", ""),
            item["title"],
            item["address"],
            item["region"],
            item["property_type"],
            item["appraisal_price"],
            item["min_bid_price"],
            item["discount_rate"],
            item.get("discount_score"),
            item["bid_round"],
            item.get("round_score"),
            item.get("opportunity_score"),
            item.get("price_bucket"),
            item["auction_date"],
            item["area_m2"],
            item["status"],
            item["source_url"],
            item["raw_json"],
        )
        for item in listings
    ]
    con.executemany(UPSERT_SQL, rows)
    total = int(con.execute("SELECT COUNT(*) FROM listings").fetchone()[0])
    new_listing_ids = [x for x in listing_ids if x not in existing]
    return {
        "new_count": len(new_listing_ids),
        "new_listing_ids": new_listing_ids,
        "total_after_upsert": total,
    }


def prune_old_data(con: duckdb.DuckDBPyConnection, months: int = 3) -> int:
    before = int(con.execute("SELECT COUNT(*) FROM listings").fetchone()[0])
    con.execute(
        f"""
        DELETE FROM listings
        WHERE COALESCE(auction_date, CAST(created_at AS DATE))
              < CURRENT_DATE - INTERVAL '{months} months'
        """
    )
    after = int(con.execute("SELECT COUNT(*) FROM listings").fetchone()[0])
    con.execute("CHECKPOINT")
    return before - after

"""Deterministic synthetic data generator for offline demo mode.

Every row produced here is written with ``source='synthetic'`` and the org is
created with ``type='demo'``. The API surfaces that label all the way to the
client, so a demo screen can never be mistaken for real POS data (rules 10/11).

Patterns included (PDF section 4.1 + demo section 11):
* weekly demand shape (weekday/weekend)
* a mild seasonal term
* a holiday spike in the days approaching a named holiday
* realistic multiplicative noise

Reproducibility: everything derives from ``seed`` (default 20261003) via
``random.Random``, so two runs on two machines produce identical CSVs.
"""

from __future__ import annotations

import datetime as _dt
import random
from dataclasses import dataclass, field

from app.projects.foodlink_predict.errors import ValidationFailed
from app.projects.foodlink_predict.ingest import (
    KIND_CALENDAR,
    KIND_INVENTORY,
    KIND_ITEMS,
    KIND_SALES,
)
from app.projects.foodlink_predict.util import date_range, iso

DEFAULT_SEED = 20261003

# Future calendar days emitted so the model always has upcoming holiday flags.
FORECAST_HORIZON_DAYS = 14

# Two locations so transfer recommendation has a real destination to evaluate.
DEMO_LOCATIONS: tuple[dict, ...] = (
    {"id": "loc_main_canteen", "name": "Central Canteen", "lat": 17.3850, "lng": 78.4867, "timezone": "Asia/Kolkata"},
    {"id": "loc_north_canteen", "name": "North Annex Canteen", "lat": 17.4500, "lng": 78.5000, "timezone": "Asia/Kolkata"},
)

# (id, name, category, food_class, shelf_life_hours, unit_cost, unit_price, base_daily_qty)
DEMO_ITEMS: tuple[dict, ...] = (
    {
        "id": "itm_cooked_rice",
        "name": "Cooked Rice",
        "category": "mains",
        "food_class": "cooked",
        "shelf_life_hours": 24.0,
        "unit_cost": 18.0,
        "unit_price": 60.0,
        "base_daily_qty": 210.0,
        "prep_batches": True,
    },
    {
        "id": "itm_cooked_curry",
        "name": "Cooked Dal Curry",
        "category": "mains",
        "food_class": "cooked",
        "shelf_life_hours": 24.0,
        "unit_cost": 22.0,
        "unit_price": 70.0,
        "base_daily_qty": 180.0,
        "prep_batches": True,
    },
    {
        "id": "itm_curd",
        "name": "Curd Cup",
        "category": "dairy",
        "food_class": "chilled",
        "shelf_life_hours": 72.0,
        "unit_cost": 8.0,
        "unit_price": 25.0,
        "base_daily_qty": 120.0,
        "prep_batches": False,
    },
    {
        "id": "itm_salad",
        "name": "Mixed Salad",
        "category": "produce",
        "food_class": "produce",
        "shelf_life_hours": 48.0,
        "unit_cost": 12.0,
        "unit_price": 40.0,
        "base_daily_qty": 90.0,
        "prep_batches": False,
    },
    {
        "id": "itm_bread",
        "name": "Packaged Bread",
        "category": "bakery",
        "food_class": "packaged",
        "shelf_life_hours": 168.0,
        "unit_cost": 15.0,
        "unit_price": 45.0,
        "base_daily_qty": 70.0,
        "prep_batches": False,
    },
)

# Weekday multipliers (Mon=0 .. Sun=6). Cafeterias: quiet weekends, busy Fridays.
WEEKDAY_SHAPE: tuple[float, ...] = (1.05, 1.00, 1.02, 1.08, 1.22, 0.55, 0.35)

# The demo story: a regional holiday a few days after the forecast date, which
# pulls people away from the canteen and strands prepared food.
DEMO_HOLIDAY = {"date_offset_days": 4, "name": "Regional Foundation Day", "region": "default"}

SYNTHETIC_TAG = "DEMO/SYNTHETIC"


@dataclass
class SyntheticDataset:
    """In-memory CSVs plus provenance. Nothing here is ever labelled real."""

    items_csv: str
    locations_csv: str
    sales_csv: str
    inventory_csv: str
    calendar_csv: str
    seed: int = DEFAULT_SEED
    history_days: int = 56
    synthetic: bool = True
    notes: str = field(
        default=(
            "SYNTHETIC demo data. Weekly + seasonal + holiday patterns with seeded noise. "
            "Not derived from any real POS or inventory system."
        )
    )

    def to_dict(self) -> dict:
        return {
            "synthetic": True,
            "tag": SYNTHETIC_TAG,
            "seed": self.seed,
            "history_days": self.history_days,
            "notes": self.notes,
            "items_rows": _count_rows(self.items_csv),
            "sales_rows": _count_rows(self.sales_csv),
            "inventory_rows": _count_rows(self.inventory_csv),
            "calendar_rows": _count_rows(self.calendar_csv),
            "locations": [loc["id"] for loc in DEMO_LOCATIONS],
            "items": [it["id"] for it in DEMO_ITEMS],
            "holiday": DEMO_HOLIDAY,
        }


def _count_rows(text: str) -> int:
    return max(0, len([ln for ln in (text or "").splitlines() if ln.strip()]) - 1)


def _iso_date(d: _dt.date) -> str:
    return d.isoformat()


def _seasonal_factor(day: _dt.date) -> float:
    """Slow sine over the year (amplitude ~8%). Deterministic, no randomness."""
    day_of_year = day.timetuple().tm_yday
    return 1.0 + 0.08 * _sin(2 * 3.141592653589793 * (day_of_year / 365.25))


def _sin(x: float) -> float:
    import math

    return math.sin(x)


def _holiday_lift(day: _dt.date, holiday: _dt.date) -> float:
    """Canteen closes-ish on a holiday: demand drops as the holiday approaches."""
    delta = (holiday - day).days
    if delta == 0:
        return 0.45
    if delta in (1, 2):
        return 0.80
    if delta == 3:
        return 0.95
    return 1.0


def generate(
    *,
    as_of: _dt.datetime,
    history_days: int = 56,
    seed: int = DEFAULT_SEED,
) -> SyntheticDataset:
    """Build the full synthetic corpus ending at ``as_of``.

    Args:
        as_of: 'now' for the demo; deterministic for tests.
        history_days: sales window. 56 days gives the 28-day rolling mean and
            the 4-week rolling-origin backtest something real to work with.
    """
    if history_days < 35:
        raise ValidationFailed(
            f"history_days must be >= 35 to support lag-14, the 28-day rolling mean and a 4-week backtest; got {history_days}"
        )
    rng = random.Random(seed)
    # Sales/calendar are day-granular, so they are anchored to midnight...
    day_anchor = as_of.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=_dt.timezone.utc)
    # ...but inventory carries real timestamps. Anchoring batches to midnight would
    # make the demo's donate-by depend on the hour of day it was run, which is both
    # confusing and flaky. Using the actual time means "prepared 5 hours ago" is
    # true whenever the generator runs.
    holiday = as_of + _dt.timedelta(days=DEMO_HOLIDAY["date_offset_days"])
    start = day_anchor - _dt.timedelta(days=history_days - 1)

    # --- items -------------------------------------------------------------
    item_lines = ["item_id,name,category,food_class,unit,shelf_life_hours,unit_cost,unit_price"]
    for it in DEMO_ITEMS:
        item_lines.append(
            f"{it['id']},{it['name']},{it['category']},{it['food_class']},portion,"
            f"{it['shelf_life_hours']},{it['unit_cost']},{it['unit_price']}"
        )

    loc_lines = ["location_id,name,lat,lng,timezone"]
    for loc in DEMO_LOCATIONS:
        loc_lines.append(f"{loc['id']},{loc['name']},{loc['lat']},{loc['lng']},{loc['timezone']}")

    # --- calendar ----------------------------------------------------------
    cal_lines = ["date,region,is_holiday,holiday_name"]
    for d in date_range(start, day_anchor + _dt.timedelta(days=FORECAST_HORIZON_DAYS)):
        is_hol = d == holiday
        name = DEMO_HOLIDAY["name"] if is_hol else ""
        cal_lines.append(f"{_iso_date(d)},{DEMO_HOLIDAY['region']},{str(is_hol).lower()},{name}")

    # --- sales -------------------------------------------------------------
    sales_lines = ["date,item_id,location_id,qty_sold,promo_flag,revenue"]
    for d in date_range(start, day_anchor):
        for it in DEMO_ITEMS:
            for loc in DEMO_LOCATIONS:
                # The annex runs at ~55% of the main canteen's volume.
                site_scale = 1.0 if loc["id"] == DEMO_LOCATIONS[0]["id"] else 0.55
                promo = rng.random() < 0.12
                expected = (
                    it["base_daily_qty"]
                    * site_scale
                    * WEEKDAY_SHAPE[d.weekday()]
                    * _seasonal_factor(d)
                    * _holiday_lift(d, holiday)
                    * (1.45 if promo else 1.0)
                )
                # Multiplicative lognormal-ish noise; rounded to whole portions.
                noise = rng.gauss(1.0, 0.09)
                qty = max(0, int(round(expected * max(0.2, noise))))
                revenue = round(qty * it["unit_price"], 2)
                sales_lines.append(f"{_iso_date(d)},{it['id']},{loc['id']},{qty},{str(promo).lower()},{revenue}")

    # --- inventory ---------------------------------------------------------
    # The hero scenario: over-prepared cooked rice for `as_of`, expiring that night.
    inv_lines = [
        "batch_id,item_id,location_id,qty,received_or_prepared_at,expires_at,storage"
    ]
    prepared_at = as_of - _dt.timedelta(hours=5)
    inv_lines.append(
        "bat_demo_rice_001,itm_cooked_rice,loc_main_canteen,240,"
        f"{iso(prepared_at)},{iso(prepared_at + _dt.timedelta(hours=20))},hot"
    )
    inv_lines.append(
        "bat_demo_curry_001,itm_cooked_curry,loc_main_canteen,190,"
        f"{iso(prepared_at)},{iso(prepared_at + _dt.timedelta(hours=19))},hot"
    )
    inv_lines.append(
        "bat_demo_curd_001,itm_curd,loc_main_canteen,140,"
        f"{iso(prepared_at)},{iso(prepared_at + _dt.timedelta(hours=70))},chilled"
    )
    inv_lines.append(
        "bat_demo_salad_001,itm_salad,loc_north_canteen,85,"
        f"{iso(prepared_at)},{iso(prepared_at + _dt.timedelta(hours=40))},chilled"
    )
    inv_lines.append(
        "bat_demo_bread_001,itm_bread,loc_main_canteen,64,"
        f"{iso(as_of - _dt.timedelta(days=2))},{iso(as_of + _dt.timedelta(days=5))},ambient"
    )
    # An already-expired batch: exercises the compost path and the "no donation
    # past donate_by" gate.
    inv_lines.append(
        "bat_demo_expired_001,itm_cooked_curry,loc_main_canteen,25,"
        f"{iso(as_of - _dt.timedelta(days=1, hours=8))},{iso(as_of - _dt.timedelta(hours=2))},hot"
    )
    # A clean low-risk batch: fresh produce with plenty of shelf life left.
    inv_lines.append(
        "bat_demo_salad_fresh_001,itm_salad,loc_main_canteen,40,"
        f"{iso(as_of - _dt.timedelta(hours=2))},{iso(as_of + _dt.timedelta(hours=60))},chilled"
    )

    return SyntheticDataset(
        items_csv="\n".join(item_lines),
        locations_csv="\n".join(loc_lines),
        sales_csv="\n".join(sales_lines),
        inventory_csv="\n".join(inv_lines),
        calendar_csv="\n".join(cal_lines),
        seed=seed,
        history_days=history_days,
    )


def load_into_db(sess, org_id: str, dataset: SyntheticDataset) -> dict:
    """Write the synthetic corpus into the database with source='synthetic'."""
    from app.projects.foodlink_predict.ingest import (
        ingest_calendar,
        ingest_inventory,
        ingest_items,
        ingest_sales,
        upsert_location,
    )
    from app.projects.foodlink_predict.util import read_csv_text

    loc_report = {"inserted": 0, "updated": 0, "issues": []}
    for row in read_csv_text(dataset.locations_csv):
        existed = _location_exists(sess, org_id, row["location_id"])
        upsert_location(
            sess,
            org_id,
            row["location_id"],
            name=row.get("name"),
            lat=float(row.get("lat") or 0.0),
            lng=float(row.get("lng") or 0.0),
            timezone=row.get("timezone"),
        )
        loc_report["updated" if existed else "inserted"] += 1

    reports = [
        ingest_items(sess, org_id, dataset.items_csv, source="synthetic"),
        ingest_sales(sess, org_id, dataset.sales_csv, source="synthetic"),
        ingest_inventory(sess, org_id, dataset.inventory_csv, source="synthetic"),
        ingest_calendar(sess, org_id, dataset.calendar_csv, source="synthetic"),
    ]
    return {
        "locations": loc_report,
        **{
            "items": reports[0].to_dict(),
            "sales": reports[1].to_dict(),
            "inventory": reports[2].to_dict(),
            "calendar": reports[3].to_dict(),
        },
        "synthetic": True,
        "tag": SYNTHETIC_TAG,
        "seed": dataset.seed,
        "notes": dataset.notes,
    }


def _location_exists(sess, org_id: str, location_id: str) -> bool:
    from app.projects.foodlink_predict.db import get_by_id
    from app.projects.foodlink_predict.models import Location

    return get_by_id(sess, Location, location_id, org_id) is not None
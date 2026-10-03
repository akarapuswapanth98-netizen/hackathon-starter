"""Unit tests: CSV ingestion, normalisation, validation errors and provenance."""

from __future__ import annotations

import pytest

from app.projects.foodlink_predict.db import session_scope
from app.projects.foodlink_predict.errors import ValidationFailed
from app.projects.foodlink_predict.ingest import (
    detect_kind,
    ingest_any,
    ingest_calendar,
    ingest_inventory,
    ingest_items,
    ingest_sales,
)

ITEMS_CSV = """item_id,name,category,food_class,shelf_life_hours,unit_cost,unit_price
itm_rice,Cooked Rice,mains,cooked,24,18,60
itm_bread,Packaged Bread,bakery,packaged,168,15,45
"""

LOCATIONS_CSV = """location_id,name,lat,lng,timezone
loc_a,Main,17.3850,78.4867,UTC
"""


def _seed_catalogue(org_id):
    with session_scope() as sess:
        ingest_items(sess, org_id, ITEMS_CSV)
        from app.projects.foodlink_predict.ingest import upsert_location

        upsert_location(sess, org_id, "loc_a", name="Main", lat=17.385, lng=78.4867)


# ---------------------------------------------------------- kind detect --
def test_detects_each_csv_kind():
    assert detect_kind(ITEMS_CSV) == "items"
    assert detect_kind("date,item_id,location_id,qty_sold,promo_flag,revenue\n2026-01-01,i,l,1,false,1") == "sales"
    assert detect_kind("batch_id,item_id,location_id,qty,expires_at,storage\nb,i,l,1,2026-01-01,hot") == "inventory"
    assert detect_kind("date,region,is_holiday,holiday_name\n2026-01-01,r,true,H") == "calendar"


def test_unknown_csv_is_rejected_with_the_headers_named():
    with pytest.raises(ValidationFailed) as exc:
        detect_kind("alpha,beta\n1,2")
    assert exc.value.issues[0].code == "unknown_kind"
    # The headers must reach the HTTP body too (via `detail`), not just the
    # structured issues, because that is all the starter's handler emits.
    assert "alpha" in exc.value.detail


def test_empty_csv_is_rejected():
    with pytest.raises(ValidationFailed):
        detect_kind("   ")


# -------------------------------------------------------------- items ---
def test_ingest_items_inserts_and_upserts(org_id):
    with session_scope() as sess:
        first = ingest_items(sess, org_id, ITEMS_CSV)
        assert first.inserted == 2 and first.updated == 0 and first.ok
        second = ingest_items(sess, org_id, ITEMS_CSV)
        assert second.inserted == 0 and second.updated == 2


def test_ingest_items_reports_duplicate_ids_in_one_file(org_id):
    csv = ITEMS_CSV + "itm_rice,Cooked Rice Again,mains,cooked,24,18,60\n"
    with session_scope() as sess:
        rep = ingest_items(sess, org_id, csv)
    assert rep.issues
    assert rep.issues[0].code == "duplicate"


def test_ingest_items_reports_missing_columns(org_id):
    with session_scope() as sess:
        rep = ingest_items(sess, org_id, "item_id,name\nx,y\n")
    assert not rep.ok
    assert rep.issues[0].code == "missing_columns"


# -------------------------------------------------------------- sales ---
def test_ingest_sales_happy_path(org_id):
    _seed_catalogue(org_id)
    csv = "date,item_id,location_id,qty_sold,promo_flag,revenue\n2026-01-01,itm_rice,loc_a,100,false,6000\n"
    with session_scope() as sess:
        rep = ingest_sales(sess, org_id, csv)
    assert rep.ok and rep.inserted == 1


def test_ingest_sales_flags_unknown_item(org_id):
    _seed_catalogue(org_id)
    csv = "date,item_id,location_id,qty_sold\n2026-01-01,ghost_item,loc_a,10\n"
    with session_scope() as sess:
        rep = ingest_sales(sess, org_id, csv)
    assert rep.issues[0].code == "unknown_item"
    assert rep.skipped == 1


def test_ingest_sales_flags_unknown_location(org_id):
    _seed_catalogue(org_id)
    csv = "date,item_id,location_id,qty_sold\n2026-01-01,itm_rice,ghost_loc,10\n"
    with session_scope() as sess:
        rep = ingest_sales(sess, org_id, csv)
    assert rep.issues[0].code == "unknown_location"


def test_ingest_sales_rejects_negative_quantity(org_id):
    _seed_catalogue(org_id)
    csv = "date,item_id,location_id,qty_sold\n2026-01-01,itm_rice,loc_a,-5\n"
    with session_scope() as sess:
        rep = ingest_sales(sess, org_id, csv)
    assert rep.issues[0].code == "negative_quantity"


def test_ingest_sales_rejects_invalid_date(org_id):
    _seed_catalogue(org_id)
    csv = "date,item_id,location_id,qty_sold\nnot-a-date,itm_rice,loc_a,5\n"
    with session_scope() as sess:
        rep = ingest_sales(sess, org_id, csv)
    assert rep.issues[0].code == "invalid_date"


def test_ingest_sales_rejects_non_numeric_quantity(org_id):
    _seed_catalogue(org_id)
    csv = "date,item_id,location_id,qty_sold\n2026-01-01,itm_rice,loc_a,many\n"
    with session_scope() as sess:
        rep = ingest_sales(sess, org_id, csv)
    assert rep.issues[0].code == "bad_type"


def test_duplicate_sales_day_is_an_update_not_a_duplicate_row(org_id):
    _seed_catalogue(org_id)
    csv = "date,item_id,location_id,qty_sold\n2026-01-01,itm_rice,loc_a,100\n"
    csv2 = "date,item_id,location_id,qty_sold\n2026-01-01,itm_rice,loc_a,140\n"
    with session_scope() as sess:
        ingest_sales(sess, org_id, csv)
        rep = ingest_sales(sess, org_id, csv2)
    assert rep.updated == 1 and rep.inserted == 0


def test_header_aliases_are_accepted(org_id):
    _seed_catalogue(org_id)
    csv = "Sales Date,SKU,Site,Sold,On Promo,Sales Value\n2026-01-01,itm_rice,loc_a,55,yes,3300\n"
    with session_scope() as sess:
        rep = ingest_sales(sess, org_id, csv)
    assert rep.ok and rep.inserted == 1


# ---------------------------------------------------------- inventory ---
def test_ingest_inventory_happy_path(org_id):
    _seed_catalogue(org_id)
    csv = "batch_id,item_id,location_id,qty,prepared_at,expires_at,storage\nb1,itm_rice,loc_a,240,2026-01-01T01:00:00Z,2026-01-01T21:00:00Z,hot\n"
    with session_scope() as sess:
        rep = ingest_inventory(sess, org_id, csv)
    assert rep.ok and rep.inserted == 1


def test_ingest_inventory_rejects_negative_stock(org_id):
    _seed_catalogue(org_id)
    csv = "item_id,location_id,qty,expires_at\nitm_rice,loc_a,-3,2026-01-02T00:00:00Z\n"
    with session_scope() as sess:
        rep = ingest_inventory(sess, org_id, csv)
    assert rep.issues[0].code == "negative_quantity"


def test_ingest_inventory_rejects_expiry_before_preparation(org_id):
    _seed_catalogue(org_id)
    csv = "item_id,location_id,qty,prepared_at,expires_at\nitm_rice,loc_a,10,2026-01-05T00:00:00Z,2026-01-01T00:00:00Z\n"
    with session_scope() as sess:
        rep = ingest_inventory(sess, org_id, csv)
    assert rep.issues[0].code == "invalid_range"


def test_ingest_inventory_generates_a_batch_id_when_absent(org_id):
    _seed_catalogue(org_id)
    csv = "item_id,location_id,qty,expires_at\nitm_rice,loc_a,10,2026-01-02T00:00:00Z\n"
    with session_scope() as sess:
        rep = ingest_inventory(sess, org_id, csv)
    assert rep.ok and rep.inserted == 1


def test_ingest_inventory_rejects_bad_expiry(org_id):
    _seed_catalogue(org_id)
    csv = "item_id,location_id,qty,expires_at\nitm_rice,loc_a,10,whenever\n"
    with session_scope() as sess:
        rep = ingest_inventory(sess, org_id, csv)
    assert rep.issues[0].code == "invalid_date"


# ------------------------------------------------------------ calendar --
def test_ingest_calendar_sets_day_of_week_from_the_date(org_id):
    csv = "date,region,is_holiday,holiday_name\n2026-10-05,r,true,Festival\n"
    with session_scope() as sess:
        rep = ingest_calendar(sess, org_id, csv)
    assert rep.ok and rep.inserted == 1
    from app.projects.foodlink_predict.models import CalendarDay

    with session_scope() as sess:
        row = sess.query(CalendarDay).filter(CalendarDay.org_id == org_id).one()
        assert row.day_of_week == 0  # 2026-10-05 is a Monday
        assert row.is_holiday is True


# ----------------------------------------------------------- dispatch ---
def test_ingest_any_dispatches_on_detection(org_id):
    _seed_catalogue(org_id)
    csv = "item_id,name,category,food_class\nitm_new,New Item,dairy,chilled\n"
    with session_scope() as sess:
        rep = ingest_any(sess, org_id, csv)
    assert rep.kind == "items" and rep.inserted == 1


def test_ingest_any_honours_an_explicit_kind(org_id):
    with session_scope() as sess:
        rep = ingest_any(sess, org_id, ITEMS_CSV, kind="items")
    assert rep.kind == "items"


def test_ingest_any_rejects_an_unsupported_kind(org_id):
    with pytest.raises(ValidationFailed):
        with session_scope() as sess:
            ingest_any(sess, org_id, ITEMS_CSV, kind="telepathy")


# --------------------------------------------------------- provenance ---
def test_synthetic_source_is_persisted_on_every_row(seeded):
    """Synthetic rows must be distinguishable in the database, not just in prose."""
    from sqlalchemy import func, select

    from app.projects.foodlink_predict.models import SalesDaily

    with session_scope() as sess:
        total = sess.execute(select(func.count()).select_from(SalesDaily).where(SalesDaily.org_id == seeded)).scalar_one()
        synth = sess.execute(
            select(func.count()).select_from(SalesDaily).where(SalesDaily.org_id == seeded, SalesDaily.source == "synthetic")
        ).scalar_one()
    assert total > 0
    assert synth == total


def test_uploaded_rows_are_labelled_uploaded(org_id):
    _seed_catalogue(org_id)
    csv = "date,item_id,location_id,qty_sold\n2026-01-01,itm_rice,loc_a,10\n"
    with session_scope() as sess:
        ingest_sales(sess, org_id, csv, source="uploaded")
    from app.projects.foodlink_predict.models import SalesDaily

    with session_scope() as sess:
        row = sess.query(SalesDaily).filter(SalesDaily.org_id == org_id).one()
        assert row.source == "uploaded"
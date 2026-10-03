"""CSV ingestion and normalisation.

Reuses the toolkit's existing ``POST /api/upload`` as the transport (the file
lands in the same uploads dir, same extension allow-list) and adds the
domain-specific normalisation the PDF calls for.

Validation is *row-level and reportable*: every problem becomes an issue with a
row number and a field name, and the caller decides whether to reject the whole
batch or accept the good rows. Nothing is dropped silently.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Any, Iterable

from app.projects.foodlink_predict.errors import ValidationFailed
from app.projects.foodlink_predict.models import Batch, CalendarDay, Item, Location, SalesDaily
from app.projects.foodlink_predict.util import (
    new_id,
    parse_date,
    parse_datetime,
    read_csv_text,
    to_bool,
    to_float,
)

# Accepted header spellings -> canonical column. Keeps the CSV contract forgiving
# about naming while the stored schema stays strict.
SALES_ALIASES: dict[str, str] = {
    "date": "date",
    "day": "date",
    "sales_date": "date",
    "item": "item_id",
    "item_id": "item_id",
    "item_code": "item_id",
    "sku": "item_id",
    "product": "item_id",
    "location": "location_id",
    "location_id": "location_id",
    "site": "location_id",
    "store": "location_id",
    "qty_sold": "qty_sold",
    "quantity_sold": "qty_sold",
    "qty": "qty_sold",
    "sold": "qty_sold",
    "units_sold": "qty_sold",
    "promo": "promo_flag",
    "promo_flag": "promo_flag",
    "on_promo": "promo_flag",
    "is_promo": "promo_flag",
    "revenue": "revenue",
    "sales_value": "revenue",
}

INVENTORY_ALIASES: dict[str, str] = {
    "batch": "batch_id",
    "batch_id": "batch_id",
    "lot": "batch_id",
    "lot_id": "batch_id",
    "item": "item_id",
    "item_id": "item_id",
    "sku": "item_id",
    "location": "location_id",
    "location_id": "location_id",
    "site": "location_id",
    "qty": "qty",
    "quantity": "qty",
    "qty_on_hand": "qty",
    "on_hand": "qty",
    "prepared_at": "received_or_prepared_at",
    "prepared": "received_or_prepared_at",
    "received_at": "received_or_prepared_at",
    "prepared_or_received": "received_or_prepared_at",
    "expiry": "expires_at",
    "expires_at": "expires_at",
    "expiry_date": "expires_at",
    "use_by": "expires_at",
    "storage": "storage",
}

ITEM_ALIASES: dict[str, str] = {
    "item": "item_id",
    "item_id": "item_id",
    "sku": "item_id",
    "name": "name",
    "item_name": "name",
    "category": "category",
    "unit": "unit",
    "uom": "unit",
    "shelf_life_hours": "shelf_life_hours",
    "shelf_life": "shelf_life_hours",
    "food_class": "food_class",
    "class": "food_class",
    "unit_cost": "unit_cost",
    "cost": "unit_cost",
    "unit_price": "unit_price",
    "price": "unit_price",
}

CALENDAR_ALIASES: dict[str, str] = {
    "date": "date",
    "day": "date",
    "region": "region",
    "is_holiday": "is_holiday",
    "holiday": "is_holiday",
    "holiday_flag": "is_holiday",
    "holiday_name": "holiday_name",
    "name": "holiday_name",
    "weather": "weather",
}

KIND_SALES = "sales"
KIND_INVENTORY = "inventory"
KIND_ITEMS = "items"
KIND_CALENDAR = "calendar"

_ALIASES = {
    KIND_SALES: SALES_ALIASES,
    KIND_INVENTORY: INVENTORY_ALIASES,
    KIND_ITEMS: ITEM_ALIASES,
    KIND_CALENDAR: CALENDAR_ALIASES,
}

REQUIRED_COLUMNS = {
    KIND_SALES: ("date", "item_id", "location_id", "qty_sold"),
    KIND_INVENTORY: ("item_id", "location_id", "qty", "expires_at"),
    KIND_ITEMS: ("item_id", "name", "category", "food_class"),
    KIND_CALENDAR: ("date",),
}


@dataclass
class Issue:
    """One actionable validation problem."""

    row: int
    field: str
    code: str
    message: str

    def to_dict(self) -> dict:
        return {"row": self.row, "field": self.field, "code": self.code, "message": self.message}


@dataclass
class IngestReport:
    kind: str
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    issues: list[Issue] = field(default_factory=list)
    source: str = "uploaded"

    @property
    def ok(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "inserted": self.inserted,
            "updated": self.updated,
            "skipped": self.skipped,
            "issues": [i.to_dict() for i in self.issues],
            "issue_count": len(self.issues),
            "ok": self.ok,
            "source": self.source,
        }


def _canon(row: dict[str, str], kind: str) -> dict[str, str]:
    aliases = _ALIASES[kind]
    out: dict[str, str] = {}
    for raw_key, raw_val in row.items():
        key = aliases.get(str(raw_key).strip().lower())
        if key:
            out[key] = raw_val
    return out


def detect_kind(text: str, hint: str | None = None) -> str:
    """Infer the CSV kind from its headers (or trust an explicit hint).

    Scoring weighs how many of a kind's REQUIRED columns are present first, then
    how many of its known headers appear at all. The second term breaks ties the
    first one cannot: a ``date,region,is_holiday,holiday_name`` file satisfies
    the (single-column) calendar requirement as well as the sales one, and only
    the second term can tell those two apart.
    """
    if hint:
        if hint not in _ALIASES:
            raise ValidationFailed(
                f"Unsupported CSV kind '{hint}'",
                issues=[
                    Issue(
                        row=0,
                        field="kind",
                        code="unknown_kind",
                        message=f"Supported kinds: {sorted(_ALIASES)}",
                    )
                ],
            )
        return hint

    try:
        rows = read_csv_text(text)
    except ValueError as exc:
        raise ValidationFailed(f"CSV could not be parsed: {exc}") from exc
    if not rows:
        raise ValidationFailed("CSV contains a header but no data rows")

    headers = [str(h).strip().lower() for h in rows[0].keys()]
    scores: dict[str, tuple[int, int]] = {}
    for kind, aliases in _ALIASES.items():
        keys = {aliases.get(h) for h in headers}
        scores[kind] = (
            sum(1 for c in REQUIRED_COLUMNS[kind] if c in keys),
            len({k for k in keys if k}),
        )

    # Most specific kind wins: more required columns matched, then more known
    # headers, then the smaller requirement to satisfy.
    best = max(
        scores,
        key=lambda k: (scores[k][0], scores[k][1], -len(REQUIRED_COLUMNS[k])),
    )
    if scores[best][0] == 0:
        raise ValidationFailed(
            "Could not identify CSV type. Recognise one of: sales, inventory, items, calendar",
            issues=[
                Issue(
                    row=0,
                    field="header",
                    code="unknown_kind",
                    message=(
                        f"headers={sorted(headers)} matched none of the known CSV types"
                    ),
                )
            ],
        )
    return best


def check_columns(rows: list[dict[str, str]], kind: str) -> list[Issue]:
    """Required-column check with the missing names spelled out."""
    aliases = _ALIASES[kind]
    present = {aliases.get(h) for h in rows[0].keys()} if rows else set()
    missing = [c for c in REQUIRED_COLUMNS[kind] if c not in present]
    if not missing:
        return []
    return [
        Issue(
            row=0,
            field=",".join(missing),
            code="missing_columns",
            message=(
                f"{kind} CSV is missing required column(s): {', '.join(missing)}. "
                f"Accepted aliases include: {sorted(a for a, v in aliases.items() if v in missing)}"
            ),
        )
    ]


# --------------------------------------------------------------------------
# Catalogue
# --------------------------------------------------------------------------
def upsert_item(
    sess,
    org_id: str,
    item_id: str,
    *,
    name: str | None = None,
    category: str | None = None,
    unit: str | None = None,
    shelf_life_hours: float | None = None,
    food_class: str | None = None,
    unit_cost: float | None = None,
    unit_price: float | None = None,
    unit_weight_kg: float | None = None,
) -> Item:
    from app.projects.foodlink_predict.db import get_by_id

    existing = get_by_id(sess, Item, item_id, org_id)
    if existing is not None:
        # Never clobber safety-relevant fields with None from a partial upload.
        for field_name, value in (
            ("name", name),
            ("category", category),
            ("unit", unit),
            ("shelf_life_hours", shelf_life_hours),
            ("food_class", food_class),
            ("unit_cost", unit_cost),
            ("unit_price", unit_price),
            ("unit_weight_kg", unit_weight_kg),
        ):
            if value is not None:
                setattr(existing, field_name, value)
        return existing

    resolved_name = name or item_id
    resolved_class = (food_class or "cooked").strip().lower()
    resolved_category = (category or "other").strip().lower()
    shelf = float(shelf_life_hours) if shelf_life_hours is not None else 24.0
    item = Item(
        id=item_id,
        org_id=org_id,
        name=resolved_name,
        category=resolved_category,
        unit=(unit or "portion"),
        shelf_life_hours=shelf,
        food_class=resolved_class,
        unit_cost=float(unit_cost or 0.0),
        unit_price=float(unit_price or 0.0),
        unit_weight_kg=float(unit_weight_kg if unit_weight_kg is not None else 0.35),
    )
    sess.add(item)
    sess.flush()
    return item


def upsert_location(
    sess,
    org_id: str,
    location_id: str,
    *,
    name: str | None = None,
    lat: float | None = None,
    lng: float | None = None,
    timezone: str | None = None,
) -> Location:
    from app.projects.foodlink_predict.db import get_by_id

    existing = get_by_id(sess, Location, location_id, org_id)
    if existing is not None:
        for field_name, value in (("name", name), ("lat", lat), ("lng", lng), ("timezone", timezone)):
            if value is not None:
                setattr(existing, field_name, value)
        return existing

    loc = Location(
        id=location_id,
        org_id=org_id,
        name=name or location_id,
        lat=float(lat or 0.0),
        lng=float(lng or 0.0),
        timezone=timezone or "UTC",
    )
    sess.add(loc)
    sess.flush()
    return loc


# --------------------------------------------------------------------------
# Ingesters
# --------------------------------------------------------------------------
def ingest_items(sess, org_id: str, text: str, *, source: str = "uploaded") -> IngestReport:
    rows = read_csv_text(text)
    report = IngestReport(kind=KIND_ITEMS, source=source)
    if issues := check_columns(rows, KIND_ITEMS):
        report.issues.extend(issues)
        return report
    seen: set[str] = set()
    for idx, raw in enumerate(rows, start=2):
        row = _canon(raw, KIND_ITEMS)
        item_id = (row.get("item_id") or "").strip()
        if not item_id:
            report.issues.append(Issue(idx, "item_id", "missing_value", "item_id is required"))
            continue
        if item_id in seen:
            report.issues.append(
                Issue(idx, "item_id", "duplicate", f"item_id '{item_id}' appears more than once in this file")
            )
            report.skipped += 1
            continue
        seen.add(item_id)
        try:
            # shelf_life_hours is NOT a required column, so an absent value must
            # fall back to the default rather than fail the row. A value that is
            # present but unparseable (or non-positive) is still an error -
            # defaulting that would hide a mistake on a safety-relevant field.
            shelf_raw = (row.get("shelf_life_hours") or "").strip()
            shelf = to_float(shelf_raw, field="shelf_life_hours", allow_negative=True) if shelf_raw else None
            if shelf is not None and shelf <= 0:
                report.issues.append(
                    Issue(idx, "shelf_life_hours", "invalid_range", f"shelf_life_hours must be > 0, got {shelf}")
                )
                continue
            cost = to_float(row.get("unit_cost"), field="unit_cost", allow_negative=True) if row.get("unit_cost") else 0.0
            price = to_float(row.get("unit_price"), field="unit_price", allow_negative=True) if row.get("unit_price") else 0.0
        except ValueError as exc:
            report.issues.append(Issue(idx, "numeric", "bad_type", str(exc)))
            continue
        from app.projects.foodlink_predict.db import get_by_id

        existed = get_by_id(sess, Item, item_id, org_id) is not None
        upsert_item(
            sess,
            org_id,
            item_id,
            name=row.get("name") or item_id,
            category=row.get("category"),
            unit=row.get("unit"),
            shelf_life_hours=shelf,
            food_class=row.get("food_class"),
            unit_cost=cost,
            unit_price=price,
        )
        report.updated += int(existed)
        report.inserted += int(not existed)
    return report


def ingest_sales(sess, org_id: str, text: str, *, source: str = "uploaded") -> IngestReport:
    rows = read_csv_text(text)
    report = IngestReport(kind=KIND_SALES, source=source)
    if issues := check_columns(rows, KIND_SALES):
        report.issues.extend(issues)
        return report

    from app.projects.foodlink_predict.db import get_by_id

    for idx, raw in enumerate(rows, start=2):
        row = _canon(raw, KIND_SALES)
        item_id = (row.get("item_id") or "").strip()
        loc_id = (row.get("location_id") or "").strip()
        if not item_id or not loc_id:
            report.issues.append(Issue(idx, "item_id/location_id", "missing_value", "item_id and location_id are required"))
            continue

        # Referential checks: report unknown references instead of creating rows.
        if get_by_id(sess, Item, item_id, org_id) is None:
            report.issues.append(
                Issue(idx, "item_id", "unknown_item", f"item '{item_id}' is not in the catalogue for this organization")
            )
            report.skipped += 1
            continue
        if get_by_id(sess, Location, loc_id, org_id) is None:
            report.issues.append(
                Issue(idx, "location_id", "unknown_location", f"location '{loc_id}' is not registered for this organization")
            )
            report.skipped += 1
            continue

        try:
            day = parse_date(row.get("date"), field="date")
        except ValueError as exc:
            report.issues.append(Issue(idx, "date", "invalid_date", str(exc)))
            continue
        try:
            qty = to_float(row.get("qty_sold"), field="qty_sold", allow_negative=True)
            revenue = to_float(row.get("revenue"), field="revenue", allow_negative=True) if row.get("revenue") else 0.0
        except ValueError as exc:
            report.issues.append(Issue(idx, "qty_sold", "bad_type", str(exc)))
            continue
        if qty < 0:
            report.issues.append(Issue(idx, "qty_sold", "negative_quantity", f"qty_sold must be >= 0, got {qty}"))
            continue

        existing = (
            sess.query(SalesDaily)
            .filter(
                SalesDaily.org_id == org_id,
                SalesDaily.date == day,
                SalesDaily.item_id == item_id,
                SalesDaily.location_id == loc_id,
            )
            .one_or_none()
        )
        if existing is not None:
            # Same natural key re-uploaded: overwrite, count as update, do not duplicate.
            existing.qty_sold = qty
            existing.revenue = revenue
            existing.promo_flag = to_bool(row.get("promo_flag"), False)
            existing.source = source
            report.updated += 1
            continue
        sess.add(
            SalesDaily(
                org_id=org_id,
                date=day,
                item_id=item_id,
                location_id=loc_id,
                qty_sold=qty,
                promo_flag=to_bool(row.get("promo_flag"), False),
                revenue=revenue,
                source=source,
            )
        )
        report.inserted += 1
    sess.flush()
    return report


def ingest_inventory(sess, org_id: str, text: str, *, source: str = "uploaded") -> IngestReport:
    rows = read_csv_text(text)
    report = IngestReport(kind=KIND_INVENTORY, source=source)
    if issues := check_columns(rows, KIND_INVENTORY):
        report.issues.extend(issues)
        return report

    from app.projects.foodlink_predict.db import get_by_id

    for idx, raw in enumerate(rows, start=2):
        row = _canon(raw, KIND_INVENTORY)
        item_id = (row.get("item_id") or "").strip()
        loc_id = (row.get("location_id") or "").strip()
        if not item_id or not loc_id:
            report.issues.append(Issue(idx, "item_id/location_id", "missing_value", "item_id and location_id are required"))
            continue
        if get_by_id(sess, Item, item_id, org_id) is None:
            report.issues.append(Issue(idx, "item_id", "unknown_item", f"item '{item_id}' is not in the catalogue"))
            report.skipped += 1
            continue
        if get_by_id(sess, Location, loc_id, org_id) is None:
            report.issues.append(Issue(idx, "location_id", "unknown_location", f"location '{loc_id}' is not registered"))
            report.skipped += 1
            continue
        try:
            qty = to_float(row.get("qty"), field="qty", allow_negative=True)
        except ValueError as exc:
            report.issues.append(Issue(idx, "qty", "bad_type", str(exc)))
            continue
        if qty < 0:
            report.issues.append(Issue(idx, "qty", "negative_quantity", f"qty must be >= 0, got {qty}"))
            continue
        try:
            expires = parse_datetime(row.get("expires_at"), field="expires_at")
        except ValueError as exc:
            report.issues.append(Issue(idx, "expires_at", "invalid_date", str(exc)))
            continue
        prepared_raw = row.get("received_or_prepared_at")
        try:
            prepared = parse_datetime(prepared_raw, field="received_or_prepared_at") if prepared_raw else expires
        except ValueError as exc:
            report.issues.append(Issue(idx, "received_or_prepared_at", "invalid_date", str(exc)))
            continue
        if expires < prepared:
            report.issues.append(
                Issue(idx, "expires_at", "invalid_range", f"expires_at ({expires.isoformat()}) precedes prepared_at")
            )
            continue

        batch_id = (row.get("batch_id") or "").strip() or new_id("bat")
        existing = get_by_id(sess, Batch, batch_id, org_id)
        storage = (row.get("storage") or "ambient").strip().lower()
        if existing is not None:
            existing.qty = qty
            existing.received_or_prepared_at = prepared
            existing.expires_at = expires
            existing.storage = storage
            report.updated += 1
            continue
        sess.add(
            Batch(
                id=batch_id,
                org_id=org_id,
                item_id=item_id,
                location_id=loc_id,
                qty=qty,
                received_or_prepared_at=prepared,
                expires_at=expires,
                storage=storage,
            )
        )
        report.inserted += 1
    sess.flush()
    return report


def ingest_calendar(sess, org_id: str, text: str, *, source: str = "uploaded") -> IngestReport:
    rows = read_csv_text(text)
    report = IngestReport(kind=KIND_CALENDAR, source=source)
    if issues := check_columns(rows, KIND_CALENDAR):
        report.issues.extend(issues)
        return report
    for idx, raw in enumerate(rows, start=2):
        row = _canon(raw, KIND_CALENDAR)
        try:
            day = parse_date(row.get("date"), field="date")
        except ValueError as exc:
            report.issues.append(Issue(idx, "date", "invalid_date", str(exc)))
            continue
        existing = (
            sess.query(CalendarDay)
            .filter(CalendarDay.org_id == org_id, CalendarDay.date == day)
            .one_or_none()
        )
        values = dict(
            region=(row.get("region") or "default").strip(),
            is_holiday=to_bool(row.get("is_holiday"), False),
            holiday_name=(row.get("holiday_name") or None),
            day_of_week=day.weekday(),
            weather=(row.get("weather") or None),
        )
        if existing is not None:
            for k, v in values.items():
                setattr(existing, k, v)
            report.updated += 1
            continue
        sess.add(CalendarDay(org_id=org_id, date=day, **values))
        report.inserted += 1
    sess.flush()
    return report


def ingest_any(sess, org_id: str, text: str, *, kind: str | None = None, source: str = "uploaded") -> IngestReport:
    """Dispatch on detected kind. This is what the API endpoint calls."""
    resolved = detect_kind(text, kind)
    if resolved == KIND_SALES:
        return ingest_sales(sess, org_id, text, source=source)
    if resolved == KIND_INVENTORY:
        return ingest_inventory(sess, org_id, text, source=source)
    if resolved == KIND_ITEMS:
        return ingest_items(sess, org_id, text, source=source)
    if resolved == KIND_CALENDAR:
        return ingest_calendar(sess, org_id, text, source=source)
    raise ValidationFailed(f"Unsupported CSV kind '{resolved}'")


def summarize_reports(reports: Iterable[IngestReport]) -> dict:
    reports = list(reports)
    total_issues = sum(len(r.issues) for r in reports)
    return {
        "files": [r.to_dict() for r in reports],
        "inserted": sum(r.inserted for r in reports),
        "updated": sum(r.updated for r in reports),
        "skipped": sum(r.skipped for r in reports),
        "issue_count": total_issues,
        "ok": total_issues == 0,
    }

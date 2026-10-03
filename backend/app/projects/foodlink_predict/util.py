"""Small deterministic helpers shared across the project.

Deliberately dependency-free (stdlib only) so importing the request path never
pulls pandas/numpy/sklearn. Those stay behind lazy imports in ml/.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
import uuid
from typing import Any

# --------------------------------------------------------------------------
# Time
# --------------------------------------------------------------------------
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def as_utc(value: Any) -> _dt.datetime | None:
    """Normalise to timezone-aware UTC.

    Accepts datetime, date, or an ISO-8601 string, because risk/rationale payloads
    are passed around as JSON-shaped dicts (``to_dict()`` output) and then get
    validated. Parsing here - once, at the boundary - avoids a whole class of
    "str has no attribute tzinfo" failures deep inside the validator.

    Naive datetimes are *assumed* UTC. The demo works in UTC end to end; mixing
    naive and aware values is the usual source of off-by-one-day bugs.
    """
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = parse_datetime(value)
        except ValueError:
            return None
    if isinstance(value, _dt.datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=_dt.timezone.utc)
        return value.astimezone(_dt.timezone.utc)
    if isinstance(value, _dt.date):
        return _dt.datetime(value.year, value.month, value.day, tzinfo=_dt.timezone.utc)
    return None


def parse_datetime(value: Any, *, field: str = "datetime") -> _dt.datetime:
    """Parse an ISO-8601 string / date / datetime. Raises ValueError if unusable."""
    if isinstance(value, _dt.datetime):
        return as_utc(value)  # type: ignore[return-value]
    if isinstance(value, _dt.date):
        return _dt.datetime(value.year, value.month, value.day, tzinfo=_dt.timezone.utc)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            raise ValueError(f"{field} is empty")
        candidate = raw.replace("Z", "+00:00").replace("z", "+00:00")
        try:
            return as_utc(_dt.datetime.fromisoformat(candidate))  # type: ignore[return-value]
        except ValueError:
            pass
        if _DATE_RE.match(raw):
            d = _dt.date.fromisoformat(raw)
            return _dt.datetime(d.year, d.month, d.day, tzinfo=_dt.timezone.utc)
        raise ValueError(f"{field} '{value}' is not a valid ISO-8601 date/datetime")
    raise ValueError(f"{field} must be a string or datetime, got {type(value).__name__}")


def parse_date(value: Any, *, field: str = "date") -> _dt.date:
    dtv = parse_datetime(value, field=field)
    return dtv.date()  # type: ignore[union-attr]


def iso(value: _dt.datetime | None) -> str | None:
    v = as_utc(value)
    return v.isoformat().replace("+00:00", "Z") if v else None


def hours_until(target: _dt.datetime | None, *, now: _dt.datetime | None = None) -> float:
    """Signed hours from now to target. Negative means already past."""
    t = as_utc(target)
    if t is None:
        return float("-inf")
    ref = as_utc(now) or utcnow()
    return (t - ref).total_seconds() / 3600.0


def add_hours(base: _dt.datetime, hours: float) -> _dt.datetime:
    return as_utc(base) + _dt.timedelta(hours=float(hours))  # type: ignore[operator]


def date_range(start: _dt.date, end: _dt.date) -> list[_dt.date]:
    """Inclusive day range. Empty when end < start (never loops forever)."""
    if end < start:
        return []
    out, cur = [], start
    while cur <= end:
        out.append(cur)
        cur += _dt.timedelta(days=1)
    return out


# --------------------------------------------------------------------------
# Ids + versions
# --------------------------------------------------------------------------
def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def stable_version(parts: Any) -> str:
    """Content-addressed version tag.

    Same inputs -> same tag, so a retrain that changes nothing is visibly a
    no-op instead of silently minting a new 'version'.
    """
    blob = json.dumps(parts, sort_keys=True, default=str)
    return "fp_" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def round_or_none(value: float | None, ndigits: int = 4) -> float | None:
    return None if value is None else round(float(value), ndigits)


# --------------------------------------------------------------------------
# CSV
# --------------------------------------------------------------------------
def sniff_delimiter(sample: str, candidates: tuple[str, ...] = (",", ";", "\t", "|")) -> str:
    """Pick the delimiter with the most consistent column count in the header."""
    lines = [ln for ln in (sample or "").splitlines() if ln.strip()][:5]
    if not lines:
        return ","
    best, best_score = ",", -1
    for cand in candidates:
        try:
            import csv

            rows = list(csv.reader(lines, delimiter=cand))
        except Exception:
            continue
        widths = [len(r) for r in rows if r]
        if not widths:
            continue
        # Prefer many columns, then consistency across sample rows.
        score = (max(widths), -len(set(widths)))
        if score > (best_score, 0) and best_score == -1:
            best, best_score = cand, score[0]
        elif max(widths) > best_score:
            best, best_score = cand, max(widths)
    return best


def read_csv_text(text: str) -> list[dict[str, str]]:
    """Parse CSV text into dicts using the stdlib only (no pandas needed).

    Keys are lower-cased and whitespace-trimmed so '  Qty Sold ' and 'qty_sold'
    style drift is handled by the normaliser, not by every call site.
    """
    import csv
    import io

    if not (text or "").strip():
        raise ValueError("CSV is empty")
    delimiter = sniff_delimiter(text[:4096])
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if not reader.fieldnames:
        raise ValueError("CSV has no header row")
    out: list[dict[str, str]] = []
    for raw in reader:
        row: dict[str, str] = {}
        for k, v in raw.items():
            if k is None:
                continue
            key = str(k).strip().lower().replace(" ", "_")
            row[key] = ("" if v is None else str(v).strip())
        if any(val for val in row.values()):
            out.append(row)
    return out


def to_float(value: Any, *, field: str = "value", allow_negative: bool = False) -> float:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"{field} is required and must be numeric, got {value!r}")
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric, got boolean")
    try:
        num = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric, got {value!r}") from exc
    if num != num:  # NaN
        raise ValueError(f"{field} must be a real number, got NaN")
    if not allow_negative and num < 0:
        raise ValueError(f"{field} must be >= 0, got {num}")
    return num


def to_bool(value: Any, default: bool = False) -> bool:
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on", "t")


def redact(value: Any, *, keep: int = 4) -> str:
    """Short, non-reversible hint for logs (e.g. 'sk-…ab12'). Never the secret."""
    s = str(value or "")
    if not s:
        return ""
    return f"…{s[-keep:]}" if len(s) > keep else "***"


SENSITIVE_KEYS = ("password", "secret", "token", "api_key", "apikey", "authorization", "bearer", "cookie")


def scrub(obj: Any, _depth: int = 0) -> Any:
    """Recursively drop sensitive-looking keys. Mirrors app.core.audit behaviour."""
    if _depth > 8:
        return "<truncated>"
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if any(s in str(k).lower() for s in SENSITIVE_KEYS):
                continue
            out[k] = scrub(v, _depth + 1)
        return out
    if isinstance(obj, list):
        return [scrub(v, _depth + 1) for v in obj]
    return obj
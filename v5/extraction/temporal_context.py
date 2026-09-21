"""Token-based clinical-date resolution for matched narrative spans.

This module resolves common relative and year-only expressions around a
PhraseMatcher target. It does not identify clinical concepts and does not use
regex or substring search. The warehouse row date remains the availability
date; a resolved date is the clinical date of the individual text mention.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Sequence


_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}
_UNITS = {
    "day": "DAY",
    "days": "DAY",
    "week": "WEEK",
    "weeks": "WEEK",
    "month": "MONTH",
    "months": "MONTH",
    "year": "YEAR",
    "years": "YEAR",
}
_CLAUSE_BOUNDARIES = {
    ".", ";", "\n", "but", "however", "yet", "while", "whereas", "nevertheless",
}


@dataclass(frozen=True)
class TemporalContext:
    clinical_date: str | None
    relation: str | None
    expression: str | None
    is_historical: bool = False
    is_future: bool = False

    def attributes(self, recorded_date: Any) -> dict[str, Any]:
        output: dict[str, Any] = {"source_recorded_event_date": _date_text(recorded_date)}
        if self.clinical_date is not None:
            output["clinical_date"] = self.clinical_date
        if self.relation is not None:
            output["temporal_relation"] = self.relation
        if self.expression is not None:
            output["temporal_expression"] = self.expression
        if self.is_historical:
            output["is_historical"] = True
            output["temporality"] = "HISTORICAL"
        if self.is_future:
            output["is_future"] = True
            output["temporality"] = "FUTURE"
        return output


@dataclass(frozen=True)
class _Anchor:
    start: int
    end: int
    resolved: date
    relation: str
    expression: str


def _base_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value in (None, ""):
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except (TypeError, ValueError):
        return None


def _date_text(value: Any) -> str | None:
    parsed = _base_date(value)
    return parsed.isoformat() if parsed is not None else None


def _number(token: str) -> int | None:
    text = token.lower()
    if text.isdigit():
        value = int(text)
        return value if value >= 0 else None
    return _NUMBER_WORDS.get(text)


def _shift_months(value: date, months: int) -> date:
    total = value.year * 12 + value.month - 1 + months
    year, month_index = divmod(total, 12)
    month = month_index + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _shift(value: date, amount: int, unit: str) -> date:
    if unit == "DAY":
        return value + timedelta(days=amount)
    if unit == "WEEK":
        return value + timedelta(days=amount * 7)
    if unit == "MONTH":
        return _shift_months(value, amount)
    if unit == "YEAR":
        return _shift_months(value, amount * 12)
    return value


def _anchors(tokens: Sequence[Any], base: date) -> list[_Anchor]:
    lowered = [str(getattr(token, "text", token)).lower() for token in tokens]
    output: list[_Anchor] = []
    for index, text in enumerate(lowered):
        if text in {"today", "currently"}:
            output.append(_Anchor(index, index + 1, base, "CURRENT", text))
            continue
        if text == "yesterday":
            output.append(_Anchor(index, index + 1, base - timedelta(days=1), "PAST", text))
            continue
        if text == "tomorrow":
            output.append(_Anchor(index, index + 1, base + timedelta(days=1), "FUTURE", text))
            continue
        if text.isdigit() and len(text) == 4:
            year = int(text)
            if 1900 <= year <= base.year + 20:
                relation = "FUTURE" if year > base.year else "PAST" if year < base.year else "CURRENT"
                output.append(_Anchor(index, index + 1, date(year, 1, 1), relation, text))
            continue
        if text in {"last", "next"} and index + 1 < len(lowered):
            unit = _UNITS.get(lowered[index + 1])
            if unit:
                amount = -1 if text == "last" else 1
                output.append(_Anchor(
                    index,
                    index + 2,
                    _shift(base, amount, unit),
                    "PAST" if amount < 0 else "FUTURE",
                    " ".join(lowered[index:index + 2]),
                ))
            elif lowered[index + 1] == "night":
                amount = -1 if text == "last" else 1
                output.append(_Anchor(
                    index,
                    index + 2,
                    base + timedelta(days=amount),
                    "PAST" if amount < 0 else "FUTURE",
                    " ".join(lowered[index:index + 2]),
                ))
            continue
        amount = _number(text)
        if amount is None or index + 2 >= len(lowered):
            continue
        unit = _UNITS.get(lowered[index + 1])
        direction = lowered[index + 2]
        if unit and direction in {"ago", "later", "hence"}:
            signed = -amount if direction == "ago" else amount
            output.append(_Anchor(
                index,
                index + 3,
                _shift(base, signed, unit),
                "PAST" if signed < 0 else "FUTURE",
                " ".join(lowered[index:index + 3]),
            ))
    return output


def _clause_bounds(tokens: Sequence[Any], target_start: int, target_end: int) -> tuple[int, int]:
    left = 0
    for index in range(max(0, target_start - 1), -1, -1):
        text = str(getattr(tokens[index], "text", tokens[index])).lower()
        if text in _CLAUSE_BOUNDARIES:
            left = index + 1
            break
    right = len(tokens)
    for index in range(min(len(tokens), target_end), len(tokens)):
        text = str(getattr(tokens[index], "text", tokens[index])).lower()
        if text in _CLAUSE_BOUNDARIES:
            right = index
            break
    return left, right


def resolve_temporal_context(
    doc: Any,
    target_start: int,
    target_end: int,
    recorded_date: Any,
) -> TemporalContext:
    """Resolve the nearest clause-local date expression for one target span."""
    base = _base_date(recorded_date)
    if base is None:
        return TemporalContext(None, None, None)
    tokens = list(doc)
    candidates = _anchors(tokens, base)
    if not candidates:
        return TemporalContext(base.isoformat(), "RECORDED_DATE", None)
    left, right = _clause_bounds(tokens, target_start, target_end)
    local = [anchor for anchor in candidates if anchor.start >= left and anchor.end <= right]
    if not local:
        return TemporalContext(base.isoformat(), "RECORDED_DATE", None)
    # Relative-time phrases generally introduce the finding that follows.
    # Prefer anchors at or before the target so a later clause's date cannot
    # reach backward (for example, "two weeks ago burning feet, and yesterday
    # diarrhea"). A following anchor is retained for constructions such as
    # "symptoms began yesterday" when no preceding anchor exists.
    directional = [anchor for anchor in local if anchor.end <= target_start]
    if not directional:
        directional = local
    midpoint = (target_start + target_end) / 2
    selected = min(directional, key=lambda anchor: (
        abs(((anchor.start + anchor.end) / 2) - midpoint),
        0 if anchor.start <= target_start else 1,
    ))
    return TemporalContext(
        selected.resolved.isoformat(),
        selected.relation,
        selected.expression,
        is_historical=selected.relation == "PAST",
        is_future=selected.relation == "FUTURE",
    )


__all__ = ["TemporalContext", "resolve_temporal_context"]

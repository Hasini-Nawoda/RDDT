"""Auditable explanations with separate clinical rationale and engine trace."""
from __future__ import annotations

from typing import Any

from .reasoning_utils import value


def build_explanation(result: Any, *, patient_facing: bool = False) -> str:
    """Return a concise screening explanation, never an opaque score.

    ``patient_facing=False`` is suitable for internal output but still avoids
    proprietary implementation details.  Callers that need a pipeline trace
    should use :func:`build_trace` separately.
    """
    status = value(result, "status", "UNKNOWN")
    route = value(result, "result_route", None)
    guardrails = [str(x) for x in (value(result, "guardrail_ids", ()) or ()) if x]
    if status == "PHENOTYPE_PASS":
        text = "ATTRv screening/review route matched using independent configured clinical findings"
        if route:
            text += f" with route {route}"
    elif status == "HOLD":
        text = "ATTRv screening/review is on hold pending an auditable evidence or configuration issue"
    elif status == "NO_MATCH":
        text = "No enabled workbook-defined ATTRv combination matched"
    else:
        text = "ATTRv screening/review remains unknown because required evidence or configuration was unavailable"
    if guardrails:
        text += "; parallel review routes are present"
    return text


def build_trace(result: Any, *, implementation_version: str | None = None) -> dict[str, Any]:
    """Return a separately removable proprietary pipeline trace."""
    return {
        "matched_combination_id": value(result, "matched_combination_id", None),
        "support_lineage_ids": tuple(value(result, "support_lineage_ids", ()) or ()),
        "supporting_event_dates": tuple(value(result, "supporting_event_dates", ()) or ()),
        "config_hash": value(result, "config_hash", None),
        "implementation_version": implementation_version or value(result, "implementation_version", None),
        "guardrail_ids": tuple(value(result, "guardrail_ids", ()) or ()),
        "engine_status": value(result, "status", "UNKNOWN"),
    }


explain = build_explanation

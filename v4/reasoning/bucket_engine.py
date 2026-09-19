"""Bucket-state construction from configured signal witnesses."""
from __future__ import annotations

from typing import Any, Iterable

from .reasoning_utils import FALSE, TRUE, UNKNOWN, norm_status, rows, value


def _tier_key(tier: Any) -> tuple[int, str]:
    if isinstance(tier, (int, float)):
        return int(tier), str(tier)
    text = str(tier or "")
    digits = "".join(ch for ch in text if ch.isdigit())
    return (int(digits) if digits else 9999, text)


def build_bucket_state(config: Any, signal_hits: Iterable[Any], *, patient_id: Any = None, phenotype: str | None = None) -> list[dict[str, Any]]:
    hits = [h for h in signal_hits if norm_status(value(h, "status", UNKNOWN)) in {TRUE, UNKNOWN}]
    if patient_id is not None:
        hits = [h for h in hits if value(h, "patient_id", patient_id) == patient_id]
    buckets = {str(value(b, "reasoning_bucket", "")): b for b in rows(config, "buckets")}
    grouped: dict[str, list[Any]] = {}
    for hit in hits:
        bucket = value(hit, "reasoning_bucket", None)
        if bucket in (None, ""):
            continue
        grouped.setdefault(str(bucket), []).append(hit)
    out: list[dict[str, Any]] = []
    for bucket_id, witnesses in grouped.items():
        definition = buckets.get(bucket_id)
        true_witnesses = [w for w in witnesses if norm_status(value(w, "status", UNKNOWN)) == TRUE]
        unknown_witnesses = [w for w in witnesses if norm_status(value(w, "status", UNKNOWN)) == UNKNOWN]
        best = min((value(w, "tier", None) for w in true_witnesses if value(w, "tier", None) is not None), key=_tier_key, default=None)
        out.append({
            "patient_id": patient_id,
            "phenotype": phenotype or (value(true_witnesses[0], "phenotype", None) if true_witnesses else None),
            "reasoning_bucket": bucket_id,
            "bucket_class": value(definition, "bucket_class", None),
            "counts_independently": bool(value(definition, "counts_independently", True)),
            "status": TRUE if true_witnesses else UNKNOWN,
            "best_tier": best,
            "witnesses": tuple(witnesses),
            "true_witnesses": tuple(true_witnesses),
            "unknown_witnesses": tuple(unknown_witnesses),
            "support_lineage_ids": tuple(sorted({str(x) for w in true_witnesses for x in (value(w, "support_lineage_ids", ()) or ())})),
            "explanation": "configured reasoning bucket; tiers retained as ordinal witnesses",
            "config_hash": value(config, "config_hash", None),
        })
    return out


evaluate_buckets = build_bucket_state
run = build_bucket_state

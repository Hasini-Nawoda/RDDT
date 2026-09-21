"""Compact, population-wide ATTR and AL verdict ledger.

The expensive clinical engine still evaluates only patients with configured
candidate evidence.  This module adds an explicit row for everybody else so
that absence from candidate retrieval is never mistaken for a missing result.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping

from ..evaluation_policy import CLAIMS_RECALL, normalize_evaluation_mode
from .patient_profile import aggregate_attr_verdict


def _value(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _confirmation_scopes(rows: Iterable[Any]) -> tuple[str, ...]:
    return tuple(sorted({
        str(_value(row, "confirmation_scope"))
        for row in rows
        if _value(row, "confirmation_scope", None) not in (None, "")
    }))


def _router_verdict(row: Any | None) -> dict[str, Any]:
    if row is None:
        return {
            "status": "NO_CANDIDATE_EVIDENCE",
            "suspicion_level": None,
            "result_route": "NOT_EVALUATED",
            "provisional": False,
            "relaxations": (),
        }
    return {
        "status": _value(row, "status", "UNKNOWN"),
        "suspicion_level": _value(row, "suspicion_level", None),
        "result_route": _value(row, "result_route", None),
        "provisional": bool(_value(row, "provisional", False)),
        "relaxations": tuple(_value(row, "relaxations", ()) or ()),
    }


def build_all_patient_verdicts(
    population_patient_ids: Iterable[Any],
    router_output: Iterable[Any],
    *,
    known_attr_patients: Iterable[Any] = (),
    known_al_patients: Iterable[Any] = (),
    evaluation_mode: str = "STRICT",
) -> list[dict[str, Any]]:
    """Return one explicit ATTR/AL screening row for every supplied patient."""
    mode = normalize_evaluation_mode(evaluation_mode)
    routers_by_patient: dict[str, list[Any]] = defaultdict(list)
    for row in router_output:
        patient_id = str(_value(row, "patient_id", "") or "")
        if patient_id:
            routers_by_patient[patient_id].append(row)

    known_attr_by_patient: dict[str, list[Any]] = defaultdict(list)
    for row in known_attr_patients:
        patient_id = str(_value(row, "patient_id", "") or "")
        if patient_id:
            known_attr_by_patient[patient_id].append(row)
    known_al_by_patient: dict[str, list[Any]] = defaultdict(list)
    for row in known_al_patients:
        patient_id = str(_value(row, "patient_id", "") or "")
        if patient_id:
            known_al_by_patient[patient_id].append(row)

    patient_ids = {
        str(patient_id) for patient_id in population_patient_ids
        if patient_id not in (None, "")
    }
    patient_ids.update(routers_by_patient)
    patient_ids.update(known_attr_by_patient)
    patient_ids.update(known_al_by_patient)

    output: list[dict[str, Any]] = []
    for patient_id in sorted(patient_ids):
        attr_confirmations = known_attr_by_patient.get(patient_id, [])
        al_confirmations = known_al_by_patient.get(patient_id, [])
        if attr_confirmations or al_confirmations:
            scopes = _confirmation_scopes((*attr_confirmations, *al_confirmations))
            output.append({
                "patient_id": patient_id,
                "population_status": "CONFIRMED_AMYLOIDOSIS_EXCLUDED_FROM_SUSPICION",
                "confirmation_status": "CONFIRMED",
                "confirmation_scopes": scopes,
                "attr_status": (
                    "CONFIRMED_OR_KNOWN_AMYLOIDOSIS"
                    if attr_confirmations else "NOT_EVALUATED_CONFIRMED_EXCLUSION"
                ),
                "attr_suspicion_level": None,
                "attrv_status": "NOT_EVALUATED_CONFIRMED_EXCLUSION",
                "attrwt_status": "NOT_EVALUATED_CONFIRMED_EXCLUSION",
                "al_status": (
                    "CONFIRMED_AL"
                    if al_confirmations else "NOT_EVALUATED_CONFIRMED_EXCLUSION"
                ),
                "al_suspicion_level": None,
                "candidate_for_review": False,
                "evaluation_mode": mode,
                "verdict_scope": (
                    "CLAIMS_ONLY_RECALL" if mode == CLAIMS_RECALL
                    else "STRICT_CLINICAL_EVIDENCE"
                ),
                "provisional": False,
                "relaxations": (),
                "reason": "Confirmed amyloidosis is identified before and excluded from suspicion scoring.",
            })
            continue

        patient_router = routers_by_patient.get(patient_id, [])
        by_phenotype = {
            str(_value(row, "phenotype", "") or "").upper(): row
            for row in patient_router
        }
        attrv = _router_verdict(by_phenotype.get("ATTRV"))
        attrwt = _router_verdict(by_phenotype.get("ATTRWT"))
        al = _router_verdict(by_phenotype.get("AL"))
        if patient_router:
            attr = aggregate_attr_verdict(patient_router)
            attr_status = attr.get("status", "UNKNOWN")
            attr_level = attr.get("suspicion_level")
            attr_provisional = bool(attr.get("provisional", False))
            attr_relaxations = tuple(attr.get("relaxations", ()) or ())
            population_status = "CANDIDATE_EVALUATED"
            reason = "Configured candidate evidence was evaluated for ATTRv, ATTRwt, and AL."
        else:
            attr_status = "NO_CANDIDATE_EVIDENCE"
            attr_level = None
            attr_provisional = False
            attr_relaxations = ()
            population_status = "NO_CONFIGURED_CANDIDATE_EVIDENCE"
            reason = (
                "No configured candidate code or term was found in the selected source scope; "
                "this is not a definitive absence-of-disease finding."
            )

        relaxations = tuple(dict.fromkeys((
            *attr_relaxations,
            *attrv["relaxations"],
            *attrwt["relaxations"],
            *al["relaxations"],
        )))
        review_statuses = {
            "PHENOTYPE_PASS", "CLAIMS_RECALL_CANDIDATE", "ATTR_SUSPICION",
            "ATTR_CLAIMS_RECALL_CANDIDATE",
        }
        candidate_for_review = (
            attr_status in review_statuses
            or al["status"] in review_statuses
        )
        output.append({
            "patient_id": patient_id,
            "population_status": population_status,
            "confirmation_status": "NOT_CONFIRMED",
            "confirmation_scopes": (),
            "attr_status": attr_status,
            "attr_suspicion_level": attr_level,
            "attrv_status": attrv["status"],
            "attrwt_status": attrwt["status"],
            "al_status": al["status"],
            "al_suspicion_level": al["suspicion_level"],
            "candidate_for_review": candidate_for_review,
            "evaluation_mode": mode,
            "verdict_scope": (
                "CLAIMS_ONLY_RECALL" if mode == CLAIMS_RECALL
                else "STRICT_CLINICAL_EVIDENCE"
            ),
            "provisional": bool(
                attr_provisional or attrv["provisional"]
                or attrwt["provisional"] or al["provisional"]
            ),
            "relaxations": relaxations,
            "reason": reason,
        })
    return output


__all__ = ["build_all_patient_verdicts"]

"""Serve the patient report viewer and load an export folder or JSONL file.

Usage:
  python patient_report_viewer.py
  python patient_report_viewer.py "..\\results\\confirmed_amyloidosis_patient_profiles.jsonl"
"""

from __future__ import annotations

import argparse
import json
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
VIEWER = HERE / "patient_report_viewer.html"
DEFAULT_SOURCE = ROOT / "results" / "confirmed_amyloidosis_patient_profiles.jsonl"


def slim_profile(profile: object) -> object:
    if not isinstance(profile, dict):
        return profile
    ehr = profile.get("ehr") or {}
    tables = {}
    for key, payload in (ehr.get("records_by_table") or {}).items():
        if not isinstance(payload, dict):
            continue
        if payload.get("groups") and not payload.get("records"):
            tables[key] = {
                "physical_table": payload.get("physical_table"),
                "record_count": payload.get("record_count") or 0,
                "enabled": payload.get("enabled", payload.get("profile_enabled")),
                "records": payload.get("records") or [],
                "groups": payload.get("groups") or [],
            }
            continue
        records = [
            _project_row(row, payload.get("column_map") or {})
            for row in payload.get("records") or []
            if isinstance(row, dict)
        ]
        tables[key] = {
            "physical_table": payload.get("physical_table"),
            "record_count": payload.get("record_count") or len(records),
            "enabled": payload.get("profile_enabled"),
            "records": records[:1] if key == "census" else [],
            "groups": _group_table(key, records),
        }
    rationale = profile.get("clinical_rationale") or {}
    evidence = []
    seen = {}
    for row in rationale.get("matched_claim_evidence") or []:
        if not isinstance(row, dict):
            continue
        claim = row.get("source_claim") or {}
        code = str(row.get("matched_icd10_code") or claim.get("diagnosis_code") or "ICD-10")
        item = seen.setdefault(code, {"code": code, "mentions": 0, "unit": "encounter"})
        item["mentions"] += 1
    evidence = list(seen.values())
    return {
        "patient_id": profile.get("patient_id"),
        "run_id": profile.get("run_id"),
        "diagnosis_state": profile.get("diagnosis_state"),
        "demographics": profile.get("demographics") or {},
        "known_diagnosis": profile.get("known_diagnosis") or {},
        "phenotype_risk_assessments": profile.get("phenotype_risk_assessments") or [],
        "clinical_rationale": {
            "evidence_count": rationale.get("evidence_count") or len(evidence),
            "evidence": evidence,
        },
        "ehr": {
            "completeness_status": ehr.get("completeness_status"),
            "total_record_count": ehr.get("total_record_count"),
            "table_count": ehr.get("table_count"),
            "records_by_table": tables,
        },
    }


def _row_get(row: dict, physical: object) -> object:
    if physical in row:
        return row[physical]
    wanted = str(physical or "").strip('"').upper()
    for key, value in row.items():
        if str(key).strip('"').upper() == wanted:
            return value
    return None


def _project_row(row: dict, column_map: dict) -> dict[str, object]:
    projected: dict[str, object] = {}
    used = set()
    for logical, physical in (column_map or {}).items():
        value = _row_get(row, physical)
        used.add(str(physical or "").strip('"').upper())
        if value not in (None, ""):
            projected[str(logical)] = value
    for key, value in row.items():
        if value in (None, ""):
            continue
        if str(key).strip('"').upper() in used:
            continue
        projected[str(key)] = value
    return projected


def _first(row: dict, names: tuple[str, ...]) -> str:
    upper = {str(key).upper(): value for key, value in row.items()}
    for name in names:
        value = row.get(name)
        if value in (None, ""):
            value = upper.get(name.upper())
        if value not in (None, ""):
            return str(value)
    return ""


def _group_table(table: str, records: list[dict]) -> list[dict[str, object]]:
    names = {
        "claim": ("diagnosis_code",),
        "encounter": ("TYPE", "type"),
        "lab": ("observation_identifier", "OBSERVATIONIDENTIFIERCOMMONNAME"),
        "medication": ("medication_name", "MEDICATIONNAME"),
        "clinical_note": ("note_type", "NoteType"),
        "medical_history": ("value", "Value"),
        "surgical_history": ("value", "Value"),
        "family_history": ("condition", "Condition"),
        "social_history": ("value", "Value"),
        "census": ("patient_id",),
    }.get(table, ("name",))
    details = {
        "claim": ("diagnosis_type",),
        "encounter": ("VISITDATE", "encounter_date", "STATUS"),
        "lab": ("observation_value", "observation_datetime"),
        "medication": ("status", "MEDICATIONSTATUS", "DOSAGE"),
        "clinical_note": ("note_text",),
        "medical_history": ("event_date",),
        "surgical_history": ("event_date",),
        "family_history": ("family_member", "event_date"),
        "social_history": ("event_date",),
    }.get(table, ())
    grouped: dict[str, dict[str, object]] = {}
    for row in records:
        name = _first(row, names) or "Not recorded"
        item = grouped.setdefault(name, {"name": name, "count": 0, "detail": ""})
        item["count"] = int(item["count"]) + 1
        detail = " · ".join(_first(row, (field,)) for field in details if _first(row, (field,)))
        if detail:
            item["detail"] = detail[:160]
    return sorted(grouped.values(), key=lambda item: int(item["count"]), reverse=True)


def cache_path(source: Path) -> Path:
    return source.with_suffix(source.suffix + ".viewer.json")


def collect_records(target: Path) -> list[dict[str, object]]:
    files = [target] if target.is_file() else sorted(
        path for path in target.rglob("*")
        if path.is_file()
        and path.suffix.lower() in {".jsonl", ".json"}
        and "viewer.json" not in path.name
        and path.name != "export_summary.json"
    )
    records = []
    for path in files:
        cached = cache_path(path)
        if (
            path.suffix.lower() == ".jsonl"
            and cached.exists()
            and cached.stat().st_mtime >= path.stat().st_mtime
        ):
            records.extend(json.loads(cached.read_text(encoding="utf-8")))
            continue
        built = []
        with path.open(encoding="utf-8-sig") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    continue
                rows = parsed if isinstance(parsed, list) else [parsed]
                for profile in rows:
                    built.append({
                        "profile": slim_profile(profile),
                        "path": path.name,
                    })
        if path.suffix.lower() == ".jsonl":
            cached.write_text(json.dumps(built, default=str), encoding="utf-8")
        records.extend(built)
    return records


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/patient_report_viewer.html"}:
            self._send(200, VIEWER.read_bytes(), "text/html; charset=utf-8")
            return
        if parsed.path == "/api/default":
            target = DEFAULT_SOURCE if DEFAULT_SOURCE.exists() else None
            if target is None:
                self._send(404, b"Default results file not found", "text/plain; charset=utf-8")
                return
            self._send_records(target)
            return
        if parsed.path == "/api/load":
            raw = parse_qs(parsed.query).get("path", [""])[0]
            target = Path(unquote(raw)).expanduser()
            if not target.exists():
                self._send(400, f"Path not found: {target}".encode("utf-8"), "text/plain; charset=utf-8")
                return
            self._send_records(target)
            return
        self._send(404, b"Not found", "text/plain; charset=utf-8")

    def _send_records(self, target: Path) -> None:
        try:
            payload = json.dumps({
                "folder": str(target),
                "records": collect_records(target),
            }, default=str).encode("utf-8")
        except Exception as exc:
            self._send(500, str(exc).encode("utf-8"), "text/plain; charset=utf-8")
            return
        self._send(200, payload, "application/json; charset=utf-8")

    def log_message(self, format: str, *args: object) -> None:
        print(format % args)

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser(description="Open the V4 patient report viewer.")
    parser.add_argument("path", nargs="?", help="Export folder or JSONL file to load")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--build-cache", action="store_true")
    args = parser.parse_args()
    source = Path(args.path).expanduser() if args.path else DEFAULT_SOURCE
    if args.build_cache or source.exists():
        print(f"Preparing viewer data from {source} ...")
        count = len(collect_records(source))
        print(f"Ready: {count} patient profiles")
        if args.build_cache:
            return
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    if source.exists():
        url += "?file=" + source.resolve().as_posix()
    print(f"Patient report viewer: {url}")
    webbrowser.open(url)
    server.serve_forever()


if __name__ == "__main__":
    main()

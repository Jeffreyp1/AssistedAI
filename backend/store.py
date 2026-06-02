"""
Patient store + deterministic helpers.

Loads the mock EHR from data/patients.json and exposes pure functions for the
facility summary, lookup, and search/filter. No LLM, no external calls — this is
the deterministic layer the dashboard reads before any AI is involved.

Trend/status values are taken from the record as-is for the MVP; deriving them
from the raw time series (with tunable thresholds) is deferred.
"""

from __future__ import annotations

import json
from pathlib import Path

DATA_PATH = Path(__file__).parent / "data" / "patients.json"

_STATUSES = ("attention", "watch", "improving", "stable")


def load_data(path: Path = DATA_PATH) -> dict:
    """Load the facility + patients payload from disk."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def facility_summary(data: dict) -> dict:
    """Facility name + total + per-status counts."""
    patients = data["patients"]
    counts = {s: 0 for s in _STATUSES}
    for p in patients:
        counts[p["status"]] = counts.get(p["status"], 0) + 1
    return {"facility": data["facility"], "total": len(patients), "counts": counts}


def get_patient(data: dict, patient_id: str) -> dict | None:
    """Return the full record for a patient id, or None if absent."""
    for p in data["patients"]:
        if p["id"] == patient_id:
            return p
    return None


def search_patients(data: dict, q: str = "", status: str = "all") -> list[dict]:
    """Filter patients by free-text query (name or room) and status."""
    needle = (q or "").strip().lower()
    results = []
    for p in data["patients"]:
        if status not in ("all", "") and p["status"] != status:
            continue
        if needle and needle not in p["name"].lower() and needle not in p["room"].lower():
            continue
        results.append(p)
    return results

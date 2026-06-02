"""
AssistedAI FastAPI app.

Serves the static frontend and a small JSON API over the mock EHR:
  GET  /api/summary               facility counts
  GET  /api/patients?q=&status=   lightweight resident list (for overview + list)
  GET  /api/patients/{id}         full resident record (for the profile)
  POST /api/patients/{id}/analyze run the AI insight (live Claude, or a canned
                                  fallback when no ANTHROPIC_API_KEY is set)
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import store
from analysis import coordinator

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

app = FastAPI(title="AssistedAI", version="0.1.0")
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

DATA = store.load_data()


def _list_item(p: dict) -> dict:
    """Trim a full record down to what the overview + list screens need."""
    notes = p.get("notes") or []
    return {
        "id": p["id"],
        "name": p["name"],
        "room": p["room"],
        "age": p.get("age"),
        "sex": p.get("sex"),
        "status": p["status"],
        "summary": p.get("summary", ""),
        "trends": p.get("trends", {}),
        "latest_note": notes[0] if notes else None,
    }


@app.get("/api/summary")
async def summary():
    return store.facility_summary(DATA)


@app.get("/api/patients")
async def patients(q: str = "", status: str = "all"):
    return [_list_item(p) for p in store.search_patients(DATA, q=q, status=status)]


@app.get("/api/patients/{patient_id}")
async def patient_detail(patient_id: str):
    p = store.get_patient(DATA, patient_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Resident not found")
    return p


@app.post("/api/patients/{patient_id}/analyze")
async def analyze(patient_id: str):
    p = store.get_patient(DATA, patient_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Resident not found")

    if not os.getenv("ANTHROPIC_API_KEY"):
        canned = dict(p.get("analysis") or {"conclusion": "No analysis available.", "confidence": "low", "areas": ["behavioral"], "research": []})
        canned["simulated"] = True
        return canned

    return await coordinator.run(p)


@app.get("/")
async def root():
    return FileResponse(FRONTEND_DIR / "index.html")

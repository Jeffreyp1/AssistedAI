# AssistedAI

An assisted-living monitoring dashboard. It reads resident records (a mock EHR
for now), surfaces behavioral and health trends deterministically, and runs an
on-demand AI analysis that draws plain-language conclusions and pulls supporting
research. The goal: let a non-technical caregiver glance at the facility, see who
needs attention, and click in for the why.

## How it works

```
Mock EHR (backend/data/patients.json)
        |
        v
Deterministic layer (store.py)      facility summary, search, status  -- no LLM
        |
        v
AI layer (analysis/coordinator.py, on demand)
   router picks the relevant specialists, and only those run:
     treatment    -> PubMed          (tools/pubmed_client.py)
     trials       -> ClinicalTrials  (tools/trials_client.py)
     drug safety  -> openFDA         (tools/fda_client.py)
   synthesizer -> conclusion + confidence + research citations
        |
        v
FastAPI (main.py)  ->  three-screen frontend (frontend/)
```

External API calls go through a 24-hour TTL cache (`tools/cache.py`) so repeat
analyses don't re-hit the public APIs.

## Project structure

| Path | What it is |
|------|------------|
| `backend/store.py` | Deterministic layer: load mock EHR, facility summary, search/filter |
| `backend/analysis/coordinator.py` | AI layer: routes to specialists, synthesizes a conclusion |
| `backend/tools/` | PubMed / ClinicalTrials / openFDA clients + the TTL cache |
| `backend/main.py` | FastAPI app + JSON API; also serves the frontend |
| `frontend/` | Vanilla-JS dashboard: overview, attention list, resident profile |

## API

| Method | Path | Returns |
|--------|------|---------|
| GET | `/api/summary` | Facility name, total, per-status counts |
| GET | `/api/patients?q=&status=` | Trimmed resident list, searchable/filterable |
| GET | `/api/patients/{id}` | Full resident record |
| POST | `/api/patients/{id}/analyze` | AI insight (live Claude, or a canned fallback if no API key) |
| GET | `/` | The dashboard |

## Run it

```
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

Then open http://127.0.0.1:8000.

The analyze endpoint uses Claude when `ANTHROPIC_API_KEY` is set; without a key
it returns the pre-baked analysis flagged `simulated: true`, so the dashboard is
fully demoable offline.

## Status

MVP. Mock EHR only — fake data, no real PHI. A real EHR/FHIR ingestion pipeline
(data lake -> cleaning -> warehouse), auth, and persistence beyond the JSON file
are out of scope for this stage.

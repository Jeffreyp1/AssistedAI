"""
ClinicalTrials.gov client tool.

Queries the ClinicalTrials.gov v2 REST API for clinical studies matching
a condition or intervention. Returns structured trial records for Claude
to reason over.

If no trials are found, returns an explanatory message so Claude can
retry with a refined query or different status filter.
"""

from __future__ import annotations

import httpx

from tools.cache import DEFAULT_TTL_SECONDS, async_ttl_cache

_BASE_URL = "https://clinicaltrials.gov/api/v2/studies"

_FIELDS = [
    "NCTId",
    "BriefTitle",
    "OverallStatus",
    "Phase",
    "StartDate",
    "PrimaryCompletionDate",
    "BriefSummary",
    "Condition",
    "InterventionName",
]


def _parse_trials(data: dict) -> list[dict]:
    """
    Extracts relevant fields from the ClinicalTrials.gov v2 JSON response.

    Each study in the response is nested under a 'protocolSection' key.
    We pull identification, status, design, and a brief summary for Claude.

    Args:
        data: Parsed JSON response from the /api/v2/studies endpoint.

    Returns:
        List of trial dicts, one per study returned by the API.
    """
    trials = []

    for study in data.get("studies", []):
        protocol = study.get("protocolSection", {})

        id_module = protocol.get("identificationModule", {})
        status_module = protocol.get("statusModule", {})
        design_module = protocol.get("designModule", {})
        desc_module = protocol.get("descriptionModule", {})
        conditions_module = protocol.get("conditionsModule", {})
        arms_module = protocol.get("armsInterventionsModule", {})

        # Interventions — join names if multiple
        interventions = [
            i.get("name", "")
            for i in arms_module.get("interventions", [])
            if i.get("name")
        ]

        trials.append(
            {
                "nct_id": id_module.get("nctId", ""),
                "title": id_module.get("briefTitle", ""),
                "status": status_module.get("overallStatus", ""),
                "phase": design_module.get("phases", []),
                "start_date": status_module.get("startDateStruct", {}).get("date", ""),
                "completion_date": status_module.get(
                    "primaryCompletionDateStruct", {}
                ).get("date", ""),
                "conditions": conditions_module.get("conditions", []),
                "interventions": interventions,
                "summary": desc_module.get("briefSummary", ""),
            }
        )

    return trials


@async_ttl_cache(ttl_seconds=DEFAULT_TTL_SECONDS)
async def search(
    query: str,
    filter_overall_status: str,
    sort: str,
    page_size: int,
) -> dict:
    """
    Searches ClinicalTrials.gov and returns structured trial data for Claude.

    Args:
        query:                 Condition or intervention to search for.
        filter_overall_status: Trial status filter (e.g. COMPLETED, RECRUITING).
        sort:                  Sort field (e.g. LastUpdatePostDate, StartDate).
        page_size:             Number of results to return (capped at 10 by coordinator).

    Returns:
        Dict with a 'results' list and a 'message' string. On success,
        'results' contains trial dicts. On no results, 'results' is empty
        and 'message' tells Claude to refine its query or status filter.
    """
    params = {
        "query.cond": query,
        "filter.overallStatus": filter_overall_status,
        "sort": sort,
        "pageSize": page_size,
        "format": "json",
        "fields": ",".join(_FIELDS),
    }

    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(_BASE_URL, params=params)
        response.raise_for_status()
        data = response.json()

    trials = _parse_trials(data)

    if not trials:
        return {
            "results": [],
            "message": (
                f"No {filter_overall_status.lower()} trials found for query: '{query}'. "
                f"Consider using a different status filter or broader search term."
            ),
        }

    return {
        "results": trials,
        "message": f"Found {len(trials)} {filter_overall_status.lower()} trials for query: '{query}'.",
    }

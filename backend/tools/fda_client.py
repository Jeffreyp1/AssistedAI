"""
FDA client tool.

Queries the openFDA drug/event endpoint (FAERS — FDA Adverse Event
Reporting System) for adverse event reports associated with a given drug.

Returns structured report data for Claude to reason over, including the
reported reactions, patient outcomes, and report seriousness.

If no reports are found, returns an explanatory message so Claude can
retry with a different drug name or seriousness filter.
"""

from __future__ import annotations

import httpx

from tools.cache import DEFAULT_TTL_SECONDS, async_ttl_cache

_BASE_URL = "https://api.fda.gov/drug/event.json"


def _parse_reports(data: dict) -> list[dict]:
    """
    Extracts relevant fields from the openFDA drug/event JSON response.

    Each result represents one adverse event report submitted to FAERS.
    We extract the drug name, reported reactions, seriousness flags, and
    patient outcome to give Claude actionable safety signal data.

    Args:
        data: Parsed JSON response from the openFDA drug/event endpoint.

    Returns:
        List of report dicts, one per adverse event result.
    """
    reports = []

    for result in data.get("results", []):
        # Seriousness flags — each is "1" (yes) or "2" (no) as a string
        serious = result.get("serious")
        seriousness_flags = {
            "death": result.get("seriousnessdeath") == "1",
            "hospitalization": result.get("seriousnesshospitalization") == "1",
            "life_threatening": result.get("seriousnesslifethreatening") == "1",
            "disabling": result.get("seriousnessdisabling") == "1",
        }

        # Reactions — each report can list multiple MedDRA reaction terms
        reactions = [
            r.get("reactionmeddrapt", "")
            for r in result.get("patient", {}).get("reaction", [])
            if r.get("reactionmeddrapt")
        ]

        # Drugs involved — extract the primary suspect drug name
        drugs = result.get("patient", {}).get("drug", [])
        suspect_drugs = [
            d.get("medicinalproduct", "")
            for d in drugs
            if d.get("drugcharacterization") == "1" and d.get("medicinalproduct")
        ]

        reports.append(
            {
                "report_id": result.get("safetyreportid", ""),
                "serious": serious == "1",
                "seriousness_flags": seriousness_flags,
                "reactions": reactions,
                "suspect_drugs": suspect_drugs,
                "receipt_date": result.get("receiptdate", ""),
            }
        )

    return reports


@async_ttl_cache(ttl_seconds=DEFAULT_TTL_SECONDS)
async def search(
    drug_name: str,
    serious: int | None,
    limit: int,
) -> dict:
    """
    Searches the FDA adverse event database for reports involving a drug.

    Builds a search query targeting the medicinal product name field.
    Optionally filters by seriousness. Returns structured report data
    for Claude to assess drug safety signals.

    Args:
        drug_name: Generic or brand name of the drug to check.
        serious:   Seriousness filter. 1 = serious reports only,
                   2 = non-serious only, None = all reports.
        limit:     Max number of reports to return (capped at 10 by coordinator).

    Returns:
        Dict with a 'results' list and a 'message' string. On success,
        'results' contains report dicts. On no results, 'results' is empty
        and 'message' guides Claude to retry with a different drug name
        or seriousness setting.
    """
    # Build the search query — target the medicinal product name field
    search_query = f'patient.drug.medicinalproduct:"{drug_name}"'

    # Append seriousness filter if specified
    if serious is not None:
        search_query += f"+AND+serious:{serious}"

    params: dict = {
        "search": search_query,
        "limit": limit,
    }

    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(_BASE_URL, params=params)

        # openFDA returns 404 when no results match — treat as empty, not an error
        if response.status_code == 404:
            return {
                "results": [],
                "message": (
                    f"No adverse event reports found for drug: '{drug_name}'. "
                    f"Try the generic name or check the spelling."
                ),
            }

        response.raise_for_status()
        data = response.json()

    reports = _parse_reports(data)

    if not reports:
        return {
            "results": [],
            "message": (
                f"No adverse event reports found for drug: '{drug_name}'. "
                f"Try the generic name or check the spelling."
            ),
        }

    serious_label = (
        "serious" if serious == 1
        else "non-serious" if serious == 2
        else "all"
    )

    return {
        "results": reports,
        "message": (
            f"Found {len(reports)} {serious_label} adverse event report(s) for '{drug_name}'."
        ),
    }

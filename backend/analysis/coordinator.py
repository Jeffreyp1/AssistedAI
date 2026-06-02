"""
Behavioral analysis coordinator for AssistedAI.

Renders a resident's mock EHR into a prompt, then runs Claude in a single
agentic loop with the PubMed / ClinicalTrials / OpenFDA tools. Claude decides
which sources to consult, so irrelevant specialists are skipped (no meds -> no
drug-safety call, etc.). The tools Claude actually used become the `areas`
reported to the UI, and their results are collected as citations.

Returns a structured insight: conclusion text, confidence, areas, and research.
"""

from __future__ import annotations

import json
import os

import anthropic
from dotenv import load_dotenv

from tools import fda_client, pubmed_client, trials_client

load_dotenv()

MAX_ITERATIONS = 10
MODEL = "claude-opus-4-8"

AREA_BY_TOOL = {
    "search_pubmed": "treatment",
    "search_trials": "trials",
    "check_fda_safety": "drug_safety",
}

SYSTEM_PROMPT = """You are AssistedAI, a clinical decision-support assistant for an assisted-living facility.

You receive a resident's recent record: diagnoses, medications, behavioral trends, and caregiver notes.
Draw a careful, plain-language conclusion about the resident's health trajectory that a non-clinical
caregiver can act on.

You have three tools: search_pubmed, search_trials, check_fda_safety. Use them ONLY when relevant to
this resident:
- Consult PubMed for evidence on a symptom pattern or treatment.
- Check FDA drug safety only when a specific medication may be contributing.
- Search trials only if the resident might plausibly be a candidate.
Do not call tools that aren't relevant. Quality over quantity.

When you have enough evidence, write a final conclusion that:
- States the most likely explanation as a possibility, never a definitive diagnosis.
- Notes positive counter-signals (e.g. improving social engagement) when present.
- Ends with one concrete, conservative next step for staff.
Keep it to a short paragraph in warm, plain language.
"""

TOOLS: list[anthropic.types.ToolParam] = [
    {
        "name": "search_pubmed",
        "description": (
            "Search PubMed for peer-reviewed literature on a symptom pattern or "
            "treatment. Refine query and reldate to the resident's situation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Clinical search terms or MeSH terms."},
                "reldate": {"type": "integer", "description": "Restrict to the last N days (90-1825)."},
                "retmax": {"type": "integer", "description": "Results to return. Max 10."},
                "sort": {"type": "string", "enum": ["relevance", "pub+date"], "description": "Sort order."},
            },
            "required": ["query", "reldate", "retmax", "sort"],
        },
    },
    {
        "name": "search_trials",
        "description": "Search ClinicalTrials.gov for studies matching the resident's condition.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Condition or intervention to search for."},
                "filter_overall_status": {
                    "type": "string",
                    "enum": ["COMPLETED", "RECRUITING", "NOT_YET_RECRUITING", "ACTIVE_NOT_RECRUITING"],
                    "description": "Trial status filter.",
                },
                "sort": {
                    "type": "string",
                    "enum": ["LastUpdatePostDate", "StartDate", "StudyFirstPostDate"],
                    "description": "Sort order.",
                },
                "page_size": {"type": "integer", "description": "Results to return. Max 10."},
            },
            "required": ["query", "filter_overall_status", "sort", "page_size"],
        },
    },
    {
        "name": "check_fda_safety",
        "description": (
            "Check the FDA adverse event database (FAERS) for a specific drug. Only "
            "call when a medication may be contributing to the resident's picture."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "drug_name": {"type": "string", "description": "Generic drug name where possible."},
                "serious": {
                    "type": ["integer", "null"],
                    "enum": [1, 2, None],
                    "description": "1 = serious only, 2 = non-serious, null = all.",
                },
                "limit": {"type": "integer", "description": "Results to return. Max 10."},
            },
            "required": ["drug_name", "serious", "limit"],
        },
    },
]


def build_patient_text(p: dict) -> str:
    """Render a resident record into the free-text prompt the model reasons over."""
    lines = [f"Resident: {p['name']}, age {p.get('age', '?')}, room {p.get('room', '?')}."]
    if p.get("diagnoses"):
        lines.append("Diagnoses: " + ", ".join(p["diagnoses"]) + ".")
    if p.get("medications"):
        meds = ", ".join(f"{m['name']} ({m['dose']})" for m in p["medications"])
        lines.append("Current medications: " + meds + ".")
    if p.get("trends"):
        trends = ", ".join(f"{k}: {v}" for k, v in p["trends"].items())
        lines.append("Behavioral trends (last month): " + trends + ".")
    if p.get("notes"):
        lines.append("Recent caregiver notes:")
        for n in p["notes"][:6]:
            lines.append(f"- [{n['date']}] {n['author']}: {n['text']}")
    return "\n".join(lines)


async def _execute_tool(tool_name: str, tool_input: dict) -> str:
    """Route a tool call to the right client; always return a JSON string."""
    if tool_name == "search_pubmed":
        result = await pubmed_client.search(
            query=tool_input["query"],
            reldate=tool_input["reldate"],
            retmax=min(tool_input["retmax"], 10),
            sort=tool_input["sort"],
        )
    elif tool_name == "search_trials":
        result = await trials_client.search(
            query=tool_input["query"],
            filter_overall_status=tool_input["filter_overall_status"],
            sort=tool_input["sort"],
            page_size=min(tool_input["page_size"], 10),
        )
    elif tool_name == "check_fda_safety":
        result = await fda_client.search(
            drug_name=tool_input["drug_name"],
            serious=tool_input["serious"],
            limit=min(tool_input["limit"], 10),
        )
    else:
        result = {"error": f"Unknown tool: {tool_name}"}
    return json.dumps(result)


def _citations(tool_name: str, tool_input: dict, result: dict) -> list[dict]:
    """Extract up to two display citations from a tool result."""
    out = []
    if tool_name == "search_pubmed":
        for r in result.get("results", [])[:2]:
            if r.get("title"):
                out.append({"source": "PubMed", "title": r["title"], "ref": f"PMID {r.get('pmid', '')}".strip()})
    elif tool_name == "search_trials":
        for r in result.get("results", [])[:2]:
            if r.get("title"):
                out.append({"source": "ClinicalTrials", "title": r["title"], "ref": r.get("nct_id", "")})
    elif tool_name == "check_fda_safety":
        if result.get("results"):
            out.append({
                "source": "OpenFDA",
                "title": f"{tool_input.get('drug_name', 'Drug')} — adverse event reports",
                "ref": "FAERS",
            })
    return out


async def run(patient: dict) -> dict:
    """
    Analyze one resident. Returns a structured insight:
    {conclusion, confidence, areas, research, simulated}.
    """
    client = anthropic.AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    messages: list[anthropic.types.MessageParam] = [
        {"role": "user", "content": build_patient_text(patient)}
    ]

    tools_used: list[str] = []
    research: list[dict] = []
    conclusion = ""

    for _ in range(MAX_ITERATIONS):
        response = await client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text"):
                    conclusion = block.text
                    break
            break

        if response.stop_reason == "tool_use":
            tool_results: list[anthropic.types.ToolResultBlockParam] = []
            for block in response.content:
                if block.type == "tool_use":
                    raw = await _execute_tool(block.name, block.input)
                    tools_used.append(block.name)
                    for cite in _citations(block.name, block.input, json.loads(raw)):
                        if cite not in research:
                            research.append(cite)
                    tool_results.append(
                        {"type": "tool_result", "tool_use_id": block.id, "content": raw}
                    )
            messages.append({"role": "user", "content": tool_results})
    else:
        conclusion = "Analysis did not converge. Please review the resident manually."

    areas = ["behavioral"]
    for tool_name in tools_used:
        area = AREA_BY_TOOL.get(tool_name)
        if area and area not in areas:
            areas.append(area)

    return {
        "conclusion": conclusion,
        "confidence": "moderate",
        "areas": areas,
        "research": research,
        "simulated": False,
    }

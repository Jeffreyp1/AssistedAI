"""
Tests for the behavioral analysis coordinator.

The agentic loop and external clients are mocked: we verify the EHR is rendered
into the prompt, that the reported `areas` reflect which tools Claude actually
used (conditional invocation), and that citations are collected.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from analysis.coordinator import build_patient_text, run

SAMPLE = {
    "id": "p-1", "name": "Alice Adams", "room": "101", "age": 80, "sex": "F",
    "admission_date": "2024-01-01",
    "diagnoses": ["Alzheimer's disease"],
    "medications": [{"name": "Donepezil", "dose": "10 mg"}],
    "status": "attention",
    "trends": {"eating": "declining", "social": "improving", "activity": "stable"},
    "summary": "Eating down.",
    "notes": [{"date": "2026-05-26 18:00", "author": "CNA R", "text": "Left most of dinner."}],
}


def _end_turn(text):
    block = MagicMock(); block.text = text
    r = MagicMock(); r.stop_reason = "end_turn"; r.content = [block]
    return r


def _tool_use(name, tid, inp):
    block = MagicMock(); block.type = "tool_use"; block.id = tid; block.name = name; block.input = inp
    r = MagicMock(); r.stop_reason = "tool_use"; r.content = [block]
    return r


def test_build_patient_text_includes_core_fields():
    txt = build_patient_text(SAMPLE)
    assert "Alice Adams" in txt
    assert "Alzheimer" in txt
    assert "Donepezil" in txt
    assert "eating" in txt.lower()
    assert "Left most of dinner" in txt


@pytest.mark.asyncio
async def test_run_no_tools_returns_behavioral_only():
    create = AsyncMock(return_value=_end_turn("Possible early depressive episode."))
    with patch("analysis.coordinator.anthropic.AsyncAnthropic") as cls:
        cls.return_value.messages.create = create
        result = await run(SAMPLE)
    assert result["conclusion"] == "Possible early depressive episode."
    assert result["areas"] == ["behavioral"]
    assert result["research"] == []
    assert result["simulated"] is False


@pytest.mark.asyncio
async def test_run_with_pubmed_adds_treatment_area_and_citation():
    tool = _tool_use("search_pubmed", "t1",
                     {"query": "appetite loss dementia", "reldate": 365, "retmax": 3, "sort": "relevance"})
    done = _end_turn("Likely depression; monitor intake.")
    create = AsyncMock(side_effect=[tool, done])
    with patch("analysis.coordinator.anthropic.AsyncAnthropic") as cls, \
         patch("analysis.coordinator.pubmed_client.search", new_callable=AsyncMock) as pm:
        cls.return_value.messages.create = create
        pm.return_value = {"results": [{"pmid": "123", "title": "Appetite and depression"}], "message": "ok"}
        result = await run(SAMPLE)
    assert "behavioral" in result["areas"]
    assert "treatment" in result["areas"]
    assert result["research"][0]["source"] == "PubMed"
    assert result["research"][0]["ref"] == "PMID 123"


@pytest.mark.asyncio
async def test_run_with_fda_adds_drug_safety_area():
    tool = _tool_use("check_fda_safety", "t1", {"drug_name": "Donepezil", "serious": 1, "limit": 3})
    done = _end_turn("Medication side effects possible.")
    create = AsyncMock(side_effect=[tool, done])
    with patch("analysis.coordinator.anthropic.AsyncAnthropic") as cls, \
         patch("analysis.coordinator.fda_client.search", new_callable=AsyncMock) as fda:
        cls.return_value.messages.create = create
        fda.return_value = {"results": [{"report_id": "r1"}], "message": "ok"}
        result = await run(SAMPLE)
    assert "drug_safety" in result["areas"]
    assert result["research"][0]["source"] == "OpenFDA"

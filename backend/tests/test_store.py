"""
Tests for the deterministic patient store: facility summary, lookup, and
search/filter. Pure functions over a patients dict, no I/O or LLM.
"""

from store import facility_summary, get_patient, search_patients


def _data():
    return {
        "facility": {"name": "Test Home", "as_of": "2026-06-01T08:00:00"},
        "patients": [
            {"id": "p-1", "name": "Alice Adams", "room": "101", "status": "attention"},
            {"id": "p-2", "name": "Bob Brown", "room": "102", "status": "improving"},
            {"id": "p-3", "name": "Carol Clark", "room": "203", "status": "attention"},
            {"id": "p-4", "name": "Dave Davis", "room": "204", "status": "stable"},
        ],
    }


def test_facility_summary_counts_by_status():
    s = facility_summary(_data())
    assert s["total"] == 4
    assert s["counts"]["attention"] == 2
    assert s["counts"]["improving"] == 1
    assert s["counts"]["stable"] == 1
    assert s["counts"]["watch"] == 0
    assert s["facility"]["name"] == "Test Home"


def test_get_patient_found_and_missing():
    d = _data()
    assert get_patient(d, "p-2")["name"] == "Bob Brown"
    assert get_patient(d, "nope") is None


def test_search_filters_by_status():
    res = search_patients(_data(), status="attention")
    assert {p["id"] for p in res} == {"p-1", "p-3"}


def test_search_all_status_returns_everyone():
    assert len(search_patients(_data(), status="all")) == 4


def test_search_by_name_is_case_insensitive():
    res = search_patients(_data(), q="bob")
    assert len(res) == 1 and res[0]["id"] == "p-2"


def test_search_by_room_number():
    res = search_patients(_data(), q="203")
    assert len(res) == 1 and res[0]["id"] == "p-3"


def test_search_combines_query_and_status():
    res = search_patients(_data(), q="carol", status="attention")
    assert len(res) == 1 and res[0]["id"] == "p-3"


def test_search_empty_query_and_all_status_is_noop():
    assert len(search_patients(_data(), q="", status="all")) == 4

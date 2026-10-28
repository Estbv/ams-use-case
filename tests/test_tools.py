"""Pruebas de las tools (paso 4)."""
from __future__ import annotations

import json

import pytest

from app.tools.evidence import GetEvidenceDetail
from app.tools.known_issues import SearchKnownIssues
from app.tools.changes import GetRecentChanges
from app.tools.runbooks import SearchRunbooks
from app.tools.calendar import GetChangeCalendar
from app.tools.registry import (
    get_tools,
    get_openai_tools,
    executor,
    preload,
    TOOLS_BY_AGENT,
)


# ---------------------------------------------------------------------------
# 1. search_known_issues("ORA-12170") devuelve KI-002
# ---------------------------------------------------------------------------

def test_search_known_issues_ora12170() -> None:
    tool = SearchKnownIssues()
    result = tool.run({"query": "ORA-12170"})
    assert "error" not in result
    ids = [r["id"] for r in result["results"]]
    assert "KI-002" in ids


def test_search_known_issues_pool() -> None:
    tool = SearchKnownIssues()
    result = tool.run({"query": "pool agotado"})
    assert result["count"] >= 1
    ids = [r["id"] for r in result["results"]]
    assert "KI-001" in ids


def test_search_known_issues_empty_query() -> None:
    tool = SearchKnownIssues()
    result = tool.run({"query": ""})
    assert "error" in result


# ---------------------------------------------------------------------------
# 2. get_evidence_detail con ID inexistente devuelve error controlado
# ---------------------------------------------------------------------------

def test_get_evidence_detail_missing_id() -> None:
    tool = GetEvidenceDetail()
    result = tool.run({"ids": ["E999"]}, case=None)
    assert "error" in result
    assert "E999" in result["error"]


def test_get_evidence_detail_too_many_ids() -> None:
    tool = GetEvidenceDetail()
    result = tool.run({"ids": [f"E{i:03d}" for i in range(11)]}, case=None)
    assert "error" in result
    assert "10" in result["error"]


def test_get_evidence_detail_with_case() -> None:
    from app.models.case import Case

    case = Case(id="C1", evidence=[
        {"id": "E001", "summary": "test", "example": "linea", "example_stack": ["at foo"]},
    ])
    tool = GetEvidenceDetail()
    result = tool.run({"ids": ["E001"]}, case=case)
    assert "evidence" in result
    assert result["evidence"][0]["id"] == "E001"


# ---------------------------------------------------------------------------
# 3. to_openai_schema() y to_mcp_schema() son JSON valido
# ---------------------------------------------------------------------------

class TestSchemas:
    def test_openai_schema(self) -> None:
        tool = SearchKnownIssues()
        schema = tool.to_openai_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "search_known_issues"
        # Debe ser serializable
        json.dumps(schema)

    def test_mcp_schema(self) -> None:
        tool = SearchKnownIssues()
        schema = tool.to_mcp_schema()
        assert schema["name"] == "search_known_issues"
        assert "inputSchema" in schema
        json.dumps(schema)

    def test_all_tools_schemas(self) -> None:
        for tool in [
            GetEvidenceDetail(), SearchKnownIssues(), GetRecentChanges(),
            SearchRunbooks(), GetChangeCalendar(),
        ]:
            oa = tool.to_openai_schema()
            mcp = tool.to_mcp_schema()
            json.dumps(oa)
            json.dumps(mcp)
            assert oa["function"]["name"] == mcp["name"]


# ---------------------------------------------------------------------------
# 4. Registry
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_tools_by_agent(self) -> None:
        assert TOOLS_BY_AGENT["ingest"] == []
        assert TOOLS_BY_AGENT["communication"] == []
        assert "get_evidence_detail" in TOOLS_BY_AGENT["triage"]
        assert "search_known_issues" in TOOLS_BY_AGENT["root_cause"]
        assert "search_runbooks" in TOOLS_BY_AGENT["resolution"]

    def test_get_tools(self) -> None:
        tools = get_tools("root_cause")
        assert len(tools) == 3
        names = [t.name for t in tools]
        assert "search_known_issues" in names
        assert "get_evidence_detail" in names
        assert "get_recent_changes" in names

    def test_get_openai_tools(self) -> None:
        schemas = get_openai_tools("triage")
        assert len(schemas) == 1
        assert schemas[0]["function"]["name"] == "get_evidence_detail"

    def test_executor_unknown_tool(self) -> None:
        result = json.loads(executor("no_existe", {}, None))
        assert "error" in result

    def test_executor_valid_call(self) -> None:
        result = json.loads(executor("search_known_issues", {"query": "ORA-12170"}, None))
        assert "results" in result
        ids = [r["id"] for r in result["results"]]
        assert "KI-002" in ids

    def test_executor_bad_args(self) -> None:
        result = json.loads(executor("search_known_issues", "not json", None))
        assert "error" in result


# ---------------------------------------------------------------------------
# 5. get_recent_changes y get_change_calendar
# ---------------------------------------------------------------------------

def test_get_recent_changes() -> None:
    tool = GetRecentChanges()
    result = tool.run({"app": "checkout-service"})
    assert result["count"] >= 1
    assert any("CHG-55821" in str(c.get("id", "")) for c in result["changes"])


def test_get_change_calendar() -> None:
    tool = GetChangeCalendar()
    result = tool.run({})
    assert result["count"] >= 1
    names = [e.get("name", "") for e in result["entries"]]
    assert "BATCH_ARCHIVE" in names


# ---------------------------------------------------------------------------
# 6. search_runbooks
# ---------------------------------------------------------------------------

def test_search_runbooks() -> None:
    tool = SearchRunbooks()
    result = tool.run({"query": "pool agotado"})
    assert result["count"] >= 1
    assert "pool" in result["results"][0]["title"].lower()


# ---------------------------------------------------------------------------
# 7. preload (plan B)
# ---------------------------------------------------------------------------

def test_preload_root_cause() -> None:
    from app.models.case import Case

    case = Case(id="C1", evidence=[
        {"id": "E001", "summary": "ORA-00054 resource busy", "example": ""},
    ])
    results = preload("root_cause", case)
    assert len(results) > 0
    # Debe haber buscado ORA-00054
    assert any("ORA-00054" in k for k in results.keys())


def test_preload_ingest_empty() -> None:
    from app.models.case import Case

    case = Case(id="C1")
    results = preload("ingest", case)
    assert results == {}

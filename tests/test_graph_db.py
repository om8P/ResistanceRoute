"""Tests for pipeline.graph_db.

The first group needs no database. The second group runs against the project's
Neo4j and skips itself when it is unreachable. Integration tests only create and
delete nodes whose IDs are listed in TEST_IDS, so they are safe next to real data;
none of them calls ``clear_graph`` with ``confirm=True``.
"""

from __future__ import annotations

import uuid

import pytest

from pipeline.graph_db import (
    CONSTRAINTS_FILE,
    apply_constraints,
    clear_graph,
    get_driver,
    list_constraints,
    list_indexes,
    merge_edges,
    merge_nodes,
    ping,
    read_statements,
)
from pipeline.models import NODE_MODELS

# IDs are generated once per test process, so concurrent runs (other sessions
# using the same database) never share nodes. They stay inside the ID formats.
_TAG = uuid.uuid4().hex[:12]
_TAXID = 10**9 + uuid.uuid4().int % (10**9 - 1)
P1 = f"NCBITaxon:{_TAXID}"
P2 = f"NCBITaxon:{_TAXID + 1}"
M1 = f"LOCAL:mech:t01-test-{_TAG}"
C1 = f"t01-test-{_TAG}-class"
D1 = f"LOCAL:drug:t01-test-{_TAG}"
PASSAGE1 = f"t01-test-{_TAG}:section:1"
TEST_IDS = [P1, P2, M1, C1, D1, PASSAGE1]


# ---------------------------------------------------------------------------
# No database needed
# ---------------------------------------------------------------------------


def test_constraints_file_has_one_statement_per_line_ending_in_semicolon():
    lines = [
        line.strip()
        for line in CONSTRAINTS_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("//")
    ]
    assert lines and all(line.endswith(";") for line in lines)
    assert all(line.count(";") == 1 for line in lines)


def test_read_statements_covers_every_label_and_the_name_indexes():
    statements = read_statements()
    assert all(s.startswith("CREATE ") and not s.endswith(";") for s in statements)
    assert all("IF NOT EXISTS" in s for s in statements)
    for label in NODE_MODELS:
        assert any(f"(n:{label})" in s and "REQUIRE n.id IS UNIQUE" in s for s in statements), label
    for label in ("Drug", "Pathogen", "Mechanism", "DrugClass"):
        assert any(f"INDEX" in s and f"(n:{label}) ON (n.name)" in s for s in statements), label
    assert len(statements) == 13


def test_constraint_names_are_unique():
    names = [s.split()[2] for s in read_statements() if s.startswith("CREATE CONSTRAINT")]
    assert len(names) == 9 and len(set(names)) == 9


def test_read_statements_handles_comments_and_multiline(tmp_path):
    path = tmp_path / "x.cypher"
    path.write_text("// comment\n\nCREATE A\n  (n:X);\nCREATE B;\n", encoding="utf-8")
    assert read_statements(path) == ["CREATE A (n:X)", "CREATE B"]


class _NoDatabase:
    """Stands in for a driver; any use means a query was attempted."""

    def __getattr__(self, name):
        raise AssertionError(f"driver.{name} used although validation should have failed first")


@pytest.mark.parametrize(
    "label", ["Banana", "Drug) DETACH DELETE n //", "drug", "", "Drug {id: 1}"]
)
def test_merge_nodes_rejects_unknown_labels_before_querying(label):
    with pytest.raises(ValueError, match="unknown node label"):
        merge_nodes(_NoDatabase(), label, [{"id": "x"}])


@pytest.mark.parametrize("rel_type", ["LIKES", "has_mechanism", "HAS_MECHANISM]->(x) DETACH DELETE x //", ""])
def test_merge_edges_rejects_unknown_relationship_types_before_querying(rel_type):
    with pytest.raises(ValueError, match="unknown relationship type"):
        merge_edges(_NoDatabase(), rel_type, [])


def test_merge_edges_rejects_disallowed_pairs_before_querying():
    row = {"start_id": D1, "start_label": "Drug", "end_id": P1, "end_label": "Pathogen"}
    with pytest.raises(ValueError, match="Drug->Pathogen is not allowed for HAS_MECHANISM"):
        merge_edges(_NoDatabase(), "HAS_MECHANISM", [row])


def test_merge_edges_rejects_unknown_endpoint_labels_and_missing_keys():
    bad_label = {"start_id": "x", "start_label": "Banana", "end_id": "y", "end_label": "Mechanism"}
    with pytest.raises(ValueError):
        merge_edges(_NoDatabase(), "HAS_MECHANISM", [bad_label])
    with pytest.raises(ValueError, match="missing"):
        merge_edges(_NoDatabase(), "HAS_MECHANISM", [{"start_id": "x"}])


def test_merge_nodes_rejects_rows_without_id():
    with pytest.raises(ValueError, match="without an id"):
        merge_nodes(_NoDatabase(), "Drug", [{"name": "no id"}])


def test_merge_with_bad_batch_size_fails_before_writing():
    with pytest.raises(ValueError, match="batch_size"):
        merge_nodes(_NoDatabase(), "Drug", [{"id": D1}], batch_size=0)


def test_clear_graph_refuses_without_confirm():
    for kwargs in ({}, {"confirm": False}, {"confirm": "yes"}, {"confirm": 1}):
        with pytest.raises(ValueError, match="confirm=True"):
            clear_graph(_NoDatabase(), **kwargs)


def test_ping_returns_false_instead_of_raising(monkeypatch):
    import pipeline.graph_db as graph_db

    def boom(*args, **kwargs):
        raise RuntimeError("no driver")

    monkeypatch.setattr(graph_db, "get_driver", boom)
    assert ping() is False


# ---------------------------------------------------------------------------
# Live database
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def driver():
    if not ping():
        pytest.skip("Neo4j is not reachable; start it with `docker compose up -d`")
    drv = get_driver()
    apply_constraints(drv)
    yield drv
    drv.close()


@pytest.fixture
def clean(driver):
    def wipe():
        driver.execute_query("MATCH (n) WHERE n.id IN $ids DETACH DELETE n", ids=TEST_IDS)

    wipe()
    yield driver
    wipe()


def count(driver, cypher, **params):
    records, _, _ = driver.execute_query(cypher, **params)
    return records[0][0]


def test_ping_true_when_database_is_up(driver):
    assert ping() is True
    assert ping(driver) is True


def test_apply_constraints_creates_everything_and_is_idempotent(driver):
    first = apply_constraints(driver)
    second = apply_constraints(driver)
    assert first == second and len(first) == 13

    constraints = list_constraints(driver)
    by_label = {c["labels"][0]: c for c in constraints if c["name"].endswith("_id_unique")}
    assert set(NODE_MODELS) <= set(by_label)
    assert all(by_label[label]["properties"] == ["id"] for label in NODE_MODELS)

    indexed = {(i["labels"][0], tuple(i["properties"])) for i in list_indexes(driver)}
    for label in ("Drug", "Pathogen", "Mechanism", "DrugClass"):
        assert (label, ("name",)) in indexed


def test_uniqueness_constraint_is_enforced(clean):
    from neo4j.exceptions import ConstraintError

    clean.execute_query("CREATE (:Pathogen {id: $id})", id=P1)
    with pytest.raises(ConstraintError):
        clean.execute_query("CREATE (:Pathogen {id: $id})", id=P1)


def test_merge_nodes_creates_updates_and_is_idempotent(clean):
    rows = [
        {"id": P1, "name": "Test pathogen one", "gram_stain": "negative", "synonyms": ["a", "b"]},
        {"id": P2, "name": "Test pathogen two", "gram_stain": None},
    ]
    first = merge_nodes(clean, "Pathogen", rows)
    assert first["rows"] == 2 and first["nodes_created"] == 2

    second = merge_nodes(clean, "Pathogen", rows)
    assert second["nodes_created"] == 0
    assert count(clean, "MATCH (n:Pathogen) WHERE n.id IN $ids RETURN count(n)", ids=[P1, P2]) == 2

    node = clean.execute_query("MATCH (n:Pathogen {id: $id}) RETURN n", id=P1)[0][0]["n"]
    assert node["name"] == "Test pathogen one" and node["synonyms"] == ["a", "b"]
    other = clean.execute_query("MATCH (n:Pathogen {id: $id}) RETURN n", id=P2)[0][0]["n"]
    assert "gram_stain" not in other  # None values are not stored

    merge_nodes(clean, "Pathogen", [{"id": P1, "name": "Renamed"}])
    node = clean.execute_query("MATCH (n:Pathogen {id: $id}) RETURN n", id=P1)[0][0]["n"]
    assert node["name"] == "Renamed" and node["gram_stain"] == "negative"


def test_merge_nodes_batches(clean):
    rows = [{"id": P1, "name": "a"}, {"id": P2, "name": "b"}]
    result = merge_nodes(clean, "Pathogen", rows, batch_size=1)
    assert result["nodes_created"] == 2


def test_merge_nodes_accepts_empty_input(clean):
    assert merge_nodes(clean, "Pathogen", []) == {"rows": 0, "nodes_created": 0, "properties_set": 0}


def test_merge_edges_creates_with_provenance_and_is_idempotent(clean):
    merge_nodes(clean, "Pathogen", [{"id": P1, "name": "p"}])
    merge_nodes(clean, "Mechanism", [{"id": M1, "name": "m", "type": "other"}])
    rows = [
        {
            "start_id": P1,
            "start_label": "Pathogen",
            "end_id": M1,
            "end_label": "Mechanism",
            "source_id": "curated-seed",
            "method": "curated",
            "confidence": 1.0,
            "evidence_passage_id": None,
            "needs_review": "false",
        }
    ]
    first = merge_edges(clean, "HAS_MECHANISM", rows)
    assert first == {"rows": 1, "merged": 1, "missing_endpoints": 0, "relationships_created": 1}

    again = merge_edges(clean, "HAS_MECHANISM", rows)
    assert again["relationships_created"] == 0 and again["merged"] == 1

    rel = clean.execute_query(
        "MATCH (:Pathogen {id: $a})-[r:HAS_MECHANISM]->(:Mechanism {id: $b}) RETURN r", a=P1, b=M1
    )[0][0]["r"]
    assert rel["source_id"] == "curated-seed" and rel["method"] == "curated"
    assert rel["confidence"] == 1.0 and rel["needs_review"] == "false"
    assert "evidence_passage_id" not in rel and "start_id" not in rel


def test_merge_edges_counts_rows_with_missing_endpoints_and_creates_no_nodes(clean):
    merge_nodes(clean, "Pathogen", [{"id": P1, "name": "p"}])
    row = {
        "start_id": P1,
        "start_label": "Pathogen",
        "end_id": M1,  # mechanism was never created
        "end_label": "Mechanism",
        "source_id": "curated-seed",
        "method": "curated",
        "confidence": 1.0,
    }
    result = merge_edges(clean, "HAS_MECHANISM", [row])
    assert result["merged"] == 0 and result["missing_endpoints"] == 1
    assert count(clean, "MATCH (n) WHERE n.id = $id RETURN count(n)", id=M1) == 0


def test_merge_edges_handles_several_label_pairs_in_one_call(clean):
    merge_nodes(clean, "Drug", [{"id": D1, "name": "d"}])
    merge_nodes(clean, "DrugClass", [{"id": C1, "name": "c"}])
    merge_nodes(clean, "Pathogen", [{"id": P1, "name": "p"}])
    merge_nodes(clean, "Passage", [{"id": PASSAGE1, "text": "t", "source_doc": f"t01-test-{_TAG}", "section": "section"}])
    base = {"source_id": "pubmed", "method": "rule", "confidence": 0.5, "start_id": PASSAGE1, "start_label": "Passage"}
    rows = [
        {**base, "end_id": D1, "end_label": "Drug"},
        {**base, "end_id": C1, "end_label": "DrugClass"},
        {**base, "end_id": P1, "end_label": "Pathogen"},
    ]
    result = merge_edges(clean, "MENTIONS", rows, batch_size=1)
    assert result["merged"] == 3 and result["relationships_created"] == 3


def test_clear_graph_without_confirm_leaves_data_untouched(clean):
    merge_nodes(clean, "Pathogen", [{"id": P1, "name": "p"}])
    with pytest.raises(ValueError):
        clear_graph(clean)
    assert count(clean, "MATCH (n:Pathogen {id: $id}) RETURN count(n)", id=P1) == 1

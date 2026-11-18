"""Tests for pipeline.load (task T05).

The unit tests need no database. The integration tests load a small graph into the
project's Neo4j and skip themselves when it is unreachable. Every ID is generated per
test process (so concurrent runs never collide) and the cleanup deletes only those IDs;
nothing here calls ``clear_graph`` or ``--clear``.
"""

from __future__ import annotations

import json
import random
import uuid

import pytest

from pipeline.graph_db import get_driver, ping
from pipeline.load import (
    ACCEPTANCE_QUERY,
    _coerce_extras,
    dedupe_edges,
    load_directory,
    report_is_clean,
)
from pipeline.validate import write_csv_rows

EDGE_FIELDS = [
    "start_id", "start_label", "end_id", "end_label",
    "source_id", "method", "confidence", "evidence_passage_id", "needs_review", "notes",
]


def _edge(start, s_label, end, e_label, method="curated", confidence="1.0", source="curated-seed", **extra):
    row = dict.fromkeys(EDGE_FIELDS, "")
    row.update(
        start_id=start, start_label=s_label, end_id=end, end_label=e_label,
        source_id=source, method=method, confidence=confidence,
    )
    row.update(extra)
    return row


# ---------------------------------------------------------------------------
# Unit tests (no database)
# ---------------------------------------------------------------------------


def test_dedupe_prefers_curated_then_rule_then_llm():
    rows = [
        _edge("a", "Drug", "b", "DrugClass", method="llm", confidence="0.9", source="pubmed"),
        _edge("a", "Drug", "b", "DrugClass", method="curated"),
        _edge("a", "Drug", "b", "DrugClass", method="rule", confidence="0.8", source="card"),
        _edge("c", "Drug", "d", "DrugClass", method="llm", confidence="0.5", source="pubmed"),
        _edge("c", "Drug", "d", "DrugClass", method="llm", confidence="0.7", source="pubmed"),
    ]
    kept, dropped = dedupe_edges(rows)
    assert dropped == 3
    assert [(r["start_id"], r["method"], r["confidence"]) for r in kept] == [
        ("a", "curated", "1.0"),
        ("c", "llm", "0.7"),
    ]


def test_dedupe_keeps_distinct_pairs_in_order():
    rows = [_edge("a", "Drug", "b", "DrugClass"), _edge("a", "Drug", "c", "DrugClass")]
    kept, dropped = dedupe_edges(rows)
    assert kept == rows and dropped == 0


def test_coerce_extras_turns_true_false_into_booleans_only_for_extras():
    row = _edge("a", "Drug", "b", "DrugClass", needs_review="true", notes="false alarm")
    out = _coerce_extras(row)
    assert out["needs_review"] is True
    assert out["notes"] == "false alarm"
    assert out["source_id"] == "curated-seed"
    assert _coerce_extras({"needs_review": "false"})["needs_review"] is False


def test_acceptance_query_uses_the_three_exclusion_kinds():
    for fragment in ("INTRINSICALLY_RESISTANT_TO", "CONFERS_RESISTANCE_TO", "INACTIVATES", "IN_CLASS"):
        assert fragment in ACCEPTANCE_QUERY


# ---------------------------------------------------------------------------
# Integration tests (Neo4j)
# ---------------------------------------------------------------------------

_TAG = uuid.uuid4().hex[:12]
_RNG = random.Random(uuid.uuid4().int)


def _atc() -> str:
    # 'Z' is not an ATC main group, so these never collide with real drugs.
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return f"Z{_RNG.randrange(100):02d}{_RNG.choice(letters)}{_RNG.choice(letters)}{_RNG.randrange(100):02d}"


_TAXID = 10**9 + uuid.uuid4().int % (10**9 - 10)
PATHOGEN = f"NCBITaxon:{_TAXID}"
MECH = f"LOCAL:mech:t05-{_TAG}"
CLS_KEEP, CLS_CONFERS, CLS_INTRINSIC, CLS_OTHER = (f"t05-{_TAG}-{n}" for n in ("keep", "confers", "intr", "other"))
DRUG_KEEP, DRUG_CONFERS, DRUG_INTRINSIC, DRUG_INACT = (_atc() for _ in range(4))
while len({DRUG_KEEP, DRUG_CONFERS, DRUG_INTRINSIC, DRUG_INACT}) < 4:  # pragma: no cover
    DRUG_INACT = _atc()
NAMES = {
    DRUG_KEEP: f"keepdrug-{_TAG}",
    DRUG_CONFERS: f"confersdrug-{_TAG}",
    DRUG_INTRINSIC: f"intrdrug-{_TAG}",
    DRUG_INACT: f"inactdrug-{_TAG}",
}
BAD_NODE_ID = "not a valid drug id"
TEST_IDS = [
    PATHOGEN, MECH, CLS_KEEP, CLS_CONFERS, CLS_INTRINSIC, CLS_OTHER,
    DRUG_KEEP, DRUG_CONFERS, DRUG_INTRINSIC, DRUG_INACT,
]


@pytest.fixture(scope="module")
def driver():
    if not ping():
        pytest.skip("Neo4j is not reachable (docker compose up -d)")
    drv = get_driver()
    yield drv
    drv.close()


@pytest.fixture
def clean(driver):
    def wipe():
        driver.execute_query("MATCH (n) WHERE n.id IN $ids DETACH DELETE n", ids=TEST_IDS)

    wipe()
    yield
    wipe()


def _write_mini_graph(directory):
    write_csv_rows(
        directory / "nodes_Pathogen.csv",
        [{"id": PATHOGEN, "name": f"Testbacter {_TAG}", "gram_stain": "negative", "synonyms": ["tb"]}],
    )
    write_csv_rows(
        directory / "nodes_Mechanism.csv",
        [{"id": MECH, "name": f"Testase {_TAG}", "type": "carbapenemase", "ambler_class": "A"}],
    )
    write_csv_rows(
        directory / "nodes_DrugClass.csv",
        [{"id": c, "name": c, "family": "test-family"} for c in (CLS_KEEP, CLS_CONFERS, CLS_INTRINSIC, CLS_OTHER)],
    )
    drugs = [{"id": d, "name": NAMES[d], "aware_group": "Watch", "synonyms": []} for d in NAMES]
    drugs.append({"id": BAD_NODE_ID, "name": "broken", "aware_group": "Watch", "synonyms": []})
    write_csv_rows(directory / "nodes_Drug.csv", drugs)
    write_csv_rows(
        directory / "edges_IN_CLASS.csv",
        [
            _edge(DRUG_KEEP, "Drug", CLS_KEEP, "DrugClass"),
            _edge(DRUG_CONFERS, "Drug", CLS_CONFERS, "DrugClass"),
            _edge(DRUG_INTRINSIC, "Drug", CLS_INTRINSIC, "DrugClass"),
            _edge(DRUG_INACT, "Drug", CLS_OTHER, "DrugClass"),
            # dangling: this drug was rejected above
            _edge(BAD_NODE_ID, "Drug", CLS_KEEP, "DrugClass"),
        ],
        EDGE_FIELDS,
    )
    write_csv_rows(
        directory / "edges_HAS_MECHANISM.csv",
        [
            _edge(PATHOGEN, "Pathogen", MECH, "Mechanism", method="llm", confidence="0.4", source="pubmed"),
            _edge(PATHOGEN, "Pathogen", MECH, "Mechanism", needs_review="true", notes="from the seed"),
        ],
        EDGE_FIELDS,
    )
    write_csv_rows(
        directory / "edges_CONFERS_RESISTANCE_TO.csv",
        [_edge(MECH, "Mechanism", CLS_CONFERS, "DrugClass")],
        EDGE_FIELDS,
    )
    write_csv_rows(
        directory / "edges_INTRINSICALLY_RESISTANT_TO.csv",
        [_edge(PATHOGEN, "Pathogen", CLS_INTRINSIC, "DrugClass")],
        EDGE_FIELDS,
    )
    write_csv_rows(
        directory / "edges_INACTIVATES.csv",
        [_edge(MECH, "Mechanism", DRUG_INACT, "Drug", needs_review="false")],
        EDGE_FIELDS,
    )
    # Files the loader has never seen must be reported, not crash it.
    write_csv_rows(directory / "nodes_Mystery.csv", [{"id": "x"}])
    write_csv_rows(directory / "edges_MYSTERY.csv", [_edge("a", "Drug", "b", "Drug")], EDGE_FIELDS)


def test_load_directory_loads_reports_and_rejects(driver, clean, tmp_path):
    _write_mini_graph(tmp_path)
    report_path = tmp_path / "report.json"
    report = load_directory(tmp_path, driver=driver, report_path=report_path, acceptance=False)

    # Counts and reasons are reported per file.
    files = report["files"]
    assert files["nodes_Drug.csv"]["accepted"] == 4
    assert files["nodes_Drug.csv"]["rejected"] == 1
    assert files["nodes_Drug.csv"]["examples"][0]["row"] == 5
    assert files["edges_IN_CLASS.csv"]["accepted"] == 4
    assert files["edges_IN_CLASS.csv"]["rejected"] == 1
    assert any("not found" in reason for reason in files["edges_IN_CLASS.csv"]["reasons"])
    # Two rows for one pair collapse to the curated one (D27) before validation.
    assert files["edges_HAS_MECHANISM.csv"]["duplicates_merged"] == 1
    assert files["edges_HAS_MECHANISM.csv"]["rejected"] == 0
    assert files["edges_HAS_MECHANISM.csv"]["relationships_created"] == 1
    # Unknown file names are problems, not crashes; the run is not clean.
    assert len(report["file_problems"]) == 2
    assert not report_is_clean(report)
    assert json.loads(report_path.read_text(encoding="utf-8"))["totals"] == report["totals"]

    # Nodes and edges are really in the database.
    records, _, _ = driver.execute_query(
        "MATCH (p:Pathogen {id: $p})-[r:HAS_MECHANISM]->(m:Mechanism {id: $m}) "
        "RETURN r.method AS method, r.source_id AS source, r.needs_review AS review, r.notes AS notes",
        p=PATHOGEN, m=MECH,
    )
    assert len(records) == 1
    assert records[0]["method"] == "curated"
    assert records[0]["source"] == "curated-seed"
    assert records[0]["review"] is True  # "true" in the CSV is stored as a boolean
    assert records[0]["notes"] == "from the seed"
    records, _, _ = driver.execute_query(
        "MATCH (d:Drug {id: $d}) RETURN d.name AS name, d.aware_group AS g", d=DRUG_KEEP
    )
    assert records[0]["name"] == NAMES[DRUG_KEEP]


def test_loading_twice_is_idempotent(driver, clean, tmp_path):
    _write_mini_graph(tmp_path)
    first = load_directory(tmp_path, driver=driver, report_path=tmp_path / "r1.json", acceptance=False)
    second = load_directory(tmp_path, driver=driver, report_path=tmp_path / "r2.json", acceptance=False)
    assert first["totals"]["nodes_created"] == 10  # 1 pathogen + 1 mechanism + 4 classes + 4 drugs
    assert second["totals"]["nodes_created"] == 0
    assert second["totals"]["edges_created"] == 0


def test_acceptance_query_excludes_by_class_intrinsic_and_drug(driver, clean, tmp_path):
    _write_mini_graph(tmp_path)
    load_directory(tmp_path, driver=driver, report_path=tmp_path / "r.json", acceptance=False)
    records, _, _ = driver.execute_query(ACCEPTANCE_QUERY, pathogen=PATHOGEN, mechanisms=[MECH])
    assert len(records) == 1
    left = set(records[0]["drugs_not_excluded"])
    assert NAMES[DRUG_KEEP] in left
    assert NAMES[DRUG_CONFERS] not in left  # class from CONFERS_RESISTANCE_TO
    assert NAMES[DRUG_INTRINSIC] not in left  # class from INTRINSICALLY_RESISTANT_TO
    assert NAMES[DRUG_INACT] not in left  # drug from INACTIVATES


def test_load_directory_without_clear_keeps_other_nodes(driver, clean, tmp_path):
    marker = f"t05-{_TAG}-marker"
    driver.execute_query("MERGE (c:DrugClass {id: $id}) SET c.name = 'marker'", id=marker)
    try:
        _write_mini_graph(tmp_path)
        report = load_directory(tmp_path, driver=driver, report_path=tmp_path / "r.json", acceptance=False)
        assert report["cleared"] is False
        records, _, _ = driver.execute_query("MATCH (c:DrugClass {id: $id}) RETURN count(c) AS n", id=marker)
        assert records[0]["n"] == 1
    finally:
        driver.execute_query("MATCH (c:DrugClass {id: $id}) DETACH DELETE c", id=marker)

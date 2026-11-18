"""Checks for the relevance judgements (task T15): eval/qrels.json and eval/build_pool.py.

qrels.json maps each evaluation question to the passages judged relevant, with grade 2
(states the answer or a key part of it) or 1 (on topic, useful context). Grade-0 passages
are not listed. Decline questions have no relevant passages (T15 brief).

The pool-building helpers are tested on small in-memory data, so these tests do not load
the retrieval indexes or models.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval import build_pool as bp

ROOT = Path(__file__).resolve().parents[1]
QRELS_PATH = ROOT / "eval" / "qrels.json"
QUESTIONS_PATH = ROOT / "eval" / "questions.json"
PASSAGES_PATH = ROOT / "data" / "processed" / "passages.jsonl"


@pytest.fixture(scope="module")
def qrels() -> dict[str, dict[str, int]]:
    return json.loads(QRELS_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def questions() -> list[dict]:
    return json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))


# --- qrels.json -------------------------------------------------------------------------


def test_every_question_has_an_entry(qrels, questions):
    assert set(qrels) == {q["id"] for q in questions}


def test_shape_is_question_to_passage_to_grade(qrels):
    for qid, grades in qrels.items():
        assert isinstance(grades, dict), qid
        for pid, grade in grades.items():
            assert isinstance(pid, str) and pid, qid
            assert type(grade) is int, (qid, pid)


def test_grades_are_one_or_two(qrels):
    bad = [(q, p, g) for q, gs in qrels.items() for p, g in gs.items() if g not in (1, 2)]
    assert not bad


def test_decline_questions_have_no_relevant_passages(qrels, questions):
    declines = [q["id"] for q in questions if q["intent"] == "decline"]
    assert declines, "expected decline questions in the set"
    for qid in declines:
        assert qrels[qid] == {}, qid


def test_every_answerable_question_has_a_relevant_passage(qrels, questions):
    # Every non-decline question had at least one passage judged 1 or 2.
    for q in questions:
        if q["intent"] != "decline":
            assert qrels[q["id"]], q["id"]


@pytest.mark.skipif(not PASSAGES_PATH.exists(), reason="data/processed/passages.jsonl not built")
def test_every_passage_id_exists(qrels):
    with PASSAGES_PATH.open(encoding="utf-8") as f:
        ids = {json.loads(line)["id"] for line in f if line.strip()}
    missing = sorted({p for gs in qrels.values() for p in gs} - ids)
    assert not missing, missing[:10]


def test_manual_additions_are_judged(qrels):
    for qid, pids in bp.MANUAL.items():
        for pid in pids:
            assert pid in qrels[qid], (qid, pid)


# --- build_pool helpers -----------------------------------------------------------------


def test_gold_pages_reads_only_guideline_page_sources():
    q = {"gold_source": [
        "icmr-cr-gram-negative-2022 p17",
        "who-aware-book-2022 p596",
        "curated-seed data/curated/mechanism_class.csv lines 2-11",
        "who-aware-2025 sheet 'AWaRe classification 2025' row 142",
    ]}
    assert bp.gold_pages(q) == [("icmr-cr-gram-negative-2022", 17), ("who-aware-book-2022", 596)]


def _passages():
    return [
        {"id": "a:1", "source_doc": "a", "page": 3},
        {"id": "a:2", "source_doc": "a", "page": 5},
        {"id": "a:3", "source_doc": "a", "page": 5},
        {"id": "b:1", "source_doc": "b", "page": 5},
        {"id": "p:1", "source_doc": "pubmed-1", "page": None},
    ]


def test_page_spans_run_to_next_passage_start():
    spans = bp.page_spans(_passages())
    assert spans["a:1"] == ("a", 3, 5)  # may run onto page 5 where a:2 starts
    assert spans["a:2"] == ("a", 5, 5)
    assert spans["a:3"] == ("a", 5, 5)  # last passage of its document
    assert "p:1" not in spans  # abstracts have no page


def test_passages_on_pages_matches_document_and_page():
    spans = bp.page_spans(_passages())
    assert set(bp.passages_on_pages([("a", 4)], spans)) == {"a:1"}
    assert set(bp.passages_on_pages([("a", 5)], spans)) == {"a:1", "a:2", "a:3"}
    assert set(bp.passages_on_pages([("b", 5)], spans)) == {"b:1"}
    assert bp.passages_on_pages([("c", 5)], spans) == []


def test_stats_counts_grades_and_methods():
    pool = {"Q1": {"x": ["bm25", "dense"], "y": ["entities"], "z": ["gold_page"]}}
    qrels = {"Q1": {"x": 2, "y": 1}}
    s = bp.stats(pool, qrels)
    assert s["per_question"]["Q1"] == {"pool": 3, "grade2": 1, "grade1": 1, "grade0": 1}
    assert s["pooled_by_method"] == {"bm25": 1, "dense": 1, "entities": 1, "gold_page": 1}
    assert s["relevant_by_method"]["bm25"] == {"grade2": 1, "grade1": 0}
    assert s["relevant_by_method"]["entities"] == {"grade2": 0, "grade1": 1}
    assert s["relevant_only_by"] == {"entities": 1}
    assert s["judged_but_not_pooled"] == []


def test_stats_reports_judged_passages_missing_from_pool():
    s = bp.stats({"Q1": {"x": ["bm25"]}}, {"Q1": {"x": 1, "w": 2}})
    assert s["judged_but_not_pooled"] == ["Q1 w"]

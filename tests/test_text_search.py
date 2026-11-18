"""Tests for retrieval.build_index and retrieval.text_search (T11).

The index tests build a tiny index in a temp folder, so they do not depend on
the real corpus; a last group checks the real index if it exists.
"""
import csv
import json

import pytest

from retrieval import text_search as ts
from retrieval.build_index import INDEX_DIR, build, tokenize

PASSAGES = [
    ("d1:a:1", "Ceftazidime-avibactam plus aztreonam is recommended for NDM producing Klebsiella pneumoniae infections."),
    ("d1:a:2", "Colistin is a Reserve antibiotic and should be kept for multidrug resistant infections."),
    ("d1:b:1", "MRSA osteomyelitis in adults is treated with vancomycin or linezolid for several weeks."),
    ("d1:b:2", "Amoxicillin is an Access antibiotic used for community acquired pneumonia in children."),
    ("d2:abstract:1", "Cefiderocol activity against carbapenem resistant Acinetobacter baumannii in an outbreak."),
]


@pytest.fixture(scope="module")
def idx(tmp_path_factory):
    d = tmp_path_factory.mktemp("idx")
    pp = d / "passages.jsonl"
    with open(pp, "w", encoding="utf-8") as fh:
        for pid, text in PASSAGES:
            fh.write(json.dumps({"id": pid, "text": text, "source_doc": pid.split(":")[0], "section": pid.split(":")[1],
                                 "page": 3, "n_words": len(text.split())}) + "\n")
    mp = d / "mentions_linked.jsonl"
    rows = [
        ("d1:a:1", "J01DD52"), ("d1:a:1", "J01DF01"), ("d1:a:1", "ARO:NDM"), ("d1:a:1", "NCBITaxon:573"),
        ("d1:a:2", "J01XB01"), ("d1:b:1", "NCBITaxon:1280"), ("d1:b:1", "NCBITaxon:1280"),
        ("d2:abstract:1", "NCBITaxon:470"), ("d1:b:2", "J01CA04"),
    ]
    with open(mp, "w", encoding="utf-8") as fh:
        for pid, eid in rows:
            fh.write(json.dumps({"passage_id": pid, "entity_id": eid}) + "\n")
    sp = d / "edges_SUPPORTS.csv"
    with open(sp, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["start_id", "start_label", "end_id", "end_label"])
        w.writerow(["d1:a:1", "Passage", "REC:1", "Recommendation"])
        w.writerow(["d1:a:2", "Passage", "REC:1", "Recommendation"])
    out = d / "index"
    build(pp, out)
    return ts.TextIndex(out, pp, mp, sp), out


# --- tokenisation ----------------------------------------------------------
def test_tokenize_lowercases():
    assert tokenize("Colistin MRSA") == ["colistin", "mrsa"]


def test_tokenize_hyphenated_name_whole_and_parts():
    assert tokenize("Ceftazidime-avibactam") == ["ceftazidime-avibactam", "ceftazidime", "avibactam"]


def test_tokenize_slash_and_plus():
    assert tokenize("TMP/SMX") == ["tmp/smx", "tmp", "smx"]
    assert "ampicillin+sulbactam" in tokenize("ampicillin+sulbactam")


def test_tokenize_keeps_allele_names():
    toks = tokenize("OXA-48-like and NDM-1")
    assert "oxa-48-like" in toks and "oxa" in toks and "48" in toks and "like" in toks
    assert "ndm-1" in toks


def test_tokenize_removes_stop_words_not_content():
    assert tokenize("the use of colistin is for the sick") == ["use", "colistin", "sick"]


def test_tokenize_punctuation_and_empty():
    assert tokenize("") == []
    assert tokenize("(colistin), [meropenem].") == ["colistin", "meropenem"]


# --- build outputs ---------------------------------------------------------
def test_build_writes_meta_and_files(idx):
    _, out = idx
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    assert meta["dense"]["model"] == "sentence-transformers/all-MiniLM-L6-v2"
    assert meta["dense"]["faiss_index"] == "IndexHNSWFlat"
    assert meta["dense"]["metric"] == "inner_product" and meta["dense"]["normalized"] is True
    assert meta["n_passages"] == len(PASSAGES)
    assert meta["fusion"]["k"] == 60
    for name in ("bm25.pkl", "dense.faiss", "embeddings.npy", "passage_ids.json"):
        assert (out / name).exists()


# --- modes -----------------------------------------------------------------
def test_unknown_mode_raises(idx):
    with pytest.raises(ValueError):
        idx[0].search("colistin", "graph")


@pytest.mark.parametrize("mode", ts.MODES)
def test_each_mode_finds_the_obvious_passage(idx, mode):
    hits = idx[0].search("colistin reserve antibiotic", mode, k=3)
    assert hits[0].passage_id == "d1:a:2"
    assert [h.rank for h in hits] == list(range(1, len(hits) + 1))
    assert all(isinstance(h, ts.PassageHit) for h in hits)


def test_hit_fields(idx):
    h = idx[0].search("MRSA osteomyelitis", "bm25", k=1)[0]
    assert (h.passage_id, h.source_doc, h.section, h.page) == ("d1:b:1", "d1", "b", 3)
    assert "osteomyelitis" in h.text and h.score > 0


def test_bm25_hyphenated_query_matches_parts(idx):
    hits = idx[0].search("avibactam", "bm25", k=3)
    assert [h.passage_id for h in hits] == ["d1:a:1"]  # only the passage containing the part


def test_bm25_returns_only_positive_scores(idx):
    assert idx[0].search("zzzunknownword", "bm25", k=5) == []


def test_dense_returns_k_results_even_without_word_overlap(idx):
    hits = idx[0].search("drug for bone infection", "dense", k=3)
    assert len(hits) == 3
    assert hits[0].passage_id == "d1:b:1"


def test_k_limits_and_empty_query(idx):
    assert len(idx[0].search("antibiotic", "bm25_dense", k=2)) == 2
    assert idx[0].search("   ", "bm25_dense") == []
    assert idx[0].search("antibiotic", "bm25", k=0) == []


def test_no_duplicate_passages(idx):
    ids = [h.passage_id for h in idx[0].search("carbapenem resistant infections", "bm25_dense", k=10)]
    assert len(ids) == len(set(ids))


# --- RRF -------------------------------------------------------------------
def test_rrf_scores():
    fused = dict(ts.rrf([["a", "b"], ["b", "c"]]))
    assert fused["a"] == pytest.approx(1 / 61)
    assert fused["b"] == pytest.approx(1 / 62 + 1 / 61)
    assert fused["c"] == pytest.approx(1 / 62)


def test_rrf_order_and_tie_break():
    fused = ts.rrf([["a", "b"], ["b", "a"]])
    assert [p for p, _ in fused] == ["a", "b"]  # equal scores: first seen wins
    assert fused[0][1] == pytest.approx(1 / 61 + 1 / 62)


def test_rrf_ignores_repeats_within_a_list():
    assert dict(ts.rrf([["a", "a"]]))["a"] == pytest.approx(1 / 61)


def test_bm25_dense_score_is_rrf_of_the_two_lists(idx):
    index = idx[0]
    q = "colistin reserve antibiotic"
    b = [h.passage_id for h in index.search(q, "bm25", k=100)]
    d = [h.passage_id for h in index.search(q, "dense", k=100)]
    expected = ts.rrf([b, d])[:3]
    got = [(h.passage_id, h.score) for h in index.search(q, "bm25_dense", k=3)]
    assert [p for p, _ in got] == [p for p, _ in expected]
    assert [s for _, s in got] == pytest.approx([s for _, s in expected])


# --- entity filtering ------------------------------------------------------
@pytest.mark.parametrize("mode", ts.MODES)
def test_entity_filter_restricts_results(idx, mode):
    hits = idx[0].search("antibiotic infections", mode, k=10, entity_ids=["J01XB01"])
    assert [h.passage_id for h in hits] == ["d1:a:2"]


def test_entity_filter_union_of_entities(idx):
    hits = idx[0].search("antibiotic infections", "dense", k=10, entity_ids=["J01XB01", "NCBITaxon:470"])
    assert {h.passage_id for h in hits} == {"d1:a:2", "d2:abstract:1"}


def test_entity_filter_via_supports_edges(idx):
    hits = idx[0].search("antibiotic infections", "dense", k=10, entity_ids=["REC:1"])
    assert {h.passage_id for h in hits} == {"d1:a:1", "d1:a:2"}


def test_entity_filter_unknown_entity_gives_nothing(idx):
    for mode in ts.MODES:
        assert idx[0].search("colistin", mode, k=5, entity_ids=["NOPE"]) == []


def test_passages_for_entities_most_connected_first(idx):
    hits = idx[0].passages_for_entities(["J01DD52", "J01DF01", "REC:1"], k=5)
    assert [h.passage_id for h in hits] == ["d1:a:1", "d1:a:2"]  # 3 entities vs 1
    assert hits[0].score == 3 and hits[1].score == 1
    assert [h.rank for h in hits] == [1, 2]


def test_passages_for_entities_tie_goes_to_more_mentions(idx):
    hits = idx[0].passages_for_entities(["NCBITaxon:1280", "J01CA04"], k=5)
    assert [h.passage_id for h in hits] == ["d1:b:1", "d1:b:2"]  # both 1 entity; b:1 has 2 mentions


def test_passages_for_entities_k_and_empty(idx):
    assert len(idx[0].passages_for_entities(["REC:1"], k=1)) == 1
    assert idx[0].passages_for_entities([], k=5) == []
    assert idx[0].passages_for_entities(["REC:1"], k=0) == []
    assert idx[0].passages_for_entities(["REC:1", "REC:1"], k=5)[0].score == 1  # duplicates counted once


# --- stability -------------------------------------------------------------
@pytest.mark.parametrize("mode", ts.MODES)
def test_results_are_stable(idx, mode):
    a = [(h.passage_id, h.score) for h in idx[0].search("carbapenem resistant infections", mode, k=5)]
    b = [(h.passage_id, h.score) for h in idx[0].search("carbapenem resistant infections", mode, k=5)]
    assert a == b


def test_stale_index_is_detected(idx, tmp_path):
    _, out = idx
    other = tmp_path / "p.jsonl"
    other.write_text(json.dumps({"id": "x:y:1", "text": "t", "source_doc": "x", "section": "y"}) + "\n", encoding="utf-8")
    stale = ts.TextIndex(out, other)
    with pytest.raises(RuntimeError):
        stale.bm25


# --- the real index (skipped if not built) ---------------------------------
real = pytest.mark.skipif(not (INDEX_DIR / "meta.json").exists(), reason="real index not built")


@real
def test_real_index_matches_passages():
    meta = json.loads((INDEX_DIR / "meta.json").read_text(encoding="utf-8"))
    n = sum(1 for _ in open(ts.PASSAGES_PATH, encoding="utf-8"))
    assert meta["n_passages"] == n


@real
def test_real_index_known_query():
    hits = ts.search("ceftazidime-avibactam aztreonam NDM", "bm25_dense", k=5)
    assert any("icmr-cr-gram-negative-2022" in h.passage_id for h in hits)

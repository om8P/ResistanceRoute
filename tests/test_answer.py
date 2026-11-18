"""Tests for retrieval/fusion.py and retrieval/answer.py (T14).

Questions are written for these tests; eval/questions.json is not used (D16). Tests that need the
graph are skipped when Neo4j is unreachable. Tests with stubs run without a database.
"""
from __future__ import annotations

import re

import pytest

from retrieval import answer as ans
from retrieval import fusion
from retrieval.types import Answer, GraphResult, ParsedQuery, Path, PassageHit

Q_ALT = "If carbapenem resistance is reported for Klebsiella, which guideline-listed alternatives remain?"
INTENT_QUESTIONS = {
    "alternatives": Q_ALT,
    "why_restricted": "Why is colistin restricted?",
    "mechanism_lookup": "How does E. coli resist cephalosporins?",
    "recommendation_lookup": "What is recommended for MRSA bloodstream infection?",
    "drug_profile": "What class and AWaRe group is meropenem?",
    "surveillance": "How common is carbapenem resistance in Klebsiella in India?",
}
KEYS = {"question", "mode", "intent", "entities", "answers", "other_active", "paths", "passages",
        "answer_text", "declined", "decline_reason", "disclaimer"}


@pytest.fixture(scope="module")
def neo4j():
    from pipeline.graph_db import ping

    if not ping():
        pytest.skip("Neo4j is not reachable")


def hit(pid: str, rank: int = 1, score: float = 1.0) -> PassageHit:
    return PassageHit(pid, score, rank, f"text of {pid}", "icmr-cr-gram-negative-2022", "sec", 1)


def drug(i: str, name: str, score: float, recs=(), group="KPC") -> Answer:
    return Answer(id=i, label="Drug", name=name, group=group, aware_group="Reserve",
                  recommendation_ids=list(recs), caveats=[], score=score)


def check_shape(r: dict, mode: str):
    assert KEYS <= set(r)
    assert r["mode"] == mode
    assert r["disclaimer"] and "not medical advice" in r["disclaimer"]
    assert r["answer_text"].rstrip().endswith(r["disclaimer"])
    assert not re.search(r"\b\d+\s?(mg|mcg|g)\b|mg/kg|q\d+h", r["answer_text"])  # no doses (D18)


# ---------------------------------------------------------------------------
# RRF and fusion helpers (no database)
# ---------------------------------------------------------------------------


def test_rrf_values_and_order():
    out = dict(fusion.rrf([["a", "b", "c"], ["b", "a", "d"]]))
    assert out["a"] == pytest.approx(1 / 61 + 1 / 62)
    assert out["b"] == pytest.approx(1 / 62 + 1 / 61)
    assert out["c"] == pytest.approx(1 / 63)
    assert out["d"] == pytest.approx(1 / 63)
    ranked = [x for x, _ in fusion.rrf([["a", "b"], ["c", "a"]])]
    assert ranked[0] == "a"  # in both lists


def test_rrf_ignores_duplicates_within_a_list_and_is_stable():
    # the repeat counts once for "a"; positions still advance, as in text_search.rrf
    assert fusion.rrf([["a", "a", "b"]]) == [("a", pytest.approx(1 / 61)), ("b", pytest.approx(1 / 63))]
    assert [x for x, _ in fusion.rrf([["x"], ["y"]])] == ["x", "y"]  # tie: first seen first


def test_fuse_passages_three_lists_uses_k_60():
    bm, de, gr = [hit("p1"), hit("p2")], [hit("p2"), hit("p3")], [hit("p3"), hit("p1")]
    fused = fusion.fuse_passages([bm, de, gr], k=3)
    scores = {h.passage_id: h.score for h in fused}
    assert scores["p1"] == pytest.approx(1 / 61 + 1 / 62)
    assert scores["p2"] == pytest.approx(1 / 62 + 1 / 61)
    assert scores["p3"] == pytest.approx(1 / 62 + 1 / 61)
    assert [h.rank for h in fused] == [1, 2, 3]
    assert len(fusion.fuse_passages([bm, de, gr], k=2)) == 2


def test_text_baseline_filters_type_excludes_question_entities_and_ranks_by_rrf():
    mentions = {
        "p1": [{"entity_id": "D1", "entity_type": "Drug", "canonical_name": "colistin"},
               {"entity_id": "M1", "entity_type": "Mechanism", "canonical_name": "KPC"},
               {"entity_id": "D3", "entity_type": "Drug", "canonical_name": "meropenem"}],
        "p2": [{"entity_id": "D2", "entity_type": "Drug", "canonical_name": "amikacin"},
               {"entity_id": "D2", "entity_type": "Drug", "canonical_name": "amikacin"},
               {"entity_id": "D1", "entity_type": "Drug", "canonical_name": "colistin"}],
    }
    out = fusion.text_baseline_answers([hit("p1", 1), hit("p2", 2)], "alternatives", exclude_ids=["D3"], mentions=mentions)
    assert [a.id for a in out] == ["D1", "D2"]  # no mechanism, no excluded drug
    assert out[0].score == pytest.approx(1 / 61 + 1 / 62)
    assert out[1].score == pytest.approx(1 / 62)  # counted once per passage
    mech = fusion.text_baseline_answers([hit("p1")], "mechanism_lookup", mentions=mentions)
    assert [a.id for a in mech] == ["M1"]
    assert fusion.text_baseline_answers([hit("p1")], "unknown", mentions=mentions) == []


def test_d39_split_and_active_threshold():
    a = [drug("1", "rec-first", 1.0, ["R1"]), drug("2", "active-only", 0.5),
         drug("3", "rescued", 0.25, ["R2"]), drug("4", "excluded", 0.1)]
    rec, other = fusion.split_recommended(a)
    assert [x.name for x in rec] == ["rec-first", "rescued"]
    assert [x.name for x in other] == ["active-only"]  # excluded and unrecommended is dropped


def test_rerank_recommended_first_then_support_and_keeps_group_order():
    a = [drug("1", "no-rec", 0.5, group="NDM"), drug("2", "few", 1.0, ["R"], group="NDM"),
         drug("3", "many", 1.0, ["R"], group="NDM"), drug("4", "kpc-no-rec", 0.5, group="KPC"),
         drug("5", "rescued", 0.25, ["R"], group="NDM")]
    out = fusion.rerank_graph_answers(a, {"3": 5, "2": 1, "5": 9}, use_support=True)
    assert [x.name for x in out] == ["many", "few", "rescued", "no-rec", "kpc-no-rec"]
    plain = fusion.rerank_graph_answers(a, {"3": 5}, use_support=False)
    assert [x.name for x in plain][:3] == ["few", "many", "rescued"]  # graph order kept


def test_support_count_uses_answer_and_recommendation_links():
    links = {"D": {"p1": 2, "p9": 1}, "REC": {"p2": 1, "p1": 1}}
    a = Answer(id="D", recommendation_ids=["REC"])
    assert fusion.support_count(a, links, ["p1", "p2", "p3"]) == 2


# ---------------------------------------------------------------------------
# Stubbed answer() behaviour (no database)
# ---------------------------------------------------------------------------


@pytest.fixture
def stub(monkeypatch):
    """Parser, graph search and text search replaced by fixed results."""
    state = {"calls": [], "graph": None}
    parsed = ParsedQuery(question="q", intent="alternatives", pathogen_ids=["NCBITaxon:573"], class_families=["carbapenem"])
    monkeypatch.setattr(ans, "parse", lambda q: state.get("parsed", parsed))

    def fake_search(q, mode, k=10, entity_ids=None):
        state["calls"].append(("search", mode))
        return [hit(f"{mode}:{i}", i) for i in range(1, k + 1)]

    def fake_pfe(ids, k):
        state["calls"].append(("pfe", tuple(ids)))
        return [hit(f"graph:{i}", i, 2.0) for i in range(1, k + 1)]

    def fake_graph(p):
        state["calls"].append(("graph",))
        return state["graph"]

    monkeypatch.setattr(ans.text_search, "search", fake_search)
    monkeypatch.setattr(ans.text_search, "passages_for_entities", fake_pfe)
    monkeypatch.setattr(ans, "_graph_search", fake_graph)
    rec = "REC:icmr-cr-gram-negative-2022:002"
    answers = [drug("D1", "amikacin", 0.5, group="NDM"), drug("D2", "colistin", 1.0, [rec], group="NDM"),
               drug("D3", "meropenem", 0.25, [rec], group="NDM"), drug("D4", "levofloxacin", 0.5, group="NDM")]
    answers[1].caveats = [f"{rec}: Only as the base of a combination: colistin plus one other active agent."]
    paths = [Path(steps=[{"node_id": "x", "node_name": "K. pneumoniae", "rel_type": None, "rel_props": {}}], answer_id="D2")]
    state["graph"] = GraphResult(answers=answers, paths=paths, entity_ids=["NCBITaxon:573", "D2", rec])
    return state


def test_stub_graph_mode_d39_split_and_text(stub):
    r = ans.answer("q", "graph", k=3)
    check_shape(r, "graph")
    assert [a["name"] for a in r["answers"]] == ["colistin", "meropenem"]  # recommended only, in graph order
    assert all(a["recommended"] for a in r["answers"])
    assert [a["name"] for a in r["other_active"]] == ["amikacin", "levofloxacin"]
    t = r["answer_text"]
    assert "Recommended by the guidelines in scope: colistin" in t
    assert "Not excluded by the resistance data, but not recommended by the guidelines in scope: amikacin, levofloxacin" in t
    assert t.index("colistin") < t.index("amikacin")
    assert "Only as the base of a combination" in t and "REC:" not in t
    assert "Guidance on Diagnosis and Management of Carbapenem Resistant Gram-negative Infections (2022)" in t
    assert [p["passage_id"] for p in r["passages"]] == ["graph:1", "graph:2", "graph:3"]
    assert r["paths"] and r["paths"][0]["answer_id"] == "D2"
    assert ("search", "bm25") not in stub["calls"]  # graph mode uses no text ranking


def test_stub_hybrid_reranks_by_support_and_fuses_three_lists(stub, monkeypatch):
    monkeypatch.setattr(ans.fusion, "support_count", lambda a, links, ids: {"D3": 9, "D2": 1}.get(a.id, 0))
    r = ans.answer("q", "hybrid", k=5)
    check_shape(r, "hybrid")
    # active colistin stays ahead of rescued meropenem even though meropenem has more support
    assert [a["name"] for a in r["answers"]] == ["colistin", "meropenem"]
    assert len(r["passages"]) == 5
    ids = {p["passage_id"] for p in r["passages"]}
    assert ids >= {"bm25:1", "dense:1", "graph:1"}  # all three lists contribute at the top
    assert r["passages"][0]["score"] == pytest.approx(1 / 61)
    assert ("search", "bm25") in stub["calls"] and ("search", "dense") in stub["calls"]
    assert any(c[0] == "pfe" for c in stub["calls"])


def test_stub_hybrid_orders_recommended_drugs_by_supporting_passages(stub, monkeypatch):
    rec = "REC:icmr-cr-gram-negative-2022:002"
    stub["graph"].answers = [drug("D1", "few", 1.0, [rec], group="NDM"), drug("D2", "many", 1.0, [rec], group="NDM"),
                             drug("D3", "plain", 0.5, group="NDM")]
    monkeypatch.setattr(ans.fusion, "support_count", lambda a, links, ids: {"D1": 1, "D2": 7, "D3": 99}.get(a.id, 0))
    assert [a["name"] for a in ans.answer("q", "hybrid")["answers"]] == ["many", "few"]
    assert [a["name"] for a in ans.answer("q", "graph")["answers"]] == ["few", "many"]  # graph keeps its order


@pytest.mark.parametrize("mode", ["bm25", "dense", "bm25_dense"])
def test_stub_text_modes_do_not_touch_the_graph(stub, mode, monkeypatch):
    monkeypatch.setattr(ans.fusion, "text_baseline_answers",
                        lambda hits, intent, exclude, **kw: [Answer(id="D9", label="Drug", name="polymyxin B", score=0.03)])
    r = ans.answer("q", mode, k=4)
    check_shape(r, mode)
    assert ("graph",) not in stub["calls"] and ("search", mode) in stub["calls"]
    assert r["paths"] == [] and r["other_active"] == []
    assert [a["name"] for a in r["answers"]] == ["polymyxin B"]
    assert "not checked against the guideline" in r["answer_text"]
    assert len(r["passages"]) == 4


def test_stub_decline_runs_no_retrieval(stub):
    stub["parsed"] = ParsedQuery(question="dose?", intent="decline", decline_reason="It asks for a dose.")
    for mode in ans.MODES:
        r = ans.answer("dose?", mode)
        check_shape(r, mode)
        assert r["declined"] and r["decline_reason"] == "It asks for a dose."
        assert "It asks for a dose." in r["answer_text"]
        assert r["answers"] == [] and r["passages"] == []
    assert stub["calls"] == []


def test_stub_unknown_uses_text_retrieval_only_even_in_graph_modes(stub):
    stub["parsed"] = ParsedQuery(question="cza for crkp", intent="unknown")
    for mode in ans.MODES:
        r = ans.answer("cza for crkp", mode, k=3)
        check_shape(r, mode)
        assert not r["declined"] and r["answers"] == [] and len(r["passages"]) == 3
        assert "not understood" in r["answer_text"]
    assert ("graph",) not in stub["calls"]


def test_stub_empty_graph_says_so_and_hybrid_falls_back_to_passages(stub, monkeypatch):
    stub["graph"] = GraphResult(empty_reason="The question names no resistance.")
    g = ans.answer("q", "graph")
    assert g["answers"] == [] and "no facts" in g["answer_text"] and "names no resistance" in g["answer_text"]
    monkeypatch.setattr(ans.fusion, "text_baseline_answers",
                        lambda hits, intent, exclude, **kw: [Answer(id="D9", label="Drug", name="polymyxin B", score=0.03)])
    h = ans.answer("q", "hybrid")
    assert [a["name"] for a in h["answers"]] == ["polymyxin B"] and h["note"]
    assert "come from the passages" in h["answer_text"]


def test_bad_mode_raises():
    with pytest.raises(ValueError):
        ans.answer("q", "magic")


# ---------------------------------------------------------------------------
# Real text index (no database): the baselines and unknown / decline
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["bm25", "dense", "bm25_dense"])
def test_text_modes_return_drug_candidates_for_the_original_question(mode):
    r = ans.answer(Q_ALT, mode, k=10)
    check_shape(r, mode)
    assert r["intent"] == "alternatives"
    assert r["entities"]["pathogens"] == ["NCBITaxon:573"]
    assert len(r["passages"]) <= 10 and r["passages"]
    assert r["answers"], "text baseline should find drugs in the top passages"
    assert all(a["label"] == "Drug" for a in r["answers"])
    assert r["paths"] == []


@pytest.mark.parametrize("intent", list(INTENT_QUESTIONS))
def test_text_baseline_for_every_intent(intent):
    r = ans.answer(INTENT_QUESTIONS[intent], "bm25", k=10)
    check_shape(r, "bm25")
    assert r["intent"] == intent
    wanted = {"alternatives": {"Drug"}, "recommendation_lookup": {"Drug"}, "why_restricted": {"Mechanism"},
              "mechanism_lookup": {"Mechanism"}, "drug_profile": {"DrugClass"}, "surveillance": {"Drug"}}[intent]
    assert {a["label"] for a in r["answers"]} <= wanted


def test_real_decline_and_unknown_questions():
    d = ans.answer("What is the dose of colistin for CRAB?", "hybrid")
    check_shape(d, "hybrid")
    assert d["intent"] == "decline" and d["declined"] and d["decline_reason"]
    assert d["passages"] == [] and d["answers"] == []
    u = ans.answer("cza for crkp", "hybrid", k=5)
    check_shape(u, "hybrid")
    assert u["intent"] == "unknown" and u["answers"] == [] and len(u["passages"]) == 5
    assert "not understood" in u["answer_text"]


def test_cli_text_mode(capsys):
    assert ans.main([Q_ALT, "--mode", "bm25", "-k", "10"]) == 0
    out = capsys.readouterr().out
    assert "Mode: bm25" in out and "Top answers:" in out and "Top passages:" in out and "not medical advice" in out
    assert ans.main(["What is the dose of colistin for CRAB?"]) == 0
    assert "declined" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Live graph (skipped without Neo4j)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["graph", "hybrid"])
def test_live_alternatives_d39_split_and_groups(neo4j, mode):
    r = ans.answer(Q_ALT, mode, k=10)
    check_shape(r, mode)
    assert r["intent"] == "alternatives"
    assert r["answers"] and r["other_active"]
    assert all(a["recommended"] and a["recommendation_ids"] for a in r["answers"])
    assert all(not a["recommendation_ids"] for a in r["other_active"])
    groups = {a["group"] for a in r["answers"]}
    assert {"KPC beta-lactamase", "NDM beta-lactamase", "OXA-48-like beta-lactamase"} <= groups
    for para in r["answer_text"].split("\n\n"):  # D39: recommended before not-excluded, in every paragraph
        if "Not excluded by the resistance data" in para:
            assert para.index("Recommended by the guidelines") < para.index("Not excluded by the resistance data")
    names = {a["name"] for a in r["answers"] if a["group"] == "KPC beta-lactamase"}
    assert "ceftazidime-avibactam" in names and "nitrofurantoin" not in names
    assert "nitrofurantoin" in {a["name"] for a in r["other_active"]}
    assert "(2022)" in r["answer_text"] and "(2019)" in r["answer_text"]
    assert r["paths"] and r["paths"][0]["steps"]
    assert len(r["passages"]) == 10


def test_live_hybrid_passages_come_from_three_lists(neo4j):
    r = ans.answer(Q_ALT, "hybrid", k=10)
    scores = [p["score"] for p in r["passages"]]
    assert scores == sorted(scores, reverse=True) and scores[0] <= 3 / 61 + 1e-9
    assert [p["rank"] for p in r["passages"]] == list(range(1, 11))


@pytest.mark.parametrize("mode", ["graph", "hybrid"])
@pytest.mark.parametrize("intent", [i for i in INTENT_QUESTIONS if i != "alternatives"])
def test_live_every_intent_in_graph_modes(neo4j, mode, intent):
    r = ans.answer(INTENT_QUESTIONS[intent], mode, k=5)
    check_shape(r, mode)
    assert r["intent"] == intent
    assert r["answers"], f"no graph answers for {intent}"
    assert r["other_active"] == []
    assert r["answer_text"].count("\n\n") >= 2  # body, guidelines, disclaimer
    assert r["paths"]


def test_live_recommendation_lookup_mrsa_has_vancomycin(neo4j):
    r = ans.answer(INTENT_QUESTIONS["recommendation_lookup"], "hybrid")
    assert {"vancomycin", "teicoplanin"} <= {a["name"] for a in r["answers"]}
    assert "vancomycin" in r["answer_text"]

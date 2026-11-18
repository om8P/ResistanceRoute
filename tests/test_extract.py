"""Tests for pipeline/extract.py and eval/extraction_eval.py (T13)."""

from __future__ import annotations

import json

import pytest

from eval import extraction_eval as ev
from pipeline import extract as ex
from pipeline.models import RecommendationExtraction

KPN, ECO, ABA, SAU = "NCBITaxon:573", "NCBITaxon:562", "NCBITaxon:470", "NCBITaxon:1280"


@pytest.fixture(scope="module")
def extractor() -> ex.Extractor:
    return ex.Extractor()


def passage(text: str, pid: str = "icmr-cr-gram-negative-2022:test:1", page: int | None = 5, heading: str = "", doc: str | None = None) -> dict:
    return {
        "id": pid,
        "text": text,
        "source_doc": doc or pid.split(":")[0],
        "section": "test",
        "page": page,
        "heading": heading,
        "is_table": False,
    }


def ids(extractor: ex.Extractor, rec: RecommendationExtraction) -> dict:
    return extractor.resolve_ids(rec)


# ----------------------------------------------------------------------------- trigger rules


def test_first_choice_sentence(extractor):
    recs = extractor.extract_passage(
        passage("Colistin is the first choice for carbapenem-resistant Acinetobacter baumannii infections.")
    )
    assert len(recs) == 1
    r = ids(extractor, recs[0])
    assert r["pathogen_id"] == ABA
    assert r["drug_ids"] == ["J01XB01"]
    assert r["line_of_therapy"] == "first"
    assert recs[0].method.value == "rule"
    assert recs[0].passage_id == "icmr-cr-gram-negative-2022:test:1"
    assert 0 < recs[0].confidence <= 1


@pytest.mark.parametrize(
    "text, line",
    [
        ("Vancomycin is reserved for Staphylococcus aureus infections when no other option exists.", "last-resort"),
        ("Linezolid is an alternative for Staphylococcus aureus infection.", "alternative"),
        ("Cefazolin is the second-line agent for Escherichia coli bacteraemia.", "second"),
        ("Meropenem is preferred for Klebsiella pneumoniae sepsis.", "first"),
    ],
)
def test_trigger_to_line_of_therapy(extractor, text, line):
    recs = extractor.extract_passage(passage(text))
    assert recs and all(r.line_of_therapy.value == line for r in recs)


def test_no_drug_no_extraction(extractor):
    assert extractor.extract_passage(passage("Surgery is recommended for Klebsiella pneumoniae abscess.")) == []


def test_no_pathogen_no_extraction(extractor):
    assert extractor.extract_passage(passage("Meropenem is the first choice for severe sepsis.")) == []


def test_negated_sentence_is_skipped(extractor):
    text = "Tigecycline is not recommended for Klebsiella pneumoniae bloodstream infection."
    assert extractor.extract_passage(passage(text)) == []


def test_resistance_statement_is_not_a_recommendation_drug(extractor):
    text = "Colistin is preferred for Klebsiella pneumoniae resistant to meropenem."
    r = ids(extractor, extractor.extract_passage(passage(text))[0])
    assert r["drug_ids"] == ["J01XB01"]


def test_pathogen_carried_from_heading_has_lower_confidence(extractor):
    own = extractor.extract_passage(passage("Meropenem is preferred for Klebsiella pneumoniae sepsis."))[0]
    carried = extractor.extract_passage(
        passage("Meropenem is preferred in this setting.", heading="3.2 Klebsiella pneumoniae")
    )[0]
    assert ids(extractor, carried)["pathogen_id"] == KPN
    assert carried.confidence < own.confidence


def test_class_expansion(extractor):
    rec = extractor.extract_passage(passage("Aminoglycosides are an alternative for Escherichia coli UTI."))[0]
    assert set(ids(extractor, rec)["drug_ids"]) == {"J01GB03", "J01GB06", "J01GB01", "J01GB14"}


def test_enterobacterales_stands_for_in_scope_species(extractor):
    recs = extractor.extract_passage(passage("Meropenem is preferred for infection by Enterobacterales."))
    assert {ids(extractor, r)["pathogen_id"] for r in recs} == {KPN, ECO}


def test_phenotype_mechanism_binds_to_its_own_pathogen(extractor):
    recs = extractor.extract_passage(passage("Vancomycin is recommended for MRSA bacteraemia."))
    assert len(recs) == 1
    r = ids(extractor, recs[0])
    assert r["pathogen_id"] == SAU and r["mechanism_ids"] == ["ARO:3009312"]


def test_mechanism_not_known_for_pathogen_is_dropped(extractor):
    recs = extractor.extract_passage(passage("Linezolid is an alternative for Staphylococcus aureus with NDM."))
    assert recs and all(ids(extractor, r)["mechanism_ids"] == [] for r in recs)


def test_long_table_fragment_is_left_to_the_segment_rule(extractor):
    text = "Preferred is meropenem for Klebsiella pneumoniae " + "filler " * 80
    assert extractor.trigger(passage(text)) == []


def test_choice_blocks_are_split(extractor):
    text = (
        "Antibiotics for Staphylococcus aureus. First Choice Cloxacillin 2 g q6h IV "
        "Second Choice Cefazolin 2 g q8h IV ---- OR ---- Vancomycin 15 mg/kg q12h IV"
    )
    recs = extractor.extract_passage(passage(text))
    by_line = {r.line_of_therapy.value: set(ids(extractor, r)["drug_ids"]) for r in recs}
    assert by_line["first"] == {"J01CF02"}
    assert by_line["second"] == {"J01DB04", "J01XA01"}


# ----------------------------------------------------------------------------- table 4 and segments

TABLE4_TEXT = (
    "Table 4: Available treatment options for carbapenem resistant Enterobacterales in India. "
    "Carbapenemase Metallo-β-lactamase (eg. NDM) + OXA-48: 1st choice: Prolonged infusion of "
    "ceftazidime-avibactam and aztreonam (over 3 hours)*; other options: a. Polymyxins plus other "
    "agent (like tigecycline, aminoglycosides) b. Tigecycline (approved for intra-abdominal infection)."
)


def test_table4_row(extractor):
    recs = extractor.extract_passage(passage(TABLE4_TEXT, page=16))
    first = [r for r in recs if r.line_of_therapy.value == "first"]
    assert {ids(extractor, r)["pathogen_id"] for r in first} == {KPN, ECO}
    r = ids(extractor, first[0])
    assert r["drug_ids"] == ["J01DD52", "J01DF01"]
    assert r["mechanism_ids"] == ["ARO:3000057", "ARO:3007721"]  # co-producers stay together
    assert first[0].confidence == 0.95
    alternatives = [r for r in recs if r.line_of_therapy.value == "alternative"]
    assert len(alternatives) == 4  # two options x two pathogens
    assert any(ids(extractor, r)["drug_ids"] == ["J01AA12"] for r in alternatives)


def test_segment_rule_cuts_at_pathogen_mentions(extractor):
    text = "Etiology Suggested regimens Preferred Alternative E. coli Meropenem Colistin Acinetobacter spp Colistin"
    recs = extractor.segment(passage(text, doc="icmr-treatment-guidelines-2019", pid="icmr-treatment-guidelines-2019:t:1"))
    got = {ids(extractor, r)["pathogen_id"]: set(ids(extractor, r)["drug_ids"]) for r in recs}
    assert got == {ECO: {"J01DH02", "J01XB01"}, ABA: {"J01XB01"}}
    assert all(r.line_of_therapy is None and r.confidence == 0.3 for r in recs)


# ----------------------------------------------------------------------------- driver


def test_extract_all_skips_abstracts_and_merges_overlap(extractor):
    text = "Meropenem is preferred for Klebsiella pneumoniae sepsis."
    passages = [
        passage(text, pid="icmr-cr-gram-negative-2022:s:1", page=5),
        passage(text, pid="icmr-cr-gram-negative-2022:s:2", page=6),  # overlap copy on the next page
        passage(text, pid="icmr-cr-gram-negative-2022:s:3", page=20),  # same text far away: kept
        passage(text, pid="pubmed-1:abstract:1", page=None, doc="pubmed-1"),
    ]
    recs = extractor.extract_all(passages)
    assert [r.passage_id for r in recs] == ["icmr-cr-gram-negative-2022:s:1", "icmr-cr-gram-negative-2022:s:3"]


def test_jsonl_round_trip(extractor, tmp_path):
    recs = extractor.extract_passage(passage("Meropenem is preferred for Klebsiella pneumoniae sepsis."))
    path = tmp_path / "out.jsonl"
    assert ex.write_jsonl(recs, path) == len(recs)
    back = [RecommendationExtraction(**json.loads(line)) for line in path.read_text(encoding="utf8").splitlines()]
    assert back == recs


def test_resolve_ids_round_trips_canonical_names(extractor):
    rec = extractor.extract_passage(passage(TABLE4_TEXT, page=16))[0]
    r = ids(extractor, rec)
    assert r["pathogen_id"] in {KPN, ECO}
    assert None not in r["drug_ids"] and r["drug_ids"]


def test_real_output_file_is_valid_if_present():
    if not ex.OUT_PATH.exists() or not ex.PASSAGES_PATH.exists():
        pytest.skip("run python -m pipeline.extract first")
    known = {p["id"]: p for p in ex.load_passages()}
    lines = [json.loads(line) for line in ex.OUT_PATH.read_text(encoding="utf8").splitlines() if line.strip()]
    assert lines
    for row in lines:
        rec = RecommendationExtraction(**row)
        assert rec.method.value == "rule" and rec.passage_id in known
        assert not known[rec.passage_id]["source_doc"].startswith("pubmed-")


# ----------------------------------------------------------------------------- evaluation


def g(i, pathogen=KPN, mech=(), drugs=("A",), page=10, guideline="gl", line="first"):
    return {
        "id": i, "guideline": guideline, "pathogen": pathogen, "mechanism": frozenset(mech),
        "drugs": frozenset(drugs), "line_of_therapy": line, "page": page, "text": "",
    }


def p(i, conf=0.5, **kw):
    row = g(i, **kw)
    row.update(confidence=conf, passage_id="x:y:1", evidence="e")
    return row


def test_strict_match_needs_all_fields_and_page_within_one():
    gold = g("G1", mech=("M",), drugs=("A", "B"), page=10)
    assert ev.MATCHERS["strict"](p("P1", mech=("M",), drugs=("A", "B"), page=11), gold)
    for bad in (
        p("P", mech=("M",), drugs=("A", "B"), page=12),
        p("P", mech=(), drugs=("A", "B"), page=10),
        p("P", pathogen=ECO, mech=("M",), drugs=("A", "B")),
        p("P", mech=("M",), drugs=("A",)),
        p("P", mech=("M",), drugs=("A", "B"), guideline="other"),
    ):
        assert not ev.MATCHERS["strict"](bad, gold)


def test_lenient_allows_partial_drug_overlap():
    assert ev.MATCHERS["lenient"](p("P", drugs=("A", "B")), g("G", drugs=("A", "B", "C")))
    assert not ev.MATCHERS["lenient"](p("P", drugs=("A",)), g("G", drugs=("A", "B", "C")))


def test_matching_is_one_to_one_and_scores_use_set_prf():
    gold = [g("G1")]
    preds = [p("P1", conf=0.9), p("P2", conf=0.4)]  # duplicates: one TP, one FP
    s = ev.score(preds, gold, ev.MATCHERS["strict"])
    assert s["true_positives"] == 1
    assert s["precision"] == 0.5 and s["recall"] == 1.0 and s["f1"] == pytest.approx(0.6667, abs=1e-3)


def test_empty_predictions_score_zero():
    s = ev.score([], [g("G1")], ev.MATCHERS["strict"])
    assert s["precision"] == 0 and s["recall"] == 0 and s["f1"] == 0


def test_error_causes_describe_the_extraction():
    gold = [g("G1", drugs=("A", "B"))]
    assert ev.fp_cause(p("P", drugs=("A",)), gold) == "drug set too small (a drug is missing)"
    assert ev.fp_cause(p("P", drugs=("A", "B", "C")), gold) == "drug set too large (extra drug)"
    assert ev.fn_cause(gold[0], [p("P", drugs=("A", "B", "C"))]) == "drug set too large (extra drug)"
    assert ev.fn_cause(gold[0], [p("P", drugs=("A",))]) == "drug set too small (a drug is missing)"
    assert ev.fn_cause(gold[0], [p("P", page=50)]) == "nothing extracted on this page"
    assert ev.fn_cause(gold[0], [p("P", pathogen=ECO, drugs=("A", "B"))]) == "pathogen not found or wrong"
    assert ev.fn_cause(gold[0], [p("P", mech=("M",), drugs=("A", "B"))]) == "mechanism missing or wrong"


def test_pick_covers_causes_round_robin():
    items = [{"cause": "a", "n": i} for i in range(8)] + [{"cause": "b", "n": 0}, {"cause": "c", "n": 0}]
    chosen = ev.pick(items, 4)
    assert {c["cause"] for c in chosen} == {"a", "b", "c"} and len(chosen) == 4


def test_gold_loads_80_rows():
    gold = ev.load_gold()
    assert len(gold) == 80
    assert all(r["page"] > 0 and r["drugs"] and r["pathogen"] for r in gold)


def test_result_file_structure_if_present():
    if not ev.RESULT_PATH.exists():
        pytest.skip("run python -m eval.extraction_eval first")
    res = json.loads(ev.RESULT_PATH.read_text(encoding="utf8"))
    assert res["dev_set"] == ev.DEV_SET
    assert set(res["per_guideline"]) == {
        "icmr-cr-gram-negative-2022", "icmr-treatment-guidelines-2019", "who-aware-book-2022"
    }
    for block in [res["overall"], *res["per_guideline"].values()]:
        assert set(block["fields"]) == set(ev.FIELDS)
        for s in (block["strict"], block["lenient"], *block["fields"].values()):
            assert 0 <= s["precision"] <= 1 and 0 <= s["recall"] <= 1 and 0 <= s["f1"] <= 1
    assert len(res["error_analysis"]["false_positive_sample"]) == 10
    assert len(res["error_analysis"]["false_negative_sample"]) == 10

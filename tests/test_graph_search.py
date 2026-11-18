"""Tests for retrieval/graph_search.py (T10).

Database tests read the shared Neo4j graph and never write to it; they are
skipped when Neo4j is unreachable. Expected drug sets come from
data/curated/REVIEW_NOTES.md section 3.
"""

from __future__ import annotations

import re

import pytest

from retrieval import graph_search as gs
from retrieval.graph_search import graph_search
from retrieval.types import GraphResult, ParsedQuery

KP, EC, SA = "NCBITaxon:573", "NCBITaxon:562", "NCBITaxon:1280"
KPC, NDM, OXA48, VIM, CTXM, MECA = (
    "ARO:3000059", "ARO:3000057", "ARO:3007721", "ARO:3000021", "ARO:3000016", "ARO:3009312")
BETA_LACTAM_FAMILIES = {"penicillin", "cephalosporin", "carbapenem", "monobactam", "beta-lactam-bli"}

EXPECTED_BETA_LACTAMS = {  # REVIEW_NOTES section 3
    KPC: {"ceftazidime-avibactam", "meropenem-vaborbactam", "imipenem-cilastatin-relebactam",
          "cefiderocol", "aztreonam-avibactam"},
    NDM: {"aztreonam", "aztreonam-avibactam", "cefiderocol"},
    OXA48: {"ceftazidime-avibactam", "cefiderocol", "aztreonam-avibactam", "aztreonam", "cefazolin",
            "cefuroxime", "ceftriaxone", "cefotaxime", "ceftazidime", "cefepime", "ceftaroline fosamil"},
}
NON_BETA_LACTAMS = {"gentamicin", "amikacin", "tobramycin", "plazomicin", "ciprofloxacin", "levofloxacin",
                    "moxifloxacin", "colistin", "polymyxin B", "doxycycline", "minocycline", "eravacycline",
                    "tigecycline", "fosfomycin", "sulfamethoxazole-trimethoprim", "nitrofurantoin"}


# ---------------------------------------------------------------------------
# Without the database
# ---------------------------------------------------------------------------


def test_every_template_loads_and_uses_parameters_only():
    names = sorted(p.stem for p in gs.CYPHER_DIR.glob("*.cypher"))
    for intent in ("alternatives", "recommendations", "why_restricted", "mechanism_lookup",
                   "drug_profile", "surveillance", "mechanisms", "class_families"):
        assert intent in names
    for name in names:
        text = gs.load_template(name)
        assert text and not text.startswith("//")
        # IDs are never written into the template text; only $parameters
        assert not re.search(r"(ARO:|NCBITaxon:|J01[A-Z]{2}\d\d|REC:)", text), name
        assert not re.search(r"\b(CREATE|MERGE|DELETE|SET|REMOVE)\b", text), name


def test_d34_caveats_available_for_the_11_conflict_rows():
    # from the `caveat` column (D40), or the RECOMMENDATION_NOTES table while it is missing
    ids = [f"REC:icmr-cr-gram-negative-2022:{n:03d}" for n in (1, 2, 6, 10, 13, 14, 15, 19, 23, 26)]
    ids.append("REC:who-aware-book-2022:006")
    assert all(gs.rec_caveat(i) for i in ids)
    assert "avibactam protects aztreonam" in gs.rec_caveat("REC:icmr-cr-gram-negative-2022:001")
    assert "MIC is low" in gs.rec_caveat("REC:icmr-cr-gram-negative-2022:010")
    assert gs.rec_caveat("REC:icmr-cr-gram-negative-2022:009") is None


def test_curated_columns_are_read():
    meta = gs.rec_meta()
    assert meta["REC:icmr-cr-gram-negative-2022:002"]["base_drug_ids"] == ["J01XB01", "J01XB02"]
    assert meta["REC:icmr-cr-gram-negative-2022:001"]["base_drug_ids"] == []  # fixed pair
    assert meta["REC:who-aware-book-2022:020"]["susceptible_only"] is True
    assert meta["REC:icmr-cr-gram-negative-2022:001"]["susceptible_only"] is False
    assert sum(1 for v in meta.values() if v["caveat"]) == 11


def test_decline_and_unknown_intents_need_no_database():
    r = graph_search(ParsedQuery(intent="decline", decline_reason="dose question"))
    assert isinstance(r, GraphResult) and r.answers == [] and r.empty_reason == "dose question"
    r = graph_search(ParsedQuery(intent="unknown"))
    assert r.answers == [] and "text search" in r.empty_reason


# ---------------------------------------------------------------------------
# Against the shared graph (read-only)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def driver():
    from pipeline.graph_db import get_driver, ping

    drv = get_driver(connection_timeout=2.0)
    if not ping(drv):
        drv.close()
        pytest.skip("Neo4j is not reachable")
    with drv.session() as s:
        if s.run("MATCH (r:Recommendation) RETURN count(r) AS n").single()["n"] == 0:
            drv.close()
            pytest.skip("Graph has no recommendations loaded")
    yield drv
    drv.close()


@pytest.fixture(scope="module")
def families(driver):
    with driver.session() as s:
        return {r["id"]: r["f"] for r in s.run("MATCH (d:Drug)-[:IN_CLASS]->(c) RETURN d.id AS id, c.family AS f")}


def run(driver, **kw) -> GraphResult:
    return graph_search(ParsedQuery(**kw), driver=driver)


def active(answers):
    return [a for a in answers if a.score >= gs.ACTIVE_SCORE]


def by_group(result):
    out = {}
    for a in result.answers:
        out.setdefault(a.group, []).append(a)
    return out


def find(answers, name):
    hits = [a for a in answers if a.name == name]
    assert hits, f"{name} not in answers"
    return hits[0]


@pytest.mark.parametrize("mech", [KPC, NDM, OXA48])
def test_three_mechanisms_give_review_notes_drug_sets(driver, families, mech):
    r = run(driver, intent="alternatives", pathogen_ids=[KP], mechanism_ids=[mech], class_families=["carbapenem"])
    names = {a.name for a in active(r.answers)}
    beta = {a.name for a in active(r.answers) if families[a.id] in BETA_LACTAM_FAMILIES}
    assert beta == EXPECTED_BETA_LACTAMS[mech]
    assert names == beta | NON_BETA_LACTAMS


def test_the_three_sets_differ_as_d4_requires():
    sets = EXPECTED_BETA_LACTAMS
    assert sets[KPC] != sets[NDM] and sets[NDM] != sets[OXA48] and sets[OXA48] != sets[KPC]


def test_unknown_mechanism_returns_one_group_per_carbapenemase(driver, families):
    r = run(driver, intent="alternatives", pathogen_ids=[KP], class_families=["carbapenem"])
    groups = by_group(r)
    assert set(groups) == {"KPC beta-lactamase", "NDM beta-lactamase", "OXA-48-like beta-lactamase",
                           "VIM beta-lactamase"}
    for name, mech in (("KPC beta-lactamase", KPC), ("NDM beta-lactamase", NDM),
                       ("OXA-48-like beta-lactamase", OXA48)):
        beta = {a.name for a in active(groups[name]) if families[a.id] in BETA_LACTAM_FAMILIES}
        assert beta == EXPECTED_BETA_LACTAMS[mech]
    # the group paths show why each mechanism is in the answer
    group_paths = [p for p in r.paths if p.answer_id == NDM]
    assert any(s["rel_type"] == "CONFERS_RESISTANCE_TO" and s["node_id"] == "carbapenem"
               for p in group_paths for s in p.steps)


def test_ndm_returns_ceftazidime_avibactam_plus_aztreonam_with_caveat(driver):
    r = run(driver, intent="alternatives", pathogen_ids=[KP], mechanism_ids=[NDM])
    cza = find(r.answers, "ceftazidime-avibactam")
    atm = find(r.answers, "aztreonam")
    rec = "REC:icmr-cr-gram-negative-2022:001"
    assert rec in cza.recommendation_ids and rec in atm.recommendation_ids
    assert cza.score < gs.ACTIVE_SCORE  # excluded alone, kept by D34
    assert any(gs.rec_caveat(rec) in c for c in cza.caveats)
    assert any("inactivates ceftazidime-avibactam" in c for c in cza.caveats)
    assert any("Only together with aztreonam" in c for c in cza.caveats)
    assert atm.score >= gs.ACTIVE_SCORE
    assert any("Only together with ceftazidime-avibactam" in c for c in atm.caveats)
    assert any("Ask about NDM + CTX-M" in c for c in atm.caveats)  # REVIEW_NOTES 3, item 1
    # the exclusion edge is on a path, with its provenance
    excl = [s for p in r.paths if p.answer_id == cza.id for s in p.steps if s["rel_type"] == "INACTIVATES"]
    assert excl and excl[0]["rel_props"]["source_id"] == "curated-seed"


def test_oxa48_cephalosporins_carry_co_production_caveat(driver):
    r = run(driver, intent="alternatives", pathogen_ids=[KP], mechanism_ids=[OXA48])
    for name in ("cefepime", "ceftriaxone", "aztreonam"):
        assert any("OXA-48-like + CTX-M" in c for c in find(r.answers, name).caveats)
    for name in ("ceftazidime-avibactam", "cefiderocol"):
        assert not any("+ CTX-M" in c for c in find(r.answers, name).caveats)


def test_exclusions_are_the_union_over_mechanisms(driver, families):
    r = run(driver, intent="alternatives", pathogen_ids=[KP], mechanism_ids=[OXA48, CTXM])
    beta = {a.name for a in active(r.answers) if families[a.id] in BETA_LACTAM_FAMILIES}
    assert beta == {"ceftazidime-avibactam", "cefiderocol", "aztreonam-avibactam"}
    assert {a.group for a in r.answers} == {"OXA-48-like beta-lactamase + CTX-M beta-lactamase (ESBL)"}
    r = run(driver, intent="alternatives", pathogen_ids=[KP], mechanism_ids=[NDM, CTXM])
    assert "aztreonam" not in {a.name for a in active(r.answers)}


def test_family_expands_to_every_class_in_it(driver):
    r = run(driver, intent="drug_profile", class_families=["carbapenem"])
    assert {a.name for a in r.answers} == {"meropenem", "imipenem-cilastatin", "ertapenem"}
    assert {a.group for a in r.answers} == {"Carbapenems (antipseudomonal group 2)",
                                            "Carbapenems (non-antipseudomonal group 1)"}
    r = run(driver, intent="drug_profile", class_families=["cephalosporin"])
    names = {a.name for a in r.answers}
    assert {"cefiderocol", "ceftaroline fosamil", "cefazolin", "cefepime"} <= names
    assert "ceftazidime-avibactam" not in names  # beta-lactam-bli family (D29)


def test_family_in_alternatives_excludes_both_carbapenem_classes(driver):
    # E. coli with a mechanism that does not touch carbapenems: the reported
    # carbapenem family still removes meropenem and ertapenem (phenotype)
    r = run(driver, intent="alternatives", pathogen_ids=[EC], mechanism_ids=[CTXM], class_families=["carbapenem"])
    names = {a.name for a in active(r.answers)}
    assert not names & {"meropenem", "imipenem-cilastatin", "ertapenem"}
    assert {"meropenem-vaborbactam", "imipenem-cilastatin-relebactam"} <= names


def test_mechanism_free_base_plus_partner_row_keeps_active_partners_only(driver):
    r = run(driver, intent="alternatives", pathogen_ids=[KP], mechanism_ids=[KPC])
    rec = "REC:icmr-cr-gram-negative-2022:027"  # no mechanism, polymyxin + partner
    tige = find(r.answers, "tigecycline")
    colistin = find(r.answers, "colistin")
    assert rec in tige.recommendation_ids and rec in colistin.recommendation_ids
    assert any(c.startswith(rec) and "Only as a combination partner of colistin or polymyxin B" in c
               for c in tige.caveats)
    assert any(c.startswith(rec) and "Partners left out" in c and "meropenem" in c for c in colistin.caveats)
    meropenem = find(r.answers, "meropenem")  # only through the KPC-specific row (D34)
    assert meropenem.recommendation_ids == ["REC:icmr-cr-gram-negative-2022:010"]
    assert any("MIC is low" in c for c in meropenem.caveats)


def test_mechanism_free_fixed_pair_is_judged_as_a_unit(driver):
    # :029 (CZA + aztreonam, carbapenemase unknown) has no mechanism, so for NDM
    # it is dropped because ceftazidime-avibactam is excluded (D34)
    r = run(driver, intent="alternatives", pathogen_ids=[KP], mechanism_ids=[NDM])
    assert "REC:icmr-cr-gram-negative-2022:029" not in find(r.answers, "aztreonam").recommendation_ids
    # ... and kept for OXA-48-like, where both drugs are active
    r = run(driver, intent="alternatives", pathogen_ids=[KP], mechanism_ids=[OXA48])
    assert "REC:icmr-cr-gram-negative-2022:029" in find(r.answers, "aztreonam").recommendation_ids


def test_guideline_listed_alternatives_for_crkp(driver):
    """D39: 'If carbapenem resistance is reported for Klebsiella, which guideline-listed
    alternatives remain?' Recommended drugs are a small set per mechanism; drugs that are
    only not excluded have no recommendation IDs."""
    r = run(driver, intent="alternatives", pathogen_ids=[KP], class_families=["carbapenem"])
    groups = by_group(r)
    for name, answers in groups.items():
        recommended = [a for a in answers if a.recommendation_ids]
        unrecommended = [a for a in answers if not a.recommendation_ids]
        assert all(a.score == gs.ACTIVE_SCORE for a in unrecommended), name
        assert all(a.score != gs.ACTIVE_SCORE for a in recommended), name
        if name != "VIM beta-lactamase":  # no VIM row for K. pneumoniae
            assert 0 < len(recommended) <= 14 and len(recommended) < len(answers), name
        assert "nitrofurantoin" not in {a.name for a in recommended}
    kpc = {a.name: a for a in groups["KPC beta-lactamase"] if a.recommendation_ids}
    assert "ceftazidime-avibactam" in kpc and kpc["ceftazidime-avibactam"].score >= gs.ACTIVE_SCORE
    ndm = {a.name: a for a in groups["NDM beta-lactamase"] if a.recommendation_ids}
    pair = "REC:icmr-cr-gram-negative-2022:001"
    assert pair in ndm["ceftazidime-avibactam"].recommendation_ids
    assert pair in ndm["aztreonam"].recommendation_ids


def test_susceptible_only_rows_are_dropped_for_resistant_organisms(driver, monkeypatch):
    """D41: WHO :020 (ciprofloxacin, mild pyelonephritis) is susceptible_only."""
    rec = "REC:who-aware-book-2022:020"
    flagged = {k for k, v in gs.rec_meta().items() if v["susceptible_only"]}
    for q in (dict(mechanism_ids=[KPC]), dict(class_families=["carbapenem"])):
        r = run(driver, intent="alternatives", pathogen_ids=[EC], **q)
        assert not flagged & {x for a in r.answers for x in a.recommendation_ids}
        cipro = find(r.answers, "ciprofloxacin")
        assert cipro.recommendation_ids == [] and cipro.score == gs.ACTIVE_SCORE
    # a question that names no resistance still shows it
    r = run(driver, intent="recommendation_lookup", pathogen_ids=[EC])
    assert rec in find(r.answers, "ciprofloxacin").recommendation_ids
    # without the flag it would have been attached: the filter is what removes it
    meta = {k: dict(v, susceptible_only=False) for k, v in gs.rec_meta().items()}
    monkeypatch.setattr(gs, "rec_meta", lambda: meta)
    r = run(driver, intent="alternatives", pathogen_ids=[EC], mechanism_ids=[KPC])
    assert rec in find(r.answers, "ciprofloxacin").recommendation_ids


def test_mrsa_alternatives_are_anti_mrsa_agents(driver, families):
    r = run(driver, intent="alternatives", pathogen_ids=[SA], mechanism_ids=[MECA])
    names = {a.name for a in active(r.answers)}
    assert {"vancomycin", "teicoplanin", "linezolid", "daptomycin", "ceftaroline fosamil"} <= names
    beta = {a.name for a in active(r.answers) if families[a.id] in BETA_LACTAM_FAMILIES}
    assert beta == {"ceftaroline fosamil"}
    assert not names & {"colistin", "polymyxin B", "aztreonam"}  # intrinsic for S. aureus
    assert all(a.score >= gs.ACTIVE_SCORE for a in r.answers)  # no MRSA row names an excluded drug


def test_mrsa_bloodstream_recommendations(driver, families):
    r = run(driver, intent="recommendation_lookup", pathogen_ids=[SA], mechanism_ids=[MECA],
            infection_site="bloodstream infection")
    names = {a.name for a in r.answers}
    assert {"vancomycin", "teicoplanin", "daptomycin"} <= names
    assert not any(families[a.id] in BETA_LACTAM_FAMILIES and a.name != "ceftaroline fosamil" for a in r.answers)
    assert all(a.recommendation_ids for a in r.answers)
    rec_ids = {x for a in r.answers for x in a.recommendation_ids}
    assert "REC:icmr-treatment-guidelines-2019:001" in rec_ids  # CLABSI
    assert "REC:icmr-treatment-guidelines-2019:014" not in rec_ids  # HAP/VAP
    assert all(0 < a.score <= 1.0 for a in r.answers)


def test_recommendation_lookup_unknown_mechanism_groups(driver):
    r = run(driver, intent="recommendation_lookup", pathogen_ids=[KP], class_families=["carbapenem"])
    groups = by_group(r)
    assert "REC:icmr-cr-gram-negative-2022:009" in find(groups["KPC beta-lactamase"],
                                                         "ceftazidime-avibactam").recommendation_ids
    assert "cefiderocol" in {a.name for a in groups["NDM beta-lactamase"]}
    assert all(a.recommendation_ids for a in r.answers)


def test_why_restricted_colistin(driver):
    r = run(driver, intent="why_restricted", drug_ids=["J01XB01"])
    main = r.answers[0]
    assert main.id == "J01XB01" and main.aware_group == "Reserve"
    assert "ARO:3004268" in {a.id for a in r.answers if a.label == "Mechanism"}  # MCR
    last = [a for a in r.answers if a.group == "Kept as last resort"]
    assert last and all(a.id.startswith("REC:") for a in last)
    assert any(a.label == "Passage" for a in r.answers)


def test_mechanism_lookup_e_coli_cephalosporins(driver):
    r = run(driver, intent="mechanism_lookup", pathogen_ids=[EC], class_families=["cephalosporin"])
    ids = {a.id for a in r.answers}
    assert {CTXM, "ARO:3000069"} <= ids  # CTX-M and CMY
    assert "ARO:3004268" not in ids  # MCR does not act on cephalosporins


def test_surveillance_carbapenem_klebsiella_india(driver):
    r = run(driver, intent="surveillance", pathogen_ids=[KP], class_families=["carbapenem"], country="IND")
    assert r.answers and all(a.label == "SurveillanceStat" and ":IND:" in a.id for a in r.answers)
    assert "GLASS:IND:2018:NCBITaxon:573:J01DH02" not in {a.id for a in r.answers}  # latest year only
    r = run(driver, intent="surveillance", pathogen_ids=[KP], class_families=["carbapenem"],
            country="IND", year=2018)
    stat = next(a for a in r.answers if a.id == "GLASS:IND:2018:NCBITaxon:573:J01DH02")
    assert "55.2%" in stat.name


QUESTIONS = [
    dict(intent="alternatives", pathogen_ids=[KP], class_families=["carbapenem"]),
    dict(intent="alternatives", pathogen_ids=[SA], mechanism_ids=[MECA]),
    dict(intent="recommendation_lookup", pathogen_ids=[SA], mechanism_ids=[MECA], infection_site="bloodstream"),
    dict(intent="why_restricted", drug_ids=["J01XB01"]),
    dict(intent="mechanism_lookup", pathogen_ids=[EC], class_families=["cephalosporin"]),
    dict(intent="drug_profile", drug_ids=["J01DH02"]),
    dict(intent="surveillance", pathogen_ids=[KP], class_families=["carbapenem"], country="IND"),
]


@pytest.mark.parametrize("q", QUESTIONS, ids=[f"{q['intent']}-{i}" for i, q in enumerate(QUESTIONS)])
def test_every_answer_has_a_path_with_provenance(driver, q):
    r = run(driver, **q)
    assert r.answers and r.empty_reason is None and r.cypher
    question_ids = set(q.get("pathogen_ids", []) + q.get("drug_ids", []))
    path_ids = set()
    for p in r.paths:
        assert p.steps[0]["rel_type"] is None
        assert p.steps[0]["node_id"] in question_ids  # paths start at the question's entities
        for s in p.steps[1:]:
            assert s["rel_type"] and s["from_node_id"] in {x["node_id"] for x in p.steps}
            for key in gs.PROVENANCE_KEYS:
                assert key in s["rel_props"], (s["rel_type"], key)
            assert s["rel_props"]["method"] in {"curated", "rule", "llm", "derived"}
            if s["rel_props"]["method"] != "derived":
                assert s["rel_props"]["source_id"]
        path_ids.update(x["node_id"] for x in p.steps)
    for a in r.answers:
        assert any(p.answer_id == a.id for p in r.paths), a.name
    assert set(r.entity_ids) == path_ids


def test_curated_edges_on_paths_carry_evidence_sources(driver):
    r = run(driver, intent="alternatives", pathogen_ids=[KP], mechanism_ids=[NDM])
    has_mech = [s for p in r.paths for s in p.steps if s["rel_type"] == "HAS_MECHANISM"]
    assert has_mech and all(s["rel_props"]["evidence_sources"] for s in has_mech)


def test_no_pathogen_or_resistance_gives_empty_reason(driver):
    assert run(driver, intent="alternatives").empty_reason
    r = run(driver, intent="alternatives", pathogen_ids=[KP])
    assert r.answers == [] and "no resistance" in r.empty_reason

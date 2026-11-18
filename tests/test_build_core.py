"""Tests for pipeline.build_core (task T05).

``build_core`` writes into a temporary directory, so these tests never touch
``data/processed/`` and need no database. They need the raw data in ``data/raw/``.
"""

from __future__ import annotations

import shutil

import pandas as pd
import pytest

from pipeline.build_core import (
    AWARE_2025_FILE,
    GLASS_FILE,
    GLASS_MAP_FILE,
    build_core,
    build_recommendations,
    check_aware,
    infer_regimen_type,
    load_scope,
    read_glass_map,
)
from pipeline.config import DATA_CURATED, DATA_PROCESSED
from pipeline.validate import read_csv_rows, validate_directory

needs_raw = pytest.mark.skipif(
    not (AWARE_2025_FILE.is_file() and GLASS_FILE.is_file()),
    reason="data/raw/ is not downloaded (python -m pipeline.download)",
)

BETA_LACTAM_FAMILIES = {"penicillin", "beta-lactam-bli", "cephalosporin", "carbapenem", "monobactam"}

# data/curated/REVIEW_NOTES.md section 3: beta-lactams left for each mechanism.
EXPECTED_BETA_LACTAMS = {
    "ARO:3000059": {  # KPC
        "ceftazidime-avibactam",
        "meropenem-vaborbactam",
        "imipenem-cilastatin-relebactam",
        "cefiderocol",
        "aztreonam-avibactam",
    },
    "ARO:3000057": {"aztreonam", "aztreonam-avibactam", "cefiderocol"},  # NDM
    "ARO:3007721": {  # OXA-48-like
        "ceftazidime-avibactam",
        "cefiderocol",
        "aztreonam-avibactam",
        "aztreonam",
        "cefazolin",
        "cefuroxime",
        "ceftriaxone",
        "cefotaxime",
        "ceftazidime",
        "cefepime",
        "ceftaroline fosamil",
    },
}
NON_BETA_LACTAMS_LEFT = 16


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("processed")
    report = build_core(out)
    # SUPPORTS edges start at Passage nodes, which T06 writes; copy them (read-only) so that
    # endpoint checks in the validation test can see them.
    passages = DATA_PROCESSED / "nodes_Passage.csv"
    if passages.is_file():
        shutil.copy(passages, out / passages.name)
    return out, report


def _rows(out, name):
    return read_csv_rows(out / name)


@needs_raw
def test_all_listed_files_are_written(built):
    out, _ = built
    labels = ["Pathogen", "Mechanism", "Gene", "Drug", "DrugClass", "Guideline", "SurveillanceStat"]
    types = [
        "HAS_MECHANISM", "ENCODES", "CONFERS_RESISTANCE_TO", "INACTIVATES",
        "INTRINSICALLY_RESISTANT_TO", "IN_CLASS", "ABOUT_PATHOGEN", "ABOUT_DRUG", "ABOUT_CLASS",
    ]
    for label in labels:
        assert (out / f"nodes_{label}.csv").is_file(), label
    for rel in types:
        assert (out / f"edges_{rel}.csv").is_file(), rel


@needs_raw
def test_every_file_passes_validation_with_no_rejections(built):
    out, _ = built
    result = validate_directory(out)
    assert result.ok, [
        (p.name, r.reason_counts()) for p, r in result.node_reports + result.edge_reports if not r.ok
    ]
    assert not result.problems


@needs_raw
def test_seed_nodes_match_scope_yaml(built):
    out, _ = built
    scope = load_scope()
    assert len(_rows(out, "nodes_Pathogen.csv")) == len(scope["pathogens"]) == 5
    assert len(_rows(out, "nodes_Mechanism.csv")) == len(scope["mechanisms"])
    assert len(_rows(out, "nodes_Drug.csv")) == len(scope["drugs"])
    assert len(_rows(out, "nodes_DrugClass.csv")) == len(scope["drug_classes"])
    assert len(_rows(out, "nodes_Guideline.csv")) == 3


@needs_raw
def test_drug_class_family_and_dropped_columns(built):
    out, _ = built
    scope = load_scope()
    classes = _rows(out, "nodes_DrugClass.csv")
    assert list(classes[0]) == ["id", "name", "family"]
    assert all(c["family"] for c in classes)
    assert {c["id"]: c["family"] for c in classes} == {c["id"]: c["family"] for c in scope["drug_classes"]}
    drug_columns = list(_rows(out, "nodes_Drug.csv")[0])
    assert "id_verified" not in drug_columns
    assert "class_id" not in drug_columns


@needs_raw
def test_in_class_edges_follow_scope_yaml_not_aware(built):
    out, _ = built
    scope = load_scope()
    edges = {r["start_id"]: r["end_id"] for r in _rows(out, "edges_IN_CLASS.csv")}
    assert edges == {d["id"]: d["class_id"] for d in scope["drugs"]}
    # AWaRe files ceftazidime-avibactam under cephalosporins; the graph must not (D28).
    assert edges["J01DD52"] == "cephalosporin-bli"


@needs_raw
def test_drug_properties_come_from_seed_files(built):
    out, _ = built
    drugs = {r["id"]: r for r in _rows(out, "nodes_Drug.csv")}
    assert drugs["J01DH02"]["aware_group"] == "Watch"
    assert drugs["J01DH02"]["synonyms"]  # from schema/synonyms.csv
    assert "meropenem" not in [s.lower() for s in drugs["J01DH02"]["synonyms"].split("|")]  # canonical excluded
    assert drugs["J01CG30"]["aware_group"] == "Unclassified"


@needs_raw
@pytest.mark.parametrize(
    "filename,rel",
    [
        ("pathogen_mechanism.csv", "HAS_MECHANISM"),
        ("mechanism_class.csv", "CONFERS_RESISTANCE_TO"),
        ("mechanism_inactivates_drug.csv", "INACTIVATES"),
        ("intrinsic_resistance.csv", "INTRINSICALLY_RESISTANT_TO"),
    ],
)
def test_curated_edges_keep_review_flags(built, filename, rel):
    out, _ = built
    source = read_csv_rows(DATA_CURATED / filename)
    edges = _rows(out, f"edges_{rel}.csv")
    assert len(edges) == len(source)
    assert {e["source_id"] for e in edges} == {"curated-seed"}
    assert {e["method"] for e in edges} == {"curated"}
    assert {e["confidence"] for e in edges} == {"1.0"}
    assert [e["needs_review"] for e in edges] == [s["needs_review"].lower() for s in source]
    assert [e["notes"] for e in edges] == [s["notes"] for s in source]


@needs_raw
def test_aware_cross_check_reports_no_mismatch(built):
    _, report = built
    aware = report["aware"]
    assert aware["drugs_checked"] == 49
    assert aware["mismatches"] == 0, aware["mismatch_list"]
    assert [d["id"] for d in aware["absent_list"]] == ["J01CG30"]


def test_check_aware_picks_iv_row_and_reports_mismatches():
    scope = {
        "drugs": [
            {"id": "J01XX01", "name": "fosfomycin", "aware_group": "Reserve"},
            {"id": "J01CR02", "name": "amoxicillin-clavulanic acid", "aware_group": "Access"},
            {"id": "J01DH02", "name": "meropenem", "aware_group": "Access"},
            {"id": "J01ZZ99", "name": "madeup", "aware_group": "Watch"},
            {"id": "J01ZZ98", "name": "other", "aware_group": "Unclassified"},
        ]
    }
    aware = pd.DataFrame(
        [
            ["Fosfomycin_oral", "Phosphonics", "J01XX01", "Watch"],
            ["Fosfomycin_IV", "Phosphonics", "J01XX01", "Reserve"],
            ["Amoxicillin/sulbactam", "BL/BLI", "J01CR02", "Watch"],
            ["Amoxicillin/clavulanic-acid", "BL/BLI", "J01CR02", "Access"],
            ["Meropenem", "Carbapenems", "J01DH02", "Watch"],
        ],
        columns=["Antibiotic", "Class", "ATC code", "Category"],
    )
    result = check_aware(scope, aware)
    assert result["matches"] == 2  # fosfomycin (IV row) and amoxicillin-clavulanic acid (by name)
    assert result["mismatches"] == 2
    by_id = {m["id"]: m for m in result["mismatch_list"]}
    assert by_id["J01DH02"]["aware_2025"] == "Watch"
    assert by_id["J01ZZ99"]["aware_2025"] == "(not in AWaRe 2025)"
    assert result["absent_and_unclassified"] == 1


@needs_raw
def test_card_genes_are_capped_and_attach_to_scope_mechanisms(built):
    out, report = built
    genes = _rows(out, "nodes_Gene.csv")
    encodes = _rows(out, "edges_ENCODES.csv")
    mechanism_ids = {m["id"] for m in load_scope()["mechanisms"]}
    assert 0 < len(genes) <= 1000
    assert report["card"]["genes_kept"] == len(genes)
    assert {e["end_id"] for e in encodes} <= mechanism_ids
    assert {e["start_id"] for e in encodes} == {g["id"] for g in genes}
    assert {e["source_id"] for e in encodes} == {"card"}


def test_glass_map_targets_exist_in_scope():
    scope = load_scope()
    drugs = {d["id"] for d in scope["drugs"]}
    classes = {c["id"] for c in scope["drug_classes"]}
    for name, (label, target) in read_glass_map(GLASS_MAP_FILE).items():
        if not target:
            continue  # deliberately unmapped
        assert label in ("Drug", "DrugClass"), name
        assert target in (drugs if label == "Drug" else classes), name


@needs_raw
def test_glass_stats(built):
    out, report = built
    stats = {r["id"]: r for r in _rows(out, "nodes_SurveillanceStat.csv")}
    glass = report["glass"]
    assert len(stats) == glass["stats_written"] > 10_000
    assert glass["glass_names_unmapped"]  # skipped and counted, not silently dropped
    pathogen_edges = _rows(out, "edges_ABOUT_PATHOGEN.csv")
    assert len(pathogen_edges) == len(stats)
    assert len(_rows(out, "edges_ABOUT_DRUG.csv")) + len(_rows(out, "edges_ABOUT_CLASS.csv")) == len(stats)
    # GLASS has no P. aeruginosa; Acinetobacter is genus level (D30).
    assert {e["end_id"] for e in pathogen_edges} == {
        "NCBITaxon:573", "NCBITaxon:562", "NCBITaxon:470", "NCBITaxon:1280",
    }
    for edge in pathogen_edges:
        if edge["end_id"] == "NCBITaxon:470":
            assert edge["reported_taxon"] == "Acinetobacter spp."
        else:
            assert edge["reported_taxon"] == ""
    # A value checked by hand in the raw file (T02 handoff): India, K. pneumoniae, meropenem, 2018.
    india = stats["GLASS:IND:2018:NCBITaxon:573:J01DH02"]
    assert float(india["pct_resistant"]) == pytest.approx(55.159038014)
    assert int(india["n_tested"]) > 0
    class_edges = _rows(out, "edges_ABOUT_CLASS.csv")
    assert any(e["end_id"] == "carbapenem" for e in class_edges)
    assert all(e["end_label"] == "DrugClass" for e in class_edges)


@needs_raw
def test_worked_example_sets_match_review_notes(built):
    """REVIEW_NOTES.md section 3, computed from the built edge files."""
    out, _ = built
    scope = load_scope()
    drug_name = {d["id"]: d["name"] for d in scope["drugs"]}
    drug_class = {d["id"]: d["class_id"] for d in scope["drugs"]}
    family = {c["id"]: c["family"] for c in scope["drug_classes"]}

    intrinsic = {
        e["end_id"] for e in _rows(out, "edges_INTRINSICALLY_RESISTANT_TO.csv")
        if e["start_id"] == "NCBITaxon:573"
    }
    confers: dict[str, set[str]] = {}
    for e in _rows(out, "edges_CONFERS_RESISTANCE_TO.csv"):
        confers.setdefault(e["start_id"], set()).add(e["end_id"])
    inactivates: dict[str, set[str]] = {}
    for e in _rows(out, "edges_INACTIVATES.csv"):
        inactivates.setdefault(e["start_id"], set()).add(e["end_id"])

    results = {}
    for mechanism, expected in EXPECTED_BETA_LACTAMS.items():
        left = [
            d for d in drug_class
            if drug_class[d] not in intrinsic
            and drug_class[d] not in confers.get(mechanism, set())
            and d not in inactivates.get(mechanism, set())
        ]
        beta = {drug_name[d] for d in left if family[drug_class[d]] in BETA_LACTAM_FAMILIES}
        other = [d for d in left if family[drug_class[d]] not in BETA_LACTAM_FAMILIES]
        assert beta == expected, mechanism
        assert len(other) == NON_BETA_LACTAMS_LEFT, mechanism
        results[mechanism] = frozenset(beta)
    assert len(set(results.values())) == 3  # three different answers


@needs_raw
def test_curated_edges_carry_evidence_sources(built):
    out, _ = built
    source = read_csv_rows(DATA_CURATED / "mechanism_inactivates_drug.csv")
    edges = _rows(out, "edges_INACTIVATES.csv")
    assert [e["evidence_sources"] for e in edges] == [s["source"] for s in source]
    assert any("|" in e["evidence_sources"] for e in edges)


@needs_raw
def test_glass_methicillin_and_oxacillin(built):
    out, report = built
    mapping = read_glass_map(GLASS_MAP_FILE)
    assert mapping["Methicillin"] == ("DrugClass", "antistaphylococcal-penicillin")
    # D35 (corrected): oxacillin is not in scope, so GLASS Oxacillin is deliberately unmapped.
    assert mapping["Oxacillin"] == ("", "")
    class_edges = _rows(out, "edges_ABOUT_CLASS.csv")
    mrsa = [e for e in class_edges if e["end_id"] == "antistaphylococcal-penicillin"]
    assert mrsa and all(e["start_id"].split(":")[3:5] == ["NCBITaxon", "1280"] for e in mrsa)
    assert not report["glass"].get("glass_targets_not_in_scope")


@needs_raw
def test_recommendation_files(built):
    out, report = built
    source = read_csv_rows(DATA_CURATED / "recommendations_curated.csv")
    recs = _rows(out, "nodes_Recommendation.csv")
    assert [r["id"] for r in recs] == [r["rec_id"] for r in source]
    assert list(recs[0]) == ["id", "text", "infection_site", "line_of_therapy", "patient_group", "regimen_type"]
    assert all(r["regimen_type"] in ("single", "combination", "any-of") for r in recs)
    assert len(_rows(out, "edges_FOR_PATHOGEN.csv")) == len(source)
    assert len(_rows(out, "edges_FROM.csv")) == len(source)
    expected_drugs = sum(len(set(r["drug_ids"].split("|"))) for r in source)
    assert len(_rows(out, "edges_RECOMMENDS.csv")) == expected_drugs
    expected_mech = sum(len({m for m in r["mechanism_id"].split("|") if m}) for r in source)
    assert len(_rows(out, "edges_FOR_MECHANISM.csv")) == expected_mech
    assert report["recommendations"]["rows_without_supporting_passage"] == []


@needs_raw
def test_supports_edges_point_at_passages_of_the_same_document(built):
    out, _ = built
    source = {r["rec_id"]: r for r in read_csv_rows(DATA_CURATED / "recommendations_curated.csv")}
    supports = _rows(out, "edges_SUPPORTS.csv")
    assert supports
    covered = set()
    for e in supports:
        rec = source[e["end_id"]]
        assert e["start_label"] == "Passage" and e["end_label"] == "Recommendation"
        assert e["method"] == "rule"
        assert e["start_id"].startswith(rec["guideline_id"] + ":")
        assert 0 < float(e["confidence"]) <= 1
        covered.add(e["end_id"])
    assert covered == set(source)


def _write_recs(path, header, rows):
    lines = [",".join(header), *(",".join(r) for r in rows)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_passages(path, items):
    import json

    path.write_text("\n".join(json.dumps(i) for i in items) + "\n", encoding="utf-8")


def test_recommendations_infer_regimen_type_and_split_mechanisms(tmp_path):
    header = [
        "rec_id", "guideline_id", "pathogen_id", "mechanism_id", "drug_ids", "infection_site",
        "line_of_therapy", "patient_group", "text", "source_section", "source_page",
    ]
    base = ["REC:who-aware-book-2022:00%d", "who-aware-book-2022", "NCBITaxon:573"]
    rows = [
        [base[0] % 1, base[1], base[2], "ARO:3000057|ARO:3007721", "J01DD52", "", "first", "", "t", "1. Sec", "5"],
        [base[0] % 2, base[1], base[2], "", "J01DD52|J01DF01", "", "first", "", "t", "1. Sec", "9"],
    ]
    recs = tmp_path / "recs.csv"
    _write_recs(recs, header, rows)
    passages = tmp_path / "passages.jsonl"
    _write_passages(
        passages,
        [
            {"id": "who-aware-book-2022:a:1", "source_doc": "who-aware-book-2022", "page": 5, "heading": "1. Sec"},
            {"id": "who-aware-book-2022:a:2", "source_doc": "who-aware-book-2022", "page": 6, "heading": "1. Sec"},
            {"id": "other-doc-2020:a:1", "source_doc": "other-doc-2020", "page": 9, "heading": ""},
        ],
    )
    nodes, edges, report = build_recommendations(load_scope(), recs, passages)
    assert [n["regimen_type"] for n in nodes] == ["single", "any-of"]
    assert report["regimen_type_inferred"] == 2
    assert [(e["start_id"][-1], e["end_id"]) for e in edges["FOR_MECHANISM"]] == [
        ("1", "ARO:3000057"), ("1", "ARO:3007721"),
    ]
    assert len(edges["RECOMMENDS"]) == 3
    exact = [e for e in edges["SUPPORTS"] if e["end_id"].endswith("001")]
    assert [e["start_id"] for e in exact] == ["who-aware-book-2022:a:1"] and exact[0]["confidence"] == 1.0
    # page 9 has no passage in this document: the nearest earlier one (page 6) is used.
    nearest = [e for e in edges["SUPPORTS"] if e["end_id"].endswith("002")]
    assert [e["start_id"] for e in nearest] == ["who-aware-book-2022:a:2"]
    assert nearest[0]["confidence"] == 0.7
    assert report["rows_with_nearest_earlier_passage"] == 1


def test_recommendations_keep_explicit_regimen_type_column(tmp_path):
    header = [
        "rec_id", "guideline_id", "pathogen_id", "mechanism_id", "drug_ids", "regimen_type",
        "infection_site", "line_of_therapy", "patient_group", "text", "source_section", "source_page",
    ]
    row = ["REC:who-aware-book-2022:001", "who-aware-book-2022", "NCBITaxon:573", "", "J01DD52|J01DF01",
           "combination", "", "first", "", "t", "x", ""]
    recs = tmp_path / "recs.csv"
    _write_recs(recs, header, [row])
    nodes, edges, report = build_recommendations(load_scope(), recs, tmp_path / "missing.jsonl")
    assert nodes[0]["regimen_type"] == "combination"
    assert report["regimen_type_inferred"] == 0
    assert edges["SUPPORTS"] == [] and report["rows_without_supporting_passage"] == ["REC:who-aware-book-2022:001"]


def test_infer_regimen_type():
    assert infer_regimen_type(["J01DD52"]) == "single"
    assert infer_regimen_type(["J01DD52", "J01DF01"]) == "any-of"

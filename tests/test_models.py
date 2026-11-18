"""Tests for pipeline.models: node models, ID formats, Edge, registries."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pipeline.models import (
    EDGE_TYPES,
    NODE_MODELS,
    Drug,
    DrugClass,
    Edge,
    Gene,
    Guideline,
    Mechanism,
    Passage,
    Pathogen,
    Recommendation,
    RecommendationExtraction,
    SurveillanceStat,
    check_id,
    is_valid_id,
)

# ---------------------------------------------------------------------------
# ID formats: (label, valid examples, invalid examples)
# ---------------------------------------------------------------------------

ID_CASES = [
    (
        "Drug",
        ["J01DH02", "J01DD52", "LOCAL:drug:aztreonam-avibactam"],
        ["j01dh02", "J01DH0", "J01DH022", "LOCAL:drug:Aztreonam", "drug:aztreonam", "meropenem", ""],
    ),
    (
        "DrugClass",
        ["carbapenem", "beta-lactam-inhibitor-combination"],
        ["Carbapenem", "carbapenem-", "-carbapenem", "carba pen", "carba_penem", ""],
    ),
    (
        "Pathogen",
        ["NCBITaxon:573", "NCBITaxon:1280"],
        ["573", "NCBITaxon:", "NCBITaxon:abc", "ncbitaxon:573", "NCBITaxon:573 "],
    ),
    (
        "Mechanism",
        ["ARO:3000059", "LOCAL:mech:porin-loss"],
        ["ARO:300005", "ARO:30000590", "LOCAL:mech:Porin", "LOCAL:drug:porin-loss", "aro:3000059"],
    ),
    ("Gene", ["ARO:3002312"], ["ARO:123", "LOCAL:mech:x", "3002312"]),
    (
        "Guideline",
        ["who-aware-book-2022", "idsa-2023"],
        ["who-aware-book", "who-aware-book-22", "WHO-2022", "2022", "-2022"],
    ),
    (
        "Recommendation",
        ["REC:who-aware-book-2022:014", "REC:idsa-2023:001"],
        ["REC:who-aware-book-2022:14", "REC:who-aware-book:014", "who-aware-book-2022:014", "REC:who-aware-book-2022:0140"],
    ),
    (
        "Passage",
        ["who-aware-book-2022:sepsis-adults:3", "pubmed-123:abstract:1"],
        ["who-aware-book-2022:sepsis-adults", "who-aware-book-2022:Sepsis:3", "a:b:c", "a::3"],
    ),
    (
        "SurveillanceStat",
        [
            "GLASS:IND:2022:NCBITaxon:573:J01DH02",
            "GLASS:KEN:2021:NCBITaxon:562:carbapenem",
            "GLASS:IND:2022:NCBITaxon:573:LOCAL:drug:aztreonam-avibactam",
        ],
        ["GLASS:IN:2022:NCBITaxon:573:J01DH02", "GLASS:IND:22:NCBITaxon:573:J01DH02", "GLASS:IND:2022:573:J01DH02", "GLASS:IND:2022:NCBITaxon:573"],
    ),
]


@pytest.mark.parametrize("label,valid,_invalid", ID_CASES)
def test_valid_ids_accepted(label, valid, _invalid):
    for value in valid:
        assert check_id(label, value) == value
        assert is_valid_id(label, value)


@pytest.mark.parametrize("label,_valid,invalid", ID_CASES)
def test_invalid_ids_rejected(label, _valid, invalid):
    for value in invalid:
        assert not is_valid_id(label, value), value
        with pytest.raises(ValueError):
            check_id(label, value)


def test_check_id_unknown_label():
    with pytest.raises(ValueError, match="unknown label"):
        check_id("Banana", "x")


def test_id_cases_cover_every_label():
    assert {case[0] for case in ID_CASES} == set(NODE_MODELS)


# ---------------------------------------------------------------------------
# Node models
# ---------------------------------------------------------------------------

VALID_ROWS = {
    "Pathogen": {"id": "NCBITaxon:573", "name": "Klebsiella pneumoniae", "gram_stain": "negative", "synonyms": "K. pneumoniae|Kleb"},
    "Mechanism": {"id": "ARO:3000059", "name": "KPC beta-lactamase", "type": "carbapenemase", "ambler_class": "A"},
    "Gene": {"id": "ARO:3002312", "name": "KPC-2"},
    "Drug": {"id": "J01DH02", "name": "meropenem", "aware_group": "Watch", "synonyms": "Merrem"},
    "DrugClass": {"id": "carbapenem", "name": "Carbapenems"},
    "Recommendation": {
        "id": "REC:who-aware-book-2022:014",
        "text": "Use ceftazidime-avibactam for KPC producers.",
        "infection_site": "bloodstream",
        "line_of_therapy": "first",
        "patient_group": "adults",
    },
    "Guideline": {"id": "who-aware-book-2022", "title": "WHO AWaRe antibiotic book", "organisation": "WHO", "year": "2022", "version": ""},
    "SurveillanceStat": {
        "id": "GLASS:IND:2022:NCBITaxon:573:J01DH02",
        "country": "IND",
        "year": "2022",
        "pct_resistant": "54.3",
        "n_tested": "1200",
    },
    "Passage": {"id": "who-aware-book-2022:sepsis-adults:3", "text": "Some text.", "source_doc": "who-aware-book-2022", "section": "sepsis-adults"},
}


@pytest.mark.parametrize("label", sorted(NODE_MODELS))
def test_valid_row_accepted_for_every_label(label):
    node = NODE_MODELS[label].model_validate(VALID_ROWS[label])
    row = node.to_row()
    assert row["id"] == VALID_ROWS[label]["id"]
    assert "id" not in node.properties()
    # a normalised row validates again to the same thing
    assert NODE_MODELS[label].model_validate(row).to_row() == row


@pytest.mark.parametrize("label", sorted(NODE_MODELS))
def test_bad_id_rejected_for_every_label(label):
    row = {**VALID_ROWS[label], "id": "not an id"}
    with pytest.raises(ValidationError):
        NODE_MODELS[label].model_validate(row)


@pytest.mark.parametrize("label", sorted(NODE_MODELS))
def test_unknown_column_rejected(label):
    with pytest.raises(ValidationError, match="Extra inputs"):
        NODE_MODELS[label].model_validate({**VALID_ROWS[label], "colour": "red"})


@pytest.mark.parametrize(
    "label,missing",
    [
        ("Pathogen", "name"),
        ("Mechanism", "name"),
        ("Mechanism", "type"),
        ("Gene", "name"),
        ("Drug", "name"),
        ("DrugClass", "name"),
        ("Recommendation", "text"),
        ("Guideline", "title"),
        ("Guideline", "organisation"),
        ("Guideline", "year"),
        ("SurveillanceStat", "country"),
        ("SurveillanceStat", "pct_resistant"),
        ("Passage", "text"),
        ("Passage", "source_doc"),
        ("Passage", "section"),
    ],
)
def test_required_property_missing_or_blank(label, missing):
    row = {k: v for k, v in VALID_ROWS[label].items() if k != missing}
    with pytest.raises(ValidationError, match=missing):
        NODE_MODELS[label].model_validate(row)
    blank = {**VALID_ROWS[label], missing: "  "}
    with pytest.raises(ValidationError, match=missing):
        NODE_MODELS[label].model_validate(blank)


def test_csv_style_values_are_coerced():
    pathogen = Pathogen.model_validate(VALID_ROWS["Pathogen"])
    assert pathogen.synonyms == ["K. pneumoniae", "Kleb"]
    guideline = Guideline.model_validate(VALID_ROWS["Guideline"])
    assert guideline.year == 2022 and guideline.version is None
    stat = SurveillanceStat.model_validate(VALID_ROWS["SurveillanceStat"])
    assert stat.pct_resistant == 54.3 and stat.n_tested == 1200


def test_optional_blank_cells_use_defaults():
    drug = Drug.model_validate({"id": "J01DH02", "name": "meropenem", "aware_group": "", "synonyms": ""})
    assert drug.aware_group == "Unclassified"
    assert drug.synonyms == []
    mech = Mechanism.model_validate({"id": "LOCAL:mech:porin-loss", "name": "Porin loss", "type": "porin-loss", "ambler_class": ""})
    assert mech.ambler_class is None
    assert "ambler_class" not in mech.to_row()


def test_to_row_serialises_enums_as_plain_strings():
    row = Drug.model_validate(VALID_ROWS["Drug"]).to_row()
    assert row["aware_group"] == "Watch" and type(row["aware_group"]) is str
    assert row["synonyms"] == ["Merrem"]


@pytest.mark.parametrize(
    "label,field,bad",
    [
        ("Drug", "aware_group", "Reserved"),
        ("Drug", "aware_group", "watch"),
        ("Mechanism", "type", "magic"),
        ("Mechanism", "ambler_class", "E"),
        ("Pathogen", "gram_stain", "purple"),
        ("Recommendation", "line_of_therapy", "third"),
        ("Guideline", "year", "twenty"),
        ("Guideline", "year", "1800"),
        ("SurveillanceStat", "pct_resistant", "101"),
        ("SurveillanceStat", "pct_resistant", "-1"),
        ("SurveillanceStat", "n_tested", "-5"),
        ("SurveillanceStat", "country", "IN"),
    ],
)
def test_invalid_property_values_rejected(label, field, bad):
    with pytest.raises(ValidationError, match=field):
        NODE_MODELS[label].model_validate({**VALID_ROWS[label], field: bad})


@pytest.mark.parametrize("group", ["Access", "Watch", "Reserve", "Unclassified"])
def test_every_aware_group_accepted(group):
    assert Drug.model_validate({"id": "J01DH02", "name": "x", "aware_group": group}).aware_group == group


@pytest.mark.parametrize("line", ["first", "second", "alternative", "last-resort"])
def test_every_line_of_therapy_accepted(line):
    rec = Recommendation.model_validate({**VALID_ROWS["Recommendation"], "line_of_therapy": line})
    assert rec.line_of_therapy == line


@pytest.mark.parametrize("kind", ["single", "combination", "any-of"])
def test_every_regimen_type_accepted(kind):
    rec = Recommendation.model_validate({**VALID_ROWS["Recommendation"], "regimen_type": kind})
    assert rec.regimen_type == kind
    assert rec.to_row()["regimen_type"] == kind


def test_regimen_type_is_optional_blank_and_checked():
    base = VALID_ROWS["Recommendation"]
    assert Recommendation.model_validate(base).regimen_type is None
    assert Recommendation.model_validate({**base, "regimen_type": ""}).regimen_type is None
    with pytest.raises(ValidationError):
        Recommendation.model_validate({**base, "regimen_type": "either"})


@pytest.mark.parametrize("kind", ["carbapenemase", "esbl", "ampc", "target-modification", "efflux", "porin-loss", "other"])
def test_every_mechanism_type_accepted(kind):
    assert Mechanism.model_validate({**VALID_ROWS["Mechanism"], "type": kind}).type == kind


def test_surveillance_id_must_match_country_and_year():
    with pytest.raises(ValidationError, match="does not match id country"):
        SurveillanceStat.model_validate({**VALID_ROWS["SurveillanceStat"], "country": "KEN"})
    with pytest.raises(ValidationError, match="does not match id year"):
        SurveillanceStat.model_validate({**VALID_ROWS["SurveillanceStat"], "year": "2021"})


def test_node_models_registry_has_the_nine_labels():
    assert set(NODE_MODELS) == {
        "Pathogen", "Mechanism", "Gene", "Drug", "DrugClass",
        "Recommendation", "Guideline", "SurveillanceStat", "Passage",
    }
    for label, model in NODE_MODELS.items():
        assert model.LABEL == label
        assert model.__name__ == label


def test_models_are_the_registered_classes():
    for model in (Pathogen, Mechanism, Gene, Drug, DrugClass, Recommendation, Guideline, SurveillanceStat, Passage):
        assert NODE_MODELS[model.LABEL] is model


# ---------------------------------------------------------------------------
# Edge and EDGE_TYPES
# ---------------------------------------------------------------------------

VALID_EDGE = {
    "start_id": "NCBITaxon:573",
    "start_label": "Pathogen",
    "end_id": "ARO:3000059",
    "end_label": "Mechanism",
    "source_id": "curated-seed",
    "method": "curated",
    "confidence": "",
    "evidence_passage_id": "",
}


def test_valid_curated_edge_defaults_confidence_to_one():
    edge = Edge.model_validate(VALID_EDGE)
    assert edge.confidence == 1.0
    row = edge.to_row()
    assert row["method"] == "curated" and "evidence_passage_id" not in row
    assert set(edge.properties()) == {"source_id", "method", "confidence"}


def test_extra_edge_columns_are_kept_as_properties():
    edge = Edge.model_validate({**VALID_EDGE, "note": "hand checked"})
    assert edge.properties()["note"] == "hand checked"


@pytest.mark.parametrize("missing", ["source_id", "method"])
def test_edge_requires_provenance(missing):
    row = {k: v for k, v in VALID_EDGE.items() if k != missing}
    with pytest.raises(ValidationError, match=missing):
        Edge.model_validate(row)
    with pytest.raises(ValidationError, match=missing):
        Edge.model_validate({**VALID_EDGE, missing: ""})


@pytest.mark.parametrize("method", ["rule", "llm"])
def test_extracted_edge_needs_confidence(method):
    with pytest.raises(ValidationError, match="confidence is required"):
        Edge.model_validate({**VALID_EDGE, "method": method})
    edge = Edge.model_validate({**VALID_EDGE, "method": method, "confidence": "0.7"})
    assert edge.confidence == 0.7


@pytest.mark.parametrize(
    "overrides,match",
    [
        ({"method": "guess"}, "method"),
        ({"confidence": "1.5"}, "confidence"),
        ({"confidence": "-0.1"}, "confidence"),
        ({"source_id": "somewhere-else"}, "source_id"),
        ({"start_label": "Banana"}, "unknown label"),
        ({"start_id": "ARO:1"}, "not a valid Pathogen id"),
        ({"end_id": "NCBITaxon:573"}, "not a valid Mechanism id"),
        ({"evidence_passage_id": "not-a-passage"}, "not a valid Passage id"),
    ],
)
def test_invalid_edge_values_rejected(overrides, match):
    with pytest.raises(ValidationError, match=match):
        Edge.model_validate({**VALID_EDGE, **overrides})


@pytest.mark.parametrize(
    "source_id",
    ["card", "who-aware-2023", "who-aware-2025", "glass", "curated-seed", "pubmed", "who-aware-book-2022"],
)
def test_valid_edge_source_ids(source_id):
    assert Edge.model_validate({**VALID_EDGE, "source_id": source_id}).source_id == source_id


def test_edge_evidence_passage_id_accepted():
    edge = Edge.model_validate({**VALID_EDGE, "evidence_passage_id": "who-aware-book-2022:sepsis-adults:3"})
    assert edge.evidence_passage_id == "who-aware-book-2022:sepsis-adults:3"


def test_edge_types_cover_every_architecture_relationship():
    expected = {
        "HAS_MECHANISM": {("Pathogen", "Mechanism")},
        "ENCODES": {("Gene", "Mechanism")},
        "CONFERS_RESISTANCE_TO": {("Mechanism", "DrugClass")},
        "INACTIVATES": {("Mechanism", "Drug")},
        "INTRINSICALLY_RESISTANT_TO": {("Pathogen", "DrugClass")},
        "IN_CLASS": {("Drug", "DrugClass")},
        "FOR_PATHOGEN": {("Recommendation", "Pathogen")},
        "FOR_MECHANISM": {("Recommendation", "Mechanism")},
        "RECOMMENDS": {("Recommendation", "Drug")},
        "FROM": {("Recommendation", "Guideline")},
        "ABOUT_PATHOGEN": {("SurveillanceStat", "Pathogen")},
        "ABOUT_DRUG": {("SurveillanceStat", "Drug")},
        "ABOUT_CLASS": {("SurveillanceStat", "DrugClass")},
        "MENTIONS": {("Passage", "Pathogen"), ("Passage", "Drug"), ("Passage", "DrugClass"), ("Passage", "Mechanism")},
        "SUPPORTS": {("Passage", "Recommendation")},
    }
    assert {k: set(v) for k, v in EDGE_TYPES.items()} == expected
    labels = set(NODE_MODELS)
    for pairs in EDGE_TYPES.values():
        for start, end in pairs:
            assert start in labels and end in labels


# ---------------------------------------------------------------------------
# RecommendationExtraction
# ---------------------------------------------------------------------------


def test_recommendation_extraction_minimal_and_full():
    minimal = RecommendationExtraction.model_validate(
        {"pathogen": "Klebsiella pneumoniae", "drugs": ["meropenem"], "evidence_text": "Use meropenem."}
    )
    assert minimal.mechanism is None and minimal.line_of_therapy is None

    full = RecommendationExtraction.model_validate(
        {
            "pathogen": "K. pneumoniae",
            "mechanism": "KPC",
            "drugs": "ceftazidime-avibactam|meropenem-vaborbactam",
            "infection_site": "bloodstream",
            "line_of_therapy": "first",
            "patient_group": "adults",
            "evidence_text": "For KPC producers, use ...",
            "passage_id": "who-aware-book-2022:sepsis-adults:3",
            "method": "llm",
            "confidence": 0.8,
        }
    )
    assert full.drugs == ["ceftazidime-avibactam", "meropenem-vaborbactam"]
    assert full.model_dump(mode="json")["line_of_therapy"] == "first"


@pytest.mark.parametrize(
    "overrides",
    [
        {"drugs": []},
        {"drugs": ""},
        {"pathogen": ""},
        {"evidence_text": ""},
        {"line_of_therapy": "third"},
        {"passage_id": "bad"},
        {"confidence": 2},
    ],
)
def test_recommendation_extraction_rejects_bad_input(overrides):
    base = {"pathogen": "Klebsiella pneumoniae", "drugs": ["meropenem"], "evidence_text": "Use meropenem."}
    with pytest.raises(ValidationError):
        RecommendationExtraction.model_validate({**base, **overrides})

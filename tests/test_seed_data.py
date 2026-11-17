"""Consistency tests for the hand-curated seed data (task T03).

Covers schema/scope.yaml, schema/synonyms.csv, schema/class_overrides.csv and the four
resistance-fact files in data/curated/. Also runs the worked example from
data/curated/REVIEW_NOTES.md (carbapenem-resistant K. pneumoniae by mechanism) on the raw
files, so a change to the seed data that breaks the acceptance example fails here first.
"""

from __future__ import annotations

import csv
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

import pytest
import yaml

from pipeline.config import DATA_CURATED, SCHEMA_DIR

# ---------------------------------------------------------------------------
# Contract constants (CONTRACTS.md sections 2-4)
# ---------------------------------------------------------------------------

SLUG = r"[a-z0-9]+(?:-[a-z0-9]+)*"
ID_RE = {
    "Drug": re.compile(rf"(?:[A-Z][0-9]{{2}}[A-Z]{{2}}[0-9]{{2}}|LOCAL:drug:{SLUG})"),
    "DrugClass": re.compile(SLUG),
    "Pathogen": re.compile(r"NCBITaxon:[0-9]+"),
    "Mechanism": re.compile(rf"(?:ARO:[0-9]{{7}}|LOCAL:mech:{SLUG})"),
    "Gene": re.compile(r"ARO:[0-9]{7}"),
}
MECHANISM_TYPES = {
    "carbapenemase", "esbl", "ampc", "target-modification", "efflux", "porin-loss", "other",
}
AMBLER = {"A", "B", "C", "D", ""}
AWARE = {"Access", "Watch", "Reserve", "Unclassified"}
SYNONYM_TYPES = {"canonical", "abbreviation", "brand", "variant"}
# Source tags explained in data/curated/REVIEW_NOTES.md section 1.
SOURCE_TAGS = {
    "CARD",
    "IDSA-AMR-GN-2024",
    "EUCAST-ERP-v1.2-2023",
    "EUCAST-expert-rules",
    "WHO-AWaRe-book-2022",
    "ICMR",
    "unverified",
}
TAIL = ["source", "needs_review", "notes"]
CURATED = {
    # file: (leading columns, (label, column) pairs to check against scope)
    "pathogen_mechanism.csv": (
        ["pathogen_id", "pathogen_name", "mechanism_id", "mechanism_name"],
        [("Pathogen", "pathogen"), ("Mechanism", "mechanism")],
    ),
    "mechanism_class.csv": (
        ["mechanism_id", "mechanism_name", "class_id", "class_name"],
        [("Mechanism", "mechanism"), ("DrugClass", "class")],
    ),
    "mechanism_inactivates_drug.csv": (
        ["mechanism_id", "mechanism_name", "drug_id", "drug_name"],
        [("Mechanism", "mechanism"), ("Drug", "drug")],
    ),
    "intrinsic_resistance.csv": (
        ["pathogen_id", "pathogen_name", "class_id", "class_name"],
        [("Pathogen", "pathogen"), ("DrugClass", "class")],
    ),
}

# ---------------------------------------------------------------------------
# Loading helpers
# ---------------------------------------------------------------------------


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
        return list(reader.fieldnames or []), rows


@lru_cache(maxsize=None)
def scope() -> dict:
    with (SCHEMA_DIR / "scope.yaml").open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@lru_cache(maxsize=None)
def entities() -> dict[str, dict[str, dict]]:
    """label -> id -> record, from scope.yaml."""
    s = scope()
    return {
        "Pathogen": {p["id"]: p for p in s["pathogens"]},
        "Mechanism": {m["id"]: m for m in s["mechanisms"]},
        "DrugClass": {c["id"]: c for c in s["drug_classes"]},
        "Drug": {d["id"]: d for d in s["drugs"]},
    }


@lru_cache(maxsize=None)
def families() -> dict[str, set[str]]:
    """family slug -> class ids, from scope.yaml (DECISIONS.md D29)."""
    out: dict[str, set[str]] = {}
    for c in scope()["drug_classes"]:
        out.setdefault(c.get("family"), set()).add(c["id"])
    return out


def curated(name: str) -> list[dict[str, str]]:
    return _read_csv(DATA_CURATED / name)[1]


def norm(text: str) -> str:
    """Normalisation used for synonym clash checks: case, Greek beta, spacing, punctuation."""
    text = text.lower().replace("β", "beta")
    text = re.sub(r"[\s\-/.,()']+", " ", text)
    return text.strip()


# ---------------------------------------------------------------------------
# scope.yaml
# ---------------------------------------------------------------------------


def test_scope_has_all_sections_and_expected_sizes():
    s = scope()
    assert set(s) >= {"pathogens", "mechanisms", "drug_classes", "drugs"}
    names = {p["name"] for p in s["pathogens"]}
    assert names == {
        "Klebsiella pneumoniae",
        "Escherichia coli",
        "Acinetobacter baumannii",
        "Pseudomonas aeruginosa",
        "Staphylococcus aureus",
    }
    assert 10 <= len(s["mechanisms"]) <= 14
    assert 45 <= len(s["drugs"]) <= 55


@pytest.mark.parametrize("label", ["Pathogen", "Mechanism", "DrugClass", "Drug"])
def test_scope_ids_match_contract_format_and_are_unique(label):
    section = {"Pathogen": "pathogens", "Mechanism": "mechanisms",
               "DrugClass": "drug_classes", "Drug": "drugs"}[label]
    ids = [item["id"] for item in scope()[section]]
    bad = [i for i in ids if not ID_RE[label].fullmatch(str(i))]
    assert not bad, f"{label} ids not in contract format: {bad}"
    dupes = [i for i, n in Counter(ids).items() if n > 1]
    assert not dupes, f"duplicate {label} ids: {dupes}"
    names = [item["name"] for item in scope()[section]]
    assert all(isinstance(n, str) and n.strip() for n in names)
    dup_names = [n for n, c in Counter(n.lower() for n in names).items() if c > 1]
    assert not dup_names, f"duplicate {label} names: {dup_names}"


def test_scope_required_mechanisms_present():
    mech_ids = set(entities()["Mechanism"])
    required = {
        "ARO:3000059",  # KPC
        "ARO:3000057",  # NDM
        "ARO:3007721",  # OXA-48-like
        "ARO:3000021",  # VIM
        "ARO:3000016",  # CTX-M
        "ARO:3000069",  # CMY (plasmid AmpC)
        "ARO:3007710",  # OXA-23-like
        "ARO:3009312",  # mecA / PBP2a family
    }
    assert required <= mech_ids


def test_scope_field_values():
    for p in scope()["pathogens"]:
        assert p["gram_stain"] in {"positive", "negative"}
        assert isinstance(p["id_verified"], bool)
    for m in scope()["mechanisms"]:
        assert m["type"] in MECHANISM_TYPES, m
        assert m["ambler_class"] in AMBLER, m
        assert isinstance(m["id_verified"], bool)
        if m["id"].startswith("LOCAL:"):
            assert m["id_verified"] is False, f"LOCAL id cannot be verified: {m['id']}"
        if m["type"] in {"carbapenemase", "esbl", "ampc"}:
            assert m["ambler_class"], f"beta-lactamase without Ambler class: {m['id']}"
    classes = entities()["DrugClass"]
    for d in scope()["drugs"]:
        assert d["aware_group"] in AWARE, d
        assert isinstance(d["id_verified"], bool)
        assert d.get("class_id") in classes, f"drug {d['id']} has unknown class {d.get('class_id')}"


def test_every_class_has_a_drug():
    used = {d["class_id"] for d in scope()["drugs"]}
    unused = set(entities()["DrugClass"]) - used
    assert not unused, f"classes with no drug: {sorted(unused)}"


def test_required_drugs_present():
    names = {d["name"] for d in scope()["drugs"]}
    for required in [
        "ceftazidime-avibactam", "meropenem-vaborbactam", "imipenem-cilastatin-relebactam",
        "ceftolozane-tazobactam", "cefiderocol", "colistin", "tigecycline", "fosfomycin",
        "vancomycin", "linezolid", "daptomycin", "meropenem", "aztreonam",
    ]:
        assert required in names, required


# ---------------------------------------------------------------------------
# class_overrides.csv
# ---------------------------------------------------------------------------


def test_class_overrides_match_scope():
    header, rows = _read_csv(SCHEMA_DIR / "class_overrides.csv")
    assert header == ["drug_id", "drug_name", "class_id", "class_name", "reason"]
    drugs, classes = entities()["Drug"], entities()["DrugClass"]
    seen = Counter(r["drug_id"] for r in rows)
    assert not [d for d, n in seen.items() if n > 1], "a drug is overridden twice"
    for r in rows:
        assert None not in r, f"row has extra columns (unquoted comma?): {r}"
        assert r["drug_id"] in drugs, r
        assert r["drug_name"] == drugs[r["drug_id"]]["name"], r
        assert r["class_id"] in classes, r
        assert r["class_name"] == classes[r["class_id"]]["name"], r
        assert drugs[r["drug_id"]]["class_id"] == r["class_id"], (
            f"scope.yaml class for {r['drug_id']} disagrees with class_overrides.csv"
        )
        assert len(r["reason"].strip()) > 20, f"reason too short for {r['drug_id']}"


def test_bl_bli_combinations_are_not_in_their_backbone_class():
    """D6 / ARCHITECTURE 5.2 rule 3: combinations have their own classes."""
    by_name = {d["name"]: d for d in scope()["drugs"]}
    assert by_name["ceftazidime-avibactam"]["class_id"] != by_name["ceftazidime"]["class_id"]
    assert by_name["meropenem-vaborbactam"]["class_id"] != by_name["meropenem"]["class_id"]
    assert by_name["imipenem-cilastatin-relebactam"]["class_id"] != by_name["meropenem"]["class_id"]
    assert by_name["aztreonam-avibactam"]["class_id"] != by_name["aztreonam"]["class_id"]


# ---------------------------------------------------------------------------
# Curated resistance facts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("filename", sorted(CURATED))
def test_curated_file_structure_and_references(filename):
    leading, refs = CURATED[filename]
    header, rows = _read_csv(DATA_CURATED / filename)
    assert header == leading + TAIL, f"{filename}: header {header}"
    assert rows, f"{filename} is empty"
    ents = entities()
    keys = []
    for line_no, r in enumerate(rows, start=2):
        where = f"{filename}:{line_no}"
        assert None not in r, f"{where}: extra columns (unquoted comma?)"
        for label, prefix in refs:
            ident, name = r[f"{prefix}_id"], r[f"{prefix}_name"]
            assert ID_RE[label].fullmatch(ident), f"{where}: bad {label} id {ident!r}"
            assert ident in ents[label], f"{where}: {label} {ident} not in scope.yaml"
            assert name == ents[label][ident]["name"], (
                f"{where}: name {name!r} != scope name {ents[label][ident]['name']!r}"
            )
        assert r["needs_review"] in {"true", "false"}, f"{where}: needs_review={r['needs_review']!r}"
        tags = r["source"].split("|")
        assert r["source"] and all(t in SOURCE_TAGS for t in tags), f"{where}: source {r['source']!r}"
        if "unverified" in tags:
            assert tags == ["unverified"], f"{where}: 'unverified' mixed with a source"
            assert r["needs_review"] == "true", f"{where}: unverified row must need review"
        keys.append((r[leading[0]], r[leading[2]]))
    dupes = [k for k, n in Counter(keys).items() if n > 1]
    assert not dupes, f"{filename}: duplicate rows {dupes}"


def test_drug_level_exceptions_are_not_redundant():
    """An INACTIVATES row should not duplicate a class-level edge from the same mechanism."""
    class_edges = {(r["mechanism_id"], r["class_id"]) for r in curated("mechanism_class.csv")}
    drugs = entities()["Drug"]
    redundant = [
        (r["mechanism_id"], r["drug_id"])
        for r in curated("mechanism_inactivates_drug.csv")
        if (r["mechanism_id"], drugs[r["drug_id"]]["class_id"]) in class_edges
    ]
    assert not redundant, f"drug-level rows already covered by a class edge: {redundant}"


def test_beta_lactamases_have_no_class_edges_to_combination_classes():
    """Modelling rule (REVIEW_NOTES 2.2): enzyme effects on BL/BLI combinations are drug-level."""
    combo_classes = {
        "aminopenicillin-bli", "aminopenicillin-sulbactam", "antipseudomonal-penicillin-bli",
        "sulbactam-durlobactam", "cephalosporin-bli", "carbapenem-bli", "monobactam-bli",
    }
    mechs = entities()["Mechanism"]
    bad = [
        (r["mechanism_id"], r["class_id"])
        for r in curated("mechanism_class.csv")
        if mechs[r["mechanism_id"]]["type"] in {"carbapenemase", "esbl", "ampc"}
        and r["class_id"] in combo_classes
    ]
    assert not bad, bad


def test_every_mechanism_occurs_in_a_pathogen_and_has_an_effect():
    pm = {r["mechanism_id"] for r in curated("pathogen_mechanism.csv")}
    effects = {r["mechanism_id"] for r in curated("mechanism_class.csv")} | {
        r["mechanism_id"] for r in curated("mechanism_inactivates_drug.csv")
    }
    for mech_id in entities()["Mechanism"]:
        assert mech_id in pm, f"{mech_id} is in no pathogen"
        assert mech_id in effects, f"{mech_id} has no resistance effect"


def test_no_doses_in_curated_text():
    dose = re.compile(r"\b\d+(?:\.\d+)?\s?(?:mg|g|mcg|µg|iu|units?|mg/kg)\b", re.IGNORECASE)
    paths = [DATA_CURATED / f for f in CURATED] + [
        SCHEMA_DIR / "class_overrides.csv", DATA_CURATED / "REVIEW_NOTES.md",
    ]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        hits = dose.findall(text)
        assert not hits, f"{path.name} looks like it contains doses: {hits}"


# ---------------------------------------------------------------------------
# synonyms.csv
# ---------------------------------------------------------------------------


def test_synonyms_structure_and_targets():
    header, rows = _read_csv(SCHEMA_DIR / "synonyms.csv")
    assert header == ["entity_type", "entity_id", "canonical_name", "synonym", "synonym_type"]
    ents = entities()
    exact = Counter()
    for line_no, r in enumerate(rows, start=2):
        where = f"synonyms.csv:{line_no}"
        assert None not in r, f"{where}: extra columns"
        assert r["entity_type"] in {"Drug", "DrugClass", "ClassFamily", "Pathogen", "Mechanism", "Gene"}, where
        assert r["synonym_type"] in SYNONYM_TYPES, where
        assert r["synonym"].strip() == r["synonym"] and r["synonym"], f"{where}: blank or padded"
        if r["entity_type"] == "ClassFamily":
            assert r["entity_id"] in families(), f"{where}: family {r['entity_id']} not used in scope"
        else:
            assert r["entity_type"] in ents, f"{where}: no Gene entities are in scope"
            assert r["entity_id"] in ents[r["entity_type"]], f"{where}: {r['entity_id']} not in scope"
            assert r["canonical_name"] == ents[r["entity_type"]][r["entity_id"]]["name"], where
        if r["synonym_type"] == "canonical":
            assert r["synonym"] == r["canonical_name"], f"{where}: canonical row must repeat the name"
        exact[(r["entity_type"], r["entity_id"], r["synonym"])] += 1
    dupes = [k for k, n in exact.items() if n > 1]
    assert not dupes, f"duplicate synonym rows: {dupes}"


def test_every_entity_has_exactly_one_canonical_synonym():
    _, rows = _read_csv(SCHEMA_DIR / "synonyms.csv")
    canon = Counter((r["entity_type"], r["entity_id"]) for r in rows if r["synonym_type"] == "canonical")
    for label, items in entities().items():
        for ident in items:
            assert canon[(label, ident)] == 1, f"{label} {ident}: {canon[(label, ident)]} canonical rows"


def test_every_drug_and_pathogen_has_an_alias():
    _, rows = _read_csv(SCHEMA_DIR / "synonyms.csv")
    non_canonical = Counter(
        (r["entity_type"], r["entity_id"]) for r in rows if r["synonym_type"] != "canonical"
    )
    for label in ("Drug", "Pathogen", "Mechanism"):
        missing = [i for i in entities()[label] if non_canonical[(label, i)] == 0]
        # cloxacillin has no widely used abbreviation or current brand; allowed.
        missing = [m for m in missing if m != "J01CF02"]
        assert not missing, f"{label} without any synonym: {missing}"


def test_no_synonym_maps_to_two_entities_of_the_same_type():
    _, rows = _read_csv(SCHEMA_DIR / "synonyms.csv")
    targets: dict[tuple[str, str], set[str]] = {}
    for r in rows:
        targets.setdefault((r["entity_type"], norm(r["synonym"])), set()).add(r["entity_id"])
    clashes = {k: v for k, v in targets.items() if len(v) > 1}
    assert not clashes, f"ambiguous synonyms: {clashes}"


def test_no_case_only_duplicates_within_an_entity():
    # Punctuation variants (pip-tazo / pip/tazo) are kept on purpose for the linker's
    # exact-match stage; synonyms that differ only in letter case are redundant.
    _, rows = _read_csv(SCHEMA_DIR / "synonyms.csv")
    seen = Counter((r["entity_type"], r["entity_id"], r["synonym"].lower()) for r in rows)
    dupes = [k for k, n in seen.items() if n > 1]
    assert not dupes, f"synonyms that only differ in case: {dupes}"


def test_every_class_has_a_valid_family():
    for c in scope()["drug_classes"]:
        assert isinstance(c.get("family"), str) and ID_RE["DrugClass"].fullmatch(c["family"]), c
    fams = families()
    assert 10 <= len(fams) <= 20, sorted(fams)
    # The two carbapenem classes share a family; combinations are kept out of it so that
    # "carbapenem resistance" does not exclude meropenem-vaborbactam or imipenem-relebactam.
    assert fams["carbapenem"] == {"carbapenem", "carbapenem-group-1"}
    combos = {"cephalosporin-bli", "carbapenem-bli", "monobactam-bli", "aminopenicillin-bli",
              "aminopenicillin-sulbactam", "antipseudomonal-penicillin-bli", "sulbactam-durlobactam"}
    assert combos <= fams["beta-lactam-bli"]


def test_every_family_has_one_canonical_synonym_and_a_consistent_name():
    _, rows = _read_csv(SCHEMA_DIR / "synonyms.csv")
    fam_rows = [r for r in rows if r["entity_type"] == "ClassFamily"]
    canon = Counter(r["entity_id"] for r in fam_rows if r["synonym_type"] == "canonical")
    for fam in families():
        assert canon[fam] == 1, f"family {fam}: {canon[fam]} canonical rows"
        names = {r["canonical_name"] for r in fam_rows if r["entity_id"] == fam}
        assert len(names) == 1, f"family {fam} has several canonical names: {names}"


def test_family_and_class_synonyms_agree():
    """A string that is both a DrugClass and a ClassFamily synonym must name a class in that family."""
    _, rows = _read_csv(SCHEMA_DIR / "synonyms.csv")
    fam_of = {norm(r["synonym"]): r["entity_id"] for r in rows if r["entity_type"] == "ClassFamily"}
    for r in rows:
        if r["entity_type"] == "DrugClass" and norm(r["synonym"]) in fam_of:
            fam = fam_of[norm(r["synonym"])]
            assert r["entity_id"] in families()[fam], (
                f"{r['synonym']!r}: class {r['entity_id']} is not in family {fam}"
            )


def test_phenotypes_reference_scope():
    header, rows = _read_csv(SCHEMA_DIR / "phenotypes.csv")
    assert header == ["acronym", "pathogen_id", "mechanism_ids", "class_family", "notes"]
    ents, fams = entities(), families()
    pm = {(r["pathogen_id"], r["mechanism_id"]) for r in curated("pathogen_mechanism.csv")}
    keys = Counter((r["acronym"], r["pathogen_id"]) for r in rows)
    assert not [k for k, n in keys.items() if n > 1], "duplicate phenotype rows"
    for r in rows:
        assert None not in r, f"extra columns: {r}"
        assert r["acronym"].strip() == r["acronym"] and r["acronym"]
        assert r["pathogen_id"] in ents["Pathogen"], r
        for mech in filter(None, r["mechanism_ids"].split("|")):
            assert mech in ents["Mechanism"], r
            assert (r["pathogen_id"], mech) in pm, f"{r['acronym']}: {mech} not recorded for pathogen"
        if r["class_family"]:
            assert r["class_family"] in fams, r
    acronyms = {r["acronym"] for r in rows}
    assert {"MRSA", "CRKP", "CRAB", "CRPA", "CRE", "ESBL-E"} <= acronyms


def test_phenotype_acronyms_resolve():
    _, rows = _read_csv(SCHEMA_DIR / "synonyms.csv")
    lookup = {(r["entity_type"], r["synonym"]): r["entity_id"] for r in rows}
    assert lookup[("Pathogen", "MRSA")] == "NCBITaxon:1280"
    assert lookup[("Pathogen", "CRKP")] == "NCBITaxon:573"
    assert lookup[("Pathogen", "CRAB")] == "NCBITaxon:470"
    assert lookup[("Pathogen", "CRPA")] == "NCBITaxon:287"
    assert lookup[("Mechanism", "ESBL")] == "ARO:3000016"
    assert lookup[("Drug", "CZA")] == "J01DD52"


# ---------------------------------------------------------------------------
# Worked example (acceptance test for the graph; REVIEW_NOTES.md section 3)
# ---------------------------------------------------------------------------


def remaining_drugs(pathogen_id: str, mechanism_id: str) -> set[str]:
    """Drug names left after intrinsic, class-level and drug-level exclusions for one mechanism."""
    pm = {(r["pathogen_id"], r["mechanism_id"]) for r in curated("pathogen_mechanism.csv")}
    assert (pathogen_id, mechanism_id) in pm, "mechanism not recorded for this pathogen"
    intrinsic = {r["class_id"] for r in curated("intrinsic_resistance.csv") if r["pathogen_id"] == pathogen_id}
    mech_classes = {r["class_id"] for r in curated("mechanism_class.csv") if r["mechanism_id"] == mechanism_id}
    mech_drugs = {r["drug_id"] for r in curated("mechanism_inactivates_drug.csv") if r["mechanism_id"] == mechanism_id}
    return {
        d["name"]
        for d in scope()["drugs"]
        if d["class_id"] not in intrinsic | mech_classes and d["id"] not in mech_drugs
    }


KP = "NCBITaxon:573"
NON_BETA_LACTAMS_KP = {
    "gentamicin", "amikacin", "tobramycin", "plazomicin",
    "ciprofloxacin", "levofloxacin", "moxifloxacin",
    "colistin", "polymyxin B",
    "doxycycline", "minocycline", "eravacycline", "tigecycline",
    "fosfomycin", "sulfamethoxazole-trimethoprim", "nitrofurantoin",
}
EXPECTED_BETA_LACTAMS = {
    "ARO:3000059": {  # KPC
        "ceftazidime-avibactam", "meropenem-vaborbactam", "imipenem-cilastatin-relebactam",
        "cefiderocol", "aztreonam-avibactam",
    },
    "ARO:3000057": {  # NDM
        "aztreonam", "aztreonam-avibactam", "cefiderocol",
    },
    "ARO:3007721": {  # OXA-48-like
        "ceftazidime-avibactam", "cefiderocol", "aztreonam-avibactam", "aztreonam",
        "cefazolin", "cefuroxime", "ceftriaxone", "cefotaxime", "ceftazidime", "cefepime",
        "ceftaroline fosamil",
    },
}


@pytest.mark.parametrize("mechanism_id", sorted(EXPECTED_BETA_LACTAMS))
def test_worked_example_crkp_by_mechanism(mechanism_id):
    expected = EXPECTED_BETA_LACTAMS[mechanism_id] | NON_BETA_LACTAMS_KP
    assert remaining_drugs(KP, mechanism_id) == expected


def test_worked_example_gives_three_different_answers():
    answers = {m: frozenset(remaining_drugs(KP, m)) for m in EXPECTED_BETA_LACTAMS}
    assert len(set(answers.values())) == 3
    kpc, ndm, oxa = (answers[m] for m in ("ARO:3000059", "ARO:3000057", "ARO:3007721"))
    assert "ceftazidime-avibactam" in kpc and "ceftazidime-avibactam" not in ndm
    assert "meropenem-vaborbactam" in kpc and "meropenem-vaborbactam" not in oxa
    assert "aztreonam" in ndm and "aztreonam" not in kpc
    assert not ({"meropenem", "ertapenem", "imipenem-cilastatin"} & (kpc | ndm | oxa))


# ---------------------------------------------------------------------------
# Cross-check against downloaded sources (skipped when data/raw is not present)
# ---------------------------------------------------------------------------

ARO_OBO = DATA_CURATED.parent / "raw" / "card" / "ontology" / "aro.obo"
AWARE_2025 = DATA_CURATED.parent / "raw" / "aware" / "WHO-AWaRe-classification-2025.xlsx"


@pytest.mark.skipif(not ARO_OBO.exists(), reason="CARD ontology not downloaded")
def test_verified_mechanism_ids_exist_in_card_with_matching_names():
    names: dict[str, str] = {}
    current = None
    for line in ARO_OBO.read_text(encoding="utf-8").splitlines():
        if line.startswith("id: "):
            current = line[4:].strip()
        elif line.startswith("name: ") and current:
            names[current] = line[6:].strip()
            current = None
    for m in scope()["mechanisms"]:
        if not m["id_verified"]:
            continue
        assert m["id"] in names, f"{m['id']} not in CARD ontology"
        card_name = names[m["id"]].lower()
        assert m["name"].lower().startswith(card_name.split(" (")[0][:12]), (
            f"{m['id']}: scope name {m['name']!r} vs CARD {names[m['id']]!r}"
        )


@pytest.mark.skipif(not AWARE_2025.exists(), reason="WHO AWaRe 2025 file not downloaded")
def test_verified_drugs_match_aware_2025():
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.load_workbook(AWARE_2025, read_only=True, data_only=True)
    groups: dict[str, set[str]] = {}
    for sheet in ("Access", "Watch", "Reserve"):
        rows = list(wb[sheet].iter_rows(values_only=True))
        start = next(
            i for i, row in enumerate(rows[:60])
            if "atc code" in [str(c).strip().lower() for c in row if c is not None]
        )
        header = [str(c).strip().lower() if c is not None else "" for c in rows[start]]
        atc_col, cat_col = header.index("atc code"), header.index("category")
        for row in rows[start + 1:]:
            if row[atc_col]:
                groups.setdefault(str(row[atc_col]).strip().upper(), set()).add(str(row[cat_col]).strip())
    for d in scope()["drugs"]:
        if d["id_verified"]:
            assert d["id"] in groups, f"{d['id']} {d['name']} not in AWaRe 2025"
            assert d["aware_group"] in groups[d["id"]], (
                f"{d['name']}: scope {d['aware_group']} vs AWaRe {sorted(groups[d['id']])}"
            )
        else:
            assert d["id"] not in groups, f"{d['name']} is in AWaRe 2025; set id_verified true"


def test_mrsa_keeps_anti_mrsa_agents_and_loses_other_beta_lactams():
    left = remaining_drugs("NCBITaxon:1280", "ARO:3009312")
    for drug in ["vancomycin", "linezolid", "daptomycin", "ceftaroline fosamil", "dalbavancin"]:
        assert drug in left, drug
    for drug in ["flucloxacillin", "cefazolin", "meropenem", "piperacillin-tazobactam",
                 "ceftazidime-avibactam", "aztreonam", "colistin", "cefiderocol"]:
        assert drug not in left, drug

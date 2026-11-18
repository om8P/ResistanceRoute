"""Tests for the hand-curated guideline recommendations (task T08).

Checks data/curated/recommendations_curated.csv against CONTRACTS.md sections 2-4 and
schema/scope.yaml, the page numbers against the guideline PDFs, the paraphrase rules from
the T08 brief, and that every conflict with the curated resistance facts is documented in
data/curated/RECOMMENDATION_NOTES.md.
"""

from __future__ import annotations

import csv
import re
from collections import Counter, defaultdict
from functools import lru_cache

import pytest
import yaml

from pipeline.config import DATA_CURATED, DATA_RAW, SCHEMA_DIR
from pipeline.models import Recommendation

CSV_PATH = DATA_CURATED / "recommendations_curated.csv"
NOTES_PATH = DATA_CURATED / "RECOMMENDATION_NOTES.md"

COLUMNS = [
    "rec_id", "guideline_id", "pathogen_id", "mechanism_id", "drug_ids", "regimen_type", "base_drug_ids",
    "susceptible_only", "infection_site", "line_of_therapy", "patient_group", "text", "caveat",
    "source_section", "source_page",
]
LINES_OF_THERAPY = {"first", "second", "alternative", "last-resort"}
REGIMEN_TYPES = {"single", "combination", "any-of"}

# Guideline id -> (PDF file, page count). The count is checked against the PDF when it is present.
GUIDELINES = {
    "icmr-cr-gram-negative-2022": ("icmr-carbapenem-resistant-gram-negative-2022.pdf", 24),
    "who-aware-book-2022": ("who-aware-antibiotic-book-2022.pdf", 697),
    "icmr-treatment-guidelines-2019": ("icmr-treatment-guidelines-2019.pdf", 206),
}

REC_ID_RE = re.compile(r"REC:([a-z0-9]+(?:-[a-z0-9]+)*-[0-9]{4}):([0-9]{3})")
DRUG_RE = re.compile(r"(?:[A-Z][0-9]{2}[A-Z]{2}[0-9]{2}|LOCAL:drug:[a-z0-9]+(?:-[a-z0-9]+)*)")
# A number followed by a dose, duration or rate unit. Mechanism names such as OXA-48 are allowed.
DOSE_RE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*(?:mg|g|gm|mcg|µg|mu|miu|iu|units?|lakh?s?|lacs?|ml|kg|days?|hours?|hrs?|h|weeks?|q\d+h)\b",
    re.IGNORECASE,
)


@lru_cache(maxsize=None)
def rows() -> list[dict[str, str]]:
    with CSV_PATH.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


@lru_cache(maxsize=None)
def header() -> list[str]:
    with CSV_PATH.open(encoding="utf-8", newline="") as fh:
        return next(csv.reader(fh))


@lru_cache(maxsize=None)
def scope() -> dict:
    with (SCHEMA_DIR / "scope.yaml").open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def scope_ids(key: str) -> set[str]:
    return {item["id"] for item in scope()[key]}


def curated(name: str) -> list[dict[str, str]]:
    with (DATA_CURATED / name).open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def drug_ids(row: dict[str, str]) -> list[str]:
    return row["drug_ids"].split("|")


def mechanism_ids(row: dict[str, str]) -> list[str]:
    """Empty list when no mechanism; several IDs for co-producers (D33)."""
    return row["mechanism_id"].split("|") if row["mechanism_id"] else []


# ---------------------------------------------------------------------------
# Format
# ---------------------------------------------------------------------------

def test_header_matches_contract():
    assert header() == COLUMNS


def test_row_count_in_range():
    assert 40 <= len(rows()) <= 80


def test_no_blank_required_cells():
    for row in rows():
        for col in ("rec_id", "guideline_id", "pathogen_id", "drug_ids", "regimen_type", "line_of_therapy", "text",
                    "source_section", "source_page"):
            assert row[col].strip(), f"{row['rec_id']}: {col} is blank"
        for col, value in row.items():
            assert value == value.strip(), f"{row['rec_id']}: {col} has surrounding whitespace"


def test_rec_ids_unique_and_well_formed():
    ids = [row["rec_id"] for row in rows()]
    dupes = [i for i, n in Counter(ids).items() if n > 1]
    assert not dupes, f"duplicate rec_id: {dupes}"
    for row in rows():
        match = REC_ID_RE.fullmatch(row["rec_id"])
        assert match, f"bad rec_id {row['rec_id']!r}"
        assert match.group(1) == row["guideline_id"], f"{row['rec_id']}: guideline in id differs from guideline_id"


def test_rec_ids_numbered_from_001_without_gaps():
    numbers = defaultdict(list)
    for row in rows():
        guideline, number = REC_ID_RE.fullmatch(row["rec_id"]).groups()
        numbers[guideline].append(int(number))
    for guideline, found in numbers.items():
        assert sorted(found) == list(range(1, len(found) + 1)), guideline


def test_guideline_ids_known():
    assert {row["guideline_id"] for row in rows()} <= set(GUIDELINES)


def test_line_of_therapy_values():
    bad = {row["rec_id"]: row["line_of_therapy"] for row in rows() if row["line_of_therapy"] not in LINES_OF_THERAPY}
    assert not bad


def test_regimen_type_values_and_drug_count():
    for row in rows():
        regimen, n = row["regimen_type"], len(drug_ids(row))
        assert regimen in REGIMEN_TYPES, f"{row['rec_id']}: {regimen!r}"
        if regimen == "single":
            assert n == 1, f"{row['rec_id']}: single regimen with {n} drugs"
        else:
            assert n >= 2, f"{row['rec_id']}: {regimen} regimen with one drug"


def test_ceftazidime_avibactam_plus_aztreonam_rows_are_combinations():
    for row in rows():
        if set(drug_ids(row)) == {"J01DD52", "J01DF01"}:
            assert row["regimen_type"] == "combination", row["rec_id"]


def test_base_drugs_are_a_proper_subset_of_combination_drugs():
    # D40: base_drug_ids only for "base drug plus partners" regimens.
    for row in rows():
        if not row["base_drug_ids"]:
            continue
        base = row["base_drug_ids"].split("|")
        assert row["regimen_type"] == "combination", f"{row['rec_id']}: base drugs on a {row['regimen_type']} row"
        assert len(base) == len(set(base)), f"{row['rec_id']}: repeated base drug"
        assert set(base) < set(drug_ids(row)), f"{row['rec_id']}: base drugs must be a proper subset of drug_ids"


def test_fixed_pairs_have_no_base_drugs():
    for row in rows():
        if set(drug_ids(row)) == {"J01DD52", "J01DF01"}:
            assert not row["base_drug_ids"], row["rec_id"]


def test_susceptible_only_is_boolean():
    bad = {row["rec_id"]: row["susceptible_only"] for row in rows() if row["susceptible_only"] not in {"true", "false"}}
    assert not bad


def test_susceptible_only_rows_are_not_tied_to_a_resistance_mechanism():
    for row in rows():
        if row["susceptible_only"] == "true":
            assert not row["mechanism_id"], f"{row['rec_id']}: susceptible-only row with a mechanism"


def test_rows_validate_as_recommendation_nodes():
    for row in rows():
        Recommendation(
            id=row["rec_id"],
            text=row["text"],
            infection_site=row["infection_site"] or None,
            line_of_therapy=row["line_of_therapy"],
            patient_group=row["patient_group"] or None,
        )


# ---------------------------------------------------------------------------
# IDs in scope
# ---------------------------------------------------------------------------

def test_pathogens_in_scope():
    unknown = {row["pathogen_id"] for row in rows()} - scope_ids("pathogens")
    assert not unknown


def test_mechanisms_in_scope_or_empty():
    for row in rows():
        ids = mechanism_ids(row)
        assert set(ids) <= scope_ids("mechanisms"), f"{row['rec_id']}: {set(ids) - scope_ids('mechanisms')}"
        assert len(ids) == len(set(ids)), f"{row['rec_id']}: repeated mechanism id"


def test_co_producer_rows_carry_both_mechanisms():
    co = [row for row in rows() if len(mechanism_ids(row)) > 1]
    assert co, "expected the ICMR 2022 NDM + OXA-48 co-producer rows"
    for row in co:
        assert set(mechanism_ids(row)) == {"ARO:3000057", "ARO:3007721"}, row["rec_id"]
        assert "co-produc" not in row["patient_group"], f"{row['rec_id']}: old patient_group workaround"


def test_mechanism_recorded_for_pathogen():
    known = {(r["pathogen_id"], r["mechanism_id"]) for r in curated("pathogen_mechanism.csv")}
    missing = [(row["rec_id"], m) for row in rows() for m in mechanism_ids(row)
               if (row["pathogen_id"], m) not in known]
    assert not missing, f"mechanism not recorded for the pathogen in pathogen_mechanism.csv: {missing}"


def test_drugs_in_scope_and_not_repeated():
    in_scope = scope_ids("drugs")
    for row in rows():
        ids = drug_ids(row)
        assert all(DRUG_RE.fullmatch(i) for i in ids), row["rec_id"]
        assert set(ids) <= in_scope, f"{row['rec_id']}: {set(ids) - in_scope}"
        assert len(ids) == len(set(ids)), f"{row['rec_id']}: repeated drug id"


# ---------------------------------------------------------------------------
# Pages and paraphrases
# ---------------------------------------------------------------------------

def test_source_page_is_a_positive_integer_within_known_page_count():
    for row in rows():
        assert row["source_page"].isdigit(), row["rec_id"]
        page = int(row["source_page"])
        assert 1 <= page <= GUIDELINES[row["guideline_id"]][1], row["rec_id"]


@pytest.mark.parametrize("guideline_id", sorted(GUIDELINES))
def test_page_counts_match_pdfs(guideline_id):
    pypdf = pytest.importorskip("pypdf")
    filename, expected = GUIDELINES[guideline_id]
    path = DATA_RAW / "guidelines" / filename
    if not path.exists():
        pytest.skip(f"{path} not downloaded")
    assert len(pypdf.PdfReader(str(path)).pages) == expected


def test_paraphrases_at_most_40_words():
    long = {row["rec_id"]: len(row["text"].split()) for row in rows() if len(row["text"].split()) > 40}
    assert not long


def test_paraphrases_contain_no_doses_or_durations():
    hits = {row["rec_id"]: DOSE_RE.findall(row["text"]) for row in rows() if DOSE_RE.search(row["text"])}
    assert not hits


# ---------------------------------------------------------------------------
# Coverage (T08 brief)
# ---------------------------------------------------------------------------

def test_all_five_pathogens_covered():
    assert {row["pathogen_id"] for row in rows()} == scope_ids("pathogens")


def test_at_least_15_rows_tied_to_a_carbapenemase():
    carbapenemases = {m["id"] for m in scope()["mechanisms"] if m["type"] == "carbapenemase"}
    assert sum(bool(set(mechanism_ids(row)) & carbapenemases) for row in rows()) >= 15


def test_every_guideline_contributes():
    assert {row["guideline_id"] for row in rows()} == set(GUIDELINES)


# ---------------------------------------------------------------------------
# Consistency with the curated resistance facts (T03 exclusion rule)
# ---------------------------------------------------------------------------

def excluded_drugs(pathogen_id: str, *mechanism_ids_: str) -> set[str]:
    """Drugs excluded by intrinsic resistance, class-level resistance or drug-level inactivation.

    With several mechanisms (co-producers) the exclusions are their union (T03 handoff).
    """
    mechs = set(mechanism_ids_)
    classes = {r["class_id"] for r in curated("intrinsic_resistance.csv") if r["pathogen_id"] == pathogen_id}
    classes |= {r["class_id"] for r in curated("mechanism_class.csv") if r["mechanism_id"] in mechs}
    drugs = {d["id"] for d in scope()["drugs"] if d["class_id"] in classes}
    drugs |= {r["drug_id"] for r in curated("mechanism_inactivates_drug.csv") if r["mechanism_id"] in mechs}
    return drugs


def conflicts() -> dict[str, set[str]]:
    found = {}
    for row in rows():
        if row["mechanism_id"]:
            hit = set(drug_ids(row)) & excluded_drugs(row["pathogen_id"], *mechanism_ids(row))
            if hit:
                found[row["rec_id"]] = hit
    return found


def test_exclusion_rule_reproduces_known_case():
    # REVIEW_NOTES.md section 3: NDM inactivates ceftazidime-avibactam but spares aztreonam.
    ndm_kp = excluded_drugs("NCBITaxon:573", "ARO:3000057")
    assert "J01DD52" in ndm_kp and "J01DF01" not in ndm_kp


def test_every_conflict_is_documented_in_notes():
    notes = NOTES_PATH.read_text(encoding="utf-8")
    undocumented = sorted(rec_id for rec_id in conflicts() if rec_id not in notes)
    assert not undocumented, f"conflicting rows missing from RECOMMENDATION_NOTES.md: {undocumented}"


def test_documented_conflict_count_matches():
    notes = NOTES_PATH.read_text(encoding="utf-8")
    match = re.search(r"Conflicts found:\s*(\d+) rows, (\d+) drug-level conflicts", notes)
    assert match, "RECOMMENDATION_NOTES.md must state 'Conflicts found: <n> rows, <m> drug-level conflicts'"
    found = conflicts()
    assert int(match.group(1)) == len(found)
    assert int(match.group(2)) == sum(len(v) for v in found.values())


def test_caveat_on_every_conflict_row_and_nowhere_else():
    # D34/D40: the CSV is the source of the caveat; conflict rows need one, other rows leave it empty.
    found = conflicts()
    for row in rows():
        caveat = row["caveat"]
        if row["rec_id"] in found:
            assert caveat, f"{row['rec_id']}: conflict row without a caveat"
            assert caveat.endswith(".") and len(caveat.split()) <= 30, f"{row['rec_id']}: caveat should be one short sentence"
            assert not DOSE_RE.search(caveat), row["rec_id"]
        else:
            assert not caveat, f"{row['rec_id']}: caveat on a row without a conflict"


def test_notes_caveat_table_matches_csv():
    notes = NOTES_PATH.read_text(encoding="utf-8")
    section = notes.split("### 3.3")[1].split("### 3.4")[0]
    table = {}
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 2 and REC_ID_RE.fullmatch(cells[0]):
            table[cells[0]] = cells[1]
    assert table == {row["rec_id"]: row["caveat"] for row in rows() if row["caveat"]}

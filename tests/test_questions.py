"""Checks for the evaluation question set (task T09): eval/questions.json.

The file is hand-written before any retrieval code exists (DECISIONS.md D16). These tests
check its structure, the question mix the T09 brief requires, that every ID exists in
schema/scope.yaml, and that every gold answer cites a source that can be located.
"""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from itertools import combinations
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS_PATH = ROOT / "eval" / "questions.json"
SCOPE_PATH = ROOT / "schema" / "scope.yaml"
SYNONYMS_PATH = ROOT / "schema" / "synonyms.csv"

FIELDS = {
    "id", "question", "intent", "hops", "entities",
    "answer_type", "gold", "gold_source", "notes",
}
INTENTS = {
    "alternatives", "why_restricted", "mechanism_lookup",
    "recommendation_lookup", "drug_profile", "surveillance",
}
ANSWER_TYPES = {"drug_set", "class_set", "mechanism_set", "fact", "number", "decline"}
SET_TYPES = {"drug_set": "drugs", "class_set": "drug_classes", "mechanism_set": "mechanisms"}

# The six mechanisms the brief names for mechanism-dependent questions.
KEY_MECHANISMS = {
    "ARO:3000059",  # KPC
    "ARO:3000057",  # NDM
    "ARO:3007721",  # OXA-48-like
    "ARO:3000021",  # VIM
    "ARO:3007710",  # OXA-23-like
    "ARO:3009312",  # mecA / PBP2a
}

# PDF page counts from the T02 handoff; sources cite PDF pages, not printed pages.
GUIDELINE_PAGES = {
    "who-aware-book-2022": 697,
    "icmr-treatment-guidelines-2019": 206,
    "icmr-cr-gram-negative-2022": 24,
}
GUIDELINE_RE = re.compile(r"^(?P<doc>[a-z0-9-]+) p(?P<page>\d+)$")
CURATED_RE = re.compile(
    r"^curated-seed (?P<file>\S+) lines? (?P<lines>\d+(?:-\d+)?(?:, \d+(?:-\d+)?)*)$"
)
AWARE_RE = re.compile(r"^who-aware-2025 sheet 'AWaRe classification 2025' row (?P<row>\d+)$")
GLASS_RE = re.compile(r"^glass \S")
AWARE_2025_ROWS = 268 + 4  # data rows plus the four lines above them

# A number followed by a dosing unit, or a dosing interval such as q8h.
DOSE_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:mg|g|mcg|ug|iu|mu|units?|million units|lakh|lacs|laks)\b"
    r"(?:\s*/\s*(?:kg|day|dose))?|\bq\s?\d+\s?h\b",
    re.IGNORECASE,
)


@pytest.fixture(scope="module")
def questions() -> list[dict]:
    with QUESTIONS_PATH.open(encoding="utf-8") as fh:
        data = json.load(fh)
    assert isinstance(data, list)
    return data


@pytest.fixture(scope="module")
def scope() -> dict[str, set[str]]:
    with SCOPE_PATH.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return {key: {item["id"] for item in raw[key]} for key in
            ("pathogens", "mechanisms", "drug_classes", "drugs")}


@pytest.fixture(scope="module")
def all_scope_ids(scope) -> set[str]:
    return set().union(*scope.values())


# --- IDs and fields -------------------------------------------------------------------


def test_forty_unique_ids_in_order(questions):
    ids = [q["id"] for q in questions]
    assert ids == [f"Q{n:02d}" for n in range(1, 41)]


KEYWORD_FIELDS = {"gold_keywords", "gold_keywords_any"}
TEXT_ANSWERS = {"fact", "decline"}


def test_every_question_has_exactly_the_contract_fields(questions):
    for q in questions:
        allowed = FIELDS | KEYWORD_FIELDS if q["answer_type"] in TEXT_ANSWERS else FIELDS
        assert FIELDS <= set(q) <= allowed, q["id"]


def test_field_values_are_valid(questions):
    for q in questions:
        qid = q["id"]
        assert isinstance(q["question"], str) and q["question"].strip(), qid
        assert q["intent"] in INTENTS | {"decline"}, qid
        assert q["hops"] in {"single", "multi"}, qid
        assert q["answer_type"] in ANSWER_TYPES, qid
        assert isinstance(q["entities"], list), qid
        assert len(set(q["entities"])) == len(q["entities"]), f"{qid}: duplicate entity"
        assert isinstance(q["notes"], str), qid


def test_questions_are_unique(questions):
    texts = [q["question"].strip().lower() for q in questions]
    assert len(set(texts)) == len(texts)


def test_decline_intent_matches_decline_answer(questions):
    for q in questions:
        assert (q["intent"] == "decline") == (q["answer_type"] == "decline"), q["id"]


# --- Required counts ------------------------------------------------------------------


def test_twenty_single_and_twenty_multi_hop(questions):
    hops = Counter(q["hops"] for q in questions)
    assert hops == {"single": 20, "multi": 20}


def test_intent_counts(questions):
    intents = Counter(q["intent"] for q in questions)
    for intent in INTENTS:
        assert intents[intent] >= 4, intent
    assert intents["alternatives"] >= 8
    assert intents["why_restricted"] >= 8
    assert intents["decline"] == 4


def _mechanism_dependent(q: dict) -> bool:
    return q["hops"] == "multi" and bool(KEY_MECHANISMS & set(q["entities"]))


def test_at_least_six_mechanism_dependent_multi_hop(questions):
    assert sum(_mechanism_dependent(q) for q in questions) >= 6


def test_mechanism_dependent_questions_cover_all_six_mechanisms(questions):
    covered = set()
    for q in questions:
        if _mechanism_dependent(q):
            covered |= KEY_MECHANISMS & set(q["entities"])
    assert covered == KEY_MECHANISMS, KEY_MECHANISMS - covered


def test_a_pair_differs_only_in_the_mechanism(questions):
    """Same intent and answer type, same non-mechanism entities, different mechanism,
    identical wording apart from the mechanism name, and different gold answers."""
    names = {"ARO:3000059": "KPC", "ARO:3000057": "NDM", "ARO:3007721": "OXA-48",
             "ARO:3000021": "VIM", "ARO:3007710": "OXA-23", "ARO:3009312": "MRSA"}
    pairs = []
    for a, b in combinations([q for q in questions if _mechanism_dependent(q)], 2):
        if (a["intent"], a["answer_type"]) != (b["intent"], b["answer_type"]):
            continue
        mech_a = KEY_MECHANISMS & set(a["entities"])
        mech_b = KEY_MECHANISMS & set(b["entities"])
        if mech_a == mech_b or len(mech_a) != 1 or len(mech_b) != 1:
            continue
        if set(a["entities"]) - mech_a != set(b["entities"]) - mech_b:
            continue
        text_a = a["question"].replace(names[next(iter(mech_a))], "<M>")
        text_b = b["question"].replace(names[next(iter(mech_b))], "<M>")
        if text_a == text_b and a["gold"] != b["gold"]:
            pairs.append((a["id"], b["id"]))
    assert pairs, "no question pair differs only in the mechanism"


# --- IDs exist in scope.yaml ----------------------------------------------------------


def test_every_entity_exists_in_scope(questions, all_scope_ids):
    for q in questions:
        unknown = set(q["entities"]) - all_scope_ids
        assert not unknown, f"{q['id']}: {unknown}"


def test_non_decline_questions_name_at_least_one_entity(questions):
    for q in questions:
        if q["intent"] != "decline":
            assert q["entities"], q["id"]


def test_set_gold_ids_exist_in_the_matching_scope_section(questions, scope):
    for q in questions:
        section = SET_TYPES.get(q["answer_type"])
        if section is None:
            continue
        gold = q["gold"]
        assert isinstance(gold, list) and gold, q["id"]
        assert len(set(gold)) == len(gold), f"{q['id']}: duplicate gold id"
        unknown = set(gold) - scope[section]
        assert not unknown, f"{q['id']}: {unknown} not in scope.yaml {section}"


def test_text_gold_is_a_statement(questions):
    for q in questions:
        if q["answer_type"] in {"fact", "decline"}:
            assert isinstance(q["gold"], str) and len(q["gold"]) >= 20, q["id"]


def test_number_gold_has_value_year_and_country(questions):
    for q in questions:
        if q["answer_type"] != "number":
            continue
        gold = q["gold"]
        assert set(gold) == {"value", "unit", "year", "country"}, q["id"]
        assert isinstance(gold["value"], (int, float)) and 0 <= gold["value"] <= 100, q["id"]
        assert isinstance(gold["year"], int) and 2016 <= gold["year"] <= 2023, q["id"]
        assert re.fullmatch(r"[A-Z]{3}", gold["country"]), q["id"]


# --- Keywords for fact and decline answers (orchestrator ruling on T09) ----------------


def _is_keyword(item, all_scope_ids) -> bool:
    if not isinstance(item, str) or not item.strip():
        return False
    if item in all_scope_ids:
        return True
    return item == item.lower() and len(item) <= 40


def test_text_answers_have_keywords(questions, all_scope_ids):
    for q in questions:
        if q["answer_type"] not in TEXT_ANSWERS:
            continue
        qid = q["id"]
        assert "gold_keywords" in q, f"{qid}: no gold_keywords"
        required = q["gold_keywords"]
        groups = q.get("gold_keywords_any", [])
        assert isinstance(required, list) and isinstance(groups, list), qid
        assert required or groups, f"{qid}: no keyword at all"
        for item in required:
            assert _is_keyword(item, all_scope_ids), f"{qid}: bad keyword {item!r}"
        for group in groups:
            assert isinstance(group, list) and len(group) >= 2, f"{qid}: bad group {group!r}"
            for item in group:
                assert _is_keyword(item, all_scope_ids), f"{qid}: bad keyword {item!r}"


def test_keyword_ids_exist_in_scope(questions, all_scope_ids):
    id_like = re.compile(r"^(J01|NCBITaxon:|ARO:|LOCAL:)")
    for q in questions:
        items = list(q.get("gold_keywords", []))
        for group in q.get("gold_keywords_any", []):
            items += group
        for item in items:
            if id_like.match(item):
                assert item in all_scope_ids, f"{q['id']}: {item} not in scope.yaml"


def test_gold_statement_satisfies_its_own_keywords(questions, all_scope_ids):
    """The gold text must pass its own keyword check, so the keywords are not stricter
    than the answer they stand for."""
    for q in questions:
        if q["answer_type"] not in TEXT_ANSWERS:
            continue
        text = q["gold"].lower()
        for item in q["gold_keywords"]:
            if item not in all_scope_ids:
                assert item in text, f"{q['id']}: {item!r} not in gold"
        for group in q.get("gold_keywords_any", []):
            phrases = [i for i in group if i not in all_scope_ids]
            assert any(p in text for p in phrases), f"{q['id']}: no {group} in gold"


# --- Sources --------------------------------------------------------------------------


def _check_curated_source(qid: str, match: re.Match) -> None:
    path = ROOT / match["file"]
    assert path.is_file(), f"{qid}: {match['file']} does not exist"
    n_lines = len(path.read_text(encoding="utf-8").splitlines())
    for part in match["lines"].split(", "):
        for line in part.split("-"):
            assert 1 <= int(line) <= n_lines, f"{qid}: {match['file']} has no line {line}"


def test_every_answer_has_a_locatable_source(questions):
    for q in questions:
        qid = q["id"]
        sources = q["gold_source"]
        assert isinstance(sources, list) and sources, f"{qid}: no gold_source"
        for src in sources:
            if m := GUIDELINE_RE.match(src):
                assert m["doc"] in GUIDELINE_PAGES, f"{qid}: unknown guideline {m['doc']}"
                assert 1 <= int(m["page"]) <= GUIDELINE_PAGES[m["doc"]], f"{qid}: {src}"
            elif m := CURATED_RE.match(src):
                _check_curated_source(qid, m)
            elif m := AWARE_RE.match(src):
                assert 5 <= int(m["row"]) <= AWARE_2025_ROWS, f"{qid}: {src}"
            else:
                assert GLASS_RE.match(src), f"{qid}: unrecognised source {src!r}"


def test_surveillance_answers_cite_glass(questions):
    for q in questions:
        if q["intent"] == "surveillance":
            assert any(s.startswith("glass ") for s in q["gold_source"]), q["id"]


def test_no_doses_in_gold_or_notes(questions):
    for q in questions:
        text = json.dumps(q["gold"]) + " " + q["notes"]
        hit = DOSE_RE.search(text)
        assert not hit, f"{q['id']}: {hit.group(0) if hit else ''!r}"


# --- Realistic wording ----------------------------------------------------------------


@pytest.fixture(scope="module")
def synonyms() -> dict[str, set[str]]:
    by_type: dict[str, set[str]] = {}
    with SYNONYMS_PATH.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            by_type.setdefault(row["synonym_type"], set()).add(row["synonym"])
    return by_type


def _count_containing(questions, terms, case_sensitive):
    count = 0
    for q in questions:
        text = q["question"] if case_sensitive else q["question"].lower()
        for term in terms:
            needle = term if case_sensitive else term.lower()
            if re.search(rf"(?<![A-Za-z0-9]){re.escape(needle)}(?![A-Za-z0-9])", text):
                count += 1
                break
    return count


def test_wording_uses_abbreviations_and_brands(questions, synonyms):
    assert _count_containing(questions, synonyms["abbreviation"], case_sensitive=True) >= 8
    assert _count_containing(questions, synonyms["brand"], case_sensitive=False) >= 3


def test_wording_includes_lower_case_misspellings_and_class_families(questions):
    assert sum(q["question"][0].islower() for q in questions) >= 5
    misspellings = ("baumanii", "klebsiela")
    assert sum(any(m in q["question"].lower() for m in misspellings) for q in questions) >= 2
    assert any("carbapenems" in q["question"].lower() for q in questions)

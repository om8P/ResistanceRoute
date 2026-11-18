"""Tests for the entity linker (pipeline/link.py, task T07)."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from pipeline.config import EVAL_DIR
from pipeline.link import EntityLinker, evaluate_gold, run_corpus


@pytest.fixture(scope="module")
def linker() -> EntityLinker:
    return EntityLinker()


def ids(linker: EntityLinker, text: str) -> list[str]:
    return [m.entity_id for m in linker.link(text)]


# ---------------------------------------------------------------- case-sensitive abbreviations


def test_abbreviation_matches_only_in_its_own_case(linker):
    assert ids(linker, "MEM was given") == ["J01DH02"]
    assert ids(linker, "mem was given") == []
    assert ids(linker, "The Mem tool") == []


def test_non_abbreviation_synonyms_ignore_case(linker):
    for text in ("meropenem", "Meropenem", "MEROPENEM", "Merrem", "MERREM"):
        assert ids(linker, text) == ["J01DH02"], text


def test_lowercase_acronym_is_not_linked(linker):
    assert ids(linker, "mrsa and crkp") == []
    assert linker.resolve("mrsa") is None


def test_drug_codes_are_not_pluralised_or_respaced(linker):
    # "CROs" are contract research organisations, "C-T" is a DNA substitution
    assert ids(linker, "CROs ran the trial; a C-T transition") == []
    assert ids(linker, "C/T was used") == ["J01DI54"]


def test_acronym_plural(linker):
    m = linker.link("ESBLs and MRSAs")
    assert [x.entity_id for x in m] == ["ARO:3000016", "NCBITaxon:1280"]


# ---------------------------------------------------------------- combinations


@pytest.mark.parametrize(
    "surface",
    [
        "ceftazidime-avibactam",
        "ceftazidime/avibactam",
        "ceftazidime + avibactam",
        "ceftazidime+avibactam",
        "Ceftazidime–avibactam",  # en dash
        "CZA",
        "CAZ-AVI",
        "CAZ/AVI",
    ],
)
def test_combination_links_once_as_the_combination(linker, surface):
    mentions = linker.link(f"Give {surface} now.")
    assert [m.entity_id for m in mentions] == ["J01DD52"]
    assert mentions[0].surface == surface


def test_combination_is_never_also_a_single_drug(linker):
    for text in ("ceftazidime-avibactam", "piperacillin/tazobactam", "imipenem-cilastatin-relebactam",
                 "meropenem + vaborbactam", "aztreonam-avibactam"):
        got = ids(linker, text)
        assert len(got) == 1, (text, got)
    assert "J01DD02" not in ids(linker, "ceftazidime-avibactam")  # ceftazidime
    assert "J01DF01" not in ids(linker, "aztreonam + avibactam")  # aztreonam


def test_two_separate_drugs_stay_two(linker):
    assert ids(linker, "meropenem plus colistin") == ["J01DH02", "J01XB01"]
    assert ids(linker, "ceftazidime-avibactam plus aztreonam") == ["J01DD52", "J01DF01"]


# ---------------------------------------------------------------- phenotypes


def test_mrsa_returns_pathogen_and_mechanism(linker):
    ent = linker.resolve("MRSA")
    assert ent.entity_id == "NCBITaxon:1280" and ent.entity_type == "Pathogen"
    assert ent.phenotype == "MRSA"
    assert ent.mechanism_ids == ["ARO:3009312"]
    assert ent.class_family == ""


def test_crkp_returns_pathogen_and_class_family(linker):
    (m,) = linker.link("CRKP outbreak")
    assert m.entity_id == "NCBITaxon:573"
    assert m.class_family == "carbapenem"
    assert m.mechanism_ids == []
    assert m.to_row()["class_family"] == "carbapenem"


def test_kpc_kp_and_crab(linker):
    assert linker.resolve("KPC-Kp").mechanism_ids == ["ARO:3000059"]
    crab = linker.resolve("CRAB")
    assert (crab.entity_id, crab.class_family) == ("NCBITaxon:470", "carbapenem")


def test_acronym_missing_from_synonyms_comes_from_phenotypes(linker):
    ent = linker.resolve("ESBL-EC")
    assert ent.entity_id == "NCBITaxon:562" and ent.mechanism_ids == ["ARO:3000016"]


def test_phenotype_across_species_is_flagged_ambiguous(linker):
    cre = linker.resolve("CRE")
    assert cre.pathogen_ids == ["NCBITaxon:573", "NCBITaxon:562"]
    assert cre.ambiguous_pathogen


def test_plain_pathogen_has_no_phenotype_fields(linker):
    row = linker.link("Klebsiella pneumoniae")[0].to_row()
    assert "phenotype" not in row and row["entity_id"] == "NCBITaxon:573"


# ---------------------------------------------------------------- resolve and match types


def test_match_types_and_scores(linker):
    assert linker.resolve("meropenem").match_type == "exact"
    assert linker.resolve("Meropenem").match_type == "normalised"
    assert linker.resolve("Pip tazo").match_type == "normalised"
    fz = linker.resolve("meropnem")
    assert (fz.entity_id, fz.match_type) == ("J01DH02", "fuzzy")
    assert linker.resolve("meropenem").score > linker.resolve("Meropenem").score > fz.score


def test_normalisation_covers_hyphens_greek_plurals(linker):
    assert linker.resolve("Carbapenems").entity_id == "carbapenem"
    assert linker.resolve("New Delhi metallo-beta-lactamase").entity_id == "ARO:3000057"
    assert linker.resolve("New Delhi metallo β lactamase").entity_id == "ARO:3000057"
    assert linker.resolve("amoxicillin clavulanate").entity_id == "J01CR02"
    assert linker.resolve("K.pneumoniae").entity_id == "NCBITaxon:573"


def test_class_family_preferred_over_drug_class(linker):
    ent = linker.resolve("carbapenems")
    assert ent.entity_type == "ClassFamily" and ent.entity_id == "carbapenem"
    assert ("DrugClass", "carbapenem") in ent.alternatives
    assert linker.resolve("carbapenems", entity_type="DrugClass").entity_type == "DrugClass"
    # a class that is not also a family name stays a DrugClass
    assert linker.resolve("third-generation cephalosporins").entity_type == "DrugClass"


def test_resolve_entity_type_filter(linker):
    assert linker.resolve("KPC", entity_type="Drug") is None
    assert linker.resolve("KPC", entity_type="Mechanism").entity_id == "ARO:3000059"


# ---------------------------------------------------------------- fuzzy matching


@pytest.mark.parametrize(
    "typo, expected",
    [
        ("vancomicin", "J01XA01"),
        ("ceftriaxon", "J01DD04"),
        ("meropnem", "J01DH02"),
        ("amoxicilin", "J01CA04"),
        ("Klebsiela pneumoniae", "NCBITaxon:573"),
        ("Pseudomonas aeruginsa", "NCBITaxon:287"),
        ("ciprofloxacine", "J01MA02"),
    ],
)
def test_fuzzy_links_typos(linker, typo, expected):
    mentions = linker.link(f"The isolate was {typo} resistant")
    hit = [m for m in mentions if m.surface == typo]
    assert [m.entity_id for m in hit] == [expected]
    assert hit[0].match_type == "fuzzy" and 0.85 <= hit[0].score <= 0.95


def test_fuzzy_never_applies_to_abbreviations_or_short_strings(linker):
    assert linker.resolve("MEN") is None
    assert linker.resolve("KPD") is None
    assert linker.resolve("NDN") is None
    assert linker.resolve("amp") is None  # lower-case abbreviation, and under 5 characters


def test_fuzzy_respects_digits(linker):
    assert linker.resolve("OXA-999") is None


# ---------------------------------------------------------------- no false links


COMMON_WORDS = (
    "the patient was discharged home after a five day course of therapy with dosage adjustments "
    "resistance mechanisms guidelines gentle handling minimal inhibitory concentration colitis "
    "diarrhoea cephalexin cefoxitin azithromycin infection control hospital clinical outcomes "
    "sensitive susceptible intermediate breakpoint treatment prophylaxis combination monotherapy "
    "antibiotic antimicrobial stewardship bacteraemia pneumonia endocarditis cystitis meningitis "
    "organism isolate culture specimen sample laboratory surveillance prevalence incidence "
    "tetracyclic quinine penicillamine vancouver colorado monocycle minute "
    "colony resistant tolerance cephalic carbonate"
)


def test_common_words_are_not_linked(linker):
    assert [(m.surface, m.entity_id) for m in linker.link(COMMON_WORDS)] == []


def test_each_common_word_alone_is_not_linked(linker):
    for word in set(COMMON_WORDS.split()):
        assert linker.resolve(word) is None, word


def test_out_of_scope_species_are_not_linked_as_in_scope_genus(linker):
    assert ids(linker, "Klebsiella oxytoca and Pseudomonas putida") == []
    assert ids(linker, "Acinetobacter lwoffii") == []
    assert ids(linker, "Klebsiella infections") == ["NCBITaxon:573"]


def test_sentence_final_period_does_not_hide_a_mention(linker):
    assert ids(linker, "The gene was mecA.") == ["ARO:3009312"]
    assert ids(linker, "Isolated K. pneumoniae.") == ["NCBITaxon:573"]
    assert ids(linker, "K. pneumoniae grew.") == ["NCBITaxon:573"]
    assert [m.surface for m in linker.link("It was E. coli. Then more")] == ["E. coli"]


def test_offsets_index_the_original_text(linker):
    text = "Use β-lactamase inhibitor – and ceftazidime–avibactam, not MEM."
    mentions = linker.link(text)
    assert mentions
    for m in mentions:
        assert text[m.start:m.end] == m.surface


def test_numbered_alleles_link_to_their_family(linker):
    for surface, aro in (("blaNDM-9", "ARO:3000057"), ("KPC-14", "ARO:3000059"),
                         ("CTX-M-27", "ARO:3000016"), ("mcr-5", "ARO:3004268"),
                         ("blaVIM-4", "ARO:3000021")):
        (m,) = linker.link(f"We found {surface} in the isolate.")
        assert (m.surface, m.entity_id, m.match_type) == (surface, aro, "normalised"), surface
    # the OXA number decides the family, so an unlisted OXA allele is not guessed
    assert ids(linker, "OXA-58 and OXA-51") == []
    assert ids(linker, "OXA-181") == ["ARO:3007721"]


def test_spacing_variants_of_a_synonym_are_normalised_matches(linker):
    for surface, aro in (("OXA48", "ARO:3007721"), ("KPC2", "ARO:3000059"), ("NDM1", "ARO:3000057")):
        (m,) = linker.link(f"{surface} positive")
        assert (m.entity_id, m.match_type) == (aro, "normalised"), surface


def test_fuzzy_does_not_link_inflections_or_neighbouring_words(linker):
    # real false positives seen on PubMed abstracts before the guards were added
    text = ("methicillin-resistant isolates; ceftazidime. A new β-lactamase; "
            "Cefotaximases and C β-lactamases; Staphylococcus are common")
    assert [(m.surface, m.entity_id) for m in linker.link(text)] == [("ceftazidime", "J01DD02")]


# ---------------------------------------------------------------- longest match


def test_longest_match_wins(linker):
    (m,) = linker.link("carbapenem-resistant Klebsiella pneumoniae")
    assert m.surface == "carbapenem-resistant Klebsiella pneumoniae"
    (m,) = linker.link("OXA-48-like carbapenemase")
    assert m.entity_id == "ARO:3007721" and m.surface == "OXA-48-like carbapenemase"
    (m,) = linker.link("AmpC overproduction")
    assert m.entity_id == "ARO:3000098"


# ---------------------------------------------------------------- corpus run and gold


def test_corpus_run_writes_contract_files(tmp_path: Path, linker):
    passages = [
        {"id": "doc:sec:1",
         "text": "MRSA treated with vancomycin. Vancocin again; Carbapenems and carbapenem. "
                 "Also blaOXA-1 and cefoxitin.",
         "source_doc": "doc", "section": "sec", "page": 1, "n_words": 14},
        {"id": "doc:sec:2", "text": "CRE and ESBL-E were seen with meropenem (MEM) and meropnem.",
         "source_doc": "doc", "section": "sec", "page": 1, "n_words": 12},
    ]
    src = tmp_path / "passages.jsonl"
    src.write_text("\n".join(json.dumps(p) for p in passages), encoding="utf-8")
    counts = run_corpus(src, tmp_path, linker)
    assert counts["passages"] == 2

    def read_jsonl(name):
        return [json.loads(x) for x in (tmp_path / name).read_text(encoding="utf-8").splitlines()]

    linked, mentions = read_jsonl("mentions_linked.jsonl"), read_jsonl("mentions.jsonl")
    assert {"passage_id", "start", "end", "surface", "entity_type", "entity_id", "match_type",
            "score"} <= set(linked[0])
    assert all({"passage_id", "start", "end", "surface", "entity_type"} <= set(m) for m in mentions)
    assert len(mentions) > len(linked)  # unlinked candidates are in mentions.jsonl only
    assert any(m["entity_type"] == "ClassFamily" for m in linked)

    with (tmp_path / "edges_MENTIONS.csv").open(encoding="utf-8", newline="") as fh:
        edges = list(csv.DictReader(fh))
    assert list(edges[0]) == ["start_id", "start_label", "end_id", "end_label", "source_id", "method",
                              "confidence", "evidence_passage_id"]
    pairs = [(e["start_id"], e["end_id"]) for e in edges]
    assert len(pairs) == len(set(pairs)), "one edge per passage-entity pair"
    assert not any(e["end_label"] in ("ClassFamily", "Gene") for e in edges)
    assert all(e["start_label"] == "Passage" and e["source_id"] == "curated-seed" and e["method"] == "rule"
               for e in edges)
    van = [e for e in edges if e["end_id"] == "J01XA01"]
    assert len(van) == 1 and float(van[0]["confidence"]) == 1.0  # vancomycin + Vancocin: one edge
    mem = [e for e in edges if e["end_id"] == "J01DH02"]
    assert len(mem) == 1 and float(mem[0]["confidence"]) == 1.0  # exact beats the fuzzy "meropnem"
    # CRE and ESBL-E span two species, so they give no pathogen edge
    assert not any(e["start_id"] == "doc:sec:2" and e["end_label"] == "Pathogen" for e in edges)

    with (tmp_path / "unlinked.csv").open(encoding="utf-8", newline="") as fh:
        unl = list(csv.DictReader(fh))
    assert list(unl[0]) == ["surface", "entity_type", "count", "example_passage_id"]
    assert {u["surface"] for u in unl} >= {"cefoxitin", "blaOXA-1"}


def test_gold_file_scores():
    res = evaluate_gold(EVAL_DIR / "linking_gold.csv")
    assert res["gold_mentions"] >= 100
    assert res["precision"] >= 0.95 and res["recall"] >= 0.95 and res["accuracy"] >= 0.95, res["errors"]

"""Tests for retrieval/parser.py and retrieval/types.py (task T12).

The questions below were written for this file and were not taken from eval/questions.json
(the evaluation set stays independent of the system, D16).
"""

from __future__ import annotations

import dataclasses

import pytest

from retrieval.parser import INTENT_RULES, explain, extract_country, extract_year, get_linker, parse
from retrieval.types import INTENTS, Answer, GraphResult, ParsedQuery, PassageHit, Path

KP, EC, AB, PA, SA = (
    "NCBITaxon:573", "NCBITaxon:562", "NCBITaxon:470", "NCBITaxon:287", "NCBITaxon:1280",
)
KPC, NDM, OXA48, ESBL, MECA, MCR = (
    "ARO:3000059", "ARO:3000057", "ARO:3007721", "ARO:3000016", "ARO:3009312", "ARO:3004268",
)
COLISTIN, MEROPENEM, CEFIDEROCOL, VANCOMYCIN, CZA, TIGECYCLINE = (
    "J01XB01", "J01DH02", "J01DI04", "J01XA01", "J01DD52", "J01AA12",
)


# --------------------------------------------------------------------------------------
# Types
# --------------------------------------------------------------------------------------

def test_types_have_defaults_and_contract_fields():
    pq = ParsedQuery()
    assert pq.intent == "unknown" and pq.country is None and pq.year is None
    assert pq.pathogen_ids == [] and pq.mentions == []
    names = {f.name for f in dataclasses.fields(ParsedQuery)}
    assert names == {
        "question", "intent", "pathogen_ids", "mechanism_ids", "drug_ids", "class_ids",
        "class_families", "country", "year", "infection_site", "decline_reason", "mentions",
    }
    assert {f.name for f in dataclasses.fields(Answer)} == {
        "id", "label", "name", "group", "aware_group", "recommendation_ids", "caveats", "score",
    }
    assert {f.name for f in dataclasses.fields(GraphResult)} == {
        "answers", "paths", "entity_ids", "cypher", "empty_reason",
    }
    assert {f.name for f in dataclasses.fields(PassageHit)} == {
        "passage_id", "score", "rank", "text", "source_doc", "section", "page",
    }
    assert Path().steps == []


def test_list_defaults_are_not_shared():
    a, b = ParsedQuery(), ParsedQuery()
    a.pathogen_ids.append("x")
    assert b.pathogen_ids == []


def test_intents_constant_matches_contract():
    assert set(INTENTS) == {
        "alternatives", "why_restricted", "mechanism_lookup", "recommendation_lookup",
        "drug_profile", "surveillance", "decline", "unknown",
    }


# --------------------------------------------------------------------------------------
# Intent and entities. (question, intent, expected entity lists; each id must be present)
# --------------------------------------------------------------------------------------

CASES = [
    # why_restricted
    ("Why is colistin restricted?", "why_restricted", {"drug_ids": [COLISTIN]}),
    ("why is colistin a reserve antibiotic", "why_restricted", {"drug_ids": [COLISTIN]}),
    ("Why is meropenem on the Watch list?", "why_restricted", {"drug_ids": [MEROPENEM]}),
    ("Why are carbapenems reserved for serious infections?", "why_restricted",
     {"class_families": ["carbapenem"]}),
    ("Why is vancomycin restricted?", "why_restricted", {"drug_ids": [VANCOMYCIN]}),
    ("Why is colisin restricted", "why_restricted", {"drug_ids": [COLISTIN]}),  # misspelling
    # alternatives
    ("If carbapenem resistance is reported for Klebsiella, which alternatives remain?",
     "alternatives", {"pathogen_ids": [KP], "class_families": ["carbapenem"]}),
    ("What alternatives remain for KPC-producing Klebsiella pneumoniae?", "alternatives",
     {"pathogen_ids": [KP], "mechanism_ids": [KPC]}),
    ("what else works against crab", "alternatives",
     {"pathogen_ids": [AB], "class_families": ["carbapenem"]}),
    ("Which antibiotics still work against NDM-producing E. coli?", "alternatives",
     {"pathogen_ids": [EC], "mechanism_ids": [NDM]}),
    ("Options for CRE other than meropenem?", "alternatives",
     {"pathogen_ids": [KP, EC], "drug_ids": [MEROPENEM]}),
    ("Is cefiderocol active against CRAB?", "alternatives",
     {"pathogen_ids": [AB], "drug_ids": [CEFIDEROCOL]}),
    ("Which reserve options remain for CRAB?", "alternatives", {"pathogen_ids": [AB]}),
    ("Is tigecycline active against CRE?", "alternatives", {"drug_ids": [TIGECYCLINE]}),
    # mechanism_lookup
    ("How does E. coli resist cephalosporins?", "mechanism_lookup",
     {"pathogen_ids": [EC], "class_families": ["cephalosporin"]}),
    ("how does klebsiella resist carbapenems", "mechanism_lookup",
     {"pathogen_ids": [KP], "class_families": ["carbapenem"]}),
    ("What mechanisms make Pseudomonas aeruginosa resistant to carbapenems?",
     "mechanism_lookup", {"pathogen_ids": [PA]}),
    ("What does KPC confer resistance to?", "mechanism_lookup", {"mechanism_ids": [KPC]}),
    ("Which drugs does NDM inactivate?", "mechanism_lookup", {"mechanism_ids": [NDM]}),
    ("Does OXA-48 affect ceftazidime-avibactam?", "mechanism_lookup",
     {"mechanism_ids": [OXA48], "drug_ids": [CZA]}),
    ("Why is Klebsiella resistant to carbapenems?", "mechanism_lookup", {"pathogen_ids": [KP]}),
    ("mcr-1 colistin resistance", "mechanism_lookup", {"mechanism_ids": [MCR]}),
    ("How does Klebsiela pnumoniae resist merpenem?", "mechanism_lookup",
     {"pathogen_ids": [KP], "drug_ids": [MEROPENEM]}),  # three misspelled words
    # recommendation_lookup
    ("What is recommended for MRSA bloodstream infection?", "recommendation_lookup",
     {"pathogen_ids": [SA], "mechanism_ids": [MECA]}),
    ("what do the guidelines recommend for crkp", "recommendation_lookup",
     {"pathogen_ids": [KP], "class_families": ["carbapenem"]}),
    ("First-line treatment of ESBL E. coli urinary tract infection?", "recommendation_lookup",
     {"pathogen_ids": [EC], "mechanism_ids": [ESBL]}),
    ("What does ICMR 2019 recommend for CRAB?", "recommendation_lookup", {"pathogen_ids": [AB]}),
    ("How should DTR-PA be treated?", "recommendation_lookup", {"pathogen_ids": [PA]}),
    ("How is KPC-Kp treated?", "recommendation_lookup",
     {"pathogen_ids": [KP], "mechanism_ids": [KPC]}),
    # drug_profile
    ("What class and AWaRe group is meropenem?", "drug_profile", {"drug_ids": [MEROPENEM]}),
    ("what class is ceftazidime-avibactam", "drug_profile", {"drug_ids": [CZA]}),
    ("Tell me about colistin", "drug_profile", {"drug_ids": [COLISTIN]}),
    ("What is cefiderocol?", "drug_profile", {"drug_ids": [CEFIDEROCOL]}),
    # surveillance
    ("How common is carbapenem resistance in Klebsiella in India?", "surveillance",
     {"pathogen_ids": [KP], "class_families": ["carbapenem"]}),
    ("What percentage of Acinetobacter isolates in Pakistan were carbapenem-resistant in 2021?",
     "surveillance", {"pathogen_ids": [AB]}),
    ("mrsa prevalence in USA", "surveillance", {"pathogen_ids": [SA], "mechanism_ids": [MECA]}),
    ("Resistance rate of E. coli to fluoroquinolones in Kenya, 2020", "surveillance",
     {"pathogen_ids": [EC], "class_families": ["fluoroquinolone"]}),
    ("Is MRSA resistance trending up in Japan?", "surveillance", {"pathogen_ids": [SA]}),
    ("carbapenem resistant Acinetobacter in Brazil", "surveillance", {"pathogen_ids": [AB]}),
    # decline
    ("What is the dose of colistin for CRAB?", "decline", {}),
    ("How long should I treat a Klebsiella bloodstream infection?", "decline", {}),
    ("My patient has a CRE UTI, what should I give?", "decline", {}),
    ("Should I give meropenem for ESBL?", "decline", {}),
    ("Is colistin safe in pregnancy?", "decline", {}),
    ("What antibiotic for a child with MRSA?", "decline", {}),
    ("What is recommended for Streptococcus pneumoniae pneumonia?", "decline", {}),
    ("Alternatives for VRE?", "decline", {}),
    ("Treatment options for gonorrhoea", "decline", {}),
    ("What mg of vancomycin?", "decline", {}),
    # unknown
    ("Tell me a joke", "unknown", {}),
    ("Which antibiotics are in the Reserve group?", "unknown", {}),
    ("cza for crkp", "unknown", {"pathogen_ids": [KP], "drug_ids": [CZA]}),
]


@pytest.mark.parametrize("question,intent,expected", CASES, ids=[c[0][:50] for c in CASES])
def test_intent_and_entities(question, intent, expected):
    pq = parse(question)
    assert pq.intent == intent, explain(question)
    for field_name, ids in expected.items():
        for i in ids:
            assert i in getattr(pq, field_name), f"{field_name} should contain {i}: {getattr(pq, field_name)}"


def test_at_least_forty_questions_cover_every_intent():
    assert len(CASES) >= 40
    assert {c[1] for c in CASES} == set(INTENTS)


# --------------------------------------------------------------------------------------
# Entities
# --------------------------------------------------------------------------------------

def test_lowercase_acronyms_resolve_d37():
    pq = parse("what is recommended for mrsa")
    assert pq.pathogen_ids == [SA] and pq.mechanism_ids == [MECA]
    pq = parse("is cza active against crkp")
    assert pq.drug_ids == [CZA] and pq.pathogen_ids == [KP] and pq.class_families == ["carbapenem"]


def test_lowercase_retry_does_not_link_ordinary_words():
    text = ("the dose can be given for the best time, and then we wait; our mar tom pip min "
            "gen van dox fort pen all tri for you")
    assert parse(text).mentions == []


def test_phenotype_adds_pathogen_mechanism_and_family():
    pq = parse("Which alternatives remain for KPC-Kp?")
    assert pq.pathogen_ids == [KP] and pq.mechanism_ids == [KPC] and pq.class_families == ["carbapenem"]
    pq = parse("Alternatives for MRSA?")
    assert pq.pathogen_ids == [SA] and pq.mechanism_ids == [MECA] and pq.class_families == []


def test_ambiguous_phenotype_adds_every_pathogen():
    for q in ("Which alternatives remain for CRE?", "Alternatives for ESBL-E infections?"):
        assert parse(q).pathogen_ids == [KP, EC]


def test_ambiguous_phenotype_narrowed_by_named_species():
    pq = parse("If CRE is reported for Klebsiella, which alternatives remain?")
    assert pq.pathogen_ids == [KP]


def test_class_family_goes_to_class_families_not_class_ids():
    pq = parse("Why are fluoroquinolones restricted?")
    assert pq.class_families == ["fluoroquinolone"]
    assert pq.class_ids == []


def test_mentions_are_linked_mentions_sorted_by_position():
    pq = parse("how does klebsiella resist carbapenems")
    starts = [m.start for m in pq.mentions]
    assert starts == sorted(starts) and len(pq.mentions) == 2


def test_ids_are_unique_and_in_question_order():
    pq = parse("E. coli, Klebsiella and E. coli again, and meropenem vs meropenem")
    assert pq.pathogen_ids == [EC, KP] and pq.drug_ids == [MEROPENEM]


def test_misspellings_link_through_the_linker():
    pq = parse("Does merpenem work for Acinetobactor baumannii?")
    assert MEROPENEM in pq.drug_ids and AB in pq.pathogen_ids


# --------------------------------------------------------------------------------------
# Countries, years, sites
# --------------------------------------------------------------------------------------

def test_country_by_name_and_code():
    assert parse("How common is MRSA in India?").country == "IND"
    assert parse("how common is mrsa in india?").country == "IND"
    assert parse("How common is MRSA in KEN?").country == "KEN"
    assert parse("MRSA rate in the United States").country == "USA"
    assert parse("MRSA rate in the UK in 2019").country == "GBR"


def test_country_not_taken_from_drug_codes_or_words():
    assert parse("How common is CRE in Klebsiella?").country is None
    assert parse("What is the capital of Chad").country == "TCD"
    assert parse("chad said carbapenems are restricted").country is None
    assert extract_country("The cat can mar the floor") is None


def test_year_extraction():
    assert parse("How common was CRKP in India in 2019?").year == 2019
    assert parse("What does ICMR 2019 recommend for CRAB?").year is None
    assert parse("What does the 2022 ICMR guidance say about CRAB?").year is None
    assert extract_year("resistance in 2020") == 2020
    assert parse("How common is CRAB").year is None


def test_infection_site():
    assert parse("What is recommended for MRSA bloodstream infection?").infection_site == "bloodstream infection"
    assert parse("Treatment of ESBL E. coli UTI").infection_site == "urinary tract infection"
    assert parse("What is recommended for CRAB pneumonia?").infection_site == "pneumonia"
    assert parse("What is recommended for Klebsiella pneumoniae?").infection_site is None
    assert parse("What is recommended for MRSA?").infection_site is None


# --------------------------------------------------------------------------------------
# Decline rules
# --------------------------------------------------------------------------------------

DECLINES = [
    "What dose of meropenem for KPC?",
    "meropenem dosing in CRKP",
    "How many mg of colistin?",
    "What is the duration of therapy for CRAB?",
    "For how long should MRSA bacteraemia be treated?",
    "My patient has MRSA, what do I do?",
    "Should I start colistin for CRAB?",
    "A 54 year old man with a Klebsiella UTI",
    "What should I give for ESBL E. coli?",
    "Best antibiotic for MRSA in a pregnant woman",
    "Is meropenem safe in neonates?",
    "Treatment of Klebsiella infection in children",
    "What is recommended for Enterococcus faecium?",
    "How is C. difficile treated?",
    "Treatment of tuberculosis",
    "Options for Enterobacter cloacae",
]


@pytest.mark.parametrize("question", DECLINES)
def test_declines_with_reason(question):
    pq = parse(question)
    assert pq.intent == "decline", explain(question)
    assert pq.decline_reason


def test_decline_reasons_are_distinct_by_kind():
    reasons = {
        parse("What dose of meropenem for KPC?").decline_reason,
        parse("My patient has MRSA").decline_reason,
        parse("Treatment of Klebsiella infection in children").decline_reason,
        parse("Treatment of tuberculosis").decline_reason,
    }
    assert len(reasons) == 4


def test_non_decline_has_no_reason():
    assert parse("Why is colistin restricted?").decline_reason is None


def test_out_of_scope_organism_with_in_scope_one_is_not_declined():
    assert parse("Is Klebsiella more common than Enterococcus in India?").intent != "decline"


def test_children_in_surveillance_question_is_not_declined():
    assert parse("How common is MRSA in children in India?").intent == "surveillance"


def test_enterobacterales_is_not_enterobacter():
    pq = parse("Which alternatives remain for carbapenem-resistant Enterobacterales Klebsiella?")
    assert pq.intent == "alternatives"


# --------------------------------------------------------------------------------------
# Robustness and rule order
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("question", ["", "   ", "?", "a", "!!!!", "carbapenem " * 200])
def test_odd_input_does_not_raise(question):
    pq = parse(question)
    assert pq.intent in INTENTS and pq.question == question


def test_upper_and_lower_case_give_the_same_parse():
    a = parse("WHY IS COLISTIN RESTRICTED?")
    b = parse("why is colistin restricted?")
    assert (a.intent, a.drug_ids) == (b.intent, b.drug_ids) == ("why_restricted", [COLISTIN])


def test_decline_beats_every_intent_rule():
    # contains a restriction trigger and a drug, but asks for a dose
    assert parse("Why is the colistin dose restricted?").intent == "decline"


def test_alternatives_beats_why_restricted():
    assert parse("Which restricted options remain for CRAB?").intent == "alternatives"


def test_rule_names_are_listed_in_order():
    names = [n for n, _, _ in INTENT_RULES]
    assert names[0].startswith("S1") and names[1].startswith("A1") and len(names) == len(set(names))
    assert explain("Why is colistin restricted?").startswith("W1")
    assert explain("Tell me a joke").startswith("none")
    assert explain("What is the dose of colistin?").startswith("decline")


def test_shared_linker_is_reused():
    assert get_linker() is get_linker()

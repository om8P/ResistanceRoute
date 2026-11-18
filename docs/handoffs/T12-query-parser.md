# Handoff: T12 Query parser, intent rules and shared retrieval types

- **Model:** Sonnet 5.5
- **Status:** complete
- **Date:** 2026-11-18

## What was built

`retrieval/types.py` holds the dataclasses `ParsedQuery`, `Answer`, `Path`, `GraphResult` and `PassageHit` exactly as CONTRACTS §7 (plain dataclasses with defaults, plus an `INTENTS` tuple). `retrieval/parser.py` has `parse(question, linker=None) -> ParsedQuery`: it links entities with `EntityLinker`, retries unmatched lower-case tokens upper-cased (D37), expands phenotype acronyms, extracts country, year and infection site, applies decline rules (D18) and then ordered intent rules. `explain(question)` returns the name of the rule that decided, for debugging.

## Files created or changed

| Path | What it is |
|---|---|
| `retrieval/types.py` | The five dataclasses and `INTENTS` |
| `retrieval/parser.py` | `parse`, `explain`, `extract_country`, `extract_year`, `extract_site`, `INTENT_RULES`, `get_linker` |
| `tests/test_parser.py` | 101 tests: 53 hand-written questions covering all 8 intents, 16 more decline questions, and tests for entities, countries, years, sites and rule order |

## How to run and check it

```bash
.venv/Scripts/python -m pytest tests/test_parser.py
```

```bash
.venv/Scripts/python -c "from retrieval.parser import parse, explain; q='Why is colistin restricted?'; print(parse(q).intent, explain(q))"
```

## Test result

`.venv/Scripts/python -m pytest tests`: `603 passed, 2 warnings` (whole suite, 2026-11-18, final run). `tests/test_parser.py` alone: 101 passed. The warnings are `click` deprecations from `typer`. The questions in the tests were written by me; I did not read `eval/questions.json` (D16).

## What I found

### How parsing works

1. **Link** the text with `EntityLinker.link`. Then every token of 3 or more letters that is not already inside a mention is tried upper-cased with `resolve(token.upper(), fuzzy=False)`. It counts only if the matched dictionary string equals the upper-cased token, so ordinary words cannot link (tested with `mar`, `pip`, `min`, `gen`, `van`, `dox`...). Phenotype acronyms are also found by a case-insensitive lookup (`kpc-kp`, `dtr-pa`). These mentions have `match_type="uppercase"`. The lookup reads the linker's private `_phenotypes` dict.
2. **Entities.** `Pathogen` → `pathogen_ids`, `Mechanism` → `mechanism_ids`, `Drug` → `drug_ids`, `DrugClass` → `class_ids`, `ClassFamily` → `class_families` (the family id, e.g. `carbapenem`). A phenotype adds its pathogen(s), mechanisms and `class_family`. An ambiguous phenotype (CRE, ESBL-E) adds every pathogen it covers (`[573, 562]`); **if the question also names one of those species, only the named one is kept** ("CRE ... Klebsiella" → `[573]`). IDs are unique and in order of appearance.
3. **Country** by GLASS short name (`data/raw/glass/countries.csv`), a short alias list (USA, UK, South Korea, Vietnam...) or an upper-case ISO 3 code in the text. Names that are also ordinary words (Chad, Georgia, Jersey, Guinea, Turkey) need a capital letter; ISO codes that are words (CAN, MAR, PER...) are never read from upper case. **Year** is the first 4-digit year from 1900–2099, except one that names a guideline ("ICMR 2019", "the 2022 ICMR guidance"). Country and year are filled for every intent, not only surveillance. **Infection site** is a short free-text label (`bloodstream infection`, `sepsis`, `urinary tract infection`, `pneumonia`, `CLABSI`, `skin and soft tissue infection`, `intra-abdominal infection`, `osteomyelitis`, `meningitis`, `endocarditis`, `wound infection`) or `None`; T10 should match it loosely against `Recommendation.infection_site`, which is free text too.
4. **Decline** and then **intent** rules, below.

### Decline rules (checked first, in this order; the first match wins)

1. **Dosing and duration:** dose, dosing, dosage, mg, mg/kg, mcg, "how much", "duration", "for how long", "how long should/do/to", "how many mg/tablets/days", "every N hours", "q8h".
2. **Patient-specific:** "my/this/our patient" (and my mother, son, infection, culture...), "a patient with/who", "54 year old", "should/can I give/prescribe/start/use...", "what should I give", "I have a UTI".
3. **Pregnancy and children:** pregnant/pregnancy, breastfeeding, neonate, newborn, infant, child/children, paediatric, kids, toddler. Not applied when the question has a surveillance trigger ("how common is MRSA in children in India?" is a surveillance question).
4. **Out-of-scope pathogens:** Streptococcus, Enterococcus/VRE, Salmonella, Shigella, Neisseria/gonorrhoea, Clostridioides/C. diff, Haemophilus, Mycobacterium/tuberculosis, Candida and other fungi, Enterobacter, Serratia, Stenotrophomonas, Proteus, Listeria, Legionella and others, plus viruses. Applied **only when no in-scope pathogen was found**, so "Klebsiella vs Enterococcus in India" is answered.

Each kind has its own fixed `decline_reason` text (in `DECLINE_MESSAGES`).

### Intent rules (`INTENT_RULES`, first rule that fires wins)

| # | Name | Intent | Fires when |
|---|---|---|---|
| 1 | S1 | `surveillance` | how common/often/prevalent, prevalence, proportion, percent, `%`, rate(s), incidence, trend(s), surveillance, GLASS, share of, frequency, "how many isolates/cases" **and** any entity or a country |
| 2 | A1 | `alternatives` | alternative(s), what else, remain(s), still work/active/effective, left to treat, instead of, other than, apart from, "which antibiotics work/are active...", substitute, fallback **and** any entity |
| 3 | W1 | `why_restricted` | restrict, reserve(d), last resort, stewardship, kept for, protected, limited use, Watch group **and** a drug, class or family |
| 4 | M1 | `mechanism_lookup` | "how does X resist/evade/...", mechanism(s), what makes/causes, "why is X resistant", confer, inactivate, hydrolyse, enzyme, resistance gene, affect/defeat/destroy **and** a pathogen, mechanism, class, family or drug |
| 5 | A2 | `alternatives` | weak triggers: options, active/effective against, works against, coverage, suitable **and** a resistance context (resist..., a phenotype, a mechanism, ESBL) **and** a pathogen, mechanism or class |
| 6 | R1 | `recommendation_lookup` | recommend, guideline, first-line, empiric, drug of choice, treatment of, treat(ed), therapy, preferred, ICMR/IDSA/NICE, best antibiotic, manage **and** a pathogen or mechanism |
| 7 | D1 | `drug_profile` | what class/group/AWaRe, ATC, belong, tell me about, what is, spectrum, describe **and** a drug or class, no pathogen, no country |
| 8 | S2 | `surveillance` | a country or year **and** any entity, with no other trigger |
| 9 | D2 | `drug_profile` | a drug and no pathogen or mechanism |
| 10 | M2 | `mechanism_lookup` | a mechanism, the word "resist", and no phenotype |
| – | – | `unknown` | nothing fired; the caller falls back to text search (D13) |

Order choices that matter: decline beats everything; surveillance triggers beat the others (so "carbapenem resistance rate" is not an alternatives question); `alternatives` beats `why_restricted` ("which reserve options remain for CRAB" lists options); mechanism beats weak alternatives and recommendation ("how does ... resist" before "treatment").

### Parses of five example questions

| Question | Intent / rule | Entities |
|---|---|---|
| "If carbapenem resistance is reported for Klebsiella, which alternatives remain?" | `alternatives` (A1) | pathogen `NCBITaxon:573`; family `carbapenem` |
| "Why is colistin restricted?" | `why_restricted` (W1) | drug `J01XB01` |
| "How does E. coli resist cephalosporins?" | `mechanism_lookup` (M1) | pathogen `NCBITaxon:562`; family `cephalosporin` |
| "What is recommended for MRSA bloodstream infection?" | `recommendation_lookup` (R1) | pathogen `NCBITaxon:1280`; mechanism `ARO:3009312`; site `bloodstream infection` |
| "How common is carbapenem resistance in Klebsiella in India?" | `surveillance` (S1) | pathogen `NCBITaxon:573`; family `carbapenem`; country `IND` |

Lower case works too: "what else works against crab" → `alternatives`, pathogen `NCBITaxon:470`, family `carbapenem`. "What is the dose of colistin for CRAB?" → `decline` (dosing).

### Known failure cases

- **Phenotype-only and drug-plus-pathogen fragments are `unknown`:** "cza for crkp", "Can colistin be used for KPC?", "Why is cefiderocol not used first for CRAB?", "Compare meropenem and ertapenem for ESBL". There is no trigger word, so nothing fires. I judged `unknown` (text search) safer than guessing.
- **Definition questions about a pathogen or phenotype** ("what is mrsa", "What is CRE?") are `unknown`: D1 needs a drug or class.
- **"Which antibiotics are in the Reserve group?"** is `unknown` (a list question over the whole AWaRe group; no intent covers it).
- **`options` is ambiguous.** "ESBL E coli UTI options" and "Is tigecycline active against CRE?" go to `alternatives` because a phenotype or ESBL is a resistance context; "options for MRSA" is the same. Without a resistance context, "options" falls to `recommendation_lookup`.
- **"Kp"** and similar short forms that are not in `synonyms.csv` do not link, so "What is the resistance of Kp to cza in India?" gets only the drug and country (intent `surveillance` by S2, but no pathogen).
- **Single-word triggers can misfire:** "manage", "treat", "what is" and "rate" are broad; a question that merely contains "rate" next to an entity is read as surveillance.
- **Decline is deliberately aggressive:** "Why is the colistin dose restricted?" declines (the word "dose"), and a question that mentions a child, infant or pregnancy without a surveillance trigger declines even if it is about mechanisms.
- **Several drugs or pathogens with different roles** ("meropenem vs ertapenem") are returned as flat lists; the parser does not say which is the subject.
- **Misspelled trigger words** ("alternatves") are not corrected; only entity names are fuzzy-matched (by the linker).
- **Lower-case retry only covers exact dictionary strings.** `ceftaz` or `pip-tazo` do not resolve, and neither does a misspelled lower-case acronym ("mrsaa").
- **Year** is not checked against the range GLASS covers; "2035" would be returned. Countries absent from `countries.csv` and not in my alias list are not found.

## Deviations from the brief or contracts

- **`Path` has an extra field `answer_id`** and keeps its steps in `Path.steps` (a list of dicts with the keys listed in CONTRACTS §7). CONTRACTS describes a Path as "an ordered list of steps" without naming the attribute; T10 may rename or extend it.
- **`INTENTS` tuple** added to `retrieval/types.py` (not in the contract).
- `parse` accepts an optional `linker` argument, and `explain(question)` exists for debugging; neither is in the contract.
- Country and year are filled for every intent, not only surveillance.
- Ambiguous phenotypes are narrowed to the species the question names (see above). The brief only says they add every pathogen they cover.

## Not done or not verified

- The parser was not run against `eval/questions.json` (forbidden by the brief). Accuracy on the real evaluation questions is unknown; the 53 test questions were written by the same author as the rules, so they are not independent.
- Parser output was not run against the live graph; T10 and T14 are the first consumers.
- `Answer`, `Path`, `GraphResult` and `PassageHit` are only tested for their field names and defaults.

## Requests to orchestrator

1. **CONTRACTS §7:** record that `Path` has `steps` and `answer_id`, that `ParsedQuery.mentions` can hold mentions with `match_type="uppercase"` (retried lower-case acronyms), and the narrowing of ambiguous phenotypes to a named species.
2. **Synonyms (T03 files):** `Kp` (and similar user short forms such as `Ecoli`, `Pseudo`, `Staph aureus`) are not linkable. Adding them as `abbreviation` or `variant` rows would help the parser. I made no change.
3. **T14:** an `unknown` intent should go to text search only (D13); `decline` should show `decline_reason` and no retrieval.

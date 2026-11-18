# T12: Query parser, intent rules and shared retrieval types

- **Model:** Sonnet 5.5, effort `medium`
- **Wave:** 3
- **Depends on:** T07 (done)
- **Read first:** [ORCHESTRATION.md](../ORCHESTRATION.md), [CONTRACTS.md](../CONTRACTS.md) section 7 ("Retrieval interfaces"), [ARCHITECTURE.md](../ARCHITECTURE.md) section 6.1, [DECISIONS.md](../DECISIONS.md) D13, D18, D29, D37, the [T07 handoff](../handoffs/T07-entity-linker.md), `schema/phenotypes.csv` and `data/curated/REVIEW_NOTES.md` section 2.5

## Goal

Turn a natural-language question into a `ParsedQuery`: the intent, the canonical entities, and whether the system should decline. Also write the shared dataclasses that T10, T11 and T14 import.

## Files you own

- `retrieval/types.py` (**write this first**, within your first few steps, because T10 and T11 import it)
- `retrieval/parser.py`
- `tests/test_parser.py`

## Work

1. **`retrieval/types.py`**: `ParsedQuery`, `Answer`, `Path`, `GraphResult`, `PassageHit` exactly as CONTRACTS §7, as plain dataclasses with defaults.
2. **Entities** from `pipeline.link.EntityLinker`:
   - phenotype acronyms add their pathogen, implied mechanisms and class family; ambiguous ones (CRE, ESBL-E) add every pathogen they cover;
   - D37: question tokens of 3 or more letters that match nothing are retried upper-cased, so `mrsa` and `cza` resolve;
   - `ClassFamily` mentions go to `class_families`;
   - countries (name or ISO 3, from `data/raw/glass/countries.csv`) and four-digit years for surveillance.
3. **Intent rules**: ordered, readable rules using trigger phrases and the entity types found, for example "alternatives", "what else", "options", "remain" with a resistance term → `alternatives`; "why", "restricted", "reserve" with a drug → `why_restricted`; "how does … resist" → `mechanism_lookup`; "%", "how common", "rate", a country → `surveillance`. Fall back to `unknown`.
4. **Decline rules (D18)**: dose, dosing, mg, duration, "my patient", "should I give", pregnancy or child-specific treatment requests, and pathogens outside scope. Set `decline_reason`.
5. **Tests** from at least 40 questions you write yourself, covering every intent, abbreviations, lower case, misspellings, families and declines. Do not read `eval/questions.json`; the evaluation must stay independent (D16).

## Done when

- `.venv/Scripts/python -m pytest tests` passes.
- The handoff `docs/handoffs/T12-query-parser.md` lists the rules in order, the known failure cases, and the parse of five example questions.

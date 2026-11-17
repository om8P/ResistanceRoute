# T09: Evaluation questions with gold answers

- **Model:** Opus 5.5
- **Wave:** 2
- **Depends on:** T02, T03 (done)
- **Read first:** [ORCHESTRATION.md](../ORCHESTRATION.md), [ARCHITECTURE.md](../ARCHITECTURE.md) sections 6.1 and 7.2, [DECISIONS.md](../DECISIONS.md) D16, the [T02 handoff](../handoffs/T02-data-acquisition.md), `schema/scope.yaml` and `data/curated/REVIEW_NOTES.md`

## Goal

Write the 40 evaluation questions and their gold answers before any retrieval code exists, so the evaluation cannot be fitted to the system (D16). Gold answers come from the source documents, not from the graph. Relevant passage IDs are added later by T15.

## Files you own

- `eval/questions.json`
- `eval/QUESTIONS_NOTES.md`
- `tests/test_questions.py`

## Question set

- 40 questions: 20 single-hop, 20 multi-hop.
- All six intents in ARCHITECTURE §6.1, at least 4 questions each. The `alternatives` and `why_restricted` intents get at least 8 each.
- At least 6 multi-hop questions where the answer depends on the mechanism (KPC, NDM, OXA-48-like, VIM, OXA-23-like, mecA), including at least one pair that differs only in the mechanism.
- Varied wording, as a student or clinician would type it: abbreviations (CRKP, MRSA, CZA), brand names, lower case, one or two misspellings, questions that name a class family ("carbapenems") rather than a drug.
- 4 questions that the system should decline: out-of-scope pathogens, dosing, patient-specific advice. Their gold answer is `decline` with a reason.

## Format of `eval/questions.json`

A JSON list of objects:

| Field | Meaning |
|---|---|
| `id` | `Q01` … `Q40` |
| `question` | The question text |
| `intent` | One of the six intents, or `decline` |
| `hops` | `single` or `multi` |
| `entities` | Canonical IDs from `scope.yaml` the question refers to, including any implied by an acronym |
| `answer_type` | `drug_set`, `class_set`, `mechanism_set`, `fact`, `number`, or `decline` |
| `gold` | For sets, a list of canonical IDs; for `fact`, a short statement; for `number`, a value with year and country; for `decline`, the reason |
| `gold_source` | Guideline ID with PDF page, `glass` with the row key, or `curated-seed` with the file and row, for every answer |
| `notes` | Anything an evaluator should know, such as acceptable alternative answers |

## Rules specific to this task

- Derive gold answers from the guideline PDFs, the GLASS file and the curated seed files, and cite the page or row. Read the pages yourself.
- Do not read any retrieval code, and do not design questions around what you expect the system to do well.
- Where sources disagree, choose the stricter answer and say so in `notes`.
- No doses or patient-specific advice in any gold answer.

## Tests

`tests/test_questions.py`: 40 unique IDs, valid field values, counts per intent and hop type as specified, every entity and gold ID exists in `scope.yaml`, every answer has a `gold_source`.

## Done when

- `.venv/Scripts/python -m pytest tests` passes.
- `eval/QUESTIONS_NOTES.md` explains the design and lists the questions whose gold answers were hardest to decide.
- The handoff `docs/handoffs/T09-eval-questions.md` gives counts per intent, hop type and answer type.

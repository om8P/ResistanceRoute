# Handoff: T09 Evaluation questions with gold answers

- **Model:** Opus 5.5
- **Status:** complete
- **Date:** 2026-11-18

## What was built

40 evaluation questions with gold answers in `eval/questions.json`, written before any retrieval code exists. Gold answers come from guideline pages I read myself, the GLASS file and the curated seed files; no system output was used. Every answer cites a source that `tests/test_questions.py` can locate: a guideline ID with PDF page, a GLASS row key with file line, an AWaRe 2025 workbook row, or a curated-seed file and line. Where sources disagreed I chose the stricter answer and said so in `notes`. `eval/QUESTIONS_NOTES.md` explains the design and the ten hardest gold answers.

## Files created or changed

| Path | What it is |
|---|---|
| `eval/questions.json` | 40 questions, fields exactly as in the T09 brief |
| `eval/QUESTIONS_NOTES.md` | Design, definitions (single vs multi-hop, source formats), hardest gold answers, limits |
| `tests/test_questions.py` | 20 tests: IDs, fields, counts, mechanism pair, scope IDs, locatable sources, no doses, wording variety |
| `docs/handoffs/T09-eval-questions.md` | This file |

## How to run and check it

```bash
.venv/Scripts/python -m pytest tests/test_questions.py -q
.venv/Scripts/python -m pytest tests
```

## Test result

`tests/test_questions.py`: `20 passed in 0.11s`. Whole suite: `407 passed, 2 warnings in 12.20s` (the warnings are Click deprecation warnings from `typer`, not from project code). No failures in any file.

## What I found

### Counts

| Intent | Single | Multi | Total |
|---|---|---|---|
| alternatives | 0 | 9 | 9 |
| why_restricted | 5 | 3 | 8 |
| mechanism_lookup | 2 | 3 | 5 |
| recommendation_lookup | 0 | 5 | 5 |
| drug_profile | 4 | 0 | 4 |
| surveillance | 5 | 0 | 5 |
| decline | 4 | 0 | 4 |
| **Total** | **20** | **20** | **40** |

| Answer type | Count |
|---|---|
| drug_set | 13 |
| class_set | 1 |
| mechanism_set | 5 |
| number | 4 |
| fact | 13 |
| decline | 4 |

- **Mechanism-dependent multi-hop questions:** 11, covering all of KPC, NDM, OXA-48-like, VIM, OXA-23-like and mecA.
- **Pairs that differ only in the mechanism:** Q02/Q03 (KPC vs NDM *K. pneumoniae*, which beta-lactams remain) and Q15/Q16 (ICMR first choice for KPC vs NDM CRE).
- **Declines:** dosing (Q17), patient-specific (Q24), out-of-scope pathogens VRE (Q32) and *Enterobacter cloacae* (Q40).

### Facts the next tasks need

- **Best mechanism sources.** AWaRe book Table 41.1 (PDF p596–597) gives each Reserve antibiotic's activity per beta-lactamase type (ESBL, KPC, MBL, AmpC, OXA-48, non-fermenters). It is the clearest mechanism-to-drug source after ICMR 2022 Table 4 (p16–17). T08 and T15 should use both.
- **GLASS MRSA rows disagree.** India 2023 has `Methicillin` 53.6% (blank group, line 123486) and `Oxacillin` 28.0% (group `Methicillin resistance`, line 41602). T05 must decide which row becomes the *S. aureus* `SurveillanceStat`. Q28 uses the methicillin row as gold and accepts 28.0.
- **GLASS has no *P. aeruginosa* rows** (0 of 233,306, rechecked). Q35 tests that the system says so.
- **Where the gold differs from the curated seed (stricter):**
  - Q03: plain aztreonam left out for NDM.
  - Q13: plain cephalosporins and aztreonam left out for OXA-48-like.
  - Q18: aztreonam left out for VIM *P. aeruginosa*.

  A graph that reports single-mechanism activity will lose precision on these, which matches the two caveats in REVIEW_NOTES §3. Combining with CTX-M, or adding the T14 caveat, would recover it.
- **Sandbox environment fact.** The venv's base interpreter is the Microsoft Store Python, which the sandboxed shell cannot launch ("Unable to create process"). I ran `.venv/Scripts/python` with the sandbox disabled for read-only extraction and for pytest. Other workers may hit the same error.

## Deviations from the brief or contracts

- **`gold_source` is a list of strings, not one string**, because most answers cite several pages.
- **A fourth source form, `who-aware-2025 sheet 'AWaRe classification 2025' row <n>`**, is used for AWaRe groups. The brief lists guideline/page, GLASS and curated-seed only. The AWaRe workbook is the contract's source for groups (`source_id` `who-aware-2025`).
- **`schema/scope.yaml` and `schema/phenotypes.csv` lines are cited as `curated-seed`**, as is the `scope.yaml` header line 3 ("No doses") for declines. These files are T03 seed data like `data/curated/`.
- **Surveillance Q35 has answer type `fact`** ("GLASS has no figure"), not `number`.

## Not done or not verified

- Relevant passage IDs are not added (T15's task).
- The IDSA and EUCAST documents behind some seed rows were not read. Gold answers resting on them cite the seed row and its `needs_review` flag (Q21, Q23, Q38).
- Fact and decline answers (17 of 40) have no automatic scoring yet. The `notes` say which parts of each answer are required.

## Requests to orchestrator

1. Accept the `gold_source` list format and the `who-aware-2025 … row` form, or say which form to use instead. If accepted, record them in CONTRACTS.md for T15 and T17.
2. T17 needs a scoring rule for `fact` and `decline` answers: a rubric, manual scoring, or keyword checks built from the `notes`.
3. In the T05 brief, decide which GLASS row (methicillin or oxacillin) represents MRSA.
4. Tell T15 that Q23 (ceftaroline for MRSA) is sourced only to the curated seed and needs a supporting passage if one exists.

## Follow-up (2026-11-18, after orchestrator review)

The review accepted T09 and ruled on the requests (DECISIONS.md "Other rulings" and D35).

- **Keywords added.** All 17 `fact` and `decline` questions now have `gold_keywords`, a list of required items. 15 of them also have `gold_keywords_any`, a list of alternative groups where one item of each group must appear. Q01, Q25 and Q29 need only required items.
  - Items are lower-case phrases or `scope.yaml` IDs, kept minimal. Examples: Q01 `carbapenem` and `watch`; Q10 `avibactam` plus one of `metallo`, `mbl` or `class b`.
  - Decline questions need a topic group and a refusal group. For example, Q17 needs one of `dose`/`dosing` and one of `cannot`, `unable`, `no doses`, …
  - The fields come right after `gold`. `questions.json` was rewritten with `json.dump(indent=2)`; no other field changed.
- **MRSA row (D35).** Q28 already used the GLASS `Methicillin` row (53.6%), so no gold or source changed. The oxacillin row stays in `notes` only as an accepted alternative.
- **Tests.** `tests/test_questions.py` has three new tests (23 in total):
  - the keyword fields are present on every fact/decline question and on no other kind, and are well-formed;
  - any ID-like keyword exists in `scope.yaml`;
  - each gold statement passes its own keyword check, so the keywords are never stricter than the gold.
- **Test result.** `tests/test_questions.py`: 23 passed. Whole suite: `2 failed, 457 passed, 2 warnings in 23.74s`. Both failures are in `tests/test_build_core.py`, which another task owns: `test_glass_map_targets_exist_in_scope` and `test_every_file_passes_validation_with_no_rejections`. The cause is that the GLASS map sends `Oxacillin` to `J01CF04`, which is not in `scope.yaml`. This relates to D35 (MRSA uses the Methicillin row), but I did not touch those files.

# T08: Curate guideline recommendations

- **Model:** Opus 5.5
- **Wave:** 2
- **Depends on:** T02, T03 (done)
- **Read first:** [ORCHESTRATION.md](../ORCHESTRATION.md), [CONTRACTS.md](../CONTRACTS.md) sections 2 and 4, [ARCHITECTURE.md](../ARCHITECTURE.md) section 5, [DECISIONS.md](../DECISIONS.md) D5, D9, D18, D31, the "guidelines" part of the [T02 handoff](../handoffs/T02-data-acquisition.md), and the [T03 handoff](../handoffs/T03-domain-seed.md) with `data/curated/REVIEW_NOTES.md`

## Goal

Write the hand-curated recommendations that the graph's answers rest on. They are also the gold standard for the extraction experiment (T13), so each row must be traceable to a page.

## Files you own

- `data/curated/recommendations_curated.csv`
- `data/curated/RECOMMENDATION_NOTES.md`
- `tests/test_recommendations_curated.py`

## Sources and where to look

| Guideline ID | File | Pages to read (PDF pages) |
|---|---|---|
| `icmr-cr-gram-negative-2022` | `data/raw/guidelines/icmr-carbapenem-resistant-gram-negative-2022.pdf` | Section 3, p15–19, including Table 4 (per mechanism) |
| `who-aware-book-2022` | `data/raw/guidelines/who-aware-antibiotic-book-2022.pdf` | Reserve chapters 41–48 (p593–642); sepsis in adults (p311–334); hospital-acquired pneumonia (p397–411); upper UTI (p490–504); osteomyelitis and septic arthritis for MRSA (p505–538) |
| `icmr-treatment-guidelines-2019` | `data/raw/guidelines/icmr-treatment-guidelines-2019.pdf` | Chapter 10, hospital-acquired infection (printed p93–125, PDF p98–130); chapter 3, sepsis |

Read the pages yourself with `pdfplumber` or `pypdf`. Do not rely on memory of these guidelines.

## Work

1. **`recommendations_curated.csv`**, 40–80 rows, columns exactly as CONTRACTS §4:
   - Only pathogens, mechanisms and drugs in `schema/scope.yaml`. A recommendation for a drug that is not in scope is noted in `RECOMMENDATION_NOTES.md`, not added.
   - `mechanism_id` only when the guideline names a mechanism (as in ICMR 2022 Table 4); empty otherwise.
   - One row per distinct recommendation. Combination therapy (for example ceftazidime-avibactam plus aztreonam) is one row with both drug IDs.
   - `text` is a short paraphrase in your own words, at most 40 words. No doses, durations or patient-specific advice.
   - `source_page` is the PDF page; `source_section` is the chapter or section title.
   - Cover all five pathogens; aim for at least 15 rows tied to a carbapenem-resistance mechanism.
2. **Consistency check against the seed data.** For every row with a mechanism, check that no recommended drug is excluded for that mechanism by the curated resistance facts (the exclusion rule is in the T03 handoff). List every conflict in `RECOMMENDATION_NOTES.md` with the page that supports the recommendation. Do not edit T03's files; the orchestrator decides.
3. **`RECOMMENDATION_NOTES.md`**: how rows were chosen, where the guidelines disagree with each other, conflicts from step 2, out-of-scope drugs mentioned, and rows you are unsure about.

## Tests

`tests/test_recommendations_curated.py`: columns and ID formats, IDs exist in scope, `rec_id` unique and in the `REC:<guideline>:<nnn>` format, `line_of_therapy` values, page numbers within each PDF's page count, paraphrases at most 40 words.

## Done when

- `.venv/Scripts/python -m pytest tests` passes.
- The handoff `docs/handoffs/T08-curate-recommendations.md` gives row counts per guideline, per pathogen and per mechanism, and the number of conflicts found.

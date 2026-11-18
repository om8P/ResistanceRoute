# T13: Recommendation extraction experiment

- **Model:** Sonnet 5.5, effort `medium`
- **Wave:** 3
- **Depends on:** T06, T07, T08 (done)
- **Read first:** [ORCHESTRATION.md](../ORCHESTRATION.md), [CONTRACTS.md](../CONTRACTS.md) sections 4 and 6, [ARCHITECTURE.md](../ARCHITECTURE.md) section 4, [DECISIONS.md](../DECISIONS.md) D9, D33, Q2, and the handoffs for [T06](../handoffs/T06-pdf-chunking.md), [T07](../handoffs/T07-entity-linker.md) and [T08](../handoffs/T08-curate-recommendations.md)

## Goal

Measure how well recommendations can be extracted from guideline text automatically, using the hand-curated recommendations as the gold standard. This is the schema-guided extraction experiment in the syllabus. Extracted recommendations are not loaded into the graph.

## Files you own

- `pipeline/extract.py`
- `data/processed/recommendations_extracted.jsonl`
- `eval/extraction_eval.py`
- `eval/results/extraction_eval.json`
- `tests/test_extract.py`

## Work

1. **Rule-based extractor** in `pipeline/extract.py`: over the guideline passages (not the abstracts), find sentences that recommend drugs, using trigger patterns ("first choice", "recommended", "preferred", "alternative", "options include", "reserve for", table rows from ICMR 2022 Table 4) and the entity linker for pathogens, mechanisms and drugs. Output one `RecommendationExtraction` (in `pipeline/models.py`) per extracted recommendation, with `passage_id`, `method` `rule` and a confidence.
2. **Linking to IDs**: resolve extracted names to canonical IDs with the linker.
3. **Evaluation** in `eval/extraction_eval.py`: match extracted to curated recommendations by pathogen, mechanism, drug set and source page (allow ±1 page). Report precision, recall and F1 overall, per guideline, and per field (pathogen, mechanism, drugs, line of therapy), using `eval.metrics`. Write `eval/results/extraction_eval.json`.
4. **Error analysis**: ten false positives and ten false negatives with their passages, grouped by cause.

## Rules specific to this task

- Do not tune the extractor by reading the curated rows one by one and writing a pattern for each; that would make the score meaningless. Develop on the ICMR 2019 guideline, then report the score on all three, with ICMR 2019 shown separately as the development set.
- LLM extraction stays out of scope (Q2).

## Done when

- `.venv/Scripts/python -m pytest tests` passes.
- The handoff `docs/handoffs/T13-extraction-experiment.md` gives the scores, the error analysis and what would improve them.

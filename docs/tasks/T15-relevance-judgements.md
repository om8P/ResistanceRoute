# T15: Relevance judgements for the evaluation questions

- **Model:** Opus 5.5, effort `medium`
- **Wave:** 4
- **Depends on:** T09, T10, T11 (done)
- **Read first:** [ORCHESTRATION.md](../ORCHESTRATION.md), [ARCHITECTURE.md](../ARCHITECTURE.md) section 7.2, [DECISIONS.md](../DECISIONS.md) D16, the handoffs for [T09](../handoffs/T09-eval-questions.md) and [T11](../handoffs/T11-passage-indexes.md), and `eval/questions.json` with `eval/QUESTIONS_NOTES.md`

## Goal

Mark which passages are relevant to each of the 40 evaluation questions, so that passage retrieval can be scored with Recall@k, MRR and nDCG.

## Files you own

- `eval/qrels.json`
- `eval/build_pool.py`
- `eval/QRELS_NOTES.md`
- `tests/test_qrels.py`

Do not edit `eval/questions.json`.

## Method: pooling

Standard IR practice, so that no single system decides what counts as relevant.

1. **`eval/build_pool.py`**: for each question, the union of the top 20 passages from `bm25`, `dense` and `bm25_dense` (`retrieval.text_search.search`), plus the passages linked to the question's gold entities and gold sources (`passages_for_entities`, and passages from each `gold_source` page). Record which method contributed each passage.
2. **Judge every pooled passage yourself** by reading it, on a 0–2 scale: 2 = it states the answer or a key part of it; 1 = it is on topic and useful context; 0 = not relevant. Judge from the passage text and the question, not from which method found it.
3. **Decline questions** have no relevant passages.
4. Q23 (ceftaroline for MRSA) is sourced only to the curated seed: look specifically for a supporting passage and say what you found.

## Output

`eval/qrels.json`: `{"Q01": {"<passage id>": 2, ...}, ...}`, listing only grades 1 and 2.

`eval/QRELS_NOTES.md`: pool sizes, grade counts per question, how many relevant passages each pooling method contributed, questions with no relevant passage, and hard judgement calls.

## Tests

`tests/test_qrels.py`: every question ID has an entry, every passage ID exists in `passages.jsonl`, grades are 1 or 2, decline questions are empty.

## Done when

- `.venv/Scripts/python -m pytest tests` passes.
- The handoff `docs/handoffs/T15-relevance-judgements.md` gives the totals and any question where the gold answer looks wrong given the passages (report it; do not change it).

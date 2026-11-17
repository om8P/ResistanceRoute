# T04: Evaluation metric functions

- **Model:** Haiku 5.5
- **Wave:** 1
- **Depends on:** T00 (done)
- **Read first:** [ORCHESTRATION.md](../ORCHESTRATION.md), [CONTRACTS.md](../CONTRACTS.md) section 7

## Goal

Write the metric functions the evaluation will use, with tests that prove they are correct. Standard library only.

## Files you own

- `eval/metrics.py`
- `tests/test_metrics.py`

Do not edit `eval/__init__.py`.

## Functions

All ranked lists are sequences of string IDs, best first. Count a repeated ID only at its first position.

| Function | Returns |
|---|---|
| `precision_at_k(ranked, relevant, k)` | Relevant items in the top `k`, divided by `k` |
| `recall_at_k(ranked, relevant, k)` | Relevant items in the top `k`, divided by the number of relevant items; `0.0` when `relevant` is empty |
| `reciprocal_rank(ranked, relevant)` | `1 / rank` of the first relevant item; `0.0` when none is found |
| `average_precision(ranked, relevant)` | Mean of precision at each relevant item's rank, divided by the number of relevant items; `0.0` when `relevant` is empty |
| `ndcg_at_k(ranked, relevance, k)` | nDCG with gain equal to the relevance grade and discount `log2(rank + 1)`. `relevance` is either a mapping of ID to grade, or a collection of IDs treated as grade 1. `0.0` when the ideal DCG is 0 |
| `set_prf(predicted, gold)` | `{"precision", "recall", "f1"}` comparing two sets. Both empty gives 1.0 for all three. One empty gives 0.0 for all three |
| `accuracy(predictions, gold)` | Fraction of positions where the two equal-length sequences match; raise `ValueError` when lengths differ; `0.0` when both are empty |
| `aggregate(per_query)` | Given a list of `{metric name: value}` dicts, the mean of each metric across queries; `{}` for an empty list |

Rules:

- `k` less than 1 raises `ValueError`.
- Every function has type hints and a short docstring stating the formula and the edge cases above.
- No rounding inside the functions.

## Tests

`tests/test_metrics.py` must include, for each function:

- a case with a value worked out by hand, with the arithmetic shown in a comment;
- the edge cases listed above;
- for `ndcg_at_k`, one binary case and one graded case, and a check that a perfect ranking gives exactly 1.0.

## Done when

- `.venv/Scripts/python -m pytest tests/test_metrics.py` passes.
- The handoff `docs/handoffs/T04-eval-metrics.md` is written.

# Handoff: T04 Evaluation metric functions

- **Model:** Haiku 5.5 (claude-haiku-5-5)
- **Status:** complete
- **Date:** 2026-11-17

## What was built

The eight evaluation metrics in `eval/metrics.py`, standard library only: `precision_at_k`, `recall_at_k`, `reciprocal_rank`, `average_precision`, `ndcg_at_k`, `set_prf`, `accuracy` and `aggregate`. None of them rounds. Each has type hints and a docstring stating its formula and edge cases. Ranked lists are deduplicated before ranks are assigned, so a repeated ID counts only at its first position and does not push later items down. `tests/test_metrics.py` has 55 tests. Every function has at least one hand-worked value with the arithmetic in a comment, plus its edge cases. `ndcg_at_k` has a binary case, a graded case, two more hand-worked graded checks, and checks that a perfect ranking gives exactly `1.0`.

## Files created or changed

| Path | What it is |
|---|---|
| `eval/metrics.py` | The eight metric functions and two private helpers (`_check_k`, `_dedupe`) |
| `tests/test_metrics.py` | 55 pytest tests with hand-worked values and edge cases |
| `docs/handoffs/T04-eval-metrics.md` | This handoff |

`eval/__init__.py` was not edited.

## How to run and check it

```bash
.venv/Scripts/python -m pytest tests/test_metrics.py
.venv/Scripts/python -m pytest tests
```

## Test result

Targeted run: `55 passed in 0.07s`

Full `tests` folder: `55 passed in 0.09s`. No other tests exist yet, so there are no failures to report.

## What I found

- Import path: `from eval.metrics import ...`. `eval/__init__.py` is empty, so nothing is re-exported. T17 should import from `eval.metrics` directly.
- Ranked-list inputs are `Sequence[str]`. Relevant and gold inputs are `Iterable[str]`, converted to sets internally, so a list or a generator works.
- `ndcg_at_k` takes either a mapping of ID to grade or a plain collection of IDs (grade 1). Items missing from a mapping have grade 0.
- `aggregate` takes a list of dicts and returns a dict with the same metric names. It returns `{}` for an empty list.

## Deviations from the brief or contracts

Choices the brief left open, made to keep the behaviour unambiguous:

1. **Duplicate IDs in ranked lists.** The brief says to count a repeated ID only at its first position. I read that as dropping later copies before ranks are assigned. So `["a", "a", "b"]` is treated as `["a", "b"]`. The alternative would be to keep the duplicate's slot and skip it when counting hits. The two readings give different numbers for `precision_at_k`, `recall_at_k`, `reciprocal_rank`, `average_precision` and `ndcg_at_k`. The tests fix the first reading.
2. **Negative nDCG grades** raise `ValueError`. The brief does not mention this.
3. **`aggregate` with mismatched metric names** raises `ValueError`. Every dict must have the same key set as the first. The brief does not mention this case. Silently averaging over different query counts would be misleading.
4. **`accuracy`** accepts any `Sequence[object]`, not only strings, so it can compare labels of any type.

## Not done or not verified

Nothing is left out. Floating-point results are checked with `pytest.approx` where the expected value comes from a logarithm or a non-terminating fraction. Where the expected value is exact in binary (for example `2/3` computed the same way, or `1.0`), the test uses `==`.

## Requests to orchestrator

- Please confirm the duplicate-ID reading in deviation 1. It affects every ranked metric. If you want the other reading (keep the slot, skip the hit), it is a small change in `_dedupe`'s callers, and the tests need updating too.
- No packages are needed. Only the standard library and `pytest` are used.

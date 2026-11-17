"""Evaluation metrics for ranked retrieval and set-based comparison.

Standard library only. No function rounds its result.

Conventions shared by the ranked metrics:

- A ranked list is a sequence of string IDs, best first. Rank 1 is the first item.
- A repeated ID is counted only at its first position. Later copies are dropped
  before ranks are assigned, so they do not push other items down.
- ``relevant`` and ``gold`` are collections of IDs. Duplicates in them have no effect.
- ``k`` must be at least 1; otherwise ``ValueError`` is raised.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence


def _check_k(k: int) -> None:
    """Raise ``ValueError`` when ``k`` is below 1."""
    if k < 1:
        raise ValueError(f"k must be at least 1, got {k}")


def _dedupe(ranked: Iterable[str]) -> list[str]:
    """Return the IDs in order, keeping only the first occurrence of each ID.

    Empty input gives an empty list.
    """
    seen: set[str] = set()
    unique: list[str] = []
    for item in ranked:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def precision_at_k(ranked: Sequence[str], relevant: Iterable[str], k: int) -> float:
    """Precision at cut-off ``k``.

    Formula: (number of relevant items in the top ``k``) / ``k``.

    Edge cases:
    - The denominator is always ``k``, even when the list is shorter than ``k``.
    - An empty ``ranked`` gives 0.0.
    - An empty ``relevant`` gives 0.0 (no hits are possible).
    - Repeated IDs are counted once, at their first position.
    - ``k`` below 1 raises ``ValueError``.
    """
    _check_k(k)
    rel = set(relevant)
    top = _dedupe(ranked)[:k]
    hits = sum(1 for item in top if item in rel)
    return hits / k


def recall_at_k(ranked: Sequence[str], relevant: Iterable[str], k: int) -> float:
    """Recall at cut-off ``k``.

    Formula: (number of relevant items in the top ``k``) / (number of relevant items).

    Edge cases:
    - An empty ``relevant`` gives 0.0.
    - An empty ``ranked`` gives 0.0.
    - Repeated IDs are counted once, at their first position.
    - ``k`` below 1 raises ``ValueError``.
    """
    _check_k(k)
    rel = set(relevant)
    if not rel:
        return 0.0
    top = _dedupe(ranked)[:k]
    hits = sum(1 for item in top if item in rel)
    return hits / len(rel)


def reciprocal_rank(ranked: Sequence[str], relevant: Iterable[str]) -> float:
    """Reciprocal rank of the first relevant item.

    Formula: 1 / rank, where rank is the 1-based position of the first item in
    ``ranked`` that is in ``relevant``.

    Edge cases:
    - Returns 0.0 when no relevant item appears in ``ranked``.
    - Returns 0.0 when ``ranked`` or ``relevant`` is empty.
    - Repeated IDs are counted once, at their first position.
    """
    rel = set(relevant)
    if not rel:
        return 0.0
    for rank, item in enumerate(_dedupe(ranked), start=1):
        if item in rel:
            return 1 / rank
    return 0.0


def average_precision(ranked: Sequence[str], relevant: Iterable[str]) -> float:
    """Average precision over the whole ranked list.

    Formula: (sum over relevant items found of precision at that item's rank)
    / (total number of relevant items). Precision at rank ``i`` is the number of
    relevant items in the first ``i`` positions divided by ``i``.

    Edge cases:
    - Relevant items that never appear in ``ranked`` still count in the
      denominator, so they lower the score.
    - Returns 0.0 when ``relevant`` is empty.
    - Returns 0.0 when ``ranked`` is empty.
    - Repeated IDs are counted once, at their first position.
    """
    rel = set(relevant)
    if not rel:
        return 0.0
    hits = 0
    total = 0.0
    for rank, item in enumerate(_dedupe(ranked), start=1):
        if item in rel:
            hits += 1
            total += hits / rank
    return total / len(rel)


def ndcg_at_k(
    ranked: Sequence[str],
    relevance: Mapping[str, float] | Iterable[str],
    k: int,
) -> float:
    """Normalised discounted cumulative gain at cut-off ``k``.

    Gain for an item is its relevance grade. Discount at rank ``r`` is
    ``log2(r + 1)``. Then::

        DCG  = sum over the top k of grade(item at rank r) / log2(r + 1)
        IDCG = the same sum, but over the grades sorted from highest to lowest
        nDCG = DCG / IDCG

    ``relevance`` is either:
    - a mapping from ID to grade (graded relevance; IDs not in the mapping have grade 0), or
    - a collection of IDs, each treated as grade 1 (binary relevance).

    Edge cases:
    - Returns 0.0 when IDCG is 0, for example when ``relevance`` is empty or
      every grade is 0.
    - Returns 0.0 when ``ranked`` is empty and IDCG is positive.
    - A perfect ranking gives exactly 1.0, because DCG and IDCG then sum the
      same terms in the same order.
    - Repeated IDs are counted once, at their first position.
    - Negative grades raise ``ValueError``.
    - ``k`` below 1 raises ``ValueError``.
    """
    _check_k(k)
    if isinstance(relevance, Mapping):
        grades: dict[str, float] = dict(relevance)
    else:
        grades = {doc: 1.0 for doc in relevance}
    if any(grade < 0 for grade in grades.values()):
        raise ValueError("relevance grades must be non-negative")

    dcg = 0.0
    for rank, item in enumerate(_dedupe(ranked)[:k], start=1):
        dcg += grades.get(item, 0.0) / math.log2(rank + 1)

    ideal_grades = sorted(grades.values(), reverse=True)[:k]
    idcg = 0.0
    for rank, grade in enumerate(ideal_grades, start=1):
        idcg += grade / math.log2(rank + 1)

    if idcg == 0:
        return 0.0
    return dcg / idcg


def set_prf(predicted: Iterable[str], gold: Iterable[str]) -> dict[str, float]:
    """Precision, recall and F1 of a predicted set against a gold set.

    Formulas, with ``tp`` = size of the intersection::

        precision = tp / |predicted|
        recall    = tp / |gold|
        f1        = 2 * precision * recall / (precision + recall)

    Edge cases:
    - Both sets empty: precision, recall and f1 are all 1.0.
    - Exactly one set empty: precision, recall and f1 are all 0.0.
    - No overlap (both sets non-empty): all three are 0.0.
    - Duplicates within an input have no effect, because the inputs become sets.

    Returns a dict with keys ``"precision"``, ``"recall"`` and ``"f1"``.
    """
    pred = set(predicted)
    gld = set(gold)
    if not pred and not gld:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    if not pred or not gld:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    tp = len(pred & gld)
    if tp == 0:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    precision = tp / len(pred)
    recall = tp / len(gld)
    f1 = 2 * precision * recall / (precision + recall)
    return {"precision": precision, "recall": recall, "f1": f1}


def accuracy(predictions: Sequence[object], gold: Sequence[object]) -> float:
    """Fraction of positions where the prediction equals the gold value.

    Formula: (number of positions i where predictions[i] == gold[i]) / length.

    Edge cases:
    - Lengths that differ raise ``ValueError``.
    - Two empty sequences give 0.0.
    """
    if len(predictions) != len(gold):
        raise ValueError(
            f"predictions and gold must have the same length, "
            f"got {len(predictions)} and {len(gold)}"
        )
    if not predictions:
        return 0.0
    correct = sum(1 for p, g in zip(predictions, gold) if p == g)
    return correct / len(predictions)


def aggregate(per_query: Sequence[Mapping[str, float]]) -> dict[str, float]:
    """Mean of each metric across queries.

    Formula: for each metric name, the sum of its values over all queries
    divided by the number of queries.

    Edge cases:
    - An empty list gives ``{}``.
    - Every dict must have the same set of metric names as the first one;
      otherwise ``ValueError`` is raised. This stops a metric from being averaged
      over a different number of queries from the others.
    - No rounding is applied.
    """
    if not per_query:
        return {}
    names = set(per_query[0])
    for index, row in enumerate(per_query):
        if set(row) != names:
            raise ValueError(
                f"query {index} has metrics {sorted(row)}, expected {sorted(names)}"
            )
    n = len(per_query)
    return {name: sum(row[name] for row in per_query) / n for name in per_query[0]}

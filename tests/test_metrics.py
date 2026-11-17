"""Tests for eval/metrics.py. Expected values are worked out by hand in comments."""

import math

import pytest

from eval.metrics import (
    accuracy,
    aggregate,
    average_precision,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
    set_prf,
)


# ---------------------------------------------------------------- precision_at_k

def test_precision_at_k_hand_worked():
    # ranked top 3 = a, b, c. relevant = {a, c, x}. Hits in top 3: a and c = 2.
    # precision = 2 / k = 2 / 3.
    assert precision_at_k(["a", "b", "c", "d", "e"], {"a", "c", "x"}, 3) == 2 / 3


def test_precision_at_k_divides_by_k_even_when_list_is_short():
    # Only 5 items ranked, k = 10. Hits = a and c = 2. precision = 2 / 10 = 0.2.
    assert precision_at_k(["a", "b", "c", "d", "e"], {"a", "c", "x"}, 10) == 2 / 10


def test_precision_at_k_empty_ranked_is_zero():
    assert precision_at_k([], {"a"}, 5) == 0.0


def test_precision_at_k_empty_relevant_is_zero():
    assert precision_at_k(["a", "b"], set(), 2) == 0.0


def test_precision_at_k_repeated_id_counted_once():
    # After removing the repeat, ranked = [a, b]. Top 2 both relevant.
    # precision = 2 / 2 = 1.0. Counting the repeat would give 3 / 2.
    assert precision_at_k(["a", "a", "b"], {"a", "b"}, 2) == 1.0


@pytest.mark.parametrize("k", [0, -1])
def test_precision_at_k_rejects_k_below_one(k):
    with pytest.raises(ValueError):
        precision_at_k(["a"], {"a"}, k)


# ------------------------------------------------------------------ recall_at_k

def test_recall_at_k_hand_worked():
    # ranked top 3 = a, b, c. relevant = {a, c, x, y} (4 items).
    # Hits in top 3: a and c = 2. recall = 2 / 4 = 0.5.
    assert recall_at_k(["a", "b", "c", "d"], {"a", "c", "x", "y"}, 3) == 0.5


def test_recall_at_k_empty_relevant_is_zero():
    assert recall_at_k(["a", "b"], set(), 2) == 0.0


def test_recall_at_k_empty_ranked_is_zero():
    assert recall_at_k([], {"a"}, 2) == 0.0


def test_recall_at_k_repeated_id_counted_once():
    # After removing the repeat, ranked = [a, c, b]; top 2 = [a, c], both relevant.
    # relevant has 3 items. recall = 2 / 3. Counting the repeat would give 1 / 3.
    assert recall_at_k(["a", "a", "c", "b"], {"a", "b", "c"}, 2) == 2 / 3


@pytest.mark.parametrize("k", [0, -3])
def test_recall_at_k_rejects_k_below_one(k):
    with pytest.raises(ValueError):
        recall_at_k(["a"], {"a"}, k)


# ------------------------------------------------------------ reciprocal_rank

def test_reciprocal_rank_hand_worked():
    # First relevant item is c, at rank 3 (a=1, b=2, c=3). RR = 1 / 3.
    assert reciprocal_rank(["a", "b", "c", "d"], {"c", "d"}) == 1 / 3


def test_reciprocal_rank_none_found_is_zero():
    assert reciprocal_rank(["a", "b"], {"z"}) == 0.0


def test_reciprocal_rank_empty_ranked_is_zero():
    assert reciprocal_rank([], {"a"}) == 0.0


def test_reciprocal_rank_empty_relevant_is_zero():
    assert reciprocal_rank(["a", "b"], set()) == 0.0


def test_reciprocal_rank_repeated_id_counted_once():
    # After removing the repeat, ranked = [x, c]. c is at rank 2. RR = 1 / 2.
    # Without removing the repeat, c would be at rank 3 and RR = 1 / 3.
    assert reciprocal_rank(["x", "x", "c"], {"c"}) == 0.5


# ---------------------------------------------------------- average_precision

def test_average_precision_hand_worked():
    # ranked = a, x, b, y. relevant = {a, b, c} (3 items).
    # a at rank 1: hits = 1, precision = 1 / 1 = 1.
    # b at rank 3: hits = 2, precision = 2 / 3.
    # c is never retrieved, so it adds nothing to the sum.
    # AP = (1 + 2/3) / 3 = (5/3) / 3 = 5/9.
    assert average_precision(["a", "x", "b", "y"], {"a", "b", "c"}) == pytest.approx(5 / 9)


def test_average_precision_empty_relevant_is_zero():
    assert average_precision(["a", "b"], set()) == 0.0


def test_average_precision_empty_ranked_is_zero():
    assert average_precision([], {"a"}) == 0.0


def test_average_precision_nothing_found_is_zero():
    assert average_precision(["x", "y"], {"a"}) == 0.0


def test_average_precision_repeated_id_counted_once():
    # After removing the repeat, ranked = [a, b].
    # a at rank 1: precision 1 / 1 = 1. b at rank 2: precision 2 / 2 = 1.
    # AP = (1 + 1) / 2 = 1.0. Counting the repeat would give 1.5.
    assert average_precision(["a", "a", "b"], {"a", "b"}) == 1.0


# ------------------------------------------------------------------ ndcg_at_k

def test_ndcg_binary_hand_worked():
    # Binary: relevance is a plain collection, so every relevant item has grade 1.
    # ranked = a, x, b. relevant = {a, b}. k = 3.
    # DCG: a at rank 1 gives 1 / log2(2) = 1. x gives 0. b at rank 3 gives 1 / log2(4) = 1/2.
    #      DCG = 1 + 1/2 = 1.5.
    # IDCG: the ideal order puts a and b at ranks 1 and 2.
    #       IDCG = 1 / log2(2) + 1 / log2(3) = 1 + 1 / log2(3).
    # nDCG = 1.5 / (1 + 1 / log2(3)).
    expected = 1.5 / (1 + 1 / math.log2(3))
    assert ndcg_at_k(["a", "x", "b"], {"a", "b"}, 3) == pytest.approx(expected)


def test_ndcg_graded_hand_worked():
    # Graded: ranked = a, b, c. relevance a=3, b=2, c=0, d=1. k = 3.
    # DCG: a at rank 1 gives 3 / log2(2) = 3. b at rank 2 gives 2 / log2(3).
    #      c at rank 3 has grade 0. DCG = 3 + 2 / log2(3).
    # IDCG: sorted grades are 3, 2, 1, 0. Top 3 give 3 + 2 / log2(3) + 1 / log2(4)
    #       = 3 + 2 / log2(3) + 1/2.
    # nDCG = (3 + 2 / log2(3)) / (3 + 2 / log2(3) + 1/2).
    dcg = 3 + 2 / math.log2(3)
    idcg = dcg + 0.5
    rel = {"a": 3, "b": 2, "c": 0, "d": 1}
    assert ndcg_at_k(["a", "b", "c"], rel, 3) == pytest.approx(dcg / idcg)


def test_ndcg_graded_out_of_order_hand_worked():
    # ranked = b, a. grades a=3, b=2. k = 2.
    # DCG: b at rank 1 gives 2 / 1 = 2. a at rank 2 gives 3 / log2(3).
    # IDCG: a first, then b: 3 / 1 + 2 / log2(3).
    rel = {"a": 3, "b": 2}
    dcg = 2 + 3 / math.log2(3)
    idcg = 3 + 2 / math.log2(3)
    assert ndcg_at_k(["b", "a"], rel, 2) == pytest.approx(dcg / idcg)


def test_ndcg_perfect_binary_ranking_is_exactly_one():
    assert ndcg_at_k(["a", "b", "c"], {"a", "b"}, 3) == 1.0


def test_ndcg_perfect_graded_ranking_is_exactly_one():
    # Sorted by grade, the ranking is already ideal, so the DCG and IDCG terms are identical.
    assert ndcg_at_k(["a", "b", "c"], {"a": 3, "b": 2, "c": 1}, 3) == 1.0


def test_ndcg_perfect_ranking_with_small_k_is_exactly_one():
    assert ndcg_at_k(["a", "b", "c"], {"a": 3, "b": 2, "c": 1}, 2) == 1.0


def test_ndcg_empty_relevance_is_zero():
    assert ndcg_at_k(["a", "b"], {}, 2) == 0.0
    assert ndcg_at_k(["a", "b"], set(), 2) == 0.0


def test_ndcg_all_zero_grades_is_zero():
    # IDCG = 0, so the result is 0.0 by definition.
    assert ndcg_at_k(["a"], {"a": 0}, 1) == 0.0


def test_ndcg_empty_ranked_is_zero():
    assert ndcg_at_k([], {"a"}, 3) == 0.0


def test_ndcg_no_relevant_retrieved_is_zero():
    # DCG = 0 because c has no grade. IDCG = 1 / log2(2) = 1. nDCG = 0 / 1 = 0.0.
    assert ndcg_at_k(["c"], {"a": 1}, 1) == 0.0


def test_ndcg_repeated_id_counted_once():
    # After removing the repeat, ranked = [a, b], which is perfect. nDCG = 1.0.
    assert ndcg_at_k(["a", "a", "b"], {"a", "b"}, 2) == 1.0


def test_ndcg_rejects_negative_grade():
    with pytest.raises(ValueError):
        ndcg_at_k(["a"], {"a": -1}, 1)


@pytest.mark.parametrize("k", [0, -2])
def test_ndcg_rejects_k_below_one(k):
    with pytest.raises(ValueError):
        ndcg_at_k(["a"], {"a"}, k)


# ------------------------------------------------------------------- set_prf

def test_set_prf_hand_worked():
    # predicted = {a, b, c} (3). gold = {a, b, d, e} (4). Intersection = {a, b}, tp = 2.
    # precision = 2 / 3. recall = 2 / 4 = 1/2.
    # f1 = 2 * (2/3) * (1/2) / ((2/3) + (1/2)) = (2/3) / (7/6) = 4/7.
    result = set_prf({"a", "b", "c"}, {"a", "b", "d", "e"})
    assert result["precision"] == pytest.approx(2 / 3)
    assert result["recall"] == pytest.approx(0.5)
    assert result["f1"] == pytest.approx(4 / 7)


def test_set_prf_identical_sets_are_perfect():
    assert set_prf({"a", "b"}, {"a", "b"}) == {"precision": 1.0, "recall": 1.0, "f1": 1.0}


def test_set_prf_both_empty_is_one():
    assert set_prf(set(), set()) == {"precision": 1.0, "recall": 1.0, "f1": 1.0}


@pytest.mark.parametrize(
    "predicted, gold",
    [(set(), {"a"}), ({"a"}, set())],
)
def test_set_prf_one_empty_is_zero(predicted, gold):
    assert set_prf(predicted, gold) == {"precision": 0.0, "recall": 0.0, "f1": 0.0}


def test_set_prf_disjoint_is_zero():
    assert set_prf({"a"}, {"b"}) == {"precision": 0.0, "recall": 0.0, "f1": 0.0}


def test_set_prf_duplicates_in_input_are_ignored():
    # Sets are {a, b} and {a}. tp = 1. precision = 1/2, recall = 1/1 = 1.
    # f1 = 2 * (1/2) * 1 / (1/2 + 1) = 1 / (3/2) = 2/3.
    result = set_prf(["a", "a", "b"], ["a"])
    assert result["precision"] == pytest.approx(0.5)
    assert result["recall"] == pytest.approx(1.0)
    assert result["f1"] == pytest.approx(2 / 3)


# ------------------------------------------------------------------ accuracy

def test_accuracy_hand_worked():
    # Positions 0, 2 and 3 match (a=a, c=c, d=d). Position 1 does not (b != x).
    # accuracy = 3 / 4 = 0.75.
    assert accuracy(["a", "b", "c", "d"], ["a", "x", "c", "d"]) == 0.75


def test_accuracy_all_match_is_one():
    assert accuracy([1, 2, 3], [1, 2, 3]) == 1.0


def test_accuracy_none_match_is_zero():
    assert accuracy(["a", "b"], ["b", "a"]) == 0.0


def test_accuracy_empty_is_zero():
    assert accuracy([], []) == 0.0


def test_accuracy_length_mismatch_raises():
    with pytest.raises(ValueError):
        accuracy(["a", "b"], ["a"])


# ----------------------------------------------------------------- aggregate

def test_aggregate_hand_worked():
    # p: (0.5 + 0.25) / 2 = 0.75 / 2 = 0.375. r: (1.0 + 0.0) / 2 = 0.5.
    rows = [{"p": 0.5, "r": 1.0}, {"p": 0.25, "r": 0.0}]
    assert aggregate(rows) == {"p": 0.375, "r": 0.5}


def test_aggregate_three_queries():
    # f1: (0.2 + 0.4 + 0.9) / 3 = 1.5 / 3 = 0.5.
    rows = [{"f1": 0.2}, {"f1": 0.4}, {"f1": 0.9}]
    assert aggregate(rows)["f1"] == pytest.approx(0.5)


def test_aggregate_empty_list_is_empty_dict():
    assert aggregate([]) == {}


def test_aggregate_single_query_returns_same_values():
    assert aggregate([{"p": 0.3}]) == {"p": 0.3}


def test_aggregate_does_not_round():
    # mean = (1/3 + 0) / 2 = 1/6. Compared exactly, so any rounding would fail.
    assert aggregate([{"x": 1 / 3}, {"x": 0.0}]) == {"x": (1 / 3 + 0.0) / 2}


def test_aggregate_mismatched_keys_raise():
    with pytest.raises(ValueError):
        aggregate([{"p": 0.1}, {"p": 0.2, "r": 0.3}])

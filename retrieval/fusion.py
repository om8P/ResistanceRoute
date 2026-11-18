"""Fusion helpers for the answer builder (T14).

* ``rrf``: reciprocal rank fusion over ranked ID lists (D14, k = 60).
* ``fuse_passages``: RRF over lists of ``PassageHit``.
* ``text_baseline_answers``: answer entities taken from the linked mentions of the
  top passages, for the three text-only modes (the baselines).
* ``split_recommended`` and ``rerank_graph_answers``: the D39 split and the hybrid
  re-ranking of graph answers.
"""
from __future__ import annotations

import csv
import json
from collections import OrderedDict
from dataclasses import replace
from functools import lru_cache
from typing import Iterable, Mapping, Sequence

from retrieval.build_index import PROCESSED
from retrieval.types import Answer, PassageHit

RRF_K = 60
ACTIVE_SCORE = 0.5  # graph_search: score >= 0.5 means the drug is active on its own

# Entity type a text-only mode extracts for each intent. This is what the parser says the
# question asks for, so the baselines use the same information the graph modes get.
TARGET_TYPES: dict[str, tuple[str, ...]] = {
    "alternatives": ("Drug",),
    "recommendation_lookup": ("Drug",),
    "why_restricted": ("Mechanism",),
    "mechanism_lookup": ("Mechanism",),
    "drug_profile": ("DrugClass",),
    "surveillance": ("Drug",),
}


def rrf(rankings: Sequence[Sequence[str]], k: int = RRF_K) -> list[tuple[str, float]]:
    """score(x) = sum over lists of 1 / (k + rank), ranks from 1; ties keep first-seen order."""
    scores: dict[str, float] = OrderedDict()
    for ranking in rankings:
        seen: set[str] = set()
        for rank, item in enumerate(ranking, start=1):
            if item in seen:
                continue
            seen.add(item)
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: -kv[1])  # stable


def fuse_passages(lists: Sequence[Sequence[PassageHit]], k: int = 10, rrf_k: int = RRF_K) -> list[PassageHit]:
    """RRF over several ranked passage lists. Returns hits with the fused score and a new rank."""
    first: dict[str, PassageHit] = {}
    for lst in lists:
        for h in lst:
            first.setdefault(h.passage_id, h)
    fused = rrf([[h.passage_id for h in lst] for lst in lists], rrf_k)
    return [replace(first[pid], score=score, rank=i) for i, (pid, score) in enumerate(fused[:k], start=1)]


@lru_cache(maxsize=1)
def mentions_by_passage() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    path = PROCESSED / "mentions_linked.jsonl"
    if not path.exists():
        return out
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                m = json.loads(line)
                out.setdefault(m["passage_id"], []).append(m)
    return out


@lru_cache(maxsize=1)
def drug_meta() -> dict[str, dict]:
    path = PROCESSED / "nodes_Drug.csv"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8", newline="") as fh:
        return {r["id"]: r for r in csv.DictReader(fh)}


def text_baseline_answers(
    hits: Sequence[PassageHit],
    intent: str,
    exclude_ids: Iterable[str] = (),
    mentions: Mapping[str, list[dict]] | None = None,
    limit: int = 20,
) -> list[Answer]:
    """Answer entities of the type ``intent`` asks for, from the linked mentions of ``hits``.

    Each passage counts once per entity; an entity scores the sum of 1 / (60 + passage rank)
    over the passages that mention it. Entities the question already names are skipped.
    """
    types = TARGET_TYPES.get(intent)
    if not types:
        return []
    mentions = mentions if mentions is not None else mentions_by_passage()
    excluded = set(exclude_ids)
    scores: dict[str, float] = OrderedDict()
    names: dict[str, str] = {}
    labels: dict[str, str] = {}
    for rank, hit in enumerate(hits, start=1):
        seen: set[str] = set()
        for m in mentions.get(hit.passage_id, []):
            eid = m.get("entity_id")
            if not eid or m.get("entity_type") not in types or eid in excluded or eid in seen:
                continue
            seen.add(eid)
            scores[eid] = scores.get(eid, 0.0) + 1.0 / (RRF_K + rank)
            names.setdefault(eid, m.get("canonical_name") or m.get("surface") or eid)
            labels.setdefault(eid, m["entity_type"])
    dm = drug_meta()
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])[:limit]
    return [
        Answer(
            id=eid,
            label=labels[eid],
            name=names[eid],
            aware_group=(dm.get(eid, {}).get("aware_group") or "") if labels[eid] == "Drug" else "",
            score=score,
        )
        for eid, score in ranked
    ]


def is_recommended(a: Answer) -> bool:
    """D39: a guideline-recommended answer has at least one supporting recommendation."""
    return bool(a.recommendation_ids)


def split_recommended(answers: Sequence[Answer], active_score: float = 0.5) -> tuple[list[Answer], list[Answer]]:
    """D39 for ``alternatives``: (guideline-recommended, merely not excluded).

    Answers that are neither recommended nor active (score below ``active_score``) are dropped.
    """
    rec = [a for a in answers if is_recommended(a)]
    other = [a for a in answers if not is_recommended(a) and a.score >= active_score]
    return rec, other


def rerank_graph_answers(
    answers: Sequence[Answer],
    support: Mapping[str, int] | None = None,
    use_support: bool = True,
) -> list[Answer]:
    """Hybrid order: groups keep their first-seen order; inside a group guideline-recommended drugs
    come first, then more supporting passages, then the graph score. Graph mode passes
    ``use_support=False`` and keeps the graph's score order (line of therapy)."""
    support = support or {}
    group_pos: dict[str, int] = {}
    for a in answers:
        group_pos.setdefault(a.group, len(group_pos))

    def key(item: tuple[int, Answer]):
        i, a = item
        sup = -support.get(a.id, 0) if use_support else 0
        # recommended first; among those, drugs active on their own before drugs a guideline keeps
        # only through a mechanism-specific rescue (D34, score below ACTIVE_SCORE), then support
        return (group_pos[a.group], not is_recommended(a), a.score < ACTIVE_SCORE, sup, -a.score, i)

    return [a for _, a in sorted(enumerate(answers), key=key)]


def support_count(answer: Answer, links: Mapping[str, Mapping[str, int]], passage_ids: Iterable[str]) -> int:
    """Number of passages in ``passage_ids`` linked to the answer or to one of its recommendations."""
    pool = set(passage_ids)
    linked: set[str] = set()
    for eid in [answer.id, *answer.recommendation_ids]:
        linked.update(p for p in links.get(eid, {}) if p in pool)
    return len(linked)

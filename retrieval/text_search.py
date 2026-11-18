"""Text search over guideline passages (T11): BM25, dense, and their fusion.

    python -m retrieval.text_search "<query>" --mode bm25_dense [-k 10] [--entity ID ...]

``search`` and ``passages_for_entities`` follow CONTRACTS section 7. Entity
filtering reads ``mentions_linked.jsonl`` and ``edges_SUPPORTS.csv`` directly,
so Neo4j is not needed.
"""
from __future__ import annotations

import argparse
import csv
import json
import pickle
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from retrieval.build_index import EF_SEARCH, INDEX_DIR, MODEL_NAME, PASSAGES_PATH, PROCESSED, tokenize

try:  # shared dataclass from T12
    from retrieval.types import PassageHit  # type: ignore
except ImportError:  # pragma: no cover - until retrieval/types.py exists
    from dataclasses import dataclass

    @dataclass
    class PassageHit:
        passage_id: str
        score: float
        rank: int
        text: str
        source_doc: str
        section: str
        page: int | None = None


MODES = ("bm25", "dense", "bm25_dense")
RRF_K = 60
POOL = 100  # candidates taken from each list before fusion


def rrf(rankings: list[list[str]], k: int = RRF_K) -> list[tuple[str, float]]:
    """Reciprocal rank fusion: score(p) = sum 1 / (k + rank_i(p)), ranks from 1.

    Ties are broken by the order of first appearance across the lists.
    """
    scores: dict[str, float] = {}
    for ranking in rankings:
        seen: set[str] = set()
        for rank, pid in enumerate(ranking, start=1):
            if pid in seen:
                continue
            seen.add(pid)
            scores[pid] = scores.get(pid, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: -kv[1])  # sorted() is stable


class TextIndex:
    def __init__(
        self,
        index_dir: Path = INDEX_DIR,
        passages_path: Path = PASSAGES_PATH,
        mentions_path: Path = PROCESSED / "mentions_linked.jsonl",
        supports_path: Path = PROCESSED / "edges_SUPPORTS.csv",
    ):
        self.index_dir = Path(index_dir)
        self.passages_path = Path(passages_path)
        self.mentions_path = Path(mentions_path)
        self.supports_path = Path(supports_path)
        self._passages: list[dict] | None = None
        self._bm25 = None
        self._faiss = None
        self._emb = None
        self._model = None
        self._links: dict[str, Counter] | None = None  # entity_id -> Counter(passage_id)

    # -- loading ---------------------------------------------------------
    @property
    def passages(self) -> list[dict]:
        if self._passages is None:
            with open(self.passages_path, encoding="utf-8") as fh:
                self._passages = [json.loads(line) for line in fh if line.strip()]
            self._row = {p["id"]: i for i, p in enumerate(self._passages)}
        return self._passages

    @property
    def row(self) -> dict[str, int]:
        self.passages
        return self._row

    def _check_ids(self) -> None:
        with open(self.index_dir / "passage_ids.json", encoding="utf-8") as fh:
            ids = json.load(fh)
        if ids != [p["id"] for p in self.passages]:
            raise RuntimeError("index is out of date with passages.jsonl; run python -m retrieval.build_index")

    @property
    def bm25(self):
        if self._bm25 is None:
            self._check_ids()
            with open(self.index_dir / "bm25.pkl", "rb") as fh:
                self._bm25 = pickle.load(fh)
        return self._bm25

    @property
    def faiss_index(self):
        if self._faiss is None:
            import faiss

            self._check_ids()
            self._faiss = faiss.read_index(str(self.index_dir / "dense.faiss"))
            self._faiss.hnsw.efSearch = EF_SEARCH
        return self._faiss

    @property
    def embeddings(self) -> np.ndarray:
        if self._emb is None:
            self._emb = np.load(self.index_dir / "embeddings.npy")
        return self._emb

    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            try:
                name = json.load(open(self.index_dir / "meta.json", encoding="utf-8"))["dense"]["model"]
            except (OSError, KeyError):
                name = MODEL_NAME
            import torch

            self._model = SentenceTransformer(name, device="cuda" if torch.cuda.is_available() else "cpu")
        return self._model

    @property
    def links(self) -> dict[str, Counter]:
        """entity_id -> Counter of passage_id (count = number of mentions, or 1 per SUPPORTS edge)."""
        if self._links is None:
            links: dict[str, Counter] = defaultdict(Counter)
            if self.mentions_path.exists():
                with open(self.mentions_path, encoding="utf-8") as fh:
                    for line in fh:
                        if line.strip():
                            m = json.loads(line)
                            links[m["entity_id"]][m["passage_id"]] += 1
            if self.supports_path.exists():
                with open(self.supports_path, encoding="utf-8", newline="") as fh:
                    for r in csv.DictReader(fh):
                        links[r["end_id"]][r["start_id"]] += 1
            self._links = dict(links)
        return self._links

    # -- candidate lists -------------------------------------------------
    def _allowed_rows(self, entity_ids: list[str] | None) -> np.ndarray | None:
        if not entity_ids:
            return None
        pids: set[str] = set()
        for e in entity_ids:
            pids.update(self.links.get(e, {}))
        return np.array(sorted(self.row[p] for p in pids if p in self.row), dtype=int)

    def _bm25_ranking(self, query: str, allowed: np.ndarray | None, depth: int) -> list[int]:
        toks = tokenize(query)
        if not toks:
            return []
        scores = np.asarray(self.bm25.get_scores(toks))
        if allowed is not None:
            cand = allowed
        else:
            cand = np.arange(len(scores))
        cand = cand[scores[cand] > 0]
        order = np.argsort(-scores[cand], kind="stable")
        return [int(i) for i in cand[order][:depth]]

    def _dense_ranking(self, query: str, allowed: np.ndarray | None, depth: int) -> list[int]:
        q = self.model.encode([query], normalize_embeddings=True, convert_to_numpy=True).astype("float32")
        if allowed is None:
            _, idx = self.faiss_index.search(q, depth)
            return [int(i) for i in idx[0] if i >= 0]
        if len(allowed) == 0:
            return []
        sims = self.embeddings[allowed] @ q[0]  # exact, on the allowed subset
        order = np.argsort(-sims, kind="stable")
        return [int(i) for i in allowed[order][:depth]]

    def _hit(self, row: int, score: float, rank: int) -> PassageHit:
        p = self.passages[row]
        return PassageHit(
            passage_id=p["id"],
            score=float(score),
            rank=rank,
            text=p["text"],
            source_doc=p["source_doc"],
            section=p["section"],
            page=p.get("page"),
        )

    # -- public ----------------------------------------------------------
    def search(self, query: str, mode: str, k: int = 10, entity_ids: list[str] | None = None) -> list[PassageHit]:
        if mode not in MODES:
            raise ValueError(f"unknown mode {mode!r}; expected one of {MODES}")
        if k <= 0 or not query.strip():
            return []
        allowed = self._allowed_rows(entity_ids)
        depth = max(POOL, k)
        if mode == "bm25":
            rows = self._bm25_ranking(query, allowed, k)
            scores = np.asarray(self.bm25.get_scores(tokenize(query)))
            return [self._hit(r, scores[r], i) for i, r in enumerate(rows, 1)]
        if mode == "dense":
            rows = self._dense_ranking(query, allowed, k)
            q = self.model.encode([query], normalize_embeddings=True, convert_to_numpy=True).astype("float32")[0]
            return [self._hit(r, float(self.embeddings[r] @ q), i) for i, r in enumerate(rows, 1)]
        b = self._bm25_ranking(query, allowed, depth)
        d = self._dense_ranking(query, allowed, depth)
        fused = rrf([[self.passages[r]["id"] for r in b], [self.passages[r]["id"] for r in d]])[:k]
        return [self._hit(self.row[pid], s, i) for i, (pid, s) in enumerate(fused, 1)]

    def passages_for_entities(self, entity_ids: list[str], k: int) -> list[PassageHit]:
        """Passages linked to the entities by MENTIONS or SUPPORTS, most-connected first.

        Score = number of distinct requested entities linked to the passage;
        ties go to the larger number of mentions, then to corpus order.
        """
        if k <= 0:
            return []
        distinct: Counter = Counter()
        total: Counter = Counter()
        for e in dict.fromkeys(entity_ids):
            for pid, n in self.links.get(e, {}).items():
                if pid in self.row:
                    distinct[pid] += 1
                    total[pid] += n
        ranked = sorted(distinct, key=lambda p: (-distinct[p], -total[p], self.row[p]))[:k]
        return [self._hit(self.row[p], distinct[p], i) for i, p in enumerate(ranked, 1)]


_default: TextIndex | None = None


def get_index() -> TextIndex:
    global _default
    if _default is None:
        _default = TextIndex()
    return _default


def search(query: str, mode: str, k: int = 10, entity_ids: list[str] | None = None) -> list[PassageHit]:
    return get_index().search(query, mode, k, entity_ids)


def passages_for_entities(entity_ids: list[str], k: int) -> list[PassageHit]:
    return get_index().passages_for_entities(entity_ids, k)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Search guideline passages.")
    ap.add_argument("query")
    ap.add_argument("--mode", choices=MODES, default="bm25_dense")
    ap.add_argument("-k", type=int, default=5)
    ap.add_argument("--entity", action="append", help="restrict to passages mentioning this entity ID (repeatable)")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):  # Windows consoles default to cp1252
        sys.stdout.reconfigure(errors="replace")
    for h in search(args.query, args.mode, args.k, args.entity):
        text = " ".join(h.text.split())
        print(f"{h.rank:>2}. {h.score:.4f}  {h.passage_id}  (p{h.page})")
        print(f"    {text[:220]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

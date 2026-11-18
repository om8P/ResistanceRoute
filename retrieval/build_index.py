"""Build the BM25 and dense (FAISS HNSW) passage indexes (T11, D11).

    python -m retrieval.build_index

Writes to ``data/processed/index/``: ``bm25.pkl``, ``dense.faiss``,
``embeddings.npy``, ``passage_ids.json`` and ``meta.json``.
Passage text is indexed as stored in ``passages.jsonl``, including the
30-word overlap with the previous passage.
"""
from __future__ import annotations

import argparse
import json
import pickle
import re
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
PASSAGES_PATH = PROCESSED / "passages.jsonl"
INDEX_DIR = PROCESSED / "index"

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
HNSW_M = 32
EF_CONSTRUCTION = 200
EF_SEARCH = 128

STOPWORDS = frozenset(
    "a an and are as at be by for from has have in is it its of on or that the "
    "this to was were which with".split()
)

# A word, optionally joined by hyphens, slashes or plus signs: ceftazidime-avibactam, OXA-48, TMP/SMX.
_COMPOUND = re.compile(r"[^\W_]+(?:[-/+][^\W_]+)*", re.UNICODE)
_PART = re.compile(r"[-/+]")


def tokenize(text: str) -> list[str]:
    """Lower-case tokens; a hyphenated or slashed name gives the whole name and its parts.

    ``"Ceftazidime-avibactam"`` -> ``["ceftazidime-avibactam", "ceftazidime", "avibactam"]``.
    Stop words are removed (also as parts); the order follows the text.
    """
    tokens: list[str] = []
    for match in _COMPOUND.finditer(text.lower()):
        word = match.group(0)
        parts = _PART.split(word)
        if len(parts) > 1:
            tokens.append(word)
        for part in parts:
            if part and part not in STOPWORDS:
                tokens.append(part)
        if len(parts) == 1 and word in STOPWORDS:
            continue
    return tokens


def load_passages(path: Path = PASSAGES_PATH) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def build(passages_path: Path = PASSAGES_PATH, index_dir: Path = INDEX_DIR, batch_size: int = 64) -> dict:
    import faiss
    import numpy as np
    import torch
    from rank_bm25 import BM25Okapi
    from sentence_transformers import SentenceTransformer

    t0 = time.time()
    passages = load_passages(passages_path)
    ids = [p["id"] for p in passages]
    index_dir.mkdir(parents=True, exist_ok=True)

    # Sparse.
    t = time.time()
    tokenized = [tokenize(p["text"]) for p in passages]
    bm25 = BM25Okapi(tokenized)
    with open(index_dir / "bm25.pkl", "wb") as fh:
        pickle.dump(bm25, fh, protocol=pickle.HIGHEST_PROTOCOL)
    bm25_seconds = time.time() - t

    # Dense.
    t = time.time()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = SentenceTransformer(MODEL_NAME, device=device)
    emb = model.encode(
        [p["text"] for p in passages],
        batch_size=batch_size,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    ).astype("float32")
    dim = emb.shape[1]
    index = faiss.IndexHNSWFlat(dim, HNSW_M, faiss.METRIC_INNER_PRODUCT)
    index.hnsw.efConstruction = EF_CONSTRUCTION
    index.add(emb)
    faiss.write_index(index, str(index_dir / "dense.faiss"))
    np.save(index_dir / "embeddings.npy", emb)
    dense_seconds = time.time() - t

    with open(index_dir / "passage_ids.json", "w", encoding="utf-8") as fh:
        json.dump(ids, fh)

    meta = {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_passages": len(passages),
        "source": str(passages_path.relative_to(ROOT)) if passages_path.is_relative_to(ROOT) else str(passages_path),
        "text_indexed": "passage text as stored (includes the 30-word overlap)",
        "bm25": {
            "library": "rank_bm25.BM25Okapi",
            "k1": bm25.k1,
            "b": bm25.b,
            "epsilon": bm25.epsilon,
            "n_tokens": int(sum(len(t_) for t_ in tokenized)),
            "vocabulary_size": len(bm25.idf),
            "stopwords": sorted(STOPWORDS),
        },
        "dense": {
            "model": MODEL_NAME,
            "device": device,
            "dim": int(dim),
            "normalized": True,
            "faiss_index": "IndexHNSWFlat",
            "metric": "inner_product",
            "M": HNSW_M,
            "efConstruction": EF_CONSTRUCTION,
            "efSearch": EF_SEARCH,
        },
        "fusion": {"method": "reciprocal_rank_fusion", "k": 60},
        "seconds": {
            "bm25": round(bm25_seconds, 2),
            "dense": round(dense_seconds, 2),
            "total": round(time.time() - t0, 2),
        },
        "files": {
            name: (index_dir / name).stat().st_size
            for name in ("bm25.pkl", "dense.faiss", "embeddings.npy", "passage_ids.json")
        },
    }
    with open(index_dir / "meta.json", "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)
    return meta


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build BM25 and FAISS passage indexes.")
    ap.add_argument("--passages", type=Path, default=PASSAGES_PATH)
    ap.add_argument("--out-dir", type=Path, default=INDEX_DIR)
    args = ap.parse_args(argv)
    if not args.passages.exists():
        print(f"missing {args.passages}; run python -m pipeline.ingest first")
        return 1
    meta = build(args.passages, args.out_dir)
    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

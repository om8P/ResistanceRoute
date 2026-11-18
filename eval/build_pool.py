"""Build the judgement pool for the evaluation questions (T15).

    python -m eval.build_pool [--out POOL.json] [--qrels eval/qrels.json]

For each question in ``eval/questions.json`` the pool is the union of

- the top ``DEPTH`` passages from each text mode (``bm25``, ``dense``,
  ``bm25_dense``) in ``retrieval.text_search.search``;
- the top ``DEPTH`` passages linked to the question's gold entities
  (``passages_for_entities``), method ``entities``;
- every passage that covers a guideline page cited in ``gold_source``
  (``<doc id> p<PDF page>``), method ``gold_page``;
- passages found by a targeted search of the corpus (``MANUAL``), method
  ``manual``.

Each pooled passage records the methods that contributed it, so the notes can
say how many relevant passages each method found. Judging is done by a person
reading the passages; the grades are stored in ``eval/qrels.json``. With
``--qrels`` the script prints the per-question and per-method statistics used
in ``eval/QRELS_NOTES.md``.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS_PATH = ROOT / "eval" / "questions.json"
QRELS_PATH = ROOT / "eval" / "qrels.json"
PASSAGES_PATH = ROOT / "data" / "processed" / "passages.jsonl"

DEPTH = 20
TEXT_MODES = ("bm25", "dense", "bm25_dense")
METHODS = TEXT_MODES + ("entities", "gold_page", "manual")
# Passages added by a targeted search of the whole corpus, outside the
# automatic pool. The brief asks for a specific search for Q23 (ceftaroline):
# only 4 of 1,428 passages mention ceftaroline, and this one was not pooled.
MANUAL = {"Q23": ["pubmed-40887577:abstract:1"]}
PAGE_SOURCE = re.compile(r"^(?P<doc>[a-z0-9-]+) p(?P<page>\d+)$")


def load_questions(path: Path = QUESTIONS_PATH) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_passages(path: Path = PASSAGES_PATH) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def gold_pages(question: dict) -> list[tuple[str, int]]:
    """(doc id, PDF page) for each guideline page cited in ``gold_source``."""
    out = []
    for src in question.get("gold_source", []):
        m = PAGE_SOURCE.match(src.strip())
        if m:
            out.append((m["doc"], int(m["page"])))
    return out


def page_spans(passages: list[dict]) -> dict[str, tuple[str, int, int]]:
    """Passage id -> (doc, first page, last page it may reach).

    Passages store only their start page. A passage is taken to run up to the
    start page of the next passage in the same document, so a passage that
    starts at the foot of page p-1 also counts as covering page p.
    """
    by_doc: dict[str, list[dict]] = defaultdict(list)
    for p in passages:
        if p.get("page") is not None:
            by_doc[p["source_doc"]].append(p)
    spans = {}
    for doc, ps in by_doc.items():
        for i, p in enumerate(ps):  # corpus order is document order
            end = ps[i + 1]["page"] if i + 1 < len(ps) else p["page"]
            spans[p["id"]] = (doc, p["page"], max(p["page"], end))
    return spans


def passages_on_pages(pages: list[tuple[str, int]], spans: dict[str, tuple[str, int, int]]) -> list[str]:
    hits = []
    for pid, (doc, first, last) in spans.items():
        if any(doc == d and first <= pg <= last for d, pg in pages):
            hits.append(pid)
    return hits


def build_pool(questions: list[dict], passages: list[dict], depth: int = DEPTH) -> dict[str, dict[str, list[str]]]:
    """{question id: {passage id: [methods]}}, methods in METHODS order."""
    from retrieval import text_search  # loads models lazily

    spans = page_spans(passages)
    pool: dict[str, dict[str, list[str]]] = {}
    for q in questions:
        found: dict[str, list[str]] = {}

        def add(pid: str, method: str) -> None:
            ms = found.setdefault(pid, [])
            if method not in ms:
                ms.append(method)

        for mode in TEXT_MODES:
            for hit in text_search.search(q["question"], mode, k=depth):
                add(hit.passage_id, mode)
        if q.get("entities"):
            for hit in text_search.passages_for_entities(q["entities"], k=depth):
                add(hit.passage_id, "entities")
        for pid in passages_on_pages(gold_pages(q), spans):
            add(pid, "gold_page")
        for pid in MANUAL.get(q["id"], []):
            add(pid, "manual")
        pool[q["id"]] = {pid: sorted(ms, key=METHODS.index) for pid, ms in found.items()}
    return pool


def stats(pool: dict[str, dict[str, list[str]]], qrels: dict[str, dict[str, int]]) -> dict:
    """Per-question pool size and grade counts, and relevant passages per method."""
    per_q = {}
    pooled_by: Counter = Counter()
    by_method: dict[str, Counter] = {m: Counter() for m in METHODS}
    only_by: Counter = Counter()
    not_pooled = []
    for qid, cands in pool.items():
        grades = qrels.get(qid, {})
        c = Counter(grades.values())
        per_q[qid] = {"pool": len(cands), "grade2": c[2], "grade1": c[1], "grade0": len(cands) - c[2] - c[1]}
        for ms in cands.values():
            pooled_by.update(ms)
        for pid, g in grades.items():
            ms = cands.get(pid)
            if ms is None:
                not_pooled.append(f"{qid} {pid}")
                continue
            for m in ms:
                by_method[m][g] += 1
            if len(ms) == 1:
                only_by[ms[0]] += 1
    return {
        "per_question": per_q,
        "pooled_by_method": dict(pooled_by),
        "relevant_by_method": {m: {"grade2": c[2], "grade1": c[1]} for m, c in by_method.items()},
        "relevant_only_by": dict(only_by),
        "judged_but_not_pooled": not_pooled,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build the relevance-judgement pool.")
    ap.add_argument("--out", type=Path, help="write the pool as JSON here")
    ap.add_argument("--qrels", type=Path, help="print statistics for these judgements")
    ap.add_argument("--depth", type=int, default=DEPTH)
    args = ap.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    pool = build_pool(load_questions(), load_passages(), args.depth)
    if args.out:
        args.out.write_text(json.dumps(pool, indent=1), encoding="utf-8")
    sizes = [len(v) for v in pool.values()]
    print(f"{len(pool)} questions, pool sizes {min(sizes)}-{max(sizes)}, total {sum(sizes)}")
    if args.qrels:
        qrels = json.loads(args.qrels.read_text(encoding="utf-8"))
        print(json.dumps(stats(pool, qrels), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

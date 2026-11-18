"""Evaluate rule-based recommendation extraction against the curated recommendations (T13).

Matching is one-to-one and greedy (highest confidence first). Two levels:

* **strict** (the headline): same guideline, same pathogen, same set of mechanisms, same set of
  drugs, and source pages at most 1 apart.
* **lenient**: same guideline, pathogen and mechanisms, pages within 1, and the drug sets overlap
  with Jaccard >= 0.5 (so one missing or extra partner drug does not break a match).

Precision, recall and F1 come from ``eval.metrics.set_prf``: the predicted set holds, for each
extraction, the ID of the curated row it matched (or a unique ``FP:n`` key); the gold set holds the
curated IDs. They are reported overall, per guideline and per field. A field score uses only that
field (plus guideline and page) to match, so it shows how well each field is extracted on its own.

Usage: ``python -m eval.extraction_eval [--extracted PATH] [--out PATH]``
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable

from eval.metrics import set_prf
from pipeline.extract import OUT_PATH, PASSAGES_PATH, Extractor, load_passages
from pipeline.models import RecommendationExtraction

ROOT = Path(__file__).resolve().parent.parent
GOLD_PATH = ROOT / "data" / "curated" / "recommendations_curated.csv"
RESULT_PATH = ROOT / "eval" / "results" / "extraction_eval.json"
DEV_SET = "icmr-treatment-guidelines-2019"
PAGE_TOLERANCE = 1
FIELDS = ("pathogen", "mechanism", "drugs", "line_of_therapy")


def load_gold(path: Path = GOLD_PATH) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf8", newline="") as fh:
        for r in csv.DictReader(fh):
            rows.append(
                {
                    "id": r["rec_id"],
                    "guideline": r["guideline_id"],
                    "pathogen": r["pathogen_id"],
                    "mechanism": frozenset(x for x in r["mechanism_id"].split("|") if x),
                    "drugs": frozenset(x for x in r["drug_ids"].split("|") if x),
                    "line_of_therapy": r["line_of_therapy"],
                    "page": int(r["source_page"]),
                    "text": r["text"],
                }
            )
    return rows


def load_predictions(
    extracted: list[RecommendationExtraction], extractor: Extractor, passages: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    out = []
    for i, rec in enumerate(extracted):
        p = passages[rec.passage_id]
        ids = extractor.resolve_ids(rec)
        out.append(
            {
                "id": f"EXT:{i:04d}",
                "guideline": p["source_doc"],
                "pathogen": ids["pathogen_id"],
                "mechanism": frozenset(ids["mechanism_ids"]),
                "drugs": frozenset(ids["drug_ids"]),
                "line_of_therapy": ids["line_of_therapy"] or "",
                "page": p.get("page") or 0,
                "confidence": rec.confidence or 0.0,
                "passage_id": rec.passage_id,
                "evidence": rec.evidence_text,
            }
        )
    return out


# ----------------------------------------------------------------------------- matching


def _jaccard(a: frozenset, b: frozenset) -> float:
    return len(a & b) / len(a | b) if (a | b) else 0.0


def _base(p: dict, g: dict) -> bool:
    return p["guideline"] == g["guideline"] and abs(p["page"] - g["page"]) <= PAGE_TOLERANCE


Matcher = Callable[[dict, dict], bool]
MATCHERS: dict[str, Matcher] = {
    "strict": lambda p, g: _base(p, g)
    and p["pathogen"] == g["pathogen"]
    and p["mechanism"] == g["mechanism"]
    and p["drugs"] == g["drugs"],
    "lenient": lambda p, g: _base(p, g)
    and p["pathogen"] == g["pathogen"]
    and p["mechanism"] == g["mechanism"]
    and _jaccard(p["drugs"], g["drugs"]) >= 0.5,
    "field:pathogen": lambda p, g: _base(p, g) and p["pathogen"] == g["pathogen"],
    "field:mechanism": lambda p, g: _base(p, g) and p["mechanism"] == g["mechanism"],
    "field:drugs": lambda p, g: _base(p, g) and p["drugs"] == g["drugs"],
    "field:line_of_therapy": lambda p, g: _base(p, g) and p["line_of_therapy"] == g["line_of_therapy"],
}


def match(preds: list[dict], gold: list[dict], matcher: Matcher) -> dict[str, str]:
    """Greedy one-to-one matching. Returns ``{prediction id: gold id}``."""
    used: set[str] = set()
    pairs: dict[str, str] = {}
    for p in sorted(preds, key=lambda x: (-x["confidence"], x["id"])):
        for g in gold:
            if g["id"] not in used and matcher(p, g):
                used.add(g["id"])
                pairs[p["id"]] = g["id"]
                break
    return pairs


def score(preds: list[dict], gold: list[dict], matcher: Matcher) -> dict[str, Any]:
    pairs = match(preds, gold, matcher)
    predicted = {pairs.get(p["id"], f"FP:{p['id']}") for p in preds}
    prf = set_prf(predicted, {g["id"] for g in gold})
    return {
        "n_extracted": len(preds),
        "n_gold": len(gold),
        "true_positives": len(pairs),
        **{k: round(v, 4) for k, v in prf.items()},
    }


def score_block(preds: list[dict], gold: list[dict]) -> dict[str, Any]:
    return {
        "strict": score(preds, gold, MATCHERS["strict"]),
        "lenient": score(preds, gold, MATCHERS["lenient"]),
        "fields": {f: score(preds, gold, MATCHERS[f"field:{f}"]) for f in FIELDS},
    }


# ----------------------------------------------------------------------------- error analysis


def _diagnose(own: dict, others: list[dict], missing_label: str, own_is_gold: bool) -> str:
    """Why ``own`` has no strict match among ``others`` (rows of the other kind).

    Labels always describe the extraction: "too small" means it lacks a drug the curated row has.
    """
    near = [o for o in others if _base(own, o)]
    if not near:
        return missing_label
    same_path = [o for o in near if o["pathogen"] == own["pathogen"]]
    if not same_path:
        return "pathogen not found or wrong"
    same_mech = [o for o in same_path if o["mechanism"] == own["mechanism"]]
    if not same_mech:
        return "mechanism missing or wrong"
    small, large = "drug set too small (a drug is missing)", "drug set too large (extra drug)"
    if own_is_gold:
        small, large = large, small  # a gold row inside the extraction means the extraction has extras
    if any(own["drugs"] < o["drugs"] for o in same_mech):
        return small
    if any(own["drugs"] > o["drugs"] for o in same_mech):
        return large
    if any(_jaccard(own["drugs"], o["drugs"]) > 0 for o in same_mech):
        return "drug sets partly overlap"
    return "different drugs"


def fn_cause(g: dict, preds: list[dict]) -> str:
    return _diagnose(g, preds, "nothing extracted on this page", own_is_gold=True)


def fp_cause(p: dict, gold: list[dict]) -> str:
    return _diagnose(
        p, gold, "no curated row on this page (may be a real recommendation that was not curated)", own_is_gold=False
    )


def pick(items: list[dict], n: int = 10) -> list[dict]:
    """Round-robin over causes (largest first) so the sample shows every cause."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        groups[it["cause"]].append(it)
    ordered = sorted(groups.values(), key=len, reverse=True)
    out: list[dict] = []
    i = 0
    while len(out) < min(n, len(items)):
        for g in ordered:
            if i < len(g) and len(out) < n:
                out.append(g[i])
        i += 1
    return out


def error_analysis(preds: list[dict], gold: list[dict], passages: dict[str, dict], names: Callable[[str], str]) -> dict:
    pairs = match(preds, gold, MATCHERS["strict"])
    matched_gold = set(pairs.values())
    fps = [
        {
            "id": p["id"],
            "cause": fp_cause(p, gold),
            "guideline": p["guideline"],
            "page": p["page"],
            "pathogen": names(p["pathogen"]),
            "mechanism": [names(m) for m in sorted(p["mechanism"])],
            "drugs": [names(d) for d in sorted(p["drugs"])],
            "line_of_therapy": p["line_of_therapy"],
            "confidence": p["confidence"],
            "passage_id": p["passage_id"],
            "evidence": p["evidence"][:300],
        }
        for p in preds
        if p["id"] not in pairs
    ]
    fns = [
        {
            "id": g["id"],
            "cause": fn_cause(g, preds),
            "guideline": g["guideline"],
            "page": g["page"],
            "pathogen": names(g["pathogen"]),
            "mechanism": [names(m) for m in sorted(g["mechanism"])],
            "drugs": [names(d) for d in sorted(g["drugs"])],
            "line_of_therapy": g["line_of_therapy"],
            "curated_text": g["text"],
            "page_passages": sorted(
                pid for pid, ps in passages.items() if ps["source_doc"] == g["guideline"] and ps.get("page") == g["page"]
            ),
        }
        for g in gold
        if g["id"] not in matched_gold
    ]
    return {
        "false_positive_causes": dict(Counter(f["cause"] for f in fps)),
        "false_negative_causes": dict(Counter(f["cause"] for f in fns)),
        "false_positive_sample": pick(fps),
        "false_negative_sample": pick(fns),
    }


# ----------------------------------------------------------------------------- driver


def confidence_sweep(preds: list[dict], gold: list[dict]) -> list[dict[str, Any]]:
    rows = []
    for cut in (0.0, 0.3, 0.5, 0.6, 0.8, 0.9):
        kept = [p for p in preds if p["confidence"] >= cut]
        s = score(kept, gold, MATCHERS["strict"])
        lenient = score(kept, gold, MATCHERS["lenient"])
        rows.append(
            {
                "min_confidence": cut,
                "n_extracted": len(kept),
                "strict_precision": s["precision"],
                "strict_recall": s["recall"],
                "strict_f1": s["f1"],
                "lenient_f1": lenient["f1"],
            }
        )
    return rows


def run(
    extracted_path: Path = OUT_PATH, passages_path: Path = PASSAGES_PATH, out_path: Path = RESULT_PATH
) -> dict[str, Any]:
    extractor = Extractor()
    passages = {p["id"]: p for p in load_passages(passages_path)}
    extracted = [
        RecommendationExtraction(**json.loads(line))
        for line in extracted_path.read_text(encoding="utf8").splitlines()
        if line.strip()
    ]
    preds = load_predictions(extracted, extractor, passages)
    gold = load_gold()
    guidelines = sorted({g["guideline"] for g in gold})

    result: dict[str, Any] = {
        "note": (
            "Development set: icmr-treatment-guidelines-2019 (rules were tuned on it). "
            "icmr-cr-gram-negative-2022 and who-aware-book-2022 were scored after the rules were frozen."
        ),
        "dev_set": DEV_SET,
        "page_tolerance": PAGE_TOLERANCE,
        "overall": score_block(preds, gold),
        "per_guideline": {
            gl: score_block([p for p in preds if p["guideline"] == gl], [g for g in gold if g["guideline"] == gl])
            for gl in guidelines
        },
        "held_out_icmr2022_and_who": score_block(
            [p for p in preds if p["guideline"] != DEV_SET], [g for g in gold if g["guideline"] != DEV_SET]
        ),
        "confidence_sweep": confidence_sweep(preds, gold),
        "extractions_by_line": dict(Counter(p["line_of_therapy"] or "none" for p in preds)),
    }
    result["error_analysis"] = error_analysis(preds, gold, passages, lambda i: extractor.names.get(i, str(i)))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf8")
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--extracted", type=Path, default=OUT_PATH)
    ap.add_argument("--out", type=Path, default=RESULT_PATH)
    args = ap.parse_args(argv)
    if not args.extracted.exists():
        print(f"missing {args.extracted}; run python -m pipeline.extract first", file=sys.stderr)
        return 1
    res = run(args.extracted, out_path=args.out)
    for name, block in [("overall", res["overall"]), *res["per_guideline"].items()]:
        s, lo = block["strict"], block["lenient"]
        print(
            f"{name:34s} n={s['n_extracted']:3d} gold={s['n_gold']:2d} "
            f"strict P={s['precision']:.2f} R={s['recall']:.2f} F1={s['f1']:.2f} | "
            f"lenient P={lo['precision']:.2f} R={lo['recall']:.2f} F1={lo['f1']:.2f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Answer builder (T14): parse, retrieve in one of five modes, fuse, and build the answer text.

    python -m retrieval.answer "<question>" --mode hybrid [-k 10]

``answer(question, mode, k)`` returns a plain dict (see ``docs/tasks/T14-answer-builder.md``).
The answer text comes from fixed templates filled only from retrieved facts (D15); it gives
no doses (D18) and always ends with the guideline names and years and the disclaimer.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from dataclasses import asdict
from functools import lru_cache
from typing import Any

from retrieval import fusion, text_search
from retrieval.build_index import PROCESSED
from retrieval.parser import parse
from retrieval.types import Answer, GraphResult, ParsedQuery, PassageHit

MODES = ("bm25", "dense", "bm25_dense", "graph", "hybrid")
TEXT_MODES = ("bm25", "dense", "bm25_dense")
POOL = 50  # depth of each candidate list before fusion
FALLBACK_TEXT_MODE = "bm25_dense"  # used for `unknown` questions in the graph modes

DISCLAIMER = (
    "This is an educational tool, not medical advice. It does not replace a clinician, local "
    "susceptibility results or the full guidelines, and it gives no doses or patient-specific advice."
)

# Fixed templates (D15). Placeholders are filled only with retrieved facts.
T = {
    "declined": "This question was declined: {reason}",
    "unknown": ("The question was not understood as one of the supported types (alternatives, restrictions, "
                "mechanisms, recommendations, drug profiles, surveillance), so only the passages that best "
                "match its wording are shown."),
    "empty_graph": "The knowledge graph has no facts that answer this question. {reason}",
    "text_head": ("Text retrieval only ({mode}). The {noun} most often mentioned in the best-matching passages: "
                  "{names}. These come from passage wording and are not checked against the guideline "
                  "recommendations or the resistance data."),
    "text_none": "Text retrieval only ({mode}). The best-matching passages do not mention any {noun} that could answer it.",
    "hybrid_fallback": "The graph had no facts for this question, so the entities below come from the passages.",
    "alt_head": ("Alternatives for {pathogens} when resistance to {classes} is reported, separated by the "
                 "resistance mechanism."),
    "alt_group": "{group}: ",
    "alt_rec": "Recommended by the guidelines in scope: {drugs}.",
    "alt_none_rec": "No guideline in scope recommends a specific drug for this case.",
    "alt_caveats": "Caveats: {caveats}",
    "alt_other": ("Not excluded by the resistance data, but not recommended by the guidelines in scope: "
                  "{drugs}."),
    "why_drug": "{name} is in the WHO AWaRe {aware} group.",
    "why_defeated": "It is defeated by: {names}.",
    "why_intrinsic": "It is intrinsically inactive against: {names}.",
    "why_recs": "The guidelines in scope keep it for these situations: {items}.",
    "mech_head": "{pathogens} can resist {classes} through: ",
    "mech_item": "{name} ({detail})",
    "rec_head": "Guideline-listed options for {pathogens}{site}: {drugs}.",
    "profile": "{name}: class {group}; WHO AWaRe group {aware}; named in {n} guideline recommendation(s).",
    "surv": "WHO GLASS statistics found: {items}.",
    "sources": "Guidelines: {guidelines}.",
    "sources_scope": "Guidelines in scope: {guidelines}.",
}

LINE_NAME = {"first": "first line", "second": "second line", "alternative": "alternative", "last-resort": "last resort"}
LINE_ORDER = {"first": 0, "second": 1, "alternative": 2, "last-resort": 3}
NOUN = {"Drug": "drugs", "Mechanism": "resistance mechanisms", "DrugClass": "drug classes", "Pathogen": "pathogens"}


# ---------------------------------------------------------------------------
# Reference data (read from the processed CSVs; no database needed)
# ---------------------------------------------------------------------------


def _read_csv(name: str) -> list[dict]:
    path = PROCESSED / name
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _initials(org: str) -> str:
    words = [w for w in re.split(r"\s+", org.strip()) if w and w.lower() not in {"of", "the", "for", "and"}]
    return "".join(w[0].upper() for w in words) if len(words) > 1 else org


@lru_cache(maxsize=1)
def guidelines() -> dict[str, dict]:
    """guideline id -> {title, year, short} (short is for example 'ICMR 2022')."""
    out = {}
    for r in _read_csv("nodes_Guideline.csv"):
        out[r["id"]] = {"title": r["title"], "year": r["year"], "short": f"{_initials(r.get('organisation', ''))} {r['year']}"}
    return out


@lru_cache(maxsize=1)
def rec_meta() -> dict[str, dict]:
    return {r["id"]: r for r in _read_csv("nodes_Recommendation.csv")}


def guideline_id(rec_id: str) -> str | None:
    m = re.match(r"REC:(.+):\d+$", rec_id)
    return m.group(1) if m else None


def best_line(rec_ids: list[str]) -> str | None:
    lines = [rec_meta().get(r, {}).get("line_of_therapy") for r in rec_ids]
    lines = [x for x in lines if x in LINE_ORDER]
    return min(lines, key=LINE_ORDER.get) if lines else None


def guideline_ids_of(rec_ids: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for r in rec_ids:
        g = guideline_id(r)
        if g in guidelines():
            seen[g] = None
    return list(seen)


# ---------------------------------------------------------------------------
# Text building
# ---------------------------------------------------------------------------


def _join(items: list[str]) -> str:
    items = [i for i in items if i]
    if len(items) <= 2:
        return " and ".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _drug_entry(a: Answer) -> str:
    bits = []
    if a.aware_group:
        bits.append(a.aware_group)
    line = best_line(a.recommendation_ids)
    if line:
        bits.append(LINE_NAME[line])
    gl = [guidelines()[g]["short"] for g in guideline_ids_of(a.recommendation_ids)]
    if gl:
        bits.append(", ".join(gl))
    return f"{a.name} ({'; '.join(bits)})" if bits else a.name


MAX_CAVEATS = 4 # distinct caveat sentences per paragraph; every caveat stays in answers[].caveats
MAX_OTHER = 15


def _strip_rec_prefix(caveat: str) -> str:
    return re.sub(r"^REC:[^:]+:\d+:\s*", "", caveat).strip()


def _caveat_text(answers: list[Answer]) -> str:
    """Distinct caveat sentences, each with the drugs it applies to. Caveats that qualify how a drug may
    be used (not active alone, only in combination, co-production) come before plain restrictions."""
    by_sentence: dict[str, list[str]] = {}
    for a in answers:
        for c in a.caveats:
            s = _strip_rec_prefix(c)
            if not s:
                continue
            # variants that differ only in a bracketed list (partner drugs) count as one caveat
            key = next((k for k in by_sentence if k.split(" (")[0] == s.split(" (")[0]), s)
            if a.name not in by_sentence.setdefault(key, []):
                by_sentence[key].append(a.name)

    def weight(item):
        s = item[0]
        return 1 if s.startswith(("Restricted to", "Patient group", "Partners left out")) else 0

    ordered = sorted(by_sentence.items(), key=weight)  # stable
    shown = [f"{s.rstrip('.')} ({_join(d)})." for s, d in ordered[:MAX_CAVEATS]]
    more = len(ordered) - MAX_CAVEATS
    if more > 0:
        shown.append(f"{more} more caveat(s) are listed with each answer.")
    return " ".join(shown)


def _names(parsed: ParsedQuery, graph_names: dict[str, str], ids: list[str], fallback: str) -> str:
    names = [graph_names.get(i, i) for i in ids]
    return _join(names) or fallback


def _alternatives_text(parsed: ParsedQuery, recommended: list[Answer], other: list[Answer],
                       names: dict[str, str]) -> str:
    classes = _names(parsed, names, parsed.class_ids, "")
    if parsed.class_families and not parsed.class_ids:
        classes = _join(parsed.class_families)
    head = T["alt_head"].format(
        pathogens=_names(parsed, names, parsed.pathogen_ids, "the organism"),
        classes=classes or "the reported antibiotic class",
    )
    groups: dict[str, dict[str, list[Answer]]] = {}
    for a in recommended:
        groups.setdefault(a.group, {"rec": [], "other": []})["rec"].append(a)
    for a in other:
        groups.setdefault(a.group, {"rec": [], "other": []})["other"].append(a)
    paragraphs = [head]
    for group, parts in groups.items():
        text = T["alt_group"].format(group=group or "No mechanism named")
        text += (T["alt_rec"].format(drugs="; ".join(_drug_entry(a) for a in parts["rec"]))
                 if parts["rec"] else T["alt_none_rec"])
        cav = _caveat_text(parts["rec"])
        if cav:
            text += " " + T["alt_caveats"].format(caveats=cav)
        if parts["other"]:
            names_o = [a.name for a in parts["other"]]
            shown_o = ", ".join(names_o[:MAX_OTHER]) + (f" and {len(names_o) - MAX_OTHER} more" if len(names_o) > MAX_OTHER else "")
            text += " " + T["alt_other"].format(drugs=shown_o)
        paragraphs.append(text)
    return "\n\n".join(paragraphs)


def _why_text(answers: list[Answer]) -> str:
    by: dict[str, list[Answer]] = {}
    for a in answers:
        by.setdefault(a.label, []).append(a)
    parts = []
    for d in by.get("Drug", []):
        s = T["why_drug"].format(name=d.name, aware=d.aware_group or "unlisted")
        parts.append(s + (" " + " ".join(d.caveats[:1]) if d.caveats else ""))
    if by.get("Mechanism"):
        parts.append(T["why_defeated"].format(names=_join([a.name for a in by["Mechanism"]])))
    if by.get("Pathogen"):
        parts.append(T["why_intrinsic"].format(names=_join([a.name for a in by["Pathogen"]])))
    if by.get("Recommendation"):
        items = []
        for r in by["Recommendation"]:
            gl = [guidelines()[g]["short"] for g in guideline_ids_of([r.id])]
            items.append(f"{r.name} ({', '.join(gl)})" if gl else r.name)
        parts.append(T["why_recs"].format(items=" ".join(f"[{i + 1}] {t}" for i, t in enumerate(items))))
    return "\n\n".join(parts)


def _graph_text(parsed: ParsedQuery, answers: list[Answer], recommended: list[Answer], other: list[Answer],
                names: dict[str, str]) -> str:
    intent = parsed.intent
    if intent == "alternatives":
        return _alternatives_text(parsed, recommended, other, names)
    if intent == "why_restricted":
        return _why_text(answers)
    if intent == "mechanism_lookup":
        head = T["mech_head"].format(
            pathogens=_names(parsed, names, parsed.pathogen_ids, "The organism"),
            classes=_join(parsed.class_families + [names.get(c, c) for c in parsed.class_ids]) or "the antibiotic",
        )
        items = [T["mech_item"].format(name=a.name, detail=(a.caveats[0] if a.caveats else a.group)) for a in answers]
        return head + "; ".join(items) + "."
    if intent == "recommendation_lookup":
        site = f" ({parsed.infection_site})" if parsed.infection_site else ""
        return T["rec_head"].format(pathogens=_names(parsed, names, parsed.pathogen_ids, "the organism"), site=site,
                                    drugs="; ".join(_drug_entry(a) for a in answers))
    if intent == "drug_profile":
        return "\n\n".join(T["profile"].format(name=a.name, group=a.group or "unknown", aware=a.aware_group or "unlisted",
                                               n=len(a.recommendation_ids)) for a in answers)
    if intent == "surveillance":
        return T["surv"].format(items="; ".join(a.name for a in answers))
    return ""


def _text_answer_text(mode: str, intent: str, answers: list[Answer]) -> str:
    types = fusion.TARGET_TYPES.get(intent, ())
    noun = NOUN.get(types[0], "entities") if types else "entities"
    if not answers:
        return T["text_none"].format(mode=mode, noun=noun)
    return T["text_head"].format(mode=mode, noun=noun, names=", ".join(a.name for a in answers[:10]))


def _sources_line(rec_ids: list[str], passages: list[PassageHit]) -> str:
    ids = guideline_ids_of(rec_ids)
    for p in passages:
        if p.source_doc in guidelines() and p.source_doc not in ids:
            ids.append(p.source_doc)
    if ids:
        return T["sources"].format(guidelines="; ".join(f"{guidelines()[g]['title']} ({guidelines()[g]['year']})" for g in ids))
    allg = "; ".join(f"{g['title']} ({g['year']})" for g in guidelines().values())
    return T["sources_scope"].format(guidelines=allg)


# ---------------------------------------------------------------------------
# The function
# ---------------------------------------------------------------------------


def _entities(parsed: ParsedQuery) -> dict[str, Any]:
    return {
        "pathogens": list(parsed.pathogen_ids), "mechanisms": list(parsed.mechanism_ids),
        "drugs": list(parsed.drug_ids), "classes": list(parsed.class_ids),
        "class_families": list(parsed.class_families), "country": parsed.country,
        "year": parsed.year, "infection_site": parsed.infection_site,
    }


def _a(a: Answer, recommended: bool) -> dict[str, Any]:
    d = asdict(a)
    d["recommended"] = recommended
    return d


def _text_passages(question: str, mode: str, k: int) -> list[PassageHit]:
    return text_search.search(question, mode, k)


def _hybrid_passages(question: str, graph_hits: list[PassageHit], k: int) -> tuple[list[PassageHit], list[PassageHit]]:
    """RRF (k = 60) of BM25, dense and graph-linked passages. Returns (top k, the whole fused pool)."""
    bm = text_search.search(question, "bm25", POOL)
    de = text_search.search(question, "dense", POOL)
    pool = fusion.fuse_passages([bm, de, graph_hits], k=POOL)
    return pool[:k], pool


def _graph_hits(graph: GraphResult, k: int) -> list[PassageHit]:
    """Graph-linked passages: passages that mention or support the path entities, plus passage
    nodes the graph returned itself (``why_restricted`` guideline text)."""
    idx = text_search.get_index()
    hits: list[PassageHit] = []
    seen: set[str] = set()
    for a in graph.answers:
        if a.label == "Passage" and a.id in idx.row and a.id not in seen:
            seen.add(a.id)
            hits.append(idx._hit(idx.row[a.id], 1.0, len(hits) + 1))
    for h in text_search.passages_for_entities(graph.entity_ids, k):
        if h.passage_id not in seen:
            seen.add(h.passage_id)
            hits.append(PassageHit(h.passage_id, h.score, len(hits) + 1, h.text, h.source_doc, h.section, h.page))
    return hits[:k]


def answer(question: str, mode: str = "hybrid", k: int = 10) -> dict[str, Any]:
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}; expected one of {MODES}")
    t0 = time.perf_counter()
    parsed = parse(question)
    out: dict[str, Any] = {
        "question": question, "mode": mode, "intent": parsed.intent, "entities": _entities(parsed),
        "answers": [], "other_active": [], "paths": [], "passages": [], "answer_text": "",
        "declined": False, "decline_reason": None, "disclaimer": DISCLAIMER, "cypher": [],
        "empty_reason": None, "note": None,
    }

    if parsed.intent == "decline":
        reason = parsed.decline_reason or "The question is outside what this tool answers."
        out.update(declined=True, decline_reason=reason,
                   answer_text=f"{T['declined'].format(reason=reason)}\n\n{DISCLAIMER}")
        out["timing_s"] = time.perf_counter() - t0
        return out

    exclude = parsed.pathogen_ids + parsed.mechanism_ids + parsed.drug_ids + parsed.class_ids
    text_mode = mode if mode in TEXT_MODES else FALLBACK_TEXT_MODE

    if parsed.intent == "unknown" or mode in TEXT_MODES:
        hits = _text_passages(question, text_mode, k)
        answers = [] if parsed.intent == "unknown" else fusion.text_baseline_answers(hits, parsed.intent, exclude)
        out["answers"] = [_a(a, False) for a in answers]
        out["passages"] = [asdict(h) for h in hits]
        if parsed.intent == "unknown":
            out["note"] = T["unknown"]
            body = T["unknown"]
        else:
            body = _text_answer_text(text_mode, parsed.intent, answers)
        out["answer_text"] = "\n\n".join([body, _sources_line([], hits), DISCLAIMER])
        out["timing_s"] = time.perf_counter() - t0
        return out

    # graph and hybrid
    graph = _graph_search(parsed)
    out["cypher"] = graph.cypher
    out["empty_reason"] = graph.empty_reason
    graph_hits = _graph_hits(graph, POOL if mode == "hybrid" else k)
    if mode == "graph":
        passages = graph_hits[:k]
        support = None
    else:
        passages, pool = _hybrid_passages(question, graph_hits, k)
        links = text_search.get_index().links
        pool_ids = [p.passage_id for p in pool]
        support = {a.id: fusion.support_count(a, links, pool_ids) for a in graph.answers}

    answers_all = fusion.rerank_graph_answers(graph.answers, support, use_support=(mode == "hybrid"))
    if parsed.intent == "alternatives":
        recommended, other = fusion.split_recommended(answers_all)
    else:
        recommended, other = answers_all, []

    if not graph.answers and mode == "hybrid":  # graph found nothing: fall back to passage entities
        fb = fusion.text_baseline_answers(passages, parsed.intent, exclude)
        out["answers"] = [_a(a, False) for a in fb]
        out["note"] = T["hybrid_fallback"]
        body = T["empty_graph"].format(reason=graph.empty_reason or "") + " " + T["hybrid_fallback"]
        if fb:
            body += " " + _text_answer_text(mode, parsed.intent, fb)
    elif not graph.answers:
        body = T["empty_graph"].format(reason=graph.empty_reason or "").strip()
    else:
        names = {a.id: a.name for a in graph.answers}
        for p in graph.paths:
            for s in p.steps:
                names.setdefault(s["node_id"], s.get("node_name") or s["node_id"])
        body = _graph_text(parsed, answers_all if parsed.intent != "alternatives" else recommended + other,
                           recommended, other, names)
        out["answers"] = [_a(a, fusion.is_recommended(a)) for a in recommended]
        out["other_active"] = [_a(a, False) for a in other]

    rank: dict[str, int] = {}
    for i, a in enumerate(out["answers"] + out["other_active"]):
        rank.setdefault(a["id"], i)
    shown_paths = [p for p in graph.paths if p.answer_id in rank]
    shown_paths.sort(key=lambda p: rank[p.answer_id])
    out["paths"] = [asdict(p) for p in shown_paths]
    out["passages"] = [asdict(h) for h in passages]
    rec_ids = [r for a in graph.answers for r in a.recommendation_ids]
    out["answer_text"] = "\n\n".join([body, _sources_line(rec_ids, passages), DISCLAIMER])
    out["timing_s"] = time.perf_counter() - t0
    return out


def _graph_search(parsed: ParsedQuery) -> GraphResult:
    from retrieval.graph_search import graph_search

    return graph_search(parsed)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def format_path(path: dict[str, Any]) -> str:
    parts = []
    for i, s in enumerate(path["steps"]):
        name = s.get("node_name") or s["node_id"]
        if i == 0 or not s.get("rel_type"):
            parts.append(name)
            continue
        props = s.get("rel_props") or {}
        prov = "/".join(str(x) for x in (props.get("source_id"), props.get("method")) if x)
        rel = f"{s['rel_type']} {prov}".strip()
        parts.append(f"<-[{rel}]- {name}" if s.get("direction") == "in" else f"-[{rel}]-> {name}")
    return " ".join(parts)


def _one_line(text: str, n: int = 200) -> str:
    return " ".join(text.split())[:n]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Answer an antimicrobial-resistance question (educational use only).")
    ap.add_argument("question")
    ap.add_argument("--mode", choices=MODES, default="hybrid")
    ap.add_argument("-k", type=int, default=10)
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    r = answer(args.question, args.mode, args.k)
    print(f"Question: {r['question']}\nMode: {r['mode']}   Intent: {r['intent']}   Time: {r['timing_s']:.2f} s\n")
    print(r["answer_text"])
    if r["answers"]:
        print("\nTop answers:")
        for a in r["answers"][:10]:
            tag = "recommended" if a["recommended"] else "text"
            print(f"  {a['name']}  [{a['group'] or '-'}]  {a['aware_group'] or '-'}  score {a['score']:.3f}  {tag}")
    if r["other_active"]:
        print(f"\nOther active, not recommended ({len(r['other_active'])}): "
              + ", ".join(a["name"] for a in r["other_active"][:12]))
    if r["paths"]:
        print("\nOne path:\n  " + format_path(r["paths"][0]))
    if r["passages"]:
        print("\nTop passages:")
        for p in r["passages"][:3]:
            print(f"  {p['rank']}. {p['passage_id']} (p{p['page']}, score {p['score']:.4f})\n     {_one_line(p['text'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

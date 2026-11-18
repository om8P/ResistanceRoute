"""Graph reasoning for AMR-Navigator (task T10).

``graph_search(parsed) -> GraphResult`` runs one parameterised Cypher template
per intent (``retrieval/cypher/*.cypher``) and applies the reasoning rules:

* **Class families (D29):** ``class_families`` expand to every ``DrugClass``
  with that ``family``; the result is unioned with ``class_ids``.
* **Exclusion rule (T03, D4):** for pathogen ``p`` and mechanisms ``M`` a drug
  is excluded when ``p`` is intrinsically resistant to its class, any ``m`` in
  ``M`` confers resistance to its class, or any ``m`` in ``M`` inactivates it.
  In ``alternatives`` the classes the question reports as resistant are also
  excluded (a phenotype; there is no edge for it).
* **Unknown mechanism:** with resistant classes but no mechanism, every
  mechanism of ``p`` that confers resistance to one of them becomes its own
  group, so the answer shows how the choice depends on the mechanism.
* **Recommendations (D33, D34):** a recommendation with ``FOR_MECHANISM`` to a
  mechanism in ``M`` is always kept; a drug of it that is excluded is still
  returned, with a score below 0.5 and the row's ``caveat`` (D40).
  Recommendations without a mechanism are filtered: ``any-of`` drug by drug,
  ``single`` and fixed-pair ``combination`` as a unit, and "base plus one of
  several partners" combinations as described under REGIMEN RULE below.
  Rows with ``susceptible_only`` are dropped whenever the question names a
  mechanism or a resistant class (D41).
* **D39:** ``recommendation_ids`` is filled exactly for drugs that come from a
  recommendation; drugs that are only not excluded have an empty list.
* Per-recommendation data the graph does not hold (``caveat``,
  ``base_drug_ids``, ``susceptible_only``, drug order) is read from
  ``data/curated/recommendations_curated.csv``.
* **Co-production caveats (REVIEW_NOTES section 3):** a drug that survives a
  carbapenemase alone but would be removed if the pathogen's ESBL (CTX-M) were
  also present gets a caveat (aztreonam for NDM, cephalosporins for OXA-48-like).
* **Paths:** every answer has at least one path from the question's entities
  to it. Each step carries the provenance of the relationship that leads to it.

REGIMEN RULE for ``combination`` rows (task step 9)
    A combination without ``base_drug_ids`` is a fixed unit (ceftazidime-avibactam plus
    aztreonam): both drugs are shown, each with "only together with <other>".
    A combination with ``base_drug_ids`` is "a base drug plus one other
    active agent" (ICMR 2022 Table 4: a polymyxin plus tigecycline, an
    aminoglycoside, IV fosfomycin or a carbapenem). The base drugs come from
    ``base_drug_ids``; the rest are partners, of which one is given. Without a mechanism the row is
    kept when at least one base drug and at least one partner are active, and
    only the active drugs are shown. Every drug of such a row gets a caveat
    saying it is used only in that combination, so a partner such as
    tigecycline is never shown as a stand-alone recommendation.

Answer scores
    1.0 / 0.9 / 0.8 / 0.7  active and recommended (first / second /
                            alternative / last-resort line, best one counts)
    0.5                     active, no recommendation for this pathogen
    0.25                    excluded on its own, returned only because a
                            mechanism-specific recommendation names it (D34)
"""

from __future__ import annotations

import csv
import re
from collections import OrderedDict, defaultdict
from functools import lru_cache
from pathlib import Path as FsPath
from typing import Any, Iterable

from pipeline.config import DATA_CURATED
from retrieval.types import Answer, GraphResult, ParsedQuery, Path

CYPHER_DIR = FsPath(__file__).resolve().parent / "cypher"
RECOMMENDATIONS_CSV = DATA_CURATED / "recommendations_curated.csv"

ESBL_ID = "ARO:3000016"  # CTX-M, the representative ESBL (REVIEW_NOTES 2.5)
PROVENANCE_KEYS = ("source_id", "method", "evidence_sources", "needs_review")
LINE_SCORE = {"first": 1.0, "second": 0.9, "alternative": 0.8, "last-resort": 0.7}
ACTIVE_SCORE = 0.5
RESCUED_SCORE = 0.25
RESTRICT_WORDS = ["reserve", "last resort", "last-resort", "restrict", "stewardship"]

# Words a question's infection site may use, mapped to words found in the
# recommendations' infection_site / text (recommendation_lookup only).
SITE_WORDS = {
    "bloodstream": ["bloodstream", "clabsi", "bacteraemia", "bacteremia", "sepsis"],
    "bacteraemia": ["bloodstream", "clabsi", "bacteraemia", "bacteremia", "sepsis"],
    "bacteremia": ["bloodstream", "clabsi", "bacteraemia", "bacteremia", "sepsis"],
    "sepsis": ["sepsis", "bloodstream", "septic"],
    "pneumonia": ["pneumonia", "hap", "vap"],
    "uti": ["uti", "urinary", "pyelonephritis"],
    "urinary": ["uti", "urinary", "pyelonephritis"],
    "pyelonephritis": ["pyelonephritis", "upper uti", "urinary"],
    "osteomyelitis": ["osteomyelitis", "bone"],
    "bone": ["osteomyelitis", "bone"],
    "skin": ["skin", "soft tissue"],
    "abdominal": ["intra-abdominal", "abdominal"],
    "catheter": ["clabsi", "catheter"],
}

_driver = None


# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------


@lru_cache(maxsize=None)
def load_template(name: str) -> str:
    """Return the Cypher text of ``retrieval/cypher/<name>.cypher`` without comments."""
    lines = (CYPHER_DIR / f"{name}.cypher").read_text(encoding="utf-8").splitlines()
    return "\n".join(l for l in lines if not l.strip().startswith("//")).strip()


def _get_driver():
    global _driver
    if _driver is None:
        from pipeline.graph_db import get_driver

        _driver = get_driver()
    return _driver


class _Runner:
    """Runs templates read-only and records each query once for ``GraphResult.cypher``."""

    def __init__(self, driver):
        self.driver = driver
        self.queries: list[str] = []

    def run(self, name: str, **params) -> list[dict[str, Any]]:
        query = load_template(name)
        if query not in self.queries:
            self.queries.append(query)
        with self.driver.session() as session:
            return session.execute_read(lambda tx: [r.data() for r in tx.run(query, **params)])


@lru_cache(maxsize=1)
def rec_meta() -> dict[str, dict]:
    """Per-recommendation data from ``recommendations_curated.csv`` (D40).

    Keys per rec_id: ``drug_order`` (list), ``caveat`` (str or None),
    ``base_drug_ids`` (list or None), ``susceptible_only`` (bool or None).
    ``None`` means the column is missing, so the fallback applies.
    """
    try:
        with RECOMMENDATIONS_CSV.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            cols = set(reader.fieldnames or [])
            out = {}
            for r in reader:
                out[r["rec_id"]] = {
                    "drug_order": [d for d in (r.get("drug_ids") or "").split("|") if d],
                    "caveat": (r.get("caveat") or "").strip() if "caveat" in cols else None,
                    "base_drug_ids": ([d for d in (r.get("base_drug_ids") or "").split("|") if d]
                                      if "base_drug_ids" in cols else None),
                    "susceptible_only": ((r.get("susceptible_only") or "").strip().lower() == "true"
                                         if "susceptible_only" in cols else None),
                }
            return out
    except (OSError, KeyError):
        return {}


def rec_caveat(rec_id: str) -> str | None:
    """The D34 caveat from the ``caveat`` column, or None."""
    return rec_meta().get(rec_id, {}).get("caveat") or None


def _prov(props: dict | None, **extra) -> dict:
    """Relationship properties with the provenance keys always present."""
    out = dict(props or {})
    for key in PROVENANCE_KEYS:
        out.setdefault(key, False if key == "needs_review" else None)
    out.update(extra)
    return out


def _derived(rule: str) -> dict:
    """Provenance for a reasoning step that is not an edge (absence of exclusion edges)."""
    return _prov({}, method="derived", derived=True, derived_from="curated-seed", rule=rule)


def _step(node_id, label, name, rel_type=None, rel_props=None, direction=None, from_node_id=None) -> dict:
    return {
        "node_id": node_id,
        "node_label": label,
        "node_name": name,
        "rel_type": rel_type,
        "rel_props": rel_props if rel_props is not None else {},
        "direction": direction,          # "out": prev -> node, "in": node -> prev
        "from_node_id": from_node_id,    # node the relationship attaches to
    }


class _PathBuilder:
    def __init__(self):
        self.steps: list[dict] = []

    def start(self, node_id, label, name):
        self.steps.append(_step(node_id, label, name))
        return self

    def out(self, node_id, label, name, rel_type, props, attach_to=None):
        prev = attach_to or self.steps[-1]["node_id"]
        self.steps.append(_step(node_id, label, name, rel_type, props, "out", prev))
        return self

    def into(self, node_id, label, name, rel_type, props, attach_to=None):
        prev = attach_to or self.steps[-1]["node_id"]
        self.steps.append(_step(node_id, label, name, rel_type, props, "in", prev))
        return self

    def build(self, answer_id) -> Path:
        return Path(steps=self.steps, answer_id=answer_id)


def _uniq(items: Iterable) -> list:
    return list(OrderedDict.fromkeys(i for i in items if i))


def _finish(answers: list[Answer], paths: list[Path], runner: _Runner, empty_reason=None) -> GraphResult:
    entity_ids = _uniq(step["node_id"] for p in paths for step in p.steps)
    for a in answers:
        a.caveats = _uniq(a.caveats)
        a.recommendation_ids = _uniq(a.recommendation_ids)
    if not answers and empty_reason is None:
        empty_reason = "The graph has no facts that answer this question."
    return GraphResult(answers=answers, paths=paths, entity_ids=entity_ids,
                       cypher=list(runner.queries), empty_reason=empty_reason if not answers else None)


def _expand_classes(runner: _Runner, parsed: ParsedQuery) -> list[dict]:
    if not parsed.class_ids and not parsed.class_families:
        return []
    return runner.run("class_families", families=list(parsed.class_families), class_ids=list(parsed.class_ids))


def _entities(runner: _Runner, ids: list[str]) -> dict[str, dict]:
    if not ids:
        return {}
    return {r["id"]: r for r in runner.run("entities", ids=ids)}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def graph_search(parsed: ParsedQuery, driver=None) -> GraphResult:
    """Answer ``parsed`` from the knowledge graph (CONTRACTS section 7)."""
    if parsed.intent == "decline":
        return GraphResult(empty_reason=parsed.decline_reason or "The question was declined.")
    handler = _HANDLERS.get(parsed.intent)
    if handler is None:
        return GraphResult(empty_reason=f"No graph template for intent '{parsed.intent}'; use text search.")
    try:
        runner = _Runner(driver or _get_driver())
        return handler(parsed, runner)
    except Exception as exc:  # database down: report, never invent
        if exc.__class__.__name__ in {"ServiceUnavailable", "AuthError", "SessionExpired"}:
            return GraphResult(empty_reason=f"Graph database unavailable: {exc.__class__.__name__}")
        raise


# ---------------------------------------------------------------------------
# Core reasoning shared by alternatives and recommendation_lookup
# ---------------------------------------------------------------------------


def _exclusion_reasons(row: dict) -> list[str]:
    reasons = []
    if row["intrinsic"]:
        reasons.append(f"intrinsic resistance to {row['class_name']}")
    for c in row["conferred"]:
        reasons.append(f"{c['mechanism_name']} confers resistance to {row['class_name']}")
    for i in row["inactivated"]:
        reasons.append(f"{i['mechanism_name']} inactivates {row['drug_name']}")
    if row["reported_resistant"]:
        reasons.append(f"{row['class_name']} reported resistant")
    return reasons


class _Group:
    """One pathogen with one set of mechanisms."""

    def __init__(self, pathogen: dict, mechs: list[dict], resistant_classes: list[str], name: str):
        self.pathogen = pathogen            # {"id", "name"}
        self.mechs = mechs                  # rows of mechanisms.cypher
        self.mech_ids = [m["mechanism_id"] for m in mechs]
        self.resistant_classes = resistant_classes
        self.name = name
        self.drugs: dict[str, dict] = {}    # rows of alternatives.cypher
        self.excluded: dict[str, list[str]] = {}

    def load(self, runner: _Runner):
        rows = runner.run("alternatives", pathogen_id=self.pathogen["id"],
                          mechanism_ids=self.mech_ids, resistant_class_ids=self.resistant_classes)
        for r in rows:
            self.drugs[r["drug_id"]] = r
            reasons = _exclusion_reasons(r)
            if reasons:
                self.excluded[r["drug_id"]] = reasons

    @property
    def is_resistant(self) -> bool:
        """True when the question is about a resistant organism (mechanism or resistant class)."""
        return bool(self.mech_ids or self.resistant_classes)

    def active(self, drug_id: str) -> bool:
        return drug_id in self.drugs and drug_id not in self.excluded


def _make_groups(runner: _Runner, pathogen_ids: list[str], mechanism_ids: list[str],
                 resistant_classes: list[str]) -> tuple[list[_Group], list[str]]:
    """Mechanism groups per pathogen, plus notes for the caveats."""
    groups, notes = [], []
    for pid in pathogen_ids:
        rows = runner.run("mechanisms", pathogen_id=pid, mechanism_ids=mechanism_ids,
                          class_ids=resistant_classes)
        if not rows:
            continue
        pathogen = {"id": pid, "name": rows[0]["pathogen_name"]}
        prefix = f"{pathogen['name']}: " if len(pathogen_ids) > 1 else ""
        if mechanism_ids:
            chosen = [r for r in rows if r["mechanism_id"] in mechanism_ids]
            chosen.sort(key=lambda r: mechanism_ids.index(r["mechanism_id"]))
            name = " + ".join(r["mechanism_name"] for r in chosen)
            groups.append(_Group(pathogen, chosen, resistant_classes, prefix + name))
        elif resistant_classes:
            confer = [r for r in rows if r["confers_reported"]]
            if confer:
                for r in confer:
                    groups.append(_Group(pathogen, [r], resistant_classes, prefix + r["mechanism_name"]))
            else:
                notes.append(f"No mechanism of {pathogen['name']} in the graph explains resistance to the "
                             "reported classes; only the phenotype and intrinsic resistance are used.")
                groups.append(_Group(pathogen, [], resistant_classes, prefix + "reported resistance only"))
        else:
            groups.append(_Group(pathogen, [], [], prefix + "no acquired resistance named"))
    return groups, notes


def _co_production_drugs(runner: _Runner, group: _Group) -> set[str]:
    """Drugs active for the group's carbapenemase(s) that the pathogen's ESBL would remove."""
    if not any(m["mechanism_type"] == "carbapenemase" for m in group.mechs):
        return set()
    if ESBL_ID in group.mech_ids:
        return set()
    has_esbl = runner.run("mechanisms", pathogen_id=group.pathogen["id"], mechanism_ids=[], class_ids=[])
    if not any(r["mechanism_id"] == ESBL_ID and r["has_mechanism"] for r in has_esbl):
        return set()
    with_esbl = _Group(group.pathogen, group.mechs + [{"mechanism_id": ESBL_ID}], group.resistant_classes, "")
    with_esbl.load(runner)
    return {d for d in group.drugs if group.active(d) and not with_esbl.active(d)}


def _co_production_caveat(group: _Group, drug: dict) -> str:
    mech = " + ".join(m["mechanism_name"].split(" beta-lactamase")[0] for m in group.mechs)
    if drug["class_id"] == "monobactam":
        detail = (f"{mech} alone does not hydrolyse aztreonam, but most producers also carry an ESBL or "
                  "AmpC that does; that is why guidelines pair aztreonam with avibactam.")
    else:
        detail = (f"{mech} alone barely hydrolyses this drug, but most clinical isolates also produce an "
                  "ESBL such as CTX-M-15, which defeats it.")
    return f"Active against {mech} alone only. {detail} Ask about {mech} + CTX-M for the realistic answer."


class _RecView:
    """How one recommendation applies to one group."""

    def __init__(self, rec: dict, group: _Group):
        self.rec = rec
        self.drug_ids = [d["id"] for d in rec["drugs"]]
        self.drug_by_id = {d["id"]: d for d in rec["drugs"]}
        self.mech_ids = [m["id"] for m in rec["mechanisms"]]
        self.matching_mechs = [m for m in rec["mechanisms"] if m["id"] in group.mech_ids]
        self.specific = bool(self.matching_mechs)
        self.applies = False
        self.shown: list[str] = []      # drugs returned
        self.rescued: list[str] = []    # excluded drugs returned because of D34
        self.dropped: list[str] = []    # excluded partners left out
        self.base: list[str] = []
        self.partners: list[str] = []
        self._decide(group)

    def _split_base(self):
        """Base drugs from the ``base_drug_ids`` column (D40); the other drugs are partners."""
        order = rec_meta().get(self.rec["rec_id"], {}).get("drug_order") or self.drug_ids
        base_ids = rec_meta().get(self.rec["rec_id"], {}).get("base_drug_ids") or []
        self.base = [d for d in base_ids if d in self.drug_by_id]
        self.partners = [d for d in order if d in self.drug_by_id and d not in self.base] if self.base else []

    def _decide(self, group: _Group):
        rt = self.rec["regimen_type"]
        if rt == "combination":
            self._split_base()
        if self.mech_ids and not self.specific:
            return  # tied to other mechanisms only
        if group.is_resistant and rec_meta().get(self.rec["rec_id"], {}).get("susceptible_only"):
            return  # D41: for susceptible organisms only
        active = [d for d in self.drug_ids if group.active(d)]
        if self.specific:  # D34: always returned
            self.applies = True
            self.shown = list(self.drug_ids)
            self.rescued = [d for d in self.drug_ids if not group.active(d)]
            return
        if rt == "any-of":
            self.shown = active
        elif rt == "combination" and self.base:
            base_ok = [d for d in self.base if group.active(d)]
            part_ok = [d for d in self.partners if group.active(d)]
            if base_ok and part_ok:
                self.shown = base_ok + part_ok
                self.dropped = [d for d in self.partners if d not in part_ok]
        else:  # single, fixed-pair combination: as a unit
            if len(active) == len(self.drug_ids):
                self.shown = list(self.drug_ids)
        self.applies = bool(self.shown)

    def caveats_for(self, drug_id: str, group: _Group) -> list[str]:
        """Caveats from this recommendation, each prefixed with its ID so that
        caveats of several recommendations on one answer stay apart."""
        return [f"{self.rec['rec_id']}: {c}" for c in self._caveats(drug_id, group)]

    def _caveats(self, drug_id: str, group: _Group) -> list[str]:
        out = []
        names = {d: self.drug_by_id[d]["name"] for d in self.drug_ids}
        rt = self.rec["regimen_type"]
        if rt == "combination" and self.base:
            partners = [names[d] for d in self.partners if d in self.shown]
            base = " or ".join(names[d] for d in self.base if d in self.shown)
            if drug_id in self.base:
                out.append(f"Only as the base of a combination: {names[drug_id]} plus one other active agent "
                           f"({', '.join(partners)}).")
            else:
                out.append(f"Only as a combination partner of {base}, not on its own.")
            if self.dropped:
                out.append("Partners left out because they are excluded here: "
                           + ", ".join(f"{names[d]} ({group.excluded[d][0]})" for d in self.dropped) + ".")
        elif rt == "combination":
            others = [names[d] for d in self.drug_ids if d != drug_id]
            out.append(f"Only together with {' and '.join(others)} (combination).")
        if drug_id in self.rescued:
            out.append(rec_caveat(self.rec["rec_id"]) or (
                f"{names[drug_id]} is excluded on its own ({'; '.join(group.excluded[drug_id])}), "
                "but the guideline still lists it in this regimen."))
        extra = [m["name"] for m in self.rec["mechanisms"] if m["id"] not in group.mech_ids]
        if extra:
            out.append("The recommendation is for isolates that also produce " + ", ".join(extra) + ".")
        if self.rec.get("infection_site"):
            out.append(f"Restricted to: {self.rec['infection_site']}.")
        if self.rec.get("patient_group"):
            out.append(f"Patient group: {self.rec['patient_group']}.")
        return out


def _rec_path(group: _Group, view: _RecView, drug: dict) -> Path:
    rec = view.rec
    p = group.pathogen
    b = _PathBuilder().start(p["id"], "Pathogen", p["name"])
    if view.specific:
        m_rec = view.matching_mechs[0]
        g_mech = next(m for m in group.mechs if m["mechanism_id"] == m_rec["id"])
        b.out(m_rec["id"], "Mechanism", m_rec["name"], "HAS_MECHANISM", _mech_edge_props(g_mech))
        b.into(rec["rec_id"], "Recommendation", rec["text"], "FOR_MECHANISM", _prov(m_rec["props"]))
    else:
        b.into(rec["rec_id"], "Recommendation", rec["text"], "FOR_PATHOGEN", _prov(rec["for_pathogen"]))
    b.out(drug["id"], "Drug", drug["name"], "RECOMMENDS", _prov(drug["props"]))
    b.out(rec["guideline_id"], "Guideline", f"{rec['guideline_title']} ({rec['guideline_year']})", "FROM",
          _prov(rec["from_props"]), attach_to=rec["rec_id"])
    return b.build(drug["id"])


def _mech_edge_props(mech_row: dict) -> dict:
    if mech_row.get("has_mechanism"):
        return _prov(mech_row["has_mechanism"])
    return _derived("Mechanism named in the question; the graph has no HAS_MECHANISM edge for this pathogen.")


def _activity_paths(group: _Group, drug_row: dict) -> list[Path]:
    """Why a drug is active: no exclusion edge from the pathogen or its mechanisms."""
    p = group.pathogen
    rule = (f"No INTRINSICALLY_RESISTANT_TO, CONFERS_RESISTANCE_TO ({drug_row['class_name']}) or "
            f"INACTIVATES ({drug_row['drug_name']}) edge")
    paths = []
    starts = group.mechs or [None]
    for m in starts:
        b = _PathBuilder().start(p["id"], "Pathogen", p["name"])
        if m:
            b.out(m["mechanism_id"], "Mechanism", m["mechanism_name"], "HAS_MECHANISM", _mech_edge_props(m))
        b.out(drug_row["drug_id"], "Drug", drug_row["drug_name"], "NOT_EXCLUDED", _derived(rule))
        b.out(drug_row["class_id"], "DrugClass", drug_row["class_name"], "IN_CLASS", _prov(drug_row["in_class"]))
        paths.append(b.build(drug_row["drug_id"]))
    return paths


def _exclusion_paths(group: _Group, drug_row: dict) -> list[Path]:
    """Why a drug is excluded, with the provenance of each exclusion edge."""
    p = group.pathogen
    paths = []
    mech_by_id = {m["mechanism_id"]: m for m in group.mechs}
    for c in drug_row["conferred"]:
        m = mech_by_id[c["mechanism_id"]]
        b = _PathBuilder().start(p["id"], "Pathogen", p["name"])
        b.out(m["mechanism_id"], "Mechanism", m["mechanism_name"], "HAS_MECHANISM", _mech_edge_props(m))
        b.out(drug_row["class_id"], "DrugClass", drug_row["class_name"], "CONFERS_RESISTANCE_TO", _prov(c["props"]))
        b.into(drug_row["drug_id"], "Drug", drug_row["drug_name"], "IN_CLASS", _prov(drug_row["in_class"]))
        paths.append(b.build(drug_row["drug_id"]))
    for i in drug_row["inactivated"]:
        m = mech_by_id[i["mechanism_id"]]
        b = _PathBuilder().start(p["id"], "Pathogen", p["name"])
        b.out(m["mechanism_id"], "Mechanism", m["mechanism_name"], "HAS_MECHANISM", _mech_edge_props(m))
        b.out(drug_row["drug_id"], "Drug", drug_row["drug_name"], "INACTIVATES", _prov(i["props"]))
        paths.append(b.build(drug_row["drug_id"]))
    for props in drug_row["intrinsic"]:
        b = _PathBuilder().start(p["id"], "Pathogen", p["name"])
        b.out(drug_row["class_id"], "DrugClass", drug_row["class_name"], "INTRINSICALLY_RESISTANT_TO", _prov(props))
        b.into(drug_row["drug_id"], "Drug", drug_row["drug_name"], "IN_CLASS", _prov(drug_row["in_class"]))
        paths.append(b.build(drug_row["drug_id"]))
    return paths


def _group_paths(group: _Group) -> list[Path]:
    """Why the group exists: the mechanism's resistance to the reported classes."""
    p = group.pathogen
    out = []
    for m in group.mechs:
        for c in m.get("confers_reported") or []:
            b = _PathBuilder().start(p["id"], "Pathogen", p["name"])
            b.out(m["mechanism_id"], "Mechanism", m["mechanism_name"], "HAS_MECHANISM", _mech_edge_props(m))
            b.out(c["class_id"], "DrugClass", c["class_name"], "CONFERS_RESISTANCE_TO", _prov(c["props"]))
            out.append(b.build(m["mechanism_id"]))
    return out


def _reason(parsed: ParsedQuery, runner: _Runner, include_unrecommended: bool,
            site: str | None = None) -> GraphResult:
    if not parsed.pathogen_ids:
        return _finish([], [], runner, "The question names no pathogen.")
    resistant = [r["class_id"] for r in _expand_classes(runner, parsed)]
    if include_unrecommended and not resistant and not parsed.mechanism_ids:
        return _finish([], [], runner, "The question names no resistance (mechanism or resistant drug class), "
                                       "so there is nothing to find alternatives to.")
    groups, notes = _make_groups(runner, list(parsed.pathogen_ids), list(parsed.mechanism_ids), resistant)
    if not groups:
        return _finish([], [], runner, "The pathogen is not in the graph.")

    answers: list[Answer] = []
    paths: list[Path] = []
    site_note = None
    recs_cache: dict[str, list[dict]] = {}
    for group in groups:
        group.load(runner)
        pid = group.pathogen["id"]
        if pid not in recs_cache:
            recs_cache[pid] = runner.run("recommendations", pathogen_id=pid)
        recs = recs_cache[pid]
        if parsed.drug_ids and not include_unrecommended:
            named = [r for r in recs if set(parsed.drug_ids) & {d["id"] for d in r["drugs"]}]
            recs = named or recs
        site_match: set[str] = set()
        if site:
            site_match = {r["rec_id"] for r in recs if _site_matches(site, r)}
            if site_match:
                recs = [r for r in recs if r["rec_id"] in site_match or not r.get("infection_site")]
            else:
                site_note = f"No recommendation names '{site}'; recommendations for any site are shown."
        views = [v for v in (_RecView(r, group) for r in recs) if v.applies]
        co_prod = _co_production_drugs(runner, group)

        per_drug: dict[str, Answer] = {}
        drug_paths: dict[str, list[Path]] = defaultdict(list)

        def answer_for(drug_id: str) -> Answer:
            if drug_id not in per_drug:
                row = group.drugs[drug_id]
                per_drug[drug_id] = Answer(id=drug_id, label="Drug", name=row["drug_name"], group=group.name,
                                           aware_group=row["aware_group"] or "", score=0.0)
            return per_drug[drug_id]

        for view in views:
            for drug_id in view.shown:
                a = answer_for(drug_id)
                a.recommendation_ids.append(view.rec["rec_id"])
                a.caveats.extend(view.caveats_for(drug_id, group))
                if drug_id in view.rescued:
                    a.score = max(a.score, RESCUED_SCORE)
                else:
                    # with a site in the question, rows for any site rank below rows for that site
                    penalty = 0.05 if site_match and view.rec["rec_id"] not in site_match else 0.0
                    a.score = max(a.score, LINE_SCORE.get(view.rec["line_of_therapy"], 0.7) - penalty)
                drug_paths[drug_id].append(_rec_path(group, view, view.drug_by_id[drug_id]))

        if include_unrecommended:
            for drug_id in group.drugs:
                if group.active(drug_id):
                    a = answer_for(drug_id)
                    a.score = max(a.score, ACTIVE_SCORE)

        for drug_id, a in per_drug.items():
            row = group.drugs[drug_id]
            if group.active(drug_id):
                a.score = max(a.score, ACTIVE_SCORE)
                drug_paths[drug_id][:0] = _activity_paths(group, row)
                if drug_id in co_prod:
                    a.caveats.append(_co_production_caveat(group, row))
            else:
                a.score = min(a.score, RESCUED_SCORE)  # excluded alone: never ranks as active
                a.caveats.insert(0, f"Not active on its own here: {'; '.join(group.excluded[drug_id])}.")
                drug_paths[drug_id].extend(_exclusion_paths(group, row))
            for m in group.mechs:
                if not m.get("has_mechanism"):
                    a.caveats.append(f"{m['mechanism_name']} is not recorded for {group.pathogen['name']} "
                                     "in the graph; the answer assumes the question is right.")
            a.caveats.extend(notes)
            if site_note:
                a.caveats.append(site_note)

        for a in per_drug.values():
            a.score = round(a.score, 4)
        ordered = sorted(per_drug.values(), key=lambda a: (-a.score, a.name))
        answers.extend(ordered)
        paths.extend(_group_paths(group))
        for a in ordered:
            paths.extend(drug_paths[a.id])
    empty = None
    if not answers:
        empty = ("No recommendation in the graph applies to this pathogen and resistance."
                 if not include_unrecommended else "Every drug in scope is excluded.")
    return _finish(answers, paths, runner, empty)


def _site_matches(site: str, rec: dict) -> bool:
    words = set()
    for token in re.findall(r"[a-z]+", site.lower()):
        words.update(SITE_WORDS.get(token, [token] if len(token) > 3 else []))
    # infection_site only: the text often names other sites in passing ("depends on bacteraemia")
    hay = (rec.get("infection_site") or "").lower()
    return any(re.search(rf"\b{re.escape(w)}", hay) for w in words if w not in {"infection", "infections"})


# ---------------------------------------------------------------------------
# Intent handlers
# ---------------------------------------------------------------------------


def _alternatives(parsed: ParsedQuery, runner: _Runner) -> GraphResult:
    return _reason(parsed, runner, include_unrecommended=True)


def _recommendation_lookup(parsed: ParsedQuery, runner: _Runner) -> GraphResult:
    return _reason(parsed, runner, include_unrecommended=False, site=parsed.infection_site)


def _why_restricted(parsed: ParsedQuery, runner: _Runner) -> GraphResult:
    if not parsed.drug_ids:
        return _finish([], [], runner, "The question names no drug.")
    answers, paths = [], []
    for drug_id in parsed.drug_ids:
        rows = runner.run("why_restricted", drug_id=drug_id, restrict_words=RESTRICT_WORDS)
        if not rows:
            continue
        r = rows[0]
        drug_start = lambda: _PathBuilder().start(r["drug_id"], "Drug", r["drug_name"])  # noqa: E731
        last_resort = [x for x in r["recommendations"] if x["line_of_therapy"] == "last-resort"]
        main = Answer(id=r["drug_id"], label="Drug", name=r["drug_name"], group="AWaRe group",
                      aware_group=r["aware_group"] or "", score=1.0,
                      recommendation_ids=[x["id"] for x in last_resort])
        aware = r["aware_group"] or "Unclassified"
        main.caveats.append({
            "Reserve": "WHO AWaRe Reserve: kept as a last-resort option for confirmed or suspected multidrug-resistant infections.",
            "Watch": "WHO AWaRe Watch: higher resistance potential; a stewardship priority.",
            "Access": "WHO AWaRe Access: not a restricted group.",
        }.get(aware, f"WHO AWaRe group: {aware}."))
        main.caveats.append("AWaRe group from WHO AWaRe 2025 (who-aware-2025).")
        answers.append(main)
        paths.append(drug_start().out(r["class_id"], "DrugClass", r["class_name"], "IN_CLASS",
                                      _prov(r["in_class"])).build(r["drug_id"]))

        for m in r["by_class"] + r["by_drug"]:
            carriers = ", ".join(sorted(p["name"] for p in m["pathogens"])) or "no in-scope pathogen"
            how = (f"confers resistance to {r['class_name']}" if m["via"] == "CONFERS_RESISTANCE_TO"
                   else f"inactivates {r['drug_name']}")
            a = Answer(id=m["id"], label="Mechanism", name=m["name"], group="Defeated by", score=0.8,
                       caveats=[f"{m['name']} {how} (found in {carriers})."]
                       + ([m["props"]["notes"]] if m["props"].get("notes") else []))
            answers.append(a)
            b = drug_start()
            if m["via"] == "CONFERS_RESISTANCE_TO":
                b.out(r["class_id"], "DrugClass", r["class_name"], "IN_CLASS", _prov(r["in_class"]))
                b.into(m["id"], "Mechanism", m["name"], "CONFERS_RESISTANCE_TO", _prov(m["props"]))
            else:
                b.into(m["id"], "Mechanism", m["name"], "INACTIVATES", _prov(m["props"]))
            for p in m["pathogens"][:1]:
                b.into(p["id"], "Pathogen", p["name"], "HAS_MECHANISM", _prov(p["props"]))
            paths.append(b.build(m["id"]))

        for p in r["intrinsic"]:
            answers.append(Answer(id=p["id"], label="Pathogen", name=p["name"], group="Intrinsically resistant",
                                  score=0.6, caveats=[f"{p['name']} is intrinsically resistant to {r['class_name']}."]))
            paths.append(drug_start()
                         .out(r["class_id"], "DrugClass", r["class_name"], "IN_CLASS", _prov(r["in_class"]))
                         .into(p["id"], "Pathogen", p["name"], "INTRINSICALLY_RESISTANT_TO", _prov(p["props"]))
                         .build(p["id"]))

        for x in last_resort:
            g = x["guideline"] or {}
            answers.append(Answer(id=x["id"], label="Recommendation", name=x["text"], group="Kept as last resort",
                                  score=0.9, recommendation_ids=[x["id"]],
                                  caveats=[f"{g.get('title')} ({g.get('year')}), for "
                                           f"{(x['pathogen'] or {}).get('name')}."]))
            b = drug_start().into(x["id"], "Recommendation", x["text"], "RECOMMENDS", _prov(x["props"]))
            if g:
                b.out(g["id"], "Guideline", f"{g['title']} ({g['year']})", "FROM", _prov(g["props"]))
            for s in x["passages"][:2]:
                b.into(s["id"], "Passage", s["section"], "SUPPORTS", _prov(s["props"]), attach_to=x["id"])
            paths.append(b.build(x["id"]))

        scored = sorted(r["passages"], key=lambda s: -sum(s["text"].lower().count(w) for w in RESTRICT_WORDS))
        for s in scored[:3]:
            snippet = _snippet(s["text"], RESTRICT_WORDS)
            answers.append(Answer(id=s["id"], label="Passage", name=snippet, group="Guideline text", score=0.5,
                                  caveats=[f"{s['source_doc']}, section '{s['section']}'."]))
            paths.append(drug_start().into(s["id"], "Passage", s["section"], "MENTIONS", _prov(s["props"]))
                         .build(s["id"]))
    return _finish(answers, paths, runner, "The drug is not in the graph.")


def _snippet(text: str, words: list[str], width: int = 240) -> str:
    low = text.lower()
    pos = min([low.find(w) for w in words if w in low] or [0])
    start = max(0, pos - width // 3)
    if start:
        space = text.find(" ", start)
        start = space + 1 if 0 <= space < pos else start
    return ("…" if start else "") + text[start:start + width].strip() + ("…" if start + width < len(text) else "")


def _mechanism_lookup(parsed: ParsedQuery, runner: _Runner) -> GraphResult:
    if not parsed.pathogen_ids:
        return _finish([], [], runner, "The question names no pathogen.")
    class_rows = _expand_classes(runner, parsed)
    class_ids = [c["class_id"] for c in class_rows]
    drug_ids = list(parsed.drug_ids)
    if drug_ids and not class_ids:
        class_ids = _uniq(e["class_id"] for e in _entities(runner, drug_ids).values())
    answers, paths = [], []
    for pid in parsed.pathogen_ids:
        rows = runner.run("mechanism_lookup", pathogen_id=pid, class_ids=class_ids, drug_ids=drug_ids)
        if not rows:
            continue
        r = rows[0]
        for m in r["mechanisms"]:
            if (class_ids or drug_ids) and not m["classes"] and not m["drugs"]:
                continue
            if parsed.mechanism_ids and m["id"] not in parsed.mechanism_ids:
                continue
            classes = [c["name"] for c in m["classes"]]
            drugs = [d["name"] for d in m["drugs"]]
            cav = []
            if classes:
                cav.append("Confers resistance to: " + ", ".join(classes) + ".")
            if drugs:
                cav.append("Inactivates: " + ", ".join(drugs) + ".")
            if m["props"].get("notes"):
                cav.append(m["props"]["notes"])
            if m["props"].get("needs_review"):
                cav.append("This pathogen-mechanism fact is flagged for expert review.")
            answers.append(Answer(id=m["id"], label="Mechanism", name=m["name"], group=m["type"] or "",
                                  score=1.0 if classes else 0.8, caveats=cav))
            for c in m["classes"]:
                paths.append(_PathBuilder().start(r["pathogen_id"], "Pathogen", r["pathogen_name"])
                             .out(m["id"], "Mechanism", m["name"], "HAS_MECHANISM", _prov(m["props"]))
                             .out(c["id"], "DrugClass", c["name"], "CONFERS_RESISTANCE_TO", _prov(c["props"]))
                             .build(m["id"]))
            for d in m["drugs"]:
                paths.append(_PathBuilder().start(r["pathogen_id"], "Pathogen", r["pathogen_name"])
                             .out(m["id"], "Mechanism", m["name"], "HAS_MECHANISM", _prov(m["props"]))
                             .out(d["id"], "Drug", d["name"], "INACTIVATES", _prov(d["props"]))
                             .build(m["id"]))
            if not m["classes"] and not m["drugs"]:
                paths.append(_PathBuilder().start(r["pathogen_id"], "Pathogen", r["pathogen_name"])
                             .out(m["id"], "Mechanism", m["name"], "HAS_MECHANISM", _prov(m["props"]))
                             .build(m["id"]))
        for c in r["intrinsic"]:
            answers.append(Answer(id=c["id"], label="DrugClass", name=c["name"], group="intrinsic", score=0.9,
                                  caveats=[f"{r['pathogen_name']} is intrinsically resistant to {c['name']}."]
                                  + ([c["props"]["notes"]] if c["props"].get("notes") else [])))
            paths.append(_PathBuilder().start(r["pathogen_id"], "Pathogen", r["pathogen_name"])
                         .out(c["id"], "DrugClass", c["name"], "INTRINSICALLY_RESISTANT_TO", _prov(c["props"]))
                         .build(c["id"]))
    answers.sort(key=lambda a: (-a.score, a.name))
    return _finish(answers, paths, runner,
                   "The graph has no mechanism of this pathogen that acts on these drugs, "
                   "and no intrinsic resistance to them.")


def _drug_profile(parsed: ParsedQuery, runner: _Runner) -> GraphResult:
    class_ids = [c["class_id"] for c in _expand_classes(runner, parsed)]
    if not parsed.drug_ids and not class_ids:
        return _finish([], [], runner, "The question names no drug or drug class.")
    rows = runner.run("drug_profile", drug_ids=list(parsed.drug_ids), class_ids=class_ids)
    answers, paths = [], []
    for r in rows:
        answers.append(Answer(id=r["drug_id"], label="Drug", name=r["drug_name"], group=r["class_name"],
                              aware_group=r["aware_group"] or "", score=1.0,
                              recommendation_ids=[x["id"] for x in r["recommendations"]],
                              caveats=[f"Class family: {r['family']}.",
                                       "AWaRe group from WHO AWaRe 2025 (who-aware-2025)."]))
        paths.append(_PathBuilder().start(r["drug_id"], "Drug", r["drug_name"])
                     .out(r["class_id"], "DrugClass", r["class_name"], "IN_CLASS", _prov(r["in_class"]))
                     .build(r["drug_id"]))
        if r["drug_id"] not in parsed.drug_ids:  # reached through a named class or family
            b = _PathBuilder().start(r["class_id"], "DrugClass", r["class_name"])
            b.into(r["drug_id"], "Drug", r["drug_name"], "IN_CLASS", _prov(r["in_class"]))
            paths.append(b.build(r["drug_id"]))
    return _finish(answers, paths, runner, "The drug is not in the graph.")


def _surveillance(parsed: ParsedQuery, runner: _Runner) -> GraphResult:
    if not parsed.pathogen_ids:
        return _finish([], [], runner, "The question names no pathogen.")
    class_ids = [c["class_id"] for c in _expand_classes(runner, parsed)]
    names = _entities(runner, list(parsed.pathogen_ids))
    answers, paths = [], []
    for pid in parsed.pathogen_ids:
        targets = list(parsed.drug_ids) + class_ids
        if class_ids:  # GLASS also reports single drugs of the class (e.g. meropenem)
            targets += [r["drug_id"] for r in runner.run("drug_profile", drug_ids=[], class_ids=class_ids)]
        if not targets and parsed.mechanism_ids:  # e.g. MRSA: the classes mecA confers resistance to
            for r in runner.run("mechanism_lookup", pathogen_id=pid, class_ids=[], drug_ids=[]):
                for m in r["mechanisms"]:
                    if m["id"] in parsed.mechanism_ids:
                        targets += [c["id"] for c in m["classes"]]
        targets = _uniq(targets)
        if not targets:
            continue
        rows = runner.run("surveillance", pathogen_id=pid, target_ids=targets,
                          country=parsed.country, year=parsed.year)
        latest: dict[tuple, dict] = {}
        for s in rows:  # newest first per (target, country)
            latest.setdefault((s["target_id"], s["country"]), s)
        chosen = list(latest.values()) if parsed.year is None else rows
        note = None
        if parsed.country is None:
            chosen = sorted(chosen, key=lambda s: -(s["n_tested"] or 0))[:10]
            note = "No country named: the 10 latest statistics with the most isolates tested are shown."
        pname = names.get(pid, {}).get("name", pid)
        for s in chosen:
            cav = [f"WHO GLASS, blood isolates, {s['year']}, {s['n_tested']} tested."]
            if s["about_pathogen"].get("reported_taxon"):
                cav.append(f"GLASS reports this as '{s['about_pathogen']['reported_taxon']}' (genus level, D30).")
            if s["target_id"] == "carbapenem":
                cav.append("GLASS 'Carbapenems' is linked to the meropenem/imipenem class only.")
            if s["target_id"] == "antistaphylococcal-penicillin":
                cav.append("GLASS methicillin row, the MRSA indicator (D35).")
            if note:
                cav.append(note)
            if parsed.year is None:
                cav.append("Latest year available.")
            answers.append(Answer(id=s["stat_id"], label="SurveillanceStat",
                                  name=f"{s['country']} {s['year']}: {s['pct_resistant']:.1f}% resistant to "
                                       f"{s['target_name']} (n={s['n_tested']})",
                                  group=s["target_name"], score=round((s["pct_resistant"] or 0) / 100, 4),
                                  caveats=cav))
            paths.append(_PathBuilder().start(pid, "Pathogen", pname)
                         .into(s["stat_id"], "SurveillanceStat", s["stat_id"], "ABOUT_PATHOGEN",
                               _prov(s["about_pathogen"]))
                         .out(s["target_id"], s["target_label"], s["target_name"], s["about_type"],
                              _prov(s["about_props"]))
                         .build(s["stat_id"]))
    return _finish(answers, paths, runner, "GLASS has no statistics for this pathogen, antibiotic and country.")


_HANDLERS = {
    "alternatives": _alternatives,
    "recommendation_lookup": _recommendation_lookup,
    "why_restricted": _why_restricted,
    "mechanism_lookup": _mechanism_lookup,
    "drug_profile": _drug_profile,
    "surveillance": _surveillance,
}

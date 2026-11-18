"""Rule-based extraction of drug recommendations from guideline passages (T13).

Reads ``data/processed/passages.jsonl`` (guideline passages only, not PubMed abstracts) and writes
``data/processed/recommendations_extracted.jsonl``: one ``RecommendationExtraction`` per line.
Nothing is loaded into the graph.

Rules, in the order they run on a passage:

* **table4** - ICMR 2022 Table 4 rows, which T06 turned into one sentence per mechanism
  ("Carbapenemase X: 1st choice: ...; other options: a. ... b. ..."). One extraction for the
  first choice and one per lettered option.
* **trigger** - prose, bullets and "First Choice / Second Choice" blocks. A unit (sentence or
  block) is a recommendation when it holds a trigger phrase ("first choice", "recommended",
  "preferred", "alternative", "options include", "reserve for", ...), at least one drug and a
  pathogen (in the unit, or carried from the passage heading or an earlier unit).
* **segment** - ICMR 2019 style tables ("Etiology / Suggested regimens / Preferred /
  Alternative"). The extracted text has its columns interleaved, so the passage is cut at each
  pathogen mention and the drugs up to the next one are taken together, without a line of therapy.

Entities come from ``pipeline.link.EntityLinker``. A drug class in the text ("aminoglycosides") is
expanded to the in-scope drugs of that class. "Enterobacterales" (not a pathogen in scope) stands
for the in-scope Enterobacterales, *K. pneumoniae* and *E. coli*. Extractions hold canonical names
(the model's fields are free text); ``Extractor.resolve_ids`` links them back to IDs.

Usage: ``python -m pipeline.extract [--passages PATH] [--out PATH]``
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml

from pipeline.link import EntityLinker, LinkedMention
from pipeline.models import RecommendationExtraction

ROOT = Path(__file__).resolve().parent.parent
PASSAGES_PATH = ROOT / "data" / "processed" / "passages.jsonl"
OUT_PATH = ROOT / "data" / "processed" / "recommendations_extracted.jsonl"
SCOPE_PATH = ROOT / "schema" / "scope.yaml"
PATHOGEN_MECHANISM_PATH = ROOT / "data" / "curated" / "pathogen_mechanism.csv"
MAX_UNIT_WORDS = 60  # longer units are flattened table fragments; only the segment rule reads them

ENTEROBACTERALES_IDS = ["NCBITaxon:573", "NCBITaxon:562"]  # in-scope Enterobacterales

# ----------------------------------------------------------------------------- trigger patterns

LAST = re.compile(
    r"reserve[d]?\b|last[- ]resort|last[- ]line|only (?:when|if) no other|when no other (?:option|treatment)",
    re.I,
)
SECOND = re.compile(r"second[- ]choice|second[- ]line|2nd choice|2nd line", re.I)
FIRST_STRONG = re.compile(
    r"first[- ]choice|1st choice|first[- ]line|drug of choice|agent of choice|treatment of choice|choice of (?:treatment|therapy|agent)",
    re.I,
)
FIRST_WEAK = re.compile(r"\bpreferred\b|\brecommended\b|\brecommend\b|\bsuggested\b", re.I)
ALT = re.compile(
    r"alternative|other options?|options? include|can be (?:used|considered)|may be (?:used|considered)|acceptable (?:option|alternative)",
    re.I,
)
NEGATION = re.compile(
    r"\bdo[- ]?not use\b|\bnot recommended\b|\bshould not be used\b|\bnot to be used\b|\bavoid\b|\bcontraindicated\b",
    re.I,
)
# A drug name that is really a resistance phenotype or a statement about resistance.
RESISTANT_AFTER = re.compile(r"^[\s-]*(?:resistan|non-?suscept|sparing|insensitive)", re.I)
RESISTANT_BEFORE = re.compile(r"(?:resistan(?:t|ce) to|not active against|inactive against|resistance against)\s*$", re.I)

SPLIT = re.compile(
    r"(?<=[.;?!])\s+(?=[A-Z0-9(])"  # sentence ends
    r"|\s*[•➢●◦▪]\s*"  # bullets
    r"|(?=\b(?:First|Second|Third) [Cc]hoice\b)"  # AWaRe blocks
    r"|(?=Table \d+[.:])"
)
TABLE4 = re.compile(
    r"Carbapenemase\s+(?P<mech>.+?):\s*1st choice:\s*(?P<first>.+?);\s*other options:\s*(?P<other>.+)$",
    re.I | re.S,
)
OPTION_SPLIT = re.compile(r"(?:(?<=\s)|^)[a-z]\.\s+(?=[A-Z])")
ENTEROBACTERALES_RE = re.compile(r"\bEnterobacterales\b|\bEnterobacteriaceae\b", re.I)
TABLE_COLUMNS = re.compile(r"Preferred\s+Alternative|Suggested regimens", re.I)


def classify_trigger(unit: str) -> tuple[str, float] | None:
    """Return ``(line_of_therapy, base confidence)`` when ``unit`` holds a trigger phrase."""
    if LAST.search(unit):
        return "last-resort", 0.8
    if SECOND.search(unit):
        return "second", 0.8
    if FIRST_STRONG.search(unit):
        return "first", 0.8
    if ALT.search(unit):
        return "alternative", 0.6
    if re.search(r"\bpreferred\b", unit, re.I):
        return "first", 0.6
    if FIRST_WEAK.search(unit):
        return "first", 0.45
    return None


# ----------------------------------------------------------------------------- data classes


@dataclass
class Found:
    """Entities found in one text unit, as IDs."""

    pathogens: list[str] = field(default_factory=list)
    mechanisms: list[str] = field(default_factory=list)
    drugs: list[str] = field(default_factory=list)
    # Mechanisms implied by a phenotype acronym (MRSA -> mecA) belong to that pathogen only.
    implied: dict[str, list[str]] = field(default_factory=dict)

    @staticmethod
    def _add(target: list[str], value: str) -> None:
        if value not in target:
            target.append(value)


class Extractor:
    """Rule-based recommendation extractor over passages."""

    def __init__(self, linker: EntityLinker | None = None, scope_path: Path = SCOPE_PATH) -> None:
        self.linker = linker or EntityLinker()
        scope = yaml.safe_load(scope_path.read_text(encoding="utf8"))
        self.names: dict[str, str] = {}
        for key in ("pathogens", "mechanisms", "drugs", "drug_classes"):
            for row in scope.get(key, []):
                self.names[row["id"]] = row["name"]
        self.valid_pairs: set[tuple[str, str]] = set()
        if PATHOGEN_MECHANISM_PATH.exists():
            with PATHOGEN_MECHANISM_PATH.open(encoding="utf8", newline="") as fh:
                self.valid_pairs = {(r["pathogen_id"], r["mechanism_id"]) for r in csv.DictReader(fh)}
        self.class_members: dict[str, list[str]] = {}
        for drug in scope["drugs"]:
            self.class_members.setdefault(drug["class_id"], []).append(drug["id"])

    # ------------------------------------------------------------------ entity collection

    def find(self, text: str) -> Found:
        """Link ``text`` and collect pathogen, mechanism and drug IDs (classes expanded)."""
        out = Found()
        mentions: list[LinkedMention] = self.linker.link(text)
        for m in mentions:
            if m.entity_type == "Pathogen":
                ids = m.pathogen_ids or [m.entity_id]
                for pid in ids:
                    out._add(out.pathogens, pid)
                for pid in ids:
                    for mid in m.mechanism_ids:
                        out._add(out.implied.setdefault(pid, []), mid)
            elif m.entity_type == "Mechanism":
                out._add(out.mechanisms, m.entity_id)
            elif m.entity_type in ("Drug", "DrugClass", "ClassFamily"):
                before, after = text[: m.start], text[m.end :]
                if RESISTANT_AFTER.search(after[:20]) or RESISTANT_BEFORE.search(before[-30:]):
                    continue
                if m.entity_type == "Drug":
                    out._add(out.drugs, m.entity_id)
                else:
                    for did in self.class_members.get(m.entity_id, []):
                        out._add(out.drugs, did)
        if ENTEROBACTERALES_RE.search(text):
            for pid in ENTEROBACTERALES_IDS:
                out._add(out.pathogens, pid)
        return out

    # ------------------------------------------------------------------ building outputs

    def _make(
        self,
        passage: dict[str, Any],
        *,
        pathogen: str,
        mechanism: list[str],
        drugs: list[str],
        line: str | None,
        evidence: str,
        confidence: float,
    ) -> RecommendationExtraction:
        return RecommendationExtraction(
            pathogen=self.names[pathogen],
            mechanism="|".join(self.names[m] for m in mechanism) or None,
            drugs=[self.names[d] for d in drugs],
            line_of_therapy=line,
            evidence_text=re.sub(r"\s+", " ", evidence).strip()[:400] or "(empty)",
            passage_id=passage["id"],
            method="rule",
            confidence=round(max(0.05, min(0.99, confidence)), 2),
        )

    # ------------------------------------------------------------------ rules

    def table4(self, passage: dict[str, Any]) -> list[RecommendationExtraction]:
        m = TABLE4.search(passage["text"])
        if not m or "Table 4" not in passage["text"]:
            return []
        mech = self.find(m["mech"]).mechanisms
        pathogens = self.find(passage["text"].split("Carbapenemase")[0]).pathogens
        if not pathogens:
            return []
        units = [("first", m["first"])]
        units += [("alternative", o) for o in OPTION_SPLIT.split(m["other"]) if o.strip()]
        out = []
        for line, chunk in units:
            drugs = self.find(chunk).drugs
            if not drugs:
                continue
            for pid in pathogens:
                out.append(
                    self._make(
                        passage, pathogen=pid, mechanism=mech, drugs=drugs, line=line,
                        evidence=chunk, confidence=0.95,
                    )
                )
        return out

    def trigger(self, passage: dict[str, Any]) -> list[RecommendationExtraction]:
        ctx_path = self.find(passage.get("heading") or "").pathogens
        heading_ctx = bool(ctx_path)
        out: list[RecommendationExtraction] = []
        for unit in (u.strip() for u in SPLIT.split(passage["text"]) if u):
            if len(unit) < 15 or len(unit.split()) > MAX_UNIT_WORDS:
                continue
            found = self.find(unit)
            if found.pathogens:
                ctx_path, heading_ctx = found.pathogens, False
            trig = classify_trigger(unit)
            if trig is None or NEGATION.search(unit) or not found.drugs:
                continue
            pathogens = found.pathogens or ctx_path
            if not pathogens:
                continue
            line, conf = trig
            if not found.pathogens:
                conf -= 0.25 if heading_ctx else 0.15
            if len(found.drugs) > 4:
                conf -= 0.1
            for pid in pathogens:
                for mechs in self._mechanism_options(pid, found):
                    out.append(
                        self._make(
                            passage, pathogen=pid, mechanism=mechs, drugs=found.drugs, line=line,
                            evidence=unit, confidence=conf,
                        )
                    )
        return out

    def _mechanism_options(self, pid: str, found: Found) -> list[list[str]]:
        """Mechanism lists to emit for one pathogen: stated mechanisms that the seed data knows
        for this pathogen, else the one implied by a phenotype (MRSA), else none."""
        stated = [[m] for m in found.mechanisms if (pid, m) in self.valid_pairs]
        return stated or [found.implied.get(pid, [])]

    def segment(self, passage: dict[str, Any]) -> list[RecommendationExtraction]:
        text = passage["text"]
        if not TABLE_COLUMNS.search(text):
            return []
        mentions = [
            m for m in self.linker.link(text)
            if m.entity_type == "Pathogen" and not m.ambiguous_pathogen
        ]
        out = []
        for i, pm in enumerate(mentions):
            end = mentions[i + 1].start if i + 1 < len(mentions) else len(text)
            seg = text[pm.end : end]
            found = self.find(seg)
            if not found.drugs or NEGATION.search(seg):
                continue
            out.append(
                self._make(
                    passage, pathogen=pm.entity_id, mechanism=list(pm.mechanism_ids),
                    drugs=found.drugs, line=None, evidence=text[pm.start : end], confidence=0.3,
                )
            )
        return out

    # ------------------------------------------------------------------ driver

    def extract_passage(self, passage: dict[str, Any]) -> list[RecommendationExtraction]:
        results = self.table4(passage)
        if not results:
            results = self.trigger(passage)
        results += self.segment(passage)
        return results

    def extract_all(self, passages: Iterable[dict[str, Any]]) -> list[RecommendationExtraction]:
        """Extract from guideline passages and drop repeats caused by the 30-word overlap.

        A repeat has the same document, pathogen, mechanism and drug set on the same or the next
        page; the higher-confidence one is kept.
        """
        kept: dict[tuple, tuple[RecommendationExtraction, int]] = {}
        order: list[tuple] = []
        for p in passages:
            if p["source_doc"].startswith("pubmed-"):
                continue
            page = p.get("page") or 0
            for rec in self.extract_passage(p):
                base = (p["source_doc"], rec.pathogen, rec.mechanism, tuple(sorted(rec.drugs)))
                key = next((k for k in order if k[:4] == base and abs(kept[k][1] - page) <= 1), None)
                if key is None:
                    key = base + (len(order),)
                    order.append(key)
                    kept[key] = (rec, page)
                elif (rec.confidence or 0) > (kept[key][0].confidence or 0):
                    kept[key] = (rec, page)
        return [kept[k][0] for k in order]

    # ------------------------------------------------------------------ names -> IDs

    def resolve_ids(self, rec: RecommendationExtraction) -> dict[str, Any]:
        """Link an extraction's free-text names to canonical IDs with the entity linker."""

        def one(name: str, kind: str) -> str | None:
            hit = self.linker.resolve(name, entity_type=kind)
            return hit.entity_id if hit else None

        mechs = [one(n, "Mechanism") for n in (rec.mechanism or "").split("|") if n]
        drugs = [one(n, "Drug") for n in rec.drugs]
        return {
            "pathogen_id": one(rec.pathogen, "Pathogen"),
            "mechanism_ids": sorted(x for x in mechs if x),
            "drug_ids": sorted(x for x in drugs if x),
            "line_of_therapy": rec.line_of_therapy.value if rec.line_of_therapy else None,
        }


def load_passages(path: Path = PASSAGES_PATH) -> list[dict[str, Any]]:
    with path.open(encoding="utf8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def write_jsonl(recs: Iterable[RecommendationExtraction], path: Path = OUT_PATH) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf8", newline="\n") as fh:
        for rec in recs:
            fh.write(json.dumps(rec.to_row(), ensure_ascii=False) + "\n")
            n += 1
    return n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--passages", type=Path, default=PASSAGES_PATH)
    ap.add_argument("--out", type=Path, default=OUT_PATH)
    args = ap.parse_args(argv)
    if not args.passages.exists():
        print(f"missing {args.passages}; run python -m pipeline.ingest first", file=sys.stderr)
        return 1
    recs = Extractor().extract_all(load_passages(args.passages))
    n = write_jsonl(recs, args.out)
    print(f"{n} extractions written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

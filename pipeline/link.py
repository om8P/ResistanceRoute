"""Entity linker for AMR-Navigator (task T07, DECISIONS D7 and D8).

One linker, used both when the graph is built (``python -m pipeline.link`` over the
passage corpus) and when a question is parsed (``EntityLinker.link`` / ``resolve``).

* ``link(text)`` finds mentions with spaCy ``PhraseMatcher`` (``spacy.blank("en")``,
  no model download). ``abbreviation`` synonyms match case-sensitively, every other
  synonym type case-insensitively. Overlaps are resolved by the longest match, so a
  combination such as ``ceftazidime-avibactam`` is never also linked as
  ``ceftazidime``. A last pass links near-miss spellings with ``rapidfuzz``.
* ``resolve(surface, entity_type=None)`` maps one surface string to an entity:
  exact, then normalised, then fuzzy, and records ``match_type`` and ``score``.
* Phenotype acronyms (MRSA, CRKP, ...) resolve to the pathogen and carry the
  implied mechanisms and class family from ``schema/phenotypes.csv``.

Scores: exact 1.0, normalised 0.97, fuzzy the rapidfuzz ratio / 100 (capped at 0.95).
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

import spacy
import yaml
from rapidfuzz import fuzz, process
from rapidfuzz.distance import DamerauLevenshtein
from spacy.matcher import PhraseMatcher

from pipeline.config import DATA_PROCESSED, EVAL_DIR, SCHEMA_DIR

# --------------------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------------------

# When one string belongs to several entity types, the first type in this list wins.
# ClassFamily comes before DrugClass because the parser should prefer the family reading
# of "carbapenems" (REVIEW_NOTES 2.6).
TYPE_PRIORITY = ["Pathogen", "Drug", "Mechanism", "Gene", "ClassFamily", "DrugClass"]

SCORE_EXACT = 1.0
SCORE_NORMALISED = 0.97
FUZZY_CUTOFF = 85  # rapidfuzz.fuzz.ratio, 0-100
FUZZY_SCORE_CAP = 0.95
FUZZY_MIN_LEN = 5  # characters of the normalised surface
FUZZY_MAX_WORDS = 3

# Entity types that may become MENTIONS edges (models.EDGE_TYPES["MENTIONS"]).
EDGE_LABELS = {"Pathogen", "Drug", "DrugClass", "Mechanism"}

GREEK = {"α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "ß": "beta"}
_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−"), "-")
_SPACES = dict.fromkeys(map(ord, "    "), " ")
_TEXT_MAP = {**_DASHES, **_SPACES}  # one character to one character: offsets stay valid

_SEP = re.compile(r"[\s\-/+_.,;:()\[\]'’]+")
_CHUNK = re.compile(r"[^\W\d_](?:[\w\-/+]*\w)?")

# Species of the four in-scope genera that are NOT in scope. A bare genus name
# ("Klebsiella") links to the in-scope species (T03 simplification), but not when the
# next word names one of these other species.
OTHER_SPECIES = {
    "oxytoca", "variicola", "aerogenes", "michiganensis", "quasipneumoniae", "granulomatis",
    "fergusonii", "hermannii", "albertii", "vulneris", "blattae",
    "lwoffii", "pittii", "nosocomialis", "calcoaceticus", "haemolyticus", "junii",
    "johnsonii", "ursingii", "radioresistens", "bereziniae", "seifertii",
    "putida", "fluorescens", "stutzeri", "mendocina", "syringae", "putrefaciens",
    "alcaligenes", "monteilii", "otitidis", "protegens",
}

# Rule-based detection of entity-like strings the dictionary does not know (unlinked.csv).
_DRUG_LIKE = re.compile(
    r"\b(?:[A-Za-z]{2,}(?:cillin|penem|floxacin|oxacin|mycin|micin|cycline|bactam|navir"
    r"|oxazolid\w*|vancin|planin|conazole|trimoxazole|sulfa\w+)"
    r"|cef[a-z]{3,}|ceph[a-z]{4,}|aztreonam|colistin|polymyxin|fosfomycin|trimethoprim"
    r"|nitrofurantoin|rifampi[cn]\w*|daptomycin|linezolid|clindamycin|chloramphenicol"
    r"|temocillin|mecillinam|pivmecillinam)\b",
    re.IGNORECASE,
)
_MECH_LIKE = re.compile(
    r"\b(?:bla[A-Z][A-Za-z0-9]*(?:-\d+)?|mcr-?\d+[a-z]?"
    r"|(?:OXA|NDM|VIM|IMP|KPC|GES|CTX-M|SHV|TEM|CMY|OprD|OmpK3[56]|AcrAB|MexAB|MexXY|MexCD)"
    r"(?:-?\d[\w\-]*|-type)?"
    r"|(?:DHA|ACT|FOX|MOX|SPM|GIM|SIM|AIM|BIC|PER|VEB|TLA|SFO|BEL)-?\d[\w\-]*"
    r"|(?:metallo-?)?(?:beta|β)-?lactamases?|carbapenemases?|AmpC|porin\s+loss"
    r"|efflux\s+pumps?|ESBLs?)\b"
)
_PATHOGEN_LIKE = re.compile(
    r"\b(?:(?:Staphylococcus|Streptococcus|Enterococcus|Klebsiella|Escherichia|Enterobacter"
    r"|Citrobacter|Serratia|Proteus|Salmonella|Shigella|Acinetobacter|Pseudomonas"
    r"|Stenotrophomonas|Burkholderia|Haemophilus|Neisseria|Mycobacterium|Candida"
    r"|Morganella|Providencia|Clostridioides)\s+[a-z]{4,}"
    r"|[A-Z]\.\s?[a-z]{4,}|Enterobacterales|Enterobacteriaceae)\b"
)


# --------------------------------------------------------------------------------------
# Data classes
# --------------------------------------------------------------------------------------


@dataclass
class LinkedEntity:
    """The result of ``EntityLinker.resolve``."""

    entity_id: str
    entity_type: str
    canonical_name: str
    match_type: str  # exact | normalised | fuzzy
    score: float
    synonym: str = ""  # the dictionary string that matched
    # Phenotype acronyms only (MRSA, CRKP, ...):
    phenotype: str = ""
    pathogen_ids: list[str] = field(default_factory=list)
    mechanism_ids: list[str] = field(default_factory=list)
    class_family: str = ""
    # Other entities the same string could stand for (entity_type, entity_id).
    alternatives: list[tuple[str, str]] = field(default_factory=list)

    @property
    def ambiguous_pathogen(self) -> bool:
        """True for a phenotype that spans several species (CRE, ESBL-E)."""
        return len(self.pathogen_ids) > 1


@dataclass
class LinkedMention:
    """One mention found in a text. Serialises to a ``mentions_linked.jsonl`` row."""

    passage_id: str
    start: int
    end: int
    surface: str
    entity_type: str
    entity_id: str
    match_type: str
    score: float
    canonical_name: str = ""
    phenotype: str = ""
    pathogen_ids: list[str] = field(default_factory=list)
    mechanism_ids: list[str] = field(default_factory=list)
    class_family: str = ""

    @property
    def ambiguous_pathogen(self) -> bool:
        return len(self.pathogen_ids) > 1

    def to_mention_row(self) -> dict[str, Any]:
        """The ``mentions.jsonl`` shape (CONTRACTS section 6)."""
        return {
            "passage_id": self.passage_id,
            "start": self.start,
            "end": self.end,
            "surface": self.surface,
            "entity_type": self.entity_type,
        }

    def to_row(self) -> dict[str, Any]:
        """The ``mentions_linked.jsonl`` shape: mention fields plus the link.

        Phenotype mentions carry four extra keys (phenotype, pathogen_ids, mechanism_ids,
        class_family); other mentions have only the contract keys plus canonical_name.
        """
        row = self.to_mention_row()
        row.update(
            entity_id=self.entity_id,
            match_type=self.match_type,
            score=round(self.score, 4),
            canonical_name=self.canonical_name,
        )
        if self.phenotype:
            row.update(
                phenotype=self.phenotype,
                pathogen_ids=self.pathogen_ids,
                mechanism_ids=self.mechanism_ids,
                class_family=self.class_family,
            )
        return row


@dataclass(frozen=True)
class _Entry:
    entity_type: str
    entity_id: str
    canonical_name: str
    synonym: str
    synonym_type: str

    @property
    def case_sensitive(self) -> bool:
        return self.synonym_type == "abbreviation"


# --------------------------------------------------------------------------------------
# Normalisation helpers
# --------------------------------------------------------------------------------------


def _greek(s: str) -> str:
    for g, name in GREEK.items():
        s = s.replace(g, name)
    return s


def norm_cs(s: str) -> str:
    """Case-preserving key (abbreviations): separators, Greek letters and spacing only."""
    return " ".join(_words(s, False))


_ALNUM_SPLIT = re.compile(r"(?<=[^\W\d_])(?=\d)|(?<=\d)(?=[^\W\d_])")


def _words(s: str, fold: bool) -> list[str]:
    """Words of ``s`` after unifying separators, Greek letters and letter/digit joins
    ("OXA48" and "OXA-48" both give ["OXA", "48"])."""
    s = unicodedata.normalize("NFKC", s)
    if fold:
        s = s.casefold()
    s = _greek(s).translate(_TEXT_MAP)
    return _ALNUM_SPLIT.sub(" ", _SEP.sub(" ", s)).split()


def norm_ci(s: str) -> str:
    """Case-insensitive key: case, hyphens, slashes, plus signs, dots, Greek letters,
    letter/digit joins, "and"/"plus" and a trailing plural "s" are ignored."""
    words = [w for w in _words(s, True) if w not in ("and", "plus")]
    if words and len(words[-1]) > 4 and words[-1].endswith("s") and not words[-1].endswith("ss"):
        words[-1] = words[-1][:-1]
    return " ".join(words)


_ALLELE_SYN = re.compile(r"(?:bla)?([A-Za-z]+(?:-[A-Z])?)-\d+[a-z]?$", re.IGNORECASE)
_ALLELE_TOKEN = re.compile(r"(?:bla)?([A-Za-z]+(?:-[A-Z])?)-?\d+[a-z]?", re.IGNORECASE)
SCORE_ALLELE = 0.93

_SENTENCE_DOT = re.compile(r"(?<=[^\W_])(?<![\s(][A-Z])\.(?=\s*$|\s+[A-Z0-9])")


def _prep(text: str) -> str:
    """Text as the matcher sees it. Same length as ``text``, so offsets stay valid:
    typographic dashes become hyphens, and a sentence-final period is blanked because
    spaCy otherwise keeps it inside tokens such as "mecA." ("K. pneumoniae" is untouched:
    a period after a single capital letter, or before a lower-case word, stays)."""
    t = text.translate(_TEXT_MAP)
    return _SENTENCE_DOT.sub(" ", t)


def _variants(entry: _Entry) -> set[str]:
    """Surface forms to give the PhraseMatcher for one synonym."""
    syn = entry.synonym
    out = {syn}
    for src, dst in (("β", "beta"), ("beta", "β")):
        if src in syn:
            out.add(syn.replace(src, dst))
    if entry.case_sensitive:
        # Acronym combinations: CAZ-AVI, CAZ/AVI, CAZ+AVI. Plural of a one-token acronym.
        parts = re.split(r"[-/]", syn)
        if len(parts) > 1 and all(p.isalpha() and p.isupper() and len(p) >= 3 for p in parts):
            out |= _join_variants(parts)
        if syn.isalpha() and syn.isupper() and len(syn) >= 3 and entry.entity_type != "Drug":
            out.add(syn + "s")
        return out
    if entry.entity_type == "Drug":
        parts = re.split(r"[-/]", syn)
        if len(parts) > 1 and all(p.isalpha() and len(p) >= 3 for p in parts):
            out |= _join_variants(parts)
    if "-" in syn:
        out.add(syn.replace("-", " "))
    if entry.entity_type in ("DrugClass", "ClassFamily") and syn[-1:].isalpha() and not syn.endswith("s"):
        out.add(syn + "s")
    return out


def _join_variants(parts: list[str]) -> set[str]:
    seps = ["-", "/", "+", " + ", " ", " and "]
    return {
        "".join(p + (s[i] if i < len(s) else "") for i, p in enumerate(parts))
        for s in itertools.product(seps, repeat=len(parts) - 1)
    }


# --------------------------------------------------------------------------------------
# The linker
# --------------------------------------------------------------------------------------


class EntityLinker:
    """Dictionary-based entity matcher and linker (see the module docstring)."""

    def __init__(
        self,
        synonyms_path: Path | None = None,
        scope_path: Path | None = None,
        phenotypes_path: Path | None = None,
    ) -> None:
        synonyms_path = synonyms_path or SCHEMA_DIR / "synonyms.csv"
        scope_path = scope_path or SCHEMA_DIR / "scope.yaml"
        phenotypes_path = phenotypes_path or SCHEMA_DIR / "phenotypes.csv"

        self._entries: list[_Entry] = []
        self._exact: dict[str, list[_Entry]] = defaultdict(list)
        self._norm_cs: dict[str, list[_Entry]] = defaultdict(list)
        self._norm_ci: dict[str, list[_Entry]] = defaultdict(list)
        self._phenotypes: dict[str, dict[str, Any]] = {}
        self._fuzzy_cache: dict[tuple[str, Optional[str]], Optional[tuple[_Entry, float]]] = {}

        self._load_synonyms(synonyms_path)
        self._load_scope(scope_path)
        self._load_phenotypes(phenotypes_path)
        self._build_indexes()
        self._build_matchers()

    # ------------------------------------------------------------------ loading

    def _add(self, entry: _Entry) -> None:
        if entry not in self._entries:
            self._entries.append(entry)

    def _load_synonyms(self, path: Path) -> None:
        with path.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                syn = row["synonym"].strip()
                if syn:
                    self._add(
                        _Entry(row["entity_type"], row["entity_id"], row["canonical_name"],
                               syn, row["synonym_type"])
                    )

    def _load_scope(self, path: Path) -> None:
        """Make sure every scope name is also a linkable canonical synonym."""
        scope = yaml.safe_load(path.read_text(encoding="utf-8"))
        self._names: dict[str, str] = {}
        for key, etype in (("pathogens", "Pathogen"), ("mechanisms", "Mechanism"),
                           ("drug_classes", "DrugClass"), ("drugs", "Drug")):
            for item in scope.get(key, []):
                self._names[item["id"]] = item["name"]
                self._add(_Entry(etype, item["id"], item["name"], item["name"], "canonical"))

    def _load_phenotypes(self, path: Path) -> None:
        if not path.is_file():
            return
        with path.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                acr = row["acronym"].strip()
                ph = self._phenotypes.setdefault(
                    acr, {"pathogen_ids": [], "mechanism_ids": [], "class_family": ""}
                )
                pid = row["pathogen_id"].strip()
                if pid and pid not in ph["pathogen_ids"]:
                    ph["pathogen_ids"].append(pid)
                for mid in filter(None, (m.strip() for m in row["mechanism_ids"].split("|"))):
                    if mid not in ph["mechanism_ids"]:
                        ph["mechanism_ids"].append(mid)
                ph["class_family"] = ph["class_family"] or row["class_family"].strip()
        # An acronym missing from synonyms.csv (CRE, ESBL-E, ...) is added as an
        # abbreviation of its first pathogen.
        known = {e.synonym for e in self._entries if e.entity_type == "Pathogen"}
        for acr, ph in self._phenotypes.items():
            if acr not in known and ph["pathogen_ids"]:
                pid = ph["pathogen_ids"][0]
                self._add(_Entry("Pathogen", pid, self._names.get(pid, pid), acr, "abbreviation"))

    def _build_indexes(self) -> None:
        for e in self._entries:
            self._exact[e.synonym].append(e)
            if e.case_sensitive:
                self._norm_cs[norm_cs(e.synonym)].append(e)
            else:
                self._norm_ci[norm_ci(e.synonym)].append(e)
        # Fuzzy pool: case-insensitive synonyms long enough to be distinctive.
        self._fuzzy_keys = [k for k in self._norm_ci if len(k) >= FUZZY_MIN_LEN]
        # Gene families whose alleles are numbered (KPC-2, NDM-5, CTX-M-15, mcr-3): a numbered
        # allele that is not itself a synonym links to the family. Families that share a base
        # name (OXA-48-like vs OXA-23-like) are left out because the number decides the family.
        bases: dict[str, set[str]] = defaultdict(set)
        canon: dict[str, _Entry] = {}
        for e in self._entries:
            if e.entity_type == "Mechanism":
                m = _ALLELE_SYN.match(e.synonym)
                if m:
                    bases[m.group(1).lower()].add(e.entity_id)
                if e.synonym_type == "canonical":
                    canon[e.entity_id] = e
        self._allele_bases = {b: canon[next(iter(ids))] for b, ids in bases.items()
                              if len(ids) == 1 and next(iter(ids)) in canon}

    def _build_matchers(self) -> None:
        self._nlp = spacy.blank("en")
        self._cs_matcher = PhraseMatcher(self._nlp.vocab, attr="ORTH")
        self._ci_matcher = PhraseMatcher(self._nlp.vocab, attr="LOWER")
        self._pattern_entries: dict[str, list[_Entry]] = defaultdict(list)
        seen: set[str] = set()
        for e in self._entries:
            for v in _variants(e):
                key = ("S|" + v) if e.case_sensitive else ("I|" + v.casefold())
                if e not in self._pattern_entries[key]:
                    self._pattern_entries[key].append(e)
                if key in seen:
                    continue
                seen.add(key)
                matcher = self._cs_matcher if e.case_sensitive else self._ci_matcher
                matcher.add(key, [self._nlp.make_doc(v)])

    # ------------------------------------------------------------------ resolve

    def _choose(self, cands: list[_Entry]) -> tuple[_Entry, list[tuple[str, str]]]:
        def rank(e: _Entry) -> tuple[int, str]:
            t = TYPE_PRIORITY.index(e.entity_type) if e.entity_type in TYPE_PRIORITY else 99
            return (t, e.entity_id)

        ordered = sorted(cands, key=rank)
        best = ordered[0]
        alts: list[tuple[str, str]] = []
        for e in ordered[1:]:
            pair = (e.entity_type, e.entity_id)
            if pair != (best.entity_type, best.entity_id) and pair not in alts:
                alts.append(pair)
        return best, alts

    def _entity(self, cands: list[_Entry], match_type: str, score: float) -> LinkedEntity:
        best, alts = self._choose(cands)
        ent = LinkedEntity(
            entity_id=best.entity_id,
            entity_type=best.entity_type,
            canonical_name=best.canonical_name,
            match_type=match_type,
            score=score,
            synonym=best.synonym,
            alternatives=alts,
        )
        ph = self._phenotypes.get(best.synonym) if best.entity_type == "Pathogen" else None
        if ph:
            ent.phenotype = best.synonym
            ent.pathogen_ids = list(ph["pathogen_ids"])
            ent.mechanism_ids = list(ph["mechanism_ids"])
            ent.class_family = ph["class_family"]
        return ent

    @staticmethod
    def _filter(cands: Iterable[_Entry], entity_type: str | None) -> list[_Entry]:
        return [c for c in cands if entity_type is None or c.entity_type == entity_type]

    def resolve(
        self, surface: str, entity_type: str | None = None, fuzzy: bool = True
    ) -> LinkedEntity | None:
        """Resolve one surface string: exact, then normalised, then fuzzy.

        ``entity_type`` restricts the answer to one type. Abbreviations are only ever
        matched case-sensitively, and never fuzzily.
        """
        s = surface.strip()
        if not s:
            return None
        exact = self._filter(self._exact.get(s, []), entity_type)
        # Exact and normalised candidates compete together, so that "carbapenems" (a
        # DrugClass synonym verbatim) still resolves to the ClassFamily reading.
        cands = self._filter(self._norm_cs.get(norm_cs(s), []) + self._norm_ci.get(norm_ci(s), []),
                             entity_type)
        pool = exact + [c for c in cands if c not in exact]
        if pool:
            best, _ = self._choose(pool)
            if best in exact:
                return self._entity(pool, "exact", SCORE_EXACT)
            return self._entity(pool, "normalised", SCORE_NORMALISED)
        if not cands and len(s) > 3 and s.endswith("s") and s[:-1].isupper():
            cands = self._filter(
                [e for e in self._exact.get(s[:-1], []) if e.case_sensitive and e.entity_type != "Drug"], entity_type
            )
        if cands:
            return self._entity(cands, "normalised", SCORE_NORMALISED)

        if fuzzy:
            hit = self._fuzzy(norm_ci(s), entity_type)
            if hit:
                entry, ratio = hit
                cands = self._filter(self._norm_ci[norm_ci(entry.synonym)], entity_type)
                return self._entity(cands, "fuzzy", min(ratio / 100.0, FUZZY_SCORE_CAP))
        return None

    def _fuzzy(self, key: str, entity_type: str | None) -> tuple[_Entry, float] | None:
        """Best near-miss of a normalised key, or None. Strict guards keep common words out:
        the key needs at least 5 characters, the same first letter, digits and word count as
        the dictionary string, at most one typo (a transposition counts as one) per word and
        two in total, and a rapidfuzz ratio of at least 85."""
        if len(key) < FUZZY_MIN_LEN:
            return None
        ck = (key, entity_type)
        if ck in self._fuzzy_cache:
            return self._fuzzy_cache[ck]
        result = None
        digits = re.sub(r"\D", "", key)
        for cand, ratio, _ in process.extract(
            key, self._fuzzy_keys, scorer=fuzz.ratio, score_cutoff=FUZZY_CUTOFF, limit=5
        ):
            if cand[0] != key[0] or re.sub(r"\D", "", cand) != digits:
                continue
            kw, cw = key.split(), cand.split()
            if len(kw) != len(cw):
                continue
            dists = [DamerauLevenshtein.distance(a, b) for a, b in zip(kw, cw)]
            if max(dists) > 1 or sum(dists) > 2:
                continue  # at most one typo per word, two in total
            entries = self._filter(self._norm_ci[cand], entity_type)
            if entries:
                best, _ = self._choose(entries)
                result = (best, ratio)
                break
        self._fuzzy_cache[ck] = result
        return result

    # --------------------------------------------------------------------- link

    def link(self, text: str, passage_id: str = "", fuzzy: bool = True) -> list[LinkedMention]:
        """Find and link all mentions in ``text``. Offsets refer to ``text``."""
        t = _prep(text)
        doc = self._nlp.make_doc(t)
        found: dict[tuple[int, int], list[_Entry]] = defaultdict(list)
        for matcher in (self._cs_matcher, self._ci_matcher):
            for match_id, s, e in matcher(doc):
                span = doc[s:e]
                entries = self._pattern_entries[self._nlp.vocab.strings[match_id]]
                if self._is_other_species(entries, t, span.end_char):
                    continue
                found[(span.start_char, span.end_char)].extend(entries)

        taken: list[tuple[int, int]] = []
        mentions: list[LinkedMention] = []
        for (start, end), entries in sorted(found.items(), key=lambda kv: (kv[0][0] - kv[0][1], kv[0][0])):
            if any(start < b and a < end for a, b in taken):
                continue  # overlaps a longer (or earlier) match
            taken.append((start, end))
            surface = text[start:end]
            best, _ = self._choose(entries)
            is_exact = best.synonym == surface
            ent = self._entity(entries, "exact" if is_exact else "normalised",
                               SCORE_EXACT if is_exact else SCORE_NORMALISED)
            mentions.append(self._mention(passage_id, start, end, surface, ent))

        if fuzzy:
            mentions = self._fuzzy_scan(text, text.translate(_TEXT_MAP), passage_id, mentions)
        return sorted(mentions, key=lambda m: m.start)

    @staticmethod
    def _mention(passage_id: str, start: int, end: int, surface: str, ent: LinkedEntity) -> LinkedMention:
        return LinkedMention(
            passage_id=passage_id, start=start, end=end, surface=surface,
            entity_type=ent.entity_type, entity_id=ent.entity_id,
            match_type=ent.match_type, score=ent.score, canonical_name=ent.canonical_name,
            phenotype=ent.phenotype, pathogen_ids=ent.pathogen_ids,
            mechanism_ids=ent.mechanism_ids, class_family=ent.class_family,
        )

    @staticmethod
    def _is_other_species(entries: list[_Entry], t: str, end: int) -> bool:
        """A bare genus name followed by the name of a species we do not cover."""
        if not all(e.entity_type == "Pathogen" and e.synonym.isalpha() and e.synonym_type == "variant"
                   for e in entries):
            return False
        m = re.match(r"\s+([A-Za-z]+)", t[end:])
        return bool(m and m.group(1).lower() in OTHER_SPECIES)

    def _fuzzy_scan(
        self, text: str, t: str, passage_id: str, exact: list[LinkedMention]
    ) -> list[LinkedMention]:
        """Add near-miss spellings to the exact mentions.

        A fuzzy window may not overlap an exact mention, except that it may swallow one
        that links to the same entity (so "Pseudomonas aeruginsa" replaces the bare
        "Pseudomonas"). Returns the combined list."""
        chunks = [(m.start(), m.end()) for m in _CHUNK.finditer(t)]
        hits: list[tuple[int, int, LinkedEntity]] = []
        for a0, a1 in chunks:  # numbered alleles: blaNDM-1, KPC-4, CTX-M-27, mcr-3
            m = _ALLELE_TOKEN.fullmatch(t[a0:a1])
            fam = self._allele_bases.get(m.group(1).lower()) if m else None
            if not fam:
                continue
            over = [x for x in exact if a0 < x.end and x.start < a1]
            # The allele token may swallow shorter matches inside it ("CTX" of "CTX-M-27",
            # which is also the code for cefotaxime), but not replace an identical span.
            if all(a0 <= x.start and x.end <= a1 for x in over) and not any(
                x.start == a0 and x.end == a1 for x in over
            ):
                hits.append((a0, a1, self._entity([fam], "normalised", SCORE_ALLELE)))
        for i, (s0, _) in enumerate(chunks):
            for w in range(min(FUZZY_MAX_WORDS, len(chunks) - i), 0, -1):
                j = i + w - 1
                if any(t[chunks[k][1]:chunks[k + 1][0]].strip() for k in range(i, j)):
                    continue  # words must be separated by whitespace only
                start, end = s0, chunks[j][1]
                overlapping = [m for m in exact if start < m.end and m.start < end]
                if overlapping and not all(start <= m.start and m.end <= end for m in overlapping):
                    continue
                if any(m.start == start and m.end == end for m in overlapping):
                    continue  # the matcher already found exactly this span
                window = t[start:end]
                key = norm_ci(window)
                # Windows that lose words in normalisation ("and", "plus") are not mentions.
                if len(key.split()) != len(_words(window, True)):
                    continue
                direct = [e for e in self._norm_cs.get(norm_cs(window), []) if len(e.synonym) >= 4]
                direct += self._norm_ci.get(key, [])
                if direct:
                    # Same string as a synonym once spacing is ignored: "OXA48", "KPC2".
                    if self._is_other_species(direct, t, end):
                        continue
                    ent = self._entity(direct, "normalised", SCORE_NORMALISED)
                else:
                    if len(key) < FUZZY_MIN_LEN or (chunks[i][1] - chunks[i][0]) < 3:
                        continue
                    hit = self._fuzzy(key, None)
                    if hit is None:
                        continue
                    entry, ratio = hit
                    ent = self._entity(self._norm_ci[norm_ci(entry.synonym)], "fuzzy",
                                       min(ratio / 100.0, FUZZY_SCORE_CAP))
                if any(m.entity_id != ent.entity_id for m in overlapping):
                    continue
                hits.append((start, end, ent))
        out = list(exact)
        used: list[tuple[int, int]] = []
        for start, end, ent in sorted(hits, key=lambda h: (-(h[2].score), h[0] - h[1])):
            if any(start < b and a < end for a, b in used):
                continue
            used.append((start, end))
            out = [m for m in out if not (start <= m.start and m.end <= end)]
            out.append(self._mention(passage_id, start, end, text[start:end], ent))
        return out

    # ----------------------------------------------------------------- unlinked

    @staticmethod
    def find_unlinked(text: str, covered: list[tuple[int, int]]) -> list[tuple[int, int, str, str]]:
        """Entity-like strings (drug-like names, resistance genes, species names) that no
        linked mention covers. Returns ``(start, end, surface, entity_type_guess)``."""
        out: list[tuple[int, int, str, str]] = []
        for rx, etype in ((_DRUG_LIKE, "Drug"), (_MECH_LIKE, "Mechanism"), (_PATHOGEN_LIKE, "Pathogen")):
            for m in rx.finditer(text):
                a, b = m.span()
                if any(a < d and c < b for c, d in covered):
                    continue
                if any(a < d and c < b for c, d, _, _ in out):
                    continue
                out.append((a, b, m.group(0), etype))
        return sorted(out)


# --------------------------------------------------------------------------------------
# Corpus run
# --------------------------------------------------------------------------------------


def _jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    n = 0
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
    return n


def run_corpus(
    passages_path: Path | None = None, out_dir: Path | None = None, linker: EntityLinker | None = None
) -> dict[str, int]:
    """Link every passage and write the four output files. Returns counts."""
    passages_path = passages_path or DATA_PROCESSED / "passages.jsonl"
    out_dir = out_dir or DATA_PROCESSED
    out_dir.mkdir(parents=True, exist_ok=True)
    linker = linker or EntityLinker()

    linked_rows: list[dict[str, Any]] = []
    mention_rows: list[dict[str, Any]] = []
    edge_best: dict[tuple[str, str, str], float] = {}
    unlinked: dict[tuple[str, str], list[Any]] = {}
    n_passages = 0

    with passages_path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            p = json.loads(line)
            n_passages += 1
            pid, text = p["id"], p["text"]
            mentions = linker.link(text, passage_id=pid)
            for m in mentions:
                linked_rows.append(m.to_row())
                mention_rows.append(m.to_mention_row())
                # ClassFamily and Gene are not MENTIONS targets; a phenotype spanning
                # several species (CRE, ESBL-E) names no single pathogen.
                if m.entity_type in EDGE_LABELS and not m.ambiguous_pathogen:
                    k = (pid, m.entity_id, m.entity_type)
                    edge_best[k] = max(edge_best.get(k, 0.0), m.score)
            covered = [(m.start, m.end) for m in mentions]
            for a, b, surface, etype in linker.find_unlinked(text, covered):
                mention_rows.append(
                    {"passage_id": pid, "start": a, "end": b, "surface": surface, "entity_type": etype}
                )
                key_s = surface if (not surface.islower() and not surface.istitle()) else surface.lower()
                rec = unlinked.setdefault((key_s, etype), [0, pid])
                rec[0] += 1

    n_men = _jsonl(out_dir / "mentions.jsonl", mention_rows)
    n_linked = _jsonl(out_dir / "mentions_linked.jsonl", linked_rows)

    with (out_dir / "unlinked.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["surface", "entity_type", "count", "example_passage_id"])
        for (surface, etype), (count, example) in sorted(unlinked.items(), key=lambda kv: (-kv[1][0], kv[0][0])):
            w.writerow([surface, etype, count, example])

    with (out_dir / "edges_MENTIONS.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["start_id", "start_label", "end_id", "end_label", "source_id", "method",
                    "confidence", "evidence_passage_id"])
        for (pid, eid, label), score in sorted(edge_best.items()):
            w.writerow([pid, "Passage", eid, label, "curated-seed", "rule", round(score, 4), pid])

    return {"passages": n_passages, "mentions_total": n_men, "mentions_linked": n_linked,
            "edges": len(edge_best), "unlinked_surfaces": len(unlinked)}


# --------------------------------------------------------------------------------------
# Evaluation on the hand-labelled gold file
# --------------------------------------------------------------------------------------


def evaluate_gold(path: Path | None = None, linker: EntityLinker | None = None) -> dict[str, Any]:
    """Score the linker on ``eval/linking_gold.csv`` (columns text,surface,entity_type,entity_id).

    A predicted mention is correct when its (surface, entity_id) equals a gold row of the
    same text (surface compared case-insensitively). Rows with an empty entity_id are
    sentences without any entity: they are correct only if nothing is linked.
    ``accuracy`` is over all gold rows, ``precision`` and ``recall`` over mentions.
    """
    path = path or EVAL_DIR / "linking_gold.csv"
    linker = linker or EntityLinker()
    by_text: dict[str, list[dict[str, str]]] = defaultdict(list)
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            by_text[row["text"]].append(row)

    tp = n_pred = n_gold = correct_rows = n_rows = 0
    errors: list[dict[str, Any]] = []
    for text, rows in by_text.items():
        preds = linker.link(text)
        pred_keys = {(m.surface.casefold(), m.entity_id) for m in preds}
        n_pred += len(pred_keys)
        for row in rows:
            n_rows += 1
            if not row["entity_id"]:
                ok = not preds
                if not ok:
                    errors.append({"text": text, "gold": None, "predicted": sorted(pred_keys)})
            else:
                n_gold += 1
                ok = (row["surface"].casefold(), row["entity_id"]) in pred_keys
                tp += ok
                if not ok:
                    errors.append({"text": text, "gold": (row["surface"], row["entity_id"]),
                                   "predicted": sorted(pred_keys)})
            correct_rows += ok
        gold_keys = {(r["surface"].casefold(), r["entity_id"]) for r in rows if r["entity_id"]}
        for k in pred_keys - gold_keys:
            errors.append({"text": text, "gold": None, "false_positive": k})
    return {
        "rows": n_rows, "texts": len(by_text), "gold_mentions": n_gold, "predicted_mentions": n_pred,
        "true_positives": tp,
        "accuracy": correct_rows / n_rows if n_rows else 0.0,
        "precision": tp / n_pred if n_pred else 0.0,
        "recall": tp / n_gold if n_gold else 0.0,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m pipeline.link", description=__doc__.split("\n")[0])
    ap.add_argument("--passages", type=Path, default=DATA_PROCESSED / "passages.jsonl")
    ap.add_argument("--out-dir", type=Path, default=DATA_PROCESSED)
    ap.add_argument("--eval", action="store_true", help="score eval/linking_gold.csv instead of running the corpus")
    ap.add_argument("--gold", type=Path, default=EVAL_DIR / "linking_gold.csv")
    args = ap.parse_args(argv)

    linker = EntityLinker()
    if args.eval:
        res = evaluate_gold(args.gold, linker)
        errors = res.pop("errors")
        print(json.dumps(res, indent=2))
        for e in errors:
            print("ERROR", json.dumps(e, ensure_ascii=False), file=sys.stderr)
        return 0
    if not args.passages.is_file():
        print(f"{args.passages} not found (written by T06); nothing to do.", file=sys.stderr)
        return 1
    print(json.dumps(run_corpus(args.passages, args.out_dir, linker), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Query parser: a natural-language question to a ``ParsedQuery`` (task T12).

``parse(question)`` does three things, in this order:

1. **Entities.** ``pipeline.link.EntityLinker`` links the question. Question tokens of three
   or more letters that match nothing are retried upper-cased (D37), so ``mrsa`` and ``cza``
   resolve. Phenotype acronyms add their pathogen, implied mechanisms and class family; an
   ambiguous one (CRE, ESBL-E) adds every pathogen it covers unless the question names one of
   them. Countries (name or ISO 3) and years are extracted for surveillance questions.
2. **Decline rules (D18)**, checked first: dosing and duration, patient-specific advice,
   pregnancy or child treatment, and pathogens outside the five-pathogen scope.
3. **Intent rules**, in the order of ``INTENT_RULES``. The first rule that fires wins; if none
   does the intent is ``unknown`` and the caller falls back to text search.

Educational use only: nothing here gives clinical advice.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from pipeline.link import EntityLinker, LinkedMention
from retrieval.types import ParsedQuery

ROOT = Path(__file__).resolve().parents[1]
COUNTRIES_CSV = ROOT / "data" / "raw" / "glass" / "countries.csv"

_linker: EntityLinker | None = None


def get_linker() -> EntityLinker:
    """One shared linker (building it reads the schema files and takes about a second)."""
    global _linker
    if _linker is None:
        _linker = EntityLinker()
    return _linker


# --------------------------------------------------------------------------------------
# Countries and years
# --------------------------------------------------------------------------------------

# Names people type that differ from the GLASS short names.
COUNTRY_ALIASES = {
    "usa": "USA", "u.s.a.": "USA", "united states": "USA", "united states of america": "USA",
    "uk": "GBR", "u.k.": "GBR", "britain": "GBR", "great britain": "GBR", "england": "GBR",
    "united kingdom": "GBR", "south korea": "KOR", "korea": "KOR", "russia": "RUS",
    "vietnam": "VNM", "turkey": "TUR", "turkiye": "TUR", "türkiye": "TUR", "iran": "IRN",
    "uae": "ARE", "tanzania": "TZA", "laos": "LAO", "syria": "SYR", "moldova": "MDA",
    "bolivia": "BOL", "venezuela": "VEN", "czech republic": "CZE", "czechia": "CZE",
}
# Country names that are also ordinary words or first names: match only when capitalised.
CAPITAL_ONLY = {"chad", "georgia", "jersey", "guinea", "turkey"}
# ISO 3 codes that are also words or drug codes; never read as a country from upper case.
ISO3_SKIP = {"CAN", "MAR", "COM", "DOM", "PER", "SEN", "NOR", "SAM", "GAB", "TOG", "MAY", "LAO"}

_country_names: list[tuple[str, str, bool]] | None = None  # (lower name, ISO 3, capital_only)
_iso3: set[str] = set()


def _load_countries() -> list[tuple[str, str, bool]]:
    global _country_names
    if _country_names is not None:
        return _country_names
    names: dict[str, str] = {}
    if COUNTRIES_CSV.is_file():
        with COUNTRIES_CSV.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                code = row["CODE_ISO_3"].strip()
                _iso3.add(code)
                full = row["NAME_SHORT_EN"].strip()
                for variant in {full, full.split(",")[0].strip(), re.sub(r"\s*\(.*?\)", "", full).strip()}:
                    if len(variant) >= 4:
                        names[variant.lower()] = code
    for alias, code in COUNTRY_ALIASES.items():
        names[alias] = code
    _country_names = sorted(
        ((n, c, n in CAPITAL_ONLY) for n, c in names.items()), key=lambda t: -len(t[0])
    )
    return _country_names


def extract_country(text: str, skip_spans: list[tuple[int, int]] | None = None) -> str | None:
    """ISO 3 code of the first country named (by name, or by an upper-case ISO 3 code)."""
    skip_spans = skip_spans or []
    low = text.lower()
    best: tuple[int, str] | None = None
    for name, code, capital_only in _load_countries():
        for m in re.finditer(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])", low):
            if capital_only and not text[m.start()].isupper():
                continue
            if any(s <= m.start() < e for s, e in skip_spans):
                continue
            if best is None or m.start() < best[0]:
                best = (m.start(), code)
            break
    for m in re.finditer(r"(?<![\w-])[A-Z]{3}(?![\w-])", text):
        code = m.group()
        if code in _iso3 and code not in ISO3_SKIP and not any(s <= m.start() < e for s, e in skip_spans):
            if best is None or m.start() < best[0]:
                best = (m.start(), code)
            break
    return best[1] if best else None


_YEAR_RE = re.compile(r"(?<![\d.-])((?:19|20)\d{2})(?![\d-])")
_GUIDELINE_AROUND = re.compile(r"(icmr|who|idsa|nice|esccmid|cdc|guideline|guidance|edition|version)\W*$")


def extract_year(text: str) -> int | None:
    """First four-digit year, ignoring a year that is part of a guideline's name (ICMR 2019)."""
    for m in _YEAR_RE.finditer(text):
        before = text[: m.start()].lower()
        after = text[m.end():].lower()
        if _GUIDELINE_AROUND.search(before) or re.match(r"\W*(?:(?:icmr|who|idsa|nice|esccmid|cdc)\W+)?(guideline|guidance|edition|version)", after):
            continue
        return int(m.group(1))
    return None


# --------------------------------------------------------------------------------------
# Infection site
# --------------------------------------------------------------------------------------

# Most specific first; the label is free text (the curated recommendations use free text too).
SITE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("CLABSI", re.compile(r"\bclabsi\b|central line", re.I)),
    ("bloodstream infection", re.compile(r"bloodstream|blood stream|bact(?:a)?emi|septic(?:a)?emi|\bbsi\b", re.I)),
    ("sepsis", re.compile(r"\bsepsis\b|\bseptic\b", re.I)),
    ("urinary tract infection", re.compile(r"\buti\b|\butis\b|urinary|cystitis|pyelonephritis", re.I)),
    ("pneumonia", re.compile(r"\bpneumonia\b|\bhap\b|\bvap\b", re.I)),
    ("skin and soft tissue infection", re.compile(r"skin and soft|soft[- ]tissue|\bssti\b|cellulitis|abscess", re.I)),
    ("intra-abdominal infection", re.compile(r"intra-?abdominal|\bciai\b|peritonitis", re.I)),
    ("osteomyelitis", re.compile(r"osteomyelitis|bone and joint", re.I)),
    ("meningitis", re.compile(r"meningitis", re.I)),
    ("endocarditis", re.compile(r"endocarditis", re.I)),
    ("wound infection", re.compile(r"wound", re.I)),
]


def extract_site(text: str) -> str | None:
    for label, pat in SITE_PATTERNS:
        if pat.search(text):
            return label
    return None


# --------------------------------------------------------------------------------------
# Entities
# --------------------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[-/][A-Za-z0-9]+)*")


def _overlaps(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    return any(start < e and s < end for s, e in spans)


def _retry_uppercase(text: str, linker: EntityLinker, spans: list[tuple[int, int]]) -> list[LinkedMention]:
    """D37: tokens of 3+ letters that matched nothing are tried upper-cased.

    Only an exact dictionary string counts (``mrsa`` -> ``MRSA``), so ordinary words never
    link; phenotype acronyms are also found by a case-insensitive lookup (``kpc-kp``).
    """
    phenos = {a.lower(): a for a in getattr(linker, "_phenotypes", {})}
    found: list[LinkedMention] = []
    for m in _TOKEN_RE.finditer(text):
        tok = m.group()
        if sum(c.isalpha() for c in tok) < 3 or tok.isupper() or _overlaps(m.start(), m.end(), spans):
            continue
        up = tok.upper()
        ent = linker.resolve(up, fuzzy=False)
        if ent is None and tok.lower() in phenos:
            ent = linker.resolve(phenos[tok.lower()], fuzzy=False)
        if ent is None:
            continue
        if ent.synonym.upper() != up and not ent.phenotype:
            continue
        found.append(
            LinkedMention(
                passage_id="", start=m.start(), end=m.end(), surface=tok,
                entity_type=ent.entity_type, entity_id=ent.entity_id, match_type="uppercase",
                score=ent.score * 0.9, canonical_name=ent.canonical_name, phenotype=ent.phenotype,
                pathogen_ids=list(ent.pathogen_ids), mechanism_ids=list(ent.mechanism_ids),
                class_family=ent.class_family,
            )
        )
    return found


def _add(lst: list[str], value: str) -> None:
    if value and value not in lst:
        lst.append(value)


def _fill_entities(pq: ParsedQuery, mentions: list[LinkedMention]) -> None:
    explicit_pathogens = [
        m.entity_id for m in mentions if m.entity_type == "Pathogen" and not m.phenotype
    ]
    for m in sorted(mentions, key=lambda x: x.start):
        if m.phenotype:
            pids = list(m.pathogen_ids) or [m.entity_id]
            if len(pids) > 1:  # CRE, ESBL-E: ambiguous, unless the question names a covered species
                named = [p for p in pids if p in explicit_pathogens]
                pids = named or pids
            for p in pids:
                _add(pq.pathogen_ids, p)
            for mech in m.mechanism_ids:
                _add(pq.mechanism_ids, mech)
            _add(pq.class_families, m.class_family)
            continue
        if m.entity_type == "Pathogen":
            _add(pq.pathogen_ids, m.entity_id)
        elif m.entity_type == "Mechanism":
            _add(pq.mechanism_ids, m.entity_id)
        elif m.entity_type == "Drug":
            _add(pq.drug_ids, m.entity_id)
        elif m.entity_type == "DrugClass":
            _add(pq.class_ids, m.entity_id)
        elif m.entity_type == "ClassFamily":
            _add(pq.class_families, m.entity_id)


# --------------------------------------------------------------------------------------
# Decline rules (D18). Checked before any intent rule; the first match wins.
# --------------------------------------------------------------------------------------

def _rx(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.I)


DOSING = _rx(
    r"\b(dos(?:e|es|ed|ing|age)|mcg|mg(?:/kg|/day|/dl)?|g/day|how much|loading dose|"
    r"duration|course (?:length|of therapy)|for how long|how long (?:should|do|does|to|is|will|must)|"
    r"how many (?:mg|grams?|tablets?|pills?|doses?|days?|weeks?)|every \d+ ?(?:h|hours?)|q\d+h|"
    r"how often (?:should|do i|to) (?:give|take|administer|dose))\b"
)
PATIENT = _rx(
    r"\b(?:my|this|our|his|her) (?:patient|mother|father|mom|dad|son|daughter|wife|husband|child|baby|"
    r"friend|grandmother|grandfather|brother|sister|infection|uti|wound|culture|test|report)\b"
    r"|\ba patient (?:with|who|has|is|presents|came)\b|\b\d+[- ]?(?:year|yr|y)[- ]?old\b"
    r"|\b(?:should|can|could|may|shall) i (?:give|prescribe|start|use|take|treat|switch|stop|try)\b"
    r"|\bwhat (?:should|do|can) i (?:give|prescribe|take|use|start)\b|\bi (?:have|got|am|was) (?:a |an )?"
    r"(?:uti|infection|fever|diagnosed|infected|prescribed)\b"
)
SPECIAL_GROUP = _rx(
    r"\b(?:pregnan\w*|breast-?feeding|lactating|neonat\w*|newborns?|infants?|child|children|"
    r"p(?:a)?ediatric\w*|kids?|toddlers?)\b"
)
# Pathogens outside the five-pathogen scope (D1). Checked only when no in-scope pathogen is found.
OUT_OF_SCOPE = _rx(
    r"\b(?:streptococc\w*|enterococc\w*|vre|salmonella\w*|shigella|neisseria|gonorrh\w*|chlamydia|"
    r"clostrid\w*|c\.? ?diff\w*|haemophilus|h\. ?influenzae|mycobacteri\w*|tuberculosis|tb|mdr-tb|"
    r"candida\w*|aspergill\w*|fung\w*|enterobacter|serratia|stenotrophomonas|proteus|listeria|"
    r"legionella|helicobacter|campylobacter|vibrio|cholera|bordetella|treponema|syphilis|"
    r"s\. ?pneumoniae|s\. ?pyogenes|e\. ?faecalis|e\. ?faecium|n\. ?gonorrhoeae|"
    r"hiv|covid\w*|influenza|malaria|virus\w*|viral)\b"
)
STRONG_SURVEILLANCE = _rx(
    r"\bhow (?:common|often|prevalent|frequent\w*)\b|\bprevalen\w*|\bproportion\b|\bpercent\w*|%|"
    r"\brates?\b|\bincidence\b|\btrends?\b|\bsurveillance\b|\bglass\b|\bshare of\b|\bfrequency\b|"
    r"\bhow many (?:isolates|cases|infections)\b"
)

DECLINE_MESSAGES = {
    "dosing": "Dosing, dose adjustment and treatment duration are outside what this educational tool "
              "provides (D18); consult a clinician or the current guideline.",
    "patient_specific": "Patient-specific treatment advice is not given; this tool explains guideline "
                        "reasoning in general terms only (D18).",
    "special_group": "Treatment for pregnancy, breastfeeding, neonates and children needs individual "
                     "clinical judgement and is not covered (D18).",
    "out_of_scope": "The question is about a pathogen outside the five covered (K. pneumoniae, E. coli, "
                    "A. baumannii, P. aeruginosa, S. aureus).",
}


def decline_rule(text: str, pq: ParsedQuery) -> str | None:
    """Return a decline reason, or None. Order: dosing, patient, special group, scope."""
    if DOSING.search(text):
        return DECLINE_MESSAGES["dosing"]
    if PATIENT.search(text):
        return DECLINE_MESSAGES["patient_specific"]
    if SPECIAL_GROUP.search(text) and not STRONG_SURVEILLANCE.search(text):
        return DECLINE_MESSAGES["special_group"]
    if not pq.pathogen_ids and OUT_OF_SCOPE.search(text):
        return DECLINE_MESSAGES["out_of_scope"]
    return None


# --------------------------------------------------------------------------------------
# Intent rules, in order. Each is (name, intent, predicate(features) -> bool).
# --------------------------------------------------------------------------------------

@dataclass
class Features:
    text: str  # lower-cased question
    pq: ParsedQuery
    has_phenotype: bool = False
    flags: dict[str, bool] = field(default_factory=dict)

    @property
    def has_drug(self) -> bool:
        return bool(self.pq.drug_ids)

    @property
    def has_class(self) -> bool:
        return bool(self.pq.class_ids or self.pq.class_families)

    @property
    def has_pathogen(self) -> bool:
        return bool(self.pq.pathogen_ids)

    @property
    def has_resistance_context(self) -> bool:
        return bool(
            self.has_phenotype or self.pq.mechanism_ids
            or re.search(r"resist|non-?susceptib|\bfail|producing|producer|carbapenemase|esbl", self.text)
        )

    def any_entity(self) -> bool:
        return self.has_drug or self.has_class or self.has_pathogen or bool(self.pq.mechanism_ids)


def _has(pattern: str) -> Callable[[Features], bool]:
    rx = re.compile(pattern)
    return lambda f: bool(rx.search(f.text))


ALT_STRONG = re.compile(
    r"alternativ|what else|which else|\bremain(?:s|ing)?\b|still (?:work|active|effective|useful|an option|"
    r"treat|options?)|left to treat|instead of|other than|apart from|besides|"
    r"(?:what|which) (?:antibiotics?|drugs?|agents?|options?|antimicrobials?) (?:still |can |could )?"
    r"(?:work|are active|are effective|remain|can be used|could be used|are left|to use|are available)|"
    r"what (?:works|still works)|substitut|fallback|back-?up (?:option|drug|antibiotic)"
)
ALT_WEAK = re.compile(
    r"\boptions?\b|\bactive (?:against|in|for)\b|\beffective (?:against|for|in)\b|"
    r"\bworks? (?:against|for|in)\b|\bcover(?:s|age)? (?:for|of)?\b|\buseful (?:against|for)\b|\bsuitable\b"
)
RESTRICT = re.compile(
    r"restrict|\breserv(?:e|ed)\b|last[- ]resort|last[- ]line|stewardship|kept (?:back|for)|"
    r"held back|protected|limit(?:ed)? use|why (?:is|are) .{0,40}\b(?:limited|avoided|watch)\b|"
    r"\bwatch (?:group|antibiotic)|\baware\b.*\bwhy\b|\bwhy\b.*\baware\b"
)
MECHANISM = re.compile(
    r"how (?:does|do|can|did|is) .{0,60}(?:resist|evade|become resistant|survive|defeat|overcome|"
    r"inactivate|break down|hydrolys|hydrolyz|degrade)|"
    r"mechanisms?|what makes|what causes|why (?:is|are|do|does) .{0,60}resistan|"
    r"\bconfer(?:s|red)?\b|inactivat|hydrolys|hydrolyz|\bresistance genes?\b|\benzymes?\b|"
    r"what (?:does|do) .{0,30}(?:resist|confer|inactivat|hydrolys)|resist\w* mechanism|"
    r"basis of resistance|how .{0,40} (?:resists?|resistance (?:arises|develops|works))|"
    r"\b(?:affect|defeat|destroy|neutrali[sz]e|undermine|impair)\w*"
)
RECOMMEND = re.compile(
    r"recommend|guideline|first[- ]line|second[- ]line|empiric|drug of choice|choice for|"
    r"treatment (?:of|for)|\btreat(?:s|ed|ing|ment)?\b|therapy|therapeutic|preferred|"
    r"what (?:is|are) (?:used|given)|\bicmr\b|\bidsa\b|\bnice\b|\bwho (?:guideline|recommend)|"
    r"best (?:antibiotic|drug|option|choice)|what to use|\bmanage(?:d|ment)?\b"
)
PROFILE = re.compile(
    r"\bwhat (?:class|group|type|category)\b|\bwhich (?:class|group|aware|category)\b|\baware\b|\batc\b|"
    r"belong|\bdrug class\b|\bclass of\b|tell me about|\bwhat is\b|\bwhat are\b|\bspectrum\b|"
    r"\bprofile\b|\bdescribe\b|\bexplain\b|\bis \S+ (?:an? )?(?:access|watch|reserve)\b|\bfamily\b"
)


def r_surveillance_strong(f: Features) -> bool:
    if not STRONG_SURVEILLANCE.search(f.text):
        return False
    # "alternatives remain" style questions also contain "rate"; the strong trigger needs an entity
    return f.any_entity() or f.pq.country is not None


def r_alternatives_strong(f: Features) -> bool:
    return bool(ALT_STRONG.search(f.text)) and f.any_entity()


def r_why_restricted(f: Features) -> bool:
    return bool(RESTRICT.search(f.text)) and (f.has_drug or f.has_class)


def r_mechanism(f: Features) -> bool:
    return bool(MECHANISM.search(f.text)) and (f.has_pathogen or f.pq.mechanism_ids or f.has_class or f.has_drug)


def r_alternatives_weak(f: Features) -> bool:
    return bool(ALT_WEAK.search(f.text)) and f.has_resistance_context and (f.has_pathogen or f.pq.mechanism_ids or f.has_class)


def r_recommendation(f: Features) -> bool:
    return bool(RECOMMEND.search(f.text)) and (f.has_pathogen or bool(f.pq.mechanism_ids))


def r_profile_trigger(f: Features) -> bool:
    return bool(PROFILE.search(f.text)) and (f.has_drug or bool(f.pq.class_ids)) and not f.has_pathogen \
        and f.pq.country is None


def r_surveillance_geo(f: Features) -> bool:
    return (f.pq.country is not None or f.pq.year is not None) and f.any_entity()


def r_profile_fallback(f: Features) -> bool:
    return f.has_drug and not f.has_pathogen and not f.pq.mechanism_ids


def r_mechanism_fallback(f: Features) -> bool:
    return bool(f.pq.mechanism_ids) and not f.has_phenotype and bool(re.search(r"resist", f.text))


# The order is the priority: the first rule that fires decides the intent.
INTENT_RULES: list[tuple[str, str, Callable[[Features], bool]]] = [
    ("S1 surveillance trigger (how common, %, rate, prevalence, trend) + an entity or country",
     "surveillance", r_surveillance_strong),
    ("A1 alternatives trigger (alternatives, what else, remain, still work, instead of) + an entity",
     "alternatives", r_alternatives_strong),
    ("W1 restriction trigger (restricted, reserve, last resort, stewardship) + a drug or class",
     "why_restricted", r_why_restricted),
    ("M1 mechanism trigger (how does X resist, mechanism, confers, inactivates, enzyme) + an entity",
     "mechanism_lookup", r_mechanism),
    ("A2 weak alternatives trigger (options, active against, effective against) + resistance context",
     "alternatives", r_alternatives_weak),
    ("R1 recommendation trigger (recommended, guideline, first-line, treatment of) + pathogen or mechanism",
     "recommendation_lookup", r_recommendation),
    ("D1 drug profile trigger (what class, AWaRe group, what is) + a drug or class, no pathogen",
     "drug_profile", r_profile_trigger),
    ("S2 country or year + an entity (no other trigger)", "surveillance", r_surveillance_geo),
    ("D2 a drug and nothing else", "drug_profile", r_profile_fallback),
    ("M2 a mechanism and the word resistance, no other trigger", "mechanism_lookup", r_mechanism_fallback),
]


# --------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------

def parse(question: str, linker: EntityLinker | None = None) -> ParsedQuery:
    """Parse one question. Never raises on odd input; an empty question is ``unknown``."""
    linker = linker or get_linker()
    text = (question or "").replace("’", "'").replace("–", "-").replace("‐", "-").strip()
    pq = ParsedQuery(question=question or "")
    if not text:
        return pq

    mentions = linker.link(text)
    spans = [(m.start, m.end) for m in mentions]
    mentions += _retry_uppercase(text, linker, spans)
    mentions.sort(key=lambda m: m.start)
    pq.mentions = mentions
    _fill_entities(pq, mentions)

    spans = [(m.start, m.end) for m in mentions]
    pq.country = extract_country(text, spans)
    pq.year = extract_year(text)
    pq.infection_site = extract_site(text)

    low = text.lower()
    reason = decline_rule(low, pq)
    if reason:
        pq.intent, pq.decline_reason = "decline", reason
        return pq

    feats = Features(low, pq, has_phenotype=any(m.phenotype for m in mentions))
    _, pq.intent = _decide(feats)
    return pq


def _decide(feats: Features) -> tuple[str, str]:
    """(rule name, intent) of the first intent rule that fires, else ("none", "unknown")."""
    for name, intent, rule in INTENT_RULES:
        if rule(feats):
            return name, intent
    return "none: fall back to text search", "unknown"


def explain(question: str) -> str:
    """Name the rule that decided the intent (for debugging and the handoff)."""
    pq = parse(question)
    if pq.intent == "decline":
        return f"decline: {pq.decline_reason}"
    feats = Features(pq.question.lower(), pq, has_phenotype=any(m.phenotype for m in pq.mentions))
    return _decide(feats)[0]

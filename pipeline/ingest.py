"""PDF ingestion and section-aware chunking (task T06).

Turns the three guideline PDFs in ``data/raw/guidelines/`` and the PubMed abstracts in
``data/raw/pubmed/abstracts.jsonl`` into passages of 150-250 words with stable IDs
``<source doc id>:<section slug>:<n>`` (docs/CONTRACTS.md section 2).

Steps: read ``schema/sections.yaml`` -> extract page text with pdfplumber (header and footer
cropped, two-column pages split) -> cut the line stream into sections -> repair the text
(``normalise_text``) -> pack into passages that never cross a section boundary.

Run: ``python -m pipeline.ingest`` (writes ``passages.jsonl``, ``nodes_Passage.csv`` and
``ingest_report.json`` into ``data/processed/``).
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

import yaml

from pipeline.config import DATA_PROCESSED, DATA_RAW, SCHEMA_DIR

SECTIONS_FILE = SCHEMA_DIR / "sections.yaml"
SYNONYMS_FILE = SCHEMA_DIR / "synonyms.csv"
PUBMED_FILE = DATA_RAW / "pubmed" / "abstracts.jsonl"
GUIDELINE_DIR = DATA_RAW / "guidelines"

MIN_WORDS = 150
MAX_WORDS = 250
OVERLAP_WORDS = 30
# A sentence longer than this is cut into slices. With pieces of at most MAX_WORDS - MIN_WORDS
# words, a chunk that overflows always holds more than MIN_WORDS words, so no chunk except the
# last one in a section (or one next to a table) is short.
MAX_PIECE_WORDS = MAX_WORDS - MIN_WORDS
SLUG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")

# ---------------------------------------------------------------------------
# Text normalisation
# ---------------------------------------------------------------------------

# Typographic ligature code points (what well-behaved PDFs emit).
LIGATURE_CHARS = {
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl",
    "ﬅ": "st", "ﬆ": "st",
}

# pdfplumber prints a glyph it cannot map as "(cid:N)". In the AWaRe book N=31 and N=157 are
# the "fi" ligature (checked on "De(cid:31)nition", "con(cid:157)rmed", "ce(cid:31)derocol").
# Every other N seen in the book (1, 5, 7, 8, 11-15, 23, 26-30, 127, 129, 141, 143) is also a
# "fi" or "fl" ligature, but which one depends on the font subset, so it becomes the marker
# below and the vocabulary decides ("In<marker>uenza" -> "Influenza" only if exactly one of
# fi/fl/ff/ffi/ffl gives a known word). A marker that cannot be resolved is dropped and counted.
CID_KNOWN = {31: "fi", 157: "fi"}
LIGATURE_MARKER = "�"
CID_RE = re.compile(r"\(cid:(\d+)\)")

# Explicit repairs, checked against the PDFs. Each is (pattern, replacement); word boundaries
# keep them from touching a longer word.
EXPLICIT_REPLACEMENTS: list[tuple[str, str]] = [
    (r"\bce derocol\b", "cefiderocol"),
    (r"\bCe derocol\b", "Cefiderocol"),
    (r"\bTr eatment\b", "Treatment"),
    (r"\bres istant\b", "resistant"),
    (r"\bInfe ctions\b", "Infections"),
    (r"\bcon rmed\b", "confirmed"),
    (r"\bsigni cant\b", "significant"),
    (r"\bbene t\b", "benefit"),
]

# Ligatures that a PDF font can swallow or replace by a stray symbol.
LIGATURE_CANDIDATES = ("fi", "fl", "ff", "ffi", "ffl")
# Symbols that stand in for a ligature inside a word in the AWaRe book: "In“uenza"
# (fl), "signi’cant" (fi), "signiŒcant" (fi), "In…uenza" (fl).
STRAY_LIGATURE_SYMBOLS = "“”‘’…Œœ‹›"
STRAY_IN_WORD_RE = re.compile(rf"([A-Za-z]+)([{STRAY_LIGATURE_SYMBOLS}�])([a-z]+)")
MARKER_AT_START_RE = re.compile(r"(?<![A-Za-z])()(�)([a-z]+)")
PRIVATE_USE_RE = re.compile("[-​‌‍⁠﻿­]")
BULLET_RE = re.compile(r"[•·●▪]")
TOKEN_SPLIT_RE = re.compile(r"^([^A-Za-z]*)([A-Za-z]+)([^A-Za-z]*)$")
WORD_RE = re.compile(r"[A-Za-z]+")


class Vocabulary:
    """Lower-case word counts from text known to be clean, plus protected domain names.

    Repairs that join or complete words are applied only when the result is a word in this
    vocabulary, which is what keeps normalisation from guessing.
    """

    def __init__(self, counts: Optional[Counter] = None, protected: Iterable[str] = (), min_count: int = 3):
        self.counts: Counter = Counter(counts or {})
        self.min_count = min_count
        for word in protected:
            for part in WORD_RE.findall(word):
                self.counts[part.lower()] += 10 * min_count

    def add_text(self, text: str) -> None:
        self.counts.update(w.lower() for w in WORD_RE.findall(text))

    def count(self, word: str) -> int:
        return self.counts.get(word.lower(), 0)

    def has(self, word: str) -> bool:
        return self.count(word) >= self.min_count

    def rare(self, word: str) -> bool:
        return self.count(word) < self.min_count


def fix_characters(text: str, stats: Optional[Counter] = None) -> str:
    """Character-level repairs that need no dictionary."""
    stats = stats if stats is not None else Counter()
    text = unicodedata.normalize("NFC", text)
    for char, replacement in LIGATURE_CHARS.items():
        if char in text:
            stats["ligature_chars"] += text.count(char)
            text = text.replace(char, replacement)

    def _cid(match: re.Match) -> str:
        number = int(match.group(1))
        if number in CID_KNOWN:
            stats["cid_known"] += 1
            return CID_KNOWN[number]
        stats["cid_unknown_marked"] += 1
        return LIGATURE_MARKER

    text = CID_RE.sub(_cid, text)
    text = PRIVATE_USE_RE.sub("", text)
    text = BULLET_RE.sub("•", text)
    text = re.sub(r"[     ]", " ", text)
    return text


def _repair_stray_symbols(text: str, vocab: Vocabulary, stats: Counter) -> str:
    """Replace a stray symbol inside a word by the one ligature that makes a known word."""

    def _fix(match: re.Match) -> str:
        left, _symbol, right = match.groups()
        hits = [lig for lig in LIGATURE_CANDIDATES if vocab.has(left + lig + right)]
        if len(hits) == 1:
            stats["stray_symbol_ligature"] += 1
            return left + hits[0] + right
        if len(hits) > 1:
            stats["stray_symbol_ambiguous"] += 1
        return match.group(0)

    previous = None
    while previous != text:
        previous = text
        text = STRAY_IN_WORD_RE.sub(_fix, text)
        text = MARKER_AT_START_RE.sub(_fix, text)
    return text


def _split_token(token: str) -> Optional[tuple[str, str, str]]:
    match = TOKEN_SPLIT_RE.match(token)
    return match.groups() if match else None


def _repair_spacing(text: str, vocab: Vocabulary, stats: Counter) -> str:
    """Repair words broken by a stray space or by a swallowed ligature, only when verified.

    * "Infe ctions": two fragments whose join is a known word (one fragment is rare).
    * "con rmed", "bene t": the join with a ligature between is a known word (unique choice).
    * "rst": a rare token that becomes a known word with "fi" or "fl" in front.
    """
    tokens = text.split(" ")
    out: list[str] = []
    i = 0
    while i < len(tokens):
        current = tokens[i]
        parts = _split_token(current)
        if parts and i + 1 < len(tokens):
            following = _split_token(tokens[i + 1])
            lead_a, core_a, trail_a = parts
            if following and not trail_a and not following[0] and following[1][0].islower():
                core_b, trail_b = following[1], following[2]
                joined = core_a + core_b
                one_rare = vocab.rare(core_a) or vocab.rare(core_b)
                if one_rare and len(joined) >= 5:
                    hits = [lig for lig in LIGATURE_CANDIDATES if vocab.has(core_a + lig + core_b)]
                    if vocab.has(joined) and not hits:
                        out.append(lead_a + joined + trail_b)
                        stats["space_join"] += 1
                        i += 2
                        continue
                    if len(hits) == 1 and not vocab.has(joined):
                        out.append(lead_a + core_a + hits[0] + core_b + trail_b)
                        stats["ligature_gap_join"] += 1
                        i += 2
                        continue
        if parts:
            lead, core, trail = parts
            if len(core) >= 2 and core.islower() and vocab.rare(core):
                hits = [lig for lig in ("fi", "fl") if vocab.has(lig + core)]
                if len(hits) == 1:
                    out.append(lead + hits[0] + core + trail)
                    stats["ligature_prefix"] += 1
                    i += 1
                    continue
        out.append(current)
        i += 1
    return " ".join(out)


def normalise_text(text: str, vocab: Optional[Vocabulary] = None, stats: Optional[Counter] = None) -> str:
    """Repair extraction damage in ``text``.

    Always: ligature code points, ``(cid:N)`` glyphs, private-use symbols, odd spaces, the
    explicit replacement list and spacing before punctuation. With a ``vocab``: stray ligature
    symbols and broken spaces, each only when the repaired word is in the vocabulary.
    Idempotent: ``normalise_text(normalise_text(x)) == normalise_text(x)``.
    """
    stats = stats if stats is not None else Counter()
    text = fix_characters(text, stats)
    text = re.sub(r"[ \t]+", " ", text)
    for pattern, replacement in EXPLICIT_REPLACEMENTS:
        text, n = re.subn(pattern, replacement, text)
        stats["explicit_replacement"] += n
    if vocab is not None:
        text = _repair_stray_symbols(text, vocab, stats)
        text = _repair_spacing(text, vocab, stats)
    if LIGATURE_MARKER in text:
        stats["ligature_marker_unresolved"] += text.count(LIGATURE_MARKER)
        text = text.replace(LIGATURE_MARKER, "")
    text = re.sub(r"\s+([,.;:)\]])", r"\1", text)
    text = re.sub(r"([(\[])\s+", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def join_lines(lines: list[str], vocab: Optional[Vocabulary] = None) -> str:
    """Join wrapped lines into one string, repairing end-of-line hyphenation.

    A hyphen at a line end is removed only when the word without it is in the vocabulary and
    more frequent than the hyphenated word ("infec-" + "tion"); otherwise the hyphen stays and
    no space is added ("ceftazidime-" + "avibactam" -> "ceftazidime-avibactam").
    """
    text = ""
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if not text:
            text = line
            continue
        if text.endswith("-") and len(text) > 1 and text[-2].isalpha() and line[0].isalpha() and line[0].islower():
            left = WORD_RE.findall(text[:-1])
            right = WORD_RE.findall(line)
            if vocab is not None and left and right:
                solid, hyphenated = left[-1] + right[0], f"{left[-1]}-{right[0]}"
                if vocab.has(solid) and vocab.count(solid) > vocab.count(hyphenated):
                    text = text[:-1] + line
                    continue
            text += line
        else:
            text += " " + line
    return text


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(•])")


@dataclass
class Piece:
    """The smallest thing the packer places: a sentence, a heading or a table row."""

    text: str
    kind: str = "text"  # text | heading | table_row
    page: int = 0
    heading: str = ""
    is_table: bool = False

    @property
    def words(self) -> int:
        return len(self.text.split())


@dataclass
class Chunk:
    text: str
    page: int
    heading: str
    is_table: bool
    n_words: int


def count_words(text: str) -> int:
    return len(text.split())


def _split_oversize(piece: Piece, limit: int) -> list[Piece]:
    """Split a piece longer than ``limit`` words into near-equal slices on word boundaries."""
    words = piece.text.split()
    if len(words) <= limit:
        return [piece]
    n_parts = -(-len(words) // limit)
    size = -(-len(words) // n_parts)
    return [
        Piece(" ".join(words[i : i + size]), piece.kind, piece.page, piece.heading, piece.is_table)
        for i in range(0, len(words), size)
    ]


def to_pieces(units: list[Piece]) -> list[Piece]:
    """Cut text units into sentences; headings and table rows stay whole."""
    pieces: list[Piece] = []
    for unit in units:
        if unit.kind in ("heading", "table_row"):
            pieces.extend(_split_oversize(unit, MAX_PIECE_WORDS if unit.kind == "heading" else MAX_WORDS))
            continue
        for sentence in SENTENCE_SPLIT_RE.split(unit.text):
            sentence = sentence.strip()
            if sentence:
                pieces.extend(
                    _split_oversize(Piece(sentence, "text", unit.page, unit.heading, unit.is_table), MAX_PIECE_WORDS)
                )
    return pieces


def _carry(chunk_pieces: list[Piece], limit: int = OVERLAP_WORDS + 5) -> list[Piece]:
    """Trailing sentences of a chunk (at most ``limit`` words) to repeat at the next chunk's start."""
    carried: list[Piece] = []
    total = 0
    for piece in reversed(chunk_pieces):
        if piece.kind != "text":
            break
        if total + piece.words > limit:
            if not carried:
                tail = piece.text.split()[-OVERLAP_WORDS:]
                carried.insert(0, Piece(" ".join(tail), "text", piece.page, piece.heading, piece.is_table))
            break
        carried.insert(0, piece)
        total += piece.words
    return carried


def _make_chunk(pieces: list[Piece]) -> Chunk:
    text = " ".join(p.text for p in pieces)
    return Chunk(
        text=text,
        page=pieces[0].page,
        heading=pieces[0].heading,
        is_table=any(p.is_table for p in pieces),
        n_words=count_words(text),
    )


def pack_pieces(
    pieces: list[Piece],
    min_words: int = MIN_WORDS,
    max_words: int = MAX_WORDS,
) -> list[Chunk]:
    """Pack pieces into chunks of ``min_words``..``max_words`` words with ~30 words of overlap.

    Rules: a chunk never exceeds ``max_words``; a table row is a chunk of its own (rows are
    one sentence each and are not merged or overlapped); a heading starts a new chunk once the
    current one has ``min_words``; only the last chunk of a section may be shorter than
    ``min_words`` (and a tail that fits is merged into the chunk before it).
    """
    chunks: list[list[Piece]] = []
    current: list[Piece] = []
    carry_len = 0
    words = 0

    def emit(overlap: bool) -> None:
        nonlocal current, words, carry_len
        if len(current) > carry_len:
            chunks.append(current)
        carry = _carry(current) if overlap else []
        current = list(carry)
        carry_len = len(carry)
        words = sum(p.words for p in current)

    def close_tail() -> None:
        """Finish the text before a table or at the end: merge a short tail into the chunk before it."""
        tail = current[carry_len:]
        tail_words = sum(p.words for p in tail)
        fits = bool(chunks) and chunks[-1][-1].kind != "table_row" and sum(p.words for p in chunks[-1]) + tail_words <= max_words
        if tail_words < min_words and fits:
            chunks[-1] = chunks[-1] + tail
        else:
            chunks.append(current)

    for piece in pieces:
        if piece.kind == "table_row":
            if len(current) > carry_len:
                close_tail()
            current, carry_len, words = [], 0, 0
            chunks.append([piece])
            continue
        if len(current) > carry_len:
            if piece.kind == "heading" and words >= min_words:
                emit(False)
            elif words + piece.words > max_words:
                emit(True)
                if words + piece.words > max_words:  # the overlap does not fit: drop it
                    current, carry_len, words = [], 0, 0
        current.append(piece)
        words += piece.words
    if len(current) > carry_len:
        close_tail()
    return [_make_chunk(c) for c in chunks]


# ---------------------------------------------------------------------------
# Section lines -> text units
# ---------------------------------------------------------------------------

HEADING_RE = re.compile(r"^(\d{1,2}(?:\.\d+){0,3}\.?)\s+([A-Z][^.]{2,100})$")
SUBHEADING_RE = re.compile(r"^\d{1,2}\.\d+(?:\.\d+)*\.?\s+[A-Z]")
BULLET_START_RE = re.compile(r"^(•|[-–]\s|\d{1,2}[.)]\s|[a-z][.)]\s)")
REFERENCES_RE = re.compile(r"^references?:?$", re.I)
TABLE_CAPTION_RE = re.compile(r"^Table\s+[\dA-Z][\d.]*\s*[:.–-]")


def strip_references(items: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Drop a "References" list: from the line "References" up to the next numbered heading."""
    kept: list[tuple[int, str]] = []
    skipping = False
    for page, line in items:
        stripped = line.strip()
        if REFERENCES_RE.match(stripped):
            skipping = True
            continue
        if skipping and (SUBHEADING_RE.match(stripped) or re.match(r"^(Table|Box|Figure|Fig)\b", stripped)):
            skipping = False
        if not skipping:
            kept.append((page, line))
    return kept


def _tabular(line: str) -> bool:
    tokens = line.split()
    return bool(tokens) and (len(tokens) <= 3 or (len(tokens) <= 8 and any(ch.isdigit() for ch in line)))


def build_units(
    items: list[tuple[int, str]], vocab: Optional[Vocabulary] = None, stats: Optional[Counter] = None
) -> list[Piece]:
    """Group ``(page, line)`` items into headings, bullets and paragraphs, then normalise each."""
    if not items:
        return []
    median = statistics.median(len(t) for _p, t in items) or 1
    groups: list[tuple[str, int, list[str]]] = []  # (kind, page, lines)
    for page, line in items:
        stripped = line.strip()
        if not stripped:
            continue
        last = groups[-1] if groups else None
        if HEADING_RE.match(stripped) and not (last and last[0] == "text" and last[2][-1].endswith("-")):
            groups.append(("heading", page, [stripped]))
        elif last and last[0] == "heading" and len(last[2]) == 1 and stripped[0].islower():
            last[2].append(stripped)
        elif BULLET_START_RE.match(stripped):
            groups.append(("text", page, [stripped]))
        elif last and last[0] == "text":
            previous = last[2][-1]
            if previous.endswith((".", ":")) and stripped[0].isupper() and len(previous) < 0.6 * median:
                groups.append(("text", page, [stripped]))
            else:
                last[2].append(stripped)
        else:
            groups.append(("text", page, [stripped]))

    units: list[Piece] = []
    current_heading = ""
    for kind, page, lines in groups:
        text = normalise_text(join_lines(lines, vocab), vocab, stats)
        if not text:
            continue
        if kind == "heading":
            current_heading = text
        # Tables whose structure cannot be recovered stay as text but are flagged: a run of short
        # numeric lines, or a unit that opens with a "Table 10.11:" caption.
        tabular_run = len(lines) >= 6 and all(_tabular(line) for line in lines)
        captioned = bool(TABLE_CAPTION_RE.match(lines[0]))
        units.append(Piece(text, kind, page, current_heading, is_table=tabular_run or captioned))
    return units


# ---------------------------------------------------------------------------
# PDF extraction
# ---------------------------------------------------------------------------

WHO_RUNNING_LINES = [
    re.compile(
        r"^[ ]*(PRIMARY HEALTH CARE|HOSPITAL FACILITY|RESERVE ANTIBIOTICS|DOSING GUIDANCE|REFERENCES|References)[ ]*$"
    ),
    re.compile(r"^\d+ The WHO AWaRe \(Access, Watch, Reserve\) antibiotic book$"),
    re.compile(r"^The WHO AWaRe \(Access, Watch, Reserve\) antibiotic book \d+$"),
    re.compile(r"^(seunitnoc|:dnegeL|aannttiibbiioottiicc bbooookk)$"),
]
PAGE_NUMBER_RE = re.compile(r"^(\d{1,3}|[ivxlc]{1,6})$", re.I)


def _text_kwargs(extract_cfg: dict) -> dict:
    if "x_tolerance_ratio" in extract_cfg:
        return {"x_tolerance_ratio": extract_cfg["x_tolerance_ratio"]}
    return {"x_tolerance": extract_cfg.get("x_tolerance", 3)}


def is_two_column(words: list[dict], page_width: float) -> bool:
    """True when enough words sit on both sides of the page middle and none crosses it."""
    if len(words) < 60:
        return False
    mid = page_width / 2
    crossing = sum(1 for w in words if w["x0"] < mid - 2 and w["x1"] > mid + 2)
    left = sum(1 for w in words if w["x1"] <= mid + 2)
    right = sum(1 for w in words if w["x0"] >= mid - 2)
    return crossing <= max(1, 0.005 * len(words)) and left >= 0.2 * len(words) and right >= 0.2 * len(words)


def extract_page_lines(page: Any, doc_id: str, extract_cfg: dict, meta: Counter) -> list[str]:
    """Text lines of one page in reading order, without running headers, footers or page numbers."""
    kwargs = _text_kwargs(extract_cfg)
    body = page
    crop = extract_cfg.get("crop")
    if crop:
        body = page.within_bbox((0, crop[0], page.width, page.height - crop[1]))
    text = None
    if extract_cfg.get("columns") == "auto":
        words = body.extract_words(**kwargs)
        if is_two_column(words, page.width):
            meta["two_column_pages"] += 1
            mid = page.width / 2
            top, bottom = body.bbox[1], body.bbox[3]
            left = body.within_bbox((0, top, mid, bottom)).extract_text(**kwargs) or ""
            right = body.within_bbox((mid, top, page.width, bottom)).extract_text(**kwargs) or ""
            text = left + "\n" + right
    if text is None:
        text = body.extract_text(**kwargs) or ""
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if doc_id == "who-aware-book-2022":
        lines = [ln for ln in lines if not any(p.match(ln.strip()) for p in WHO_RUNNING_LINES)]
    elif lines and PAGE_NUMBER_RE.match(lines[-1].strip()):
        lines = lines[:-1]  # printed page number
    return lines


def heading_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


@dataclass
class SectionSpec:
    slug: str
    title: str
    first_page: int
    last_page: int
    skip: bool = False
    reason: str = ""
    start_heading: str = ""


@dataclass
class DocSpec:
    doc_id: str
    file: str
    title: str
    page_offset: int
    extract: dict
    sections: list[SectionSpec]
    tables: list[dict] = field(default_factory=list)
    strip_references: bool = False


def load_sections(path: Path = SECTIONS_FILE) -> dict[str, DocSpec]:
    """Read and validate ``schema/sections.yaml``."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    docs: dict[str, DocSpec] = {}
    for doc_id, cfg in raw["documents"].items():
        sections = [
            SectionSpec(
                slug=s["slug"], title=s["title"], first_page=s["pages"][0], last_page=s["pages"][1],
                skip=bool(s.get("skip")), reason=s.get("reason", ""), start_heading=s.get("start_heading", ""),
            )
            for s in cfg["sections"]
        ]
        slugs = [s.slug for s in sections]
        if len(set(slugs)) != len(slugs):
            raise ValueError(f"{doc_id}: duplicate section slug")
        for s in sections:
            if not SLUG_RE.fullmatch(s.slug) or s.first_page > s.last_page:
                raise ValueError(f"{doc_id}: bad section {s.slug!r}")
        starts = [s.first_page for s in sections]
        if starts != sorted(starts):
            raise ValueError(f"{doc_id}: sections are not in page order")
        docs[doc_id] = DocSpec(
            doc_id=doc_id, file=cfg["file"], title=cfg["title"], page_offset=cfg["page_offset"],
            extract=cfg.get("extract", {}), sections=sections, tables=cfg.get("tables", []),
            strip_references=bool(cfg.get("strip_references")),
        )
    return docs


def _cell_lines(text: Optional[str]) -> list[str]:
    return [ln.strip() for ln in (text or "").split("\n") if ln.strip()]


def table_to_sentences(
    rows: list[list[Optional[str]]], caption: str, label_header: str, vocab: Optional[Vocabulary] = None
) -> list[str]:
    """One sentence per table row. Rows with an empty first cell continue the row above.

    A row whose second cell reads "1st Choice: ... Other options: a. ... b. ..." (ICMR 2022
    Table 4) becomes "<caption>. <header> <label>: 1st choice: ...; other options: a. ...".
    Any other two-column row becomes "<caption>. <header> <label>: <cell>.". A row with an
    empty second cell is a header and produces nothing.
    """
    merged: list[list[str]] = []
    for row in rows:
        label = join_lines(_cell_lines(row[0] if row else ""), vocab)
        cell = join_lines(_cell_lines(row[1] if len(row) > 1 else ""), vocab)
        if label and cell:
            merged.append([label, cell])
        elif not label and cell and merged:
            merged[-1][1] = join_lines([merged[-1][1], cell], vocab)
    sentences = []
    for label, cell in merged:
        match = re.match(r"^1st Choice:\s*(.*?)\s*Other options:\s*(.*)$", cell, re.S | re.I)
        if match:
            first, others = match.groups()
            sentences.append(
                f"{caption}. {label_header} {label}: 1st choice: {first.rstrip('.')}; other options: {others.rstrip('.')}."
            )
        else:
            sentences.append(f"{caption}. {label_header} {label}: {cell.rstrip('.')}.")
    return sentences


def _region_lines(region: Any, spec: DocSpec) -> list[str]:
    text = region.extract_text(**_text_kwargs(spec.extract)) or ""
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if lines and PAGE_NUMBER_RE.match(lines[-1].strip()):
        lines = lines[:-1]
    return lines


def _drop_caption(lines: list[str], caption: str) -> list[str]:
    """Remove the table caption (which wraps onto a second line) from the text above a table."""
    target = heading_key(caption)
    stem = heading_key(caption.split(":")[0])
    for i, line in enumerate(lines):
        if heading_key(line).startswith(stem):
            acc = ""
            for j in range(i, len(lines)):
                acc += heading_key(lines[j])
                if not target.startswith(acc):
                    return lines
                if acc == target:
                    return lines[:i] + lines[j + 1 :]
            return lines
    return lines


def extract_document(spec: DocSpec, pdf_path: Path, meta: dict) -> list[dict]:
    """Read the needed pages of one PDF. Returns stream items in reading order.

    An item is ``{"page", "kind": "line", "text"}`` for a text line, or
    ``{"page", "kind": "table", "rows", "table"}`` for a table to be turned into sentences.
    """
    import pdfplumber  # imported here so the normalisation tests need no PDF library

    wanted: set[int] = set()
    for s in spec.sections:
        if not s.skip:
            wanted.update(range(s.first_page, s.last_page + 1))
    table_cfgs = {p: t for t in spec.tables for p in t["pages"]}
    items: list[dict] = []
    counters: Counter = Counter()
    no_text: list[int] = []
    table_pages: list[int] = []
    pending_rows: list[list[Optional[str]]] = []
    with pdfplumber.open(pdf_path) as pdf:
        meta["pdf_pages"] = len(pdf.pages)
        for page_no in sorted(wanted):
            if page_no > len(pdf.pages):
                continue
            page = pdf.pages[page_no - 1]
            cfg = table_cfgs.get(page_no)
            tables = page.find_tables() if cfg else []
            if tables:
                table = tables[0]
                top, bottom = table.bbox[1], table.bbox[3]
                pre = _region_lines(page.within_bbox((0, 0, page.width, top)), spec) if top > 1 else []
                post = _region_lines(page.within_bbox((0, bottom, page.width, page.height)), spec) if bottom < page.height - 1 else []
                items.extend({"page": page_no, "kind": "line", "text": ln} for ln in _drop_caption(pre, cfg["caption"]))
                pending_rows.extend(table.extract())
                table_pages.append(page_no)
                if page_no == max(cfg["pages"]):
                    items.append({"page": cfg["pages"][0], "kind": "table", "rows": pending_rows, "table": cfg})
                    pending_rows = []
                items.extend({"page": page_no, "kind": "line", "text": ln} for ln in post)
                continue
            lines = extract_page_lines(page, spec.doc_id, spec.extract, counters)
            if not lines:
                no_text.append(page_no)
            items.extend({"page": page_no, "kind": "line", "text": ln} for ln in lines)
    meta["pages_extracted"] = len(wanted)
    meta["pages_no_text"] = no_text
    meta["two_column_pages"] = counters.get("two_column_pages", 0)
    meta["table_pages"] = table_pages
    return items


def split_into_sections(spec: DocSpec, items: list[dict]) -> dict[str, list[dict]]:
    """Assign stream items to sections: a section runs from its start to the next section's start."""
    starts: list[int] = []
    cursor = 0
    for s in spec.sections:
        idx = None
        for k in range(cursor, len(items)):
            item = items[k]
            if item["page"] < s.first_page:
                continue
            if s.start_heading:
                if item["kind"] == "line" and heading_key(item["text"]).startswith(heading_key(s.start_heading)):
                    idx = k
                    break
                if item["page"] > s.last_page:
                    break
            else:
                idx = k
                break
        if idx is None:
            if s.start_heading:
                raise ValueError(f"{spec.doc_id}: heading {s.start_heading!r} for section {s.slug} not found")
            idx = len(items)
        starts.append(max(idx, cursor))
        cursor = starts[-1]
    result: dict[str, list[dict]] = {}
    for n, s in enumerate(spec.sections):
        end = starts[n + 1] if n + 1 < len(starts) else len(items)
        if not s.skip:
            result[s.slug] = items[starts[n] : end]
    return result


# ---------------------------------------------------------------------------
# Vocabulary and quality measure
# ---------------------------------------------------------------------------

def load_domain_names() -> list[str]:
    """Drug, class, pathogen and mechanism names and synonyms from schema/synonyms.csv."""
    names: list[str] = []
    if SYNONYMS_FILE.exists():
        with SYNONYMS_FILE.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                names.append(row.get("synonym", ""))
                names.append(row.get("canonical_name", ""))
    return [n for n in names if n]


def load_abstracts(path: Path = PUBMED_FILE) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


STRAY_RE = re.compile(rf"[A-Za-z][{STRAY_LIGATURE_SYMBOLS}][a-z]")


def page_is_clean(texts: list[str]) -> bool:
    joined = "\n".join(texts)
    return "(cid:" not in joined and not STRAY_RE.search(joined)


def build_vocabulary(abstracts: list[dict], clean_texts: list[str], domain_names: list[str]) -> Vocabulary:
    vocab = Vocabulary(protected=domain_names)
    for a in abstracts:
        vocab.add_text(f"{a.get('title', '')} {a.get('abstract', '')}")
    for text in clean_texts:
        vocab.add_text(text)
    return vocab


def unknown_token_rate(texts: list[str], vocab: Vocabulary) -> tuple[int, int]:
    """(tokens not in the vocabulary, tokens) over alphabetic tokens of 3+ letters."""
    unknown = total = 0
    for text in texts:
        for word in WORD_RE.findall(text):
            if len(word) >= 3:
                total += 1
                if not vocab.has(word):
                    unknown += 1
    return unknown, total


def domain_mentions(texts: list[str], names: list[str]) -> int:
    """Occurrences of single-word drug/pathogen names (5+ letters, so abbreviations are not counted)."""
    singles = {n.lower() for n in names if n.isalpha() and len(n) >= 5}
    return sum(1 for text in texts for word in WORD_RE.findall(text) if word.lower() in singles)


# ---------------------------------------------------------------------------
# Main run
# ---------------------------------------------------------------------------

RESERVE_SECTIONS = (
    "reserve-overview", "cefiderocol", "ceftazidime-avibactam", "fosfomycin-iv", "linezolid",
    "meropenem-vaborbactam", "plazomicin", "polymyxin-colistin",
)


def naive_reserve_texts(spec: DocSpec, pdf_path: Path) -> list[str]:
    """Plain ``extract_text()`` of the Reserve chapter pages: the baseline the repairs are measured against."""
    import pdfplumber

    pages = sorted({p for s in spec.sections if s.slug in RESERVE_SECTIONS for p in range(s.first_page, s.last_page + 1)})
    with pdfplumber.open(pdf_path) as pdf:
        return [pdf.pages[p - 1].extract_text() or "" for p in pages if p <= len(pdf.pages)]


def printed_page(page: int, offset: int) -> Optional[int]:
    value = page - offset
    return value if value >= 1 else None


def chunk_section(
    section_items: list[dict], spec: DocSpec, vocab: Vocabulary, stats: Counter
) -> tuple[list[dict], list[str]]:
    """Chunk one section. Returns (passage rows without id, raw paragraph texts for the quality measure)."""
    units: list[Piece] = []
    raw_texts: list[str] = []
    buffer: list[tuple[int, str]] = []

    def flush() -> None:
        nonlocal buffer
        if spec.strip_references:
            buffer = strip_references(buffer)
        if buffer:
            raw_texts.append(join_lines([t for _p, t in buffer]))
            units.extend(build_units(buffer, vocab, stats))
        buffer = []

    first_line = next((i for i in section_items if i["kind"] == "line"), None)
    running_title = ""
    if first_line and HEADING_RE.match(first_line["text"].strip()):
        running_title = first_line["text"].strip()  # AWaRe repeats the chapter title on every page
    for item in section_items:
        if running_title and item["kind"] == "line" and item["page"] != first_line["page"] and item["text"].strip() == running_title:
            continue
        if item["kind"] == "table":
            flush()
            cfg = item["table"]
            for sentence in table_to_sentences(item["rows"], cfg["caption"], cfg.get("label_header", ""), vocab):
                units.append(Piece(normalise_text(sentence, vocab, stats), "table_row", item["page"], cfg["caption"], True))
        else:
            buffer.append((item["page"], item["text"]))
    flush()

    rows = [
        {"text": c.text, "page": c.page, "n_words": c.n_words, "is_table": c.is_table, "heading": c.heading}
        for c in pack_pieces(to_pieces(units))
    ]
    return rows, raw_texts


def run(
    out_dir: Path = DATA_PROCESSED,
    only: Optional[list[str]] = None,
    guideline_dir: Path = GUIDELINE_DIR,
    sections_file: Path = SECTIONS_FILE,
    include_pubmed: bool = True,
) -> dict:
    """Produce passages.jsonl, nodes_Passage.csv and ingest_report.json. Returns the report."""
    specs = load_sections(sections_file)
    selected = {d: s for d, s in specs.items() if not only or d in only}
    abstracts = load_abstracts()
    domain_names = load_domain_names()

    extracted: dict[str, tuple[dict[str, list[dict]], dict]] = {}
    clean_texts: list[str] = []
    for doc_id, spec in selected.items():
        meta: dict = {}
        items = extract_document(spec, guideline_dir / spec.file, meta)
        extracted[doc_id] = (split_into_sections(spec, items), meta)
        pages: dict[int, list[str]] = {}
        for it in items:
            if it["kind"] == "line":
                pages.setdefault(it["page"], []).append(it["text"])
        for page_lines in pages.values():
            # clean-vocabulary sources: every ICMR page, and the AWaRe pages without damage
            if doc_id != "who-aware-book-2022" or page_is_clean(page_lines):
                clean_texts.append(" ".join(page_lines))
    vocab = build_vocabulary(abstracts, clean_texts, domain_names)

    report: dict = {
        "documents": {},
        "settings": {"min_words": MIN_WORDS, "max_words": MAX_WORDS, "overlap_words": OVERLAP_WORDS},
    }
    all_rows: list[dict] = []
    reserve_raw: list[str] = []
    reserve_fixed: list[str] = []
    norm_stats: Counter = Counter()

    for doc_id, spec in selected.items():
        by_section, meta = extracted[doc_id]
        doc_report: dict = {
            "title": spec.title, "pdf_pages": meta.get("pdf_pages"), "pages_extracted": meta.get("pages_extracted"),
            "pages_with_no_text": meta.get("pages_no_text", []), "two_column_pages": meta.get("two_column_pages", 0),
            "table_pages_parsed": meta.get("table_pages", []), "sections": {},
            "sections_skipped": {
                s.slug: {"pages": [s.first_page, s.last_page], "reason": s.reason} for s in spec.sections if s.skip
            },
        }
        for s in spec.sections:
            if s.skip:
                continue
            stats: Counter = Counter()
            rows, raw_texts = chunk_section(by_section.get(s.slug, []), spec, vocab, stats)
            norm_stats.update(stats)
            for n, row in enumerate(rows, start=1):
                row.update(
                    {
                        "id": f"{doc_id}:{s.slug}:{n}", "source_doc": doc_id, "section": s.slug,
                        "printed_page": printed_page(row["page"], spec.page_offset),
                    }
                )
                all_rows.append(row)
            doc_report["sections"][s.slug] = {
                "title": s.title, "pages": [s.first_page, s.last_page], "passages": len(rows),
                "words": sum(r["n_words"] for r in rows), "table_passages": sum(1 for r in rows if r["is_table"]),
            }
            if doc_id == "who-aware-book-2022" and s.slug in RESERVE_SECTIONS:
                reserve_fixed.extend(r["text"] for r in rows)
        if doc_id == "who-aware-book-2022":
            reserve_raw = naive_reserve_texts(spec, guideline_dir / spec.file)
        doc_report["passages"] = sum(v["passages"] for v in doc_report["sections"].values())
        doc_report["words"] = sum(v["words"] for v in doc_report["sections"].values())
        report["documents"][doc_id] = doc_report

    if include_pubmed and not only:
        n_rows = words = empty = 0
        for a in abstracts:
            body = " ".join(str(a.get("abstract", "")).split())
            if not body:
                empty += 1
                continue
            text = " ".join(f"{a.get('title', '')} {body}".split())
            doc_id = f"pubmed-{a['pmid']}"
            all_rows.append(
                {
                    "id": f"{doc_id}:abstract:1", "text": text, "source_doc": doc_id, "section": "abstract",
                    "page": None, "printed_page": None, "n_words": count_words(text), "is_table": False, "heading": "",
                }
            )
            n_rows += 1
            words += count_words(text)
        report["documents"]["pubmed"] = {
            "abstracts_read": len(abstracts), "passages": n_rows, "words": words, "abstracts_without_text": empty,
            "note": "one passage per abstract (title + abstract), exempt from the 150-250 word range",
        }

    if reserve_raw:
        u_raw, t_raw = unknown_token_rate(reserve_raw, vocab)
        u_fix, t_fix = unknown_token_rate(reserve_fixed, vocab)
        report["text_quality_reserve_chapters"] = {
            "definition": (
                "share of alphabetic tokens (3+ letters) in AWaRe chapters 41-48 that are not in the clean "
                "vocabulary (PubMed abstracts, ICMR text, undamaged AWaRe pages, names from schema/synonyms.csv). "
                "Before = plain pdfplumber extract_text() of those pages; after = the passages"
            ),
            "tokens_before_repair": t_raw, "unknown_before_repair": u_raw,
            "unknown_share_before": round(u_raw / t_raw, 4) if t_raw else None,
            "tokens_after_repair": t_fix, "unknown_after_repair": u_fix,
            "unknown_share_after": round(u_fix / t_fix, 4) if t_fix else None,
            "scope_name_mentions_before": domain_mentions(reserve_raw, domain_names),
            "scope_name_mentions_after": domain_mentions(reserve_fixed, domain_names),
            "most_common_unknown_tokens_after": Counter(
                w.lower() for t in reserve_fixed for w in WORD_RE.findall(t) if len(w) >= 3 and not vocab.has(w)
            ).most_common(30),
        }
    report["normalisation_repairs"] = dict(norm_stats)
    report["totals"] = {
        "passages": len(all_rows), "words": sum(r["n_words"] for r in all_rows),
        "ids_unique": len({r["id"] for r in all_rows}) == len(all_rows),
    }
    write_outputs(out_dir, all_rows, report)
    return report


def write_outputs(out_dir: Path, rows: list[dict], report: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    fields = ["id", "text", "source_doc", "section", "page", "n_words", "printed_page", "is_table", "heading"]
    with (out_dir / "passages.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps({k: row.get(k) for k in fields}, ensure_ascii=False) + "\n")
    with (out_dir / "nodes_Passage.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["id", "text", "source_doc", "section"], lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row[k] for k in writer.fieldnames})
    (out_dir / "ingest_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Chunk the guideline PDFs and PubMed abstracts into passages.")
    parser.add_argument("--only", nargs="*", help="document ids to process (skips PubMed; for quick checks)")
    parser.add_argument("--out-dir", type=Path, default=DATA_PROCESSED)
    args = parser.parse_args(argv)
    report = run(out_dir=args.out_dir, only=args.only)
    for doc_id, doc in report["documents"].items():
        print(f"{doc_id}: {doc.get('passages')} passages, {doc.get('words')} words")
    print(f"total: {report['totals']['passages']} passages -> {args.out_dir}")


if __name__ == "__main__":
    main()

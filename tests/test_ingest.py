"""Tests for pipeline/ingest.py (task T06): normalisation, chunk sizes, section boundaries, ID stability.

Most tests use small synthetic input. Two tests read the real ICMR 2022 PDF (24 pages, about
3 seconds each); the output-file tests read data/processed/ and are skipped when ingest has
not run.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from collections import Counter, defaultdict

import pytest

from pipeline import ingest
from pipeline.config import DATA_PROCESSED, ROOT
from pipeline.ingest import (
    MAX_WORDS,
    MIN_WORDS,
    Piece,
    Vocabulary,
    join_lines,
    normalise_text,
    pack_pieces,
    split_into_sections,
    strip_references,
    table_to_sentences,
    to_pieces,
)
from pipeline.models import check_id

ICMR_2022 = "icmr-cr-gram-negative-2022"
ICMR_2022_PDF = ingest.GUIDELINE_DIR / "icmr-carbapenem-resistant-gram-negative-2022.pdf"


def vocab_from(text: str) -> Vocabulary:
    vocab = Vocabulary()
    vocab.add_text(text)
    return vocab


# --- normalisation -----------------------------------------------------------------------------


def test_ligature_code_points_are_expanded():
    assert normalise_text("eﬀective ﬁrst ﬂow oﬃce") == "effective first flow office"


def test_known_cid_glyphs_become_fi():
    stats: Counter = Counter()
    assert normalise_text("ce(cid:31)derocol De(cid:31)nition con(cid:157)rmed", stats=stats) == (
        "cefiderocol Definition confirmed"
    )
    assert stats["cid_known"] == 3


def test_explicit_replacements_need_no_vocabulary():
    assert normalise_text("Tr eatment of res istant Infe ctions with ce derocol") == (
        "Treatment of resistant Infections with cefiderocol"
    )


def test_explicit_replacements_do_not_touch_longer_words():
    assert normalise_text("the ce derocolx") == "the ce derocolx"


def test_private_use_glyphs_and_odd_spaces_are_removed():
    assert normalise_text("RESERVE ANTIBIOTICS book​") == "RESERVE ANTIBIOTICS book"


def test_space_before_punctuation_is_closed():
    assert normalise_text("infection , and ( note ) .") == "infection, and (note)."


def test_stray_symbol_in_word_is_repaired_only_with_a_known_word():
    vocab = vocab_from("influenza " * 5)
    assert normalise_text("In“uenza", vocab=vocab) == "Influenza"
    # no vocabulary, or no matching word: left alone rather than guessed
    assert normalise_text("In“uenza") == "In“uenza"
    assert normalise_text("Qx“uy", vocab=vocab) == "Qx“uy"


def test_real_quotation_marks_survive():
    vocab = vocab_from("antibiotic " * 5)
    assert normalise_text("a “no antibiotic” approach", vocab=vocab) == "a “no antibiotic” approach"


def test_unknown_cid_marker_is_resolved_by_vocabulary_or_dropped():
    vocab = vocab_from("inflammation " * 5 + "fluoride " * 5)
    stats: Counter = Counter()
    assert normalise_text("In(cid:29)ammation", vocab=vocab, stats=stats) == "Inflammation"
    assert normalise_text("(cid:30)uoride", vocab=vocab) == "fluoride"
    assert normalise_text("zz(cid:12)zz", vocab=vocab, stats=stats) == "zzzz"
    assert stats["ligature_marker_unresolved"] == 1


def test_broken_space_and_swallowed_ligature_are_repaired_when_verified():
    vocab = vocab_from("infections confirmed benefit first significant " * 4)
    assert normalise_text("Infe ctions", vocab=vocab) == "Infections"
    assert normalise_text("con rmed", vocab=vocab) == "confirmed"
    assert normalise_text("bene t", vocab=vocab) == "benefit"
    assert normalise_text("excluded rst", vocab=vocab) == "excluded first"


def test_two_real_words_are_not_joined():
    vocab = vocab_from("in to into patient patients " * 6)
    assert normalise_text("in to the patients", vocab=vocab) == "in to the patients"


def test_normalisation_is_idempotent():
    vocab = vocab_from("influenza confirmed infections " * 5)
    raw = "In“uenza con rmed Infe ctions ce(cid:31)derocol , ok"
    once = normalise_text(raw, vocab=vocab)
    assert normalise_text(once, vocab=vocab) == once


def test_hyphenation_at_line_end():
    vocab = vocab_from("infection " * 5 + "ceftazidime-avibactam " * 5)
    assert join_lines(["an infec-", "tion of the lung"], vocab) == "an infection of the lung"
    assert join_lines(["ceftazidime-", "avibactam is used"], vocab) == "ceftazidime-avibactam is used"
    assert join_lines(["high-", "dose therapy"]) == "high-dose therapy"  # no vocabulary: keep the hyphen


# --- chunk sizes ---------------------------------------------------------------------------------


def sentences(n: int, words: int = 18, start: int = 0) -> list[Piece]:
    return [Piece(" ".join(f"w{start + i}x{j}" for j in range(words)) + ".", "text", 1, "") for i in range(n)]


def test_chunks_stay_within_150_to_250_words_except_the_last():
    chunks = pack_pieces(sentences(60))
    assert len(chunks) > 3
    assert all(c.n_words <= MAX_WORDS for c in chunks)
    assert all(c.n_words >= MIN_WORDS for c in chunks[:-1])


def test_long_sentence_does_not_leave_a_short_chunk():
    long_sentence = Piece(" ".join(f"long{i}" for i in range(400)) + ".", "text", 1, "")
    chunks = pack_pieces(to_pieces(sentences(3) + [long_sentence] + sentences(3, start=99)))
    assert all(c.n_words <= MAX_WORDS for c in chunks)
    assert all(c.n_words >= MIN_WORDS for c in chunks[:-1])


def test_consecutive_chunks_overlap_by_about_30_words():
    chunks = pack_pieces(sentences(40))
    assert len(chunks) > 2
    for first, second in zip(chunks, chunks[1:]):
        tail = set(first.text.split()[-40:])
        shared = [w for w in second.text.split()[:40] if w in tail]
        assert 15 <= len(shared) <= 40


def test_short_section_gives_one_short_chunk():
    chunks = pack_pieces(sentences(3))
    assert len(chunks) == 1 and chunks[0].n_words < MIN_WORDS


def test_a_tail_that_fits_is_merged_into_the_previous_chunk():
    assert len(pack_pieces(sentences(13))) == 1  # 234 words


def test_heading_starts_a_new_chunk_once_the_chunk_is_big_enough():
    pieces = sentences(10) + [Piece("2.1 Next topic", "heading", 1, "2.1 Next topic")] + sentences(10, start=50)
    chunks = pack_pieces(pieces)
    assert len(chunks) == 2
    assert chunks[1].text.startswith("2.1 Next topic")


def test_table_rows_are_chunks_of_their_own():
    def row(i: int) -> Piece:
        return Piece(f"Table 4: row {i} " + "word " * 40, "table_row", 16, "Table 4", True)

    chunks = pack_pieces(sentences(12) + [row(1), row(2)] + sentences(12, start=40))
    table_chunks = [c for c in chunks if c.is_table]
    assert len(table_chunks) == 2
    assert all(c.text.startswith("Table 4: row") for c in table_chunks)


# --- section boundaries --------------------------------------------------------------------------


def make_spec(sections: list[dict], **kw) -> ingest.DocSpec:
    return ingest.DocSpec(
        doc_id="doc", file="x.pdf", title="t", page_offset=0, extract={},
        sections=[ingest.SectionSpec(**s) for s in sections], **kw,
    )


def lines(page: int, *texts: str) -> list[dict]:
    return [{"page": page, "kind": "line", "text": t} for t in texts]


def test_sections_split_on_page_boundaries_and_skip_sections_are_dropped():
    spec = make_spec(
        [
            dict(slug="front", title="f", first_page=1, last_page=1, skip=True),
            dict(slug="one", title="1", first_page=2, last_page=3),
            dict(slug="two", title="2", first_page=4, last_page=4),
        ]
    )
    result = split_into_sections(spec, lines(2, "a") + lines(3, "b") + lines(4, "c"))
    assert set(result) == {"one", "two"}
    assert [i["text"] for i in result["one"]] == ["a", "b"]
    assert [i["text"] for i in result["two"]] == ["c"]


def test_section_can_start_mid_page_at_its_heading():
    spec = make_spec(
        [
            dict(slug="a", title="a", first_page=1, last_page=2),
            dict(slug="b", title="b", first_page=2, last_page=2, start_heading="2. Diagnosis of  carbapenem"),
        ]
    )
    items = lines(1, "x") + lines(2, "tail of a", "2. Diagnosis of carbapenem resistance", "body of b")
    result = split_into_sections(spec, items)
    assert [i["text"] for i in result["a"]] == ["x", "tail of a"]
    assert [i["text"] for i in result["b"]] == ["2. Diagnosis of carbapenem resistance", "body of b"]


def test_missing_start_heading_is_an_error():
    spec = make_spec([dict(slug="a", title="a", first_page=1, last_page=1, start_heading="Nope")])
    with pytest.raises(ValueError):
        split_into_sections(spec, lines(1, "something else"))


def test_passages_never_cross_a_section_boundary():
    spec = make_spec(
        [dict(slug="a", title="a", first_page=1, last_page=1), dict(slug="b", title="b", first_page=2, last_page=2)]
    )
    items = lines(1, *[f"Alpha sentence number {i} has some words in it to count." for i in range(40)])
    items += lines(2, *[f"Beta sentence number {i} has some words in it to count." for i in range(40)])
    by_section = split_into_sections(spec, items)
    for slug, marker, other in (("a", "Alpha", "Beta"), ("b", "Beta", "Alpha")):
        rows, _ = ingest.chunk_section(by_section[slug], spec, Vocabulary(), Counter())
        assert rows and all(marker in r["text"] and other not in r["text"] for r in rows)


def test_section_map_is_valid():
    specs = ingest.load_sections()
    assert set(specs) == {"who-aware-book-2022", "icmr-treatment-guidelines-2019", ICMR_2022}
    for doc_id, spec in specs.items():
        slugs = [s.slug for s in spec.sections]
        assert len(slugs) == len(set(slugs))
        for s in spec.sections:
            assert ingest.SLUG_RE.fullmatch(s.slug)
            check_id("Passage", f"{doc_id}:{s.slug}:1")
        pages = [s.first_page for s in spec.sections]
        assert pages == sorted(pages)
    icmr_2019 = {s.slug for s in specs["icmr-treatment-guidelines-2019"].sections if s.skip}
    assert {"front-matter", "appendix-i", "tables-duration-dosage"} <= icmr_2019
    who = {s.slug for s in specs["who-aware-book-2022"].sections if s.skip}
    assert {"front-matter", "dosing-adults", "dosing-children", "references"} <= who


def test_references_list_is_dropped_until_the_next_numbered_heading():
    texts = ["text", "References", "1. World Health Organization. Report. 2011", "2. Hughes J. Study",
             "10.3 Surgical Site Infections", "more text"]
    kept = [t for _p, t in strip_references([(1, t) for t in texts])]
    assert kept == ["text", "10.3 Surgical Site Infections", "more text"]


def test_running_chapter_title_is_removed_from_later_pages():
    spec = make_spec([dict(slug="a", title="a", first_page=1, last_page=2)])
    items = lines(1, "42. Cefiderocol", "First page text.") + lines(2, "42. Cefiderocol", "Second page text.")
    rows, _ = ingest.chunk_section(items, spec, Vocabulary(), Counter())
    assert rows[0]["text"].count("42. Cefiderocol") == 1


# --- table sentences -----------------------------------------------------------------------------


def test_table_rows_become_one_sentence_each_and_continuation_rows_are_merged():
    rows = [
        ["Carbapenemase", ""],
        ["KPC", "1st Choice: Prolonged infusion of ceftazidime-\navibactam\nOther options:\na. Polymyxins"],
        ["", "b. Tigecycline"],
        ["NDM", "1st Choice: Ceftazidime-avibactam and aztreonam\nOther options:\na. Polymyxins"],
    ]
    result = table_to_sentences(rows, "Table 4: Options", "Carbapenemase")
    assert len(result) == 2
    assert result[0] == (
        "Table 4: Options. Carbapenemase KPC: 1st choice: Prolonged infusion of ceftazidime-avibactam; "
        "other options: a. Polymyxins b. Tigecycline."
    )
    assert "NDM" in result[1]


def test_two_column_detection():
    left = [{"x0": 50.0, "x1": 90.0}] * 40
    right = [{"x0": 250.0, "x1": 300.0}] * 40
    assert ingest.is_two_column(left + right, 419.5)
    crossing = [{"x0": 150.0, "x1": 280.0}] * 10
    assert not ingest.is_two_column(left + right + crossing, 419.5)
    assert not ingest.is_two_column(left[:10], 419.5)


# --- ID stability and the real ICMR 2022 PDF -----------------------------------------------------


@pytest.mark.skipif(not ICMR_2022_PDF.exists(), reason="ICMR 2022 PDF not downloaded")
def test_rerun_gives_identical_ids_and_text(tmp_path):
    ingest.run(out_dir=tmp_path / "a", only=[ICMR_2022])
    ingest.run(out_dir=tmp_path / "b", only=[ICMR_2022])
    for name in ("passages.jsonl", "nodes_Passage.csv"):
        assert (tmp_path / "a" / name).read_text(encoding="utf-8") == (tmp_path / "b" / name).read_text(encoding="utf-8")
    ids = [json.loads(line)["id"] for line in (tmp_path / "a" / "passages.jsonl").read_text(encoding="utf-8").splitlines()]
    assert ids and len(ids) == len(set(ids))
    for passage_id in ids:
        check_id("Passage", passage_id)


@pytest.mark.skipif(not ICMR_2022_PDF.exists(), reason="ICMR 2022 PDF not downloaded")
def test_icmr_2022_table_4_is_one_sentence_per_mechanism(tmp_path):
    ingest.run(out_dir=tmp_path, only=[ICMR_2022])
    rows = [json.loads(line) for line in (tmp_path / "passages.jsonl").read_text(encoding="utf-8").splitlines()]
    table = [r for r in rows if r["is_table"] and r["text"].startswith("Table 4")]
    assert len(table) == 4
    joined = " ".join(r["text"] for r in table)
    for label in ("NDM)", "OXA-48 like", "KPC"):
        assert label in joined
    for r in table:
        assert "1st choice" in r["text"] and "ceftazidime-avibactam" in r["text"]
        assert r["section"] == "directed-enterobacterales" and r["page"] == 16 and r["printed_page"] == 16
    section = [r for r in rows if r["section"] == "directed-enterobacterales"]
    assert any(not r["is_table"] for r in section)  # text before and after the table is kept
    assert {r["page"] for r in rows if r["section"] == "prevention"} == {20}


# --- generated files -----------------------------------------------------------------------------

PASSAGES = DATA_PROCESSED / "passages.jsonl"
needs_output = pytest.mark.skipif(not PASSAGES.exists(), reason="python -m pipeline.ingest has not been run")


def load_rows() -> list[dict]:
    return [json.loads(line) for line in PASSAGES.read_text(encoding="utf-8").splitlines()]


@needs_output
def test_output_ids_are_unique_and_follow_the_contract():
    rows = load_rows()
    assert len({r["id"] for r in rows}) == len(rows)
    counters: dict[tuple, int] = defaultdict(int)
    for r in rows:
        check_id("Passage", r["id"])
        doc, section, n = r["id"].rsplit(":", 2)
        assert (doc, section) == (r["source_doc"], r["section"])
        counters[(doc, section)] += 1
        assert int(n) == counters[(doc, section)], "n counts up from 1 inside a section"


@needs_output
def test_output_pdf_passages_respect_size_limits():
    by_section: dict[tuple, list[dict]] = defaultdict(list)
    for r in load_rows():
        if not r["source_doc"].startswith("pubmed-"):
            by_section[(r["source_doc"], r["section"])].append(r)
    assert by_section
    for rows in by_section.values():
        for i, r in enumerate(rows):
            assert r["n_words"] == len(r["text"].split())
            assert r["n_words"] <= MAX_WORDS, r["id"]
            if i < len(rows) - 1 and not r["is_table"]:
                assert r["n_words"] >= MIN_WORDS, f"{r['id']} has {r['n_words']} words"


@needs_output
def test_output_passages_stay_inside_their_section_pages():
    specs = ingest.load_sections()
    for r in load_rows():
        if r["source_doc"] not in specs:
            continue
        spec = specs[r["source_doc"]]
        section = next(s for s in spec.sections if s.slug == r["section"])
        assert not section.skip
        assert section.first_page <= r["page"] <= section.last_page, r["id"]
        assert r["printed_page"] == r["page"] - spec.page_offset


@needs_output
def test_output_has_no_extraction_damage():
    text = "\n".join(r["text"] for r in load_rows())
    assert "(cid:" not in text
    assert "�" not in text and not re.search("[-]", text)
    assert "ﬁ" not in text and "ﬂ" not in text


@needs_output
def test_output_has_the_three_pdfs_and_every_abstract():
    rows = load_rows()
    assert {"who-aware-book-2022", "icmr-treatment-guidelines-2019", ICMR_2022} <= {r["source_doc"] for r in rows}
    abstracts = [r for r in rows if r["source_doc"].startswith("pubmed-")]
    pmids = {
        json.loads(line)["pmid"]
        for line in ingest.PUBMED_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    assert {r["source_doc"] for r in abstracts} == {f"pubmed-{p}" for p in pmids}
    assert all(r["section"] == "abstract" and r["id"].endswith(":abstract:1") for r in abstracts)


@needs_output
def test_nodes_passage_csv_passes_the_validator(tmp_path):
    shutil.copy(DATA_PROCESSED / "nodes_Passage.csv", tmp_path / "nodes_Passage.csv")
    result = subprocess.run(
        [sys.executable, "-m", "pipeline.validate", str(tmp_path)], cwd=ROOT, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr

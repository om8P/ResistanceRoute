# Handoff: T06 PDF ingestion and section-aware chunking

- **Model:** Sonnet 5.5
- **Status:** complete
- **Date:** 2026-11-18

## What was built

`python -m pipeline.ingest` reads the three guideline PDFs and the 319 PubMed abstracts and writes **1,428 passages** (313,821 words) with IDs `<source doc id>:<section slug>:<n>`. PDF passages hold 150 to 250 words with about 30 words of overlap and never cross a section boundary. Each abstract is one passage. Running headers, footers, page numbers and the inline ICMR 2019 reference lists are removed. The AWaRe infographic pages (157 two-column pages) are read column by column. ICMR 2022 Table 4 becomes one sentence per mechanism. A rerun gives byte-identical `passages.jsonl`. `nodes_Passage.csv` passes `pipeline.validate` (1,428 accepted, 0 rejected).

## Files created or changed

| Path | What it is |
|---|---|
| `pipeline/ingest.py` | Extraction, `normalise_text`, section split, chunking, outputs, CLI |
| `schema/sections.yaml` | Section map: 3 documents, slug, title, PDF page range, `skip` with reason, `start_heading` where two sections share a page |
| `data/processed/passages.jsonl` | `id, text, source_doc, section, page, n_words, printed_page, is_table, heading` |
| `data/processed/nodes_Passage.csv` | `id, text, source_doc, section` |
| `data/processed/ingest_report.json` | Counts per document and section, skipped sections, pages with no text, repair counts, text-quality measure |
| `tests/test_ingest.py` | 37 tests (normalisation, chunk sizes, section boundaries, ID stability, Table 4, output files) |

No other file was touched.

## How to run and check it

```bash
.venv/Scripts/python -m pipeline.ingest                    # about 60 s; rewrites the three outputs
.venv/Scripts/python -m pipeline.ingest --only icmr-cr-gram-negative-2022 --out-dir <dir>   # quick check, skips PubMed
.venv/Scripts/python -m pipeline.validate data/processed
.venv/Scripts/python -m pytest tests/test_ingest.py
```

On this machine `.venv\Scripts\python.exe` could not be started directly from PowerShell or Git Bash ("Unable to create process", the venv points at the Microsoft Store Python). I ran everything as `cmd /c ".venv\Scripts\python.exe ..."`, which works.

## Test result

`448 passed, 2 warnings in 12.19s` for `.venv/Scripts/python -m pytest tests` (whole suite; the warnings are `typer`/`click` deprecations in site-packages). No failures. The output-file tests in `test_ingest.py` are skipped if `passages.jsonl` does not exist.

## What I found

### Passage counts

| Document | Passages | Words | Sections with passages | Pages with no text (read) |
|---|---|---|---|---|
| `who-aware-book-2022` | 880 | 194,669 | 48 (chapters 1 to 48; 7 sections skipped) | 42, 308, 642 (blank ends of chapters) |
| `icmr-treatment-guidelines-2019` | 205 | 43,182 | 13 (chapters 1 to 13) | none |
| `icmr-cr-gram-negative-2022` | 24 | 4,336 | 7 | none |
| `pubmed-<pmid>` (319 documents) | 319 | 71,634 | `abstract` | – |

Per-section counts are in `ingest_report.json`. Skipped: front matter; the three AWaRe part-divider pages, dosing chapters 49 and 50 (PDF 643 to 668) and references (669 to 697); ICMR 2019 chapter 14 tables, Appendix I and II; ICMR 2022 title page, Table 7 (dosage) and references. Sections are chapters, so the ID `n` runs through a whole chapter; the nearest sub-heading is in the `heading` field of `passages.jsonl`. Section slugs follow the contract example (`sepsis-adults`, `lower-uti`, ...).

Size rule, checked by a test over the real output: every PDF passage is at most 250 words (median 231), and only the last passage of a section may be shorter than 150, except passages flagged `is_table`. 25 AWaRe and 5 ICMR 2019 passages are short (the tail of a section). Abstracts are one passage each and exempt (median 203 words, a few above 250).

### Three samples (text cut for length)

**AWaRe Reserve chapter**, `who-aware-book-2022:cefiderocol:3` (PDF p599, printed p583, 242 words, two-column infographic page):

> - who have previously been treated for infections caused by carbapenem-resistant pathogens susceptible to cefiderocol - who are known to be colonized with carbapenem-resistant pathogens susceptible to cefiderocol Important Considerations • Efficacy demonstrated in clinical trials for empiric use for complicated UTI, VAP/HAP, BSI and sepsis in adults • Very limited evidence for other infections and use in children Formulations • Powder for intravenous infusion: 1 g/vial Spectrum of Activity • Active against: - Aerobic Gram-negative bacteria including many carbapenem resistant Enterobacterales, Pseudomonas aeruginosa and Acinetobacter baumannii • Carbapenemases: KPC, OXA-48 and MBLs • ESBL and AmpC β-lactamases • Not active against: - Gram-positive bacteria and anaerobes ...

The first words are the 30-word overlap from passage 2. The same page extracted naively reads `Carbapenemases:KPC,OXA-48andMBLs`, `ce(cid:31)derocol` and `con rmed`, with the two columns interleaved line by line.

**ICMR 2022 Table 4**, `icmr-cr-gram-negative-2022:directed-enterobacterales:2` (p16, 99 words, `is_table: true`):

> Table 4: Available treatment options for carbapenem resistant Enterobacterales in India. Carbapenemase Metallo-β-lactamase (eg. NDM): 1st choice: Prolonged infusion of ceftazidime-avibactam and aztreonam (over 3 hours)*; other options: a. Polymyxins (Do-not use polymyxin B for UTI) plus other agent to which organism has demonstrated susceptible MIC (like tigecycline, aminoglycosides, IV fosfomycin) or high dose carbapenems if MIC < 16 b. Tigecycline (...) c. Aminoglycosides (...).

Passages 3 to 5 are the NDM + OXA-48, OXA-48-like and KPC rows (the KPC row continues on p17 and is merged). The `*` and `**` footnote marks are kept; the footnotes are in passage 6.

**Abstract**, `pubmed-37937997:abstract:1` (180 words, `page` null): title plus abstract: "Klebsiella pneumoniae carbapenemase variants: the new threat to global public health. Klebsiella pneumoniae carbapenemase (KPC) variants, which refer to the substitution, insertion, or deletion of amino acid sequence compared to wild blaKPC type, have reduced utility of ceftazidime-avibactam (CZA) ..."

### Text-quality measure (AWaRe Reserve chapters 41 to 48, PDF p593 to 642)

The measure is the share of alphabetic tokens of 3 or more letters that are not in a clean vocabulary (PubMed abstracts, the ICMR PDFs, AWaRe pages with no damage, and every name and synonym in `schema/synonyms.csv`). The literal version in the brief (words not in a dictionary of drug and pathogen names) would be about 90% for any English prose, so I used this one.

| | Tokens | Not in vocabulary | Share |
|---|---|---|---|
| Plain `pdfplumber extract_text()` of those pages | 11,737 | 226 | **1.93%** |
| The 8 chapters' passages after repair | 12,572 | 133 | **1.06%** |

Mentions of single-word scope names (5+ letters) rise from 758 to 834 (+10%): names that were glued or broken are now found. The 133 remaining tokens are almost all ordinary English words missing from the small vocabulary (`bind`, `lysis`, `ribosome`, `vestibular`, ...; the top 30 are in the report). Residual damage I know of: 9 ligature glyphs in the whole book could not be resolved to one word and were dropped (`ligature_marker_unresolved`), and one heading wraps as `polymyxin E) myxin E)`.

### How the text is repaired (`normalise_text`, all counts in the report)

- **Ligature code points** (U+FB00 to U+FB06) and `(cid:31)` / `(cid:157)` become `fi`. All other `(cid:N)` glyphs in the book (N = 1, 5, 7, 8, 11 to 15, 23, 26 to 30, 127, 129, 141, 143) are also `fi` or `fl`, but which one depends on the font subset, so each becomes a marker and the vocabulary decides: `In<marker>uenza` becomes `Influenza` only if exactly one of fi, fl, ff, ffi, ffl gives a known word. Same rule for stray symbols inside words (`In“uenza`, `signi’cant`, `signiŒcant`). 208 stray symbols and 180 cid glyphs were handled this way.
- **Spacing**: extraction uses `x_tolerance_ratio=0.1` for the AWaRe book (word gaps there are only about 1 pt at font size 6, so the default tolerance glued words). Remaining breaks (`Infe ctions`, `con rmed`, `bene t`, `rst` for `first`) are joined only if the result is a vocabulary word and one fragment is rare; two real words are never joined. 11 space joins, 22 prefix repairs.
- **Explicit list** (`EXPLICIT_REPLACEMENTS`): `ce derocol`, `Tr eatment`, `res istant`, `Infe ctions`, `con rmed`, `signi cant`, `bene t`. Word boundaries, no vocabulary needed.
- **Hyphenation at line ends** is removed only when the solid word is in the vocabulary and more frequent than the hyphenated one; otherwise the hyphen stays (`ceftazidime-avibactam`).
- Private-use glyphs (Webdings arrows in the AWaRe headers), zero-width characters and odd spaces are removed. Real quotation marks are kept.

### Layout facts for later tasks

- AWaRe running header and footer sit at y = 24 and y = 568 (page height 595); the extractor crops 29 pt from the top and 35 pt from the bottom, then drops the chapter title that repeats on every page.
- AWaRe infographic pages are two columns with no word crossing the page middle; the extractor reads left column, then right column. In the output an infographic chapter therefore reads as "key messages, long text, then the infographic left column, then right column". Section headings of the infographic ("Treatment", "Most Likely Pathogens") appear inline.
- ICMR 2019 prints references inside each chapter; they are dropped from the line "References" to the next numbered heading. Its tables (for example Table 10.11, 10.12) extract column by column and are not recoverable: they stay as text and are flagged `is_table` only when the passage starts with a `Table N:` caption or a run of short numeric lines (182 AWaRe, 30 ICMR 2019, 6 ICMR 2022 passages are flagged; the 4 ICMR 2022 Table 4 rows are the only ones converted to sentences). ICMR 2022 Tables 1, 2 and 5 are also flattened, and are unflagged where the caption is not the first line of a unit, for example `directed-non-enterobacterales:2`.
- Dosing: the dosing chapters are skipped, but each AWaRe infographic page still carries its own dose and weight-band lines. Those are in the passages. T13 should not read doses from them.
- Consecutive passages repeat about 30 words, so one entity mention can be in two neighbouring passages (T07 `MENTIONS` edges, T11 ranking).

## Deviations from the brief or contracts

- `passages.jsonl` has one field beyond the brief: `heading` (nearest numbered sub-heading, empty for abstracts). `page` and `printed_page` are `null` for abstracts (they have no page). CONTRACTS section 6 lists six fields, so a reader that expects an integer `page` must handle null.
- A table-row passage is exempt from the 150-word minimum (a Table 4 row is 92 to 100 words and is deliberately one chunk).
- Sections are whole chapters (48 AWaRe, 13 ICMR 2019), not sub-chapters; sub-headings are only in `heading`.
- The `Passage` model accepted all four CSV fields; nothing needed from `pipeline/models.py`.

## Not done or not verified

- Not read through: I read the Reserve chapter 42, bronchitis, parts of ICMR 2019 chapter 10 and all of ICMR 2022 in the output, not every passage. The text-quality measure is a vocabulary check, not a proof that no word is wrong.
- No spelling normalisation beyond the cases above, so source typos stay (`azteronam`, `A. baumanii`).
- The two-column detector is a rule (no word crossing the middle, 20% of words on each side). I checked it on pages 46, 47, 599 and 634 (two column) and 313, 594 and 100 (single column) and by the page count in the report, not on every page.
- Table 4 conversion is written for the two-column "1st Choice / Other options" layout; any other two-column table would get the fallback sentence `<caption>. <header> <label>: <cell>.`, which I did not need.

## Requests to orchestrator

1. **Venv launcher:** `.venv\Scripts\python.exe` fails from PowerShell and Git Bash on this machine and works through `cmd /c`. Other workers and the README should say so, or the venv should be rebuilt on a regular Python.
2. **`page` null for abstracts** (see Deviations): confirm, or give abstracts a fixed page such as 1.
3. **T11 / T15:** decide whether passage text should be indexed with or without the 30-word overlap (the overlap is in `text`; each passage's own start is not stored).

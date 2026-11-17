# T06: PDF ingestion and section-aware chunking

- **Model:** Sonnet 5.5
- **Wave:** 2
- **Depends on:** T02 (done)
- **Read first:** [ORCHESTRATION.md](../ORCHESTRATION.md), [CONTRACTS.md](../CONTRACTS.md) sections 2, 3 and 6, [ARCHITECTURE.md](../ARCHITECTURE.md) sections 4 and 5.3, [DECISIONS.md](../DECISIONS.md) D12, and the "guidelines" and "pubmed" parts of the [T02 handoff](../handoffs/T02-data-acquisition.md)

## Goal

Turn the three guideline PDFs and the PubMed abstracts into clean, section-aware passages with stable IDs. These passages feed the BM25 and dense indexes, the entity linker, and the recommendation curation and extraction.

## Files you own

- `pipeline/ingest.py`
- `schema/sections.yaml` (section map per document)
- `data/processed/passages.jsonl`
- `data/processed/nodes_Passage.csv`
- `data/processed/ingest_report.json`
- `tests/test_ingest.py`

## Inputs

| Source doc ID | File | Notes from T02 |
|---|---|---|
| `who-aware-book-2022` | `data/raw/guidelines/who-aware-antibiotic-book-2022.pdf` | 697 pages, PDF outline exists; printed page = PDF page − 16; Reserve chapters (PDF p598–642) extract with broken spacing and ligatures |
| `icmr-treatment-guidelines-2019` | `data/raw/guidelines/icmr-treatment-guidelines-2019.pdf` | 206 pages, no outline; contents listed in the T02 handoff; printed page = PDF page − 5 |
| `icmr-cr-gram-negative-2022` | `data/raw/guidelines/icmr-carbapenem-resistant-gram-negative-2022.pdf` | 24 pages, no outline, extra spaces inside words; Table 4 (p16–17) is per-mechanism |
| `pubmed-<pmid>` | `data/raw/pubmed/abstracts.jsonl` | 319 abstracts; one passage each, section `abstract` |

## Work

1. **`schema/sections.yaml`**: for each PDF, the list of sections with slug, title and PDF page range. Use the outline for the AWaRe book and the contents pages for the two ICMR PDFs. Front matter, dosing tables, references and the ICMR 2019 Appendix I surveillance tables are marked `skip: true`.
2. **Text extraction** with `pdfplumber` (fall back to `pypdf` per page if needed). Remove running headers, footers and page numbers. Repair hyphenation at line ends.
3. **Normalisation**: fix ligatures and the spacing problems T02 found (for example `ce/g246derocol`, `Tr eatment`, `res istant`). Write the repairs as a small, tested function with an explicit list of replacements plus generic rules; do not guess beyond what you can check. Report what fraction of words in the Reserve chapters are still not in a dictionary of the in-scope drug and pathogen names after repair, as a rough quality measure.
4. **Chunking**: within each section, split on headings and paragraphs, then pack into passages of 150–250 words with about 30 words of overlap. Never cross a section boundary. Convert table rows to one sentence each where the table structure is recoverable (at least ICMR 2022 Table 4); otherwise keep the table text as one passage and mark it `is_table: true`.
5. **Output**: `passages.jsonl` with `id`, `text`, `source_doc`, `section`, `page` (PDF page of the start), `n_words`, plus `printed_page` and `is_table`. `nodes_Passage.csv` has `id`, `text`, `source_doc`, `section`. IDs follow CONTRACTS §2 (`<source doc>:<section slug>:<n>`, `n` from 1 within a section) and must be stable across reruns.
6. **`ingest_report.json`**: passages and words per document and section, sections skipped, pages with no text.

## Rules specific to this task

- Do not write any other file in `data/processed/`. If the `Passage` model rejects a field you need, report it instead of changing `pipeline/models.py`.
- Validate `nodes_Passage.csv` with `python -m pipeline.validate` (it skips edge files that do not exist).

## Done when

- `python -m pipeline.ingest` produces the outputs and reruns give identical IDs.
- `.venv/Scripts/python -m pytest tests` passes, with tests for normalisation, chunk sizes, section boundaries and ID stability.
- The handoff `docs/handoffs/T06-pdf-chunking.md` gives passage counts per document, three sample passages (one from a Reserve chapter, one from ICMR 2022 Table 4, one abstract), and the text-quality measure.

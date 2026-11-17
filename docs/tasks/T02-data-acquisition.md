# T02: Data acquisition and source inventory

- **Model:** Sonnet 5.5
- **Wave:** 1
- **Depends on:** T00 (done)
- **Read first:** [ORCHESTRATION.md](../ORCHESTRATION.md), [CONTRACTS.md](../CONTRACTS.md), [ARCHITECTURE.md](../ARCHITECTURE.md) sections 2 and 3, [DECISIONS.md](../DECISIONS.md) D19

## Goal

Get the real source data onto disk with a repeatable script, and describe exactly what each file contains. Wave 2 writes loaders and parsers from your description, so its accuracy matters more than anything else in this task.

## Files you own

- `pipeline/download.py`
- `data/SOURCES.md`
- everything under `data/raw/`
- `tests/test_download.py`

## Sources

| Folder | Source | What to get |
|---|---|---|
| `data/raw/aware/` | WHO AWaRe classification of antibiotics, latest edition | The Excel file with antibiotic, class, ATC code and AWaRe group |
| `data/raw/card/` | CARD data download (`card.mcmaster.ca`) | The data archive, extracted: ARO index, ARO categories, `card.json` |
| `data/raw/glass/` | WHO GLASS antimicrobial resistance data | Resistance percentages by country and year for the five pathogens in scope, in any tabular form WHO publishes |
| `data/raw/guidelines/` | WHO AWaRe antibiotic book; ICMR treatment guidelines for antimicrobial use; ICMR guidance on carbapenem-resistant Gram-negative infections if published | The PDFs |
| `data/raw/taxonomy/` | NCBI Taxonomy through E-utilities | One JSON file with taxonomy ID, scientific name and synonyms for the five pathogens |
| `data/raw/pubmed/` | PubMed through E-utilities | `pmids.csv` (`query,pmid`) and `abstracts.jsonl` (`pmid,title,abstract,year,journal`), about 300–500 abstracts on resistance mechanisms and treatment for the five pathogens |

The five pathogens are *Klebsiella pneumoniae*, *Escherichia coli*, *Acinetobacter baumannii*, *Pseudomonas aeruginosa* and *Staphylococcus aureus*.

## Work

1. **Find and verify each source URL** by fetching it. Record the version or publication date and the licence.
2. **`pipeline/download.py`**
   - One function per source, and a CLI: `python -m pipeline.download [--only aware,card,...] [--force]`.
   - Skips files that already exist unless `--force` is given.
   - Writes `data/raw/manifest.json` with URL, retrieval date, size and SHA-256 for every file.
   - Every request has a timeout and the `User-Agent` from `pipeline/config.py`. No email address or name in any request. For NCBI, stay at or below three requests per second and use no API key.
3. **Run it** and download the data. Keep the total under about 1 GB.
4. **When a source cannot be downloaded automatically** (login, form, blocked), do not work around access controls. Write the manual steps in `data/SOURCES.md`, leave the folder empty and report it.
5. **`data/SOURCES.md`**: for each source, the URL, version, licence, files obtained and whether it was automatic or manual.
6. **Inspect what you downloaded** and put this in the handoff:
   - For each table: file name, sheet names, column headers, row count and three sample rows.
   - For CARD: which files and fields link a gene or gene family to a resistance mechanism and to drug classes, with an example for KPC and NDM.
   - For each PDF: page count, the table of contents, and which sections and page ranges cover the five pathogens or their infections.
   - For GLASS: which pathogens, antibiotics, countries and years are present, and whether India is included.

## Rules specific to this task

- Never fabricate a file, a URL or a value. If something is unavailable, say so.
- Do not commit to a file format in the handoff that you have not opened and checked.

## Tests

`tests/test_download.py` covers the helper functions without network access: manifest writing, hashing, skip-if-exists logic.

## Done when

- `python -m pipeline.download` re-runs cleanly and skips existing files.
- `data/raw/manifest.json` and `data/SOURCES.md` are complete.
- `.venv/Scripts/python -m pytest tests` passes.
- The handoff `docs/handoffs/T02-data-acquisition.md` contains the file inventory described in step 6 and lists any source that needs a manual download.

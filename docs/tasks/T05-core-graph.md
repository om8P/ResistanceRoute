# T05: Structured loaders and core graph build

- **Model:** Sonnet 5.5
- **Wave:** 2
- **Depends on:** T01, T02, T03 (done)
- **Read first:** [ORCHESTRATION.md](../ORCHESTRATION.md), [CONTRACTS.md](../CONTRACTS.md), [ARCHITECTURE.md](../ARCHITECTURE.md) sections 4 and 5, [DECISIONS.md](../DECISIONS.md) D26–D30, handoffs [T01](../handoffs/T01-schema-models.md), [T02](../handoffs/T02-data-acquisition.md) ("What I found": AWaRe, CARD, GLASS) and [T03](../handoffs/T03-domain-seed.md), and `data/curated/REVIEW_NOTES.md` section 3

## Goal

Build the core of the graph from the seed data and the structured sources, write it as processed CSV files, validate it, and load it into Neo4j. Write the loader so that later tasks can add their own `nodes_*.csv` and `edges_*.csv` files and load them with the same command.

## Files you own

- `pipeline/build_core.py`
- `pipeline/load.py`
- `schema/glass_map.csv`
- `data/processed/nodes_{Pathogen,Mechanism,Gene,Drug,DrugClass,Guideline,SurveillanceStat}.csv`
- `data/processed/edges_{HAS_MECHANISM,ENCODES,CONFERS_RESISTANCE_TO,INACTIVATES,INTRINSICALLY_RESISTANT_TO,IN_CLASS,ABOUT_PATHOGEN,ABOUT_DRUG,ABOUT_CLASS}.csv`
- `data/processed/load_report.json`
- `tests/test_build_core.py`, `tests/test_load.py`

## Work

1. **`pipeline/build_core.py`** writes the files above from:
   - `schema/scope.yaml`: `Pathogen`, `Mechanism`, `DrugClass` (with `family`), `Drug` nodes, and `IN_CLASS` edges from each drug's `class_id`. Drop `id_verified`. Drug synonyms come from `schema/synonyms.csv`.
   - `data/curated/*.csv`: `HAS_MECHANISM`, `CONFERS_RESISTANCE_TO`, `INACTIVATES`, `INTRINSICALLY_RESISTANT_TO`, with `source_id` `curated-seed`, `method` `curated`, and the row's `needs_review` and `notes` as extra edge properties.
   - **AWaRe 2025** (`data/raw/aware/WHO-AWaRe-classification-2025.xlsx`): cross-check `aware_group` for every in-scope drug and report mismatches; do not overwrite `scope.yaml` values. Handle the quirks listed in the T02 handoff.
   - **CARD** (`aro_index.tsv`, `card.json`): `Gene` nodes for alleles whose gene family is one of the in-scope mechanisms and that have a sequence from an in-scope pathogen, with `ENCODES` edges to the family (`source_id` `card`). Report how many genes this gives; if it is above about 1,000, keep only alleles named in `PMID.tsv` or the most common ones, and say which rule you used.
   - **GLASS** (`data/raw/glass/glass_amr_pathogens.csv`): one `SurveillanceStat` per (country, year, pathogen, antibiotic) from `PERCENTAGERESISTANCE` rows, `n_tested` from `INTERPRETABLEAST`, specimen `BLOOD` only. Follow T02's de-duplication advice. Only in-scope pathogens. GLASS antibiotic names map to a drug ID or to a class ID through `schema/glass_map.csv` (`glass_name,target_label,target_id`), which you write; unmapped names are skipped and counted. Apply D30 for *Acinetobacter*.
   - `Guideline` nodes for `who-aware-book-2022`, `icmr-treatment-guidelines-2019` and `icmr-cr-gram-negative-2022`, with title, organisation, year and version from `data/SOURCES.md`.
2. **`pipeline/load.py`**: CLI `python -m pipeline.load [--clear]`. Validates every `nodes_*.csv` and `edges_*.csv` in `data/processed/` with `pipeline.validate`, applies the constraints, loads nodes then edges with `pipeline.graph_db`, and writes `load_report.json` (counts loaded and rejected per file, with reasons). `--clear` calls `clear_graph(confirm=True)` first. It must work with files it has never seen, as long as they follow the contract.
3. **Acceptance query.** After loading, run a Cypher query that, for carbapenem-resistant *K. pneumoniae*, lists the in-scope drugs not excluded by each mechanism (exclusions = classes from `CONFERS_RESISTANCE_TO` ∪ classes from `INTRINSICALLY_RESISTANT_TO` ∪ drugs from `INACTIVATES`). Compare with `REVIEW_NOTES.md` section 3 for KPC, NDM and OXA-48-like. Put the query and its output in the handoff. This is milestone M2.

## Rules specific to this task

- Do not edit `schema/scope.yaml`, `schema/synonyms.csv` or `data/curated/`. Report problems with them.
- Other wave 2 tasks write `nodes_Passage.csv` and `edges_MENTIONS.csv` into `data/processed/`. Your loader loads them if present, but do not edit them.
- Tests that write to Neo4j use IDs unique to the run and delete only what they created. Tests must not call `--clear` on the shared database.
- The full build-and-load is run against the shared database once, at the end, with `--clear`.

## Done when

- `python -m pipeline.build_core` and `python -m pipeline.load --clear` run cleanly; `load_report.json` shows no unexplained rejections.
- The acceptance query gives three different drug sets that match REVIEW_NOTES section 3.
- `.venv/Scripts/python -m pytest tests` passes.
- The handoff `docs/handoffs/T05-core-graph.md` gives node and edge counts per type, the AWaRe mismatches, the GLASS mapping coverage and the acceptance query output.

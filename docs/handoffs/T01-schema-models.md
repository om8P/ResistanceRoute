# Handoff: T01 Schema, data models, validation, database helpers

- **Model:** Sonnet 5.5
- **Status:** complete
- **Date:** 2026-11-17

## What was built

The graph schema as code: a Cypher file with nine named uniqueness constraints and four name indexes, Pydantic v2 models for all nine node labels plus `Edge` and `RecommendationExtraction`, the `NODE_MODELS` and `EDGE_TYPES` registries, a validator with a directory CLI, and Neo4j helpers that check labels and relationship types against the registries before building any query string. **The constraints were applied to a live Neo4j** (the project's `amr-navigator-neo4j` container) and all 9 constraints and 4 indexes were confirmed present with `SHOW CONSTRAINTS` and `SHOW INDEXES`.

## Files created or changed

| Path | What it is |
|---|---|
| `schema/constraints.cypher` | 9 `CREATE CONSTRAINT <label>_id_unique IF NOT EXISTS` and 4 `CREATE INDEX <label>_name IF NOT EXISTS`, one statement per line |
| `pipeline/models.py` | Node models, `Edge`, `RecommendationExtraction`, enums, `NODE_MODELS`, `EDGE_TYPES`, `EDGE_COLUMNS`, `check_id` / `is_valid_id`, `ID_PATTERNS` |
| `pipeline/validate.py` | `validate_nodes`, `validate_edges`, `ValidationReport`, CSV helpers, `validate_directory`, CLI |
| `pipeline/graph_db.py` | `get_driver`, `ping`, `apply_constraints`, `merge_nodes`, `merge_edges`, `clear_graph`, plus `list_constraints`, `list_indexes`, `read_statements` |
| `tests/test_models.py` | 125 tests: every ID format, every model, edge provenance, registries |
| `tests/test_validate.py` | 32 tests: duplicates, dangling edges, label pairs, provenance, CSV round trip, CLI |
| `tests/test_graph_db.py` | 29 tests: label, relationship-type and `confirm` guards and statement parsing need no database; the tests that use the `driver` fixture run against Neo4j and skip when it is unreachable |

## How to run and check it

```bash
.venv/Scripts/python -m pytest tests
.venv/Scripts/python -m pipeline.validate data/processed        # exit 0 clean, 1 if anything rejected, 2 bad directory
.venv/Scripts/python -m pipeline.validate <dir> --max-examples 20 --skip-endpoints
docker compose up -d
.venv/Scripts/python -c "from pipeline.graph_db import *; d=get_driver(); apply_constraints(d); print(list_constraints(d)); d.close()"
```

Typical load code:

```python
from pipeline.validate import read_csv_rows, validate_nodes, validate_edges
from pipeline.graph_db import get_driver, merge_nodes, merge_edges

report = validate_nodes("Drug", read_csv_rows("data/processed/nodes_Drug.csv"))
merge_nodes(driver, "Drug", report.accepted)           # accepted rows are normalised dicts
ereport = validate_edges("IN_CLASS", rows, {"Drug": {...ids}, "DrugClass": {...ids}})
merge_edges(driver, "IN_CLASS", ereport.accepted)
```

## Test result

`241 passed in 2.89s` for the whole `tests` folder with Neo4j running and no skips. My three files account for 186 of those (125 + 32 + 29); the other 55 belong to other sessions' tests that were already in the folder, and all of them passed. With Neo4j unreachable the `driver`-fixture tests in `test_graph_db.py` skip with a clear message (not exercised in this run, because the database was up).

The CLI was also run on a hand-made directory (a duplicate node ID, a dangling edge, an edge with no `source_id`): it reported each reason and exited with status 1.

## What I found

- **Docker:** the daemon was running and `amr-navigator-neo4j` was already up when I ran `docker compose up -d` (another session or the user had started it), so I did not start or touch it. The database was empty (0 nodes). Ports 7474 and 7687 were published by that container.
- **Driver:** `neo4j` 6.3.1 against the `neo4j:5-community` image works. `pydantic` is 2.12.5.
- **Models accept CSV strings.** Blank cells are treated as missing (so defaults and "required" errors apply), and list fields (`synonyms`, `RecommendationExtraction.drugs`) split on `|`. `extra="forbid"` on node models: an unknown column rejects the row. `Edge` allows extra columns, which become relationship properties.
- **`Model.to_row()`** gives a JSON-friendly dict with `None` omitted (enums as plain strings, lists as lists), which is what `ValidationReport.accepted` holds and what `merge_nodes` takes. `Model.properties()` is the same without `id`.
- **ID checks (CONTRACTS section 2):** ATC `[A-Z]\d{2}[A-Z]{2}\d{2}` (upper case only, 7 characters); `ARO:` plus exactly 7 digits; `NCBITaxon:<digits>`; slugs `[a-z0-9]+(-[a-z0-9]+)*`; Guideline slug must end in `-YYYY`; Recommendation `REC:<guideline id>:<3 digits>`; Passage `<slug>:<slug>:<digits>`.
- **Defaults:** `Drug.aware_group` defaults to `Unclassified`. `Edge.confidence` defaults to `1.0` for `curated` and is required for `rule` and `llm`.
- **`known_ids`** for `validate_edges` is best given as `{label: set_of_ids}` (an ID string could in theory exist under two labels). A flat collection or `None` (skip the check) also works. `validate_directory` builds the mapping from the accepted rows of the `nodes_*.csv` files, so edges to rejected nodes count as dangling.
- **`merge_edges` return value** is `{"rows", "merged", "missing_endpoints", "relationships_created"}`. Edges whose endpoints are not in the database are skipped, never created, and counted in `missing_endpoints` (use this for `load_report.json`). `merge_nodes` returns `{"rows", "nodes_created", "properties_set"}`. Load nodes before edges.
- **Edges merge on `(start, type, end)`.** A second row for the same pair updates the first one's properties, so one pair can hold only one `evidence_passage_id`. The validator rejects the second row (see deviations).
- **`clear_graph(driver, confirm=True)`** deletes in batches and keeps constraints and indexes. The tests never call it with `confirm=True`; integration tests only create and delete nodes with their own `t01-test` or `NCBITaxon:99000000x` IDs.
- **`ping()`** takes an optional driver, never raises, and uses a 2 second connection timeout.

## Deviations from the brief or contracts

- `ping()` accepts an optional `driver` argument (the contract shows none); calling it with no argument works as specified.
- `merge_nodes` and `merge_edges` return count dictionaries rather than nothing, and `graph_db` has three extra helpers (`list_constraints`, `list_indexes`, `read_statements`).
- `validate_edges` rejects a second row with the same `(start, end)` pair as an earlier row ("duplicate edge"), because `merge_edges` could not keep both. This goes slightly beyond the brief's check list.
- `SurveillanceStat` rejects a row whose `country` or `year` differs from the ones embedded in its `id`.
- `RecommendationExtraction` has three fields beyond the brief's list: `passage_id` (optional, Passage format), `method` (default `rule`) and `confidence` (optional 0 to 1), so extracted recommendations can carry provenance into the graph.
- `GramStain` allows only `positive` and `negative`; `pct_resistant` is a percentage from 0 to 100; `Guideline.year` must be 1900 to 2100.

## Not done or not verified

- `RecommendationExtraction` is only unit-tested; no extraction code uses it yet.
- No real data was validated or loaded; the CLI and `merge_*` were exercised only on small synthetic fixtures. Edge `source_id` values are checked against the fixed list in CONTRACTS section 6 plus Guideline IDs, so any new dataset name needs a contract change.
- Performance with large batches was not tested. The skip path of the database tests was not run (Neo4j was up).

## Requests to orchestrator

1. **Class-level surveillance.** CONTRACTS section 2 allows the last part of a `SurveillanceStat` ID to be a drug class (for example `GLASS:KEN:2021:NCBITaxon:562:carbapenem`), but ARCHITECTURE section 5.1 only has `(SurveillanceStat)-[:ABOUT_DRUG]->(Drug)`. A class-level stat therefore cannot be linked to its class. I kept `EDGE_TYPES` exactly as in the architecture. Options: allow `("SurveillanceStat", "DrugClass")` under `ABOUT_DRUG`, add an `ABOUT_CLASS` type, or restrict stat IDs to drugs. Whichever you pick, it is a one-line change in `EDGE_TYPES` in `pipeline/models.py` (and the same label list in the architecture).
2. Confirm that edge duplicates by `(start, end)` should be rejected, or tell T05 to put multiple pieces of evidence for one pair in a single row.
3. Optionally note in `docs/CONTRACTS.md` section 7 that `validate_nodes` returns `accepted` as normalised dicts, that `known_ids` is best a label-to-IDs mapping, and that `merge_*` return count dictionaries.

## Follow-up (after orchestrator review, 2026-11-18)

Requests 1 and 2 above were decided (D26, D27); request 3 is done in CONTRACTS section 7. Two changes followed:

1. **`ABOUT_CLASS` added** to `EDGE_TYPES` in `pipeline/models.py` with the single pair `("SurveillanceStat", "DrugClass")`; `ABOUT_DRUG` is unchanged. `tests/test_models.py` now expects 15 relationship types, and a new test in `tests/test_validate.py` checks that class-level stat edges validate under `ABOUT_CLASS` and are rejected under `ABOUT_DRUG`, and that a `Drug` end is rejected for `ABOUT_CLASS`. Duplicate `(start, end)` edges are still rejected, as decided.
2. **Flaky database test fixed.** `tests/test_graph_db.py` no longer uses fixed IDs. A random tag and a random taxon number are generated once per test process, and every test ID (pathogens, mechanism, class, drug and the passage that was previously created and deleted inline) is built from them, within the ID formats. The cleanup fixture deletes only the nodes with that run's IDs, before and after each test. Three simultaneous runs of `tests/test_graph_db.py` against the live database all passed (29 each), and no `t01-test` nodes were left behind.

**Test result:** `.venv/Scripts/python -m pytest tests` gives `291 passed in 2.54s` with Neo4j running (my three files: 125 + 33 + 29 = 187; the rest are other sessions' tests). Only my own files were changed, plus this section.

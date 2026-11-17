# T01: Schema, data models, validation, database helpers

- **Model:** Sonnet 5.5
- **Wave:** 1
- **Depends on:** T00 (done)
- **Read first:** [ORCHESTRATION.md](../ORCHESTRATION.md), [CONTRACTS.md](../CONTRACTS.md), [ARCHITECTURE.md](../ARCHITECTURE.md) sections 4 and 5

## Goal

Turn the graph schema in the architecture into code that every later task builds on: database constraints, typed models for every node and edge, a validator for processed files, and helpers for loading into Neo4j.

## Files you own

- `schema/constraints.cypher`
- `pipeline/models.py`
- `pipeline/validate.py`
- `pipeline/graph_db.py`
- `tests/test_models.py`
- `tests/test_validate.py`
- `tests/test_graph_db.py`

Do not edit `pipeline/config.py` or `pipeline/__init__.py`; import from them.

## Work

1. **`schema/constraints.cypher`**
   - One named uniqueness constraint on `id` for each of the nine labels, written with `IF NOT EXISTS` so the file can be run repeatedly.
   - Indexes on `name` for `Drug`, `Pathogen`, `Mechanism` and `DrugClass`.
   - One statement per line ending in `;`, so it can be split and run by the driver.

2. **`pipeline/models.py`** (Pydantic v2)
   - One model per node label with the properties in ARCHITECTURE.md section 5.1.
   - ID validators that enforce the formats in CONTRACTS.md section 2.
   - Enumerations for `aware_group`, `method`, `line_of_therapy`, mechanism `type`.
   - `Edge` model with the provenance fields in CONTRACTS.md section 6. `source_id` and `method` are required.
   - `NODE_MODELS`: label → model. `EDGE_TYPES`: relationship type → set of allowed `(start_label, end_label)` pairs, covering every relationship in the architecture.
   - `RecommendationExtraction`: the structured output of recommendation extraction, with pathogen, optional mechanism, list of drugs, infection site, line of therapy, patient group and the evidence text. Names are free text here; linking to IDs happens later.

3. **`pipeline/validate.py`**
   - `validate_nodes(label, rows)` and `validate_edges(rel_type, rows, known_ids)` return a `ValidationReport` listing accepted rows and rejected rows with reasons.
   - Checks: model validation, duplicate IDs, edges whose endpoints are not in `known_ids`, label pairs not allowed for the relationship type, missing provenance.
   - Helpers to read and write the CSV conventions in CONTRACTS.md section 3, including `|`-separated lists.
   - CLI: `python -m pipeline.validate <directory>` validates every `nodes_*.csv` and `edges_*.csv` in the directory, prints a summary and exits non-zero when anything is rejected.

4. **`pipeline/graph_db.py`**
   - `get_driver()`, `ping()`, `apply_constraints(driver)`, `merge_nodes(driver, label, rows, batch_size=500)`, `merge_edges(driver, rel_type, rows, batch_size=500)`.
   - Use `UNWIND $rows` with `MERGE` on `id`. Labels and relationship types cannot be query parameters, so check them against `NODE_MODELS` and `EDGE_TYPES` before building the query string.
   - `clear_graph(driver, confirm=False)` that refuses to run unless `confirm=True`.

5. **Database check**
   - If Docker is running, start Neo4j with `docker compose up -d`, wait for it, apply the constraints and confirm they exist.
   - If Docker is not running or ports 7474/7687 are taken, do not change anything outside this project. Skip the check and report it.

## Tests

- `tests/test_models.py`: valid and invalid examples for every model and ID format.
- `tests/test_validate.py`: duplicates, dangling edges, wrong label pairs, missing provenance, CSV round trip.
- `tests/test_graph_db.py`: integration tests that skip automatically when Neo4j is unreachable.

## Done when

- `.venv/Scripts/python -m pytest tests` passes (database tests may be skipped).
- `python -m pipeline.validate` runs on a small fixture directory and reports correctly.
- The handoff `docs/handoffs/T01-schema-models.md` is written and says whether the constraints were applied to a live database.

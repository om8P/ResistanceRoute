# AMR-Navigator: Contracts

These are the formats and interfaces that tasks share. Every worker follows them exactly, so that code written in separate sessions fits together. Only the orchestrator edits this file; workers request changes in their handoff.

## 1. Environment

| Item | Value |
|---|---|
| Python | `.venv/Scripts/python` (3.11) |
| Tests | `.venv/Scripts/python -m pytest tests` |
| Paths and settings | import from `pipeline/config.py`; never hard-code paths |
| Neo4j | `bolt://localhost:7687`, user `neo4j`, password from `NEO4J_PASSWORD` (see `.env.example`) |
| Start Neo4j | `docker compose up -d` in the project root |
| Outbound HTTP | `User-Agent: amr-navigator/0.1`, timeout on every request, no personal details |

`pipeline/config.py` provides: `ROOT`, `DATA_RAW`, `DATA_PROCESSED`, `DATA_CURATED`, `SCHEMA_DIR`, `EVAL_DIR`, `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `USER_AGENT`.

## 2. Canonical IDs

All IDs are strings.

| Entity | Format | Example |
|---|---|---|
| `Drug` | WHO ATC code, upper case. Use the systemic `J01…` code when a drug has several. | `J01DH02` (meropenem) |
| `Drug` without an ATC code | `LOCAL:drug:<slug>` | `LOCAL:drug:aztreonam-avibactam` |
| `DrugClass` | lower-case slug with hyphens | `carbapenem` |
| `Pathogen` | `NCBITaxon:<taxid>` | `NCBITaxon:573` (*K. pneumoniae*) |
| `Mechanism` | CARD ARO accession of the gene family or mechanism | `ARO:3000059` |
| `Mechanism` without an ARO term | `LOCAL:mech:<slug>` | `LOCAL:mech:porin-loss` |
| `Gene` | CARD ARO accession | `ARO:3002312` |
| `Guideline` | slug ending in the year | `who-aware-book-2022` |
| `Recommendation` | `REC:<guideline id>:<3-digit number>` | `REC:who-aware-book-2022:014` |
| `Passage` | `<source doc id>:<section slug>:<number>` | `who-aware-book-2022:sepsis-adults:3` |
| `SurveillanceStat` | `GLASS:<ISO3>:<year>:<pathogen id>:<drug or class id>` | `GLASS:IND:2022:NCBITaxon:573:J01DH02` |

Slugs use lower-case ASCII letters, digits and hyphens only.

## 3. File conventions

- CSV: UTF-8, comma-separated, header row, values quoted when they contain commas.
- Multi-valued cells use `|` as the separator.
- Booleans are `true` or `false`.
- JSONL: one JSON object per line, UTF-8.

## 4. Seed and curated files (hand-maintained)

### `schema/scope.yaml`

```yaml
pathogens:
  - id: NCBITaxon:573
    name: Klebsiella pneumoniae
    gram_stain: negative
mechanisms:
  - id: ARO:3000059
    name: KPC beta-lactamase
    type: carbapenemase        # carbapenemase | esbl | ampc | target-modification | efflux | porin-loss | other
    ambler_class: A            # A | B | C | D | "" when not a beta-lactamase
drug_classes:
  - id: carbapenem
    name: Carbapenems
    family: carbapenem         # broader group for class-level questions (D29)
drugs:
  - id: J01DH02
    name: meropenem
    class_id: carbapenem
    aware_group: Watch         # Access | Watch | Reserve | Unclassified
    id_verified: false
```

- `id_verified: true` means: for a drug, the ATC code is confirmed on the WHOCC index and the drug has the same group in AWaRe 2025; for a mechanism, the accession exists in the CARD ontology; for a pathogen, the taxonomy ID matches NCBI.
- `class_id` and `id_verified` are not node properties. The loader turns `class_id` into an `IN_CLASS` edge and drops `id_verified`.
- One `Drug` node per ATC code. Where AWaRe gives IV and oral forms different groups under one code, the node takes the IV group.

### `schema/phenotypes.csv`

`acronym,pathogen_id,mechanism_ids,class_family,notes`

Phenotype acronyms that imply more than a pathogen, such as `MRSA`, `CRKP`, `CRAB`. `mechanism_ids` is `|`-separated and may be empty; `class_family` is the resistant class family and may be empty.

### `schema/synonyms.csv`

`entity_type,entity_id,canonical_name,synonym,synonym_type`

- `entity_type`: `Drug`, `DrugClass`, `ClassFamily`, `Pathogen`, `Mechanism`, `Gene`. For `ClassFamily`, `entity_id` is a `family` value from `scope.yaml`, such as `carbapenem`.
- `synonym_type`: `canonical`, `abbreviation`, `brand`, `variant`. Synonyms of type `abbreviation` are matched case-sensitively; all others case-insensitively.
- One row per synonym. The canonical name is also a row, with `synonym_type` = `canonical`.

### `schema/class_overrides.csv`

`drug_id,drug_name,class_id,class_name,reason`

### `data/curated/*.csv`

All four files end with the columns `source,needs_review,notes`.

| File | Leading columns |
|---|---|
| `pathogen_mechanism.csv` | `pathogen_id,pathogen_name,mechanism_id,mechanism_name` |
| `mechanism_class.csv` | `mechanism_id,mechanism_name,class_id,class_name` |
| `mechanism_inactivates_drug.csv` | `mechanism_id,mechanism_name,drug_id,drug_name` |
| `intrinsic_resistance.csv` | `pathogen_id,pathogen_name,class_id,class_name` |

### `data/curated/recommendations_curated.csv` (wave 2)

`rec_id,guideline_id,pathogen_id,mechanism_id,drug_ids,regimen_type,base_drug_ids,susceptible_only,infection_site,line_of_therapy,patient_group,text,caveat,source_section,source_page`

- `base_drug_ids`: `|`-separated base drugs of a base-plus-partner regimen, or empty (D40).
- `susceptible_only`: `true` when the recommendation applies only to susceptible organisms, else `false` (D40).
- `caveat`: the sentence an answer must show with this recommendation, or empty (D34, D40).

- `mechanism_id` is empty when the guideline does not name a mechanism, and may hold several `|`-separated IDs for co-producing mechanisms (D33).
- `regimen_type`: `single` (one drug), `combination` (all drugs together), `any-of` (alternatives, judged one by one). Stored on the `Recommendation` node.
- `drug_ids` is `|`-separated.
- `line_of_therapy`: `first`, `second`, `alternative`, `last-resort`.
- `text` is a short paraphrase of the recommendation, not a long quotation.

## 5. Raw data layout

Everything downloaded goes under `data/raw/<source>/`, where source is one of `aware`, `card`, `glass`, `guidelines`, `taxonomy`, `pubmed`. `data/raw/manifest.json` lists every file with its URL, retrieval date, size and SHA-256.

## 6. Processed files (written by the pipeline)

All under `data/processed/`.

| File | Shape |
|---|---|
| `nodes_<Label>.csv` | `id` plus that label's properties, as in ARCHITECTURE.md section 5.1 |
| `edges_<TYPE>.csv` | `start_id,start_label,end_id,end_label,source_id,method,confidence,evidence_passage_id` plus any extra properties |
| `passages.jsonl` | `{"id", "text", "source_doc", "section", "page", "n_words", "printed_page", "is_table", "heading"}`; `page` and `printed_page` are null for abstracts; `text` includes a 30-word overlap with the previous passage |
| `mentions.jsonl` | `{"passage_id", "start", "end", "surface", "entity_type"}`, including candidates that were not linked |
| `mentions_linked.jsonl` | the mention fields plus `{"entity_id", "match_type", "score"}`, and optionally `canonical_name` and phenotype keys. `score` is 1.0 exact, 0.97 normalised, 0.93 phenotype, at most 0.95 fuzzy |
| `unlinked.csv` | `surface,entity_type,count,example_passage_id` |
| `recommendations_extracted.jsonl` | one `RecommendationExtraction` object per line |
| `load_report.json` | counts of nodes and edges loaded and rejected, with reasons |

Edge provenance values:

- `source_id`: a `Guideline` id, or one of `card`, `who-aware-2023`, `who-aware-2025`, `glass`, `curated-seed`, `pubmed`. AWaRe groups come from `who-aware-2025`.
- GLASS reports *Acinetobacter* only as "Acinetobacter spp.". Those statistics link to `NCBITaxon:470` and their `ABOUT_PATHOGEN` edge carries `reported_taxon: "Acinetobacter spp."`. GLASS has no *P. aeruginosa* data.
- `method`: `curated`, `rule` or `llm`.
- `confidence`: a number from 0 to 1; `1.0` for curated edges.
- `evidence_passage_id`: a `Passage` id, or empty.
- `evidence_sources`: optional, `|`-separated reference tags from the curated files' `source` column (D36).

## 7. Module interfaces

| Module | Owner task | Public interface |
|---|---|---|
| `pipeline/config.py` | T00 | Constants listed in section 1 |
| `pipeline/models.py` | T01 | Pydantic models `Pathogen`, `Mechanism`, `Gene`, `Drug`, `DrugClass`, `Recommendation`, `Guideline`, `SurveillanceStat`, `Passage`, `Edge`, `RecommendationExtraction`; registries `NODE_MODELS` (label → model) and `EDGE_TYPES` (type → allowed `(start_label, end_label)` pairs) |
| `pipeline/validate.py` | T01 | `validate_nodes(label, rows)`, `validate_edges(rel_type, rows, known_ids)`, both returning a `ValidationReport`; CLI `python -m pipeline.validate <dir>` |
| `pipeline/graph_db.py` | T01 | `get_driver()`, `ping()`, `apply_constraints(driver)`, `merge_nodes(driver, label, rows)`, `merge_edges(driver, rel_type, rows)` |
| `pipeline/download.py` | T02 | CLI `python -m pipeline.download [--only <sources>] [--force]` |
| `eval/metrics.py` | T04 | `precision_at_k`, `recall_at_k`, `reciprocal_rank`, `average_precision`, `ndcg_at_k`, `set_prf`, `accuracy`, `aggregate` |
| `pipeline/link.py` | T07 | `EntityLinker.link(text) -> list[LinkedMention]`, `EntityLinker.resolve(surface, entity_type=None) -> LinkedEntity or None` |
| `retrieval/` | T10–T14 | `answer(question, mode="hybrid", k=10) -> dict` (in `retrieval/answer.py`) with keys `question`, `mode`, `intent`, `entities`, `answers`, `other_active`, `paths`, `passages`, `answer_text`, `declined`, `decline_reason`, `disclaimer`, plus `cypher`, `empty_reason`, `note`, `timing_s`; `mode` is one of `bm25`, `dense`, `bm25_dense`, `graph`, `hybrid`. In `alternatives` answers the same drug appears once per mechanism group, so de-duplicate by `id` before scoring (D44). CLI `python -m retrieval.answer "<question>" --mode hybrid` |

### Validation and loading behaviour (`pipeline/validate.py`, `pipeline/graph_db.py`)

- `ValidationReport.accepted` holds normalised dicts (from `Model.to_row()`), ready to pass to `merge_nodes` or `merge_edges`. Blank CSV cells count as missing; list fields split on `|`.
- Pass `known_ids` to `validate_edges` as a mapping of label to a set of IDs.
- `merge_nodes` returns `{"rows", "nodes_created", "properties_set"}`. `merge_edges` returns `{"rows", "merged", "missing_endpoints", "relationships_created"}`; edges with missing endpoints are skipped and counted, never created. Load nodes before edges.
- **One edge per `(start, type, end)`.** The validator rejects a second row for the same pair. When several sources support the same fact, the loader keeps one row, chosen in the order `curated`, then `rule`, then `llm`, and further evidence is represented by `Passage` nodes linked with `SUPPORTS` or `MENTIONS`.
- A new `source_id` value needs a change to the list in section 6.
- `SurveillanceStat` links to a drug with `ABOUT_DRUG` or to a drug class with `ABOUT_CLASS`, matching the last part of its ID.

### Metric behaviour (`eval/metrics.py`)

- Import with `from eval.metrics import ...`.
- A ranked list is de-duplicated before ranks are assigned: `["a", "a", "b"]` is scored as `["a", "b"]`. Retrieval code should still return each ID once.
- `ndcg_at_k` accepts a mapping of ID to grade, or a collection of IDs treated as grade 1. Negative grades raise `ValueError`.
- `aggregate` requires every per-query dict to have the same metric names, and raises `ValueError` otherwise.

### Retrieval interfaces (wave 3)

All three modules return plain dataclasses defined in `retrieval/types.py` (owned by T12, which writes it first; T10 and T11 import from it and may ask for fields in their handoffs).

**`retrieval/parser.py` (T12)**: `parse(question: str) -> ParsedQuery`

| Field | Type | Meaning |
|---|---|---|
| `question` | `str` | The input |
| `intent` | `str` | `alternatives`, `why_restricted`, `mechanism_lookup`, `recommendation_lookup`, `drug_profile`, `surveillance`, `decline`, or `unknown` |
| `pathogen_ids`, `mechanism_ids`, `drug_ids`, `class_ids` | `list[str]` | Canonical IDs found or implied (phenotype acronyms add their mechanisms) |
| `class_families` | `list[str]` | Families named in the question, such as `carbapenem` |
| `country` | `str or None` | ISO 3 code, for surveillance |
| `year` | `int or None` | For surveillance |
| `infection_site` | `str or None` | Free text if the question names one |
| `decline_reason` | `str or None` | Set when `intent` is `decline` |
| `mentions` | `list` | The `LinkedMention` objects from the linker |

**`retrieval/graph_search.py` (T10)**: `graph_search(parsed: ParsedQuery) -> GraphResult`

| Field | Type | Meaning |
|---|---|---|
| `answers` | `list[Answer]` | Each `Answer` has `id`, `label`, `name`, `group` (for example the mechanism name, or empty), `aware_group`, `recommendation_ids`, `caveats` (list of strings), `score` |
| `paths` | `list[Path]` | Each `Path` is an ordered list of steps `{node_id, node_label, node_name, rel_type, rel_props}` from the question's entities to one answer, with the relationship's provenance in `rel_props` |
| `entity_ids` | `list[str]` | Every node ID on any path, for graph-linked passage retrieval |
| `cypher` | `list[str]` | The queries run, for display |
| `empty_reason` | `str or None` | Why there is no answer, when there is none |

**`retrieval/text_search.py` (T11)**: `search(query: str, mode: str, k: int = 10, entity_ids: list[str] | None = None) -> list[PassageHit]`

- `mode` is `bm25`, `dense` or `bm25_dense` (reciprocal rank fusion of the two, k = 60).
- `entity_ids`, when given, restricts results to passages that mention at least one of those entities.
- `PassageHit` has `passage_id`, `score`, `rank`, `text`, `source_doc`, `section`, `page`.
- `passages_for_entities(entity_ids: list[str], k: int) -> list[PassageHit]` returns passages linked to the entities through `MENTIONS` or `SUPPORTS`, most-connected first.

**Behaviour notes recorded after wave 3**

- `Path` keeps its steps in `Path.steps` and names its answer in `Path.answer_id`. Each step also has `direction` (`out` or `in`) and `from_node_id`, because a guideline step attaches to the recommendation rather than to the previous drug. Derived steps (`rel_type` `NOT_EXCLUDED`, or a `HAS_MECHANISM` the question asserts) have `rel_props.method` `derived`.
- `ParsedQuery.mentions` may include mentions with `match_type` `uppercase` (D37). Ambiguous phenotypes are narrowed to the species the question names.
- `graph_search` and `parse` take optional `driver` and `linker` arguments for tests.
- `bm25` may return fewer than `k` hits. The `passages_for_entities` score is the number of distinct matching entities.
- The index in `data/processed/index/` is generated and not committed. Rebuild it with `python -m retrieval.build_index` whenever `passages.jsonl` changes; loading raises if it is stale.
- `recommendations_extracted.jsonl` holds canonical names, not IDs, for pathogen, mechanisms (`|`-joined) and drugs.
- Intent `unknown` uses text retrieval only; intent `decline` shows `decline_reason` and runs no retrieval.

## 8. Graph schema

The node labels, relationship types and their properties are defined in [ARCHITECTURE.md](ARCHITECTURE.md) section 5.1. Do not add labels, relationship types or properties without a request to the orchestrator.

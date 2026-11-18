# Handoff: T05 Structured loaders and core graph build

- **Model:** Sonnet 5.5
- **Status:** complete, except that the final `python -m pipeline.load --clear` was blocked (see "Not done or not verified")
- **Date:** 2026-11-18

## What was built

`pipeline/build_core.py` writes the core graph as 7 `nodes_*.csv` and 9 `edges_*.csv` files in `data/processed/` from the seed data, AWaRe 2025, CARD and GLASS. `pipeline/load.py` is a generic loader: it validates every `nodes_*.csv` and `edges_*.csv` in a folder, loads nodes then edges, and writes `load_report.json`. The core graph is loaded in the shared Neo4j (15,103 nodes, 29,956 relationships, 0 rejected rows). The acceptance query (milestone M2) returns three different drug sets that match `REVIEW_NOTES.md` section 3.

## Files created or changed

| Path | What it is |
|---|---|
| `pipeline/build_core.py` | `build_core(out_dir)`, CLI `python -m pipeline.build_core`; also `check_aware`, `build_card_genes`, `build_glass`, `read_glass_map` |
| `pipeline/load.py` | `load_directory(dir, driver, clear, report_path, acceptance)`, `dedupe_edges`, `ACCEPTANCE_QUERY`, CLI `python -m pipeline.load [--clear] [--dir D]` |
| `schema/glass_map.csv` | `glass_name,target_label,target_id`: 25 mapped GLASS names, 5 deliberately unmapped (blank target) |
| `data/processed/nodes_*.csv`, `edges_*.csv` | The 16 core files (counts below) |
| `data/processed/load_report.json` | Per-file accepted, rejected, duplicates merged, relationships created, plus the acceptance result |
| `tests/test_build_core.py` | 16 tests, no database (the build goes to a temp folder) |
| `tests/test_load.py` | 8 tests: 4 unit, 4 against Neo4j with run-unique IDs (skip if unreachable) |

## How to run and check it

```bash
.venv/Scripts/python -m pipeline.build_core
.venv/Scripts/python -m pipeline.validate data/processed
.venv/Scripts/python -m pipeline.load --clear
.venv/Scripts/python -m pytest tests
```

Later tasks only drop their `nodes_<Label>.csv` and `edges_<TYPE>.csv` files (CONTRACTS section 6) into `data/processed/` and run `python -m pipeline.load`. Unknown file names are reported under `file_problems`, not fatal. The exit status is 1 when any row was rejected, an endpoint was missing or a file was a problem.

## Test result

`322 passed in 7.56s` for `.venv/Scripts/python -m pytest tests`, Neo4j running, no skips, no failures (my two files: 24 tests).

## What I found

### Counts (as built and as loaded; they are equal)

| Node label | Count |
|---|---|
| Pathogen | 5 |
| Mechanism | 12 |
| Gene | 282 |
| Drug | 49 |
| DrugClass | 32 |
| Guideline | 3 |
| SurveillanceStat | 14,720 |

| Relationship | Count |
|---|---|
| HAS_MECHANISM | 26 |
| ENCODES | 282 |
| CONFERS_RESISTANCE_TO | 67 |
| INACTIVATES | 36 |
| INTRINSICALLY_RESISTANT_TO | 56 |
| IN_CLASS | 49 |
| ABOUT_PATHOGEN | 14,720 |
| ABOUT_DRUG | 11,778 |
| ABOUT_CLASS | 2,942 |

`load_report.json`: 0 rejected rows, 0 duplicate edges, 0 missing endpoints, 0 file problems.

### AWaRe 2025 cross-check

All 49 drugs checked: 48 match `scope.yaml`, **0 mismatches**, and 1 (`J01CG30` sulbactam-durlobactam) is absent from AWaRe and `Unclassified` in scope, which is consistent. Matching is by ATC code; when several AWaRe rows share a code the row with the same normalised name wins, then the `_IV` row (so fosfomycin and minocycline take the IV group, as the contract says). The `\xa0`, `not assigned` and route-suffix quirks are handled. `aware_group` is never overwritten; the `scope.yaml` values are used.

### CARD genes

1,400 alleles qualify (their AMR gene family is one of the 11 `ARO:` mechanisms and one of their sequences has the exact NCBI taxon ID of an in-scope pathogen). That is above 1,000, so the rule is **keep alleles named in `PMID.tsv`**: **282 genes**. Per family: CTX-M 69, PDC 56, CMY 37, MCR 30, VIM 28, KPC 23, NDM 14, 16S RMTase 10, OXA-48-like 8, OXA-23-like 5, mecA/PBP2 2. `ENCODES` has `source_id` `card`, `method` `rule`, confidence 1.0. The OprD mechanism (`LOCAL:`) has no genes.

### GLASS

- Blood only; `PERCENTAGERESISTANCE` rows with `n_tested` from `INTERPRETABLEAST`. The file has 233,306 rows; 16,317 (country, year, pathogen, antibiotic) keys; **14,720 statistics written**.
- Mapping coverage: 30 GLASS antibiotic names; **25 mapped** (16 to drugs, 9 to classes), **5 unmapped and skipped**: Cefoxitin 442 keys, Methicillin 545, Oxacillin 367, Doripenem 167, Penicillins 76 (1,597 keys in total). None of these drugs is in `scope.yaml` (oxacillin and methicillin are not the in-scope cloxacillin or flucloxacillin; "Penicillins" fits no single class).
- De-duplication: the key is (year, country, pathogen, antibiotic); the blank-resistance-group row is kept, and keys that exist only with a group use the first group alphabetically. 40 keys had different values between group rows (the blank-group value was used).
- Statistics per pathogen: *E. coli* 6,142, *K. pneumoniae* 5,481, *Acinetobacter* 2,974, *S. aureus* 123, *P. aeruginosa* 0. Acinetobacter statistics link to `NCBITaxon:470` and their `ABOUT_PATHOGEN` edge has `reported_taxon` = `Acinetobacter spp.` (D30).
- Class-level mappings that lose detail: `Carbapenems` maps to `carbapenem`, while ertapenem sits in `carbapenem-group-1` (same family). `Third-generation cephalosporins` maps to `cephalosporin-3rd-gen`, so it does not cover the antipseudomonal class. A reviewer may want to change these in `schema/glass_map.csv`.
- Spot check against the raw file: `GLASS:IND:2018:NCBITaxon:573:J01DH02` has 55.159038014 % (T02 handoff), and a test asserts it.

### Edge properties

Curated edges have `source_id` `curated-seed`, `method` `curated`, confidence 1.0, and extra properties `needs_review` (a boolean in Neo4j: the loader turns `true`/`false` in extra edge columns into booleans) and `notes`. `IN_CLASS` edges come from `scope.yaml` `class_id` with the same provenance and no extras. CARD and GLASS edges use `method` `rule`, confidence 1.0.

### Acceptance query (M2)

```cypher
MATCH (p:Pathogen {id: $pathogen})-[:HAS_MECHANISM]->(m:Mechanism)
WHERE m.id IN $mechanisms          // KPC ARO:3000059, NDM ARO:3000057, OXA-48-like ARO:3007721
MATCH (d:Drug)-[:IN_CLASS]->(c:DrugClass)
WHERE NOT (p)-[:INTRINSICALLY_RESISTANT_TO]->(c)
  AND NOT (m)-[:CONFERS_RESISTANCE_TO]->(c)
  AND NOT (m)-[:INACTIVATES]->(d)
RETURN m.id AS mechanism_id, m.name AS mechanism, collect(d.name) AS drugs_not_excluded
ORDER BY m.id
```

with `$pathogen` = `NCBITaxon:573`. Output from the live database. Every mechanism also keeps the same 16 non-beta-lactams (gentamicin, amikacin, tobramycin, plazomicin, ciprofloxacin, levofloxacin, moxifloxacin, colistin, polymyxin B, doxycycline, minocycline, eravacycline, tigecycline, fosfomycin, sulfamethoxazole-trimethoprim, nitrofurantoin):

| Mechanism | Drugs left | Beta-lactams left |
|---|---|---|
| NDM (ARO:3000057) | 19 | aztreonam, aztreonam-avibactam, cefiderocol |
| KPC (ARO:3000059) | 21 | aztreonam-avibactam, cefiderocol, ceftazidime-avibactam, imipenem-cilastatin-relebactam, meropenem-vaborbactam |
| OXA-48-like (ARO:3007721) | 27 | aztreonam, aztreonam-avibactam, cefazolin, cefepime, cefiderocol, cefotaxime, ceftaroline fosamil, ceftazidime, ceftazidime-avibactam, ceftriaxone, cefuroxime |

These equal the three sets in `REVIEW_NOTES.md` section 3 exactly. `tests/test_build_core.py::test_worked_example_sets_match_review_notes` computes the same sets from the built edge files, and `tests/test_load.py` checks the query on a small graph. `load_directory` also runs the query and stores the result in `load_report.json` under `acceptance_crkp`.

## Deviations from the brief or contracts

- **CARD and GLASS edges use `method` `rule`** (not `curated`): they are derived by code from a database, not written by hand.
- **`ENCODES` is limited to alleles named in `PMID.tsv`** (282 of 1,400), as the brief allows above 1,000.
- `build_core` prints its build report (AWaRe mismatches, CARD rule, GLASS coverage) to stdout only; I did not add a report file because it is not in the file list.
- The curated files' `source` column (for example `CARD|IDSA-AMR-GN-2024`) is **not** carried onto the edges; the brief lists only `needs_review` and `notes` as extra properties.

## Not done or not verified

- **The brief's final step, `python -m pipeline.load --clear` on the shared database, was not run.** The tool permission check refused the `--clear` command, and I did not try to get around it. I ran `python -m pipeline.build_core` and then `python -m pipeline.load` (no `--clear`) instead, which merges the same files. The database held nothing else: the node and relationship counts in it equal the file counts exactly, so the result matches a clean load. Please run `python -m pipeline.load --clear` once yourself if you want that exact command on record; the report then says `cleared: true`.
- Passage, Recommendation and mention files from other wave 2 tasks were not present when I ran, so loading them is covered only by the unit tests and the mini-graph tests, not by a real file.
- GLASS urine specimens and the `PERCENTAGERESISTANCELOWER/UPPER` rows are not loaded (blood and the point estimate only, as briefed).

## Requests to orchestrator

1. **Edge `source` tags:** if explanations should show the evidence tags from the curated files (`CARD`, `IDSA-AMR-GN-2024`, `EUCAST-ERP-v1.2-2023`, `unverified`), the architecture needs an edge property such as `evidence_sources`; today only `notes` carries them.
2. **GLASS class mapping:** decide whether `Carbapenems` should link to `carbapenem` only (current) or be expanded through `family` (D29) in answers. No change needed for the current data.
3. **For T10:** the acceptance query above works for one mechanism at a time. A union of exclusions over several mechanisms needs the exclusion tests applied to each mechanism of the list (for example `NONE(m IN mechs WHERE ...)`).

## Follow-up (2026-11-18, after orchestrator review: D32, D33, D35, D36)

Built and validated only; **nothing was loaded into Neo4j** (the database still holds the earlier core graph). `python -m pipeline.validate data/processed`: 24 files, 52,601 rows accepted, 0 rejected. `.venv/Scripts/python -m pytest tests`: `466 passed` (includes other sessions' tests).

**Changes**

- `pipeline/build_core.py` reads `data/curated/recommendations_curated.csv` by column name and writes `nodes_Recommendation.csv`, `edges_FOR_PATHOGEN.csv`, `edges_FOR_MECHANISM.csv`, `edges_RECOMMENDS.csv`, `edges_FROM.csv` and `edges_SUPPORTS.csv`. `mechanism_id` may hold several `|`-separated IDs (one `FOR_MECHANISM` edge each). `regimen_type` is read if present, else inferred (`single` for one drug, `any-of` otherwise); all 80 rows had it, so nothing was inferred.
- `SUPPORTS` (`Passage` to `Recommendation`, `method` `rule`, `source_id` the guideline id): passages of the same `source_doc` (= guideline id) whose `page` equals `source_page` (confidence 1.0). `source_page` is the PDF page, which is what `passages.jsonl` calls `page`. If that page has no passage, the passages on the nearest earlier page are used (confidence 0.7; 9 recommendations). When the cited section starts with a number (for example `10.4.5`), passages with the same heading number are preferred. Every recommendation has at least one passage. Only passage IDs present in `nodes_Passage.csv` are linked.
- `pipeline/models.py`: `RegimenType` enum and optional `Recommendation.regimen_type`; `tests/test_models.py` has two new tests (130 pass).
- D36: the four curated resistance edge files carry `evidence_sources` (the row's `source`, `|`-separated).
- D35: `schema/glass_map.csv` maps `Methicillin` to class `antistaphylococcal-penicillin` and `Oxacillin` to drug `J01CF04`. `Carbapenems` stays `carbapenem`.

**New counts** (changed or new only; the rest are as above)

| Item | Count |
|---|---|
| Recommendation nodes | 80 (regimen types: single 42, combination 17, any-of 21) |
| FOR_PATHOGEN / FROM | 80 / 80 |
| FOR_MECHANISM | 49 |
| RECOMMENDS | 172 |
| SUPPORTS | 196 |
| SurveillanceStat nodes | 15,265 (was 14,720) |
| ABOUT_PATHOGEN | 15,265 |
| ABOUT_DRUG | 11,778 (unchanged) |
| ABOUT_CLASS | 3,487 (was 2,942; +545 from Methicillin) |

GLASS mapping coverage is now 26 of 30 names mapped to something in scope (Methicillin added), 3 unmapped (Cefoxitin 442 keys, Doripenem 167, Penicillins 76) and **1 mapped but skipped: Oxacillin (367 keys)**.

**Problem for the orchestrator:** `schema/scope.yaml` has no oxacillin. `J01CF04` is not a drug node, so the 367 Oxacillin statistics would be dangling edges. The build skips them and counts them in its report (`glass_targets_not_in_scope`) instead of writing them. Once `J01CF04` is added to `scope.yaml` (and its AWaRe group checked), re-running `python -m pipeline.build_core` picks them up with no code change. I did not edit `scope.yaml`.

**Not verified:** loading the new files into Neo4j (not allowed in this follow-up); the new `SUPPORTS` page matching was checked on counts and document names, not by reading each linked passage.

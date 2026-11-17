# Handoff: T03 Domain seed data: scope, synonyms, resistance facts

- **Model:** Opus 5.5
- **Status:** complete
- **Date:** 2026-11-18

## What was built

Hand-curated seed data for the AMR-Navigator graph: 5 pathogens, 12 resistance mechanisms (CARD gene families), 32 reasoning drug classes and 49 drugs. On top of that, 185 curated resistance-fact rows, each with a source and a `needs_review` flag, and a 383-row synonym dictionary. All drug ATC codes were confirmed on the WHOCC index, and all AWaRe groups and CARD family accessions against the downloaded files. A test file checks consistency and runs the carbapenem-resistant *K. pneumoniae* worked example, which gives three different answers for KPC, NDM and OXA-48-like.

## Files created or changed

| Path | What it is |
|---|---|
| `schema/scope.yaml` | Pathogens, mechanisms, drug classes, drugs, with `id_verified` on pathogens, mechanisms and drugs |
| `schema/synonyms.csv` | Synonym dictionary for all entities (canonical, abbreviation, brand, variant) |
| `schema/class_overrides.csv` | Drugs whose reasoning class differs from ATC/AWaRe, with reasons |
| `data/curated/pathogen_mechanism.csv` | Which mechanisms occur in which pathogen |
| `data/curated/mechanism_class.csv` | Class-level resistance (`CONFERS_RESISTANCE_TO`) |
| `data/curated/mechanism_inactivates_drug.csv` | Drug-level exceptions (`INACTIVATES`) |
| `data/curated/intrinsic_resistance.csv` | Intrinsic resistance per pathogen and class |
| `data/curated/REVIEW_NOTES.md` | Source tags, modelling choices, **worked example (section 3)**, rows for review grouped by reviewer question, simplifications |
| `tests/test_seed_data.py` | 32 consistency, worked-example and source cross-check tests |

### Counts

| File | Rows | `needs_review = true` | `source = unverified` |
|---|---|---|---|
| `scope.yaml` | 5 pathogens, 12 mechanisms, 32 classes, 49 drugs | – | – |
| `synonyms.csv` | 383 (Drug 184, Mechanism 86, DrugClass 75, Pathogen 38; 98 canonical, 152 variant, 75 abbreviation, 58 brand) | – | – |
| `class_overrides.csv` | 13 | – | – |
| `pathogen_mechanism.csv` | 26 | 8 | 1 |
| `mechanism_class.csv` | 67 | 5 | 2 |
| `mechanism_inactivates_drug.csv` | 36 | 9 | 4 |
| `intrinsic_resistance.csv` | 56 | 21 | 17 |
| **Curated total** | **185** | **43** | **24** |

### IDs still unverified (`id_verified: false`)

- `LOCAL:mech:oprd-porin-loss` (OprD porin loss). CARD has no family term; the gene-level variant term ARO:3003686 exists.
- `J01CG30` (sulbactam-durlobactam). The ATC code is confirmed on the WHOCC index, but the drug is in neither the AWaRe 2023 nor the 2025 list, so `aware_group` is `Unclassified`.

All 5 NCBI taxon IDs, the other 11 mechanism AROs and the other 48 drug ATC codes are verified.

## How to run and check it

```bash
.venv/Scripts/python -m pytest tests/test_seed_data.py -v
```

```bash
.venv/Scripts/python -m pytest tests
```

## Test result

`293 passed in 2.67s` for the full suite (`.venv/Scripts/python -m pytest tests`, 2026-11-18). That includes 32 tests in `tests/test_seed_data.py`; the two that cross-check against `data/raw/` ran, they were not skipped. No failures in any file.

## What I found

- **Worked example (acceptance test):** for CRKP, the beta-lactams left are:
  - KPC: ceftazidime-avibactam, meropenem-vaborbactam, imipenem-cilastatin-relebactam, cefiderocol, aztreonam-avibactam.
  - NDM: aztreonam, aztreonam-avibactam, cefiderocol.
  - OXA-48-like: ceftazidime-avibactam, cefiderocol, aztreonam-avibactam, aztreonam, and the 1st–4th generation cephalosporins plus ceftaroline.

  All three also keep the same 16 non-beta-lactams. Full lists and caveats are in `REVIEW_NOTES.md` section 3; `test_worked_example_crkp_by_mechanism` computes the lists from the files. Two single-mechanism results need a caveat in the answer text (T14): aztreonam for NDM, and the cephalosporins for OXA-48-like, because co-produced ESBLs usually defeat them.
- **Modelling rule worth knowing for T05/T10:** beta-lactamases never have class-level edges to beta-lactam/inhibitor combination classes. Every combination failure is a drug-level `INACTIVATES` row whose `notes` give the inhibitor-specific reason (tested). Exclusions are therefore: classes from `INTRINSICALLY_RESISTANT_TO` ∪ classes from `CONFERS_RESISTANCE_TO` ∪ drugs from `INACTIVATES`.
- **The loader must take `class_id` from `scope.yaml`, not from the AWaRe class column.** AWaRe 2025 puts ceftazidime-avibactam under third-generation cephalosporins and ceftolozane-tazobactam under fifth-generation.
- **AWaRe files:** the per-group sheets `Access`, `Watch` and `Reserve` have their header row (`Antibiotic, Class, ATC code, Category, ...`) a few rows down, not in row 1. Some ATC codes appear twice with a route suffix (`Fosfomycin_IV` Reserve / `Fosfomycin_oral` Watch, `Minocycline_IV` / `Minocycline_oral`). The 2025 file also lists `Amoxicillin/sulbactam` under J01CR02.
- **CARD files:** `ontology/aro.tsv` does **not** contain the AMR gene-family terms; `ontology/aro.obo` (v4.0.2, dated 2026-08-11) does. `aro_index.tsv` gives gene → family → drug classes.
- **AWaRe changes made during reconciliation:** aztreonam-avibactam Unclassified → Reserve (new in 2025), minocycline Watch → Reserve (IV form). The other 46 drugs matched as first written.

## Deviations from the brief or contracts

- **32 drug classes instead of about 15.** Each split is needed for correct class-level reasoning. Examples: ertapenem vs meropenem for *P. aeruginosa* intrinsic resistance, ceftazidime vs ceftriaxone, amoxicillin-clavulanate vs ampicillin-sulbactam for *A. baumannii*. The reasons are in `REVIEW_NOTES.md` section 2.1 and `class_overrides.csv`.
- **12 mechanisms**, the top of the 10–12 range; 49 drugs.
- **`id_verified` added to pathogens and mechanisms** in `scope.yaml`, not only to drugs, as the brief asks for every unconfirmed ID.
- **One `INACTIVATES` row is a stewardship exclusion, not true inactivation:** CTX-M → piperacillin-tazobactam (MERINO/IDSA). It is flagged for review.
- **Routes:** minocycline and fosfomycin have one node each with the IV AWaRe group, because the contract keys drugs on ATC code.

## Not done or not verified

- The IDSA 2024 and EUCAST documents were cited from knowledge; I did not open them in this task. CARD facts were checked against the downloaded files. The 43 `needs_review` rows are listed for an expert in `REVIEW_NOTES.md` section 4.
- No `Gene` entities (for example mecA ARO:3000617, KPC-2 ARO:3002312) are in scope; mechanisms are gene families only.
- Multi-mechanism reasoning (for example NDM + CTX-M) is supported by the data but not tested.

## Requests to orchestrator

1. **Clarify `id_verified` in CONTRACTS.md §4.** It currently says "true once checked against the WHO AWaRe file". I used: an ATC code confirmed on WHOCC *and* found with the same group in AWaRe 2025; for mechanisms, the accession found in the CARD ontology.
2. **Add `who-aware-2025` to the edge `source_id` values** (CONTRACTS.md §6 and `DATASET_SOURCE_IDS` in `pipeline/models.py`). The 2025 file is the one reconciled against.
3. **scope.yaml carries fields that are not node properties** (`class_id`, `id_verified`). `pipeline/models.py` uses `extra="forbid"`, so the T05 loader must strip them, or turn `class_id` into an `IN_CLASS` edge, before validating.
4. **T07/T12:** match `abbreviation` synonyms case-sensitively, and give the parser the phenotype-acronym table in `REVIEW_NOTES.md` §2.5. MRSA, CRKP, CRAB and the others imply a mechanism or resistance class that the synonym file alone does not carry.
5. **T10:** support the union of exclusions over several mechanisms, and give the single-mechanism caveats in REVIEW_NOTES §3 to T14.
6. Optional: a class grouping (for example "third-generation cephalosporins" covering both 3rd-gen classes), so class-level questions can expand. This would need a schema decision. *(Decided as D29: class families; see Follow-up.)*

## Follow-up (2026-11-18, after orchestrator review, D29)

- **`schema/scope.yaml`:** every one of the 32 `drug_classes` now has a `family` slug. There are 16 families: `penicillin`, `beta-lactam-bli`, `cephalosporin`, `carbapenem`, `monobactam`, `aminoglycoside`, `fluoroquinolone`, `polymyxin`, `tetracycline`, `phosphonic`, `glycopeptide`, `oxazolidinone`, `lipopeptide`, `sulfonamide-trimethoprim`, `nitrofuran`, `lincosamide`.
- **Key choice:** `carbapenem-bli` (and every other beta-lactam/inhibitor combination class) is in its own family `beta-lactam-bli`, not in `carbapenem`, `cephalosporin` or `monobactam`. That way "carbapenem resistance" excludes only `carbapenem` and `carbapenem-group-1` and keeps meropenem-vaborbactam and imipenem-relebactam for KPC. Cefiderocol and ceftaroline are in `cephalosporin`, so no phenotype uses `cephalosporin` as its resistant family. The reasons are in `REVIEW_NOTES.md` §2.6.
- **`schema/synonyms.csv`:** 44 `ClassFamily` rows added (one canonical per family, plus plurals, variants and the abbreviations `BL/BLI`, `BLBLI`, `FQ`), for 427 rows in total.
- **`schema/phenotypes.csv` (new):** 14 rows for MRSA, MSSA, CRKP, KPC-Kp, CREC, CRE (×2), ESBL-E (×2), ESBL-EC, ESBL-KP, CRAB, CRPA and DTR-PA. A phenotype that spans two species has one row per species. `mechanism_ids` is filled only where the acronym names the mechanism; the CR- rows have `class_family = carbapenem`.
- **`tests/test_seed_data.py`:** 4 new tests (36 in total). They check that every class has a valid family, that the carbapenem and `beta-lactam-bli` families contain the right classes, that every family has exactly one canonical synonym and a consistent name, that a DrugClass and a ClassFamily synonym sharing a string agree, and that phenotypes reference IDs, mechanisms recorded for the pathogen, and families in scope. The existing synonym test now accepts `ClassFamily` rows.
- **Test result:** `298 passed in 3.49s` (`.venv/Scripts/python -m pytest tests`).
- The resistance-fact CSVs are unchanged, so the worked example and the `needs_review` counts (43 of 185) are unchanged.

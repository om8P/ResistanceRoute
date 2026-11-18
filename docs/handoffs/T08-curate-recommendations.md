# Handoff: T08 Curate guideline recommendations

- **Model:** Opus 5.5
- **Status:** complete
- **Date:** 2026-11-18

## What was built

80 recommendations curated by hand from the three guideline PDFs. I read each source page myself with `pdfplumber`, not from memory. Every row uses in-scope IDs and has a PDF page number. 35 rows are tied to a carbapenemase: NDM, KPC, OXA-48-like or VIM. I checked every mechanism row against the T03 resistance facts using the T03 exclusion rule. That gives **11 conflicting rows (17 drug-level conflicts)**; each is listed with its supporting page in `RECOMMENDATION_NOTES.md` §3, which also has an assessment and options for the orchestrator. A test file of 24 tests checks the format, the IDs, the pages and the paraphrase rules, and that every conflict is documented.

## Files created or changed

| Path | What it is |
|---|---|
| `data/curated/recommendations_curated.csv` | 80 recommendations, columns exactly as CONTRACTS.md §4 |
| `data/curated/RECOMMENDATION_NOTES.md` | Selection method, column conventions, conflicts (§3), disagreements between guidelines (§4), out-of-scope drugs (§5), rows left out (§6), uncertain rows (§7) |
| `tests/test_recommendations_curated.py` | 24 tests |

### Counts

| By guideline | Rows |
|---|---|
| `icmr-cr-gram-negative-2022` | 39 |
| `who-aware-book-2022` | 25 |
| `icmr-treatment-guidelines-2019` | 16 |

| By pathogen | Rows |
|---|---|
| *K. pneumoniae* (NCBITaxon:573) | 26 |
| *E. coli* (NCBITaxon:562) | 23 |
| *S. aureus* (NCBITaxon:1280) | 11 |
| *A. baumannii* (NCBITaxon:470) | 10 |
| *P. aeruginosa* (NCBITaxon:287) | 10 |

| By mechanism | Rows |
|---|---|
| NDM (ARO:3000057) | 13 (2 of them for NDM + OXA-48 co-producers) |
| KPC (ARO:3000059) | 12 |
| OXA-48-like (ARO:3007721) | 9 |
| VIM (ARO:3000021) | 1 |
| mecA/PBP2a (ARO:3009312), from "MRSA" | 9 |
| CTX-M (ARO:3000016), from "ESBL" | 3 |
| none | 33 |

`line_of_therapy` counts: `first` 27, `alternative` 34, `last-resort` 17, `second` 2. 38 rows list more than one drug. The longest paraphrase is 36 words.

**Conflicts: 11 rows, 17 drug-level conflicts.**
- 5 rows recommend ceftazidime-avibactam plus aztreonam for NDM, while NDM `INACTIVATES` ceftazidime-avibactam. This is expected: the combination works because aztreonam is stable to the MBL and avibactam protects it from co-produced serine beta-lactamases.
- 6 rows name high-dose meropenem or imipenem as a polymyxin partner for KPC, NDM and OXA-48 (ICMR 2022 Table 4, "if MIC < 16"), while those mechanisms `CONFERS_RESISTANCE_TO` the carbapenem class.
- None comes from intrinsic resistance.

## How to run and check it

```bash
.venv/Scripts/python -m pytest tests/test_recommendations_curated.py -v
```

```bash
.venv/Scripts/python -m pytest tests
```

## Test result

`346 passed in 9.48s` for the full suite (`.venv/Scripts/python -m pytest tests`, 2026-11-18). That includes the 24 new tests; the 3 PDF page-count tests ran and were not skipped. There were no failures in any file.

## What I found

- **ICMR 2022 Table 4** (PDF p16–17) has four mechanism lines: MBL (e.g. NDM), MBL + OXA-48, OXA-48-like and KPC. Each has the same three "other options": polymyxin plus another active agent or high-dose carbapenem, tigecycline (not alone for bloodstream infection or pneumonia), and aminoglycosides (uncomplicated UTI or source-controlled infection). The first choice is ceftazidime-avibactam plus aztreonam for the two MBL lines and ceftazidime-avibactam alone for OXA-48 and KPC. **ICMR 2022 names no newer agent** (no meropenem-vaborbactam, imipenem-relebactam or cefiderocol). Those KPC and MBL options come only from the WHO Reserve chapters.
- Page layout of the ICMR 2022 section: CRAB is on p17–18 (sulbactam-based therapy; combine at least two agents for moderate to severe infection) and CRPA on p18. Table 5 (by syndrome) is on p18–19, and Tables 6 and 7 (durations, doses) on p19.
- **WHO Table 41.1** (PDF p596–597) is a per-mechanism activity table for the Reserve antibiotics (ESBL, KPC, MBL, AmpC, OXA-48, non-fermenters). It agrees with the T03 facts, for example ceftazidime-avibactam "–" for MBL and meropenem-vaborbactam "–" for MBL and OXA-48. T09 or T10 could use it as a passage that supports `INACTIVATES` edges.
- The Reserve pages extract with words run together (`ce/g246derocol`, `laboratory-con rmed`); T06 already expects this.
- **ICMR 2019 Table 10.6** (PDF p113–114) extracts as interleaved columns. Two rows built from it are flagged in the notes §7.
- For T14: the ICMR 2022 MBL first choice (ceftazidime-avibactam plus aztreonam) needs a synergy test, and "ceftazidime-avibactam alone" needs in-vitro susceptibility testing. Both conditions are in the row `text`.
- **Environment:** for part of this session `.venv/Scripts/python` failed with "Unable to create process" (the venv launcher could not start the WindowsApps base interpreter). Meanwhile I ran the base `python3.11.exe` with `.venv/Lib/site-packages` on `PYTHONPATH`, with nothing installed. By the end the venv launcher worked again, and the final test run above used it.

## Deviations from the brief or contracts

- **`mechanism_id` for MRSA and ESBL.** The brief says to set a mechanism only when the guideline names one. I set mecA for "MRSA" (9 rows) and CTX-M for "ESBL" (3 rows), following `schema/phenotypes.csv` and the synonym rules, so that MRSA questions do not return MSSA rows. These 12 rows can be cleared if the orchestrator disagrees (notes §2).
- **"MBL"** is mapped to NDM for Enterobacterales and to VIM for *P. aeruginosa* (4 WHO rows).
- **The NDM + OXA-48 line uses `mechanism_id` = NDM**, with co-production recorded in `patient_group`, because the contract has one mechanism per row (2 rows).
- **`drug_ids` holds alternatives as well as combination partners.** The `text` says which. There is no contract field for the difference.
- **80 rows is the upper limit.** Some candidates were left out (notes §6).

## Not done or not verified

- No pharmacist or clinician has reviewed the rows. The 9 uncertain items are in notes §7, including the extraction-layout doubt on ICMR 2019 p114.
- ICMR 2022 pages 5–14 (diagnosis) were not used for rows, and the WHO septic arthritis chapter was only skimmed.
- I did not edit T03's files. The 11 conflicts are waiting for the orchestrator's decision.

## Requests to orchestrator

1. **Decide on the 6 carbapenem-partner conflicts** (notes §3.2). I recommend option (a): keep the rows and have T14 show the carbapenem with "only if the MIC is low, in combination".
2. **Tell T10 and T14 how to treat combination rows** where one partner is excluded but the regimen is designed around it: ceftazidime-avibactam plus aztreonam for NDM (notes §3.1). A rule that only checks drug by drug will mark these 5 rows as contradicted.
3. **Contract gap:** add a way to tell a combination from a list of alternatives, for example a `regimen_type` column (`single`, `combination`, `any-of`). Also consider letting `mechanism_id` hold several `|`-separated values, for co-producers such as NDM + OXA-48. T13 should know that `drug_ids` currently mixes alternatives and combination partners.
4. **Confirm the MRSA → mecA and ESBL → CTX-M `mechanism_id` interpretation** (12 rows).
5. **Scope candidates** seen often in the guidelines: cefoperazone-sulbactam (in both ICMR documents, repeatedly) and standalone sulbactam (ICMR 2022 CRAB).

## Follow-up (2026-11-18, after orchestrator review, D33–D34)

- **`regimen_type` column** added after `drug_ids` (CONTRACTS §4): `single` 42, `any-of` 21, `combination` 17. Tested rules: `single` rows have exactly one drug, the others at least two, and every ceftazidime-avibactam plus aztreonam row is `combination`.
- **9 of the 17 combination rows are "base drug plus one of several partners"**: the six Table 4 polymyxin rows, :027, CRAB :031 and CRPA :039. Under D34 a mechanism-free `combination` row is dropped when any partner is excluded, so :027, :031 and :039 would drop the whole option because of one excluded partner. T10 may want to judge the partners of such rows one by one; see notes §2.
- **Co-producers:** REC:icmr-cr-gram-negative-2022:013 and :026 now have `mechanism_id` = `ARO:3000057|ARO:3007721`, and the `patient_group` workaround is removed. The conflict check takes the union of both mechanisms' exclusions. The count is unchanged: **11 rows, 17 drug-level conflicts**.
- **Caveats:** `RECOMMENDATION_NOTES.md` §3.3 has a one-sentence caveat for each of the 11 conflict rows, for T14 to show. §3.2 records D34 option (a).
- **Tests:** 28 in `tests/test_recommendations_curated.py` (4 new). They cover the new column, multi-valued `mechanism_id` (in scope, not repeated, each recorded for the pathogen), co-producer rows, the union exclusion rule, and that every conflict row has a caveat.
- **Test result:** `1 failed, 458 passed in 25.95s` (`.venv/Scripts/python -m pytest tests`). All 28 T08 tests pass. The failure is in `tests/test_build_core.py::test_glass_map_targets_exist_in_scope`, which is not a T08 file: the GLASS map sends "Oxacillin" to `J01CF04`, which is not in `schema/scope.yaml`. That looks tied to D35 and to work in progress in another session.

## Follow-up 2 (2026-11-18, D40)

- **Three columns added** in the CONTRACTS §4 order: `base_drug_ids` and `susceptible_only` after `regimen_type`, and `caveat` after `text`.
- **`caveat`:** filled for exactly the 11 conflict rows, empty elsewhere. The CSV is now the source; the table in `RECOMMENDATION_NOTES.md` §3.3 is a copy for reading, and a test keeps the two identical.
- **`base_drug_ids`:** 10 rows, all `combination`.
  - Polymyxins (colistin, polymyxin B): the six Table 4 polymyxin rows, ICMR 2022 :027 and :039.
  - Ampicillin-sulbactam: CRAB :031.
  - Fosfomycin: ICMR 2019 :009.
  - Empty for fixed pairs (ceftazidime-avibactam plus aztreonam, colistin plus imipenem-cilastatin :007), single drugs and `any-of` lists.
- **`susceptible_only`:** `true` for 6 rows: ICMR 2019 :003 (MSSA) and :006 (carbapenem-susceptible *E. coli*), and WHO :019, :020, :021 and :023 (empiric first-choice regimens for non-resistant infection). The rest are `false`.
  - Rows that only require in-vitro susceptibility to the recommended drug, in an organism that is otherwise resistant, stay `false`. Examples: ICMR 2022 :028 and :035–:037, WHO :008 and :013. These are recommendations for resistant organisms, and D41 must not drop them. The definition is in notes §2.
- **Tests:** 33 in `tests/test_recommendations_curated.py` (5 new, 1 replaced). They check that base drugs are a proper subset of `drug_ids` and only on combination rows, that fixed pairs have no base drugs, that `susceptible_only` is boolean and never on a mechanism row, that every conflict row has a caveat and no other row does, and that the notes table matches the CSV.
- **Test result:** `1 failed, 670 passed in 43.37s` (`.venv/Scripts/python -m pytest tests`). All 33 T08 tests pass.
  - The failure is `tests/test_graph_search.py::test_susceptible_only_rows_are_dropped_for_resistant_organisms` (T10). That test simulates the flag on WHO :020 "until T08's file has it" and first asserts that the row is still returned. With the real column set to `true`, its "before" state is empty.
  - The fix belongs to T10: drop the simulation and assert directly that :020 is absent for KPC *E. coli* and present for a plain *E. coli* lookup.
  - The earlier `test_build_core` oxacillin failure no longer appears.

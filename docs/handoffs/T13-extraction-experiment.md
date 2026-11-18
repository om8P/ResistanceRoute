# Handoff: T13 Recommendation extraction experiment

- **Model:** Sonnet 5.5
- **Status:** complete
- **Date:** 2026-11-18

## What was built

A rule-based extractor (`pipeline/extract.py`) that reads the 1,109 guideline passages (the 319 PubMed abstracts are skipped) and writes **172 `RecommendationExtraction` objects** to `data/processed/recommendations_extracted.jsonl`, each with `passage_id`, `method` `rule` and a confidence. `eval/extraction_eval.py` scores them against the 80 curated recommendations and writes `eval/results/extraction_eval.json`. **The headline strict score is F1 0.13 overall (P 0.10, R 0.21). On the guideline with clean text (ICMR 2022) it is F1 0.37 strict and 0.69 lenient; on the ICMR 2019 development set it is 0.00.** Nothing is loaded into the graph; no LLM was used (Q2).

## Files created or changed

| Path | What it is |
|---|---|
| `pipeline/extract.py` | `Extractor` (rules, `extract_all`, `resolve_ids`), `load_passages`, `write_jsonl`, CLI `python -m pipeline.extract` |
| `data/processed/recommendations_extracted.jsonl` | 172 extractions, one JSON object per line (generated, not committed per D19) |
| `eval/extraction_eval.py` | Matching, scoring with `eval.metrics.set_prf`, error analysis, CLI `python -m eval.extraction_eval` |
| `eval/results/extraction_eval.json` | Scores overall, per guideline, per field, a confidence sweep, and the 10 + 10 error samples with their causes |
| `tests/test_extract.py` | 30 tests |

## How to run and check it

```bash
.venv/Scripts/python -m pipeline.extract
```

```bash
.venv/Scripts/python -m eval.extraction_eval
```

```bash
.venv/Scripts/python -m pytest tests/test_extract.py
```

The first writes the jsonl (a few seconds once the linker is built); the second prints one line per guideline and writes the JSON.

## Test result

`633 passed, 2 warnings in 33.77s` for `.venv/Scripts/python -m pytest tests` (2026-11-18, whole suite). No failures. The two warnings are the `typer`/`click` deprecations. The tests that read the real output files skip if the files are missing.

## How the extractor works

Entities come from `EntityLinker.link`. A drug class in the text ("aminoglycosides", "polymyxins", "carbapenems") is expanded to the in-scope drugs of that class, and "Enterobacterales"/"Enterobacteriaceae" stand for *K. pneumoniae* and *E. coli*. Output fields hold canonical names (the model's fields are free text); `Extractor.resolve_ids` links them back to IDs with the linker, and the evaluation uses that.

| Rule | Reads | Confidence |
|---|---|---|
| `table4` | ICMR 2022 Table 4 rows (T06's one-sentence-per-mechanism text): one extraction for "1st choice" and one per lettered "other option", for each in-scope Enterobacterales species | 0.95 |
| `trigger` | Sentences, bullets and "First Choice / Second Choice" blocks with a trigger phrase, at least one drug and a pathogen. Triggers: reserve / last resort (`last-resort`); second choice / second line (`second`); first choice / drug of choice / treatment of choice (`first`); alternative / other options / options include / may be used (`alternative`); preferred / recommended / suggested (`first`) | 0.8 for the specific phrases, 0.6 "preferred" and "alternative", 0.45 "recommended"; minus 0.15 when the pathogen is carried from an earlier sentence, 0.25 when from the heading, 0.1 for more than four drugs |
| `segment` | ICMR 2019 style tables ("Etiology / Suggested regimens / Preferred / Alternative"): cut the passage at each pathogen mention and take the drugs up to the next one, no line of therapy | 0.3 |

Guards added while developing on ICMR 2019: a unit of more than 60 words is a flattened table fragment and is left to `segment`; sentences with "do not use / not recommended / avoid" are skipped; a drug followed by "-resistant" or preceded by "resistant to" is not a recommended drug; a mechanism implied by a phenotype (MRSA gives mecA) belongs only to that pathogen; a stated mechanism is kept only if `data/curated/pathogen_mechanism.csv` lists it for that pathogen. Overlapping passages repeat about 30 words, so an extraction with the same document, pathogen, mechanism and drug set on the same or the next page is kept once.

## Scores

**Matching** is one-to-one and greedy (highest confidence first). **Strict** is the match in the brief: same guideline, pathogen, set of mechanisms and set of drugs, source page within ±1. **Lenient** is the same but the drug sets only need a Jaccard overlap of 0.5. Precision, recall and F1 come from `eval.metrics.set_prf` over the matched curated IDs.

| Set | Extracted / gold | Strict TP: P / R / F1 | Lenient TP: P / R / F1 |
|---|---|---|---|
| **All three guidelines** | 172 / 80 | 17: 0.10 / 0.21 / **0.13** | 30: 0.17 / 0.38 / **0.24** |
| ICMR 2019, **development set** | 30 / 16 | 0: 0.00 / 0.00 / **0.00** | 0: 0.00 / 0.00 / **0.00** |
| ICMR 2022, held out | 42 / 39 | 15: 0.36 / 0.38 / **0.37** | 28: 0.67 / 0.72 / **0.69** |
| WHO AWaRe book, held out | 100 / 25 | 2: 0.02 / 0.08 / **0.03** | 2: 0.02 / 0.08 / **0.03** |
| ICMR 2022 + WHO together | 142 / 64 | 17: 0.12 / 0.27 / **0.17** | 30: 0.21 / 0.47 / **0.29** |

**Per field** (a field is scored alone: guideline and page ±1 plus that field; P / R / F1):

| Field | All | ICMR 2019 (dev) | ICMR 2022 | WHO |
|---|---|---|---|---|
| Pathogen | 0.28 / 0.60 / 0.38 | 0.23 / 0.44 / 0.30 | 0.74 / 0.79 / 0.77 | 0.10 / 0.40 / 0.16 |
| Mechanism | 0.24 / 0.51 / 0.33 | 0.23 / 0.44 / 0.30 | 0.71 / 0.77 / 0.74 | 0.04 / 0.16 / 0.06 |
| Drug set (exact) | 0.16 / 0.35 / 0.22 | 0.03 / 0.06 / 0.04 | 0.38 / 0.41 / 0.40 | 0.11 / 0.44 / 0.18 |
| Line of therapy | 0.28 / 0.60 / 0.38 | 0.10 / 0.19 / 0.13 | 0.83 / 0.90 / 0.86 | 0.10 / 0.40 / 0.16 |

**Confidence works as a ranking.** Strict F1 by minimum confidence: 0.13 (all 172), 0.16 (≥ 0.5, 123 extractions), 0.21 (≥ 0.8, 65), **0.25 at ≥ 0.9 (32 extractions, P 0.44, R 0.18)**. Lenient F1 at ≥ 0.9 is 0.46. Extractions by line: first 69, alternative 53, second 24, last-resort 20, none 6 (the `segment` rule).

**How honest the split is.** I iterated on the ICMR 2019 passages only, and those changes are the guards listed above. ICMR 2022 and WHO were scored once, after the rules were frozen, and I changed nothing afterwards. Two things limit that claim: I had already read the Table 4 passages and a few WHO passages while designing the rules (and the Table 4 rule is the one the brief asked for), and the first run of the whole corpus showed all three scores together before I fixed the guards. I wrote no pattern for an individual curated row. The development set turned out to be the worst of the three, so the held-out numbers are not flattered by tuning.

## Error analysis (strict matching; the 10 + 10 samples are in the JSON)

155 extractions are false positives and 63 curated rows are false negatives. The cause is assigned by comparing each error with the rows of the other kind on the same page (`_diagnose` in `eval/extraction_eval.py`); I then read the sampled passages for the explanations.

**False positives (155) by cause:**

| Cause | Count |
|---|---|
| No curated row on that page (may be a real recommendation that was not curated) | 102 |
| Wrong pathogen for that page | 15 |
| Extra drug in the extraction | 15 |
| Wrong or missing mechanism | 10 |
| Different drugs | 9 |
| Drug sets partly overlap | 3 |
| A drug is missing | 1 |

**Ten false positives:**

1. WHO p183, *second* (0.65): "Second choice ... Amoxicillin (oral) ... Doxycycline" extracted for *P. aeruginosa*. No curated row on the page. The pathogen was carried over from an earlier unit that belongs to another infection.
2. WHO p521, *first* (0.45): "dicloxacillin and flucloxacillin are preferred options within the class" gives flucloxacillin for *K. pneumoniae* and *E. coli*. The pathogen comes from carried context and is wrong.
3. WHO p521, *alternative* (0.6): "In neonates, cefotaxime is recommended ... Clindamycin is still an acceptable option when community-acquired MRSA is suspected" gives cefotaxime and clindamycin as one MRSA row. Two statements merged in one unit (different drugs).
4. WHO p599, *last-resort* (0.65): "cefiderocol is one of the few Reserve antibiotics with reported activity against metallo-beta-lactamases" for *K. pneumoniae* has no mechanism, so it does not match the NDM row. "Metallo-beta-lactamases" is not in the synonym list.
5. WHO p211, *first* (0.45): "these would be the preferred options whenever possible ... cloxacillin ... flucloxacillin". No curated row on the page; plausibly a real recommendation that was not curated.
6. ICMR 2019 p113, Table 10.6, *alternative* (0.5), *E. coli*: five drugs (imipenem, ceftriaxone, cefotaxime, meropenem, piperacillin-tazobactam). Extra drugs: the interleaved columns put the drugs of several table cells into one segment.
7. ICMR 2019 p113, same table, *K. pneumoniae*: the same five drugs; the drug sets only partly overlap the curated rows.
8. ICMR 2019 p111, `segment` (0.3), *S. aureus* with five drugs (cloxacillin, cefazolin, vancomycin, teicoplanin, daptomycin): extra drugs from a table fragment that holds several rows.
9. ICMR 2022 p15, *first* (0.45), *K. pneumoniae*: "Polymyxins (colistin is preferred over polymyxin B for UTI) as a single agent" gives colistin and polymyxin B. No curated row has exactly this set; the nearest curated rows on p15 hold larger drug sets (drug missing).
10. ICMR 2022 Table 4 "other option" rows: aminoglycosides expand to four drugs (gentamicin, amikacin, tobramycin, plazomicin), while the curated rows list two. Extra drugs. This is consistent with the gap between strict (15 matches) and lenient (28) on ICMR 2022.

**False negatives (63) by cause:**

| Cause | Count |
|---|---|
| Extraction has extra drugs (class expansion, merged table cells) | 16 |
| Wrong or missing pathogen | 13 |
| Wrong or missing mechanism | 12 |
| Nothing extracted on that page | 11 |
| Different drugs | 8 |
| Drug sets partly overlap | 2 |
| Extraction lacks a drug | 1 |

**Ten false negatives:**

1. ICMR 2022 :002 (NDM, *K. pneumoniae*, polymyxin + tigecycline + aminoglycoside + fosfomycin + carbapenem): extra drugs in the extraction (tobramycin, plazomicin from class expansion).
2. ICMR 2022 :004 (aminoglycosides for NDM): extra drugs, same reason.
3. ICMR 2022 :027 (carbapenemase unknown, polymyxin plus another agent): the only extraction on p15 for this pathogen is the single-agent polymyxin item, so the drug set is too small. The numbered items of that list ("2. Ceftazidime-avibactam alone ...", "3. Tigecycline ...") carry no trigger phrase.
3b. ICMR 2022 :028 (carbapenemase unknown, ceftazidime-avibactam alone): different drugs, same cause: a numbered list item without a trigger word.
4. ICMR 2022 :030 and :031 (CRAB, sulbactam first and the combination): no *A. baumannii* extraction exists. The CRAB list sits under "Treatment Options" followed by "1. High dose sulbactam ...", with no trigger word, so no unit qualifies.
5. WHO :001 and :002 (cefiderocol for NDM): mechanism missing. The text says "metallo-beta-lactamase" (not linked), and the curator mapped MBL to NDM.
6. WHO :010 (linezolid for MRSA): nothing extracted. "Linezolid is used for MRSA infection in selected situations" has no trigger phrase.
7. ICMR 2019 :007 (carbapenem-resistant *Klebsiella*, colistin plus imipenem): the segment for *Klebsiella* holds drugs of neighbouring cells, so the sets only partly overlap. I did not read further into why.

The 16 ICMR 2019 rows as a whole: 7 get the right pathogen on the right page, and none gets the right drug set.

**Grouped by root cause** (an error can have more than one):

1. **Broken table text (ICMR 2019, parts of the WHO infographics).** T06 documented that the ICMR 2019 tables are flattened column by column. Drugs of the "Preferred" and "Alternative" columns and of neighbouring rows are interleaved, so neither a trigger sentence nor a pathogen segment can recover the right drug set. This gives 0.00 strict and 0.00 lenient on the development set.
2. **Class expansion.** "Aminoglycosides" and "carbapenems" expand to every in-scope drug of the class; the curator listed fewer. This is my design choice. It is the most likely reason for the 13 rows that match leniently but not strictly on ICMR 2022 (I did not check each one).
3. **No trigger phrase.** Numbered-list items, "Treatment Options" lists and "is used for ..." sentences recommend drugs without any of the listed triggers.
4. **Pathogen and mechanism context.** The pathogen is often in a heading or an earlier sentence. Carrying it forward is right for some units and wrong for many (WHO p183, p521). "MBL" / "metallo-beta-lactamase" is not linked at all.
5. **Uncurated recommendations count as false positives.** 102 of 155 false positives are on pages with no curated row. The gold file has 80 rows chosen for coverage (T08 notes §6), so some of these are real recommendations and true precision is higher than 0.10. I did not label them.

## What would improve the scores

- **Table text first.** Re-extract the ICMR 2019 tables with `pdfplumber` table or word-position extraction instead of `extract_text`, so each row stays whole (a T06 follow-up). That is the only route to a score on the development set.
- **Class expansion limited to the drugs the guideline names.** Likely to turn many of the 13 lenient-only ICMR 2022 matches into strict ones. I did not apply it after seeing the scores, to keep the numbers honest.
- **List introductions as context.** Treat items under a "Treatment Options" heading ("1.", "2.", ...) as alternatives, and add "is used for" / "alone" style triggers. This targets the ICMR 2022 false negatives (:027, :028, :030, :031) and WHO :010.
- **Link "metallo-beta-lactamase" / "MBL"** (to NDM for Enterobacterales, as the curator did, or to a mechanism class) so Reserve-chapter sentences get a mechanism.
- **Do not carry a pathogen across a topic change** (WHO p183, p521), and require the pathogen inside the unit for AWaRe passages.
- **Use the confidence threshold.** At ≥ 0.9 precision is 0.44 with 32 extractions: a usable "suggested recommendations to review" list.
- **LLM extraction (Q2)** could read broken table text and list items. I did not try it, so I cannot say how much it would gain.

## Deviations from the brief or contracts

- **Names in the output, IDs in the evaluation.** `RecommendationExtraction` has free-text fields and forbids extra ones, so the jsonl holds canonical names (several mechanisms joined with `|`). `Extractor.resolve_ids` links them to IDs through `EntityLinker.resolve`.
- **Strict and lenient both reported.** The brief names one match rule; I report it as "strict" and add "lenient" (Jaccard ≥ 0.5 on the drug set) because the curator listed alternatives and combination partners together in `drug_ids`.
- **No `regimen_type`.** `RecommendationExtraction` has no such field, so the extractor does not tell a combination from an any-of list.
- **An extra row, "ICMR 2022 + WHO".** Those two were not used for tuning; the brief asked for all three plus the development set shown separately.

## Not done or not verified

- The 102 false positives on pages with no curated row were not labelled, so true precision is unknown.
- Error explanations come from reading the 20 sampled cases, not all 218 errors; the cause labels for the rest come from the automatic comparison only.
- Table 4 footnotes (`*`, `**`) are not read, so conditions such as "only if the MIC is low" are not captured (the model has no field for them).
- Only the five in-scope pathogens are extracted; `patient_group` and `infection_site` are left empty.
- The 13-row strict/lenient gap on ICMR 2022 is attributed to class expansion by inspection of examples, not by checking every row.

## Requests to orchestrator

1. **Decide whether T06 should re-extract the ICMR 2019 tables** with word positions (cells kept as rows). Without it, extraction on that guideline is not recoverable by rules.
2. **CONTRACTS §6 note:** `recommendations_extracted.jsonl` holds canonical names for pathogen, mechanism (joined with `|`) and drugs, not IDs, because the model is free text.
3. **For the report (T18):** use the strict score as the headline with the lenient score beside it, and say that the 80 curated rows are the gold, so uncurated true recommendations count as false positives.

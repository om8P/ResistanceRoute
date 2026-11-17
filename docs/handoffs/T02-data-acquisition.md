# Handoff: T02 Data acquisition and source inventory

- **Model:** Sonnet 5.5
- **Status:** complete
- **Date:** 2026-11-18 (data retrieved 2026-11-17)

## What was built

`pipeline/download.py` fetches all six sources into `data/raw/<source>/` (137 MB, 46 files), skips files already on disk, and keeps `data/raw/manifest.json` (URL, retrieval date, size, SHA-256 for every file). All six sources downloaded automatically; no manual download is needed. `data/SOURCES.md` has the URL, version, licence and method for each. Everything below was read from the files on disk. Three sources differ from the brief (see "Deviations"): GLASS has no *P. aeruginosa*, the ICMR "2022" PDF is a QR poster, and AWaRe 2025 is the latest edition.

## Files created or changed

| Path | What it is |
|---|---|
| `pipeline/download.py` | One function per source (`download_aware`, `_card`, `_glass`, `_guidelines`, `_taxonomy`, `_pubmed`), CLI `python -m pipeline.download [--only ...] [--force]`, manifest helpers |
| `tests/test_download.py` | 19 offline tests: hashing, skip logic, manifest, magic-byte check, rate limiter, archive path safety, parsers |
| `data/SOURCES.md` | Source URLs, versions, licences, files, automatic or manual |
| `data/raw/manifest.json` | 46 entries; matches the files on disk exactly (`.gitkeep` is not listed) |
| `data/raw/aware/` `card/` `glass/` `guidelines/` `taxonomy/` `pubmed/` | The data |

## How to run and check it

```bash
.venv/Scripts/python -m pipeline.download            # re-run: prints "skip" for every file
.venv/Scripts/python -m pipeline.download --only glass --force
.venv/Scripts/python -m pytest tests
```

## Test result

`290 passed in 9.25s` for the whole suite (`.venv/Scripts/python -m pytest tests`), run on 2026-11-18 after re-running the downloader (every file skipped, manifest 46 of 46 files). On 2026-11-17 one test in `tests/test_seed_data.py` (not mine) failed because `data/curated/REVIEW_NOTES.md` did not exist yet; it passes now.

## What I found

Paths are relative to `data/raw/`. Sample rows are real rows.

### Which AWaRe edition loaders should use

**Use the 2025 workbook** (`aware/WHO-AWaRe-classification-2025.xlsx`). It is the current edition (published 5 Sept 2025), has 268 antibiotics against 257 in 2023, a `Notes` column, and `Listed on EML/EMLc 2025`. The 2023 file is kept only as a cross-check and because CONTRACTS.md names `who-aware-2023` as an edge `source_id`. Neither file has a drug ID other than the ATC code, so `Drug.id` has to come from `ATC code` (see quirks). The WHO AWaRe book PDF (2022) predates both, so a drug's group in the book can differ from the workbook; the loader should take `aware_group` from the workbook.

### aware/WHO-AWaRe-classification-2025.xlsx

Sheets: `Title`, `Copyright & Disclaimers`, `Introduction` (text only), **`AWaRe classification 2025`** (the table to load), `Access`, `Watch`, `Reserve` (the same rows split by group, each with 2 to 4 text lines above the header), `Not recommended`, `24th EML 2025`, `10th EMLc 2025`.

Main sheet: title lines in rows 1 to 2, **header in row 4** (`pandas.read_excel(..., header=3)`), 268 data rows, columns `Antibiotic | Class | ATC code | Category | Listed on EML/EMLc 2025 | Notes`. `Category` counts: Watch 145, Access 93, Reserve 30. 39 distinct `Class` values (for example `Carbapenems`, `Third-generation-cephalosporins`, `Beta-lactam/beta-lactamase-inhibitor`, `Polymyxins`, `Glycopeptides`). The class names are hyphenated, capitalised and plural, so they need slugging and a mapping to the contract's slugs (`carbapenem`), which is what `schema/class_overrides.csv` is for.

Sample rows:

| Antibiotic | Class | ATC code | Category | Listed | Notes |
|---|---|---|---|---|---|
| Amikacin | Aminoglycosides | J01GB06 | Access | Yes | (blank) |
| Meropenem | Carbapenems | J01DH02 | Watch | Yes | (blank) |
| Ceftazidime/avibactam | Third-generation-cephalosporins | J01DD52 | Reserve | Yes | (blank) |

Quirks the loader must handle (all checked):

- **Trailing non-breaking space** (`\xa0`) on 2 ATC codes (`J01CA01` Ampicillin, `J01DI02` Ceftaroline-fosamil) and on one class (`Triazaacenaphthylenes`). Replace `\xa0` and strip.
- **`not assigned`** instead of an ATC code for Cefoselis and Micronomicin. These need `LOCAL:drug:<slug>` ids.
- **Route suffixes in the name**: 25 names end in `_IV` or `_oral` (for example `Colistin_IV` J01XB01 and `Colistin_oral` A07AA10, `Vancomycin_IV` J01XA01 and `Vancomycin_oral` A07AA09, `Fosfomycin_IV` Reserve and `Fosfomycin_oral` Watch, `Minocycline_IV` Reserve and `Minocycline_oral` Watch). Oral forms often have an `A07…` ATC code; CONTRACTS.md says to use the systemic `J01…` code. IV and oral fosfomycin and minocycline share one ATC code but have different AWaRe groups.
- **Duplicate ATC codes**: Amoxicillin/clavulanic-acid and Amoxicillin/sulbactam are both `J01CR02`; the fosfomycin and minocycline pairs above. 8 rows are involved.
- **Combinations are listed by name**, for example `Aztreonam/avibactam` J01DF51 (Reserve), `Meropenem/vaborbactam` J01DH52, `Imipenem/cilastatin/relebactam` J01DH56. In-scope drugs present: meropenem, imipenem/cilastatin, ertapenem, doripenem, ceftazidime, cefepime, ceftriaxone, cefazolin, cefiderocol, aztreonam, piperacillin/tazobactam, amikacin, gentamicin, ciprofloxacin, colistin, polymyxin B, tigecycline, linezolid, vancomycin, oxacillin, cloxacillin, sulfamethoxazole/trimethoprim.
- `Notes` is blank for 260 rows; the other 8 read like `*therapeutic alternative to cloxacillin`.
- `Not recommended` sheet: header in row 4 (`Antibiotic` only), 116 fixed-dose combinations in lower case, no ATC. Not a source of nodes.

### aware/WHO-AWaRe-classification-2023.xlsx

Same layout (sheets `AWaRe classification 2023`, `Access`, `Watch`, `Reserve`, `Not recommended`, `23rd EML 2023`, `9th EMLc 2023`), header in row 4, 257 data rows, but: the column is named `Category ` with a **trailing space**, the EML column is `Listed on EML/EMLc 2023`, there are three unnamed trailing columns (empty), and two Category values are `Watch ` with a trailing space (Access 87, Watch 139 + 2, Reserve 29). Sample: `Cefepime | Fourth-generation-cephalosporins | J01DE01 | Watch | No`.

### card/ (CARD v4.0.2, built 11 Aug 2026)

Tables (tab-separated, UTF-8, header row):

| File | Rows | Columns |
|---|---|---|
| `aro_index.tsv` | 6,463 (6,458 distinct ARO accessions) | `ARO Accession`, `CVTERM ID`, `Model Sequence ID`, `Model ID`, `Model Name`, `ARO Name`, `Protein Accession`, `DNA Accession`, `AMR Gene Family`, `Drug Class`, `Resistance Mechanism`, `CARD Short Name` |
| `aro_categories.tsv` | 685 | `ARO Category`, `ARO Accession`, `ARO Name` (595 AMR Gene Family, 78 Drug Class, 12 Resistance Mechanism) |
| `aro_categories_index.tsv` | 6,411 | `Protein Accession`, `DNA Accession`, `AMR Gene Family`, `Drug Class`, `Resistance Mechanism` (no ARO ids) |
| `PMID.tsv` | 4,408 | `ARO Accession`, `CVTERM ID`, `ARO Name`, `PMID`, `DOI`, `ISBN` (PMIDs `;`-separated) |
| `snps.txt` | 3,735 | `Accession`, `Name`, `Model Type`, `Parameter Type`, `Mutations`, `CARD Short Name`, `source`, `citation` |
| `shortname_antibiotics.tsv` | 81 | `AAC Abbreviation`, `Molecule` |
| `shortname_pathogens.tsv` | 98 | `Abbreviation`, `Pathogen` |
| `card.json` | 6,451 models | see below |
| `ontology/aro.tsv` | 6,501 | `Accession`, `Name`, `Description`, `ID`, `CARD Short Name` |
| `ontology/aro.obo` | 9,051 `[Term]` stanzas | OBO 1.2 |
| `ontology/ncbi_taxonomy.tsv`, `mo.tsv`, `ro.tsv` | 1,910 / 46 / small | `Accession`, `Name`, `Description`, `ID` |

FASTA files (`nucleotide_fasta_*`, `protein_fasta_*`, by model type) are sequences only; not needed for the graph.

Sample `aro_index.tsv` rows:

| ARO Accession | ARO Name | AMR Gene Family | Drug Class | Resistance Mechanism |
|---|---|---|---|---|
| ARO:3002523 | AAC(2')-Ia | AAC(2') | aminoglycoside antibiotic | antibiotic inactivation |
| ARO:3002312 | KPC-2 | KPC beta-lactamase | carbapenem;cephalosporin;monobactam;penicillin beta-lactam | antibiotic inactivation |
| ARO:3000589 | NDM-1 | NDM beta-lactamase | carbapenem;cephalosporin;penicillin beta-lactam | antibiotic inactivation |

**How a gene links to a mechanism and drug classes (checked for KPC and NDM):**

- **Gene = `ARO Accession`** of an allele, for example `ARO:3002312` KPC-2, `ARO:3002313` KPC-3, `ARO:3000589` NDM-1, `ARO:3001782` OXA-48, `ARO:3000617` mecA.
- **Gene family** (the contract's `Mechanism` id, for example `ARO:3000059`): `aro_index.tsv` gives only the *name* (`KPC beta-lactamase`); the accession is in `aro_categories.tsv` (`AMR Gene Family  ARO:3000059  KPC beta-lactamase`; NDM is `ARO:3000057`) or in `card.json`. The family cell can be `;`-joined when a gene has more than one family (41 of the 552 distinct family strings are multi-valued, for example `AAC(6');AAC(6')-Ib-cr`), so split on `;` before the lookup.
- **Drug classes**: `aro_index.tsv` `Drug Class` holds names, `;`-separated (4,096 rows are multi-valued). Accessions are in `aro_categories.tsv` (`carbapenem` is `ARO:0000020`, `penicillin beta-lactam` `ARO:3000008`, `cephalosporin` `ARO:0000032`, `monobactam` `ARO:0000004`). CARD's drug-class names are not the AWaRe class names (`penicillin beta-lactam`, `cephalosporin`, `fluoroquinolone antibiotic`), so a mapping to the project `DrugClass` slugs is needed.
- **Resistance mechanism** (a CARD category, not the contract's `type`): the `Resistance Mechanism` column has 8 values: antibiotic inactivation 5,254 rows, target alteration 638, efflux 333, target protection 176, target replacement 81, reduced permeability 30, resistance by absence 14, host-dependent nutrient acquisition 1. Accessions are in `aro_categories.tsv` (`antibiotic inactivation` is `ARO:0001004`, `antibiotic target replacement` `ARO:0001002`).
- **`card.json`** has the same links with accessions inline. Top-level keys are the model ids (`"2"` to `"8540"`) plus `_version` (`4.0.2`), `_comment`, `_timestamp`. Each model has `model_id`, `model_name`, `model_type`, `model_type_id`, `model_description`, `model_param`, `model_sequences`, `ARO_accession` (**without** the `ARO:` prefix, e.g. `"3002312"`), `ARO_id`, `ARO_name`, `CARD_short_name`, `ARO_description`, and `ARO_category`: a dict keyed by category cvterm id whose values have `category_aro_accession` (no prefix), `category_aro_name`, `category_aro_description`, `category_aro_class_name` (one of `AMR Gene Family`, `Drug Class`, `Resistance Mechanism`). KPC-3 (`model_id` 1153): family `KPC beta-lactamase` (3000059); drug classes monobactam, carbapenem, cephalosporin, penicillin beta-lactam; mechanism `antibiotic inactivation` (0001004). NDM-1 (783): family `NDM beta-lactamase` (3000057); carbapenem, cephalosporin, penicillin beta-lactam; `antibiotic inactivation`. 6,451 models: protein homolog 6,059, protein variant 239, rRNA gene variant 86, efflux pump meta-model 22, knockout 16, overexpression 15, gene cluster meta-model 14.
- **Gene to pathogen**: `model_sequences.sequence.<id>.NCBI_taxonomy` has `NCBI_taxonomy_id` and `NCBI_taxonomy_name` (strings). Models with a sequence from each pathogen: *K. pneumoniae* 704, *E. coli* 562, *A. baumannii* 737, *P. aeruginosa* 1,081, *S. aureus* 45. The KPC family has 231 models (203 from *K. pneumoniae*, 8 *E. coli*, 5 *P. aeruginosa*); NDM has 71 (37 *E. coli*, 17 *K. pneumoniae*, 3 *A. baumannii*, 2 *P. aeruginosa*).
- **Gene family to specific antibiotics** is only in `ontology/aro.obo`. A family term (`ARO:3000059`) has `is_a: ARO:3000078 ! class A beta-lactamase` and `relationship: confers_resistance_to_drug_class ARO:0000020 ! carbapenem` lines (565 of 578 family terms have such lines). Individual genes can have `relationship: confers_resistance_to_antibiotic ARO:0000073 ! meropenem` (4,558 such lines; NDM-1 lists ertapenem `ARO:0000070`, meropenem `ARO:0000073` and imipenem `ARO:3000170`; KPC-3 lists none). Antibiotic terms (`ARO:0000073` meropenem) have `is_a` to the drug class, synonyms and `xref` to `CHEBI`, `ChEMBL`, `PubChem`, `CAS`. **There is no ATC code anywhere in CARD**, so antibiotics must be matched to ATC by name through the AWaRe workbook (`aro.obo` names are lower case, for example `meropenem`).
- **Quirk**: CARD's drug-class curation is not always clinically sensible: the CTX-M-155 model lists `azole antibiotic` and `imidazole antibiotic` next to `cephalosporin`. Treat CARD class links as `needs_review` where a link looks odd.

### glass/

`glass_amr_pathogens.csv`: UTF-8 CSV, 233,306 rows, 21 columns: `IND_CODE, DIM_TIME, DIM_GEO_CODE_ISO3, DIM_GEO_CODE_M49, DIM_GEO_CODE_TYPE, DIM_1_CODE, DIM_MEMBER_1_CODE, DIM_2_CODE, DIM_MEMBER_2_CODE, DIM_3_CODE, DIM_MEMBER_3_CODE, DIM_4_CODE, DIM_MEMBER_4_CODE, DIM_5_CODE, DIM_MEMBER_5_CODE, VALUE_NUMERIC, VALUE_NUMERIC_LOWER, VALUE_NUMERIC_UPPER, VALUE_LABEL, VALUE_COMMENTS, OBSERVATION_STATUS`. Read with `dtype=str` and `keep_default_na=False`: empty cells are empty strings.

Meaning of the columns (the same in every row of this file): `DIM_TIME` year; `DIM_GEO_CODE_ISO3` country (ISO 3, matches the `GLASS:<ISO3>:...` id); `DIM_MEMBER_1_CODE` specimen (`BLOOD` or `URINE`); `DIM_MEMBER_2_CODE` pathogen; `DIM_MEMBER_3_CODE` antibiotic or class; `DIM_MEMBER_4_CODE` always `Total` (age group); `DIM_MEMBER_5_CODE` antibiotic group, empty in 112,890 rows. `VALUE_NUMERIC` is the value. `VALUE_NUMERIC_LOWER/UPPER`, `VALUE_LABEL`, `VALUE_COMMENTS` and `OBSERVATION_STATUS` are always empty; the confidence limits arrive as separate rows (`PERCENTAGERESISTANCELOWER`, `PERCENTAGERESISTANCEUPPER`).

`IND_CODE` values and row counts: `PERCENTAGERESISTANCE` 46,020 (resistant isolates as % of those with interpretable AST); `PERCENTAGERESISTANCELOWER` 46,020 and `PERCENTAGERESISTANCEUPPER` 46,020 (confidence limits); `RESISTANT` 47,623 (number of resistant isolates); `INTERPRETABLEAST` 47,623 (denominator). Checked: `PERCENTAGERESISTANCE` = `RESISTANT` / `INTERPRETABLEAST` x 100 (largest difference 5e-10) where all three exist; 819 `RESISTANT` rows have no percentage row.

Sample rows (`IND_CODE, year, ISO3, specimen, pathogen, antibiotic, group, VALUE_NUMERIC`):

| IND_CODE | Year | ISO3 | Specimen | Pathogen | Antibiotic | Group | Value |
|---|---|---|---|---|---|---|---|
| PERCENTAGERESISTANCE | 2018 | LBN | BLOOD | Escherichia coli | Imipenem | (blank) | 5.263157895 |
| PERCENTAGERESISTANCE | 2020 | IRN | BLOOD | Escherichia coli | Imipenem | Carbapenem resistance | 16.155988858 |
| PERCENTAGERESISTANCE | 2018 | IND | BLOOD | Klebsiella pneumoniae | Meropenem | Carbapenem resistance | 55.159038014 |

Coverage:

- **Pathogens**: *Escherichia coli* 99,281 rows, *Klebsiella pneumoniae* 95,416, *Acinetobacter spp.* 31,172 (genus level), *Staphylococcus aureus* 7,437. ***Pseudomonas aeruginosa* has no rows**: it is not a GLASS-AMR pathogen. *Acinetobacter* is not split to species.
- **Specimens**: blood for all four pathogens; urine only for *E. coli* and *K. pneumoniae*.
- **Years**: 2016 to 2023. Countries with data per year (`PERCENTAGERESISTANCE`): 2016 24, 2017 52, 2018 64, 2019 72, 2020 88, 2021 87, 2022 92, 2023 101. 108 countries in total.
- **India (`IND`) is included**: 840 `PERCENTAGERESISTANCE` rows, years 2017 to 2023, with 19 antibiotics or classes for *E. coli*, 17 for *K. pneumoniae*, 11 for *Acinetobacter* spp. and 4 for *S. aureus*. Example: *K. pneumoniae*, blood, meropenem: 55.2% (2018), 57.6% (2019), 57.4% (2020).
- **Antibiotics (30 names)**: Amikacin, Aminoglycosides, Ampicillin, Carbapenems, Cefepime, Cefotaxime, Cefoxitin, Ceftazidime, Ceftriaxone, Ciprofloxacin, Co-trimoxazole, Colistin, Doripenem, Ertapenem, Fluoroquinolones, Fourth-generation cephalosporins, Gentamicin, Imipenem, Levofloxacin, Meropenem, Methicillin, Minocycline, Oxacillin, Penicillins, Polymyxins, Second-generation cephalosporines (sic), Sulfonamides and trimethoprim, Tetracyclines, Third-generation cephalosporins, Tigecycline. They mix single drugs and classes, so the stat id's `<drug or class id>` needs a name-to-id map. `DIM_MEMBER_5_CODE` has 33 values (for example `Carbapenem resistance`, `Third-generation cephalosporin resistance`, `Methicillin resistance`) that name the resistance phenotype a drug row belongs to.
- **Duplicates**: 107,613 of 125,693 keys (indicator, year, country, specimen, pathogen, antibiotic) have two rows, one with a blank group and one with a group; 12,803 keys exist only with a group. Values agree except for 182 keys, so **include `DIM_MEMBER_5_CODE` in the key, or keep the blank-group row and add the group-only rows**.

`countries.csv`: 249 rows, columns `CODE_ISO_3, CODE_ISO_2, CODE_ISO_NUMERIC, CODE_WHO, NAME_SHORT_EN`; sample rows `IND,IN,356,IND,India` and `GHA,GH,288,GHA,Ghana`.

### guidelines/

**`who-aware-antibiotic-book-2022.pdf`**: 697 PDF pages, with a PDF outline (60 entries). **Printed page number = PDF page minus 16** (PDF p594 prints 578). Pages 2, 44, 310, 592, 643, 644 and 696 have no text; the median page has about 2,000 characters. The **Reserve chapters (PDF p598 to 642) extract with broken spacing and ligatures** (`Tr eatment`, `ce/g246derocol` for cefiderocol, names run together); T06 should expect to normalise text there. Table of contents with PDF pages:

| Section | PDF pages |
|---|---|
| Foreword, Acknowledgements, Acronyms, Glossary | 7 to 16 |
| 1 Introduction | 17 |
| 2 Improving the use of antibiotics with the AWaRe book | 21 |
| 3 Allergy to antibiotics | 36 |
| PRIMARY HEALTH CARE, chapters 4 to 23 (bronchitis, otitis media, pharyngitis, sinusitis, oral and dental, lymphadenitis, eye, trachoma, mild CAP, COPD, diarrhoea, enteric fever, mild skin infections, burns, wounds and bites, four STI chapters, **23 Lower urinary tract infection p294**) | 43 to 308 |
| HOSPITAL FACILITY, chapters 24 to 40 | 309 to 590 |
| RESERVE ANTIBIOTICS: 41 Overview p593, 42 Cefiderocol p598, 43 Ceftazidime+avibactam p605, 44 Fosfomycin IV p611, 45 Linezolid p617, 46 Meropenem+vaborbactam p622, 47 Plazomicin p627, 48 Polymyxin B and colistin p633 | 591 to 642 |
| DOSING GUIDANCE: 49 adults p645, 50 children p655 | 643 to 668 |
| References | 669 to 697 |

Hospital chapters: 24 Sepsis in adults p311; 25 Sepsis in neonates and children p335; 26 Meningitis p361; 27 Severe CAP p378; 28 Hospital-acquired pneumonia p397; 29 to 33 Intra-abdominal infections (cholecystitis p412, liver abscess p430, appendicitis p450, diverticulitis p470, C. difficile p480); 34 Upper urinary tract infection p490; 35 Osteomyelitis p505; 36 Septic arthritis p523; 37 Necrotizing fasciitis p539; 38 Pyomyositis p551; 39 Febrile neutropenia p561; 40 Surgical prophylaxis p578.

Where the five pathogens appear (counts of name or abbreviation mentions in the chapter, from the extracted text; Kp, Ec, Ab, Pa, Sa = the five pathogens, Sa includes MRSA and methicillin; CR = carbapenem-resistance terms; ESBL = ESBL terms):

| Chapter (PDF pages) | Kp | Ec | Ab | Pa | Sa | CR | ESBL |
|---|---|---|---|---|---|---|---|
| 23 Lower UTI (294-308) | 1 | 8 | 3 | 2 | 0 | 0 | 18 |
| 24 Sepsis adults (311-334) | 4 | 4 | 2 | 2 | 17 | 2 | 14 |
| 25 Sepsis neonates and children (335-360) | 19 | 21 | 7 | 0 | 45 | 10 | 17 |
| 28 Hospital-acquired pneumonia (397-411) | 3 | 0 | 3 | 16 | 14 | 1 | 3 |
| 30 Liver abscess (430-449) | 6 | 3 | 0 | 0 | 0 | 8 | 12 |
| 34 Upper UTI (490-504) | 2 | 8 | 2 | 2 | 3 | 5 | 16 |
| 35 Osteomyelitis (505-522) | 0 | 0 | 4 | 4 | 47 | 0 | 0 |
| 36 Septic arthritis (523-538) | 0 | 0 | 2 | 2 | 39 | 0 | 0 |
| 37 Necrotizing fasciitis (539-550) | 0 | 0 | 0 | 3 | 31 | 0 | 0 |
| 39 Febrile neutropenia (561-577) | 0 | 0 | 0 | 3 | 16 | 6 | 12 |
| 41 Reserve overview (593-597) | 2 | 0 | 5 | 5 | 0 | 19 | 3 |
| 42 Cefiderocol (598-604) | 2 | 0 | 11 | 9 | 0 | 38 | 5 |
| 43 Ceftazidime+avibactam (605-610) | 3 | 0 | 7 | 13 | 0 | 33 | 4 |
| 44 Fosfomycin IV (611-616) | 2 | 0 | 6 | 10 | 11 | 23 | 5 |
| 45 Linezolid (617-621) | 0 | 0 | 0 | 0 | 13 | 0 | 0 |
| 46 Meropenem+vaborbactam (622-626) | 5 | 0 | 4 | 4 | 0 | 37 | 4 |
| 47 Plazomicin (627-632) | 2 | 0 | 3 | 4 | 0 | 28 | 5 |
| 48 Polymyxin B and colistin (633-642) | 1 | 0 | 8 | 6 | 0 | 24 | 3 |

*S. aureus* and MRSA content is spread over the skin (16 to 18, 37, 38), bone and joint (35, 36) and sepsis chapters. Other chapters mention the pathogens only a few times. Totals over the book: Kp 63, Ec 81, Ab 75, Pa 113, Sa 436, carbapenem-resistance terms 266, ESBL 160. The Reserve chapters (41 to 48, PDF p593 to 642) are the main source for carbapenem-resistant *Klebsiella*, *Acinetobacter* and *Pseudomonas*. I read page 599 (cefiderocol) and page 594 and 313; the counts above come from extracted text, not from reading each chapter.

**`icmr-treatment-guidelines-2019.pdf`** (ICMR, *Treatment Guidelines for Antimicrobial Use in Common Syndromes*, 2nd edition 2019): 206 PDF pages, **no PDF outline**, text on every page. **Printed page = PDF page minus 5.** Contents (printed pages): 1 Introduction to antibiotic use p1; 2 Management of acute fever p5; 3 Sepsis p29; 4 Respiratory tract infections and community-acquired pneumonia p35; 5 Intra-abdominal infections p45; 6 Skin and soft tissue p55; 7 Bone and joint p61; 8 CNS p75; 9 Urinary tract infections p86; 10 Hospital-acquired infection p93; 11 Infections in immunocompromised host p126; 12 Pelvic infections p142; 13 Infective endocarditis p154; 14 Tables on duration, drug interaction, dosage and administration p164; 15 Appendix I ICMR data 2018 p183; 16 Appendix II index of tables p198. Pathogen mentions by chapter (Kp / Ec / Ab / Pa / Sa): ch10 HAI 10/7/6/6/20 (the richest chapter, printed p93 to 125); ch11 immunocompromised 6/5/7/11/21; ch5 intra-abdominal 3/7/0/1/2; ch4 RTI 3/0/1/3/7; ch7 bone and joint 0/0/1/4/10; ch8 CNS 2/1/2/3/7; ch13 endocarditis 1/0/0/1/16; ch6 skin 0/0/0/0/11. The introduction (p1) states Indian resistance levels (ESBL in 12 to 59% of *E. coli*, up to 50% carbapenem resistance in *K. pneumoniae*, MRSA up to 30%). Appendix I (printed p183 to 197) holds 2018 ICMR surveillance tables: isolation rates (Tables 1 and 2) and percent susceptible by antibiotic per pathogen (for example Table 6 *A. baumannii*, with columns all specimens, blood, LRT and others); the tables extract as one value per line, so they need table-aware parsing.

**`icmr-carbapenem-resistant-gram-negative-2022.pdf`** (ICMR Division of ECD, *Guidance on Diagnosis and Management of Carbapenem Resistant Gram-negative Infections*, March 2022): 24 pages, **printed page = PDF page**, no outline, page 24 has no text, extra spaces inside words (`res istant`). Sections: 1 Background p2 (CRE, CRPA, CRAB definitions; ICMR network imipenem resistance 28% *E. coli*, 55% *K. pneumoniae*, 80% *A. baumannii*; Ambler classes: KPC and IMI class A, NDM, VIM, IMP class B, OXA class D); Figures 1 to 3 p3 to 4; 2 Diagnosis of carbapenem resistance p4 to 14 (molecular test table p10; 2.1 aztreonam with ceftazidime-avibactam susceptibility testing p11 to 14); **3 Recommendations for management p15 to 19**; 3.1 Empiric therapy p15; 3.2 Directed therapy p15 to 18: 3.2.1 carbapenem-resistant Enterobacterales (*K. pneumoniae*, *E. coli*) p15 to 17, with **Table 4 (p16 to 17), a per-mechanism table**: metallo-beta-lactamase (for example NDM) and NDM + OXA-48: first choice prolonged-infusion ceftazidime-avibactam plus aztreonam, other options polymyxins plus another active agent, tigecycline (not alone for bloodstream infection or pneumonia), aminoglycosides; KPC: first choice prolonged-infusion ceftazidime-avibactam, same other options. 3.2.2 non-Enterobacterales p17 to 18: carbapenem-resistant *Acinetobacter* (combination with at least two active agents including high-dose sulbactam for moderate to severe infection; sulbactam alone for mild) and carbapenem-resistant *P. aeruginosa* (a beta-lactam or beta-lactamase-inhibitor combination if susceptible, aminoglycosides, polymyxins when nothing else). 4 Prevention p20; references p21 to 23. This is the best source of mechanism-to-drug recommendations. Mentions: *K. pneumoniae* 5, *E. coli* 2, *A. baumannii* 9, *P. aeruginosa* 13, *S. aureus* none. I read pages 15 to 18 and 1 to 4 in full; I did not read p5 to 14 or p19.

### taxonomy/pathogens.json

One JSON object, keys `source`, `retrieved`, `pathogens` (list of 5). Each pathogen: `taxid` (int), `scientific_name`, `rank` (`species`), `division` (`Bacteria`), `lineage` (string, `; ` separated), `other_names` (dict of lists). Entries: 573 *Klebsiella pneumoniae*, 562 *Escherichia coli*, 470 *Acinetobacter baumannii*, 287 *Pseudomonas aeruginosa*, 1280 *Staphylococcus aureus*; the script stops if NCBI resolves a name to a different id. `other_names` keys seen: `Synonym` (for example `Bacillus pneumoniae`, `Bacterium coli`), `CommonName` (*E. coli*: `E. coli`), `EquivalentName`, `authority`, `Includes` (strain-level entries, noisy), `type material` (culture collection ids), `misspelling` (for example `Acinetobacter baumanii`, `Escherchia coli`). Useful for synonyms: `Synonym`, `CommonName`, `EquivalentName`, `misspelling`; skip `Includes` and `type material`.

### pubmed/

`pmids.csv`: UTF-8 CSV, header `query,pmid`, 319 rows (319 distinct PMIDs). Each PMID appears once, under the first of 10 queries that found it (by that query's pathogen: *K. pneumoniae* 78, *S. aureus* 77, *A. baumannii* 64, *E. coli* 60, *P. aeruginosa* 40; this is not a count of abstracts per pathogen, because abstracts can match several). `abstracts.jsonl`: 319 lines, keys `pmid` (string), `title`, `abstract` (labelled sections joined as `BACKGROUND: ... RESULTS: ...`), `year` (int, 2015 to 2026; 2024 has 64, 2023 47, 2022 46), `journal`. Median abstract 203 words. Sample: PMID 37937997, 2023, *Clinical microbiology reviews*, "Klebsiella pneumoniae carbapenemase variants: the new threat to global public health."

## Deviations from the brief or contracts

- **ICMR treatment guidelines: 2019 edition, not 2022.** ICMR's list links a "2022" PDF, but it is a one-page QR poster; the 2022 edition exists only as a web app (`https://amrtg.icmr.org.in`). I used the 2019 PDF (206 pages) and did not scrape the web app.
- **GLASS: no *P. aeruginosa*; *Acinetobacter* only at genus level.** This is how GLASS-AMR reports, not a download problem. India is present.
- **GLASS source is the WHO data portal API** (`xmart-api-public.who.int`), because I found no WHO GLASS download file with resistance percentages; the GHO bulk zip has only enrolment indicators. Only 5 indicators and age group `Total` were kept (233,306 of about 4.3 million rows).
- **Extra files, all small**: the AWaRe 2023 workbook (for `who-aware-2023`), the CARD ontology archive (for antibiotic-level and drug-class relationships), `glass/countries.csv`.
- PubMed gave **319** abstracts (target 300 to 500).

## Not done or not verified

- The ICMR 2022 web edition is not downloaded or parsed.
- PDF text quality was checked only as described above; T06 should test extraction on the Reserve chapters of the AWaRe book and on the Appendix I tables of the ICMR 2019 PDF.
- ATC codes are not checked against the WHO ATC index (no such file was downloaded; the brief did not list it).
- "Latest" AWaRe edition was judged from the WHO landing pages on 2026-11-17; I did not search for anything newer than 2025.
- Pathogen-mention counts per chapter come from text search, not from reading the chapters.

## Requests to orchestrator

1. **CONTRACTS.md `source_id`**: change `who-aware-2023` to `who-aware-2025` if loaders use the 2025 workbook (recommended above), or keep it and use the 2023 workbook. Needed before T05.
2. **T08 source for ICMR**: decide whether T08 uses the ICMR 2019 PDF plus the 2022 carbapenem-resistant PDF only, or whether a task should extract text from `https://amrtg.icmr.org.in` (the 2022 web edition).
3. **GLASS pathogens**: `SurveillanceStat` rows can exist for four pathogens only, and the *Acinetobacter* rows are genus level (`Acinetobacter spp.`). Decide in the T05 brief whether to link them to `NCBITaxon:470` with a note or add a genus node.
4. **ATC rule for oral forms and `not assigned`**: loaders need it (CONTRACTS.md says use `J01…`; two drugs have no ATC and need `LOCAL:drug:` ids). T03's `schema/scope.yaml` may already cover this.
5. **Licences**: CARD is academic-only and the ICMR PDFs are "all rights reserved"; neither should be committed or published, consistent with D19. No packages were needed or installed.

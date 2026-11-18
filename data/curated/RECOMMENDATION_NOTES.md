# Curated recommendation notes (T08)

This file goes with `recommendations_curated.csv`. It records how the 80 rows were chosen, the conventions used to fill the columns, where the three guidelines disagree, every conflict with the T03 resistance facts, the drugs left out because they are not in scope, and the rows I am unsure about.

This is reference data for an educational tool, not clinical advice. The paraphrases contain no doses, durations or patient-specific advice.

## 1. How rows were chosen

I read every cited page in the PDFs with `pdfplumber` (text extraction; the WHO Reserve pages have broken spacing, which I read through). `source_page` is the **PDF page**, not the printed page. For the WHO book the printed page is the PDF page minus 16; for the ICMR 2019 guidelines it is the PDF page minus 5; for ICMR 2022 they are the same.

| Guideline | Pages read (PDF) | Rows |
|---|---|---|
| `icmr-cr-gram-negative-2022` | 1–4, 15–19 (section 3, Table 4, CRAB, CRPA, Tables 5–7) | 39 |
| `who-aware-book-2022` | 311–334 (sepsis), 397–411 (HAP), 490–504 (upper UTI), 505–522 (osteomyelitis), 523–538 (septic arthritis, skimmed for MRSA), 593–642 (Reserve chapters 41–48) | 25 |
| `icmr-treatment-guidelines-2019` | 34–39 (ch. 3 sepsis), 98–130 (ch. 10 hospital-acquired infection) | 16 |

A row was added when the page names (a) one of the five in-scope pathogens, or a group that clearly contains it (carbapenem-resistant Enterobacterales → *K. pneumoniae* and *E. coli*), and (b) at least one in-scope drug as a treatment option. Statements that only restrict use (for example "do not use tigecycline alone for bloodstream infection") are kept inside the `text` of the row they qualify, not as rows of their own.

ICMR 2022 Table 4 is the core: its four options (first choice, polymyxin-based combination, tigecycline, aminoglycoside) are written once per mechanism (NDM, OXA-48-like, KPC) and per Enterobacterales species, plus the NDM + OXA-48 co-producer line. That is 26 of the 35 carbapenemase-tied rows. The rows repeat on purpose, because each `(pathogen, mechanism)` pair needs its own `FOR_PATHOGEN` and `FOR_MECHANISM` edges.

The file has 80 rows, the upper limit of the brief. To stay within it I left out a few candidates (section 6).

## 2. Column conventions

- **`drug_ids` lists every in-scope drug the option names, and `regimen_type` (D33) says how they go together:**
  - `single`: one drug (42 rows).
  - `any-of`: alternatives, each usable on its own, such as "gentamicin or amikacin" or "vancomycin or teicoplanin" (21 rows).
  - `combination`: the drugs are given together (17 rows).
  - The 17 combination rows include a fixed pair, ceftazidime-avibactam plus aztreonam (6 rows), and other named pairs: colistin plus imipenem-cilastatin, and fosfomycin plus imipenem-cilastatin or doxycycline.
  - **The other 9 combination rows are "a base drug plus one of several partners".** That is the six Table 4 polymyxin rows, the unknown-carbapenemase row :027, CRAB :031 (sulbactam plus at least one more active agent) and CRPA :039. For example, Table 4's "polymyxin plus another active agent (tigecycline, aminoglycosides, IV fosfomycin) or high-dose carbapenem" is one `combination` row with colistin, polymyxin B, tigecycline, gentamicin, amikacin, fosfomycin, meropenem and imipenem-cilastatin.
  - The guideline calls all of these combination therapy, so they are `combination`. Not every listed drug is given at once, though; the `text` names the base drug.
  - **T10 should know:** under D34 a mechanism-free `combination` row is dropped if any drug is excluded. For these "base plus one partner" rows, that drops the whole option when only one partner is excluded (for example the carbapenem in :027). Judging the partners one by one would be closer to the guideline.
- **Class names in the guideline are expanded to in-scope drugs:**
  - "aminoglycosides" → gentamicin, amikacin. Tobramycin and plazomicin are not named in these passages.
  - "polymyxins" → colistin, polymyxin B.
  - "high-dose carbapenems" → meropenem, imipenem-cilastatin. ICMR 2022 Table 7 doses exactly these two.
  - "sulbactam" (on its own) → ampicillin-sulbactam. Standalone sulbactam is not in scope; the guideline lists ampicillin-sulbactam as one way to give it.
- **`mechanism_id` is set when the guideline names a mechanism or a mechanism-defined phenotype:**
  - KPC, NDM, OXA-48, MBL: named in ICMR 2022 Table 4 and in the WHO Reserve chapters. "MBL" is mapped to NDM for Enterobacterales and to VIM for *P. aeruginosa*, the in-scope MBL families recorded for those pathogens (ICMR 2022 Table 4 says "eg. NDM"; WHO Table 41.1 on p596 names NDM and VIM).
  - **ESBL** → CTX-M (ARO:3000016), following the synonym rule in REVIEW_NOTES §2.5 (3 rows).
  - **MRSA** → mecA/PBP2a (ARO:3009312), following `schema/phenotypes.csv` (9 rows). The guidelines say "MRSA", not "mecA". I chose this because otherwise an MRSA question would also return the MSSA rows (cefazolin, cloxacillin). If the orchestrator wants `mechanism_id` only for explicitly named enzymes or genes, clear these 12 rows (MRSA and ESBL).
  - "Carbapenem-resistant" alone does **not** set a mechanism (ARCHITECTURE §5.2 rule 1). This applies to the ICMR 2022 "carbapenemase result not available" rows, CRAB and CRPA, the ICMR 2019 CR rows, and several WHO Reserve rows.
- **NDM + OXA-48 co-producers** (ICMR 2022 Table 4, second line): `mechanism_id` = `ARO:3000057|ARO:3007721` (D33), with `patient_group` empty (REC:icmr-cr-gram-negative-2022:013 and :026). The conflict check takes the union of both mechanisms' exclusions.
- **`line_of_therapy`:**
  - ICMR "1st Choice" or "Preferred" → `first`.
  - ICMR "Other options" or "Alternative" → `alternative`.
  - "Only when no other option" or "only when resistant to all other tested antibiotics" → `last-resort`.
  - WHO "Second Choice" → `second`.
  - **Every WHO Reserve-chapter row is `last-resort`**, because the book calls Reserve antibiotics "the so-called last-resort antibiotics" (p594). The exception is linezolid for MRSA in selected situations, which is `alternative`.
- **`base_drug_ids` (D40)** is filled for the 10 "base drug plus partners" regimens:
  - polymyxins (colistin, polymyxin B): the six Table 4 polymyxin rows, :027 and CRPA :039;
  - ampicillin-sulbactam: CRAB :031;
  - fosfomycin: ICMR 2019 :009, fosfomycin plus imipenem-cilastatin or doxycycline.

  It is empty for fixed pairs (ceftazidime-avibactam plus aztreonam, ICMR 2019 colistin plus imipenem-cilastatin :007), single drugs and `any-of` lists.
- **`susceptible_only` (D40)** is `true` for 6 rows that are meant for organisms without the resistance a question is about:
  - MSSA (ICMR 2019 :003);
  - carbapenem-susceptible *E. coli* (ICMR 2019 :006);
  - WHO empiric first-choice regimens for non-resistant infection: HAP piperacillin-tazobactam (:019), mild and severe community pyelonephritis (:020, :021), and cloxacillin for osteomyelitis, which assumes methicillin-susceptible *S. aureus* (:023).

  Rows that require **in-vitro susceptibility to the recommended drug** in an organism that is otherwise resistant stay `false`. Examples: "ceftazidime-avibactam alone if susceptible" for CRE, or "beta-lactam if susceptible" for CRPA. Those recommendations are for resistant organisms, and D41 would wrongly drop them.
- **`infection_site` and `patient_group`** are free text, filled only when the page restricts the option, for example "uncomplicated UTI; source-controlled infection", "CLABSI", "HAP/VAP" or "adults" (where WHO says the drug is not licensed or has no data in children).

## 3. Conflicts with the curated resistance facts

The rule from the T03 handoff: a drug is excluded for `(pathogen, mechanism)` if its class is in the pathogen's `INTRINSICALLY_RESISTANT_TO` classes, or in the mechanism's `CONFERS_RESISTANCE_TO` classes, or the drug is in the mechanism's `INACTIVATES` list. The check runs over every row with a `mechanism_id` (47 rows) and is repeated by `tests/test_recommendations_curated.py`.

**Conflicts found: 11 rows, 17 drug-level conflicts.** None comes from intrinsic resistance. No MRSA, ESBL, VIM or WHO KPC/OXA-48 row conflicts.

### 3.1 Ceftazidime-avibactam recommended against NDM, inside the combination with aztreonam (5 rows)

| rec_id | Pathogen | Mechanism | Excluded drug | Seed fact | Supporting page |
|---|---|---|---|---|---|
| REC:icmr-cr-gram-negative-2022:001 | *K. pneumoniae* | NDM | ceftazidime-avibactam | NDM `INACTIVATES` ceftazidime-avibactam | ICMR 2022 p16, Table 4 |
| REC:icmr-cr-gram-negative-2022:013 | *K. pneumoniae* | NDM (+ OXA-48) | ceftazidime-avibactam | same | ICMR 2022 p16, Table 4 |
| REC:icmr-cr-gram-negative-2022:014 | *E. coli* | NDM | ceftazidime-avibactam | same | ICMR 2022 p16, Table 4 |
| REC:icmr-cr-gram-negative-2022:026 | *E. coli* | NDM (+ OXA-48) | ceftazidime-avibactam | same | ICMR 2022 p16, Table 4 |
| REC:who-aware-book-2022:006 | *K. pneumoniae* | NDM | ceftazidime-avibactam | same | WHO AWaRe book p606 |

**Assessment: not an error in either file.** The seed fact is correct for ceftazidime-avibactam alone, and both guidelines agree (WHO p606: inactive against NDM, VIM and IMP "unless co-prescribed with aztreonam"). The combination works because aztreonam is stable to the MBL and avibactam protects it from co-produced serine beta-lactamases (ESBL, AmpC, OXA-48). This is the caveat in REVIEW_NOTES §3, item 1. The drug-by-drug exclusion rule cannot see that a combination's partners cover each other. **Suggestion for T10/T14:** do not flag a combination row as contradicted when at least one partner is not excluded and the excluded partner is a beta-lactamase-inhibitor combination. Alternatively, show the row with the explanation "ceftazidime-avibactam alone is inactivated by NDM; it is given here to protect aztreonam".

### 3.2 Carbapenems named as a polymyxin partner for carbapenemase producers (6 rows, 12 drug-level conflicts)

| rec_id | Pathogen | Mechanism | Excluded drugs | Seed fact | Supporting page |
|---|---|---|---|---|---|
| REC:icmr-cr-gram-negative-2022:002 | *K. pneumoniae* | NDM | meropenem, imipenem-cilastatin | NDM `CONFERS_RESISTANCE_TO` carbapenem | ICMR 2022 p16, Table 4 |
| REC:icmr-cr-gram-negative-2022:006 | *K. pneumoniae* | OXA-48-like | meropenem, imipenem-cilastatin | OXA-48-like `CONFERS_RESISTANCE_TO` carbapenem | ICMR 2022 p16, Table 4 |
| REC:icmr-cr-gram-negative-2022:010 | *K. pneumoniae* | KPC | meropenem, imipenem-cilastatin | KPC `CONFERS_RESISTANCE_TO` carbapenem | ICMR 2022 p17, Table 4 |
| REC:icmr-cr-gram-negative-2022:015 | *E. coli* | NDM | meropenem, imipenem-cilastatin | NDM `CONFERS_RESISTANCE_TO` carbapenem | ICMR 2022 p16, Table 4 |
| REC:icmr-cr-gram-negative-2022:019 | *E. coli* | OXA-48-like | meropenem, imipenem-cilastatin | OXA-48-like `CONFERS_RESISTANCE_TO` carbapenem | ICMR 2022 p16, Table 4 |
| REC:icmr-cr-gram-negative-2022:023 | *E. coli* | KPC | meropenem, imipenem-cilastatin | KPC `CONFERS_RESISTANCE_TO` carbapenem | ICMR 2022 p17, Table 4 |

**Assessment: a real disagreement, conditional in the guideline.** ICMR 2022 lists "high dose carbapenems if MIC < 16" as a polymyxin partner, for every carbapenemase in Table 4. The seed data models carbapenemases as defeating the whole carbapenem class, which is correct as a categorical statement. The guideline relies on pharmacodynamic rescue at low-level MICs, which the presence-only model cannot represent (REVIEW_NOTES §5, item 2). **Decided (D34): option (a), keep the rows and show a caveat (section 3.3).** The options I offered were:

- (a) Keep both, and let T14 show the carbapenem as "only when the measured MIC is low, in combination". This is my recommendation, because it is what the guideline says.
- (b) Remove meropenem and imipenem-cilastatin from these six rows' `drug_ids` and keep them in `text` only.
- (c) Change nothing in T03.

The same carbapenem partner appears in the mechanism-free row REC:icmr-cr-gram-negative-2022:027 and in the ICMR 2019 rows REC:icmr-treatment-guidelines-2019:007 and :009, which pair imipenem-cilastatin with colistin or fosfomycin for carbapenem-resistant *Klebsiella* "when imipenem MICs are favourable". Those rows have no mechanism, so the rule does not check them.

### 3.3 Decision (D34) and caveats for the answer (T14)

The orchestrator kept all 11 rows. Under D34 a recommendation tied to the mechanism is always returned, and the answer shows the caveat below. **The `caveat` column of the CSV is now the source (D40).** This table is a copy for reading, and a test keeps the two identical. In the CZA+ATM rows, the drug the mechanism defeats on its own is ceftazidime-avibactam; in the polymyxin rows, it is the carbapenems.

| rec_id | Caveat |
|---|---|
| REC:icmr-cr-gram-negative-2022:001 | Ceftazidime-avibactam alone is inactive against NDM; here avibactam protects aztreonam, so use the two together only after a synergy test. |
| REC:icmr-cr-gram-negative-2022:013 | Ceftazidime-avibactam alone is inactive against NDM; with OXA-48 co-production, avibactam protects aztreonam, so use them together only after a synergy test. |
| REC:icmr-cr-gram-negative-2022:014 | Ceftazidime-avibactam alone is inactive against NDM; here avibactam protects aztreonam, so use the two together only after a synergy test. |
| REC:icmr-cr-gram-negative-2022:026 | Ceftazidime-avibactam alone is inactive against NDM; with OXA-48 co-production, avibactam protects aztreonam, so use them together only after a synergy test. |
| REC:who-aware-book-2022:006 | Ceftazidime-avibactam alone is inactive against NDM; it is useful only given together with aztreonam, which avibactam protects. |
| REC:icmr-cr-gram-negative-2022:002 | NDM defeats carbapenems; a carbapenem is listed only as a polymyxin partner when the measured carbapenem MIC is low. |
| REC:icmr-cr-gram-negative-2022:006 | OXA-48-like enzymes defeat carbapenems; a carbapenem is listed only as a polymyxin partner when the measured carbapenem MIC is low. |
| REC:icmr-cr-gram-negative-2022:010 | KPC defeats carbapenems; a carbapenem is listed only as a polymyxin partner when the measured carbapenem MIC is low. |
| REC:icmr-cr-gram-negative-2022:015 | NDM defeats carbapenems; a carbapenem is listed only as a polymyxin partner when the measured carbapenem MIC is low. |
| REC:icmr-cr-gram-negative-2022:019 | OXA-48-like enzymes defeat carbapenems; a carbapenem is listed only as a polymyxin partner when the measured carbapenem MIC is low. |
| REC:icmr-cr-gram-negative-2022:023 | KPC defeats carbapenems; a carbapenem is listed only as a polymyxin partner when the measured carbapenem MIC is low. |

### 3.4 Checked and consistent

These rows agree with the seed data:

- KPC → ceftazidime-avibactam, meropenem-vaborbactam, plazomicin.
- OXA-48-like → ceftazidime-avibactam.
- NDM and VIM → cefiderocol.
- CTX-M → meropenem, amikacin, gentamicin.
- mecA → vancomycin, teicoplanin, linezolid, daptomycin, clindamycin, fosfomycin.

The WHO meropenem-vaborbactam statement that it is "not active against MBL or OXA-48" (p622–623) matches T03's NDM and OXA-48 `INACTIVATES` rows for meropenem-vaborbactam. The WHO plazomicin page (p628) calls activity against MBL producers "variable"; T03 has no NDM exclusion for plazomicin, which is consistent with "variable".

## 4. Where the guidelines disagree

| Topic | ICMR 2022 | ICMR 2019 | WHO AWaRe 2022 |
|---|---|---|---|
| Carbapenem-resistant Enterobacterales | Ceftazidime-avibactam (with aztreonam for MBL) first; polymyxin-based combinations are "other options" (p16–17) | Colistin preferred for CR *E. coli* and *Klebsiella* bloodstream infection, with imipenem for *Klebsiella*; fosfomycin as alternative (p113–114) | New beta-lactam combinations and cefiderocol as mechanism-targeted Reserve options; polymyxins also Reserve (p598–634) |
| CRAB | Sulbactam is the agent of choice; combine at least two agents including sulbactam for moderate to severe infection (p18) | Colistin preferred, ampicillin-sulbactam alternative (CLABSI, p114) | Polymyxins Reserve; cefiderocol "caution" because of higher mortality in a trial (p598) |
| CRPA | A beta-lactam or beta-lactam/inhibitor if susceptible first; polymyxins only when nothing else (p18) | Colistin preferred, piperacillin-tazobactam alternative (CLABSI, p114) | Ceftazidime-avibactam, cefiderocol and polymyxins as Reserve options (p599, p606, p634) |
| MRSA pneumonia | – | Linezolid or vancomycin preferred, teicoplanin alternative (p118) | Adding vancomycin for suspected MRSA HAP is listed as an "area of uncertainty", not a recommendation (p407); linezolid only in selected situations (p618) |
| Polymyxin B vs colistin | Avoid polymyxin B for UTI (p16–17) | Both listed | Polymyxin B usually preferred except for UTI (p634) |

The ICMR 2019 guidance is older and predates the wider availability of ceftazidime-avibactam in India. ICMR 2022 supersedes it for carbapenem-resistant organisms. Both are kept, because D5 asks for disagreements to be shown side by side.

## 5. Recommended drugs that are not in scope

These were named on the pages read and left out of `drug_ids` (they are not in `schema/scope.yaml`). Where a row still fits with the in-scope drugs, the row was kept.

| Drug | Where | Note |
|---|---|---|
| Sulbactam (standalone, high dose) | ICMR 2022 p17–18 (CRAB) | Mapped to ampicillin-sulbactam |
| Cefoperazone-sulbactam | ICMR 2022 p17 (CRAB), p18 (CRPA); ICMR 2019 p37, p111, p113–114, p118 | Common in Indian practice; already a candidate in REVIEW_NOTES §6 |
| Chloramphenicol | ICMR 2019 p114 (colistin-resistant *Klebsiella*) | |
| Metronidazole | WHO p319, p332, p606 (partner for intra-abdominal infection) | Anaerobic cover only |
| Echinocandins (caspofungin, micafungin, anidulafungin) | ICMR 2019 p37 | Antifungals |
| Dicloxacillin | WHO p522 (oral step-down) | Cloxacillin is in scope |
| Nebulised colistin | ICMR 2019 p118 | Same drug, route not modelled; ICMR 2022 p18 advises against nebulised antibiotics for CRAB |
| Oral fosfomycin (single dose) | ICMR 2022 p18, Table 5 (uncomplicated cystitis) | The fosfomycin node uses the IV AWaRe group; Table 5 is not pathogen-specific, so no row |

Also seen but outside the pathogen scope: *Enterococcus* and coagulase-negative staphylococcal CLABSI regimens (ICMR 2019 p112), and *Stenotrophomonas* and *Burkholderia* (ICMR 2022 p15, ICMR 2019 p114).

## 6. Left out to stay within 80 rows

- ICMR 2022 3.2.1(b) options for unknown carbapenemase: added for *K. pneumoniae* only, not repeated for *E. coli*. Polymyxin monotherapy for uncomplicated CRE and tigecycline for unknown carbapenemase are not added; Table 4 covers both per mechanism.
- WHO cefiderocol caution for *A. baumannii* (p598): a restriction, not an indication.
- WHO septic arthritis MRSA options (p525, p538): they repeat the osteomyelitis rows.
- WHO plazomicin for OXA-48 producers (p627–628): one plazomicin row (KPC) is kept.
- ICMR 2019 HAP/VAP "combination of two susceptible antibiotics for CRE in septic shock" (p118): no drug is named.
- ICMR 2022 Table 5 (by clinical syndrome) and Tables 6 and 7 (durations and doses): not pathogen-specific, and they contain doses.

## 7. Rows I am unsure about

| rec_id | Doubt |
|---|---|
| All 12 MRSA and ESBL rows | `mechanism_id` comes from the phenotype (section 2), not a named gene |
| REC:who-aware-book-2022:003 | "Particularly MBL-producing" *P. aeruginosa* is mapped to VIM; WHO does not name VIM in the cefiderocol chapter itself, only in Table 41.1 (p596) |
| REC:who-aware-book-2022:002 and :012 | WHO speaks of Enterobacterales; *E. coli* is my expansion. The pages give *K. pneumoniae* as the main example |
| REC:who-aware-book-2022:016 | The WHO sepsis table adds vancomycin for suspected MRSA in the skin and soft-tissue row; the row is generalised to S. aureus sepsis from that source only |
| REC:who-aware-book-2022:018 | The sepsis footnote names amikacin as carbapenem-sparing for ESBL in general; I placed it under the urinary-source regimen, where amikacin appears in the table |
| REC:icmr-treatment-guidelines-2019:007, :009 | The Table 10.6 cells extract as interleaved columns. I read "colistin ... plus imipenem/cilastatin" as the preferred regimen and "fosfomycin plus imipenem; or doxycycline" for colistin-resistant isolates. A reviewer should check the layout on PDF p114 |
| REC:icmr-treatment-guidelines-2019:014 | Table 10.8 lists "MRSA: linezolid or vancomycin" with teicoplanin in the next column. I read teicoplanin as the alternative, but kept all three in one row with `line_of_therapy` = `first` |
| REC:icmr-cr-gram-negative-2022:028 | ICMR 2022 3.2.1(b) item 2 lists ceftazidime-avibactam alone "if susceptible" and with aztreonam "if synergy" as one item; I split it into two rows (:028, :029) |
| WHO Reserve rows as `last-resort` | A blanket mapping from the book's framing (p594), not a per-chapter statement |

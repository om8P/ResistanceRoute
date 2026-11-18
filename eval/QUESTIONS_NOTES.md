# Evaluation questions: design notes (T09)

`eval/questions.json` holds the 40 evaluation questions and their gold answers. They were written on 2026-11-18, before any retrieval code existed (DECISIONS.md D16), from the guideline PDFs, the GLASS file and the curated seed files. No system output was used. Relevant passage IDs are added later by T15.

This is an educational evaluation set. No gold answer contains a dose or patient-specific advice; `tests/test_questions.py` checks for dose units.

## 1. Mix

| Intent | Single-hop | Multi-hop | Total |
|---|---|---|---|
| `alternatives` | 0 | 9 | 9 |
| `why_restricted` | 5 | 3 | 8 |
| `mechanism_lookup` | 2 | 3 | 5 |
| `recommendation_lookup` | 0 | 5 | 5 |
| `drug_profile` | 4 | 0 | 4 |
| `surveillance` | 5 | 0 | 5 |
| `decline` | 4 | 0 | 4 |
| **Total** | **20** | **20** | **40** |

| Answer type | Count | Questions |
|---|---|---|
| `drug_set` | 13 | Q02, Q03, Q07, Q08, Q13, Q15, Q16, Q18, Q23, Q26, Q27, Q33, Q36 |
| `class_set` | 1 | Q31 |
| `mechanism_set` | 5 | Q06, Q12, Q22, Q30, Q38 |
| `number` | 4 | Q04, Q11, Q20, Q28 |
| `fact` | 13 | Q01, Q05, Q09, Q10, Q14, Q19, Q21, Q25, Q29, Q34, Q35, Q37, Q39 |
| `decline` | 4 | Q17 (dosing), Q24 (patient-specific), Q32 and Q40 (out-of-scope pathogen) |

**Mechanism-dependent multi-hop questions** (the answer changes with the mechanism): Q02 KPC, Q03 NDM, Q10 NDM, Q13 OXA-48-like, Q15 KPC, Q16 NDM, Q18 VIM, Q21 OXA-23-like, Q23 mecA, Q31 KPC, Q39 OXA-48-like. There are 11; the brief asks for at least 6. All six named mechanisms appear.

**Pairs that differ only in the mechanism:**

- Q02 / Q03: "KPC-producing (NDM-producing) *K. pneumoniae* resistant to carbapenems: which beta-lactams are still active?"
- Q15 / Q16: "According to ICMR, what is the first choice for KPC-producing (NDM-producing) CRE?"

The test suite also treats Q07 and Q26 as mechanism-dependent, because MRSA implies mecA (`schema/phenotypes.csv`). Their answers come from recommendations for MRSA, not from mechanism reasoning.

## 2. Definitions used

- **Single-hop:** the answer is a property of one linked entity (AWaRe group, class), one stored relation, or one surveillance row.
- **Multi-hop:** the answer needs two or more relations chained, for example pathogen → mechanism → class → drug, phenotype → mechanism → recommendation, or mechanism → inhibitor failure → drug.
- **`entities`:** canonical IDs from `schema/scope.yaml`, including those an acronym implies: MRSA adds `ARO:3009312`, and CRE adds both Enterobacterales. A class family named in the question ("carbapenems") is given as the class ID `carbapenem`. Out-of-scope entities are left out, so Q32 has none.
- **Unspecified "aminoglycosides" in a guideline** is expanded to the in-scope non-Reserve aminoglycosides (amikacin, gentamicin, tobramycin), the same way in Q08, Q18 and Q36. Plazomicin is excluded wherever AWaRe Table 41.1 marks it inactive or only possibly active.
- **`number` gold** is `{value, unit, year, country}`, rounded to one decimal. The exact GLASS value is in `notes`. GLASS row keys are `IND_CODE|year|ISO3|specimen|pathogen|antibiotic|group`, with the file line number (header = line 1).
- **`gold_source`** is a list of strings:
  - `<guideline id> p<PDF page>` (PDF pages, not printed pages);
  - `who-aware-2025 sheet 'AWaRe classification 2025' row <Excel row>`;
  - `glass <row key> (file line <n>)`;
  - `curated-seed <file> line(s) <n>`, where line numbers include the header line.

  The guideline IDs are those in the T06 brief: `who-aware-book-2022`, `icmr-treatment-guidelines-2019` and `icmr-cr-gram-negative-2022`.

## 3. Design choices

- **Written from the sources, not for the system.** Several gold answers will penalise a system that reads the curated seed literally: Q03, Q13 and Q18 exclude drugs the seed leaves active. Several reward text retrieval: Q14, Q34 and Q37 are answered only by guideline prose.
- **Stricter answer where sources disagree** (brief rule). Each case is noted in the question's `notes` and listed in section 4.
- **Realistic wording:**
  - abbreviations: MRSA, CRAB, CRKP, CZA, KPC, NDM, VIM, UTI, TB;
  - brand names: Avycaz, Zerbaxa, Tazocin, Vabomere;
  - lower-case and terse questions;
  - two misspellings: "baumanii" in Q08 and "klebsiela" in Q13;
  - class-family wording such as "carbapenems" and "3rd gen cephalosporin".
- **Decline cases are traps.** Two cases can be retrieved from the text: colistin doses are printed in ICMR 2022 p19 (Q17), and AWaRe p617 mentions linezolid for VRE (Q32). Q40 names a carbapenem-resistant Enterobacterales that is not one of the five pathogens, to test that the CRE phenotype does not over-link to *K. pneumoniae* or *E. coli*.
- **Q35 is a "no data" surveillance question.** GLASS has no *P. aeruginosa* rows (checked: 0 of 233,306), so the correct answer is that no figure exists.

## 4. Hardest gold answers

| Question | Difficulty | Decision |
|---|---|---|
| Q03 NDM *K. pneumoniae* beta-lactams | NDM does not hydrolyse aztreonam (seed has no monobactam edge), but NDM producers usually co-produce ESBL/AmpC, and ICMR uses aztreonam only together with ceftazidime-avibactam. | Plain aztreonam left out (stricter). "CZA plus aztreonam" as a combination is acceptable. |
| Q13 OXA-48-like *K. pneumoniae* beta-lactams | The seed leaves all plain cephalosporins and aztreonam active, because OXA-48-like alone hydrolyses them weakly. Clinical isolates usually also carry CTX-M-15, and no guideline recommends them. | Gold limited to ceftazidime-avibactam, cefiderocol and aztreonam-avibactam (stricter). |
| Q18 VIM *P. aeruginosa* | VIM spares aztreonam, but no source recommends it for VIM-PA. Plazomicin and IV fosfomycin are only "possibly active" in Table 41.1. | Cefiderocol, polymyxins and aminoglycosides (if susceptible, ICMR p18). Aztreonam, plazomicin and fosfomycin left out. |
| Q08 CRAB alternatives | ICMR lists sulbactam, polymyxins, minocycline, tigecycline, and "other agents" (TMP-SMX, aminoglycosides) if susceptible. AWaRe warns about cefiderocol in *A. baumannii*. Sulbactam-durlobactam is newer than both documents. | All ICMR items included. Cefiderocol and sulbactam-durlobactam left out (stricter). |
| Q28 MRSA rate in India 2023 | Two GLASS rows disagree for the same year: methicillin 53.6%, oxacillin (group "Methicillin resistance") 28.0%. | Higher value (53.6) chosen as the stricter answer. 28.0 accepted if the oxacillin row is cited. |
| Q25 Is fosfomycin Reserve? | AWaRe 2025 lists IV fosfomycin as Reserve and oral fosfomycin as Watch under one ATC code; the graph node takes the IV group. | Gold names both routes; "Reserve" alone is partly correct. |
| Q20 Acinetobacter carbapenem resistance | GLASS reports *Acinetobacter* spp. at genus level, with a class row and two drug rows that differ slightly. ICMR 2022 gives a different figure (80%). | Class row (67.9%) is the gold. The meropenem and imipenem rows are acceptable. |
| Q23 MRSA beta-lactams | Only the curated seed covers ceftaroline; no guideline page read for this set discusses it. | Ceftaroline only, sourced to the seed. Flagged so T15 can look for a supporting passage. |
| Q38 Colistin resistance in *K. pneumoniae* | The commonest cause (chromosomal mgrB/pmrAB) is not a modelled mechanism; MCR is modelled but flagged `needs_review`. | Gold is MCR. Chromosomal mutations are correct extra content. |
| Q07 MRSA bloodstream infection | The ICMR table is for catheter-related bloodstream infection; AWaRe only says to add vancomycin if MRSA is suspected. | Vancomycin, teicoplanin, daptomycin. Linezolid is left out because these pages do not list it for bacteraemia. |

## 5. Limits

- Every guideline page cited was read for this task. The IDSA and EUCAST documents behind some seed rows were not read; where a gold answer rests on such a row, the seed row is cited and its `needs_review` flag is noted.
- Fact answers are short statements, not ID sets, so T17 needs a rubric or manual scoring for them (about a third of the set). The `notes` say which parts are required and which are a bonus.
- Gold sets are scored as sets. Where a guideline gives a preferred option and alternatives (Q07, Q26), both are in the gold; ranking is not evaluated.

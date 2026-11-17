# Seed data review notes (T03)

This file is for a pharmacology or microbiology reviewer and for the tasks that build on the seed data. It records the modelling choices, the worked example the graph must reproduce, every row flagged `needs_review`, and the known simplifications.

This is reference data for an educational tool. It describes in-vitro and mechanism-level activity, not treatment choices. It contains no doses and no patient-specific advice.

## 1. Source tags

The `source` column holds one or more of these tags, separated by `|`.

| Tag | Source |
|---|---|
| `CARD` | Comprehensive Antibiotic Resistance Database, card.mcmaster.ca: gene-family terms, drug classes, mechanism and host organisms. Family accessions were read on the CARD site on 2026-11-17 and confirmed on 2026-11-18 against the downloaded CARD ontology v4.0.2 (`data/raw/card/ontology/aro.obo`, dated 2026-08-11). Family drug classes were checked against `data/raw/card/aro_index.tsv`. |
| `IDSA-AMR-GN-2024` | IDSA 2024 Guidance on the Treatment of Antimicrobial-Resistant Gram-Negative Infections (ESBL-E, AmpC-E, CRE, DTR-*P. aeruginosa*, CRAB) |
| `EUCAST-ERP-v1.2-2023` | EUCAST Expected Resistant Phenotypes, version 1.2 (2023) |
| `EUCAST-expert-rules` | EUCAST Expert Rules on interpretation (used for "MRSA is resistant to beta-lactams other than anti-MRSA agents") |
| `WHO-AWaRe-book-2022`, `ICMR` | Allowed by the tests but not used yet. Wave 2 (T08) cites them for recommendations. |
| `unverified` | I could not name a source I am sure of. Every such row has `needs_review = true`. |

The CARD and IDSA citations name where a reviewer should check the fact. They were not read line by line in this session, and the IDSA and EUCAST documents were cited from knowledge, not opened. A row is marked `needs_review = false` only when the fact is textbook-level and the cited source is known to cover it.

## 2. Modelling choices

### 2.1 Reasoning classes, not ATC groups

Classes follow DECISIONS.md D6: they are the groups that resistance acts on, not the ATC hierarchy. That gives **32 classes**, about twice the 15 in the brief. Each split exists because a class-level edge would otherwise give a wrong answer:

| Split | Why |
|---|---|
| `aminopenicillin-bli` (amoxicillin-clavulanic acid), `aminopenicillin-sulbactam` (ampicillin-sulbactam), `antipseudomonal-penicillin-bli` (piperacillin-tazobactam) | *P. aeruginosa* is intrinsically resistant to the first two but not to piperacillin-tazobactam. *A. baumannii* is intrinsically resistant to amoxicillin-clavulanic acid but not to ampicillin-sulbactam, because sulbactam itself is active against it. |
| `sulbactam-durlobactam` | Useful only against *Acinetobacter*, so the other four pathogens are intrinsically resistant to it. |
| `cephalosporin-3rd-gen` (ceftriaxone, cefotaxime) vs `cephalosporin-3rd-gen-antipseudomonal` (ceftazidime) | *P. aeruginosa* is intrinsically resistant to ceftriaxone and cefotaxime only. PDC (AmpC) overproduction acts on ceftazidime. |
| `anti-mrsa-cephalosporin` (ceftaroline) | mecA excludes every other beta-lactam but not this one. |
| `siderophore-cephalosporin` (cefiderocol) | It is stable to all carbapenemases in scope, so no carbapenemase edge applies to it. |
| `carbapenem` (meropenem, imipenem) vs `carbapenem-group-1` (ertapenem) | *P. aeruginosa* and *A. baumannii* are intrinsically resistant to ertapenem only. |
| `cephalosporin-bli`, `carbapenem-bli`, `monobactam-bli` | ARCHITECTURE.md 5.2 rule 3: combinations need their own classes. |

Ceftobiprole was left out of scope: it would share a class with ceftaroline, but unlike ceftaroline it is active against *P. aeruginosa*, so the class would need another split. Cefoxitin, temocillin, cefoperazone-sulbactam and cefepime-enmetazobactam were also left out to keep the scope near 50 drugs (see section 6).

### 2.2 Class-level edges vs drug-level `INACTIVATES`

- A mechanism gets a `CONFERS_RESISTANCE_TO` edge to a class only when it defeats **every** drug in that class.
- **Beta-lactamases (carbapenemases, ESBL, AmpC) never get class-level edges to a beta-lactam/beta-lactamase-inhibitor combination class.** Whether a combination survives depends on whether that particular inhibitor inhibits that particular enzyme, so each failure is a separate `INACTIVATES` row with the reason in `notes`, for example "Avibactam does not inhibit metallo-beta-lactamases". The explanation path can show that reason. A new combination added later, such as one with an MBL-active inhibitor, then starts out active rather than wrongly excluded. A test enforces this rule.
- Non-enzymatic mechanisms act on the backbone whatever the inhibitor, so mecA/PBP2a does get class-level edges to the combination classes.
- No `INACTIVATES` row duplicates a class-level edge from the same mechanism (also tested).

### 2.3 Mechanism IDs

- Mechanisms are CARD **AMR gene families**, not single genes: for example ARO:3000059 is the KPC family, not KPC-2 (ARO:3002312).
- mecA/PBP2a uses the family that CARD currently assigns to mecA (ARO:3000617): "PBP2-like beta-lactam resistant peptidoglycan transpeptidase", ARO:3009312. An older CARD family, "methicillin resistant PBP2" (ARO:3001208), appears in older CARD releases. The current family also includes mecC.
- Plasmid AmpC is represented by the CMY family (ARO:3000069), the most common plasmid AmpC in *E. coli*. DHA, ACT and FOX families are not modelled separately. The synonyms `AmpC`, `pAmpC` and `plasmid AmpC` point to it.
- PDC (ARO:3000098) stands for **overproduction** of the chromosomal AmpC that every *P. aeruginosa* carries. Its presence alone does not imply resistance.
- OprD porin loss has no CARD family term, so it uses `LOCAL:mech:oprd-porin-loss` with `id_verified: false`. CARD v4.0.2 does have the variant term ARO:3003686 ("Pseudomonas aeruginosa oprD with mutation conferring resistance to imipenem"). That is a gene-level term, suitable for a `Gene` node that `ENCODES` this mechanism if genes are loaded later.
- CARD's family-level drug classes (union over the family's gene models in `aro_index.tsv`) agree with the class edges, with one gap in each direction. Where CARD lists `carbapenem` for the CTX-M, CMY and PDC families, it comes from a few carbapenem-hydrolysing variants; it is not modelled, since these families do not confer carbapenem resistance in general. The mecA family's CARD classes (cephalosporin, penam) are narrower than the EUCAST rule used here (all beta-lactams except anti-MRSA agents).

### 2.4 Intrinsic resistance

Intrinsic resistance is stored per class, as in the contract. Where EUCAST lists a single drug, such as benzylpenicillin for Gram-negatives or tetracycline for *P. aeruginosa*, the row extends it to the whole class and says so in `notes`. Drug-level intrinsic exceptions that do not fit a class (for example trimethoprim alone for *A. baumannii*) are not represented.

### 2.5 Synonyms

- Every entity has exactly one `canonical` row whose synonym equals the scope name.
- **Phenotype acronyms that imply more than a pathogen.** The query parser must handle these, because the synonym file maps them only to the pathogen:

  | Acronym | Maps to | Also implies |
  |---|---|---|
  | MRSA | *S. aureus* | mechanism ARO:3009312 (mecA/PBP2a); resistance to all beta-lactam classes except `anti-mrsa-cephalosporin` |
  | MSSA | *S. aureus* | absence of mecA |
  | CRKP | *K. pneumoniae* | carbapenem resistance (classes `carbapenem`, `carbapenem-group-1`); mechanism unknown, so answer per carbapenemase |
  | KPC-Kp | *K. pneumoniae* | mechanism ARO:3000059 (KPC) |
  | CREC | *E. coli* | carbapenem resistance, mechanism unknown |
  | CRAB | *A. baumannii* | carbapenem resistance; usually OXA-23-like (ARO:3007710) |
  | CRPA | *P. aeruginosa* | carbapenem resistance; carbapenemase (VIM) or non-carbapenemase (OprD loss with or without PDC overproduction) |
  | DTR-PA | *P. aeruginosa* | IDSA "difficult-to-treat resistance": not susceptible to all first-line beta-lactams and fluoroquinolones |

- Mechanism-group terms are mapped to one representative. `ESBL` and `extended-spectrum beta-lactamase` map to CTX-M (other ESBL families such as SHV and TEM ESBLs are not modelled), and `AmpC` maps to plasmid AmpC (CMY). With *P. aeruginosa* in the question, the parser should read `AmpC` as PDC.
- Deliberately **not** mapped, because they are ambiguous: `MBL`/`metallo-beta-lactamase` (NDM or VIM), `carbapenemase`, `CRE` (*K. pneumoniae* or *E. coli*), `porin loss` (OmpK35/36 in *Klebsiella* is not modelled), `BL/BLI` (six classes), and `third-generation cephalosporins` as a whole. That last one maps to `cephalosporin-3rd-gen`, but in a question it should usually expand to `cephalosporin-3rd-gen-antipseudomonal` as well.
- Short drug codes left out to avoid false matches in passages: `GEN` (as in "3rd gen"), `MIN` (minutes), `VAN` (author names), `DOX` (doxorubicin). The kept three-letter codes (MEM, CAZ, TZP, ...) are upper-case report codes, and the linker should match `abbreviation` rows case-sensitively.
- Bare `Klebsiella`, `Acinetobacter`, `Pseudomonas` and `Escherichia` map to the in-scope species. That is acceptable for a five-pathogen scope, but it is a simplification.
- The phenotype table above is in machine-readable form in `schema/phenotypes.csv` (CONTRACTS.md §4). It adds CRE, ESBL-E, ESBL-EC and ESBL-KP. A phenotype that spans two in-scope species (CRE, ESBL-E) has one row per species. `mechanism_ids` is filled only when the acronym names the mechanism (MRSA, KPC-Kp, the ESBL acronyms). For CRKP, CRAB and the other CR- acronyms it is empty, so the answer is given per mechanism recorded for the pathogen.

### 2.6 Class families (DECISIONS.md D29)

Each of the 32 reasoning classes has a `family`: the group a user would name. There are 16 families. Most are obvious (all cephalosporin generations → `cephalosporin`, ertapenem's class and the meropenem/imipenem class → `carbapenem`, glycylcyclines → `tetracycline`, lipoglycopeptides → `glycopeptide`, as in ATC J01AA and J01XA). The non-obvious choices:

- **All beta-lactam/beta-lactamase-inhibitor combination classes form one family, `beta-lactam-bli`, separate from their backbone families.** That includes amoxicillin-clavulanic acid, ampicillin-sulbactam, piperacillin-tazobactam, sulbactam-durlobactam and the cephalosporin, carbapenem and monobactam combinations. If `carbapenem-bli` were in `carbapenem`, then "carbapenem resistance" (CRKP, CRAB, CRPA in `phenotypes.csv`) would exclude meropenem-vaborbactam and imipenem-relebactam, which are exactly the KPC options. The same argument keeps `cephalosporin-bli` out of `cephalosporin` (ceftazidime-avibactam) and `monobactam-bli` out of `monobactam` (aztreonam-avibactam). Keeping the older penicillin combinations in the same family follows the AWaRe class "Beta-lactam/beta-lactamase-inhibitor". The cost: "which penicillins…" does not list amoxicillin-clavulanic acid unless the parser also expands `beta-lactam-bli`.
- **`siderophore-cephalosporin` (cefiderocol) and `anti-mrsa-cephalosporin` (ceftaroline) are in `cephalosporin`.** So "which cephalosporins are active?" lists them. For the same reason, no phenotype uses `cephalosporin` as its `class_family`: excluding the whole family for ESBL-E or MRSA would wrongly remove cefiderocol or ceftaroline. Those phenotypes carry a mechanism instead, and the mechanism's class edges do the exclusion.
- **No `beta-lactam` super-family.** "Beta-lactams" would span five families. It is not mapped as a synonym; the parser should expand it to `penicillin`, `cephalosporin`, `carbapenem`, `monobactam` and `beta-lactam-bli` if needed.
- Where a DrugClass synonym and a ClassFamily synonym are the same string (for example "Tetracyclines", "Glycopeptides", "carbapenems"), the class is always a member of that family (tested). The parser should prefer the ClassFamily reading for class-level questions.

## 3. Worked example: carbapenem-resistant *K. pneumoniae* (acceptance test)

Reasoning, one mechanism at a time: take all 49 drugs in scope and remove (a) classes *K. pneumoniae* is intrinsically resistant to, (b) classes the mechanism confers resistance to, and (c) drugs the mechanism inactivates.

`tests/test_seed_data.py::test_worked_example_crkp_by_mechanism` computes this from the files and checks it against the lists below.

**(a) Intrinsic, the same for every mechanism:** aminopenicillins (ampicillin, amoxicillin), antistaphylococcal penicillins, sulbactam-durlobactam, glycopeptides, lipoglycopeptides, oxazolidinones, lipopeptides, lincosamides.

**Non-beta-lactams that remain for all three mechanisms (16)**, because no in-scope mechanism of these isolates acts on them: gentamicin, amikacin, tobramycin, plazomicin, ciprofloxacin, levofloxacin, moxifloxacin, colistin, polymyxin B, doxycycline, minocycline, eravacycline, tigecycline, fosfomycin, sulfamethoxazole-trimethoprim, nitrofurantoin. In practice CRKP often co-carries other mechanisms (16S RMTase, MCR) that would remove some of these; see section 5.

**Beta-lactams that remain:**

| Mechanism | Remaining beta-lactams | Removed by a class edge | Removed by a drug-level row |
|---|---|---|---|
| **KPC** (ARO:3000059) | **ceftazidime-avibactam, meropenem-vaborbactam, imipenem-cilastatin-relebactam, cefiderocol, aztreonam-avibactam** | cephalosporins (1st–4th gen, ceftaroline), carbapenems incl. ertapenem, aztreonam | amoxicillin-clavulanic acid, ampicillin-sulbactam, piperacillin-tazobactam, ceftolozane-tazobactam |
| **NDM** (ARO:3000057) | **aztreonam, aztreonam-avibactam, cefiderocol** | cephalosporins (1st–4th gen, ceftaroline), carbapenems incl. ertapenem | amoxicillin-clavulanic acid, ampicillin-sulbactam, piperacillin-tazobactam, ceftazidime-avibactam, ceftolozane-tazobactam, meropenem-vaborbactam, imipenem-cilastatin-relebactam |
| **OXA-48-like** (ARO:3007721) | **ceftazidime-avibactam, cefiderocol, aztreonam-avibactam, aztreonam, cefazolin, cefuroxime, ceftriaxone, cefotaxime, ceftazidime, cefepime, ceftaroline fosamil** | carbapenems incl. ertapenem | amoxicillin-clavulanic acid, ampicillin-sulbactam, piperacillin-tazobactam, ceftolozane-tazobactam, meropenem-vaborbactam, imipenem-cilastatin-relebactam |

The three answers differ in the way DECISIONS.md D4 needs:

- Ceftazidime-avibactam remains for KPC and OXA-48-like but not for NDM.
- Meropenem-vaborbactam and imipenem-relebactam remain for KPC only.
- Aztreonam remains for NDM (MBLs spare monobactams) but not for KPC.
- No plain carbapenem remains for any of them.

This matches the shape of the IDSA 2024 CRE guidance: the newer combinations are preferred for KPC, ceftazidime-avibactam for OXA-48-like, and aztreonam-based or cefiderocol options for MBLs. The graph lists mechanism-level activity, not preferred therapy; preference comes from the `Recommendation` nodes (T08).

**Two answers that are correct for the single mechanism but would mislead if shown unqualified.** The answer template (T14) should caveat both:

1. **NDM leaves aztreonam.** NDM alone does not hydrolyse aztreonam, but NDM producers usually also carry an ESBL or AmpC that does. That is why guidelines pair aztreonam with avibactam (ceftazidime-avibactam plus aztreonam, or aztreonam-avibactam). Asking about NDM + CTX-M gives the realistic answer, because the CTX-M monobactam edge removes aztreonam.
2. **OXA-48-like leaves the cephalosporins and aztreonam.** OXA-48-like enzymes barely hydrolyse extended-spectrum cephalosporins, but most clinical isolates co-produce CTX-M-15. Asking about OXA-48-like + CTX-M leaves ceftazidime-avibactam, cefiderocol and aztreonam-avibactam among the beta-lactams.

## 4. Rows needing review (43 of 185 curated rows)

Grouped by the question the reviewer has to answer. The row is identified as `subject → object`.

### 4.1 Microbiology: does this mechanism occur in this pathogen often enough to include? (pathogen_mechanism.csv, 8 rows)

| Row | Source | Question |
|---|---|---|
| K. pneumoniae → CMY (plasmid AmpC) | CARD | Is DHA a better representative than CMY for *Klebsiella*? |
| K. pneumoniae → MCR | CARD | Colistin resistance in *K. pneumoniae* is mostly chromosomal (mgrB). Keep MCR as the modelled mechanism? |
| E. coli → VIM | CARD | Rare; keep? |
| A. baumannii → NDM | CARD | Uncommon; keep? |
| P. aeruginosa → NDM | CARD | Lineage-specific; keep? |
| P. aeruginosa → KPC | CARD | Regional; keep? |
| P. aeruginosa → OprD porin loss | IDSA-AMR-GN-2024 | Confirm the citation; LOCAL ID. |
| P. aeruginosa → 16S rRNA methyltransferase | unverified | rmtD and other rmt genes in *P. aeruginosa*: confirm. |

### 4.2 Enzymology: does this mechanism defeat the whole class? (mechanism_class.csv, 5 rows)

The aminopenicillin rows for OXA-23-like, CTX-M and CMY were confirmed against the CARD family drug classes in `aro_index.tsv` (penicillin beta-lactam) and are no longer flagged.

| Row | Source | Question |
|---|---|---|
| CTX-M → ceftazidime class | CARD | Variant-dependent (CTX-M-15 high, CTX-M-14 low). Keep as resistant? |
| CTX-M → cefepime | CARD, IDSA | Hydrolysis is variable; the row follows IDSA's advice to avoid cefepime for ESBL-E. |
| CTX-M → monobactams | unverified | Aztreonam hydrolysis by ESBLs. |
| CMY → ceftaroline | CARD | Confirm for CMY specifically. |
| CMY → monobactams | unverified | Moderate hydrolysis; class-level edge justified? |

### 4.3 Pharmacology: does this inhibitor fail against this enzyme? (mechanism_inactivates_drug.csv, 9 rows)

| Row | Source | Question |
|---|---|---|
| NDM → sulbactam-durlobactam | unverified | Durlobactam has no MBL activity. |
| OXA-23-like → piperacillin-tazobactam | unverified | |
| OXA-23-like → ceftazidime-avibactam | IDSA | Avibactam vs OXA-23: confirm wording. |
| OXA-23-like → ceftolozane-tazobactam | IDSA | |
| CTX-M → piperacillin-tazobactam | IDSA | **Not true inactivation** (often susceptible in vitro). It is excluded on the MERINO/IDSA stewardship rationale. Keep, or drop and leave this to recommendations? |
| CMY → ampicillin-sulbactam | unverified | |
| CMY → piperacillin-tazobactam | IDSA | |
| PDC → piperacillin-tazobactam | IDSA | |
| OprD loss → imipenem-cilastatin | unverified | Meropenem not excluded; imipenem-relebactam kept active. Agree? |

### 4.4 Expected phenotypes: is this pathogen intrinsically resistant to the whole class? (intrinsic_resistance.csv, 21 rows)

| Rows | Source | Question |
|---|---|---|
| Antistaphylococcal penicillins for K. pneumoniae, E. coli, A. baumannii, P. aeruginosa (4) | EUCAST | EUCAST names benzylpenicillin; is extending this to cloxacillin/flucloxacillin acceptable? |
| Sulbactam-durlobactam for K. pneumoniae, E. coli, P. aeruginosa, S. aureus (4) | unverified | Spectrum limited to *Acinetobacter*. |
| A. baumannii: 1st, 2nd and 3rd-gen (non-antipseudomonal) cephalosporins, ceftaroline, aztreonam-avibactam, nitrofurantoin (6) | unverified | Does EUCAST list cefotaxime/ceftriaxone for *A. baumannii*? |
| P. aeruginosa: ampicillin-sulbactam, 1st and 2nd-gen cephalosporins, ceftaroline, nitrofurantoin (5) | unverified | |
| S. aureus: aztreonam-avibactam, cefiderocol (2) | unverified | No useful Gram-positive activity. |

### 4.5 Not in any CSV but still to check

- **AWaRe groups** were reconciled on 2026-11-18 against `WHO-AWaRe-classification-2025.xlsx`, and `tests/test_seed_data.py::test_verified_drugs_match_aware_2025` re-checks them. 46 of 49 drugs matched as first written. The three to look at:
  - **Aztreonam-avibactam**: Reserve in AWaRe 2025, not listed in 2023. Changed from `Unclassified` to `Reserve`.
  - **Minocycline and fosfomycin**: one ATC code each, but AWaRe lists IV (Reserve) and oral (Watch) separately. Both use the IV group (Reserve), which is the form relevant to resistant infections; minocycline was changed from Watch. A route-specific node would need a contract change.
  - **Sulbactam-durlobactam**: in neither the 2023 nor the 2025 list. It stays `Unclassified`, with `id_verified: false` although its ATC code J01CG30 is confirmed on the WHOCC index.
- **AWaRe class names differ from the reasoning classes**, as intended (D6). AWaRe 2025 files ceftolozane-tazobactam under "Fifth-generation cephalosporins", ceftazidime-avibactam under "Third-generation cephalosporins", and dalbavancin/oritavancin under "Glycopeptides". The loader must take `class_id` from `scope.yaml`, not from the AWaRe class column.
- **Ceftolozane-tazobactam versus AmpC** (plasmid CMY): kept active, but activity is reduced in AmpC-producing Enterobacterales.
- **Cefiderocol versus NDM**: kept active. Some NDM producers have raised MICs.
- **Cefepime versus PDC overproduction**: kept active. Many derepressed mutants are cefepime non-susceptible.
- **Fosfomycin versus K. pneumoniae**: kept active. *K. pneumoniae* carries chromosomal *fosA* and often tests less susceptible.
- **OXA-48-like versus narrow-spectrum cephalosporins** (cefazolin, cefuroxime): no edge was added. Confirm whether one is needed.

## 5. Known simplifications

1. **One mechanism at a time.** The worked example and the graph templates reason about a single mechanism. Real isolates carry several (NDM + CTX-M + 16S RMTase is common). The graph supports combining them, by taking the union of exclusions over all of an isolate's mechanisms, and the query templates (T10) should offer that.
2. **Presence, not expression level.** Porin changes, efflux, inoculum effects and gene copy number change MICs; none is modelled except OprD loss and PDC overproduction.
3. **Mechanism-level activity is not a recommendation.** "Remaining" means no modelled resistance mechanism defeats the drug. It does not mean the drug is suitable for an infection site, a patient group or monotherapy. Examples: nitrofurantoin is for lower urinary tract infection only, and aminoglycosides and polymyxins are usually combination partners. Those judgements come from the `Recommendation` nodes.
4. **Families stand in for variants.** CTX-M stands for all CTX-M variants, and OXA-48-like for OXA-48/181/232/244. Variant differences, such as KPC variants that resist ceftazidime-avibactam (KPC-31 and others), are not modelled.
5. **Intrinsic resistance is per class** (section 2.4).
6. **Only the five pathogens.** Synonyms such as `Klebsiella` resolve to the in-scope species.
7. **Not modelled:** chromosomal colistin resistance (mgrB, pmrAB, lpx), *A. baumannii* ADC overproduction, efflux pumps (MexAB-OprM, AdeABC), VISA/hVISA, vanA in *S. aureus*, and target mutations (gyrA/parC). This is why fluoroquinolones are never excluded by a mechanism.

## 6. Candidate additions (not done)

- Drugs: ceftobiprole (needs a class split, section 2.1), cefoxitin (would give an AmpC vs ESBL contrast), temocillin, cefoperazone-sulbactam (common in Indian practice, relevant to ICMR), cefepime-enmetazobactam, doripenem, rifampicin and fusidic acid (anti-staphylococcal adjuncts).
- Mechanisms: IMP (class B), DHA (plasmid AmpC), SHV/TEM ESBLs, ADC overproduction, gyrA/parC mutations, chromosomal colistin resistance.

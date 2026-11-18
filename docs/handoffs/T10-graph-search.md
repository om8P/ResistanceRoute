# Handoff: T10 Cypher templates, reasoning rules and path output

- **Model:** Opus 5.5
- **Status:** complete
- **Date:** 2026-11-18

## What was built

`retrieval/graph_search.py` provides `graph_search(parsed: ParsedQuery) -> GraphResult` (CONTRACTS §7, dataclasses imported from T12's `retrieval/types.py`). It runs parameterised Cypher templates from `retrieval/cypher/` and applies these rules in Python:
- class-family expansion (D29);
- the union exclusion rule over several mechanisms;
- one group per mechanism when no mechanism is named;
- D33/D34 recommendation filtering, with the §3.3 caveats;
- the REVIEW_NOTES §3 co-production caveats;
- a regimen rule for "base plus partner" combinations.

Every answer has at least one path from the question's entities, with each relationship's provenance. The KPC, NDM and OXA-48-like answers reproduce REVIEW_NOTES §3 exactly. All queries are read-only (`execute_read`).

## Files created or changed

| Path | What it is |
|---|---|
| `retrieval/graph_search.py` | `graph_search(parsed, driver=None)`; also `load_template`, `rec_caveats`, `rec_drug_order`, constants `ACTIVE_SCORE`, `RESCUED_SCORE`, `PROVENANCE_KEYS` |
| `retrieval/cypher/alternatives.cypher` | Per drug: exclusion reasons (intrinsic, class-level, drug-level, reported phenotype) for one pathogen and a **list** of mechanisms |
| `retrieval/cypher/mechanisms.cypher` | The pathogen's mechanisms (plus named ones), with `HAS_MECHANISM` provenance and the reported classes each confers. Forms the groups |
| `retrieval/cypher/recommendations.cypher` | Every recommendation for a pathogen, with mechanisms, drugs, guideline and `SUPPORTS` passages |
| `retrieval/cypher/why_restricted.cypher` | Drug, its class, defeating mechanisms with their carriers, intrinsic resistance, recommendations, restrictive passages |
| `retrieval/cypher/mechanism_lookup.cypher` | The pathogen's mechanisms restricted to the classes/drugs asked about, plus intrinsic resistance |
| `retrieval/cypher/drug_profile.cypher` | Class, family, AWaRe group and recommendations of drugs, or of every drug in the named classes |
| `retrieval/cypher/surveillance.cypher` | GLASS statistics for a pathogen and a list of drug/class targets, with an optional country and year |
| `retrieval/cypher/class_families.cypher` | Family → class IDs (D29) |
| `retrieval/cypher/entities.cypher` | Names and labels of IDs, and a drug's class |
| `tests/test_graph_search.py` | 31 tests: 4 without a database, 27 read-only against Neo4j (skipped if it is unreachable) |

## How to run and check it

```bash
.venv/Scripts/python -m pytest tests/test_graph_search.py -v
```

```bash
.venv/Scripts/python -m pytest tests
```

```python
from retrieval.parser import parse
from retrieval.graph_search import graph_search
r = graph_search(parse("Which antibiotics remain for NDM-producing K. pneumoniae?"))
```

## Test result

`664 passed, 2 warnings in 32.74s` (`.venv/Scripts/python -m pytest tests`, Neo4j running, no skips). That includes all 31 tests in `tests/test_graph_search.py`. The 2 warnings are Click deprecation warnings from `typer`.

## What I found

### Rules as implemented

- **Groups.**
  - Mechanisms named: one group with all of them (union of exclusions); the group name joins them with " + ".
  - No mechanism but resistant classes: one group per mechanism of the pathogen that `CONFERS_RESISTANCE_TO` one of those classes. For CRKP that is KPC, NDM, OXA-48-like and VIM.
  - No mechanism of the pathogen explains the reported resistance: one group, "reported resistance only", with a caveat.
  - Several pathogens: groups are prefixed with the pathogen name.
- **Exclusion** = `INTRINSICALLY_RESISTANT_TO` ∪ `CONFERS_RESISTANCE_TO` of any mechanism ∪ `INACTIVATES` of any mechanism ∪ the classes the question reports resistant (`class_ids` plus families). The last part is a phenotype with no edge. It matters when the named mechanism does not explain the phenotype, for example CTX-M *E. coli* reported carbapenem-resistant.
- **Recommendations (D34).**
  - A row whose `FOR_MECHANISM` meets the group's mechanisms is always kept. Its excluded drugs are returned with score 0.25, the caveat "Not active on its own here: …" and the §3.3 caveat.
  - A co-producer row (NDM + OXA-48) also appears in the NDM-only group, with the caveat "The recommendation is for isolates that also produce …".
  - A row tied only to other mechanisms is skipped.
  - Rows without a mechanism are filtered: `any-of` drug by drug; `single` and two-drug `combination` as a unit; base-plus-partner rows by the rule below.
- **Scores:** 1.0 / 0.9 / 0.8 / 0.7 for active drugs recommended at first / second / alternative / last-resort line (the best line counts), 0.5 for active drugs with no recommendation, 0.25 for drugs that are excluded on their own and returned only because of D34. **Use `score >= 0.5` for "active".** In `recommendation_lookup` with an infection site, rows with no site rank 0.05 below rows for the asked site.
- **Co-production caveats (REVIEW_NOTES §3).** These are computed from the data, not hard-coded. If the group has a carbapenemase and no ESBL, and the pathogen has CTX-M recorded, then each drug active for the group but excluded for the group + CTX-M gets "Active against X alone only … Ask about X + CTX-M for the realistic answer."
  - For NDM this hits aztreonam.
  - For OXA-48-like it hits the 1st–4th generation cephalosporins, ceftaroline and aztreonam, but not ceftazidime-avibactam or cefiderocol (tested).
  - It also fires for VIM in *K. pneumoniae*, which REVIEW_NOTES does not mention. The reasoning is the same.
- **Caveats** that come from one recommendation are prefixed with its ID, so caveats from several rows on one answer stay apart.

### Regimen rule (task step 9)

- **A `combination` with 2 drugs is a fixed pair.** The 6 ceftazidime-avibactam plus aztreonam rows and ICMR 2019 :007 (colistin plus imipenem-cilastatin). Both drugs are shown, each with "Only together with <other> (combination)". Without a mechanism it is judged as a unit (D34).
- **A `combination` with 3 or more drugs is "a base plus one other active agent".** That is 10 rows: the 6 Table 4 polymyxin rows (:002, :006, :010, :015, :019, :023), :027, CRAB :031, CRPA :039 and ICMR 2019 :009.
  - **The base** is the drug(s) in the same class as the first drug in the curated `drug_ids` order: the polymyxins, ampicillin-sulbactam for :031, fosfomycin for :009. The rest are partners.
  - **Base drugs** get the caveat "Only as the base of a combination: colistin plus one other active agent (tigecycline, gentamicin, …)".
  - **Partners** get "Only as a combination partner of colistin or polymyxin B, not on its own". So tigecycline or an aminoglycoside from these rows never looks like a stand-alone recommendation.
  - **Without a mechanism** the row is kept when at least one base drug and one partner are active. Excluded partners are left out and named ("Partners left out because they are excluded here: meropenem (KPC confers resistance to Carbapenems)").
  - **With a mechanism** (D34) all drugs are shown, and the excluded carbapenem partners get the "MIC is low" caveat.
  - The rule is tested with :027 and :010 for KPC.

### Example output, one question per intent (questions parsed by T12's `parse`)

**alternatives**: "Which antibiotics remain for NDM-producing K. pneumoniae?" gives 22 answers, 50 paths, 50 entity IDs, one group "NDM beta-lactamase":

| Answer | AWaRe | Score | Recs | First caveats |
|---|---|---|---|---|
| amikacin | Access | 1.0 | 3 | `:002`: Only as a combination partner of colistin or polymyxin B, not on its own. `:004`: Restricted to: uncomplicated UTI; source-controlled infection. |
| aztreonam | Reserve | 1.0 | 3 | `:001`: Only together with ceftazidime-avibactam (combination). … Active against NDM alone only. NDM alone does not hydrolyse aztreonam, … Ask about NDM + CTX-M for the realistic answer. |
| cefiderocol | Reserve | 0.7 | 1 (WHO :001) | |
| aztreonam-avibactam, ciprofloxacin, … | | 0.5 | 0 | |
| ceftazidime-avibactam | Reserve | 0.25 | 3 (:001, :013, WHO :006) | Not active on its own here: NDM beta-lactamase inactivates ceftazidime-avibactam. `:001`: Only together with aztreonam (combination). `:001`: Ceftazidime-avibactam alone is inactive against NDM; here avibactam protects aztreonam, so use the two together only after a synergy test. |
| meropenem, imipenem-cilastatin | Watch | 0.25 | 1 (:002) | NDM defeats carbapenems; a carbapenem is listed only as a polymyxin partner when the measured carbapenem MIC is low. |

Active beta-lactams for KPC, NDM and OXA-48-like are exactly the three sets in REVIEW_NOTES §3, plus the same 16 non-beta-lactams. "If carbapenem resistance is reported for Klebsiella…" gives the four groups KPC, NDM, OXA-48-like and VIM. A path for an active, recommended drug:

```
Klebsiella pneumoniae <-[FOR_PATHOGEN curated-seed/curated]- REC:…:027 -[RECOMMENDS curated-seed/curated]-> amikacin
                                                     REC:…:027 -[FROM curated-seed/curated]-> ICMR CR guidance (2022)
```

Each active drug also has the path `Pathogen -[HAS_MECHANISM]-> Mechanism -[NOT_EXCLUDED derived]-> Drug -[IN_CLASS]-> DrugClass`. Each excluded drug has its exclusion edge as a path (for example `K. pneumoniae -[HAS_MECHANISM]-> NDM -[INACTIVATES]-> ceftazidime-avibactam`).

**recommendation_lookup**: "What is recommended for MRSA bloodstream infection?" (mecA, site "bloodstream infection") gives 4 answers:
- teicoplanin (1.0; CLABSI :001, sepsis :016);
- vancomycin (1.0);
- daptomycin (0.8; CLABSI :002);
- linezolid (0.75; WHO :010, which names no site).

HAP/VAP rows are left out, and no beta-lactam is returned. Path: `S. aureus -[HAS_MECHANISM]-> mecA <-[FOR_MECHANISM]- REC -[RECOMMENDS]-> teicoplanin`, then `REC -[FROM]-> ICMR 2019`. As `alternatives`, MRSA leaves vancomycin, teicoplanin, linezolid, tedizolid, daptomycin, dalbavancin, oritavancin, clindamycin and the other non-beta-lactams; the only beta-lactam is ceftaroline (tested).

**why_restricted**: "Why is colistin restricted?" gives 11 answers:
- colistin, AWaRe Reserve, with 5 last-resort recommendation IDs and the caveats "WHO AWaRe Reserve: kept as a last-resort option…" and "AWaRe group from WHO AWaRe 2025";
- *Defeated by*: MCR phosphoethanolamine transferase ("confers resistance to Polymyxins (found in E. coli, K. pneumoniae)", plus the CARD note);
- *Intrinsically resistant*: *S. aureus*;
- *Kept as last resort*: 5 recommendations, each with guideline, year and pathogen;
- *Guideline text*: 3 passages that mention colistin and Reserve or last-resort wording.

Paths: `colistin -[IN_CLASS]-> Polymyxins <-[CONFERS_RESISTANCE_TO]- MCR <-[HAS_MECHANISM]- E. coli`, `colistin <-[RECOMMENDS]- REC -[FROM]-> Guideline` with `SUPPORTS` passages, and `colistin <-[MENTIONS]- Passage`.

**mechanism_lookup**: "How does E. coli resist cephalosporins?" gives CMY (AmpC), CTX-M (ESBL), KPC, NDM and VIM. Each lists the cephalosporin classes it confers resistance to and the curated note. VIM's note says it is flagged for review. MCR and OXA-48-like are not returned. Path: `E. coli -[HAS_MECHANISM curated-seed/curated]-> CMY -[CONFERS_RESISTANCE_TO curated-seed/curated]-> Second-generation cephalosporins`.

**drug_profile**: "What class and AWaRe group is meropenem?" gives meropenem, Watch, group "Carbapenems (antipseudomonal group 2)", caveat "Class family: carbapenem", 9 recommendation IDs. Path: `meropenem -[IN_CLASS]-> Carbapenems (antipseudomonal group 2)`. The family `carbapenem` alone gives meropenem, imipenem-cilastatin and ertapenem (both classes) and not meropenem-vaborbactam (tested).

**surveillance**: "How common is carbapenem resistance in Klebsiella in India?" gives the latest year per target, with `score` = fraction resistant:

| Target | Statistic |
|---|---|
| meropenem | IND 2023: 62.8% resistant (n=8610) |
| ertapenem | IND 2023: 66.8% (n=4870) |
| imipenem-cilastatin | IND 2023: 62.2% (n=9065) |
| class Carbapenems | IND 2021: 60.7% (n=7183), with the caveat that GLASS "Carbapenems" is linked to the meropenem/imipenem class only |

Path: `K. pneumoniae <-[ABOUT_PATHOGEN glass/rule]- GLASS:IND:2023:NCBITaxon:573:J01DH02 -[ABOUT_DRUG glass/rule]-> meropenem`.

### Notes for T14 and T15

- `GraphResult.cypher` holds the template text of every query run, without comments.
- `entity_ids` includes Recommendation, Guideline and (in `why_restricted`) Passage IDs as well as the domain entities.
- Answers are not always drugs. `label` is `Drug`, `Mechanism`, `Pathogen`, `DrugClass`, `Recommendation`, `Passage` or `SurveillanceStat`, depending on the intent.
- `alternatives` with a pathogen but no mechanism and no resistant class returns no answers, with `empty_reason` "names no resistance". `drug_ids` are not used by `alternatives`. In `recommendation_lookup` they restrict the result to rows that name those drugs, when any do.

## Deviations from the brief or contracts

- **Two extra keys in each path step:**
  - `direction` (`"out"`: the previous node → this node; `"in"`: this node → the previous node);
  - `from_node_id` (the node the relationship attaches to).

  The guideline step attaches to the recommendation, not to the drug before it, so a path is not strictly linear. This keeps the guideline and year on every recommendation path. The first step has `rel_type` `None`.
- **Derived steps.** "Drug is active" has no edge, so the path uses `rel_type` `NOT_EXCLUDED` with `rel_props` `{method: "derived", derived: true, derived_from: "curated-seed", rule: "No INTRINSICALLY_RESISTANT_TO, …"}` and `source_id` `None`. The `HAS_MECHANISM` step for a mechanism named in the question but not recorded for the pathogen is also derived. Every `rel_props` always has `source_id`, `method`, `evidence_sources` and `needs_review`; `evidence_sources` is the stored `|`-separated string, or `None` on non-curated edges.
- **`graph_search(parsed, driver=None)`:** an optional driver argument, used by the tests. The default is a module-level driver from `pipeline.graph_db.get_driver()`. If Neo4j is unreachable, `empty_reason` says so instead of raising.
- **Reads two curated files, read-only:**
  - `RECOMMENDATION_NOTES.md` §3.3, for the 11 D34 caveats (the table is parsed; there is a generic fallback text);
  - `recommendations_curated.csv`, for the order of `drug_ids` (the graph does not keep it).
- **Several templates per intent:** `alternatives` and `recommendation_lookup` share `mechanisms`, `alternatives` and `recommendations`. There are two helpers, `class_families` and `entities`. Each intent still has its own main template.

## Not done or not verified

- The clinical content of the caveat sentences I wrote (co-production, base/partner, AWaRe groups) has not been reviewed by a clinician. The D34 caveats are T08's text.
- `why_restricted` finds "guideline text" by keyword (`reserve`, `last resort`, `restrict`, `stewardship`) among passages that `MENTION` the drug. It is not ranked by relevance; T14 may prefer T11's ranking.
- Surveillance without a country returns the 10 latest statistics with the most isolates tested. That is a display choice, not something the brief asked for.
- Infection-site matching uses a small word map (`SITE_WORDS`) on `infection_site` only, so it is not semantic.
- Not tested: several pathogens in one question, and VIM for *P. aeruginosa*. Both run, but have no test.

## Requests to orchestrator

1. **Keep drug order or mark the base drug on `Recommendation` (data problem).** `RECOMMENDS` edges have no order, so the base-plus-partner rule reads `drug_ids` order from the curated CSV. Better: a `base_drug_ids` property or a `position` on `RECOMMENDS`, or a fourth `regimen_type` value such as `base-plus-one`. Then fixed pairs and "polymyxin plus one partner" rows are not both `combination`.
2. **Put the D34 caveats in the data.** They exist only as a Markdown table in `RECOMMENDATION_NOTES.md` §3.3, which I parse. A `caveat` column on `recommendations_curated.csv` (a `Recommendation` property) would be more robust.
3. **Mechanism-free fixed pair :029** (ceftazidime-avibactam plus aztreonam, carbapenemase unknown) is dropped for NDM by the D34 unit rule. NDM is exactly the case it is for. The NDM-specific rows :001/:013 cover it for *K. pneumoniae*, so no answer is lost today. If more such rows appear, consider T08's suggestion (§3.1): keep a combination when the excluded partner is a BL/BLI that protects an active partner.
4. **Mechanism-free rows for susceptible isolates.** Some rows are for susceptible organisms but carry no mechanism: ICMR 2019 :006 is for carbapenem-susceptible *E. coli*, WHO :020 (ciprofloxacin) for mild pyelonephritis, and MSSA :003 states it only in `patient_group`. The exclusion rule drops them when their drugs are excluded. When the drugs stay active, they are attached as supporting recommendations to resistant-organism answers, for example WHO :020 on ciprofloxacin for carbapenem-resistant *E. coli*. A `susceptible-only` flag or a phenotype column would let T10 drop them.
5. **Passage text encoding (T06):** some passages contain U+FFFD replacement characters, for example a colistin passage shown as "…iae (CRKP) poses…" with a replacement character before it.
6. **D-numbers for the rules above** if you accept them: the base-plus-partner regimen rule, the phenotypic exclusion of reported classes, and the data-driven co-production caveat.

## Follow-up (2026-11-18, after orchestrator review: D39–D41)

**D40: the new columns are read, and the fallbacks are removed.** T08's `caveat`, `base_drug_ids` and `susceptible_only` columns were present in `recommendations_curated.csv` before I finished. `rec_meta()` reads them by column name; `rec_caveat(rec_id)` gives the D34 caveat.
- Before removing the fallbacks I checked them against the columns. All 11 caveats are identical to the old Markdown table. The `base_drug_ids` of all 10 base-plus-partner rows equal what the old drug-order rule gave.
- I then removed the Markdown parsing (`rec_caveats`) and the drug-order rule (`rec_drug_order`).
- A `combination` row is now base-plus-partner exactly when `base_drug_ids` is not empty. Otherwise it is a fixed unit.
- `drug_ids` order is still read, but only to list partners in a stable order.

**D41: `susceptible_only` rows are dropped** whenever the group names a mechanism or a resistant class. Six rows are flagged: WHO :019, :020, :021, :023 and ICMR 2019 :003, :006. A question with no resistance (for example `recommendation_lookup` for *E. coli* alone) still shows them. Effect: ciprofloxacin for carbapenem-resistant *E. coli* no longer carries WHO :020, and is listed as only not excluded.

**D39: `recommendation_ids` is not empty exactly for drugs that come from a recommendation.** Drugs that are only not excluded have an empty list and score 0.5; recommended drugs score 0.7–1.0, or 0.25 when kept by D34. This held already and is now tested. For "If carbapenem resistance is reported for Klebsiella, which guideline-listed alternatives remain?", the recommended drugs per mechanism are (* = excluded alone, kept by D34):

| Mechanism | Recommended / all answers | Recommended drugs |
|---|---|---|
| KPC | 12 / 23 | ceftazidime-avibactam, meropenem-vaborbactam, plazomicin, colistin, polymyxin B, tigecycline, gentamicin, amikacin, fosfomycin, doxycycline, meropenem*, imipenem-cilastatin* |
| NDM | 12 / 22 | aztreonam + ceftazidime-avibactam*, cefiderocol, colistin, polymyxin B, tigecycline, gentamicin, amikacin, fosfomycin, doxycycline, meropenem*, imipenem-cilastatin* |
| OXA-48-like | 11 / 29 | ceftazidime-avibactam, aztreonam (from the co-producer row :013 and the unknown-type row :029), colistin, polymyxin B, tigecycline, gentamicin, amikacin, fosfomycin, doxycycline, meropenem*, imipenem-cilastatin* |
| VIM | 7 / 19 | colistin, polymyxin B, tigecycline, gentamicin, amikacin, fosfomycin, doxycycline (no VIM row exists for *K. pneumoniae*; all of these come from mechanism-free rows) |

Most of each list is the polymyxin-plus-partner option. T14 can tell those drugs apart by their "Only as the base / Only as a combination partner" caveats. Doxycycline comes only from ICMR 2019 :009 (isolates resistant to carbapenems *and* colistin, stated in `patient_group`).

**Tests:** `tests/test_graph_search.py` now has 33 tests.
- New: `test_guideline_listed_alternatives_for_crkp` (D39) and `test_susceptible_only_rows_are_dropped_for_resistant_organisms` (D41; it also checks, with the flag patched off, that the filter is what removes the row).
- `test_curated_columns_are_read` replaces the drug-order test, and the caveat test now uses the column.

**Test result:** `671 passed, 2 warnings in 37.65s` (`.venv/Scripts/python -m pytest tests`, Neo4j running, no failures).

**Not changed:** request 3 (row :029) and request 5 (U+FFFD), as decided. The graph's `Recommendation` nodes do not have the three new properties yet, so they are read from the CSV. If the core build adds them to the nodes, the code can read them from the recommendations template instead.

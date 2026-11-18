# Handoff: T07 Entity matcher and linker

- **Model:** Sonnet 5.5
- **Status:** complete (corpus run, validation and a 50-mention precision check done; see "Follow-up" at the end)

## Corpus run (2026-11-18, after T06 wrote `passages.jsonl`)

`python -m pipeline.link` over 1,428 passages: 13,113 candidate mentions, 9,720 linked (6,753 exact, 2,895 normalised, 72 fuzzy), 3,822 `MENTIONS` edges, 317 unlinked surfaces. The 25 most frequent fuzzy links are all real typos or extraction errors in the PDFs ("azteronam", "Ciprofioxacin", "fiucloxacillin", "Klebsiella pneumonia"); I did not label the whole run, so no precision figure. Edges were not validated with `pipeline/validate.py`.

**Top 20 unlinked surfaces (real corpus):** enterobacterales 334, carbapenemase 272, carbapenemases 212, azithromycin 114, enterobacteriaceae 96, Streptococcus pneumoniae 89, β-lactamase 88, Streptococcus pyogenes 79, sulbactam 75, Clostridioides difficile 73, β-lactamases 65, beta-lactamases 59, piperacillin 59, Neisseria gonorrhoeae 58, cefalexin 58, Haemophilus influenzae 52, tazobactam 49, cefoperazone 48, clarithromycin 44, IMP 40. Almost all are outside the five-pathogen and 49-drug scope; `piperacillin`, `tazobactam` and `cefalexin` alone suggest synonym checks (the first two are parts of the combination, `cefalexin` is the INN spelling of cephalexin and is not in scope).
- **Date:** 2026-11-18

## What was built

`pipeline/link.py` holds `EntityLinker`, built from `schema/synonyms.csv`, `schema/scope.yaml` and `schema/phenotypes.csv`. `link(text)` finds mentions with spaCy `PhraseMatcher` (`spacy.blank("en")`; abbreviations case-sensitive, other types case-insensitive; longest match wins) and then adds near-miss spellings with `rapidfuzz`. `resolve(surface, entity_type=None)` goes exact, normalised, fuzzy. The same file has the corpus CLI (`python -m pipeline.link`) and a scorer for the gold file (`--eval`). `eval/linking_gold.csv` has 164 rows over 100 texts (149 mentions, 15 sentences with no entity). `tests/test_link.py` has 45 tests.

## Files created or changed

| Path | What it is |
|---|---|
| `pipeline/link.py` | `EntityLinker`, `LinkedEntity`, `LinkedMention`, `run_corpus`, `evaluate_gold`, CLI |
| `eval/linking_gold.csv` | `text,surface,entity_type,entity_id`; empty surface/type/id = sentence with no entity |
| `tests/test_link.py` | 45 tests |
| `data/processed/mentions.jsonl`, `mentions_linked.jsonl`, `unlinked.csv`, `edges_MENTIONS.csv` | **Not written** (see "Not done") |

## How to run and check it

```bash
.venv/Scripts/python -m pytest tests/test_link.py
```

```bash
.venv/Scripts/python -m pipeline.link
```

```bash
.venv/Scripts/python -m pipeline.link --eval
```

The second command reads `data/processed/passages.jsonl` (`--passages` and `--out-dir` override the paths). `--eval` prints accuracy, precision and recall on the gold file, and each error on stderr.

## Test result

`411 passed, 2 warnings in 12.72s` for `.venv/Scripts/python -m pytest tests` (2026-11-18, whole suite, including other tasks' files). The 2 warnings are `click` deprecation notices from `typer`.

**Scores on `eval/linking_gold.csv`** (149 gold mentions, 149 predicted): accuracy 1.000 (over all 164 rows; a no-entity sentence counts as correct when nothing is linked), precision 1.000, recall 1.000. Read this with care: I wrote the gold file and the linker, so it is not independent. The gold file exposed three real defects while I built it, and I fixed them (a sentence-final "mecA." that spaCy keeps in one token; "Pseudomonas aeruginsa" swallowed by the bare genus match; one wrong gold label of mine). Real text was a harder test than the gold file; see the next section.

## What I found

**Proxy run on real text.** Because T06's file was missing, I ran the linker on the 319 PubMed abstracts in `data/raw/pubmed/abstracts.jsonl` (title + abstract as one passage; outputs in my scratchpad only, not in `data/processed/`). Result: 6,043 candidate mentions, 4,713 linked (3,834 exact, 865 normalised, 14 fuzzy), 1,444 passage–entity edges, 178 unlinked surfaces. The first pass produced false links on this real text ("methicillin-resistant" → mecA, "Cefotaximases" → cefotaxime, fuzzy windows across sentence boundaries, "CROs" → ceftriaxone, "C-T" → ceftolozane-tazobactam, "CTX-M-27" → cefotaxime). All are fixed and covered by tests; the 14 fuzzy links left are real typos ("vancomyin", "Klebsiella pneumonia", "Acinetobactor baumannii", "Ceftolozan-tazobactam", ...). I read the non-exact links by eye but did not label the proxy run, so I give no precision number for it.

**Behaviour the next tasks need:**

- **Result fields.** `LinkedEntity`: `entity_id, entity_type, canonical_name, match_type, score, synonym, phenotype, pathogen_ids, mechanism_ids, class_family, alternatives`. `LinkedMention` adds `passage_id, start, end, surface`. `to_row()` gives the `mentions_linked.jsonl` row; phenotype mentions carry four extra keys (`phenotype, pathogen_ids, mechanism_ids, class_family`), and every row also has `canonical_name`.
- **Scores:** exact 1.0, normalised 0.97, numbered-allele fallback 0.93, fuzzy = rapidfuzz ratio / 100 capped at 0.95. `match_type` is `exact`, `normalised` or `fuzzy`.
- **Normalisation** ignores case (not for abbreviations), hyphens, slashes, plus signs, dots, Greek letters, "and"/"plus", a trailing plural s, and letter/digit joins (`OXA48` = `OXA-48`).
- **Fuzzy guards (common words are not linked):** at least 5 characters, same first letter, same digits, same word count, at most one typo per word (a transposition counts as one) and two in total, ratio ≥ 85, and never on abbreviations. A window cannot overlap an exact mention unless it extends one for the same entity. A test links about 70 ordinary and out-of-scope words (for example "colitis", "tetracyclic", "cephalexin", "gentle", "minimal") and none links.
- **Combinations:** `ceftazidime-avibactam`, `/`, `+`, ` + `, en dash, `and`, `CZA`, `CAZ-AVI`, `CAZ/AVI` all link once to the combination, never also as the single drug. Two unrelated drugs ("meropenem plus colistin") stay two.
- **Phenotypes:** MRSA gives pathogen 1280 plus mecA (ARO:3009312); CRKP gives 573 plus `class_family` `carbapenem`; acronyms absent from `synonyms.csv` (CRE, ESBL-E, ESBL-EC, ESBL-KP) are added from `phenotypes.csv`. For a phenotype that spans species (CRE, ESBL-E), `entity_id` is the first pathogen, `pathogen_ids` lists all, and `ambiguous_pathogen` is true.
- **ClassFamily wins over DrugClass** when one string names both (`carbapenems`); the other reading is in `alternatives`, and `resolve(..., entity_type="DrugClass")` returns it.
- **Lowercase acronyms do not link** (`mrsa`, `cza`, `mem`), as the contract requires. T12 may want to retry a question token in upper case. Drug codes are also never pluralised or re-spaced (`CROs`, `C-T`).
- **Bare genus names** link to the in-scope species (T03 simplification), except when the next word is a species outside scope ("Klebsiella oxytoca", "Pseudomonas putida"). That list (`OTHER_SPECIES`) is my own domain knowledge and short.
- **Numbered alleles** of a family that has numbered synonyms (KPC-14, blaNDM-9, CTX-M-27, mcr-5) link to the family at 0.93. `OXA-*` is excluded because the number decides the family (OXA-48-like vs OXA-23-like), so `OXA-58` stays unlinked.
- **Edges:** the `edges_MENTIONS.csv` writer follows D27: one row per passage–entity pair with the best score, `source_id` `curated-seed`, `method` `rule`, `evidence_passage_id` = the passage. It writes `Pathogen`, `Drug`, `DrugClass`, `Mechanism` only. `ClassFamily` and `Gene` are left out, and a phenotype spanning several species gives no pathogen edge.
- **`mentions.jsonl`** holds linked mentions plus unlinked entity-like strings found by regex rules (drug suffixes, `bla*`/`mcr-*`/OXA-style genes, species names), with a guessed `entity_type`. `mentions_linked.jsonl` has only the linked ones.

**Top 20 unlinked surfaces: proxy run on PubMed abstracts (not the real corpus):**

| Surface | Guessed type | Count |
|---|---|---|
| carbapenemase | Mechanism | 221 |
| enterobacterales | Pathogen | 131 |
| carbapenemases | Mechanism | 130 |
| β-lactamase | Mechanism | 80 |
| enterobacteriaceae | Pathogen | 74 |
| β-lactamases | Mechanism | 56 |
| sulopenem | Drug | 39 |
| taniborbactam | Drug | 27 |
| metallo-β-lactamase | Mechanism | 26 |
| avibactam | Drug | 16 |
| Enterobacter cloacae | Pathogen | 15 |
| IMP | Mechanism | 15 |
| beta-lactamase | Mechanism | 15 |
| blaNDM-1 | Mechanism | 14 |
| efflux pumps | Mechanism | 14 |
| enmetazobactam | Drug | 14 |
| metallo-β-lactamases | Mechanism | 13 |
| zidebactam | Drug | 13 |
| OXA | Mechanism | 12 |
| sulbactam | Drug | 12 |

The real list will come from `data/processed/unlinked.csv` after the corpus run.

**Suggested synonym additions for T03 (their files, not edited by me):**

- Most of the list above is out of scope or deliberately unmapped (REVIEW_NOTES §2.5: `carbapenemase`, `metallo-β-lactamase`, `β-lactamase`, `efflux pumps`, `Enterobacterales`). I suggest no mapping for these; a question parser may use them as hints.
- `blaNDM-1` is still unlinked 14 times and I did not find why (the allele fallback links most `bla…-n` forms). Adding `blaNDM-1`, `blaKPC-2`, `blaOXA-181`, `blaCTX-M-15` as explicit variants would cover it.
- Candidate mechanism rows if the scope grows: OXA-58-like, OmpK35/OmpK36 (porin loss, not modelled), IMP, GES. I did not look up ARO accessions, so I give none.
- Candidate drugs only if a task needs them: sulbactam and avibactam on their own (inhibitors, no J01 code of their own), sulopenem, taniborbactam, enmetazobactam, zidebactam.
- `Enterobacter cloacae`, `Stenotrophomonas maltophilia`, `Serratia marcescens` are outside the five-pathogen scope.

## Deviations from the brief or contracts

- **More than "about 100" mentions in the gold file:** 149 mentions (164 rows) over 100 texts, because most sentences carry several mentions.
- **`mentions_linked.jsonl` carries extra keys** beyond CONTRACTS §6 (`canonical_name`, and four phenotype keys on phenotype mentions).
- **`mentions.jsonl` also lists unlinked candidates**, not only linked mentions (CONTRACTS §6 does not say either way).
- **Two additions beyond the brief:** the numbered-allele fallback and the other-species guard.
- **Fuzzy cutoff 85:** with at most one typo per word a lower ratio is safe, and an 8-letter drug with one typo (`imipenam`) scores 87.5.

## Not done or not verified

- **Corpus run not done.** `data/processed/passages.jsonl` did not exist, so `mentions.jsonl`, `mentions_linked.jsonl`, `unlinked.csv` and `edges_MENTIONS.csv` are not written. Run `.venv/Scripts/python -m pipeline.link` once T06 has finished; it exits with code 1 and a message if the input is missing. The writer code is exercised by `test_corpus_run_writes_contract_files` on a two-passage corpus, and by the proxy run.
- Linking accuracy on the real corpus, and the real top-20 unlinked list, are unknown until then.
- The gold file is not independent of the linker (same author); no precision was measured on the proxy run.
- Edges were not validated with `pipeline/validate.py` or loaded into Neo4j.
- Speed on the full corpus is untested; the proxy run (319 abstracts) took a few seconds.

## Requests to orchestrator

1. **Run the corpus step** after T06, or tell me to (a short follow-up for this session).
2. **CONTRACTS §6:** record the extra optional keys on `mentions_linked.jsonl` rows, the score scale (1.0 / 0.97 / 0.93 / ≤0.95), and that `mentions.jsonl` includes unlinked candidates.
3. **T12:** decide how the query parser treats lowercase acronyms (`mrsa`, `cza`); the linker follows the case-sensitive rule and will not link them. It must also use `ambiguous_pathogen` / `pathogen_ids` for CRE and ESBL-E.
4. **T05 loader:** `edges_MENTIONS.csv` start nodes are `Passage` ids from T06, so Passage nodes must be loaded first; `models.EDGE_TYPES["MENTIONS"]` has no `Gene` target, so no Gene edges are written.

## Follow-up (2026-11-18, after orchestrator review)

- **Corpus run:** `python -m pipeline.link` over `passages.jsonl` (1,428 passages, 26 s) wrote the four outputs: 13,113 candidate mentions, 9,720 linked, 3,822 `MENTIONS` edges, 317 unlinked surfaces.
- **Validation:** `python -m pipeline.validate data/processed` accepted `edges_MENTIONS.csv` (3,822 rows, 0 rejected); the whole directory is 50,309 rows accepted, 0 rejected. Nothing was loaded into Neo4j.
- **Independent precision on the real corpus:** 50 linked mentions sampled with `random.seed(7)` from `mentions_linked.jsonl`, each judged by hand in its sentence. **49 of 50 correct (0.98).**
  - Mistake: #37, "Ceftazidime+avibactam 62.5 mg/kg/dose q8h IV (50 mg/kg/dose **ceftazidime** + 12.5 mg/kg/dose avibactam)" links the dose of the component to the single drug J01DD02.
  - Questionable but counted correct: #21 "Klebsiella spp." links to *K. pneumoniae* (the T03 genus simplification). Counting it wrong gives 48/50 (0.96).
  - The sample is small: the 95% interval is wide (roughly 0.89 to 1.0). It is mostly drugs, pathogens and mechanisms with exact matches, so it says little about the 72 fuzzy links.
- **Real top 20 unlinked surfaces:** enterobacterales 334, carbapenemase 272, carbapenemases 212, azithromycin 114, enterobacteriaceae 96, Streptococcus pneumoniae 89, β-lactamase 88, Streptococcus pyogenes 79, sulbactam 75, Clostridioides difficile 73, β-lactamases 65, beta-lactamases 59, piperacillin 59, Neisseria gonorrhoeae 58, cefalexin 58, Haemophilus influenzae 52, tazobactam 49, cefoperazone 48, clarithromycin 44, IMP 40. Full list in `data/processed/unlinked.csv`.
- **Suggested synonym additions for T03 (not edited):**
  - `cefalexin` is a spelling of cephalexin and `benzylpenicillin` (40) is penicillin G; both are out-of-scope drugs, but they could be added as variants of a penicillin or cephalosporin family if class-level questions should catch them.
  - `piperacillin` and `tazobactam` are almost all PDF table artefacts: the combination is split across table columns ("piperacillin thrice tazobactam daily", "Piperacillin-" / "Imipenem"). A synonym cannot fix these; they are a T06 extraction issue.
  - `sulbactam` alone is mostly `cefoperazone-sulbactam` (not in scope) and "Ampicillin –sulbactam" with a space before the dash, which is not matched. Adding `ampicillin –sulbactam` as a variant of J01CR01 would fix the second; I did not change the linker for it.
  - Out of scope by design: azithromycin, clarithromycin, rifampicin, cefoperazone, and the species *S. pneumoniae*, *S. pyogenes*, *C. difficile*, *N. gonorrhoeae*, *H. influenzae*. `Enterobacterales`, `carbapenemase(s)`, `β-lactamase(s)`, `IMP` stay unmapped (REVIEW_NOTES §2.5).
- **Test result:** `.venv/Scripts/python -m pytest tests`: 458 passed, 1 failed. The failure is `tests/test_build_core.py::test_glass_map_targets_exist_in_scope`, a T05 file, not mine. `tests/test_link.py`: 45 passed. An earlier run in the same session showed 19 failures that did not repeat (other sessions were writing files at the time).

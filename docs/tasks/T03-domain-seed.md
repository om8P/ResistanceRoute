# T03: Domain seed data: scope, synonyms, resistance facts

- **Model:** Opus 5.5
- **Wave:** 1
- **Depends on:** T00 (done)
- **Read first:** [ORCHESTRATION.md](../ORCHESTRATION.md), [CONTRACTS.md](../CONTRACTS.md) sections 2–4, [ARCHITECTURE.md](../ARCHITECTURE.md) sections 2 and 5, [DECISIONS.md](../DECISIONS.md) D1, D4, D6, D7

## Goal

Write the hand-curated seed data that defines what is in scope and encodes the core resistance facts. Every multi-hop answer the system gives depends on these files being correct, which is why this task uses the strongest model and marks anything uncertain for expert review.

## Files you own

- `schema/scope.yaml`
- `schema/synonyms.csv`
- `schema/class_overrides.csv`
- `data/curated/pathogen_mechanism.csv`
- `data/curated/mechanism_class.csv`
- `data/curated/mechanism_inactivates_drug.csv`
- `data/curated/intrinsic_resistance.csv`
- `data/curated/REVIEW_NOTES.md`
- `tests/test_seed_data.py`

The exact columns and ID formats are in CONTRACTS.md sections 2 and 4.

## Work

1. **`schema/scope.yaml`**
   - The five pathogens: *Klebsiella pneumoniae*, *Escherichia coli*, *Acinetobacter baumannii*, *Pseudomonas aeruginosa*, *Staphylococcus aureus*.
   - About 10–12 resistance mechanisms that matter clinically for them. Include at least KPC, NDM, OXA-48-like, VIM, CTX-M-type ESBL, plasmid AmpC, OXA-23-like for *Acinetobacter*, and mecA/PBP2a for *S. aureus*.
   - About 50 antibiotics in about 15 classes: the drugs that guidelines actually recommend or restrict for these pathogens, including the newer β-lactam/β-lactamase-inhibitor combinations, cefiderocol, colistin, tigecycline, fosfomycin, and the anti-MRSA agents.
   - Each drug has its ATC code as ID, its class and its AWaRe group.

2. **`schema/class_overrides.csv`**
   - Drugs whose class for resistance reasoning differs from their ATC or AWaRe class. The main case is β-lactam/β-lactamase-inhibitor combinations, which need their own classes so that a class-level resistance edge does not wrongly exclude them. Give the reason for each row.

3. **`schema/synonyms.csv`**
   - For every drug: the generic name, common abbreviations (for example the three-letter codes used on susceptibility reports), spelling variants, and well-known brand names.
   - For every pathogen: full name, abbreviated form, and resistance-phenotype acronyms that imply it (for example MRSA maps to *S. aureus*; CRKP maps to *K. pneumoniae*). Note in `REVIEW_NOTES.md` which acronyms also imply a mechanism or a resistance class, because the query parser will need that.
   - For every mechanism and drug class: the names and abbreviations used in guidelines.

4. **`data/curated/` resistance facts**
   - `pathogen_mechanism.csv`: which mechanisms occur in which pathogen.
   - `mechanism_class.csv`: which drug classes each mechanism confers resistance to.
   - `mechanism_inactivates_drug.csv`: drug-level exceptions, where a mechanism defeats a specific drug whose class is otherwise active. Example: NDM and ceftazidime-avibactam.
   - `intrinsic_resistance.csv`: classes each pathogen resists intrinsically.
   - Every row has a `source` and a `needs_review` flag.

5. **Check the worked example by hand.** With your data, the reasoning "carbapenem-resistant *K. pneumoniae* → mechanism → excluded classes and drugs → what remains" must give different remaining drugs for KPC, NDM and OXA-48-like. Write the expected remaining drugs for each in `REVIEW_NOTES.md`. The orchestrator will use this as the acceptance test for the graph.

6. **`data/curated/REVIEW_NOTES.md`**
   - The modelling choices you made and why.
   - Every row marked `needs_review`, grouped so a pharmacology or microbiology reviewer can go through them quickly.
   - Known simplifications, for example reasoning about one mechanism at a time.

## Rules specific to this task

- **Sources.** Use CARD, the WHO AWaRe book, EUCAST expected resistant phenotypes, IDSA guidance on resistant Gram-negative infections, and ICMR guidelines. Cite only what you are confident exists. When you cannot name a source for a row, write `unverified` and set `needs_review` to `true`.
- **Verify where you can.** Use web search to confirm ATC codes, ARO accessions and AWaRe groups. If `data/raw/aware/` or `data/raw/card/` already contain files (another task is downloading them in parallel), read them and prefer them over memory.
- **IDs you could not confirm** get `id_verified: false` in `scope.yaml`. A later task reconciles them against the downloaded files.
- This is reference content for an educational tool. Do not include doses or patient-specific advice.

## Tests

`tests/test_seed_data.py` checks consistency: files parse, IDs match the contract formats, every ID used in a CSV exists in `scope.yaml`, no duplicate rows, every drug has a class, every synonym points to an entity in scope, and no synonym maps to two different entities of the same type.

## Done when

- All files exist and `.venv/Scripts/python -m pytest tests` passes.
- The worked example in step 5 gives three different answers, written in `REVIEW_NOTES.md`.
- The handoff `docs/handoffs/T03-domain-seed.md` gives counts per file, the number of rows needing review, and the IDs that are still unverified.

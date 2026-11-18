# AMR-Navigator: Decisions

This file records the design decisions for AMR-Navigator, why each was made and what was rejected. The resulting design is in [ARCHITECTURE.md](ARCHITECTURE.md) and the build order is in [PLAN.md](PLAN.md).

Status values: **Accepted** (build to this), **Open** (needs an answer; the stated default applies until then).

## Summary

| ID | Decision | Status |
|---|---|---|
| D1 | Limit scope to five priority pathogens | Accepted |
| D2 | Labelled property graph in Neo4j | Accepted |
| D3 | Curated core, extracted periphery | Accepted |
| D4 | Model resistance mechanisms explicitly | Accepted |
| D5 | Make each recommendation a node | Accepted |
| D6 | Curated drug classes; ATC code is an ID only | Accepted |
| D7 | One canonical ID per entity, one linker for build and query | Accepted |
| D8 | Dictionary-based entity matching | Accepted |
| D9 | Curated recommendations as gold; schema-guided extraction compared against them | Accepted |
| D10 | Provenance on every relationship | Accepted |
| D11 | BM25 and FAISS passage index beside the graph | Accepted |
| D12 | Section-aware chunking | Accepted |
| D13 | Intent templates for Cypher, not free text-to-Cypher | Accepted |
| D14 | Reciprocal rank fusion over three passage lists | Accepted |
| D15 | Template-built answers | Accepted |
| D16 | Evaluate five retrieval modes on 40 questions | Accepted |
| D17 | Streamlit interface | Accepted |
| D18 | Educational use only, with a visible disclaimer | Accepted |
| D19 | Raw data is downloaded by script, not committed | Accepted |
| D20 | Build with an orchestrator and worker sessions in waves | Accepted |
| D21 | Choose the model by the kind of task | Accepted |
| D22 | Neo4j 5 Community in Docker | Accepted |
| D23 | Project virtual environment built on system packages | Accepted |
| D24 | Prefixed canonical IDs | Accepted |
| D25 | Seed resistance facts are hand-curated and flagged for review | Accepted |
| D26 | Surveillance statistics can be about a drug or a drug class | Accepted |
| D27 | One edge per fact; extra evidence goes through passages | Accepted |
| D28 | AWaRe 2025 is the source of AWaRe groups | Accepted |
| D29 | Fine-grained reasoning classes grouped into families | Accepted |
| D30 | GLASS genus-level Acinetobacter linked to A. baumannii with a note | Accepted |
| D31 | ICMR sources are the 2019 guidelines and the 2022 carbapenem-resistance guidance | Accepted |
| D32 | Recommendations become graph nodes in the core build | Accepted |
| D33 | Regimen type and co-producing mechanisms on recommendations | Accepted |
| D34 | Mechanism-specific recommendations outrank drug-level exclusions | Accepted |
| D35 | MRSA surveillance uses the GLASS methicillin row | Accepted |
| D36 | Curated evidence tags are kept on edges | Accepted |
| D37 | Lower-case acronyms in questions | Accepted |
| D38 | Effort per worker, adjustable mid-session, capped at high | Accepted |
| D39 | Answers separate guideline-recommended drugs from drugs merely not excluded | Accepted |
| D40 | Caveats, base drugs and susceptible-only flags live in the curated data | Accepted |
| D41 | T10's reasoning refinements | Accepted |
| D42 | The extraction score is reported as measured | Accepted |
| D43 | Q38 and Q33 gold answers stay as written | Accepted |
| D44 | Scoring rules for the evaluation runner | Accepted |
| Q1, Q4, Q5 | Open questions | Open |

## Scope and data

### D1. Limit scope to five priority pathogens
- **Decision:** Cover *K. pneumoniae*, *E. coli*, *A. baumannii*, *P. aeruginosa* and *S. aureus*, with about 10 mechanisms and about 50 drugs.
- **Why:** These are on the WHO bacterial priority pathogens list and have the richest guideline text. A small graph can be checked by hand, which a mini-project needs.
- **Rejected:** All pathogens in the AWaRe book. Too much curation for the time available.
- **Consequence:** Questions about other organisms return "out of scope".

### D3. Curated core, extracted periphery
- **Decision:** Mechanism, gene, drug and class edges come from structured sources (CARD, AWaRe, ATC). Text extraction adds only recommendations, mentions and supporting passages.
- **Why:** Errors in the core edges would make every multi-hop answer wrong. Structured sources are already reviewed by experts.
- **Rejected:** Building the whole graph by LLM extraction from PDFs. Lower precision, and hard to defend in a viva.
- **Consequence:** Extraction quality affects coverage of recommendations, not the correctness of resistance reasoning.

### D19. Raw data is downloaded by script, not committed
- **Decision:** `data/raw/` is not committed. A script and a `SOURCES.md` list record where each file comes from, its version and its licence. PubMed abstracts are stored as PMIDs and fetched on demand.
- **Why:** WHO documents are under a non-commercial Creative Commons licence, CARD is free for academic use only, and abstracts are copyrighted by publishers.
- **Consequence:** A fresh setup needs one download step before the pipeline runs.

## Graph model

### D2. Labelled property graph in Neo4j
- **Decision:** Use Neo4j 5 with Cypher.
- **Why:** Recommendations and provenance need properties on nodes and edges, which the property graph model gives directly. Cypher path queries express the multi-hop reasoning clearly. The course uses Neo4j.
- **Rejected:** An RDF triple store with SPARQL. Properties on edges need reification, and the tooling is heavier for a small project.
- **Consequence:** RDF/OWL is not the primary model. A Turtle export of the schema is a stretch goal to show the mapping.

### D4. Model resistance mechanisms explicitly
- **Decision:** Resistance always goes `Pathogen → Mechanism → DrugClass`. There is no direct pathogen-to-class resistance edge for acquired resistance.
- **Why:** The alternatives for carbapenem-resistant *Klebsiella* depend on the mechanism. Ceftazidime-avibactam works against KPC producers and fails against NDM producers. A direct edge cannot express this.
- **Rejected:** `(Pathogen)-[:RESISTANT_TO]->(DrugClass)` as in the original problem statement. It returns the same alternatives for every mechanism.
- **Consequence:** Answers are grouped by mechanism. This is the project's main argument for a graph over text-only retrieval.

### D5. Make each recommendation a node
- **Decision:** `Recommendation` is a node linked to pathogen, drug, guideline and, where stated, mechanism.
- **Why:** A recommendation depends on infection site, line of therapy and patient group. Two guidelines can also disagree, and each needs its own record.
- **Rejected:** `(Drug)-[:RECOMMENDED_IN]->(Guideline)`. It loses the context and cannot represent disagreement.
- **Consequence:** Queries are one hop longer. Conflicting guidelines appear side by side with their sources.

### D6. Curated drug classes; ATC code is an ID only
- **Decision:** Drug classes come from the AWaRe class column plus a small override file. β-lactam/β-lactamase-inhibitor combinations get their own classes. The ATC code is used only as the drug's identifier.
- **Why:** ATC files ceftazidime-avibactam under third-generation cephalosporins. With that grouping, a class-level resistance edge would wrongly exclude it.
- **Rejected:** Using the ATC hierarchy as the class hierarchy.
- **Consequence:** `schema/class_overrides.csv` must be maintained by hand, about 10 rows.

### D10. Provenance on every relationship
- **Decision:** Every relationship stores `source_id`, `method` (`curated`, `rule` or `llm`), `confidence` and, where available, `evidence_passage_id`.
- **Why:** Explanations must show where each step of a path came from. It also lets queries filter out low-confidence extracted edges.
- **Consequence:** The loader rejects any edge without a source.

## Entities and extraction

### D7. One canonical ID per entity, one linker for build and query
- **Decision:** Drugs use ATC codes, pathogens use NCBI taxonomy IDs, genes and mechanisms use CARD ARO accessions. The same linker module resolves names during graph construction and during question parsing.
- **Why:** Stable public IDs prevent duplicate nodes. A shared linker means a synonym added once works in both places.
- **Consequence:** A drug with no ATC code needs a locally assigned ID, recorded in the synonym dictionary.

### D8. Dictionary-based entity matching
- **Decision:** Find mentions with a spaCy `PhraseMatcher` built from the synonym dictionary, then resolve them with exact, normalised and fuzzy (`rapidfuzz`) matching.
- **Why:** The entity set is closed and known in advance, so a dictionary gives high precision. It installs cleanly on Windows.
- **Rejected:** scispaCy NER models as the main recogniser. They do not label pathogens or mechanisms as separate types, and installation on Windows is unreliable.
- **Consequence:** Entities missing from the dictionary are not found. The `unlinked.csv` review file is used to extend the dictionary.

### D9. Curated recommendations as gold; schema-guided extraction compared against them
- **Decision:** Curate 40–80 recommendations by hand into `recommendations_curated.csv`. Separately, extract recommendations from the same text into a Pydantic model using rule patterns and, if an LLM is available, structured-output extraction. Report extraction precision, recall and F1 against the curated set.
- **Why:** The curated file guarantees the graph has correct recommendations whatever happens with extraction. It also serves as the gold standard, so the extraction experiment costs no extra labelling. Schema-guided extraction with Pydantic is a syllabus topic.
- **Rejected:** Relying on extraction alone. A weak extractor would leave the demo with wrong or missing recommendations.
- **Consequence:** Curation must be done early. Rule-based extraction is the default; LLM extraction is a stretch goal (see Q2).

## Retrieval

### D11. BM25 and FAISS passage index beside the graph
- **Decision:** Keep passages as `Passage` nodes in Neo4j for linking, and index their text in Python with `rank_bm25` and a FAISS HNSW index over `sentence-transformers` embeddings.
- **Why:** Separate indexes make the BM25 and dense baselines independent of the graph, so the comparison is fair. HNSW demonstrates the ANN indexing covered in the syllabus.
- **Rejected:** Neo4j's built-in full-text and vector indexes. Simpler to run, but the baselines would no longer be separable from the graph system.
- **Consequence:** Two stores must be rebuilt together. Passage IDs are the join key.

### D12. Section-aware chunking
- **Decision:** Split guideline text by section heading first, then into passages of 150–250 words with a short overlap. Convert each table row into one sentence. Each abstract is one passage.
- **Why:** Guideline recommendations are organised by infection and section. Fixed-length chunks would split a recommendation from its condition.
- **Rejected:** Fixed-length chunking.

### D13. Intent templates for Cypher, not free text-to-Cypher
- **Decision:** Classify each question into one of six intents and fill a hand-written Cypher template.
- **Why:** Templates are deterministic, safe and testable. Every answer can be reproduced during evaluation.
- **Rejected:** LLM-generated Cypher as the main path. It can produce invalid or subtly wrong queries, which is unacceptable for medical content.
- **Consequence:** Questions outside the six intents fall back to text retrieval only. An LLM fallback is a stretch goal.

### D14. Reciprocal rank fusion over three passage lists
- **Decision:** Merge BM25 results, dense results and graph-linked passages with reciprocal rank fusion (k = 60).
- **Why:** RRF needs no score normalisation and no training data, and works well with few queries.
- **Rejected:** Weighted score combination. It needs tuning on data the project does not have.

### D15. Template-built answers
- **Decision:** Build the answer text from the query result and path with fixed templates. An LLM may rephrase it only as an optional extra, restricted to the retrieved facts.
- **Why:** Free generation can introduce drug claims that are not in the graph.
- **Consequence:** Answers read plainly. Generation metrics such as RAGAS apply only if the optional LLM step is added.

## Evaluation, interface and safety

### D16. Evaluate five retrieval modes on 40 questions
- **Decision:** Write 40 questions (20 single-hop, 20 multi-hop) with gold answers and relevant passages. Compare BM25, dense, BM25 + dense, graph only and graph + text hybrid. Report Recall@k, MRR, nDCG@k and answer-set F1, with multi-hop questions reported separately.
- **Why:** The project claims that a graph finds alternative paths that text retrieval misses. This comparison tests that claim directly.
- **Consequence:** Gold answers must be written from the guidelines before the retrieval code is finished, so the questions are not fitted to the system.

### D17. Streamlit interface
- **Decision:** A single-page Streamlit app with a `pyvis` path view.
- **Why:** Quick to build in Python and enough for a demo.
- **Rejected:** A separate web frontend. No benefit for a mini-project.

### D18. Educational use only, with a visible disclaimer
- **Decision:** The app shows a permanent "not medical advice" banner. It gives no doses and no patient-specific advice, and every answer shows the guideline name and year.
- **Why:** Antibiotic choice depends on susceptibility results and local resistance patterns that the system does not have.

## Orchestration and environment

These were decided by the orchestrator session on 2026-11-17, when implementation started.

### D20. Build with an orchestrator and worker sessions in waves
- **Decision:** One orchestrator session makes decisions and reviews work. Worker sessions each do one task. Tasks with no dependencies on each other run in parallel as a wave. Sessions share context only through Markdown files: contracts, task briefs and handoffs. Each task owns a fixed list of files.
- **Why:** Sessions have no shared memory, and several write to the same folder at once. Written contracts and exclusive file ownership prevent incompatible code and overwritten work.
- **Consequence:** A wave starts only after the orchestrator has reviewed the handoffs it depends on. Details are in [ORCHESTRATION.md](ORCHESTRATION.md).

### D21. Choose the model by the kind of task
- **Decision:** Opus 5.5 for clinical-domain content and query logic, Sonnet 5.5 for general implementation, Haiku 5.5 for small tasks with a complete specification.
- **Why:** Errors in resistance facts or in the reasoning queries make answers wrong, so they get the strongest model. Routine code does not need it.

### D22. Neo4j 5 Community in Docker
- **Decision:** Run Neo4j from `docker-compose.yml`. This replaces the earlier default of Neo4j Desktop (question Q3).
- **Why:** Docker is installed on the development machine and Neo4j is not. A compose file gives the same database to anyone who clones the project.
- **Rejected:** AuraDB Free, which needs an internet connection during the demo.
- **Consequence:** Docker Desktop must be running. Database tests skip themselves when it is not.

### D23. Project virtual environment built on system packages
- **Decision:** `.venv` is created with `--system-site-packages`.
- **Why:** `torch` and `sentence-transformers` are already installed system-wide and are several gigabytes. Only the missing packages are added.

### D24. Prefixed canonical IDs
- **Decision:** Refines D7. Pathogen IDs are `NCBITaxon:<taxid>`, mechanism and gene IDs are `ARO:<accession>`, and entities without a public ID use `LOCAL:<kind>:<slug>`. Drug IDs stay as plain ATC codes.
- **Why:** A prefix shows which vocabulary an ID comes from and prevents a taxonomy number from colliding with another numeric ID.
- **Consequence:** The formats are fixed in [CONTRACTS.md](CONTRACTS.md) and enforced by the data models.

### D25. Seed resistance facts are hand-curated and flagged for review
- **Decision:** The in-scope lists and the pathogen–mechanism, mechanism–class, drug-level exception and intrinsic resistance tables are written by hand into `schema/` and `data/curated/`, each row with a source and a `needs_review` flag. CARD data is used to check and extend them, not to generate them.
- **Why:** CARD links genes to drug classes at a level that is too broad for this reasoning; for example it cannot say that a carbapenemase spares a specific inhibitor combination. About a hundred curated rows are small enough to review.
- **Consequence:** A domain expert should review the flagged rows before the results are presented as correct.

### D26. Surveillance statistics can be about a drug or a drug class
- **Decision:** Add `(SurveillanceStat)-[:ABOUT_CLASS]->(DrugClass)` beside `ABOUT_DRUG`.
- **Why:** GLASS reports resistance for antibiotic classes (for example carbapenems) as well as single drugs, and the contract already allowed class-level statistic IDs.
- **Rejected:** Restricting statistics to single drugs, which would discard most of the GLASS data the surveillance questions need.

### D27. One edge per fact; extra evidence goes through passages
- **Decision:** There is one relationship per `(start, type, end)`. When several sources support it, the loader keeps the strongest provenance (`curated`, then `rule`, then `llm`) and links the other supporting text as `Passage` nodes.
- **Why:** `MERGE` on the pair can hold only one set of provenance properties, and duplicate relationships would double-count paths in queries.

### D28. AWaRe 2025 is the source of AWaRe groups
- **Decision:** Drug `aware_group` comes from the 2025 AWaRe workbook (`source_id` `who-aware-2025`). The 2023 workbook is kept only as a cross-check. Drug classes come from `scope.yaml`, never from the AWaRe class column.
- **Why:** 2025 is the current edition, and AWaRe files ceftazidime-avibactam under third-generation cephalosporins, which would break the reasoning (see D6).

### D29. Fine-grained reasoning classes grouped into families
- **Decision:** Keep T03's 32 reasoning classes, and give each `DrugClass` a `family` property (for example `carbapenem` covers both carbapenem classes, `cephalosporin` covers all cephalosporin generations). Family names are linkable through `ClassFamily` synonyms, and class-level questions expand to every class in the family.
- **Why:** The splits are needed for correct resistance reasoning (for example ertapenem behaves differently from meropenem against *P. aeruginosa*), but users ask about "carbapenems", not about group 1 and group 2.
- **Rejected:** A `SUBCLASS_OF` relationship. A property is enough for one level of grouping and needs no new relationship type.

### D30. GLASS genus-level Acinetobacter linked to A. baumannii with a note
- **Decision:** GLASS rows for "Acinetobacter spp." link to `NCBITaxon:470` and the edge records `reported_taxon`. Answers that use them must say the data is genus-level.
- **Why:** *A. baumannii* is the clinically dominant species and adding a genus node would complicate every query for little gain.
- **Consequence:** *P. aeruginosa* has no surveillance data, because GLASS does not report it.

### D31. ICMR sources are the 2019 guidelines and the 2022 carbapenem-resistance guidance
- **Decision:** Use the ICMR 2019 treatment guidelines PDF and the ICMR 2022 guidance on carbapenem-resistant Gram-negative infections. Do not scrape the 2022 web edition.
- **Why:** The 2022 treatment guidelines exist only as a web app. The 2022 carbapenem-resistance guidance has a per-mechanism table, which is exactly what the reasoning needs.

## Wave 2 review decisions (2026-11-18)

### D32. Recommendations become graph nodes in the core build
- **Decision:** `pipeline/build_core.py` turns `data/curated/recommendations_curated.csv` into `Recommendation` nodes with `FOR_PATHOGEN`, `FOR_MECHANISM`, `RECOMMENDS` and `FROM` edges, and links `SUPPORTS` edges from the passages of the same document whose page range covers the row's `source_page`.
- **Why:** No task had been given this step, and the reasoning queries (T10) need recommendations in the graph.

### D33. Regimen type and co-producing mechanisms on recommendations
- **Decision:** `recommendations_curated.csv` gets a `regimen_type` column (`single`, `combination`, `any-of`), stored on the `Recommendation` node. `mechanism_id` may hold several `|`-separated IDs for co-producers (for example NDM + OXA-48), giving one `FOR_MECHANISM` edge each.
- **Why:** `drug_ids` mixed combination partners and lists of alternatives, which need opposite logic: a combination is one unit, while alternatives are judged one by one.

### D34. Mechanism-specific recommendations outrank drug-level exclusions
- **Decision:** For a mechanism `m`, a recommendation linked to `m` by `FOR_MECHANISM` is always returned, even when one of its drugs is excluded for `m`. The answer then shows the caveat (for example "carbapenem only in combination when the MIC is low", or "aztreonam is active only because avibactam protects it"). Recommendations not tied to a mechanism are filtered by the exclusion rule: an `any-of` row is judged drug by drug, and a `combination` or `single` row is dropped if any of its drugs is excluded.
- **Why:** T08 found 11 rows where a guideline deliberately recommends a regimen built around a drug the mechanism defeats on its own (ceftazidime-avibactam plus aztreonam for NDM; carbapenem partners in combination therapy). The guideline's specific advice is better evidence than the general rule, and hiding it would make answers wrong.
- **Rejected:** Changing T03's resistance facts to remove the conflicts, which would make the single-drug reasoning wrong.

### D35. MRSA surveillance uses the GLASS methicillin row
- **Decision:** GLASS `Methicillin` maps to the class `antistaphylococcal-penicillin` and stands for MRSA. GLASS `Oxacillin` is left unmapped: oxacillin is not in scope, and the methicillin row already covers MRSA.
- **Why:** The methicillin row is the one GLASS uses for its MRSA indicator, which also underlies SDG indicator 3.d.2.

### D36. Curated evidence tags are kept on edges
- **Decision:** Edges built from the curated files carry the row's `source` column as `evidence_sources` (a `|`-separated list).
- **Why:** Explanations should show which references support each step, not only free-text notes.

### D37. Lower-case acronyms in questions
- **Decision:** The linker stays case-sensitive for abbreviations in documents. The query parser (T12) additionally tries an upper-cased lookup for question tokens of 3 or more letters that match no other entity, so `mrsa` and `cza` resolve in questions.
- **Why:** Users type in lower case; guideline text does not, and case-sensitivity there avoids false links.

### D38. Effort per worker, adjustable mid-session, capped at high
- **Decision:** Each worker session gets a reasoning effort of `low`, `medium` or `high` chosen for its task (levels and criteria in [ORCHESTRATION.md](ORCHESTRATION.md)), never `xhigh` or `max`. The orchestrator changes a running worker's effort when the work in front of it gets harder or simpler.
- **Why:** Requested by the user. Matching effort to the task spends the shared usage limit where errors are costly (clinical content, reasoning queries) and saves it on mechanical work.

## Wave 3 review decisions (2026-11-18)

### D39. Answers separate guideline-recommended drugs from drugs merely not excluded
- **Decision:** An `alternatives` answer leads with drugs that have at least one supporting recommendation (`Answer.recommendation_ids` not empty), grouped by mechanism and ordered by line of therapy. Drugs that the resistance data does not exclude but no guideline recommends are shown afterwards, as a separate, clearly labelled list.
- **Why:** The first end-to-end run returned up to 29 drugs per mechanism, including nitrofurantoin, because every non-excluded drug counted as an answer. The question asks which guideline-listed alternatives remain; "not excluded" is weaker evidence and must not look the same.
- **Consequence:** T17 scores `drug_set` answers against the guideline-recommended list unless a question's gold answer comes from the curated resistance facts.

### D40. Caveats, base drugs and susceptible-only flags live in the curated data
- **Decision:** `recommendations_curated.csv` gets three columns: `caveat` (the D34 text, or empty), `base_drug_ids` (for regimens of one base drug plus partners, or empty) and `susceptible_only` (`true` when the recommendation is for susceptible organisms only). Graph search reads them instead of parsing `RECOMMENDATION_NOTES.md`.
- **Why:** T10 had to parse a Markdown table and depend on the order of a CSV cell. Data that the reasoning depends on belongs in a validated data file.

### D41. T10's reasoning refinements
- **Decision:** Accept the rules T10 introduced: base-plus-partner regimens are judged on the base drug and at least one active partner; when the question reports resistance to a class, that class is excluded even if no mechanism in the graph confers it; co-production caveats are generated from the data. Recommendations with `susceptible_only` are dropped from answers about resistant organisms.
- **Why:** Each removes a misleading answer that T10 found in testing.

### D42. The extraction score is reported as measured
- **Decision:** The rule-based extraction experiment (T13) is reported with strict F1 as the headline (0.13 overall, 0.37 on ICMR 2022, 0.00 on the ICMR 2019 development set) and lenient F1 beside it. ICMR 2019 tables are not re-extracted.
- **Why:** The low score is a real finding: guideline recommendations are too table-bound and context-dependent for simple rules, which supports curating the core recommendations by hand (D9). Re-extracting tables would cost a wave for an experiment that is not on the critical path.

### Other rulings
- Abstract passages have `page` and `printed_page` set to null. Passage text is indexed with its 30-word overlap.
- MRSA rows use mecA and ESBL rows use CTX-M as `mechanism_id` (T08), following `schema/phenotypes.csv`.
- Cefoperazone-sulbactam and standalone sulbactam stay out of scope for now; they are listed as future additions.
- `eval/questions.json` may cite several sources per answer (`gold_source` is a list), including the form `who-aware-2025 sheet '<sheet>' row <n>`.

## Wave 4 review decisions (2026-11-18)

### D43. Q38 and Q33 gold answers stay as written
- **Decision:** Q38 keeps MCR as its only gold mechanism, and Q33 keeps ampicillin-sulbactam as its only gold drug. T15's findings are recorded as known limits in the report.
- **Why:** For Q38, chromosomal *mgrB* and *pmrAB* changes are the more common cause in *K. pneumoniae*, but they are not mechanisms in the graph or the synonym dictionary, so no retrieval mode can return them as an answer and none is penalised unfairly. For Q33, cefoperazone-sulbactam and standalone sulbactam are out of scope (wave 3 "Other rulings").
- **Consequence:** The report's limitations section names *mgrB* as a missing mechanism, and adding it is listed as future work.

### D44. Scoring rules for the evaluation runner
- **Decision:** T17 scores passages against `eval/qrels.json` with graded nDCG@k (grades 2 and 1). Recall@k and MRR count grade ≥ 1 as relevant (the headline), and are also reported at grade = 2. The seven answerable questions with no grade-2 passage are left out of the grade-2 figures, and the report says so. Answer lists are de-duplicated by `id` before scoring, and `drug_set` answers are scored against `answers` (guideline-recommended), not `other_active` (D39). The dense model is warmed with one call before anything is timed.
- **Why:** T15 found seven answerable questions with only grade-1 passages, so a grade-2-only threshold would give them nothing to find. T14 returns the same drug once per mechanism group.
- **Consequence:** The pool's single `manual` passage (Q23) stays in the qrels; it is a real relevant passage that no automatic method found.

### Q2 (resolved). LLM for extraction
- **Decision:** Rule-based extraction is the default path. LLM extraction with structured output remains a stretch goal and is not needed for any milestone.

## Open questions

| ID | Question | Default until answered |
|---|---|---|
| Q1 | What are the submission date and team size? | Six weeks of scope, built in waves by worker sessions |
| Q4 | Does the course define OS, ER, MH, EX and ED differently? | Ontology/schema, entity resolution, multi-hop, explainability, entity disambiguation |
| Q5 | Is a specific report format required? | Standard report: problem, design, implementation, evaluation, limitations |

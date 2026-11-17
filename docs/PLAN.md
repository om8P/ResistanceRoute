# AMR-Navigator: Project Plan

This is the build plan for AMR-Navigator. The design is in [ARCHITECTURE.md](ARCHITECTURE.md) and the reasons behind it are in [DECISIONS.md](DECISIONS.md).

## Goal

Build a knowledge graph of pathogens, resistance mechanisms, antibiotics and guideline recommendations, with a hybrid retrieval system that answers questions such as:

> "If carbapenem resistance is reported for *Klebsiella*, which guideline-listed alternatives remain?"

and shows the reasoning path and sources behind each answer.

**Success means:**

1. The graph answers the six question types in the architecture for the five pathogens in scope.
2. Every answer shows a reasoning path and at least one cited source.
3. The evaluation shows how graph-based retrieval compares with text-only retrieval on multi-hop questions.

## Assumptions

- Six weeks are available. If the deadline is closer, use the minimum scope below.
- Two or three people. Tasks are grouped into three tracks that can run in parallel.
- Laptops running Windows, Python 3.11 and Neo4j Desktop.

## Tracks

| Track | Covers |
|---|---|
| **A. Graph** | Schema, structured data loading, Cypher templates |
| **B. Text** | PDF ingestion, extraction, entity linking, passage index |
| **C. Evaluation and interface** | Question set, labelled data, metrics, Streamlit app, report |

## Phases

### Phase 1: Schema and data collection (week 1)

| Task | Track | Output |
|---|---|---|
| Set up the repository, folders and `requirements.txt` | A | Working environment |
| Download AWaRe list, CARD, ATC codes, GLASS data, guideline PDFs | A, B | `data/raw/`, `SOURCES.md` with versions and licences |
| Write constraints and the schema file | A | `schema/constraints.cypher` |
| Build the synonym dictionary for drugs, pathogens and mechanisms | B | `schema/synonyms.csv` |
| Write the drug class override table | A | `schema/class_overrides.csv` |
| Draft 40 evaluation questions, without answers yet | C | `eval/questions.json` (draft) |

**Done when:** constraints run on an empty Neo4j database, and the synonym dictionary covers all drugs and pathogens in scope.

### Phase 2: Core graph from structured sources (week 2)

| Task | Track | Output |
|---|---|---|
| Load drugs, classes and AWaRe groups | A | `Drug`, `DrugClass` nodes |
| Load pathogens, mechanisms and genes from CARD, filtered to scope | A | `Pathogen`, `Mechanism`, `Gene` nodes and edges |
| Add `INACTIVATES` and intrinsic resistance edges | A | Exception edges |
| Load GLASS statistics | A | `SurveillanceStat` nodes |
| Curate 40–80 recommendations from the guidelines by hand | B, C | `recommendations_curated.csv` |
| Write the validation step and load report | A | `pipeline/load.py`, `load_report.json` |

**Done when:** the `alternatives` query run by hand in Neo4j Browser returns different drugs for KPC and NDM in *K. pneumoniae*.

### Phase 3: Text pipeline (week 3)

| Task | Track | Output |
|---|---|---|
| Parse guideline PDFs and chunk by section | B | `passages.jsonl` |
| Fetch PubMed abstracts by search query | B | Abstract passages |
| Build the entity matcher and linker | B | `pipeline/link.py`, `mentions_linked.jsonl` |
| Extract recommendations into the Pydantic model | B | `recommendations_extracted.jsonl` |
| Load passages, `MENTIONS` and `SUPPORTS` edges | A | Passages joined to the graph |
| Label about 100 mentions for linker evaluation | C | `eval/linking_gold.csv` |

**Done when:** every passage is linked to at least the entities found by a manual spot check of 20 passages, and unlinked mentions are listed in `unlinked.csv`.

### Phase 4: Retrieval and reasoning (week 4)

| Task | Track | Output |
|---|---|---|
| Write the six Cypher templates and path output | A | `retrieval/graph_search.py` |
| Write the query parser and intent rules | B | `retrieval/parser.py` |
| Build BM25 and FAISS indexes | B | `retrieval/text_search.py` |
| Implement fusion and the answer builder | A, B | `retrieval/fusion.py`, `retrieval/answer.py` |
| Finish gold answers and relevant passages for the 40 questions | C | `eval/questions.json` (final) |

**Done when:** a command-line call returns an answer, a path and citations for one example of each intent.

### Phase 5: Interface and evaluation (week 5)

| Task | Track | Output |
|---|---|---|
| Build the Streamlit app with path view and disclaimer | C | `app/streamlit_app.py` |
| Write the evaluation runner for the five retrieval modes | C | `eval/run_eval.py` |
| Run retrieval, linking and extraction evaluations | C | `eval/results/` |
| Fix the errors the evaluation reveals | A, B | Updated dictionary and templates |

**Done when:** one command produces the full results table, and the app answers the demo questions end to end.

### Phase 6: Report and demo (week 6)

| Task | Track | Output |
|---|---|---|
| Write the report | All | `report/` |
| Prepare demo script with five questions | C | Demo notes |
| Record a backup demo video | C | Video file |
| Clean the repository and write the README | A | Runnable from a fresh clone |

**Done when:** a teammate can set up and run the project from the README alone.

## Milestones

| Milestone | End of | Check |
|---|---|---|
| M1. Schema fixed | Week 1 | Constraints load; dictionary complete |
| M2. Core graph queryable | Week 2 | KPC vs NDM query gives different answers |
| M3. Text linked to graph | Week 3 | Passages carry entity links |
| M4. End-to-end answer | Week 4 | Answer with path and citations from the command line |
| M5. Evaluated system | Week 5 | Results table and working app |
| M6. Submission | Week 6 | Report, demo, clean repository |

## Deliverables

- Source code for the pipeline, retrieval, app and evaluation.
- Neo4j database dump or a one-command rebuild.
- Evaluation question set with gold answers.
- Results table comparing the five retrieval modes.
- Report and demo.

## Minimum scope if time is short

Keep, in this order:

1. Core graph from structured sources (phase 2).
2. Curated recommendations.
3. The `alternatives` and `why_restricted` templates.
4. BM25 baseline and graph-only mode.
5. 20 evaluation questions.
6. A basic Streamlit page.

Drop first: PubMed abstracts, GLASS statistics, LLM extraction, the dense index, the remaining four intents.

## Stretch goals

- Schema-guided LLM extraction compared with rule-based extraction.
- LLM fallback for questions outside the six intents.
- Turtle/OWL export of the schema with an example SPARQL query.
- RAGAS or LLM-as-judge scoring of generated answers.
- Drug-resistant tuberculosis as a sixth pathogen.

## Risks

| Risk | Likelihood | Effect | Response |
|---|---|---|---|
| PDF tables extract badly | High | Missing recommendations | Curate recommendations by hand (already planned) |
| Mechanism-to-class edges from CARD are too broad or too fine | Medium | Wrong alternatives | Check the ten in-scope mechanisms by hand against a microbiology reference |
| Extraction precision is low | Medium | Noisy edges | Keep extracted edges marked by `method`; exclude them from reasoning by default |
| Evaluation questions are fitted to the system | Medium | Inflated results | Write gold answers from the guidelines before finishing retrieval code |
| The graph does not beat text retrieval | Low | Weaker claim | Report it as it is, split by single-hop and multi-hop, and analyse the failures |
| Neo4j or dependency problems on demo day | Low | Failed demo | Use Neo4j Desktop offline and keep a recorded backup demo |
| Clinical content is wrong | Medium | Loss of credibility | Ask a pharmacology or microbiology faculty member to review 10 answers |

## Report outline

1. Problem and motivation, including SDG 3.d, 3.8 and 3.3.
2. Related work: text-only RAG, GraphRAG, existing AMR databases.
3. Data sources and scope.
4. Schema and modelling rules.
5. Construction pipeline.
6. Retrieval and explanation.
7. Evaluation: setup, results, error analysis.
8. Limitations and the disclaimer.
9. Future work.

# Handoff: T15 Relevance judgements for the evaluation questions

- **Model:** Opus 5.5
- **Status:** complete
- **Date:** 2026-11-18

## What was built

All 40 questions now have relevance judgements in `eval/qrels.json`.

- **Pool.** `eval/build_pool.py` takes, for each question, the top 20 passages from `bm25`, `dense` and `bm25_dense`, the top 20 linked to the gold entities, and every passage on a cited guideline page. It also adds one passage found by a targeted search for Q23. It records which method found each passage. The script was already on disk from an earlier session that stopped without a handoff; I reviewed it against the brief, kept the pooling logic, and added the manual-addition hook and fuller statistics.
- **Judgements.** I graded every pooled passage (2,084 question–passage pairs) from its text on the 0–2 scale, independent of the method that found it.
- **Result.** `eval/qrels.json` has 345 relevant judgements: 113 grade 2 and 232 grade 1. `eval/QRELS_NOTES.md` gives the grading rules, method, per-question and per-method counts, the Q23 search, and the hard calls.

## Files created or changed

| Path | What it is |
|---|---|
| `eval/build_pool.py` | Finished: `manual` method and `MANUAL` (one Q23 passage); `stats()` now reports pairs pooled per method, relevant per method split by grade, relevant found by only one method, and judged passages missing from the pool |
| `eval/qrels.json` | `{question id: {passage id: grade}}`, grades 1 and 2 only; all 40 IDs present, decline questions `{}` |
| `eval/QRELS_NOTES.md` | Grading rules, pooling, judging method, results tables, Q23 finding, hard calls, limits |
| `tests/test_qrels.py` | 12 tests: every question ID present; shape; grades 1 or 2; decline questions empty; every answerable question has a relevant passage; every passage ID exists in `passages.jsonl` (skipped if not built); manual additions judged; pool helpers (`gold_pages`, `page_spans`, `passages_on_pages`, `stats`) on small in-memory data |

## How to run and check it

```bash
.venv/Scripts/python -m eval.build_pool --out <scratch>/pool.json --qrels eval/qrels.json
.venv/Scripts/python -m pytest tests/test_qrels.py
```

The first command rebuilds the pool in about 15 s and prints the statistics used in the notes. The pool is deterministic: rebuilt after judging, it matched the judged pool exactly.

## Test result

`.venv/Scripts/python -m pytest tests`: `725 passed, 2 warnings in 43.04s`. Neo4j container `amr-navigator-neo4j` was up. The warnings are the known `typer`/`click` deprecations. `tests/test_qrels.py`: 12 passed.

## What I found

### Totals

| | Count |
|---|---|
| Pairs pooled | 2,084, 33–67 per question; 1,883 for the 36 answerable questions, covering 598 distinct passages |
| Relevant | 345 (grade 2: 113, grade 1: 232) |
| Single-hop | 31 grade 2 + 59 grade 1 |
| Multi-hop | 82 grade 2 + 173 grade 1 |
| No relevant passage | Only the four decline questions (Q17, Q24, Q32, Q40), by rule |
| Answerable, but no grade-2 passage | Seven: Q04, Q11, Q20, Q28 (GLASS numbers are not in the corpus); Q35 (the "GLASS has no data" answer); Q09, Q19 (AWaRe group of ceftolozane-tazobactam and piperacillin-tazobactam is only in the AWaRe 2025 spreadsheet). nDCG for these is against grade-1 passages only. |

### Relevant found per method

A passage found by several methods counts for each.

| Method | Grade 2 + grade 1 | Relevant found only by this method |
|---|---|---|
| `bm25` | 62 + 102 | 15 |
| `dense` | 55 + 93 | 19 |
| `bm25_dense` | 64 + 120 | 7 |
| `entities` | 55 + 105 | 50 |
| `gold_page` | 51 + 50 | 42 |

- The three text modes together found 245 of the 345 relevant pairs; the other 100 came only from entity links, gold pages or the manual search.
- 42 relevant guideline passages were reached only through cited gold pages. Text retrieval at depth 20 misses part of the guideline evidence the gold answers rest on.

### Q23 (ceftaroline for MRSA)

- Only 4 of 1,428 passages mention ceftaroline, all PubMed abstracts; no guideline passage does.
- The one direct statement is in `pubmed-40887577:abstract:1`: MRSA prevalence 79.1%, "S. aureus remained susceptible to vancomycin, linezolid and ceftaroline". It was not in Q23's pool; I added it as `manual`, grade 2.
- The other three are pooled abstracts on ceftaroline combinations for MRSA bacteraemia, grade 1.

### Questions where the gold answer looks wrong or incomplete, given the passages

I am reporting these, not changing anything.

1. **Q38 (colistin resistance in *K. pneumoniae*).** The gold is MCR only.
   - Three pooled *K. pneumoniae* studies say the main mechanism is chromosomal *mgrB* disruption, and that *mcr* is rare: `pubmed-40879378` (*mgrB* in 53.7% of isolates, *mcr* in 1.5%), `pubmed-38381174` and `pubmed-36230959`.
   - T09 already flagged this, and chromosomal mutations are "correct extra content". But a system that answers only *mgrB* gets an answer-set F1 of 0.
   - I graded the *mgrB* passages 2.
2. **Q33 (mild CRAB UTI, single agent).** The gold is ampicillin-sulbactam only.
   - ICMR 2022 p17 says "the agent of choice is sulbactam". It is given as high-dose sulbactam on its own, as ampicillin-sulbactam (if susceptible), or as cefoperazone-sulbactam.
   - Cefoperazone-sulbactam may belong in the gold set, if it is in scope.
3. **Q23 (MRSA beta-lactam).** The gold rests on the curated seed. The corpus supports it with only one in-vitro surveillance sentence in an abstract about Gram-negative bacteria. The answer is not wrong, but it is weakly supported by the corpus.
4. **Q08 (CRAB options).** `pubmed-42661422`, an abstract of a clinical practice guideline, recommends cefiderocol for CRAB. The gold leaves cefiderocol out on purpose, following AWaRe's caution (T09's stricter choice). This is a disagreement between sources, not an error.
5. **Q12 (E. coli, 3rd-generation cephalosporins).** The gold includes KPC, NDM and VIM. The passages attribute E. coli 3GC resistance to ESBL, and in one abstract also to AmpC. The gold is broader than the corpus, but not wrong: carbapenemases also hydrolyse 3GCs.

## Deviations from the brief or contracts

- **Added a `manual` pooling method** for one passage (Q23). The brief asked for a specific search for Q23. The passage that search found was not in any automatic pool, and qrels are supposed to cover pooled passages only. `QRELS_NOTES.md` reports it as a separate method, so T17 can leave it out.
- **Judged partly from a compact view.** I did not read every pooled passage in full; the brief allows batch judging. Each passage was shown as its heading plus keyword-in-context snippets. Every candidate was then read in full, or graded from snippets that already contained the whole statement being judged. Off-topic passages were graded 0 from the compact view. `QRELS_NOTES.md` sections 3 and 7 describe this and its risk: grade-1 passages worded very differently from the question could have been missed.
- **The pool is not saved in the repository.** It is not among my files. It can be rebuilt with `python -m eval.build_pool --out ...`.

## Not done or not verified

- **No second judge.** There is no inter-annotator agreement figure.
- **Most of the 1,538 zero grades for answerable questions were given from the compact view, not a full read.**

## Requests to orchestrator

- **Decide whether to revisit the Q38 and Q33 gold answers** (see "What I found"). I did not edit `eval/questions.json`.
- **For T17:** score nDCG with the grades (2 and 1). For Recall@k and MRR, either count grade ≥ 1 as relevant or report both thresholds (≥ 1 and = 2). Seven answerable questions have no grade-2 passage, so a grade-2-only threshold leaves them with nothing to find.

# Handoff: T11 BM25 and dense passage indexes

- **Model:** Sonnet 5.5
- **Status:** complete
- **Date:** 2026-11-18

## What was built

`python -m retrieval.build_index` builds a BM25 index (`rank_bm25`) and a dense FAISS HNSW index (`all-MiniLM-L6-v2`, normalised vectors, inner product) over the 1,428 passages in 8.9 s. `retrieval/text_search.py` provides `search(query, mode, k, entity_ids)` with modes `bm25`, `dense` and `bm25_dense` (RRF, k = 60), and `passages_for_entities(entity_ids, k)`, as in CONTRACTS §7. Entity filtering reads `mentions_linked.jsonl` and `edges_SUPPORTS.csv`; Neo4j is not used. `PassageHit` is imported from `retrieval/types.py` (falls back to an identical local dataclass if that file is absent).

## Files created or changed

| Path | What it is |
|---|---|
| `retrieval/build_index.py` | `tokenize`, `build`, CLI |
| `retrieval/text_search.py` | `TextIndex`, `search`, `passages_for_entities`, `rrf`, CLI |
| `data/processed/index/` | `bm25.pkl`, `dense.faiss`, `embeddings.npy`, `passage_ids.json`, `meta.json` |
| `tests/test_text_search.py` | 36 tests |

## How to run and check it

```bash
.venv/Scripts/python -m retrieval.build_index
.venv/Scripts/python -m retrieval.text_search "why is colistin a reserve antibiotic" --mode bm25_dense -k 5 [--entity J01XB01]
.venv/Scripts/python -m pytest tests/test_text_search.py
```

## Test result

`.venv/Scripts/python -m pytest tests`: `502 passed, 2 warnings in 36.91s` (whole suite; warnings are `typer`/`click` deprecations). `tests/test_text_search.py`: 36 passed. Tests cover tokenisation, each mode, RRF values and tie-break, `bm25_dense` equal to RRF of the two lists, entity filtering (MENTIONS and SUPPORTS), `passages_for_entities` ordering, stable repeated results and stale-index detection. They build a small temporary index (real model, about 20 s); two more check the real index.

## What I found

**Index facts** (`data/processed/index/meta.json`)

| | |
|---|---|
| Passages | 1,428 (IDs checked against `passages.jsonl` at load time; a mismatch raises) |
| BM25 | `BM25Okapi`, k1 1.5, b 0.75 (library defaults); 260,359 tokens, vocabulary 14,104; `bm25.pkl` 2.26 MB; built in 0.26 s |
| Dense | `sentence-transformers/all-MiniLM-L6-v2`, **device cuda**, 384 dims, `IndexHNSWFlat` M = 32, efConstruction 200, efSearch 128, inner product on normalised vectors; `dense.faiss` 2.58 MB, `embeddings.npy` 2.19 MB; built in 8.6 s |
| Total build | 8.9 s (model already cached) |

**Behaviour the next tasks need**

- Tokeniser: lower case; `ceftazidime-avibactam` gives the whole token plus `ceftazidime` and `avibactam`; same for `/` and `+` (`tmp/smx`; `oxa-48-like` → `oxa-48-like`, `oxa`, `48`, `like`). 27 stop words (listed in meta). The query uses the same tokeniser.
- BM25 returns only passages with a positive score, so it can return fewer than k. Dense always returns k.
- Entity filter = passages linked to **any** given ID through `mentions_linked.jsonl` (`entity_id`) or `SUPPORTS` (`end_id`, so Recommendation IDs work). With a filter, BM25 and dense rank only the allowed passages; dense is then exact (dot products on the stored embeddings) instead of HNSW. Unknown IDs give an empty list.
- `bm25_dense`: each list is cut at depth max(100, k), fused with RRF k = 60, `score` is the fused score (max about 0.033), `rank` starts at 1. Ties keep first-seen order, so results are deterministic. `bm25` score is the BM25 score, `dense` score is cosine similarity.
- `passages_for_entities`: score = number of distinct given entities linked to the passage; ties by total mention count, then corpus order.
- The index holds the passage `text` as stored, including the 30-word overlap (my answer to T06 request 3: simplest, and consistent with what hits display). Neighbouring passages can therefore both match.
- MiniLM truncates input at 256 word-pieces, so the tail of a 250-word passage is not embedded. Dense matching is on the first part of long passages.
- Importing `retrieval.text_search` is cheap; the model, FAISS and BM25 load on first use (a few seconds). The CLI sets `errors="replace"` on stdout because passages contain characters like ≥ that the Windows cp1252 console cannot print.

**Sanity check** (five queries I wrote; `eval/questions.json` not used). Top 3 per mode:

1. *ceftazidime-avibactam aztreonam NDM*
   - bm25: `icmr-cr-gram-negative-2022:diagnosis:10` (E-test strip placement, aztreonam + CZA), `pubmed-36150216:abstract:1` (OXA-48-like and NDM treatment strategies), `icmr-cr-gram-negative-2022:diagnosis:8` (aztreonam with ceftazidime/avibactam for MBL infections)
   - dense: `…diagnosis:11` (susceptibility test of the triple combination), `…diagnosis:8`, `icmr-cr-gram-negative-2022:directed-enterobacterales:6` (CZA + aztreonam synergy test)
   - bm25_dense: `…diagnosis:10`, `…diagnosis:8`, `…directed-enterobacterales:6`
2. *MRSA osteomyelitis*
   - bm25: `who-aware-book-2022:osteomyelitis:12`, `…osteomyelitis:15`, `who-aware-book-2022:septic-arthritis:19`
   - dense: `pubmed-32933461:abstract:1` (osteomyelitis treatments review), `who-aware-book-2022:osteomyelitis:7`, `…osteomyelitis:8`
   - bm25_dense: `…osteomyelitis:15`, `icmr-treatment-guidelines-2019:bone-joint:1`, `…osteomyelitis:7`
3. *why is colistin a reserve antibiotic*
   - bm25: `who-aware-book-2022:reserve-overview:5`, `…reserve-overview:2`, `who-aware-book-2022:polymyxin-colistin:14`
   - dense: `pubmed-36754367:abstract:1` (colistin resistance mechanisms), `…reserve-overview:5`, `…polymyxin-colistin:2`
   - bm25_dense: `…reserve-overview:5`, `…polymyxin-colistin:12`, `pubmed-36754367:abstract:1`
4. *treatment of carbapenem-resistant Acinetobacter baumannii*
   - bm25: `pubmed-36345852` (cefiderocol for A. baumannii), `pubmed-35974429` (cefiderocol-resistant outbreak), `pubmed-41535153` (How to treat CRAB)
   - dense: `pubmed-27270503` (A. baumannii carbapenemases), `pubmed-41535153`, `pubmed-40833279` (OXA-23 inhibition)
   - bm25_dense: `pubmed-41535153`, `pubmed-35974429`, `pubmed-33009141` (identification and treatment of CR Gram-negatives)
5. *OXA-48 Klebsiella pneumoniae options*
   - bm25: `pubmed-36150216`, `pubmed-39521758` (carbapenemase-producing Kp, South Africa), `pubmed-39760498` (OXA-48-like Enterobacterales)
   - dense: `pubmed-36150216`, `pubmed-37945113` (Kp ST395 carbapenem/colistin), `pubmed-38518451` (heteroresistance)
   - bm25_dense: `pubmed-36150216`, `pubmed-39760498`, `pubmed-39521758`

Reading: BM25 handles exact drug and gene names well (queries 1 and 5), and still ranks the passages with the source typo "azteronam" first for query 1. Dense finds topical passages when the wording differs (queries 3 and 4) but drifts to general abstracts. Fusion keeps the passages both lists agree on at the top. These are my own judgements on five queries, not a measured result; for queries 2 and 4 I did not check that the top hits state a treatment.

## Deviations from the brief or contracts

- Extra files beside the two indexes: `embeddings.npy` (for exact filtered dense search) and `passage_ids.json` (staleness check).
- `PassageHit` has the CONTRACTS fields; nothing extra.

## Not done or not verified

- No retrieval quality measure; that is T15/T17.
- HNSW recall against exact search was not measured (the corpus is small; efSearch 128).
- Not checked on CPU: the build used CUDA. Search runs the query encoder on CUDA if available.
- Entity filter uses only `entity_id`; phenotype mentions' extra keys (`pathogen_ids`, `mechanism_ids`) are not expanded, so a passage mentioning "MRSA" matches the entity ID the linker assigned (the pathogen), not mecA.

## Requests to orchestrator

1. CONTRACTS §7: record that `bm25` may return fewer than k hits, and that the `passages_for_entities` score is the number of distinct matching entities.
2. Confirm `data/processed/index/` is covered by D19 (generated, not committed).
3. Rebuild the index (`python -m retrieval.build_index`) whenever `passages.jsonl` changes; loading checks this and raises.

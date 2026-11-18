# T11: BM25 and dense passage indexes

- **Model:** Sonnet 5.5, effort `medium`
- **Wave:** 3
- **Depends on:** T06, T07 (done); `retrieval/types.py` from T12 (being written in parallel)
- **Read first:** [ORCHESTRATION.md](../ORCHESTRATION.md), [CONTRACTS.md](../CONTRACTS.md) sections 6 and 7 ("Retrieval interfaces"), [ARCHITECTURE.md](../ARCHITECTURE.md) sections 5.3 and 6.3–6.4, [DECISIONS.md](../DECISIONS.md) D11, D14, and the handoffs for [T06](../handoffs/T06-pdf-chunking.md) and [T07](../handoffs/T07-entity-linker.md)

## Goal

Build the sparse and dense indexes over the 1,428 passages and the text-search functions the hybrid system and the baselines use.

## Files you own

- `retrieval/build_index.py`
- `retrieval/text_search.py`
- `data/processed/index/` (all files in it)
- `tests/test_text_search.py`

## Work

1. **BM25** with `rank_bm25` over `data/processed/passages.jsonl`. Tokenise in lower case, keep hyphenated and slashed drug names as single tokens as well as their parts, and remove a short English stop-word list. Store what is needed to rebuild quickly.
2. **Dense** embeddings with `sentence-transformers`, model `sentence-transformers/all-MiniLM-L6-v2` (from the official `sentence-transformers` organisation on Hugging Face; download it through the library on first use). Use the GPU if `torch.cuda.is_available()`. Index with FAISS HNSW (inner product on normalised vectors). Record the model name and index parameters in `data/processed/index/meta.json`.
3. **`text_search.search(...)`** and **`passages_for_entities(...)`** exactly as CONTRACTS §7. Entity filtering and `passages_for_entities` read `data/processed/mentions_linked.jsonl` and `edges_SUPPORTS.csv`; do not require Neo4j.
4. **CLI**: `python -m retrieval.build_index` builds everything; `python -m retrieval.text_search "<query>" --mode bm25_dense` prints the top hits.
5. **Sanity check** on five queries you write yourself (for example "ceftazidime-avibactam aztreonam NDM", "MRSA osteomyelitis", "why is colistin a reserve antibiotic"). Report the top 3 hits per mode. Do not use `eval/questions.json`; the evaluation must stay independent (D16).

## Done when

- `.venv/Scripts/python -m pytest tests` passes, with tests for tokenisation, mode behaviour, RRF, entity filtering and stable results.
- The handoff `docs/handoffs/T11-passage-indexes.md` gives index sizes, build time, model and device, and the sanity-check results.

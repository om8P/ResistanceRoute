# T14: Fusion and answer builder

- **Model:** Sonnet 5.5, effort `high`
- **Wave:** 4
- **Depends on:** T10, T11, T12 (done)
- **Read first:** [ORCHESTRATION.md](../ORCHESTRATION.md), [CONTRACTS.md](../CONTRACTS.md) section 7, [ARCHITECTURE.md](../ARCHITECTURE.md) section 6, [DECISIONS.md](../DECISIONS.md) D14, D15, D18, D34, D39, and the handoffs for [T10](../handoffs/T10-graph-search.md), [T11](../handoffs/T11-passage-indexes.md) and [T12](../handoffs/T12-query-parser.md)

## Goal

Combine the parser, graph search and text search into one function that answers a question in any of the five retrieval modes, with a template-built answer, its reasoning paths and its cited passages. The Streamlit app (T16) and the evaluation (T17) both call it.

## Files you own

- `retrieval/fusion.py`
- `retrieval/answer.py`
- `tests/test_answer.py`

## Interface

`answer(question: str, mode: str = "hybrid", k: int = 10) -> dict` with keys:

| Key | Content |
|---|---|
| `question`, `mode` | The inputs |
| `intent` | From the parser |
| `entities` | The parsed entity IDs, by type |
| `answers` | Ranked list of `{id, label, name, group, aware_group, recommendation_ids, caveats, score, recommended}` |
| `other_active` | Drugs not excluded but not recommended (D39), same shape; `alternatives` intent only |
| `paths` | Reasoning paths (graph modes only) |
| `passages` | Ranked `PassageHit`s as dicts |
| `answer_text` | Template-built text (D15) |
| `declined`, `decline_reason` | For `decline` |
| `disclaimer` | The fixed "not medical advice" sentence |

Modes:

| Mode | Answers from | Passages from |
|---|---|---|
| `bm25`, `dense`, `bm25_dense` | Entities mentioned in the top passages (from `mentions_linked.jsonl`), filtered to the type the intent asks for, ranked by reciprocal rank fusion over the passages that mention them | `text_search.search` |
| `graph` | `graph_search` | `passages_for_entities` on the path entities |
| `hybrid` | `graph_search`, re-ranked: guideline-recommended first, then by number of supporting passages | RRF (k = 60) of BM25, dense and graph-linked passages |

The text-only modes are the baselines. They must be a fair, reasonable attempt, not a straw man: they use the same parser to know what type of answer is wanted.

## Work

1. **`fusion.py`**: RRF over passage lists, answer re-ranking for hybrid, and the text-baseline answer extraction.
2. **`answer.py`**: the function above, plus the CLI `python -m retrieval.answer "<question>" --mode hybrid`, which prints the answer text, the top answers, one path and three passages.
3. **Answer text (D15)**: fixed templates per intent, filled only from retrieved facts. For `alternatives`, one short paragraph per mechanism, guideline-recommended drugs first with their line of therapy and guideline, caveats beneath, then "Not excluded by the resistance data, but not recommended by the guidelines in scope: …". Always end with the guideline names and years, and the disclaimer. No doses.
4. **`unknown`** intent: text retrieval only, and say that the question was not understood as one of the supported types. **`decline`**: the reason and the disclaimer, no retrieval.

## Rules specific to this task

- Do not read `eval/questions.json`; test with questions you write (D16).
- Do not change `graph_search`, `text_search` or `parser`. Report problems. T10 is finishing a small follow-up on `graph_search` (D39–D41) while you start; its interface does not change.

## Done when

- `.venv/Scripts/python -m pytest tests` passes, with tests for every mode, every intent, decline, unknown, RRF and the D39 split.
- The handoff `docs/handoffs/T14-answer-builder.md` shows the full CLI output for the original problem-statement question ("If carbapenem resistance is reported for Klebsiella, which guideline-listed alternatives remain?") in `hybrid` and in `bm25` mode, and the timing per mode.

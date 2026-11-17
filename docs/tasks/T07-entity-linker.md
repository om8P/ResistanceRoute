# T07: Entity matcher and linker

- **Model:** Sonnet 5.5
- **Wave:** 2
- **Depends on:** T03 (done, including its class-family follow-up), T06 for the corpus run
- **Read first:** [ORCHESTRATION.md](../ORCHESTRATION.md), [CONTRACTS.md](../CONTRACTS.md) sections 4, 6 and 7, [ARCHITECTURE.md](../ARCHITECTURE.md) section 4, [DECISIONS.md](../DECISIONS.md) D7, D8, D29, the [T03 handoff](../handoffs/T03-domain-seed.md) and `data/curated/REVIEW_NOTES.md` section 2.5

## Goal

Build the one entity linker used both when building the graph and when parsing questions. It finds mentions of drugs, drug classes, class families, pathogens and mechanisms in text and resolves each to a canonical ID.

## Files you own

- `pipeline/link.py`
- `data/processed/mentions.jsonl`, `data/processed/mentions_linked.jsonl`, `data/processed/unlinked.csv`
- `data/processed/edges_MENTIONS.csv`
- `eval/linking_gold.csv`
- `tests/test_link.py`

## Work

1. **`EntityLinker`** in `pipeline/link.py`, built from `schema/synonyms.csv`, `schema/scope.yaml` and `schema/phenotypes.csv`:
   - `link(text) -> list[LinkedMention]`: finds mentions with a spaCy `PhraseMatcher` (use `spacy.blank("en")`, no model download), `abbreviation` synonyms matched case-sensitively and all others case-insensitively (CONTRACTS §4). Longest match wins when matches overlap.
   - `resolve(surface, entity_type=None) -> LinkedEntity | None`: exact, then normalised (case, hyphens, slashes, plus signs, plurals, Greek letters such as β), then fuzzy with `rapidfuzz` above a threshold you tune. The result records `match_type` (`exact`, `normalised`, `fuzzy`) and `score`.
   - Phenotype acronyms (MRSA, CRKP, CRAB and so on) return the pathogen plus, as extra fields, the implied mechanisms and class family from `phenotypes.csv`.
   - Handle combination drugs written in different ways: `ceftazidime-avibactam`, `ceftazidime/avibactam`, `ceftazidime + avibactam`, `CZA`. A combination must not also be linked as its two single drugs.
   - Fuzzy matching applies only to single tokens or short phrases of at least 5 characters, so that common words are not linked.
   - `LinkedMention` and `LinkedEntity` are small dataclasses or Pydantic models with the fields in CONTRACTS §6 (`mentions_linked.jsonl`).
2. **Corpus run**: CLI `python -m pipeline.link` reads `data/processed/passages.jsonl` (written by T06; if it is not there yet, build and test everything else, then run this step when it appears, or report that it was not run), writes `mentions.jsonl`, `mentions_linked.jsonl`, `unlinked.csv` and `edges_MENTIONS.csv` (`Passage` → entity, `source_id` `curated-seed`, `method` `rule`, `confidence` = the match score; one edge per passage–entity pair as D27 requires). `ClassFamily` mentions are not graph nodes: write them to `mentions_linked.jsonl` but not to `edges_MENTIONS.csv`.
3. **`eval/linking_gold.csv`**: about 100 hand-labelled mentions (`text,surface,entity_type,entity_id`) with varied spellings, abbreviations, brands, typos, phenotype acronyms and sentences that contain no entity. Draw them from real passages and from question-like phrasings. Report accuracy, precision and recall on it in the handoff.

## Done when

- `.venv/Scripts/python -m pytest tests` passes, including tests for case-sensitive abbreviations, combinations, phenotype acronyms, fuzzy matching on typos and no false links on common words.
- The corpus run has produced its outputs, or the handoff explains why not.
- The handoff `docs/handoffs/T07-entity-linker.md` gives the linking accuracy, the top 20 unlinked surfaces, and suggested synonym additions for T03's files (do not edit them).

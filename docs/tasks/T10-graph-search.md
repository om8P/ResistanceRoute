# T10: Cypher templates, reasoning rules and path output

- **Model:** Opus 5.5, effort `high`
- **Wave:** 3
- **Depends on:** T05, T08 (done); `retrieval/types.py` from T12 (being written in parallel)
- **Read first:** [ORCHESTRATION.md](../ORCHESTRATION.md), [CONTRACTS.md](../CONTRACTS.md) section 7 ("Retrieval interfaces"), [ARCHITECTURE.md](../ARCHITECTURE.md) sections 5 and 6, [DECISIONS.md](../DECISIONS.md) D4, D5, D13, D29, D33, D34, D36, the handoffs for [T03](../handoffs/T03-domain-seed.md), [T05](../handoffs/T05-core-graph.md) and [T08](../handoffs/T08-curate-recommendations.md), `data/curated/REVIEW_NOTES.md` section 3 and `data/curated/RECOMMENDATION_NOTES.md` section 3

## Goal

Write the graph reasoning: one parameterised Cypher template per intent, the rules that decide which drugs remain and which recommendations apply, and the reasoning paths that explain each answer. This is the core of the project's claim, so correctness matters more than speed.

## Files you own

- `retrieval/graph_search.py`
- `retrieval/cypher/` (one `.cypher` file per template)
- `tests/test_graph_search.py`

## Work

1. **Templates for the six intents** in ARCHITECTURE §6.1. Parameters come from a `ParsedQuery` (CONTRACTS §7). Labels and relationship types are fixed in the template text; only IDs are parameters.
2. **Class families (D29).** When the question names a family, expand it to every `DrugClass` with that `family`.
3. **Exclusion rule.** Excluded for pathogen `p` and mechanisms `M`: classes `p` is intrinsically resistant to, plus classes any `m` in `M` confers resistance to, plus drugs any `m` in `M` inactivates. Support several mechanisms at once (union), as T03 and T05 asked.
4. **Unknown mechanism.** For "carbapenem-resistant *K. pneumoniae*" with no mechanism named, answer per mechanism: every mechanism of `p` that confers resistance to the named family, one `group` each, so the answer shows how the choice depends on the mechanism.
5. **Recommendations (D33, D34).** A recommendation with `FOR_MECHANISM` to a mechanism in `M` is always returned, with the caveat from `RECOMMENDATION_NOTES.md` §3 when one of its drugs is excluded. Recommendations without a mechanism are filtered: `any-of` drug by drug; `single` and `combination` dropped if any drug is excluded. Return the remaining drugs and the recommendation IDs that support each.
6. **Single-mechanism caveats** from `REVIEW_NOTES.md` §3 (for example aztreonam for NDM, cephalosporins for OXA-48-like) are added to `caveats`.
7. **`why_restricted`**: the drug's AWaRe group, the mechanisms that defeat it, the recommendations that keep it as last resort, and the guideline text that restricts it.
8. **Paths.** For every answer, at least one path from the question's entities to the answer with each relationship's provenance (`source_id`, `method`, `evidence_sources`, `needs_review`). Collect every node ID on the paths in `entity_ids`.
9. **Regimen semantics check.** Some `combination` rows list many drugs, for example "a polymyxin plus another active agent". Decide how such rows are shown so the answer is not misleading, and report the rows and your rule in the handoff.

## Rules specific to this task

- Do not edit the curated files or `pipeline/`. Report data problems.
- Until T12's `retrieval/types.py` exists, write against the field names in CONTRACTS §7; switch to the import when it appears.
- Tests run against the shared Neo4j database, read-only.

## Tests

`tests/test_graph_search.py` must at least check: KPC, NDM and OXA-48-like give the three drug sets in REVIEW_NOTES §3; the unknown-mechanism case returns one group per carbapenemase; NDM returns ceftazidime-avibactam plus aztreonam with its caveat; a family question expands to all classes in the family; every answer has a path with provenance; an MRSA question returns anti-MRSA agents and not beta-lactams other than ceftaroline.

## Done when

- `.venv/Scripts/python -m pytest tests` passes.
- The handoff `docs/handoffs/T10-graph-search.md` shows the output of one question per intent, the regimen rule from step 9, and any data problems found.

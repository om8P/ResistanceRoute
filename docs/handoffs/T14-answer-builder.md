# Handoff: T14 Fusion and answer builder

- **Model:** Sonnet 5.5 (effort high)
- **Status:** complete
- **Date:** 2026-11-18

## What was built

`answer(question, mode, k)` in `retrieval/answer.py` parses the question and answers it in any of the five modes, with a template-built answer text (D15), reasoning paths, cited passages and the fixed disclaimer. `retrieval/fusion.py` holds RRF (k = 60), passage fusion, the text-baseline answer extraction and the D39 split. A previous session had already written all three owned files; I audited them against every point of the brief, found nothing to change, ran everything and kept them as they were.

## Files created or changed

| Path | What it is |
|---|---|
| `retrieval/fusion.py` | `rrf`, `fuse_passages`, `text_baseline_answers`, `split_recommended` (D39), `rerank_graph_answers`, `support_count` |
| `retrieval/answer.py` | `answer()`, the templates, the CLI `python -m retrieval.answer "<question>" --mode hybrid [-k N]` |
| `tests/test_answer.py` | 42 tests: RRF, D39 split, re-ranking, stubbed behaviour of every mode, decline, unknown, real text baselines for every intent, CLI, live graph/hybrid for every intent |

No other file was edited. `eval/questions.json` was not read.

## How to run and check it

```bash
.venv/Scripts/python -m retrieval.answer "If carbapenem resistance is reported for Klebsiella, which guideline-listed alternatives remain?" --mode hybrid
.venv/Scripts/python -m retrieval.answer "If carbapenem resistance is reported for Klebsiella, which guideline-listed alternatives remain?" --mode bm25
.venv/Scripts/python -m pytest tests/test_answer.py
```

## Test result

- `tests/test_answer.py`: `42 passed`.
- Full suite `.venv/Scripts/python -m pytest tests` (Neo4j `amr-navigator-neo4j` running): **`713 passed, 2 warnings in 38.34s`** (the warnings are click deprecations inside `typer`, not ours). No failures.

## What I found

**Return value.** Beyond the brief's keys, `answer()` also returns `cypher` (queries run), `empty_reason`, `note` (set for `unknown` and for the hybrid fallback) and `timing_s`. `answers[]` holds guideline-recommended drugs only for `alternatives`; drugs the graph keeps active but no guideline recommends are in `other_active` (D39, score >= 0.5). Drugs that are neither are dropped. `paths` keeps only paths whose answer is shown, ordered like the answers.

**Modes.**
- `bm25`, `dense`, `bm25_dense`: `text_search.search` over the question, then entities of the type the intent asks for (`TARGET_TYPES` in `fusion.py`) are taken from `mentions_linked.jsonl` of the top passages, skipping entities the question already names, scored by RRF over passage ranks. `paths` is empty. The answer text says plainly that these come from wording and are not checked against recommendations or resistance data.
- `graph`: `graph_search`; guideline-recommended first in the graph's own order; passages from `passages_for_entities` on the path entities (plus Passage nodes the graph itself returns, for `why_restricted`).
- `hybrid`: graph answers re-ranked within each mechanism group: recommended first, then drugs active on their own before drugs kept only through a mechanism-specific rescue (score < 0.5), then number of supporting passages in the fused pool, then graph score. Passages are the RRF of BM25 (depth 50), dense (50) and graph-linked passages. If the graph has no answer, hybrid falls back to passage entities and says so.
- `unknown`: text retrieval only in every mode (`bm25_dense` for the graph modes), no answers, and the text says the question was not understood. `decline`: reason plus disclaimer, no retrieval at all.

**Answer text.** Fixed templates, no doses (a regex in the tests checks this), ends with the guideline titles and years of the recommendations or passages used, then the disclaimer. `alternatives`: one paragraph per mechanism, recommended drugs with AWaRe group, line of therapy and guideline short name and year, then caveats, then the "Not excluded by the resistance data, but not recommended by the guidelines in scope" list. Caveats come from `graph_search`, which reads them from `data/curated/recommendations_curated.csv`; `REC:` prefixes are stripped, similar sentences merged (at most 4 shown per paragraph, the rest counted, all kept in `answers[].caveats`).

**Original question, live graph.** Intent `alternatives`, pathogen *K. pneumoniae*, recommended drugs per mechanism KPC 12, NDM 12, OXA-48-like 11, VIM 7, matching the T10 handoff, with the not-recommended active drugs apart. Full CLI output below.

**Timing (same question, one process, Neo4j warm, wall-clock of `answer()`):**

| Mode | First call in process | Repeat (mean of 3) |
|---|---|---|
| bm25 | 0.30 s | 0.01 s |
| dense | 8.87 s (loads the embedding model) | 0.01 s |
| bm25_dense | 0.02 s | 0.01 s |
| graph | 0.34 s | 0.13 s |
| hybrid | 0.12 s | 0.10 s |

The first CLI run of `hybrid` took 11.51 s only because it was the first call in a fresh process (model load, as for `dense` above). A long-running app (T16) pays this once; T17 should call `answer("...", "dense")` once before timing.

**Observations for later tasks.**
- The `bm25` baseline for the original question returns generic drugs (linezolid and vancomycin among them), and its top passages are about NDM epidemiology, not treatment. That is the expected weakness of the baseline, not a bug.
- In the hybrid output the same drug appears once per mechanism group in `answers` (for example colistin under KPC, NDM, OXA-48-like and VIM). `answers[].group` tells them apart. T17 must de-duplicate by `id` before scoring, in line with `eval/metrics.py`.
- In the CLI "Other active" line, drug names can repeat across groups for the same reason.
- The Store-Python launcher inside this session's sandbox could not start `.venv/Scripts/python`; all Python runs were done with the sandbox disabled for the Bash call, nothing else changed.

## CLI output: `hybrid`

```text
Question: If carbapenem resistance is reported for Klebsiella, which guideline-listed alternatives remain?
Mode: hybrid   Intent: alternatives   Time: 11.51 s

Alternatives for Klebsiella pneumoniae when resistance to carbapenem is reported, separated by the resistance mechanism.

KPC beta-lactamase: Recommended by the guidelines in scope: ceftazidime-avibactam (Reserve; first line; ICMR 2022, WHO 2022); colistin (Reserve; first line; ICMR 2022); polymyxin B (Reserve; first line; ICMR 2022); fosfomycin (Reserve; first line; ICMR 2022, ICMR 2019, WHO 2022); tigecycline (Reserve; first line; ICMR 2022); meropenem-vaborbactam (Reserve; last resort; WHO 2022); amikacin (Access; first line; ICMR 2022); plazomicin (Reserve; last resort; WHO 2022); gentamicin (Access; first line; ICMR 2022); doxycycline (Access; alternative; ICMR 2019); meropenem (Watch; alternative; ICMR 2022); imipenem-cilastatin (Watch; alternative; ICMR 2022). Caveats: Only as the base of a combination: colistin plus one other active agent (tigecycline, gentamicin, amikacin, fosfomycin, meropenem, imipenem-cilastatin) (colistin). Only as the base of a combination: polymyxin B plus one other active agent (tigecycline, gentamicin, amikacin, fosfomycin, meropenem, imipenem-cilastatin) (polymyxin B). Only as a combination partner of colistin or polymyxin B, not on its own (fosfomycin, tigecycline, amikacin, gentamicin, meropenem and imipenem-cilastatin). Only as the base of a combination: fosfomycin plus one other active agent (doxycycline) (fosfomycin). 13 more caveat(s) are listed with each answer. Not excluded by the resistance data, but not recommended by the guidelines in scope: cefiderocol, imipenem-cilastatin-relebactam, aztreonam-avibactam, sulfamethoxazole-trimethoprim, eravacycline, levofloxacin, minocycline, moxifloxacin, ciprofloxacin, nitrofurantoin, tobramycin.

NDM beta-lactamase: Recommended by the guidelines in scope: colistin (Reserve; first line; ICMR 2022); polymyxin B (Reserve; first line; ICMR 2022); fosfomycin (Reserve; first line; ICMR 2022, ICMR 2019, WHO 2022); tigecycline (Reserve; first line; ICMR 2022); cefiderocol (Reserve; last resort; WHO 2022); aztreonam (Reserve; first line; ICMR 2022, WHO 2022); amikacin (Access; first line; ICMR 2022); gentamicin (Access; first line; ICMR 2022); doxycycline (Access; alternative; ICMR 2019); ceftazidime-avibactam (Reserve; first line; ICMR 2022, WHO 2022); meropenem (Watch; alternative; ICMR 2022); imipenem-cilastatin (Watch; alternative; ICMR 2022). Caveats: Only as the base of a combination: colistin plus one other active agent (tigecycline, gentamicin, amikacin, fosfomycin, meropenem, imipenem-cilastatin) (colistin). Only as the base of a combination: polymyxin B plus one other active agent (tigecycline, gentamicin, amikacin, fosfomycin, meropenem, imipenem-cilastatin) (polymyxin B). Only as a combination partner of colistin or polymyxin B, not on its own (fosfomycin, tigecycline, amikacin, gentamicin, meropenem and imipenem-cilastatin). Only as the base of a combination: fosfomycin plus one other active agent (doxycycline) (fosfomycin). 21 more caveat(s) are listed with each answer. Not excluded by the resistance data, but not recommended by the guidelines in scope: aztreonam-avibactam, plazomicin, sulfamethoxazole-trimethoprim, eravacycline, levofloxacin, minocycline, moxifloxacin, ciprofloxacin, nitrofurantoin, tobramycin.

OXA-48-like beta-lactamase: Recommended by the guidelines in scope: ceftazidime-avibactam (Reserve; first line; ICMR 2022, WHO 2022); colistin (Reserve; first line; ICMR 2022); polymyxin B (Reserve; first line; ICMR 2022); fosfomycin (Reserve; first line; ICMR 2022, ICMR 2019, WHO 2022); tigecycline (Reserve; first line; ICMR 2022); aztreonam (Reserve; first line; ICMR 2022); amikacin (Access; first line; ICMR 2022); gentamicin (Access; first line; ICMR 2022); doxycycline (Access; alternative; ICMR 2019); meropenem (Watch; alternative; ICMR 2022); imipenem-cilastatin (Watch; alternative; ICMR 2022). Caveats: Only together with aztreonam (combination) (ceftazidime-avibactam). The recommendation is for isolates that also produce NDM beta-lactamase (ceftazidime-avibactam and aztreonam). Only as the base of a combination: colistin plus one other active agent (tigecycline, gentamicin, amikacin, fosfomycin, meropenem, imipenem-cilastatin) (colistin). Only as the base of a combination: polymyxin B plus one other active agent (tigecycline, gentamicin, amikacin, fosfomycin, meropenem, imipenem-cilastatin) (polymyxin B). 16 more caveat(s) are listed with each answer. Not excluded by the resistance data, but not recommended by the guidelines in scope: cefiderocol, ceftazidime, aztreonam-avibactam, cefepime, ceftriaxone, plazomicin, sulfamethoxazole-trimethoprim, cefotaxime, eravacycline, levofloxacin, minocycline, moxifloxacin, cefazolin, ceftaroline fosamil, cefuroxime and 3 more.

VIM beta-lactamase: Recommended by the guidelines in scope: colistin (Reserve; first line; ICMR 2022); polymyxin B (Reserve; first line; ICMR 2022); fosfomycin (Reserve; first line; ICMR 2022, ICMR 2019, WHO 2022); tigecycline (Reserve; first line; ICMR 2022); amikacin (Access; first line; ICMR 2022); gentamicin (Access; first line; ICMR 2022); doxycycline (Access; alternative; ICMR 2019). Caveats: Only as the base of a combination: colistin plus one other active agent (tigecycline, gentamicin, amikacin, fosfomycin) (colistin). Only as the base of a combination: polymyxin B plus one other active agent (tigecycline, gentamicin, amikacin, fosfomycin) (polymyxin B). Only as a combination partner of colistin or polymyxin B, not on its own (fosfomycin, tigecycline, amikacin and gentamicin). Only as the base of a combination: fosfomycin plus one other active agent (doxycycline) (fosfomycin). 8 more caveat(s) are listed with each answer. Not excluded by the resistance data, but not recommended by the guidelines in scope: cefiderocol, aztreonam, aztreonam-avibactam, plazomicin, sulfamethoxazole-trimethoprim, eravacycline, levofloxacin, minocycline, moxifloxacin, ciprofloxacin, nitrofurantoin, tobramycin.

Guidelines: Guidance on Diagnosis and Management of Carbapenem Resistant Gram-negative Infections (2022); The WHO AWaRe (Access, Watch, Reserve) antibiotic book (2022); Treatment Guidelines for Antimicrobial Use in Common Syndromes (2019).

This is an educational tool, not medical advice. It does not replace a clinician, local susceptibility results or the full guidelines, and it gives no doses or patient-specific advice.

Top answers:
  ceftazidime-avibactam  [KPC beta-lactamase]  Reserve  score 1.000  recommended
  colistin  [KPC beta-lactamase]  Reserve  score 1.000  recommended
  polymyxin B  [KPC beta-lactamase]  Reserve  score 1.000  recommended
  fosfomycin  [KPC beta-lactamase]  Reserve  score 1.000  recommended
  tigecycline  [KPC beta-lactamase]  Reserve  score 1.000  recommended
  meropenem-vaborbactam  [KPC beta-lactamase]  Reserve  score 0.700  recommended
  amikacin  [KPC beta-lactamase]  Access  score 1.000  recommended
  plazomicin  [KPC beta-lactamase]  Reserve  score 0.700  recommended
  gentamicin  [KPC beta-lactamase]  Access  score 1.000  recommended
  doxycycline  [KPC beta-lactamase]  Access  score 0.800  recommended

Other active, not recommended (51): cefiderocol, imipenem-cilastatin-relebactam, aztreonam-avibactam, sulfamethoxazole-trimethoprim, eravacycline, levofloxacin, minocycline, moxifloxacin, ciprofloxacin, nitrofurantoin, tobramycin, aztreonam-avibactam

One path:
  Klebsiella pneumoniae -[HAS_MECHANISM curated-seed/curated]-> KPC beta-lactamase -[NOT_EXCLUDED derived]-> ceftazidime-avibactam -[IN_CLASS curated-seed/curated]-> Cephalosporin/beta-lactamase-inhibitor combinations

Top passages:
  1. pubmed-36705145:abstract:1 (pNone, score 0.0338)
     In vitro activity of newer β-lactam/β-lactamase inhibitor combinations, cefiderocol, plazomicin and comparators against carbapenemase-producing Klebsiella pneumoniae isolates. Infections by carbapenem
  2. icmr-treatment-guidelines-2019:hospital-acquired:22 (p113, score 0.0333)
     atin IV 500 mg Sulbactam(2:l) IV 3 g q12 may be used in E. coli/Klebsiella Carbapenem q6h h infections if the organism is sensitive Or Or susceptible Meropenem IV Piperacillin-tazobactam IV 1g q8h 4.5
  3. icmr-cr-gram-negative-2022:directed-enterobacterales:5 (p16, score 0.0315)
     Table 4: Available treatment options for carbapenem resistant Enterobacterales in India. Carbapenemase KPC: 1st choice: Prolonged Infusion of ceftazidime-avibactam **; other options: a. Polymyxins (do
```

## CLI output: `bm25`

```text
Question: If carbapenem resistance is reported for Klebsiella, which guideline-listed alternatives remain?
Mode: bm25   Intent: alternatives   Time: 0.30 s

Text retrieval only (bm25). The drugs most often mentioned in the best-matching passages: polymyxin B, linezolid, vancomycin, amikacin, colistin, meropenem-vaborbactam, meropenem, levofloxacin, imipenem-cilastatin, ceftazidime-avibactam. These come from passage wording and are not checked against the guideline recommendations or the resistance data.

Guidelines: The WHO AWaRe (Access, Watch, Reserve) antibiotic book (2022); Treatment Guidelines for Antimicrobial Use in Common Syndromes (2019).

This is an educational tool, not medical advice. It does not replace a clinician, local susceptibility results or the full guidelines, and it gives no doses or patient-specific advice.

Top answers:
  polymyxin B  [-]  Reserve  score 0.030  text
  linezolid  [-]  Reserve  score 0.029  text
  vancomycin  [-]  Watch  score 0.029  text
  amikacin  [-]  Access  score 0.029  text
  colistin  [-]  Reserve  score 0.029  text
  meropenem-vaborbactam  [-]  Reserve  score 0.029  text
  meropenem  [-]  Watch  score 0.015  text
  levofloxacin  [-]  Watch  score 0.015  text
  imipenem-cilastatin  [-]  Watch  score 0.015  text
  ceftazidime-avibactam  [-]  Reserve  score 0.014  text

Top passages:
  1. pubmed-30700432:abstract:1 (pNone, score 11.4539)
     NDM Metallo-β-Lactamases and Their Bacterial Producers in Health Care Settings. New Delhi metallo-β-lactamase (NDM) is a metallo-β-lactamase able to hydrolyze almost all β-lactams. Twenty-four NDM var
  2. pubmed-32325019:abstract:1 (pNone, score 10.4299)
     Mobile genetic elements associated with carbapenemase genes in South American Enterobacterales. INTRODUCTION: Carbapenem resistance in members of order Enterobacterales is a growing public health prob
  3. pubmed-38584572:abstract:1 (pNone, score 10.1587)
     Epidemiology and clinical significance of carbapenemases in Australia: a narrative review. Carbapenemase-producing gram-negative bacteria (CP-GNB) infections threaten public health with high mortality
```

## Deviations from the brief or contracts

- The returned dict has extra keys (`cypher`, `empty_reason`, `note`, `timing_s`); nothing is removed. `CONTRACTS.md` section 7 still lists `path` (singular) for `answer()`; the brief's `paths` is what is implemented.

## Not done or not verified

- Answer quality against the gold questions is not measured here (`eval/questions.json` was not read, per D16); that is T17.
- The text of the `unknown` and hybrid-fallback paths is only tested with a stubbed graph and a few real questions.

## Requests to orchestrator

- Update the `retrieval/` row in `CONTRACTS.md` section 7: key `paths` (list), plus `answers`, `other_active`, `answer_text`, `declined`, `decline_reason`, `disclaimer`, `timing_s`.
- T17: de-duplicate `answers` by `id` before computing ranking metrics (the same drug repeats per mechanism group), and warm the dense model before timing.
- Open item already known from T10: `caveat`, `base_drug_ids` and `susceptible_only` are still read from the curated CSV, not from the `Recommendation` nodes. No change needed in T14 when that moves.

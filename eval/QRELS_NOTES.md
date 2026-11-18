# Relevance judgements: notes (T15)

`eval/qrels.json` lists, for each of the 40 evaluation questions, the passages judged relevant to it: `{"Q01": {"<passage id>": 2, ...}, ...}`. Only grades 1 and 2 are listed; every other pooled passage was judged 0. The judgements were made on 2026-11-18 by one judge (Claude, Opus 5.5) reading the passages. They are meant for T17, which scores passage retrieval with Recall@k, MRR and nDCG@k.

## 1. Grades

| Grade | Meaning | Example |
|---|---|---|
| 2 | The passage states the answer or a key part of it, as its own point. | ICMR 2022 p16 "Carbapenemase KPC: 1st choice: Prolonged Infusion of ceftazidime-avibactam" for Q15. |
| 1 | The passage is on topic and useful context. It names the answer only in passing, gives part of the reasoning, or answers a closely related question. | A PubMed abstract whose first sentence calls colistin "the last-resort antibiotic", for Q05. |
| 0 | Not relevant, including passages that only mention the question's entities. | Case series and epidemiology studies that name KPC but say nothing about treatment, for Q02. |

Rules used throughout:

- **Judged by the passage text alone**, not by which method found it, its source type (guideline or abstract), or its rank.
- **The whole passage counts**, including the 30-word overlap with the previous passage. Neighbouring passages were judged separately, on the text each one contains.
- **Tables count.** Expected-activity tables (AWaRe Table 41.1 and the drug-chapter tables) were read cell by cell. Where a table gives the answer, for example "+" for cefiderocol against NDM, the passage is grade 2.
- **Passing mention = 1, focused statement = 2.** A passage that names the answer as background is 1. A passage whose point is the answer is 2.
- **Questions that name a source** ("According to ICMR…": Q15, Q16, Q26): the passage from that source is 2. Passages from other sources that support the same answer are 1.
- **Number questions** (Q04, Q11, Q20, Q28): no passage contains the GLASS figure, which comes from the GLASS file, not the corpus. Passages giving an Indian resistance rate for the same organism from another source (ICMR) are 1.
- **Decline questions** (Q17, Q24, Q32, Q40) have no relevant passages by rule (T15 brief), even where a passage contains the requested content (colistin doses in ICMR 2022, linezolid for VRE in AWaRe).
- **Answers beyond the gold set.** Where a passage states something the T09 notes accept as correct extra content (for example chromosomal *mgrB* mutations for Q38), it is graded like the gold content. Passages recommending drugs the gold deliberately leaves out (for example cefiderocol for CRAB, Q08) are 1: on topic, but not the gold answer.

## 2. Pooling

`python -m eval.build_pool` builds the pool. For each question it takes the union of:

| Method | What it adds |
|---|---|
| `bm25`, `dense`, `bm25_dense` | Top 20 from `retrieval.text_search.search(question, mode, k=20)` |
| `entities` | Top 20 from `passages_for_entities(question entities, k=20)` |
| `gold_page` | Every passage covering a guideline page cited in `gold_source` (`<doc> p<page>`). A passage stores only its start page, so it is taken to run up to the start page of the next passage in the same document. |
| `manual` | Passages found by a targeted search of the whole corpus. Only one: `pubmed-40887577:abstract:1` for Q23 (section 5). |

The pool is deterministic: rebuilt after judging, it matched the judged pool exactly, apart from the one manual addition.

| | Count |
|---|---|
| Question–passage pairs pooled | 2,084 (33–67 per question) |
| Pairs for the 36 answerable questions | 1,883 |
| Distinct passages in those pairs | 598 |
| Words in those pairs | about 425,000 |

## 3. How the judging was done

The pool is too large to read every pair in full (about 425,000 words), so each question was judged in one batch in two steps:

1. A compact view listed every pooled passage with its section heading, page, the methods that found it, and up to three keyword-in-context snippets (about 22 words each) for terms from the question and gold answer. A passage with no keyword hit showed its first 20 words.
2. Every passage that could be relevant from that view was read in full before it was graded (about 40 full reads, mostly guideline drug chapters and treatment-focused abstracts), or graded from its snippets where those already contained the whole statement being judged (for example the ICMR treatment-table rows).

Passages were graded 0 from the compact view when the heading and snippets showed they were off topic: for example eye-infection or diarrhoea chapters, the repeated "Legend: ACCESS antibiotics are indicated in green…" table footers, and epidemiology abstracts that name a mechanism but discuss no treatment. Every pooled passage got a grade. The grades were stored per question and written to `qrels.json` at the end.

## 4. Results

### Totals

| | Grade 2 | Grade 1 | Total relevant |
|---|---|---|---|
| All 40 questions | 113 | 232 | 345 |
| Single-hop (20) | 31 | 59 | 90 |
| Multi-hop (20) | 82 | 173 | 255 |

### Per question

| Q | Hops | Intent | Pool | Grade 2 | Grade 1 |
|---|---|---|---|---|---|
| Q01 | single | drug_profile | 47 | 1 | 1 |
| Q02 | multi | alternatives | 51 | 9 | 17 |
| Q03 | multi | alternatives | 57 | 7 | 14 |
| Q04 | single | surveillance | 46 | 0 | 2 |
| Q05 | single | why_restricted | 49 | 6 | 15 |
| Q06 | single | mechanism_lookup | 47 | 1 | 1 |
| Q07 | multi | recommendation_lookup | 67 | 5 | 5 |
| Q08 | multi | alternatives | 47 | 4 | 16 |
| Q09 | single | drug_profile | 53 | 0 | 1 |
| Q10 | multi | why_restricted | 66 | 9 | 16 |
| Q11 | single | surveillance | 51 | 0 | 2 |
| Q12 | multi | mechanism_lookup | 65 | 2 | 8 |
| Q13 | multi | alternatives | 54 | 8 | 13 |
| Q14 | single | why_restricted | 42 | 2 | 10 |
| Q15 | multi | recommendation_lookup | 49 | 1 | 5 |
| Q16 | multi | recommendation_lookup | 52 | 2 | 6 |
| Q17 | single | decline | 49 | 0 | 0 |
| Q18 | multi | alternatives | 44 | 5 | 12 |
| Q19 | single | drug_profile | 65 | 0 | 4 |
| Q20 | single | surveillance | 54 | 0 | 1 |
| Q21 | multi | why_restricted | 56 | 4 | 12 |
| Q22 | multi | mechanism_lookup | 40 | 2 | 3 |
| Q23 | multi | alternatives | 57 | 1 | 8 |
| Q24 | single | decline | 61 | 0 | 0 |
| Q25 | single | drug_profile | 33 | 4 | 5 |
| Q26 | multi | recommendation_lookup | 63 | 1 | 3 |
| Q27 | multi | alternatives | 54 | 3 | 4 |
| Q28 | single | surveillance | 61 | 0 | 2 |
| Q29 | single | why_restricted | 50 | 2 | 5 |
| Q30 | single | mechanism_lookup | 43 | 4 | 3 |
| Q31 | multi | alternatives | 62 | 3 | 8 |
| Q32 | single | decline | 42 | 0 | 0 |
| Q33 | multi | recommendation_lookup | 54 | 1 | 4 |
| Q34 | single | why_restricted | 38 | 6 | 3 |
| Q35 | single | surveillance | 58 | 0 | 1 |
| Q36 | multi | alternatives | 57 | 1 | 7 |
| Q37 | single | why_restricted | 51 | 5 | 3 |
| Q38 | multi | mechanism_lookup | 48 | 6 | 5 |
| Q39 | multi | why_restricted | 52 | 8 | 7 |
| Q40 | single | decline | 49 | 0 | 0 |

### Relevant passages per pooling method

A passage found by several methods counts once for each.

| Method | Pairs pooled | Grade 2 found | Grade 1 found | Relevant found only by this method |
|---|---|---|---|---|
| `bm25` | 800 | 62 | 102 | 15 |
| `dense` | 800 | 55 | 93 | 19 |
| `bm25_dense` | 800 | 64 | 120 | 7 |
| `entities` | 771 | 55 | 105 | 50 |
| `gold_page` | 162 | 51 | 50 | 42 |
| `manual` | 1 | 1 | 0 | 1 |

Reading:

- The three text modes together found 245 of the 345 relevant pairs. The other 100 came only from the entity links, the gold-source pages or the manual search.
- `gold_page` has the highest precision. That is expected, because those pages were used to write the gold answers.
- The 42 relevant passages found only through `gold_page` show that text retrieval at depth 20 misses some of the guideline passages the gold answers cite. T17 should not read low recall for the text modes as a judging artefact.
- These counts describe pool depth 20; they are not T17's Recall@k.

### Questions with no relevant passage

- **The four decline questions** (Q17, Q24, Q32, Q40) have none, by rule. Every answerable question has at least one relevant passage.
- **Eleven questions have no grade-2 passage**:
  - the four decline questions;
  - the four GLASS number questions (Q04, Q11, Q20, Q28);
  - Q35, whose answer is that GLASS has no *P. aeruginosa* data, which no passage says;
  - Q09 and Q19, the AWaRe groups of ceftolozane-tazobactam and piperacillin-tazobactam, which only the AWaRe 2025 spreadsheet gives.

  For the seven answerable ones among these, passage retrieval can find only grade-1 passages, so nDCG is computed against grade-1 passages alone.

## 5. Q23: ceftaroline for MRSA

The gold answer (ceftaroline) is sourced only to the curated seed, so I searched the whole corpus for it. **Only 4 of 1,428 passages mention ceftaroline, all PubMed abstracts; no guideline passage does.**

| Passage | In pool? | Content | Grade |
|---|---|---|---|
| `pubmed-40887577:abstract:1` | No (added as `manual`) | Surveillance study: MRSA prevalence 79.1%, "S. aureus remained susceptible to vancomycin, linezolid and ceftaroline". | 2 |
| `pubmed-39806392:abstract:1` | Yes | Ceftaroline-based combination therapy for MRSA bacteraemia; no outcome benefit. | 1 |
| `pubmed-33609718:abstract:1` | Yes | Daptomycin plus ceftaroline salvage therapy for MRSA bacteraemia. | 1 |
| `pubmed-39777519:abstract:1` | Yes | Ceftaroline or vancomycin with carbapenems against MRSA, in vitro and in mice. | 1 |

The only direct support is one in-vitro susceptibility statement, in an abstract that is mainly about Gram-negative bacteria. The three pooled abstracts treat ceftaroline as an anti-MRSA drug, but always in combinations, so they imply rather than state that it is active on its own. Q23 has five more grade-1 passages: four on beta-lactam activity against MRSA (two trials of adding a beta-lactam to vancomycin or daptomycin, two laboratory studies), and ICMR 2019 p111 (a beta-lactam is preferred for MSSA; MRSA gets vancomycin or daptomycin).

## 6. Hard judgement calls

- **Q01, Q09, Q19, Q25 (class and AWaRe group).** No passage states the AWaRe group of meropenem, ceftolozane-tazobactam or piperacillin-tazobactam.
  - Q01 has a grade 2 only for "a carbapenem (meropenem)" (AWaRe p622).
  - For Q25, AWaRe book passages stating that IV fosfomycin is a Reserve antibiotic are 2. No passage gives the Watch group of oral fosfomycin.
- **Q29 (why Watch, not Access).** No passage names meropenem as Watch. The AWaRe p21 definitions of Access and Watch (narrow or broad spectrum, cost, when to use) are graded 2, because they state the reason the gold gives.
- **Q03 (NDM: beta-lactams).** ICMR 2022 p16 "ceftazidime-avibactam and aztreonam" for NDM is 2, because the T09 notes accept the combination. Passages saying only that ceftazidime-avibactam is inactive against NDM are 1.
- **Q12 (E. coli and 3rd-generation cephalosporins).** No passage explains E. coli resistance mechanisms directly.
  - ICMR 2019 p12 (resistance "up to 75% on account of ESBL production") and a ceftolozane-tazobactam abstract (3GC resistance from ESBL or AmpC) are 2.
  - The expected-activity tables that list ESBL, AmpC and carbapenemases are 1.
- **Q14 (polymyxin B and UTI).** Only AWaRe p639 gives the reason: colistimethate is excreted by the kidneys, polymyxin B is not. The ICMR rule "do not use polymyxin B for UTI", repeated in seven passages, is 1.
- **Q37 (tigecycline alone for bacteraemia).** The ICMR rule, repeated in five passages, is 2, because the gold answer is the rule itself. No passage gives a pharmacological reason.
- **Q38 (colistin resistance in *K. pneumoniae*).** Passages showing chromosomal *mgrB* disruption as the main mechanism are 2, alongside MCR passages. The handoff discusses the gold answer.
- **Q21 (CZA and OXA-23 *Acinetobacter*).** AWaRe passages saying ceftazidime-avibactam is not indicated for, or has limited activity against, *A. baumannii* are 2. Passages that only describe OXA-23 as a class D enzyme in *A. baumannii* are 1.
- **Q22 (pan-aminoglycoside resistance).** Two passages are 2:
  - AWaRe p631: ribosomal modification of the target site can stop plazomicin binding.
  - A Nepal *K. pneumoniae* study: isolates highly resistant to aminoglycosides carried 16S rRNA methyltransferase genes (*armA*, *rmtB*).

## 7. Limits

- **One judge, no second opinion.** There is no inter-annotator agreement figure. Borderline grade-1 calls are the least reliable part.
- **Zeros from the compact view.** Most of the 1,538 zero grades for answerable questions were given from headings and snippets, without a full read. Snippets were built from question terms, so a passage that states the answer in completely different words could have been missed. Grade 1 is the more likely casualty than grade 2.
- **Pool depth 20.** Relevant passages ranked below 20 by every method, and not linked to a gold entity or gold page, are not judged. Section 5 shows one such passage for Q23. Recall@k in T17 is therefore recall against the pool, which is standard but optimistic.
- **The judge knew the gold answers.** This is intended: a passage is relevant if it supports the gold answer.

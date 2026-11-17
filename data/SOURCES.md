# Data sources

Everything under `data/raw/` is fetched by `pipeline/download.py` and is not committed (decision D19). Every file, with its URL, retrieval date, size and SHA-256, is listed in `data/raw/manifest.json`.

```bash
.venv/Scripts/python -m pipeline.download                 # all sources; existing files are skipped
.venv/Scripts/python -m pipeline.download --only aware,card
.venv/Scripts/python -m pipeline.download --force         # download again
```

Retrieved on **2026-11-17**. Total on disk: about 137 MB. Every URL below was fetched and checked. Requests carry the User-Agent `amr-navigator/0.1`, a 60-second timeout, and no name, e-mail address or API key. NCBI calls are limited to 2.5 per second.

**All six sources downloaded automatically. No manual download is needed.** Three things differ from what the brief assumed; they are marked "Differs from the brief" below.

| Folder | Source | Automatic | Size |
|---|---|---|---|
| `aware/` | WHO AWaRe classification (2025 and 2023 workbooks) | yes | 0.2 MB |
| `card/` | CARD data archive v4.0.2 and CARD ontology v4.0.2 | yes | 56 MB |
| `glass/` | WHO GLASS-AMR resistance rows, via the WHO data portal API | yes | 44 MB |
| `guidelines/` | WHO AWaRe antibiotic book; ICMR treatment guidelines 2019; ICMR carbapenem-resistant Gram-negative guidance 2022 | yes | 17 MB |
| `taxonomy/` | NCBI Taxonomy, five pathogens | yes | 11 KB |
| `pubmed/` | PubMed abstracts, 319 | yes | 0.7 MB |

## aware: WHO AWaRe classification

| | |
|---|---|
| URLs | 2025: `https://iris.who.int/server/api/core/bitstreams/a8c53afc-fa43-4883-9a59-21a9e069f40c/content` (landing page `https://www.who.int/publications/i/item/B09489`). 2023: `https://iris.who.int/server/api/core/bitstreams/abba5c2a-8457-431c-9695-16cb2317dd0e/content` (landing page `https://www.who.int/publications/i/item/WHO-MHP-HPS-EML-2023.04`) |
| Version | 2025 edition, published 5 September 2025 (report no. B09489); 2023 edition, published 26 July 2023 |
| Licence | CC BY-NC-SA 3.0 IGO |
| Files | `WHO-AWaRe-classification-2025.xlsx`, `WHO-AWaRe-classification-2023.xlsx` |
| How | Automatic |

The brief asks for the latest edition (2025). The 2023 workbook is kept as well because `docs/CONTRACTS.md` names `who-aware-2023` as an edge source; it is 0.1 MB.

## card: Comprehensive Antibiotic Resistance Database

| | |
|---|---|
| URLs | Data: `https://card.mcmaster.ca/download/0/broadstreet-v4.0.2.tar.bz2` (the same bytes as `https://card.mcmaster.ca/latest/data`). Ontology: `https://card.mcmaster.ca/download/5/ontology-v4.0.2.tar.bz2`. Download page: `https://card.mcmaster.ca/download` |
| Version | 4.0.2, built 11 and 12 August 2026 (`card.json` `_version` is `4.0.2`) |
| Licence | Free for academic use. The README in the archive says commercial use, in whole or in part, needs written permission from McMaster University. Cite Alcock et al. 2023, Nucleic Acids Research 51, D690-D699. |
| Files | `card-data-v4.0.2.tar.bz2` and `card-ontology-v4.0.2.tar.bz2` (kept for the checksum), plus the extracted files: `card/card.json`, `aro_index.tsv`, `aro_categories.tsv`, `aro_categories_index.tsv`, `PMID.tsv`, `snps.txt`, `shortname_antibiotics.tsv`, `shortname_pathogens.tsv`, nucleotide and protein FASTA files, `CARD-Download-README.txt`; and in `card/ontology/`: `aro.obo`, `aro.json`, `aro.owl`, `aro.tsv`, `mo.*`, `ncbi_taxonomy.*`, `ro.*`, `viro.*`, `Ontology-Download-README.txt` |
| How | Automatic |

Differs from the brief: the brief lists only the data archive. The ontology archive is added because `aro.obo` holds the relationships to individual antibiotics and the drug-class hierarchy that the data archive lacks.

## glass: WHO GLASS antimicrobial resistance data

| | |
|---|---|
| URLs | `https://xmart-api-public.who.int/DATA_/RELAY_GLASS_AMR_CTA` (rows) and `https://xmart-api-public.who.int/DATA_/REF_COUNTRY` (country names). This is the public API behind the WHO AMR data portal `https://data.who.int/dashboards/amr`. The WHO GHO bulk download `global-antimicrobial-resistance-surveillance-system-glass.zip` was also fetched and checked; it holds only programme-enrolment indicators (no resistance percentages), so it is not used. |
| Version | Data years 2016 to 2023. The API table has no version number; the table was last loaded by WHO in autumn 2026. |
| Licence | WHO data portal datasets: CC BY 4.0 with WHO's additional terms (stated on `https://data.who.int/dashboards/amr/overview`) |
| Files | `glass_amr_pathogens.csv` (233,306 rows), `countries.csv` (249 rows) |
| How | Automatic: paged OData queries. The filter is stored in the manifest note and in `pipeline/download.py` (`glass_filter()`). |

The CSV holds only rows where the age group is "Total" and the indicator is one of `PERCENTAGERESISTANCE`, `PERCENTAGERESISTANCELOWER`, `PERCENTAGERESISTANCEUPPER`, `RESISTANT` or `INTERPRETABLEAST`, for the GLASS pathogens in scope. The full table has 4.3 million rows (age and sex breakdowns, counts of sampled patients and so on); only a subset is downloaded to keep the size down. Edit `GLASS_INDICATORS` in the script and run with `--force` to get more.

Differs from the brief: **GLASS-AMR does not report *Pseudomonas aeruginosa*** (the query asked for it and returned zero rows), and it reports *Acinetobacter* at genus level ("Acinetobacter spp."), not *A. baumannii*. The GLASS-AMR pathogens are *E. coli*, *K. pneumoniae*, *Acinetobacter* spp., *S. aureus*, *S. pneumoniae*, *Salmonella* spp., *Shigella* spp. and *N. gonorrhoeae*.

Manual fallback: if the API stops working, the same data can be exported by hand from the GLASS dashboard at `https://worldhealthorg.shinyapps.io/glass-dashboard/` (an interactive app, so the export steps are not scripted here).

## guidelines: PDFs

| File | URL | Version | Licence |
|---|---|---|---|
| `who-aware-antibiotic-book-2022.pdf` | `https://iris.who.int/server/api/core/bitstreams/61517f8b-3a34-413c-ae36-67a059ebe485/content` (landing page `https://www.who.int/publications/i/item/9789240062382`) | First edition, 9 December 2022, 697 pages | CC BY-NC-SA 3.0 IGO |
| `icmr-treatment-guidelines-2019.pdf` | `https://www.icmr.gov.in/icmrobject/custom_data/pdf/resource-guidelines/Treatment_Guidelines_2019_Final.pdf` | 2nd edition, 2019, 206 pages | "© Indian Council of Medical Research 2019 All rights reserved". Use for coursework; do not redistribute. |
| `icmr-carbapenem-resistant-gram-negative-2022.pdf` | `https://www.icmr.gov.in/icmrobject/custom_data/pdf/resource-guidelines/Diagnosis_and_management_of_CROs.pdf` | March 2022, 24 pages | ICMR; no licence statement in the file. Use for coursework; do not redistribute. |

How: automatic.

Differs from the brief: the ICMR page `https://www.icmr.gov.in/guidelines` lists a "2022" edition of the treatment guidelines at `.../treatment_amr_2022.pdf`. That file is a **one-page QR-code poster** ("Please scan above QR Code to get the link"), not the guidelines. The 2022 edition exists only as a web application at `https://amrtg.icmr.org.in` (the carbapenem-resistant section is at `https://amrtg.icmr.org.in/cro-recommendations.html`). It was not scraped. The 2019 PDF is the newest full edition ICMR publishes as a PDF, so it is used. Using the 2022 web edition would need a separate decision.

## taxonomy: NCBI Taxonomy

| | |
|---|---|
| URLs | E-utilities `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=taxonomy` (name to ID) and `.../efetch.fcgi?db=taxonomy` (records) |
| Version | Live NCBI Taxonomy on 2026-11-17 |
| Licence | NCBI data are public domain; see `https://www.ncbi.nlm.nih.gov/home/about/policies/` |
| Files | `pathogens.json` |
| How | Automatic. The script checks that each name resolves to exactly the taxonomy ID in `docs/CONTRACTS.md` (573, 562, 470, 287, 1280) and stops otherwise. |

## pubmed: PubMed abstracts

| | |
|---|---|
| URLs | E-utilities `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed` and `.../efetch.fcgi?db=pubmed` |
| Version | Live PubMed on 2026-11-17 |
| Licence | Abstracts remain the copyright of their publishers; PubMed record use is subject to the NLM terms at `https://www.nlm.nih.gov/databases/download/terms_and_conditions.html`. Keep the abstracts out of any public repository (D19). |
| Files | `pmids.csv` (`query,pmid`, 319 rows), `abstracts.jsonl` (`pmid,title,abstract,year,journal`, 319 lines) |
| How | Automatic. Ten queries (five pathogens times two themes, resistance mechanisms and treatment), 40 results each by relevance, 2015 to 2026, English, with an abstract. A PMID that several queries found is listed once, under the first query. |

319 abstracts, within the 300 to 500 target. To get more, raise `PUBMED_PER_QUERY` in the script and run with `--force`.

"""Download the raw source data for AMR-Navigator (task T02).

Usage (from the project root)::

    .venv/Scripts/python -m pipeline.download [--only aware,card,...] [--force]

One function per source writes into ``data/raw/<source>/``. Files that already
exist are skipped unless ``--force`` is given. ``data/raw/manifest.json`` lists
every file with its URL, retrieval date, size and SHA-256.

Rules followed here (see docs/ORCHESTRATION.md and docs/CONTRACTS.md):

* every request has a timeout and the generic User-Agent from ``pipeline.config``;
* no name, e-mail address or API key is ever sent;
* NCBI E-utilities are called at most three times per second;
* nothing is fabricated: a source that cannot be fetched raises an error and is
  reported, and the manual steps are written in ``data/SOURCES.md``.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import sys
import tarfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Iterator
from xml.etree import ElementTree as ET

import requests

from pipeline.config import DATA_RAW, HTTP_TIMEOUT_SECONDS, USER_AGENT

MANIFEST_NAME = "manifest.json"
MANIFEST_SCHEMA = 1

# NCBI allows 3 requests per second without an API key; stay below that.
NCBI_MIN_INTERVAL_SECONDS = 0.4
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

# The five pathogens in scope (docs/ARCHITECTURE.md section 2). The taxonomy ID is
# the NCBITaxon id used as the canonical pathogen id (docs/CONTRACTS.md section 2);
# the download checks that NCBI resolves each name to exactly this id.
PATHOGENS: list[tuple[str, int]] = [
    ("Klebsiella pneumoniae", 573),
    ("Escherichia coli", 562),
    ("Acinetobacter baumannii", 470),
    ("Pseudomonas aeruginosa", 287),
    ("Staphylococcus aureus", 1280),
]

# --- source URLs (each one was fetched and checked when this file was written) -----

AWARE_2025_URL = "https://iris.who.int/server/api/core/bitstreams/a8c53afc-fa43-4883-9a59-21a9e069f40c/content"
AWARE_2023_URL = "https://iris.who.int/server/api/core/bitstreams/abba5c2a-8457-431c-9695-16cb2317dd0e/content"
CARD_DATA_URL = "https://card.mcmaster.ca/download/0/broadstreet-v4.0.2.tar.bz2"
CARD_ONTOLOGY_URL = "https://card.mcmaster.ca/download/5/ontology-v4.0.2.tar.bz2"
AWARE_BOOK_URL = "https://iris.who.int/server/api/core/bitstreams/61517f8b-3a34-413c-ae36-67a059ebe485/content"
# The ICMR page lists a "2022" treatment_amr_2022.pdf, but that file is a one-page QR-code
# poster pointing at the web edition (https://amrtg.icmr.org.in), not the guidelines.
# The 2019 second edition is the latest edition published as a full PDF.
ICMR_TREATMENT_2019_URL = "https://www.icmr.gov.in/icmrobject/custom_data/pdf/resource-guidelines/Treatment_Guidelines_2019_Final.pdf"
ICMR_CRO_URL = "https://www.icmr.gov.in/icmrobject/custom_data/pdf/resource-guidelines/Diagnosis_and_management_of_CROs.pdf"
XMART_BASE = "https://xmart-api-public.who.int/DATA_"

# --- GLASS query ----------------------------------------------------------------------

# GLASS-AMR names the pathogens at this level. "Acinetobacter spp." is genus level
# and Pseudomonas aeruginosa is not a GLASS-AMR pathogen; it is still in the filter so
# that the download shows whether WHO ever published rows for it.
GLASS_PATHOGEN_NAMES = [
    "Klebsiella pneumoniae",
    "Escherichia coli",
    "Acinetobacter spp.",
    "Staphylococcus aureus",
    "Pseudomonas aeruginosa",
]
GLASS_INDICATORS = [
    "PERCENTAGERESISTANCE",
    "PERCENTAGERESISTANCELOWER",
    "PERCENTAGERESISTANCEUPPER",
    "RESISTANT",
    "INTERPRETABLEAST",
]
GLASS_COLUMNS = [
    "IND_CODE",
    "DIM_TIME",
    "DIM_GEO_CODE_ISO3",
    "DIM_GEO_CODE_M49",
    "DIM_GEO_CODE_TYPE",
    "DIM_1_CODE",
    "DIM_MEMBER_1_CODE",
    "DIM_2_CODE",
    "DIM_MEMBER_2_CODE",
    "DIM_3_CODE",
    "DIM_MEMBER_3_CODE",
    "DIM_4_CODE",
    "DIM_MEMBER_4_CODE",
    "DIM_5_CODE",
    "DIM_MEMBER_5_CODE",
    "VALUE_NUMERIC",
    "VALUE_NUMERIC_LOWER",
    "VALUE_NUMERIC_UPPER",
    "VALUE_LABEL",
    "VALUE_COMMENTS",
    "OBSERVATION_STATUS",
]
GLASS_PAGE_SIZE = 10000
COUNTRY_COLUMNS = ["CODE_ISO_3", "CODE_ISO_2", "CODE_ISO_NUMERIC", "CODE_WHO", "NAME_SHORT_EN"]

# --- PubMed queries --------------------------------------------------------------------

PUBMED_PER_QUERY = 40
PUBMED_DATE_FILTER = "2015:2026[dp] AND English[lang] AND hasabstract"
PUBMED_THEMES = {
    "resistance": (
        "(carbapenemase OR beta-lactamase OR \"resistance mechanism\" OR \"resistance gene\" "
        "OR efflux OR porin OR mecA OR NDM OR KPC OR OXA-48)"
    ),
    "treatment": (
        "(treatment OR therapy OR \"antibiotic therapy\" OR \"clinical outcome\" "
        "OR ceftazidime-avibactam OR colistin OR cefiderocol OR vancomycin)"
    ),
}


def pubmed_queries() -> list[str]:
    """The PubMed queries, one per pathogen and theme."""
    queries = []
    for name, _taxid in PATHOGENS:
        for theme in PUBMED_THEMES.values():
            queries.append(f'"{name}"[Title/Abstract] AND {theme}[Title/Abstract] AND {PUBMED_DATE_FILTER}')
    return queries


# =======================================================================================
# Helpers that do not touch the network (covered by tests/test_download.py)
# =======================================================================================


def utc_today() -> str:
    return dt.datetime.now(dt.timezone.utc).date().isoformat()


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    """SHA-256 of a file, read in chunks."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def should_skip(path: Path, force: bool = False) -> bool:
    """True when ``path`` is already on disk (and non-empty) and ``--force`` is off."""
    if force:
        return False
    return path.is_file() and path.stat().st_size > 0


def new_manifest() -> dict:
    return {"schema": MANIFEST_SCHEMA, "client": USER_AGENT, "files": {}}


def load_manifest(path: Path) -> dict:
    """Read the manifest, or return an empty one when it does not exist yet."""
    if not path.is_file():
        return new_manifest()
    with open(path, encoding="utf-8") as handle:
        manifest = json.load(handle)
    manifest.setdefault("schema", MANIFEST_SCHEMA)
    manifest.setdefault("files", {})
    return manifest


def save_manifest(manifest: dict, path: Path) -> None:
    """Write the manifest atomically with sorted keys."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
    tmp.replace(path)


def prune_manifest(manifest: dict, root: Path) -> list[str]:
    """Drop entries whose file is no longer on disk. Returns the keys removed."""
    gone = [key for key in manifest["files"] if not (root / key).is_file()]
    for key in gone:
        del manifest["files"][key]
    return gone


def manifest_key(path: Path, root: Path) -> str:
    """Manifest key: the path relative to ``data/raw`` with forward slashes."""
    return path.resolve().relative_to(root.resolve()).as_posix()


def build_entry(
    path: Path,
    url: str,
    source: str,
    retrieved: str | None = None,
    note: str | None = None,
) -> dict:
    """Manifest entry for one file: URL, retrieval date, size and SHA-256."""
    entry = {
        "source": source,
        "url": url,
        "retrieved": retrieved or utc_today(),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }
    if note:
        entry["note"] = note
    return entry


def record_file(
    manifest: dict,
    path: Path,
    url: str,
    source: str,
    root: Path = DATA_RAW,
    retrieved: str | None = None,
    note: str | None = None,
) -> None:
    manifest["files"][manifest_key(path, root)] = build_entry(path, url, source, retrieved, note)


def ensure_recorded(
    manifest: dict,
    path: Path,
    url: str,
    source: str,
    root: Path = DATA_RAW,
    note: str | None = None,
) -> bool:
    """Make sure a file that was skipped has a manifest entry. Returns True if one was added.

    A file with no entry was put there by hand or by an earlier run that did not finish;
    its retrieval date is then the file's modification date, which the note says.
    """
    key = manifest_key(path, root)
    if key in manifest["files"]:
        return False
    mtime = dt.datetime.fromtimestamp(path.stat().st_mtime, dt.timezone.utc).date().isoformat()
    text = "file already on disk; retrieval date is the file modification date"
    if note:
        text = f"{note}; {text}"
    record_file(manifest, path, url, source, root, retrieved=mtime, note=text)
    return True


def check_magic(path: Path, expected_prefix: bytes) -> None:
    """Raise if the file does not start with the expected bytes (e.g. an HTML error page)."""
    with open(path, "rb") as handle:
        head = handle.read(len(expected_prefix))
    if head != expected_prefix:
        raise ValueError(f"{path.name}: unexpected content, starts with {head!r}, expected {expected_prefix!r}")


class RateLimiter:
    """Block so that calls are at least ``min_interval`` seconds apart."""

    def __init__(self, min_interval: float, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.min_interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None

    def wait(self) -> None:
        now = self._clock()
        if self._last is not None:
            remaining = self.min_interval - (now - self._last)
            if remaining > 0:
                self._sleep(remaining)
                now = self._clock()
        self._last = now


def chunked(items: list, size: int) -> Iterator[list]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def safe_member_names(names: Iterable[str]) -> list[str]:
    """Return the archive member names, raising if any would escape the target folder."""
    checked = []
    for name in names:
        parts = Path(name.replace("\\", "/")).parts
        if name.startswith(("/", "\\")) or ".." in parts or (parts and ":" in parts[0]):
            raise ValueError(f"unsafe path in archive: {name!r}")
        checked.append(name)
    return checked


def odata_or(field_name: str, values: Iterable[str]) -> str:
    """OData filter ``(f eq 'a' or f eq 'b')``; single quotes in values are doubled."""
    terms = ["{} eq '{}'".format(field_name, v.replace("'", "''")) for v in values]
    return "(" + " or ".join(terms) + ")"


def glass_filter() -> str:
    """The server-side filter used for the GLASS download."""
    return " and ".join(
        [
            odata_or("DIM_MEMBER_2_CODE", GLASS_PATHOGEN_NAMES),
            "DIM_MEMBER_4_CODE eq 'Total'",
            odata_or("IND_CODE", GLASS_INDICATORS),
        ]
    )


def element_text(element: ET.Element | None) -> str:
    """All text inside an element (handles inline tags such as <i> or <sup>), whitespace-normalised."""
    if element is None:
        return ""
    return " ".join("".join(element.itertext()).split())


def parse_taxonomy_xml(xml_text: str) -> list[dict]:
    """Parse an NCBI efetch taxonomy response into plain dictionaries."""
    root = ET.fromstring(xml_text)
    taxa = []
    for taxon in root.findall("Taxon"):
        other: dict[str, list[str]] = {}
        other_names = taxon.find("OtherNames")
        if other_names is not None:
            for child in other_names:
                if child.tag == "Name":
                    label = element_text(child.find("ClassCDE")) or "Name"
                    value = element_text(child.find("DispName"))
                else:
                    label, value = child.tag, element_text(child)
                if value:
                    other.setdefault(label, []).append(value)
        taxa.append(
            {
                "taxid": int(taxon.findtext("TaxId")),
                "scientific_name": taxon.findtext("ScientificName"),
                "rank": taxon.findtext("Rank"),
                "division": taxon.findtext("Division"),
                "lineage": taxon.findtext("Lineage"),
                "other_names": other,
            }
        )
    return taxa


def parse_pubmed_xml(xml_text: str) -> list[dict]:
    """Parse an NCBI efetch pubmed response; records without an abstract are dropped."""
    root = ET.fromstring(xml_text)
    records = []
    for article in root.findall("PubmedArticle"):
        citation = article.find("MedlineCitation")
        pmid = element_text(citation.find("PMID"))
        art = citation.find("Article")
        title = element_text(art.find("ArticleTitle"))
        parts = []
        for node in art.findall("Abstract/AbstractText"):
            text = element_text(node)
            label = node.get("Label")
            if text:
                parts.append(f"{label}: {text}" if label else text)
        abstract = " ".join(parts)
        if not abstract:
            continue
        year = _pubmed_year(art)
        journal = element_text(art.find("Journal/Title"))
        records.append({"pmid": pmid, "title": title, "abstract": abstract, "year": year, "journal": journal})
    return records


def _pubmed_year(art: ET.Element) -> int | None:
    year = art.findtext("Journal/JournalIssue/PubDate/Year")
    if not year:
        medline_date = art.findtext("Journal/JournalIssue/PubDate/MedlineDate") or ""
        year = medline_date[:4]
    if not year:
        year = art.findtext("ArticleDate/Year")
    return int(year) if year and year.isdigit() else None


# =======================================================================================
# Download context and source functions
# =======================================================================================


@dataclass
class Context:
    """Everything a source function needs."""

    root: Path = DATA_RAW
    force: bool = False
    session: requests.Session = field(default_factory=requests.Session)
    manifest: dict = field(default_factory=new_manifest)
    ncbi: RateLimiter = field(default_factory=lambda: RateLimiter(NCBI_MIN_INTERVAL_SECONDS))
    log: Callable[[str], None] = print

    def __post_init__(self) -> None:
        self.session.headers["User-Agent"] = USER_AGENT

    # -- HTTP ----------------------------------------------------------------------

    def get(self, url: str, params: dict | None = None, stream: bool = False, retries: int = 3) -> requests.Response:
        """GET with the project User-Agent, a timeout and a few retries on transient errors."""
        last_error: Exception | None = None
        for attempt in range(retries):
            try:
                response = self.session.get(url, params=params, timeout=HTTP_TIMEOUT_SECONDS, stream=stream)
                if response.status_code in (429, 500, 502, 503, 504):
                    raise requests.HTTPError(f"{response.status_code} from {url}", response=response)
                response.raise_for_status()
                return response
            except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as error:
                last_error = error
                if attempt + 1 < retries:
                    time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"GET {url} failed after {retries} attempts: {last_error}") from last_error

    def ncbi_get(self, endpoint: str, params: dict) -> requests.Response:
        """GET an E-utilities endpoint, at most three requests per second, no API key."""
        self.ncbi.wait()
        return self.get(f"{EUTILS}/{endpoint}", params=params)

    def download(self, url: str, dest: Path, source: str, magic: bytes | None = None, note: str | None = None) -> bool:
        """Download ``url`` to ``dest`` unless it exists. Returns True if a download happened."""
        if should_skip(dest, self.force):
            ensure_recorded(self.manifest, dest, url, source, self.root, note)
            self.log(f"  skip   {manifest_key(dest, self.root)} (already present)")
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_suffix(dest.suffix + ".part")
        with self.get(url, stream=True) as response, open(part, "wb") as handle:
            for chunk in response.iter_content(chunk_size=1 << 20):
                handle.write(chunk)
        try:
            if magic:
                check_magic(part, magic)
        except ValueError:
            part.unlink(missing_ok=True)
            raise
        part.replace(dest)
        record_file(self.manifest, dest, url, source, self.root, note=note)
        self.log(f"  got    {manifest_key(dest, self.root)} ({dest.stat().st_size:,} bytes)")
        return True

    def register_generated(self, path: Path, url: str, source: str, note: str | None = None) -> None:
        record_file(self.manifest, path, url, source, self.root, note=note)
        self.log(f"  wrote  {manifest_key(path, self.root)} ({path.stat().st_size:,} bytes)")

    def skip_generated(self, path: Path, url: str, source: str, note: str | None = None) -> bool:
        """For files built by the script: skip (and keep the manifest complete) when present."""
        if should_skip(path, self.force):
            ensure_recorded(self.manifest, path, url, source, self.root, note)
            self.log(f"  skip   {manifest_key(path, self.root)} (already present)")
            return True
        return False


XLSX_MAGIC = b"PK\x03\x04"
PDF_MAGIC = b"%PDF"
BZ2_MAGIC = b"BZh"


def download_aware(ctx: Context) -> None:
    """WHO AWaRe classification workbooks (2025 is the latest; 2023 is kept because
    docs/CONTRACTS.md names ``who-aware-2023`` as an edge source)."""
    folder = ctx.root / "aware"
    ctx.download(AWARE_2025_URL, folder / "WHO-AWaRe-classification-2025.xlsx", "aware", XLSX_MAGIC,
                 "WHO AWaRe classification 2025 (report no. B09489)")
    ctx.download(AWARE_2023_URL, folder / "WHO-AWaRe-classification-2023.xlsx", "aware", XLSX_MAGIC,
                 "WHO AWaRe classification 2023 (WHO/MHP/HPS/EML/2023.04)")


def _extract_tar_bz2(archive: Path, target: Path) -> list[Path]:
    """Extract a tar.bz2 into ``target`` with path checks. Returns the extracted file paths."""
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:bz2") as tar:
        names = safe_member_names(member.name for member in tar.getmembers())
        tar.extractall(target, filter="data")
    return [target / name for name in names if (target / name).is_file()]


def download_card(ctx: Context) -> None:
    """CARD data archive (card.json, ARO index tables, FASTA) and the CARD ontology archive."""
    folder = ctx.root / "card"
    jobs = [
        (CARD_DATA_URL, folder / "card-data-v4.0.2.tar.bz2", folder, "card.json"),
        (CARD_ONTOLOGY_URL, folder / "card-ontology-v4.0.2.tar.bz2", folder / "ontology", "aro.obo"),
    ]
    for url, archive, target, marker in jobs:
        got = ctx.download(url, archive, "card", BZ2_MAGIC)
        marker_path = target / marker
        extracted_before = marker_path.is_file()
        if got or not extracted_before or ctx.force:
            files = _extract_tar_bz2(archive, target)
            for path in files:
                record_file(ctx.manifest, path, url, "card", ctx.root, note=f"extracted from {archive.name}")
            ctx.log(f"  unpack {archive.name}: {len(files)} files into {manifest_key(target, ctx.root)}/")
        else:
            for path in sorted(p for p in target.rglob("*") if p.is_file() and p != archive):
                ensure_recorded(ctx.manifest, path, url, "card", ctx.root, f"extracted from {archive.name}")
            ctx.log(f"  skip   {archive.name} contents (already extracted)")


def download_glass(ctx: Context) -> None:
    """WHO GLASS-AMR resistance rows for the pathogens in scope, from the WHO xMart public API.

    Only rows with the age group "Total" and five indicators are kept (resistance %, its
    confidence limits, number resistant, number with interpretable AST); see data/SOURCES.md.
    """
    folder = ctx.root / "glass"
    data_url = f"{XMART_BASE}/RELAY_GLASS_AMR_CTA"
    data_path = folder / "glass_amr_pathogens.csv"
    country_url = f"{XMART_BASE}/REF_COUNTRY"
    country_path = folder / "countries.csv"
    note = f"OData $filter: {glass_filter()}; columns: {','.join(GLASS_COLUMNS)}"

    if not ctx.skip_generated(data_path, data_url, "glass", note):
        folder.mkdir(parents=True, exist_ok=True)
        tmp = data_path.with_suffix(".csv.part")
        rows_written = 0
        skip = 0
        with open(tmp, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=GLASS_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            while True:
                response = ctx.get(
                    data_url,
                    params={
                        "$filter": glass_filter(),
                        "$select": ",".join(GLASS_COLUMNS),
                        "$orderby": "Sys_PK",
                        "$top": GLASS_PAGE_SIZE,
                        "$skip": skip,
                    },
                )
                rows = response.json()["value"]
                for row in rows:
                    writer.writerow(row)
                rows_written += len(rows)
                skip += len(rows)
                if len(rows) < GLASS_PAGE_SIZE:
                    break
                time.sleep(0.3)
        if rows_written == 0:
            tmp.unlink(missing_ok=True)
            raise RuntimeError("GLASS query returned no rows")
        tmp.replace(data_path)
        ctx.register_generated(data_path, data_url, "glass", note)

    if not ctx.skip_generated(country_path, country_url, "glass", "WHO country reference table (ISO codes and names)"):
        response = ctx.get(country_url, params={"$select": ",".join(COUNTRY_COLUMNS), "$top": 1000})
        rows = response.json()["value"]
        with open(country_path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=COUNTRY_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        ctx.register_generated(country_path, country_url, "glass", "WHO country reference table (ISO codes and names)")


def download_guidelines(ctx: Context) -> None:
    """WHO AWaRe antibiotic book and the two ICMR guideline PDFs."""
    folder = ctx.root / "guidelines"
    ctx.download(AWARE_BOOK_URL, folder / "who-aware-antibiotic-book-2022.pdf", "guidelines", PDF_MAGIC,
                 "The WHO AWaRe (Access, Watch, Reserve) antibiotic book, WHO, 9 December 2022")
    ctx.download(ICMR_TREATMENT_2019_URL, folder / "icmr-treatment-guidelines-2019.pdf", "guidelines", PDF_MAGIC,
                 "ICMR Treatment Guidelines for Antimicrobial Use in Common Syndromes, 2nd edition, 2019")
    ctx.download(ICMR_CRO_URL, folder / "icmr-carbapenem-resistant-gram-negative-2022.pdf", "guidelines", PDF_MAGIC,
                 "ICMR Guidance on Diagnosis and Management of Carbapenem Resistant Gram-negative Infections, March 2022")


def download_taxonomy(ctx: Context) -> None:
    """NCBI Taxonomy records for the five pathogens (one JSON file)."""
    path = ctx.root / "taxonomy" / "pathogens.json"
    url = f"{EUTILS}/efetch.fcgi?db=taxonomy"
    if ctx.skip_generated(path, url, "taxonomy"):
        return
    ids: list[int] = []
    for name, expected in PATHOGENS:
        result = ctx.ncbi_get(
            "esearch.fcgi",
            {"db": "taxonomy", "term": f"{name}[Scientific Name]", "retmode": "json"},
        ).json()["esearchresult"]
        found = [int(x) for x in result["idlist"]]
        if found != [expected]:
            raise RuntimeError(f"NCBI Taxonomy resolved {name!r} to {found}, expected [{expected}]")
        ids.append(expected)
    xml_text = ctx.ncbi_get("efetch.fcgi", {"db": "taxonomy", "id": ",".join(map(str, ids)), "retmode": "xml"}).text
    taxa = parse_taxonomy_xml(xml_text)
    by_id = {t["taxid"]: t for t in taxa}
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise RuntimeError(f"NCBI Taxonomy returned no record for {missing}")
    document = {
        "source": "NCBI Taxonomy via E-utilities (db=taxonomy)",
        "retrieved": utc_today(),
        "pathogens": [by_id[i] for i in ids],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(document, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    ctx.register_generated(path, url, "taxonomy", "esearch (name -> taxid) then efetch (xml), parsed to JSON")


def download_pubmed(ctx: Context) -> None:
    """About 300-500 PubMed abstracts on resistance mechanisms and treatment for the five pathogens."""
    folder = ctx.root / "pubmed"
    pmids_path = folder / "pmids.csv"
    abstracts_path = folder / "abstracts.jsonl"
    url = f"{EUTILS}/esearch.fcgi?db=pubmed"
    if should_skip(pmids_path, ctx.force) and should_skip(abstracts_path, ctx.force):
        ensure_recorded(ctx.manifest, pmids_path, url, "pubmed", ctx.root)
        ensure_recorded(ctx.manifest, abstracts_path, f"{EUTILS}/efetch.fcgi?db=pubmed", "pubmed", ctx.root)
        ctx.log("  skip   pubmed/ (already present)")
        return

    pairs: list[tuple[str, str]] = []  # (query, pmid); a PMID is kept under the first query that found it
    seen: set[str] = set()
    for query in pubmed_queries():
        result = ctx.ncbi_get(
            "esearch.fcgi",
            {"db": "pubmed", "term": query, "retmax": PUBMED_PER_QUERY, "sort": "relevance", "retmode": "json"},
        ).json()["esearchresult"]
        for pmid in result["idlist"]:
            if pmid not in seen:
                seen.add(pmid)
                pairs.append((query, pmid))
    if not pairs:
        raise RuntimeError("PubMed searches returned no PMIDs")

    records: dict[str, dict] = {}
    for batch in chunked([pmid for _q, pmid in pairs], 100):
        xml_text = ctx.ncbi_get("efetch.fcgi", {"db": "pubmed", "id": ",".join(batch), "retmode": "xml"}).text
        for record in parse_pubmed_xml(xml_text):
            records[record["pmid"]] = record

    folder.mkdir(parents=True, exist_ok=True)
    kept = [(q, p) for q, p in pairs if p in records]
    with open(pmids_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["query", "pmid"])
        writer.writerows(kept)
    with open(abstracts_path, "w", encoding="utf-8", newline="\n") as handle:
        for _query, pmid in kept:
            handle.write(json.dumps(records[pmid], ensure_ascii=False) + "\n")
    note = f"{len(kept)} PMIDs with abstracts from {len(pubmed_queries())} queries; each PMID listed once, under the first query that found it"
    ctx.register_generated(pmids_path, url, "pubmed", note)
    ctx.register_generated(abstracts_path, f"{EUTILS}/efetch.fcgi?db=pubmed", "pubmed", note)


SOURCES: dict[str, Callable[[Context], None]] = {
    "aware": download_aware,
    "card": download_card,
    "glass": download_glass,
    "guidelines": download_guidelines,
    "taxonomy": download_taxonomy,
    "pubmed": download_pubmed,
}


# =======================================================================================
# Command line
# =======================================================================================


def parse_only(value: str | None) -> list[str]:
    """Turn ``--only a,b`` into a validated list; no value means every source."""
    if not value:
        return list(SOURCES)
    names = [part.strip() for part in value.split(",") if part.strip()]
    unknown = [n for n in names if n not in SOURCES]
    if unknown:
        raise ValueError(f"unknown source(s): {', '.join(unknown)}; choose from {', '.join(SOURCES)}")
    return names


def run(only: list[str], force: bool, root: Path = DATA_RAW) -> int:
    """Run the chosen sources, write the manifest, return a process exit code."""
    manifest_path = root / MANIFEST_NAME
    ctx = Context(root=root, force=force, manifest=load_manifest(manifest_path))
    failures: list[str] = []
    for name in only:
        print(f"[{name}]")
        try:
            SOURCES[name](ctx)
        except Exception as error:  # report and carry on with the other sources
            failures.append(name)
            print(f"  FAILED {name}: {error}", file=sys.stderr)
    for key in prune_manifest(ctx.manifest, root):
        print(f"  manifest: dropped {key} (file no longer on disk)")
    ctx.manifest["updated"] = utc_today()
    save_manifest(ctx.manifest, manifest_path)
    print(f"manifest: {manifest_path} ({len(ctx.manifest['files'])} files)")
    if failures:
        print(f"failed sources: {', '.join(failures)} (see data/SOURCES.md for manual steps)", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pipeline.download", description=__doc__.splitlines()[0])
    parser.add_argument("--only", help=f"comma-separated sources to fetch ({', '.join(SOURCES)}); default: all")
    parser.add_argument("--force", action="store_true", help="download again even if the files exist")
    args = parser.parse_args(argv)
    try:
        only = parse_only(args.only)
    except ValueError as error:
        parser.error(str(error))
    return run(only, args.force)


if __name__ == "__main__":
    raise SystemExit(main())

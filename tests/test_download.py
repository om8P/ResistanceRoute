"""Tests for pipeline/download.py. None of them use the network."""

from __future__ import annotations

import hashlib
import json

import pytest

from pipeline import download as dl
from pipeline.config import USER_AGENT


# --- hashing, skipping, manifest ---------------------------------------------------------


def test_sha256_file_matches_hashlib(tmp_path):
    path = tmp_path / "a.bin"
    data = b"amr-navigator" * 1000
    path.write_bytes(data)
    assert dl.sha256_file(path, chunk_size=64) == hashlib.sha256(data).hexdigest()


def test_should_skip_logic(tmp_path):
    path = tmp_path / "f.txt"
    assert not dl.should_skip(path)  # missing
    path.write_bytes(b"")
    assert not dl.should_skip(path)  # empty files are treated as failed downloads
    path.write_bytes(b"x")
    assert dl.should_skip(path)
    assert not dl.should_skip(path, force=True)


def test_manifest_roundtrip_and_entry_fields(tmp_path):
    root = tmp_path / "raw"
    (root / "aware").mkdir(parents=True)
    file = root / "aware" / "x.xlsx"
    file.write_bytes(b"PK\x03\x04data")

    manifest = dl.new_manifest()
    dl.record_file(manifest, file, "https://example.org/x", "aware", root, retrieved="2026-01-02", note="n")
    path = root / dl.MANIFEST_NAME
    dl.save_manifest(manifest, path)

    loaded = dl.load_manifest(path)
    entry = loaded["files"]["aware/x.xlsx"]
    assert entry["url"] == "https://example.org/x"
    assert entry["retrieved"] == "2026-01-02"
    assert entry["size_bytes"] == file.stat().st_size
    assert entry["sha256"] == hashlib.sha256(file.read_bytes()).hexdigest()
    assert entry["source"] == "aware"
    assert entry["note"] == "n"
    assert loaded["client"] == USER_AGENT


def test_load_manifest_missing_file_gives_empty_manifest(tmp_path):
    manifest = dl.load_manifest(tmp_path / "nope.json")
    assert manifest["files"] == {}


def test_ensure_recorded_adds_missing_entry_only_once(tmp_path):
    root = tmp_path
    file = root / "pubmed" / "pmids.csv"
    file.parent.mkdir()
    file.write_text("query,pmid\n", encoding="utf-8")
    manifest = dl.new_manifest()
    assert dl.ensure_recorded(manifest, file, "u", "pubmed", root) is True
    assert "modification date" in manifest["files"]["pubmed/pmids.csv"]["note"]
    assert dl.ensure_recorded(manifest, file, "other", "pubmed", root) is False
    assert manifest["files"]["pubmed/pmids.csv"]["url"] == "u"


def test_prune_manifest_drops_entries_for_deleted_files(tmp_path):
    keep = tmp_path / "aware" / "keep.xlsx"
    keep.parent.mkdir()
    keep.write_bytes(b"PK\x03\x04")
    manifest = dl.new_manifest()
    dl.record_file(manifest, keep, "u", "aware", tmp_path)
    manifest["files"]["guidelines/gone.pdf"] = {"url": "u"}
    assert dl.prune_manifest(manifest, tmp_path) == ["guidelines/gone.pdf"]
    assert list(manifest["files"]) == ["aware/keep.xlsx"]


def test_check_magic(tmp_path):
    good = tmp_path / "a.pdf"
    good.write_bytes(b"%PDF-1.7 ...")
    dl.check_magic(good, dl.PDF_MAGIC)
    bad = tmp_path / "b.pdf"
    bad.write_bytes(b"<html>blocked</html>")
    with pytest.raises(ValueError):
        dl.check_magic(bad, dl.PDF_MAGIC)


# --- Context: skip without a request, never send identifying data ---------------------------


class ExplodingSession:
    """A session that fails the test if any request is attempted."""

    def __init__(self):
        self.headers = {}

    def get(self, *args, **kwargs):  # pragma: no cover - only runs on failure
        raise AssertionError("network call attempted")


def test_download_skips_existing_file_without_request(tmp_path):
    ctx = dl.Context(root=tmp_path, session=ExplodingSession(), log=lambda _m: None)
    dest = tmp_path / "aware" / "x.xlsx"
    dest.parent.mkdir()
    dest.write_bytes(b"PK\x03\x04existing")
    assert ctx.download("https://example.org/x", dest, "aware", dl.XLSX_MAGIC) is False
    assert dest.read_bytes() == b"PK\x03\x04existing"
    assert "aware/x.xlsx" in ctx.manifest["files"]  # skipped files still get a manifest entry


def test_context_sets_generic_user_agent_without_personal_details():
    ctx = dl.Context(session=ExplodingSession(), log=lambda _m: None)
    assert ctx.session.headers["User-Agent"] == "amr-navigator/0.1"
    assert "@" not in USER_AGENT
    assert dl.HTTP_TIMEOUT_SECONDS > 0


def test_download_rejects_wrong_content_type(tmp_path):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def iter_content(self, chunk_size):
            yield b"<html>challenge page</html>"

    class FakeSession(ExplodingSession):
        def get(self, url, **kwargs):
            assert kwargs["timeout"] > 0  # every request has a timeout

            class R(FakeResponse):
                status_code = 200

                def raise_for_status(self):
                    return None

            return R()

    ctx = dl.Context(root=tmp_path, session=FakeSession(), log=lambda _m: None)
    dest = tmp_path / "guidelines" / "x.pdf"
    with pytest.raises(ValueError):
        ctx.download("https://example.org/x.pdf", dest, "guidelines", dl.PDF_MAGIC)
    assert not dest.exists()
    assert not dest.with_suffix(".pdf.part").exists()


# --- rate limiting ------------------------------------------------------------------------


def test_rate_limiter_keeps_calls_apart():
    now = [0.0]
    sleeps: list[float] = []

    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    limiter = dl.RateLimiter(0.4, clock=lambda: now[0], sleep=sleep)
    limiter.wait()  # first call never waits
    limiter.wait()
    now[0] += 1.0  # a long gap: no wait needed
    limiter.wait()
    assert sleeps == [pytest.approx(0.4)]
    assert 1 / dl.NCBI_MIN_INTERVAL_SECONDS <= 3  # at most three requests per second


# --- small pure helpers -------------------------------------------------------------------


def test_chunked():
    assert list(dl.chunked([1, 2, 3, 4, 5], 2)) == [[1, 2], [3, 4], [5]]


def test_safe_member_names_rejects_traversal():
    assert dl.safe_member_names(["card.json", "ontology/aro.obo"]) == ["card.json", "ontology/aro.obo"]
    for bad in ("../evil", "a/../../evil", "/abs/path", "C:/win/path"):
        with pytest.raises(ValueError):
            dl.safe_member_names([bad])


def test_odata_filter_building():
    assert dl.odata_or("F", ["a", "b'c"]) == "(F eq 'a' or F eq 'b''c')"
    text = dl.glass_filter()
    assert "DIM_MEMBER_4_CODE eq 'Total'" in text
    assert "DIM_MEMBER_2_CODE eq 'Klebsiella pneumoniae'" in text
    assert "IND_CODE eq 'PERCENTAGERESISTANCE'" in text


def test_parse_only():
    assert dl.parse_only(None) == list(dl.SOURCES)
    assert dl.parse_only("aware, card") == ["aware", "card"]
    with pytest.raises(ValueError):
        dl.parse_only("aware,nonsense")


def test_pubmed_queries_cover_each_pathogen_and_theme():
    queries = dl.pubmed_queries()
    assert len(queries) == len(dl.PATHOGENS) * len(dl.PUBMED_THEMES)
    for name, _ in dl.PATHOGENS:
        assert sum(name in q for q in queries) == len(dl.PUBMED_THEMES)


# --- parsers ------------------------------------------------------------------------------

TAXONOMY_XML = """<?xml version="1.0"?>
<TaxaSet><Taxon>
  <TaxId>573</TaxId><ScientificName>Klebsiella pneumoniae</ScientificName>
  <OtherNames>
    <Synonym>Bacillus pneumoniae</Synonym>
    <GenbankSynonym>Klebsiella pneumoniae</GenbankSynonym>
    <Name><ClassCDE>authority</ClassCDE><DispName>Klebsiella pneumoniae (Schroeter 1886)</DispName></Name>
  </OtherNames>
  <Rank>species</Rank><Division>Bacteria</Division>
  <Lineage>cellular organisms; Bacteria</Lineage>
</Taxon></TaxaSet>"""

PUBMED_XML = """<?xml version="1.0"?>
<PubmedArticleSet>
<PubmedArticle><MedlineCitation><PMID Version="1">111</PMID><Article>
  <Journal><JournalIssue><PubDate><Year>2022</Year></PubDate></JournalIssue><Title>J Test</Title></Journal>
  <ArticleTitle>NDM in <i>K. pneumoniae</i></ArticleTitle>
  <Abstract><AbstractText Label="BACKGROUND">Carbapenem resistance.</AbstractText>
  <AbstractText Label="RESULTS">NDM-1 was common.</AbstractText></Abstract>
</Article></MedlineCitation></PubmedArticle>
<PubmedArticle><MedlineCitation><PMID Version="1">222</PMID><Article>
  <Journal><JournalIssue><PubDate><MedlineDate>2019 Jan-Feb</MedlineDate></PubDate></JournalIssue><Title>J Two</Title></Journal>
  <ArticleTitle>No abstract here</ArticleTitle>
</Article></MedlineCitation></PubmedArticle>
</PubmedArticleSet>"""


def test_parse_taxonomy_xml():
    (taxon,) = dl.parse_taxonomy_xml(TAXONOMY_XML)
    assert taxon["taxid"] == 573
    assert taxon["scientific_name"] == "Klebsiella pneumoniae"
    assert taxon["rank"] == "species"
    assert taxon["other_names"]["Synonym"] == ["Bacillus pneumoniae"]
    assert taxon["other_names"]["authority"] == ["Klebsiella pneumoniae (Schroeter 1886)"]


def test_parse_pubmed_xml_drops_records_without_abstract():
    records = dl.parse_pubmed_xml(PUBMED_XML)
    assert [r["pmid"] for r in records] == ["111"]
    record = records[0]
    assert record["title"] == "NDM in K. pneumoniae"
    assert record["abstract"] == "BACKGROUND: Carbapenem resistance. RESULTS: NDM-1 was common."
    assert record["year"] == 2022
    assert record["journal"] == "J Test"
    json.dumps(record)  # serialisable as one JSONL line


def test_pubmed_year_from_medline_date():
    import xml.etree.ElementTree as ET

    art = ET.fromstring(
        "<Article><Journal><JournalIssue><PubDate><MedlineDate>2019 Jan-Feb</MedlineDate></PubDate>"
        "</JournalIssue></Journal></Article>"
    )
    assert dl._pubmed_year(art) == 2019

"""Tests for pipeline.validate: node and edge validation, CSV helpers, CLI."""

from __future__ import annotations

import subprocess
import sys

import pytest

from pipeline.config import ROOT
from pipeline.models import EDGE_COLUMNS
from pipeline.validate import (
    join_multi,
    main,
    read_csv_rows,
    split_multi,
    validate_directory,
    validate_edges,
    validate_nodes,
    write_csv_rows,
)

# ---------------------------------------------------------------------------
# Fixture data
# ---------------------------------------------------------------------------

PATHOGEN = {"id": "NCBITaxon:573", "name": "Klebsiella pneumoniae", "gram_stain": "negative", "synonyms": ["K. pneumoniae", "Kleb, sp."]}
MECHANISM = {"id": "ARO:3000059", "name": "KPC beta-lactamase", "type": "carbapenemase", "ambler_class": "A"}
DRUG = {"id": "J01DH02", "name": "meropenem", "aware_group": "Watch", "synonyms": []}
DRUG_CLASS = {"id": "carbapenem", "name": "Carbapenems"}

KNOWN = {
    "Pathogen": {"NCBITaxon:573"},
    "Mechanism": {"ARO:3000059"},
    "Drug": {"J01DH02"},
    "DrugClass": {"carbapenem"},
}


def edge(**overrides):
    row = {
        "start_id": "NCBITaxon:573",
        "start_label": "Pathogen",
        "end_id": "ARO:3000059",
        "end_label": "Mechanism",
        "source_id": "curated-seed",
        "method": "curated",
        "confidence": "1.0",
        "evidence_passage_id": "",
    }
    row.update(overrides)
    return row


# ---------------------------------------------------------------------------
# validate_nodes
# ---------------------------------------------------------------------------


def test_validate_nodes_accepts_valid_rows():
    report = validate_nodes("Drug", [DRUG, {"id": "J01XA01", "name": "vancomycin", "aware_group": "Watch"}])
    assert report.ok and report.n_accepted == 2 and report.n_rejected == 0
    assert report.accepted[0]["id"] == "J01DH02"
    assert report.summary() == "nodes Drug: 2 accepted, 0 rejected"


def test_validate_nodes_rejects_duplicate_ids_keeping_the_first():
    first = {**DRUG, "name": "first"}
    second = {**DRUG, "name": "second"}
    report = validate_nodes("Drug", [first, {"id": "J01XA01", "name": "vancomycin"}, second])
    assert [r["name"] for r in report.accepted] == ["first", "vancomycin"]
    assert report.n_rejected == 1
    rej = report.rejected[0]
    assert rej.row_number == 3
    assert "duplicate id 'J01DH02'" in rej.reasons[0]


def test_validate_nodes_reports_reasons_for_bad_rows():
    rows = [
        {"id": "meropenem", "name": "meropenem"},  # bad id
        {"id": "J01DH02"},  # missing name
        {"id": "J01DH02", "name": "x", "aware_group": "Nope"},
        {"id": "J01DH02", "name": "x", "colour": "red"},
    ]
    report = validate_nodes("Drug", rows)
    assert report.n_accepted == 0 and report.n_rejected == 4
    assert "not a valid Drug id" in report.rejected[0].reasons[0]
    assert report.rejected[1].reasons[0].startswith("name:")
    assert report.rejected[2].reasons[0].startswith("aware_group:")
    assert report.rejected[3].reasons[0].startswith("colour:")
    assert report.reason_counts()


def test_validate_nodes_unknown_label_raises():
    with pytest.raises(ValueError, match="unknown node label"):
        validate_nodes("Banana", [])


def test_validate_nodes_does_not_mutate_input():
    row = dict(DRUG, synonyms="a|b")
    validate_nodes("Drug", [row])
    assert row["synonyms"] == "a|b"


# ---------------------------------------------------------------------------
# validate_edges
# ---------------------------------------------------------------------------


def test_validate_edges_accepts_valid_rows():
    report = validate_edges("HAS_MECHANISM", [edge()], KNOWN)
    assert report.ok and report.n_accepted == 1
    assert report.accepted[0]["confidence"] == 1.0


def test_validate_edges_unknown_rel_type_raises():
    with pytest.raises(ValueError, match="unknown relationship type"):
        validate_edges("LIKES", [], KNOWN)


def test_dangling_edge_start_and_end():
    report = validate_edges(
        "HAS_MECHANISM",
        [edge(start_id="NCBITaxon:9999"), edge(end_id="ARO:3999999"), edge(start_id="NCBITaxon:8", end_id="ARO:3999998")],
        KNOWN,
    )
    assert report.n_accepted == 0
    assert "start node Pathogen 'NCBITaxon:9999' not found" in report.rejected[0].reasons
    assert "end node Mechanism 'ARO:3999999' not found" in report.rejected[1].reasons
    assert len(report.rejected[2].reasons) == 2


def test_known_ids_may_be_a_flat_collection_or_none():
    flat = {"NCBITaxon:573", "ARO:3000059"}
    assert validate_edges("HAS_MECHANISM", [edge()], flat).ok
    assert not validate_edges("HAS_MECHANISM", [edge(end_id="ARO:3999999")], flat).ok
    assert validate_edges("HAS_MECHANISM", [edge(end_id="ARO:3999999")], None).ok


def test_known_ids_mapping_is_checked_per_label():
    # the id exists, but under a different label
    wrong_label = {"Pathogen": {"NCBITaxon:573"}, "Mechanism": set()}
    report = validate_edges("HAS_MECHANISM", [edge()], wrong_label)
    assert report.n_rejected == 1 and "end node Mechanism" in report.rejected[0].reasons[0]


def test_wrong_label_pair_for_relationship_type():
    row = edge(
        start_id="J01DH02", start_label="Drug", end_id="NCBITaxon:573", end_label="Pathogen"
    )
    report = validate_edges("HAS_MECHANISM", [row], KNOWN)
    assert report.n_rejected == 1
    reason = report.rejected[0].reasons[0]
    assert "Drug->Pathogen is not allowed for HAS_MECHANISM" in reason
    assert "Pathogen->Mechanism" in reason


def test_multi_label_relationship_allows_every_listed_pair():
    rows = [
        edge(start_id="who-aware-book-2022:sepsis:1", start_label="Passage", end_id="J01DH02", end_label="Drug"),
        edge(start_id="who-aware-book-2022:sepsis:1", start_label="Passage", end_id="carbapenem", end_label="DrugClass"),
        edge(start_id="who-aware-book-2022:sepsis:1", start_label="Passage", end_id="NCBITaxon:573", end_label="Pathogen"),
        edge(start_id="who-aware-book-2022:sepsis:1", start_label="Passage", end_id="ARO:3000059", end_label="Mechanism"),
    ]
    known = {**KNOWN, "Passage": {"who-aware-book-2022:sepsis:1"}}
    report = validate_edges("MENTIONS", [{**r, "method": "rule", "confidence": "0.9"} for r in rows], known)
    assert report.ok and report.n_accepted == 4


def test_class_level_surveillance_uses_about_class():
    stat_id = "GLASS:KEN:2021:NCBITaxon:573:carbapenem"
    row = edge(start_id=stat_id, start_label="SurveillanceStat", end_id="carbapenem", end_label="DrugClass", source_id="glass")
    known = {**KNOWN, "SurveillanceStat": {stat_id}}
    assert validate_edges("ABOUT_CLASS", [row], known).ok
    # the same pair is not allowed for ABOUT_DRUG, and a Drug end is not allowed for ABOUT_CLASS
    assert "not allowed for ABOUT_DRUG" in validate_edges("ABOUT_DRUG", [row], known).rejected[0].reasons[0]
    drug_row = {**row, "end_id": "J01DH02", "end_label": "Drug"}
    assert "not allowed for ABOUT_CLASS" in validate_edges("ABOUT_CLASS", [drug_row], known).rejected[0].reasons[0]


@pytest.mark.parametrize("missing", ["source_id", "method"])
def test_missing_provenance_rejected(missing):
    row = edge()
    row[missing] = ""
    report = validate_edges("HAS_MECHANISM", [row], KNOWN)
    assert report.n_rejected == 1
    assert report.rejected[0].reasons[0].startswith(f"{missing}:")
    row2 = edge()
    del row2[missing]
    assert validate_edges("HAS_MECHANISM", [row2], KNOWN).n_rejected == 1


def test_rule_edge_without_confidence_rejected():
    report = validate_edges("HAS_MECHANISM", [edge(method="rule", confidence="")], KNOWN)
    assert "confidence is required" in report.rejected[0].reasons[0]


def test_bad_endpoint_ids_and_labels_rejected():
    report = validate_edges(
        "HAS_MECHANISM",
        [edge(start_id="573"), edge(start_label="Banana")],
        KNOWN,
    )
    assert report.n_rejected == 2
    assert "not a valid Pathogen id" in report.rejected[0].reasons[0]
    assert "unknown label" in report.rejected[1].reasons[0]


def test_duplicate_edges_rejected_keeping_the_first():
    report = validate_edges("HAS_MECHANISM", [edge(), edge(source_id="card")], KNOWN)
    assert report.n_accepted == 1 and report.accepted[0]["source_id"] == "curated-seed"
    assert "duplicate edge" in report.rejected[0].reasons[0]


def test_one_bad_row_does_not_hide_good_rows():
    report = validate_edges("HAS_MECHANISM", [edge(), edge(method="bogus"), edge(end_id="ARO:3000060")], {**KNOWN, "Mechanism": {"ARO:3000059", "ARO:3000060"}})
    assert report.n_accepted == 2 and report.n_rejected == 1 and report.rejected[0].row_number == 2


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------


def test_split_and_join_multi():
    assert split_multi("a|b| c ") == ["a", "b", "c"]
    assert split_multi("") == [] and split_multi(None) == []
    assert join_multi(["a", "b"]) == "a|b"


def test_csv_round_trip_through_validation(tmp_path):
    original = [
        {**PATHOGEN},
        {"id": "NCBITaxon:562", "name": 'Escherichia "coli"', "gram_stain": "negative", "synonyms": ["E. coli", "Bact, coli"]},
        {"id": "NCBITaxon:1280", "name": "Staphylococcus aureus", "gram_stain": None, "synonyms": []},
    ]
    path = tmp_path / "nodes_Pathogen.csv"
    write_csv_rows(path, original, ["id", "name", "gram_stain", "synonyms"])

    text = path.read_text(encoding="utf-8")
    assert text.splitlines()[0] == "id,name,gram_stain,synonyms"
    assert '"Kleb, sp."' not in text  # joined by '|' first, then quoted because of the comma
    assert "K. pneumoniae|" in text

    raw = read_csv_rows(path)
    assert raw[0]["synonyms"] == "K. pneumoniae|Kleb, sp."
    assert raw[2]["gram_stain"] == ""

    report = validate_nodes("Pathogen", raw)
    assert report.ok
    assert report.accepted[0]["synonyms"] == ["K. pneumoniae", "Kleb, sp."]
    assert report.accepted[1]["name"] == 'Escherichia "coli"'
    assert "gram_stain" not in report.accepted[2]

    # writing the accepted rows and reading them again gives the same rows
    again = tmp_path / "again.csv"
    write_csv_rows(again, report.accepted)
    assert validate_nodes("Pathogen", read_csv_rows(again)).accepted == report.accepted


def test_write_csv_rows_formats_booleans_and_none(tmp_path):
    path = tmp_path / "x.csv"
    write_csv_rows(path, [{"a": True, "b": False, "c": None, "d": 1.5}])
    assert read_csv_rows(path) == [{"a": "true", "b": "false", "c": "", "d": "1.5"}]


def test_read_csv_rows_handles_bom_and_unicode(tmp_path):
    path = tmp_path / "bom.csv"
    path.write_bytes("﻿id,name\nx,β-lactam\n".encode("utf-8"))
    assert read_csv_rows(path) == [{"id": "x", "name": "β-lactam"}]


def test_read_csv_rows_rejects_ragged_and_empty_files(tmp_path):
    ragged = tmp_path / "ragged.csv"
    ragged.write_text("a,b\n1,2,3\n", encoding="utf-8")
    with pytest.raises(ValueError, match="more cells"):
        read_csv_rows(ragged)
    empty = tmp_path / "empty.csv"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="no header"):
        read_csv_rows(empty)


# ---------------------------------------------------------------------------
# Directory validation and CLI
# ---------------------------------------------------------------------------


def write_fixture_dir(directory, *, with_problems: bool):
    nodes = {
        "Pathogen": [PATHOGEN],
        "Mechanism": [MECHANISM],
        "Drug": [DRUG],
        "DrugClass": [DRUG_CLASS],
    }
    if with_problems:
        nodes["Drug"] = [DRUG, {**DRUG, "name": "duplicate"}, {"id": "bad id", "name": "x"}]
    for label, rows in nodes.items():
        write_csv_rows(directory / f"nodes_{label}.csv", rows)

    edges = {
        "HAS_MECHANISM": [edge()],
        "IN_CLASS": [edge(start_id="J01DH02", start_label="Drug", end_id="carbapenem", end_label="DrugClass")],
    }
    if with_problems:
        edges["HAS_MECHANISM"].append(edge(end_id="ARO:3999999"))  # dangling
        edges["IN_CLASS"].append(edge(start_id="J01DH02", start_label="Drug", end_id="carbapenem", end_label="DrugClass", source_id="", method="curated"))
    for rel_type, rows in edges.items():
        write_csv_rows(directory / f"edges_{rel_type}.csv", rows, list(EDGE_COLUMNS))


def test_validate_directory_clean(tmp_path):
    write_fixture_dir(tmp_path, with_problems=False)
    result = validate_directory(tmp_path)
    assert result.ok and result.n_files == 6
    assert sum(r.n_accepted for _, r in result.node_reports + result.edge_reports) == 6


def test_validate_directory_finds_problems(tmp_path):
    write_fixture_dir(tmp_path, with_problems=True)
    result = validate_directory(tmp_path)
    assert not result.ok
    by_name = {path.name: report for path, report in result.node_reports + result.edge_reports}
    assert by_name["nodes_Drug.csv"].n_rejected == 2
    assert by_name["edges_HAS_MECHANISM.csv"].n_rejected == 1
    assert by_name["edges_IN_CLASS.csv"].n_rejected == 1
    # skipping the endpoint check still finds the missing provenance but not the dangling edge
    relaxed = validate_directory(tmp_path, check_endpoints=False)
    assert {p.name: r for p, r in relaxed.edge_reports}["edges_HAS_MECHANISM.csv"].ok


def test_edges_to_rejected_nodes_count_as_dangling(tmp_path):
    write_csv_rows(tmp_path / "nodes_Drug.csv", [{"id": "J01DH02", "name": ""}])  # rejected node
    write_csv_rows(tmp_path / "nodes_DrugClass.csv", [DRUG_CLASS])
    write_csv_rows(
        tmp_path / "edges_IN_CLASS.csv",
        [edge(start_id="J01DH02", start_label="Drug", end_id="carbapenem", end_label="DrugClass")],
        list(EDGE_COLUMNS),
    )
    result = validate_directory(tmp_path)
    edge_report = result.edge_reports[0][1]
    assert edge_report.n_rejected == 1 and "not found" in edge_report.rejected[0].reasons[0]


def test_unknown_file_names_and_unreadable_files_are_problems(tmp_path):
    write_csv_rows(tmp_path / "nodes_Banana.csv", [{"id": "x"}])
    write_csv_rows(tmp_path / "edges_LIKES.csv", [{"start_id": "x"}])
    (tmp_path / "nodes_Drug.csv").write_text("", encoding="utf-8")
    result = validate_directory(tmp_path)
    messages = sorted(p.message for p in result.problems)
    assert len(messages) == 3 and not result.ok
    assert any("unknown node label 'Banana'" in m for m in messages)
    assert any("unknown relationship type 'LIKES'" in m for m in messages)


def test_cli_exit_zero_on_clean_directory(tmp_path, capsys):
    write_fixture_dir(tmp_path, with_problems=False)
    assert main([str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "OK   nodes_Drug.csv: 1 accepted, 0 rejected" in out
    assert "6 files, 6 rows accepted, 0 rows rejected, 0 file problems" in out


def test_cli_exit_one_and_prints_reasons(tmp_path, capsys):
    write_fixture_dir(tmp_path, with_problems=True)
    assert main([str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "FAIL nodes_Drug.csv: 1 accepted, 2 rejected" in out
    assert "duplicate id 'J01DH02'" in out
    assert "end node Mechanism 'ARO:3999999' not found" in out
    assert "source_id:" in out


def test_cli_max_examples_truncates(tmp_path, capsys):
    write_csv_rows(tmp_path / "nodes_Drug.csv", [{"id": f"bad{i}", "name": "x"} for i in range(5)])
    assert main([str(tmp_path), "--max-examples", "2"]) == 1
    out = capsys.readouterr().out
    assert out.count("       row ") == 2 and "and 3 more rejected rows" in out


def test_cli_missing_directory_and_empty_directory(tmp_path, capsys):
    assert main([str(tmp_path / "nope")]) == 2
    assert main([str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "is not a directory" in err and "no nodes_*.csv or edges_*.csv files" in err


def test_cli_runs_as_a_module(tmp_path):
    write_fixture_dir(tmp_path, with_problems=False)
    proc = subprocess.run(
        [sys.executable, "-m", "pipeline.validate", str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "6 files" in proc.stdout

    write_fixture_dir(tmp_path, with_problems=True)
    proc = subprocess.run(
        [sys.executable, "-m", "pipeline.validate", str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 1

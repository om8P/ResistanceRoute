"""Validate and load processed node and edge files into Neo4j (task T05).

Run::

    python -m pipeline.load [--clear]

Every ``nodes_<Label>.csv`` and ``edges_<TYPE>.csv`` in ``data/processed/`` is read,
validated with ``pipeline.validate``, and loaded with ``pipeline.graph_db``: nodes
first, then edges. Files from later tasks (``nodes_Passage.csv``, ``edges_MENTIONS.csv``,
``nodes_Recommendation.csv`` ...) are picked up automatically as long as they follow
CONTRACTS.md section 6. Accepted rows are loaded; rejected rows are listed with their
reasons in ``data/processed/load_report.json``, and the exit status is 1 when anything
was rejected or skipped.

``--clear`` deletes the whole graph first. Only use it on a database you own.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from neo4j import Driver

from pipeline.config import DATA_PROCESSED, NEO4J_URI
from pipeline.graph_db import apply_constraints, clear_graph, get_driver, merge_edges, merge_nodes, ping
from pipeline.models import EDGE_COLUMNS, EDGE_TYPES, NODE_MODELS
from pipeline.validate import ValidationReport, read_csv_rows, validate_edges, validate_nodes

REPORT_FILE = "load_report.json"
MAX_EXAMPLES = 5
_METHOD_PRIORITY = {"curated": 0, "rule": 1, "llm": 2}

# Milestone M2: carbapenem-resistant K. pneumoniae, one carbapenemase at a time.
CRKP_PATHOGEN = "NCBITaxon:573"
CRKP_MECHANISMS = ["ARO:3000059", "ARO:3000057", "ARO:3007721"]  # KPC, NDM, OXA-48-like

ACCEPTANCE_QUERY = """\
MATCH (p:Pathogen {id: $pathogen})-[:HAS_MECHANISM]->(m:Mechanism)
WHERE m.id IN $mechanisms
MATCH (d:Drug)-[:IN_CLASS]->(c:DrugClass)
WHERE NOT (p)-[:INTRINSICALLY_RESISTANT_TO]->(c)
  AND NOT (m)-[:CONFERS_RESISTANCE_TO]->(c)
  AND NOT (m)-[:INACTIVATES]->(d)
RETURN m.id AS mechanism_id, m.name AS mechanism,
       collect(d.name) AS drugs_not_excluded
ORDER BY m.id"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coerce_extras(row: dict[str, Any]) -> dict[str, Any]:
    """Edge extra columns arrive as strings; ``true``/``false`` become booleans (CONTRACTS section 3)."""
    result = {}
    for key, value in row.items():
        if key not in EDGE_COLUMNS and isinstance(value, str) and value.lower() in ("true", "false"):
            value = value.lower() == "true"
        result[key] = value
    return result


def dedupe_edges(rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], int]:
    """Keep one row per ``(start, end)`` pair, preferring ``curated`` over ``rule`` over ``llm``
    (DECISIONS.md D27). Among equal methods the higher confidence wins, then file order.
    Returns the kept rows in their original order and the number of rows dropped."""

    def rank(row: dict[str, str]) -> tuple[int, float]:
        try:
            confidence = float(row.get("confidence") or 0)
        except ValueError:
            confidence = 0.0
        return (_METHOD_PRIORITY.get((row.get("method") or "").strip(), 3), -confidence)

    best: dict[tuple[str, str, str, str], int] = {}
    for position, row in enumerate(rows):
        key = tuple((row.get(k) or "").strip() for k in ("start_label", "start_id", "end_label", "end_id"))
        if key not in best or rank(row) < rank(rows[best[key]]):
            best[key] = position
    keep = set(best.values())
    kept = [row for position, row in enumerate(rows) if position in keep]
    return kept, len(rows) - len(kept)


def _rejected_summary(report: ValidationReport) -> dict[str, Any]:
    return {
        "rejected": report.n_rejected,
        "reasons": report.reason_counts(),
        "examples": [
            {"row": rej.row_number, "reasons": rej.reasons, "values": rej.row}
            for rej in report.rejected[:MAX_EXAMPLES]
        ],
    }


def run_acceptance_query(driver: Driver) -> Optional[dict[str, list[str]]]:
    """Run the M2 query. Returns ``{mechanism name: [drug names]}``, or ``None`` when the
    carbapenem-resistant *K. pneumoniae* mechanisms are not in the database."""
    records, _, _ = driver.execute_query(
        ACCEPTANCE_QUERY, pathogen=CRKP_PATHOGEN, mechanisms=CRKP_MECHANISMS
    )
    if not records:
        return None
    return {r["mechanism"]: sorted(r["drugs_not_excluded"]) for r in records}


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_directory(
    directory: Path = DATA_PROCESSED,
    driver: Optional[Driver] = None,
    clear: bool = False,
    report_path: Optional[Path] = None,
    acceptance: bool = True,
) -> dict[str, Any]:
    """Validate and load every ``nodes_*.csv`` and ``edges_*.csv`` in ``directory``.

    ``driver`` defaults to a new one that is closed afterwards. The report is written to
    ``report_path``, which defaults to ``<directory>/load_report.json``. Returns the report.
    """
    directory = Path(directory)
    report_path = Path(report_path) if report_path else directory / REPORT_FILE
    own_driver = driver is None
    if own_driver:
        driver = get_driver()
    try:
        report: dict[str, Any] = {
            "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "database": NEO4J_URI,
            "directory": str(directory),
            "cleared": False,
            "files": {},
            "file_problems": [],
            "totals": {},
        }
        if clear:
            report["nodes_deleted_by_clear"] = clear_graph(driver, confirm=True)
            report["cleared"] = True
        apply_constraints(driver)

        known: dict[str, set[str]] = {}
        totals = {
            "nodes_loaded": 0,
            "nodes_created": 0,
            "edges_loaded": 0,
            "edges_created": 0,
            "rows_rejected": 0,
            "duplicate_edges_merged": 0,
            "missing_endpoints": 0,
            "file_problems": 0,
        }

        def read_or_report(path: Path) -> Optional[list[dict[str, str]]]:
            try:
                return read_csv_rows(path)
            except (ValueError, OSError) as exc:
                report["file_problems"].append(f"{path.name}: {exc}")
                totals["file_problems"] += 1
                return None

        for path in sorted(directory.glob("nodes_*.csv")):
            label = path.stem.removeprefix("nodes_")
            if label not in NODE_MODELS:
                report["file_problems"].append(f"{path.name}: unknown node label {label!r}")
                totals["file_problems"] += 1
                continue
            rows = read_or_report(path)
            if rows is None:
                continue
            validated = validate_nodes(label, rows)
            merged = merge_nodes(driver, label, validated.accepted)
            known.setdefault(label, set()).update(str(r["id"]) for r in validated.accepted)
            report["files"][path.name] = {
                "kind": "nodes",
                "label": label,
                "rows": len(rows),
                "accepted": validated.n_accepted,
                "nodes_created": merged["nodes_created"],
                **_rejected_summary(validated),
            }
            totals["nodes_loaded"] += validated.n_accepted
            totals["nodes_created"] += merged["nodes_created"]
            totals["rows_rejected"] += validated.n_rejected

        for path in sorted(directory.glob("edges_*.csv")):
            rel_type = path.stem.removeprefix("edges_")
            if rel_type not in EDGE_TYPES:
                report["file_problems"].append(f"{path.name}: unknown relationship type {rel_type!r}")
                totals["file_problems"] += 1
                continue
            rows = read_or_report(path)
            if rows is None:
                continue
            kept, n_duplicates = dedupe_edges(rows)
            validated = validate_edges(rel_type, kept, known)
            accepted = [_coerce_extras(row) for row in validated.accepted]
            merged = merge_edges(driver, rel_type, accepted)
            report["files"][path.name] = {
                "kind": "edges",
                "type": rel_type,
                "rows": len(rows),
                "duplicates_merged": n_duplicates,
                "accepted": validated.n_accepted,
                "relationships_created": merged["relationships_created"],
                "missing_endpoints": merged["missing_endpoints"],
                **_rejected_summary(validated),
            }
            totals["edges_loaded"] += merged["merged"]
            totals["edges_created"] += merged["relationships_created"]
            totals["rows_rejected"] += validated.n_rejected
            totals["duplicate_edges_merged"] += n_duplicates
            totals["missing_endpoints"] += merged["missing_endpoints"]

        report["totals"] = totals
        if acceptance:
            report["acceptance_crkp"] = run_acceptance_query(driver)
    finally:
        if own_driver:
            driver.close()

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def report_is_clean(report: dict[str, Any]) -> bool:
    totals = report["totals"]
    return not (totals["rows_rejected"] or totals["missing_endpoints"] or totals["file_problems"])


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.load",
        description="Validate nodes_*.csv and edges_*.csv in data/processed/ and load them into Neo4j.",
    )
    parser.add_argument("--clear", action="store_true", help="delete the whole graph before loading")
    parser.add_argument("--dir", type=Path, default=DATA_PROCESSED, help="directory with the CSV files")
    args = parser.parse_args(argv)

    if not args.dir.is_dir():
        print(f"error: {args.dir} is not a directory", file=sys.stderr)
        return 2
    if not ping():
        print(f"error: cannot reach Neo4j at {NEO4J_URI} (is `docker compose up -d` running?)", file=sys.stderr)
        return 2

    report = load_directory(args.dir, clear=args.clear)
    for name, entry in report["files"].items():
        extra = ""
        if entry["kind"] == "edges":
            extra = f", {entry['duplicates_merged']} duplicates merged, {entry['missing_endpoints']} missing endpoints"
        print(f"{name}: {entry['accepted']} loaded, {entry['rejected']} rejected{extra}")
    for problem in report["file_problems"]:
        print(f"PROBLEM {problem}")
    totals = report["totals"]
    print(
        f"\n{totals['nodes_loaded']} nodes and {totals['edges_loaded']} edges loaded, "
        f"{totals['rows_rejected']} rows rejected, {totals['file_problems']} file problems. "
        f"Report: {args.dir / REPORT_FILE}"
    )
    return 0 if report_is_clean(report) else 1


if __name__ == "__main__":
    sys.exit(main())

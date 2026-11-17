"""Validation of node and edge rows, and CSV helpers (task T01).

Library use::

    report = validate_nodes("Drug", rows)          # rows: list of dicts (e.g. CSV rows)
    report.accepted                                # normalised dicts, ready for merge_nodes
    report.rejected                                # RejectedRow(row_number, row, reasons)

    ids = {"Drug": {...}, "DrugClass": {...}}
    report = validate_edges("IN_CLASS", rows, ids)

Command line::

    python -m pipeline.validate data/processed

validates every ``nodes_<Label>.csv`` and ``edges_<TYPE>.csv`` in the directory,
prints a summary and exits with status 1 when anything is rejected.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union

from pydantic import ValidationError

from pipeline.models import EDGE_TYPES, Edge, NODE_MODELS

KnownIds = Union[Mapping[str, Collection[str]], Collection[str], None]

LIST_SEPARATOR = "|"


# ---------------------------------------------------------------------------
# CSV helpers (CONTRACTS.md section 3)
# ---------------------------------------------------------------------------


def split_multi(value: Optional[str]) -> list[str]:
    """Split a ``|``-separated cell into a list; blank cells give an empty list."""
    if value is None:
        return []
    return [part.strip() for part in value.split(LIST_SEPARATOR) if part.strip()]


def join_multi(values: Iterable[Any]) -> str:
    return LIST_SEPARATOR.join(str(v) for v in values)


def format_cell(value: Any) -> str:
    """Render a Python value as a CSV cell: lists joined by ``|``, booleans as true/false."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple, set, frozenset)):
        return join_multi(value)
    return str(value)


def read_csv_rows(path: Union[str, Path]) -> list[dict[str, str]]:
    """Read a UTF-8 CSV file with a header row into a list of dicts of strings.

    Raises ValueError for a missing header or a row with more cells than the header.
    """
    path = Path(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"{path.name}: file is empty or has no header row")
        rows: list[dict[str, str]] = []
        for row in reader:
            if None in row:
                raise ValueError(
                    f"{path.name}: line {reader.line_num} has more cells than the header"
                )
            rows.append({k: (v if v is not None else "") for k, v in row.items()})
    return rows


def write_csv_rows(
    path: Union[str, Path],
    rows: Sequence[Mapping[str, Any]],
    fieldnames: Optional[Sequence[str]] = None,
) -> None:
    """Write rows as UTF-8 CSV. Column order is ``fieldnames`` or first appearance."""
    if fieldnames is None:
        seen: dict[str, None] = {}
        for row in rows:
            for key in row:
                seen.setdefault(key, None)
        fieldnames = list(seen)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(fieldnames)
        for row in rows:
            writer.writerow([format_cell(row.get(name)) for name in fieldnames])


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


@dataclass
class RejectedRow:
    row_number: int  # 1-based position among the data rows (header excluded)
    row: dict[str, Any]
    reasons: list[str]


@dataclass
class ValidationReport:
    kind: str  # "nodes" or "edges"
    name: str  # node label or relationship type
    accepted: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[RejectedRow] = field(default_factory=list)

    @property
    def n_accepted(self) -> int:
        return len(self.accepted)

    @property
    def n_rejected(self) -> int:
        return len(self.rejected)

    @property
    def ok(self) -> bool:
        return not self.rejected

    def reason_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for rej in self.rejected:
            for reason in rej.reasons:
                counts[reason] = counts.get(reason, 0) + 1
        return counts

    def summary(self) -> str:
        return f"{self.kind} {self.name}: {self.n_accepted} accepted, {self.n_rejected} rejected"


def _format_errors(exc: ValidationError) -> list[str]:
    reasons = []
    for err in exc.errors():
        loc = ".".join(str(part) for part in err["loc"])
        msg = err["msg"].removeprefix("Value error, ")
        reasons.append(f"{loc}: {msg}" if loc else msg)
    return reasons


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


def validate_nodes(label: str, rows: Iterable[Mapping[str, Any]]) -> ValidationReport:
    """Validate rows for one node label.

    Rejects rows that fail the label's model and rows whose ``id`` already
    appeared earlier in ``rows`` (the first occurrence is kept).
    """
    if label not in NODE_MODELS:
        raise ValueError(f"unknown node label {label!r}; expected one of {sorted(NODE_MODELS)}")
    model = NODE_MODELS[label]
    report = ValidationReport("nodes", label)
    seen: set[str] = set()
    for number, row in enumerate(rows, start=1):
        row = dict(row)
        try:
            node = model.model_validate(row)
        except ValidationError as exc:
            report.rejected.append(RejectedRow(number, row, _format_errors(exc)))
            continue
        if node.id in seen:
            report.rejected.append(RejectedRow(number, row, [f"duplicate id {node.id!r}"]))
            continue
        seen.add(node.id)
        report.accepted.append(node.to_row())
    return report


# ---------------------------------------------------------------------------
# Edges
# ---------------------------------------------------------------------------


def _endpoint_known(known_ids: KnownIds, label: str, node_id: str) -> bool:
    if known_ids is None:
        return True
    if isinstance(known_ids, Mapping):
        return node_id in known_ids.get(label, ())
    return node_id in known_ids


def validate_edges(
    rel_type: str,
    rows: Iterable[Mapping[str, Any]],
    known_ids: KnownIds,
) -> ValidationReport:
    """Validate rows for one relationship type.

    Checks, in one pass and collecting every reason per row:

    * the row passes the ``Edge`` model (labels exist, IDs have the right format,
      ``source_id`` and ``method`` present, confidence in range);
    * ``(start_label, end_label)`` is allowed for ``rel_type`` in ``EDGE_TYPES``;
    * both endpoints are in ``known_ids``. ``known_ids`` is a mapping from label to
      a collection of IDs (preferred, since an ID string can in principle occur under
      two labels), a flat collection of IDs, or ``None`` to skip this check;
    * the ``(start, end)`` pair has not appeared earlier in ``rows``. ``merge_edges``
      merges on the pair, so a second row would silently overwrite the first.
    """
    if rel_type not in EDGE_TYPES:
        raise ValueError(
            f"unknown relationship type {rel_type!r}; expected one of {sorted(EDGE_TYPES)}"
        )
    allowed = EDGE_TYPES[rel_type]
    report = ValidationReport("edges", rel_type)
    seen: set[tuple[str, str, str, str]] = set()
    for number, row in enumerate(rows, start=1):
        row = dict(row)
        reasons: list[str] = []
        edge: Optional[Edge] = None
        try:
            edge = Edge.model_validate(row)
        except ValidationError as exc:
            reasons.extend(_format_errors(exc))

        start_label = str(row.get("start_label", "")).strip()
        end_label = str(row.get("end_label", "")).strip()
        start_id = str(row.get("start_id", "")).strip()
        end_id = str(row.get("end_id", "")).strip()

        if start_label in NODE_MODELS and end_label in NODE_MODELS:
            if (start_label, end_label) not in allowed:
                pairs = ", ".join(f"{a}->{b}" for a, b in sorted(allowed))
                reasons.append(
                    f"{start_label}->{end_label} is not allowed for {rel_type} (allowed: {pairs})"
                )
            if start_id and not _endpoint_known(known_ids, start_label, start_id):
                reasons.append(f"start node {start_label} {start_id!r} not found")
            if end_id and not _endpoint_known(known_ids, end_label, end_id):
                reasons.append(f"end node {end_label} {end_id!r} not found")

        key = (start_label, start_id, end_label, end_id)
        if not reasons and key in seen:
            reasons.append(f"duplicate edge {start_id!r} -> {end_id!r}")

        if reasons or edge is None:
            report.rejected.append(RejectedRow(number, row, reasons))
            continue
        seen.add(key)
        report.accepted.append(edge.to_row())
    return report


# ---------------------------------------------------------------------------
# Directory validation and CLI
# ---------------------------------------------------------------------------


@dataclass
class FileProblem:
    path: Path
    message: str


@dataclass
class DirectoryReport:
    node_reports: list[tuple[Path, ValidationReport]] = field(default_factory=list)
    edge_reports: list[tuple[Path, ValidationReport]] = field(default_factory=list)
    problems: list[FileProblem] = field(default_factory=list)

    @property
    def n_files(self) -> int:
        return len(self.node_reports) + len(self.edge_reports) + len(self.problems)

    @property
    def ok(self) -> bool:
        reports = [r for _, r in self.node_reports + self.edge_reports]
        return not self.problems and all(r.ok for r in reports)


def validate_directory(directory: Union[str, Path], check_endpoints: bool = True) -> DirectoryReport:
    """Validate every ``nodes_*.csv`` and ``edges_*.csv`` in ``directory``.

    Node files are validated first; the IDs of the accepted nodes (per label) are
    the ``known_ids`` for the edge files. A file with an unknown label or relationship
    type in its name, or one that cannot be parsed, is reported as a problem.
    """
    directory = Path(directory)
    result = DirectoryReport()
    known: dict[str, set[str]] = {}

    for path in sorted(directory.glob("nodes_*.csv")):
        label = path.stem.removeprefix("nodes_")
        if label not in NODE_MODELS:
            result.problems.append(FileProblem(path, f"unknown node label {label!r}"))
            continue
        try:
            rows = read_csv_rows(path)
        except (ValueError, OSError) as exc:
            result.problems.append(FileProblem(path, str(exc)))
            continue
        report = validate_nodes(label, rows)
        result.node_reports.append((path, report))
        known.setdefault(label, set()).update(str(r["id"]) for r in report.accepted)

    for path in sorted(directory.glob("edges_*.csv")):
        rel_type = path.stem.removeprefix("edges_")
        if rel_type not in EDGE_TYPES:
            result.problems.append(FileProblem(path, f"unknown relationship type {rel_type!r}"))
            continue
        try:
            rows = read_csv_rows(path)
        except (ValueError, OSError) as exc:
            result.problems.append(FileProblem(path, str(exc)))
            continue
        report = validate_edges(rel_type, rows, known if check_endpoints else None)
        result.edge_reports.append((path, report))

    return result


def _print_report(result: DirectoryReport, max_examples: int, out) -> None:
    for path, report in result.node_reports + result.edge_reports:
        status = "OK  " if report.ok else "FAIL"
        print(f"{status} {path.name}: {report.n_accepted} accepted, {report.n_rejected} rejected", file=out)
        for rej in report.rejected[:max_examples]:
            print(f"       row {rej.row_number}: {'; '.join(rej.reasons)}", file=out)
        hidden = report.n_rejected - max_examples
        if hidden > 0:
            print(f"       ... and {hidden} more rejected rows", file=out)
    for problem in result.problems:
        print(f"FAIL {problem.path.name}: {problem.message}", file=out)

    accepted = sum(r.n_accepted for _, r in result.node_reports + result.edge_reports)
    rejected = sum(r.n_rejected for _, r in result.node_reports + result.edge_reports)
    print(
        f"\n{result.n_files} files, {accepted} rows accepted, {rejected} rows rejected, "
        f"{len(result.problems)} file problems",
        file=out,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.validate",
        description="Validate nodes_*.csv and edges_*.csv files against the AMR-Navigator schema.",
    )
    parser.add_argument("directory", type=Path, help="directory holding nodes_*.csv and edges_*.csv")
    parser.add_argument(
        "--max-examples", type=int, default=5, help="rejected rows to show per file (default 5)"
    )
    parser.add_argument(
        "--skip-endpoints",
        action="store_true",
        help="do not check that edge endpoints exist in the node files",
    )
    args = parser.parse_args(argv)

    if not args.directory.is_dir():
        print(f"error: {args.directory} is not a directory", file=sys.stderr)
        return 2

    result = validate_directory(args.directory, check_endpoints=not args.skip_endpoints)
    if result.n_files == 0:
        print(f"error: no nodes_*.csv or edges_*.csv files in {args.directory}", file=sys.stderr)
        return 1
    _print_report(result, args.max_examples, sys.stdout)
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())

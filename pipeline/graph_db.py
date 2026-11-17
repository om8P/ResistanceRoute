"""Neo4j helpers for AMR-Navigator (task T01).

Labels and relationship types cannot be passed as Cypher parameters, so every
helper that builds a query string first checks the name against ``NODE_MODELS``
or ``EDGE_TYPES``. Row data always goes through ``$rows`` parameters.

Typical use::

    driver = get_driver()
    apply_constraints(driver)
    merge_nodes(driver, "Drug", report.accepted)      # rows from validate_nodes
    merge_edges(driver, "IN_CLASS", edge_report.accepted)
    driver.close()
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Optional

from neo4j import Driver, GraphDatabase

from pipeline.config import NEO4J_PASSWORD, NEO4J_URI, NEO4J_USER, SCHEMA_DIR
from pipeline.models import EDGE_TYPES, NODE_MODELS

CONSTRAINTS_FILE: Path = SCHEMA_DIR / "constraints.cypher"

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ENDPOINT_KEYS = ("start_id", "start_label", "end_id", "end_label")


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------


def get_driver(connection_timeout: float = 5.0) -> Driver:
    """Create a driver from the settings in ``pipeline.config``. The caller closes it."""
    return GraphDatabase.driver(
        NEO4J_URI,
        auth=(NEO4J_USER, NEO4J_PASSWORD),
        connection_timeout=connection_timeout,
    )


def ping(driver: Optional[Driver] = None) -> bool:
    """Return True when Neo4j accepts a connection with the configured credentials.

    Never raises: any failure (server down, wrong password, driver error) gives False.
    """
    own = driver is None
    try:
        drv = driver if driver is not None else get_driver(connection_timeout=2.0)
    except Exception:
        return False
    try:
        drv.verify_connectivity()
        return True
    except Exception:
        return False
    finally:
        if own:
            drv.close()


# ---------------------------------------------------------------------------
# Constraints
# ---------------------------------------------------------------------------


def read_statements(path: Path = CONSTRAINTS_FILE) -> list[str]:
    """Split a ``.cypher`` file into statements: ``//`` comment lines are dropped,
    and each statement ends at a line-ending ``;``."""
    statements: list[str] = []
    current: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        current.append(stripped)
        if stripped.endswith(";"):
            statements.append(" ".join(current).rstrip(";").strip())
            current = []
    if current:
        statements.append(" ".join(current))
    return statements


def apply_constraints(driver: Driver, path: Path = CONSTRAINTS_FILE) -> list[str]:
    """Run every statement in ``schema/constraints.cypher``. Idempotent.

    Returns the statements that were run.
    """
    statements = read_statements(path)
    for statement in statements:
        driver.execute_query(statement)
    return statements


def list_constraints(driver: Driver) -> list[dict[str, Any]]:
    """Return the uniqueness constraints now in the database as dicts with
    ``name``, ``labels`` and ``properties``."""
    records, _, _ = driver.execute_query(
        "SHOW CONSTRAINTS YIELD name, type, labelsOrTypes, properties "
        "WHERE type = 'UNIQUENESS' RETURN name, labelsOrTypes AS labels, properties"
    )
    return [record.data() for record in records]


def list_indexes(driver: Driver) -> list[dict[str, Any]]:
    """Return the range indexes (not backing a constraint) as dicts with
    ``name``, ``labels`` and ``properties``."""
    records, _, _ = driver.execute_query(
        "SHOW INDEXES YIELD name, type, labelsOrTypes, properties, owningConstraint "
        "WHERE type = 'RANGE' AND owningConstraint IS NULL "
        "RETURN name, labelsOrTypes AS labels, properties"
    )
    return [record.data() for record in records]


# ---------------------------------------------------------------------------
# Writing nodes and edges
# ---------------------------------------------------------------------------


def _check_label(label: str) -> str:
    if label not in NODE_MODELS or not _IDENTIFIER.fullmatch(label):
        raise ValueError(f"unknown node label {label!r}; expected one of {sorted(NODE_MODELS)}")
    return label


def _check_rel_type(rel_type: str) -> str:
    if rel_type not in EDGE_TYPES or not _IDENTIFIER.fullmatch(rel_type):
        raise ValueError(
            f"unknown relationship type {rel_type!r}; expected one of {sorted(EDGE_TYPES)}"
        )
    return rel_type


def _clean_props(props: Mapping[str, Any]) -> dict[str, Any]:
    """Drop ``None`` values (Neo4j cannot store null properties)."""
    return {k: v for k, v in props.items() if v is not None}


def _batches(items: list[Any], size: int) -> Iterable[list[Any]]:
    if size < 1:
        raise ValueError("batch_size must be at least 1")
    for start in range(0, len(items), size):
        yield items[start : start + size]


def merge_nodes(
    driver: Driver,
    label: str,
    rows: Iterable[Mapping[str, Any]],
    batch_size: int = 500,
) -> dict[str, int]:
    """``MERGE`` nodes of ``label`` on ``id`` and set the other columns as properties.

    ``rows`` are dicts with an ``id`` key, normally ``ValidationReport.accepted``.
    Properties that are ``None`` are skipped. Returns counts:
    ``rows``, ``nodes_created`` and ``properties_set``.
    """
    _check_label(label)
    payload: list[dict[str, Any]] = []
    for row in rows:
        if not row.get("id"):
            raise ValueError(f"{label} row without an id: {dict(row)!r}")
        props = _clean_props({k: v for k, v in row.items() if k != "id"})
        payload.append({"id": row["id"], "props": props})

    query = (
        f"UNWIND $rows AS row "
        f"MERGE (n:{label} {{id: row.id}}) "
        f"SET n += row.props"
    )
    totals = {"rows": len(payload), "nodes_created": 0, "properties_set": 0}
    for batch in _batches(payload, batch_size):
        _, summary, _ = driver.execute_query(query, rows=batch)
        totals["nodes_created"] += summary.counters.nodes_created
        totals["properties_set"] += summary.counters.properties_set
    return totals


def merge_edges(
    driver: Driver,
    rel_type: str,
    rows: Iterable[Mapping[str, Any]],
    batch_size: int = 500,
) -> dict[str, int]:
    """``MERGE`` relationships of ``rel_type`` between existing nodes.

    Each row has ``start_id``, ``start_label``, ``end_id``, ``end_label`` plus the
    provenance columns and any extra properties, which become relationship properties.
    Rows are grouped by ``(start_label, end_label)``; every pair is checked against
    ``EDGE_TYPES[rel_type]`` before any query is built, and a disallowed pair raises
    ``ValueError`` before anything is written.

    The relationship is merged on ``(start, type, end)``; a second row for the same
    pair updates the properties of the first. Rows whose endpoint nodes are not in the
    database are skipped, not created. Returns counts: ``rows``, ``merged``,
    ``missing_endpoints`` and ``relationships_created``.
    """
    _check_rel_type(rel_type)
    allowed = EDGE_TYPES[rel_type]

    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    n_rows = 0
    for row in rows:
        missing = [k for k in _ENDPOINT_KEYS if not row.get(k)]
        if missing:
            raise ValueError(f"{rel_type} row missing {missing}: {dict(row)!r}")
        pair = (row["start_label"], row["end_label"])
        _check_label(pair[0])
        _check_label(pair[1])
        if pair not in allowed:
            raise ValueError(f"{pair[0]}->{pair[1]} is not allowed for {rel_type}")
        props = _clean_props({k: v for k, v in row.items() if k not in _ENDPOINT_KEYS})
        groups[pair].append({"start_id": row["start_id"], "end_id": row["end_id"], "props": props})
        n_rows += 1

    totals = {"rows": n_rows, "merged": 0, "missing_endpoints": 0, "relationships_created": 0}
    for (start_label, end_label), payload in groups.items():
        query = (
            f"UNWIND $rows AS row "
            f"MATCH (a:{start_label} {{id: row.start_id}}) "
            f"MATCH (b:{end_label} {{id: row.end_id}}) "
            f"MERGE (a)-[r:{rel_type}]->(b) "
            f"SET r += row.props "
            f"RETURN count(r) AS merged"
        )
        for batch in _batches(payload, batch_size):
            records, summary, _ = driver.execute_query(query, rows=batch)
            merged = records[0]["merged"] if records else 0
            totals["merged"] += merged
            totals["missing_endpoints"] += len(batch) - merged
            totals["relationships_created"] += summary.counters.relationships_created
    return totals


# ---------------------------------------------------------------------------
# Clearing
# ---------------------------------------------------------------------------


def clear_graph(driver: Driver, confirm: bool = False, batch_size: int = 10_000) -> int:
    """Delete every node and relationship. Refuses to run unless ``confirm=True``.

    Constraints and indexes are kept. Returns the number of nodes deleted.
    """
    if confirm is not True:
        raise ValueError("clear_graph deletes the whole graph; call it with confirm=True")
    deleted = 0
    with driver.session() as session:
        while True:
            count = session.run(
                "MATCH (n) WITH n LIMIT $n DETACH DELETE n RETURN count(*) AS c", n=batch_size
            ).single()["c"]
            if count == 0:
                break
            deleted += count
    return deleted

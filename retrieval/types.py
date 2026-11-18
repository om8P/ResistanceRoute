"""Shared dataclasses for the retrieval modules (CONTRACTS section 7).

Owned by T12. T10 (graph search), T11 (text search) and T14 (fusion) import from here.
All classes are plain dataclasses with defaults, so ``ParsedQuery(question="x")`` works.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

INTENTS = (
    "alternatives",
    "why_restricted",
    "mechanism_lookup",
    "recommendation_lookup",
    "drug_profile",
    "surveillance",
    "decline",
    "unknown",
)


@dataclass
class ParsedQuery:
    """A question turned into an intent and canonical entities."""

    question: str = ""
    intent: str = "unknown"
    pathogen_ids: list[str] = field(default_factory=list)
    mechanism_ids: list[str] = field(default_factory=list)
    drug_ids: list[str] = field(default_factory=list)
    class_ids: list[str] = field(default_factory=list)
    class_families: list[str] = field(default_factory=list)
    country: str | None = None  # ISO 3 code
    year: int | None = None
    infection_site: str | None = None
    decline_reason: str | None = None
    mentions: list[Any] = field(default_factory=list)  # LinkedMention objects


@dataclass
class Answer:
    """One answer entity (usually a drug) returned by graph search."""

    id: str = ""
    label: str = ""
    name: str = ""
    group: str = ""  # for example the mechanism name; empty if not grouped
    aware_group: str = ""
    recommendation_ids: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    score: float = 0.0


@dataclass
class Path:
    """An ordered reasoning path from the question's entities to one answer.

    Each step is a dict with keys ``node_id``, ``node_label``, ``node_name``,
    ``rel_type`` and ``rel_props`` (the relationship leading to this node; its
    provenance is in ``rel_props``). ``answer_id`` names the answer it ends in.
    """

    steps: list[dict[str, Any]] = field(default_factory=list)
    answer_id: str = ""


@dataclass
class GraphResult:
    """The output of ``graph_search(parsed)``."""

    answers: list[Answer] = field(default_factory=list)
    paths: list[Path] = field(default_factory=list)
    entity_ids: list[str] = field(default_factory=list)
    cypher: list[str] = field(default_factory=list)
    empty_reason: str | None = None


@dataclass
class PassageHit:
    """One passage returned by text search."""

    passage_id: str = ""
    score: float = 0.0
    rank: int = 0
    text: str = ""
    source_doc: str = ""
    section: str = ""
    page: int | None = None

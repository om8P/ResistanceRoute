"""Typed models for the AMR-Navigator graph (task T01).

One Pydantic model per node label (ARCHITECTURE.md section 5.1), an ``Edge``
model with required provenance (CONTRACTS.md section 6), and the registries
``NODE_MODELS`` and ``EDGE_TYPES`` that every later task uses to check labels
and relationship types.

The models accept values the way they arrive from CSV files: blank cells count
as missing, and multi-valued cells use ``|`` as separator (CONTRACTS.md
section 3). Use ``Model.to_row()`` to get a plain dict ready for CSV writing or
for ``graph_db.merge_nodes``.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated, Any, ClassVar, Optional

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class AwareGroup(StrEnum):
    ACCESS = "Access"
    WATCH = "Watch"
    RESERVE = "Reserve"
    UNCLASSIFIED = "Unclassified"


class Method(StrEnum):
    CURATED = "curated"
    RULE = "rule"
    LLM = "llm"


class LineOfTherapy(StrEnum):
    FIRST = "first"
    SECOND = "second"
    ALTERNATIVE = "alternative"
    LAST_RESORT = "last-resort"


class RegimenType(StrEnum):
    SINGLE = "single"  # one drug
    COMBINATION = "combination"  # all drugs together, one unit
    ANY_OF = "any-of"  # alternatives, judged one by one


class MechanismType(StrEnum):
    CARBAPENEMASE = "carbapenemase"
    ESBL = "esbl"
    AMPC = "ampc"
    TARGET_MODIFICATION = "target-modification"
    EFFLUX = "efflux"
    PORIN_LOSS = "porin-loss"
    OTHER = "other"


class AmblerClass(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class GramStain(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"


# ---------------------------------------------------------------------------
# ID formats (CONTRACTS.md section 2)
# ---------------------------------------------------------------------------

_SLUG = r"[a-z0-9]+(?:-[a-z0-9]+)*"
_ATC = r"[A-Z][0-9]{2}[A-Z]{2}[0-9]{2}"
_DRUG_ID = rf"(?:{_ATC}|LOCAL:drug:{_SLUG})"
_PATHOGEN_ID = r"NCBITaxon:[0-9]+"
_GUIDELINE_ID = rf"{_SLUG}-[0-9]{{4}}"

ID_PATTERNS: dict[str, re.Pattern[str]] = {
    "Drug": re.compile(rf"{_DRUG_ID}"),
    "DrugClass": re.compile(_SLUG),
    "Pathogen": re.compile(_PATHOGEN_ID),
    "Mechanism": re.compile(rf"(?:ARO:[0-9]{{7}}|LOCAL:mech:{_SLUG})"),
    "Gene": re.compile(r"ARO:[0-9]{7}"),
    "Guideline": re.compile(_GUIDELINE_ID),
    "Recommendation": re.compile(rf"REC:{_GUIDELINE_ID}:[0-9]{{3}}"),
    "Passage": re.compile(rf"{_SLUG}:{_SLUG}:[0-9]+"),
    "SurveillanceStat": re.compile(
        rf"GLASS:[A-Z]{{3}}:[0-9]{{4}}:{_PATHOGEN_ID}:(?:{_DRUG_ID}|{_SLUG})"
    ),
}

ID_FORMAT_HELP: dict[str, str] = {
    "Drug": "ATC code such as J01DH02, or LOCAL:drug:<slug>",
    "DrugClass": "lower-case slug with hyphens, such as carbapenem",
    "Pathogen": "NCBITaxon:<taxid>, such as NCBITaxon:573",
    "Mechanism": "ARO:<7 digits>, such as ARO:3000059, or LOCAL:mech:<slug>",
    "Gene": "ARO:<7 digits>, such as ARO:3002312",
    "Guideline": "slug ending in a 4-digit year, such as who-aware-book-2022",
    "Recommendation": "REC:<guideline id>:<3 digits>, such as REC:who-aware-book-2022:014",
    "Passage": "<source doc id>:<section slug>:<number>, such as who-aware-book-2022:sepsis-adults:3",
    "SurveillanceStat": "GLASS:<ISO3>:<year>:<pathogen id>:<drug or class id>",
}

# Values allowed in Edge.source_id besides a Guideline id (CONTRACTS.md section 6).
DATASET_SOURCE_IDS: frozenset[str] = frozenset(
    {"card", "who-aware-2023", "who-aware-2025", "glass", "curated-seed", "pubmed"}
)


def check_id(label: str, value: Any) -> str:
    """Return ``value`` if it is a valid ID for ``label``; raise ValueError otherwise."""
    if label not in ID_PATTERNS:
        raise ValueError(f"unknown label {label!r}")
    if not isinstance(value, str) or not ID_PATTERNS[label].fullmatch(value):
        raise ValueError(
            f"{value!r} is not a valid {label} id; expected {ID_FORMAT_HELP[label]}"
        )
    return value


def is_valid_id(label: str, value: Any) -> bool:
    try:
        check_id(label, value)
    except ValueError:
        return False
    return True


# ---------------------------------------------------------------------------
# Helpers for CSV-style input
# ---------------------------------------------------------------------------


def _parse_list(value: Any) -> list[str]:
    """``None`` or blank -> []; ``"a|b"`` -> ["a", "b"]; lists are cleaned."""
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split("|") if part.strip()]
    if isinstance(value, (list, tuple, set, frozenset)):
        return [str(part).strip() for part in value if str(part).strip()]
    raise ValueError("expected a '|'-separated string or a list of strings")


PipeList = Annotated[list[str], BeforeValidator(_parse_list)]


def _drop_blank(data: Any) -> Any:
    """Treat blank string cells as missing so defaults and 'required' checks apply."""
    if isinstance(data, dict):
        return {k: v for k, v in data.items() if not (isinstance(v, str) and not v.strip())}
    return data


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @model_validator(mode="before")
    @classmethod
    def _blank_cells_are_missing(cls, data: Any) -> Any:
        return _drop_blank(data)

    def to_row(self) -> dict[str, Any]:
        """Plain dict with JSON-friendly values; unset optional fields are omitted."""
        return self.model_dump(mode="json", exclude_none=True)


# ---------------------------------------------------------------------------
# Node models (ARCHITECTURE.md section 5.1)
# ---------------------------------------------------------------------------


class _Node(_Base):
    LABEL: ClassVar[str]
    id: str

    @field_validator("id", check_fields=False)
    @classmethod
    def _check_id_format(cls, value: str) -> str:
        return check_id(cls.LABEL, value)

    def properties(self) -> dict[str, Any]:
        """The row without ``id``: what goes into the node's property map."""
        row = self.to_row()
        row.pop("id", None)
        return row


class Pathogen(_Node):
    LABEL: ClassVar[str] = "Pathogen"
    name: str = Field(min_length=1)
    gram_stain: Optional[GramStain] = None
    synonyms: PipeList = Field(default_factory=list)


class Mechanism(_Node):
    LABEL: ClassVar[str] = "Mechanism"
    name: str = Field(min_length=1)
    type: MechanismType
    ambler_class: Optional[AmblerClass] = None


class Gene(_Node):
    LABEL: ClassVar[str] = "Gene"
    name: str = Field(min_length=1)


class Drug(_Node):
    LABEL: ClassVar[str] = "Drug"
    name: str = Field(min_length=1)
    aware_group: AwareGroup = AwareGroup.UNCLASSIFIED
    synonyms: PipeList = Field(default_factory=list)


class DrugClass(_Node):
    LABEL: ClassVar[str] = "DrugClass"
    name: str = Field(min_length=1)
    # Broader group used to expand class-level questions, e.g. "carbapenem"
    # covers both carbapenem classes (DECISIONS.md D29). Optional slug.
    family: Optional[str] = Field(default=None, pattern=rf"^{_SLUG}$")


class Recommendation(_Node):
    LABEL: ClassVar[str] = "Recommendation"
    text: str = Field(min_length=1)
    infection_site: Optional[str] = None
    line_of_therapy: Optional[LineOfTherapy] = None
    patient_group: Optional[str] = None
    regimen_type: Optional[RegimenType] = None  # D33


class Guideline(_Node):
    LABEL: ClassVar[str] = "Guideline"
    title: str = Field(min_length=1)
    organisation: str = Field(min_length=1)
    year: int = Field(ge=1900, le=2100)
    version: Optional[str] = None


class SurveillanceStat(_Node):
    LABEL: ClassVar[str] = "SurveillanceStat"
    country: str = Field(pattern=r"^[A-Z]{3}$", description="ISO 3166-1 alpha-3")
    year: int = Field(ge=1900, le=2100)
    pct_resistant: float = Field(ge=0, le=100, description="percent, 0-100")
    n_tested: Optional[int] = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _id_matches_country_and_year(self) -> "SurveillanceStat":
        # id is GLASS:<ISO3>:<year>:...; the format was already checked on `id`.
        _, id_country, id_year, *_ = self.id.split(":")
        if id_country != self.country:
            raise ValueError(f"country {self.country!r} does not match id country {id_country!r}")
        if int(id_year) != self.year:
            raise ValueError(f"year {self.year} does not match id year {id_year}")
        return self


class Passage(_Node):
    LABEL: ClassVar[str] = "Passage"
    text: str = Field(min_length=1)
    source_doc: str = Field(min_length=1)
    section: str = Field(min_length=1)


NODE_MODELS: dict[str, type[_Node]] = {
    "Pathogen": Pathogen,
    "Mechanism": Mechanism,
    "Gene": Gene,
    "Drug": Drug,
    "DrugClass": DrugClass,
    "Recommendation": Recommendation,
    "Guideline": Guideline,
    "SurveillanceStat": SurveillanceStat,
    "Passage": Passage,
}

# ---------------------------------------------------------------------------
# Edges (ARCHITECTURE.md section 5.1, CONTRACTS.md section 6)
# ---------------------------------------------------------------------------

EDGE_TYPES: dict[str, frozenset[tuple[str, str]]] = {
    "HAS_MECHANISM": frozenset({("Pathogen", "Mechanism")}),
    "ENCODES": frozenset({("Gene", "Mechanism")}),
    "CONFERS_RESISTANCE_TO": frozenset({("Mechanism", "DrugClass")}),
    "INACTIVATES": frozenset({("Mechanism", "Drug")}),
    "INTRINSICALLY_RESISTANT_TO": frozenset({("Pathogen", "DrugClass")}),
    "IN_CLASS": frozenset({("Drug", "DrugClass")}),
    "FOR_PATHOGEN": frozenset({("Recommendation", "Pathogen")}),
    "FOR_MECHANISM": frozenset({("Recommendation", "Mechanism")}),
    "RECOMMENDS": frozenset({("Recommendation", "Drug")}),
    "FROM": frozenset({("Recommendation", "Guideline")}),
    "ABOUT_PATHOGEN": frozenset({("SurveillanceStat", "Pathogen")}),
    "ABOUT_DRUG": frozenset({("SurveillanceStat", "Drug")}),
    "ABOUT_CLASS": frozenset({("SurveillanceStat", "DrugClass")}),
    "MENTIONS": frozenset(
        {
            ("Passage", "Pathogen"),
            ("Passage", "Drug"),
            ("Passage", "DrugClass"),
            ("Passage", "Mechanism"),
        }
    ),
    "SUPPORTS": frozenset({("Passage", "Recommendation")}),
}

# Columns every edges_<TYPE>.csv starts with (CONTRACTS.md section 6).
EDGE_COLUMNS: tuple[str, ...] = (
    "start_id",
    "start_label",
    "end_id",
    "end_label",
    "source_id",
    "method",
    "confidence",
    "evidence_passage_id",
)


class Edge(BaseModel):
    """One relationship row. Extra columns are kept and become relationship properties.

    ``source_id`` and ``method`` are required. ``confidence`` defaults to 1.0 for
    curated edges and is required for ``rule`` and ``llm`` edges.
    """

    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)

    start_id: str
    start_label: str
    end_id: str
    end_label: str
    source_id: str
    method: Method
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    evidence_passage_id: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _blank_cells_are_missing(cls, data: Any) -> Any:
        return _drop_blank(data)

    @field_validator("start_label", "end_label")
    @classmethod
    def _known_label(cls, value: str) -> str:
        if value not in NODE_MODELS:
            raise ValueError(f"unknown label {value!r}; expected one of {sorted(NODE_MODELS)}")
        return value

    @field_validator("source_id")
    @classmethod
    def _source_id_format(cls, value: str) -> str:
        if value in DATASET_SOURCE_IDS or is_valid_id("Guideline", value):
            return value
        raise ValueError(
            f"{value!r} is neither a Guideline id nor one of {sorted(DATASET_SOURCE_IDS)}"
        )

    @field_validator("evidence_passage_id")
    @classmethod
    def _evidence_is_passage_id(cls, value: Optional[str]) -> Optional[str]:
        return None if value is None else check_id("Passage", value)

    @model_validator(mode="after")
    def _ids_and_confidence(self) -> "Edge":
        # Endpoint labels may have failed field validation; those errors are reported already.
        check_id(self.start_label, self.start_id)
        check_id(self.end_label, self.end_id)
        if self.confidence is None:
            if self.method is Method.CURATED:
                self.confidence = 1.0
            else:
                raise ValueError(f"confidence is required for method {self.method.value!r}")
        return self

    def to_row(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)

    def properties(self) -> dict[str, Any]:
        """Relationship properties: provenance plus any extra columns, without endpoints."""
        row = self.to_row()
        for key in ("start_id", "start_label", "end_id", "end_label"):
            row.pop(key, None)
        return row


# ---------------------------------------------------------------------------
# Recommendation extraction output (used by the extraction task, T13)
# ---------------------------------------------------------------------------


class RecommendationExtraction(_Base):
    """Structured output of recommendation extraction.

    Names are free text; linking them to IDs happens later (pipeline/link.py).
    """

    pathogen: str = Field(min_length=1)
    mechanism: Optional[str] = None
    drugs: PipeList = Field(min_length=1)
    infection_site: Optional[str] = None
    line_of_therapy: Optional[LineOfTherapy] = None
    patient_group: Optional[str] = None
    evidence_text: str = Field(min_length=1)
    passage_id: Optional[str] = None
    method: Method = Method.RULE
    confidence: Optional[float] = Field(default=None, ge=0, le=1)

    @field_validator("passage_id")
    @classmethod
    def _passage_id_format(cls, value: Optional[str]) -> Optional[str]:
        return None if value is None else check_id("Passage", value)


__all__ = [
    "AmblerClass",
    "AwareGroup",
    "DATASET_SOURCE_IDS",
    "Drug",
    "DrugClass",
    "Edge",
    "EDGE_COLUMNS",
    "EDGE_TYPES",
    "Gene",
    "GramStain",
    "Guideline",
    "ID_FORMAT_HELP",
    "ID_PATTERNS",
    "LineOfTherapy",
    "Mechanism",
    "MechanismType",
    "Method",
    "NODE_MODELS",
    "Passage",
    "Pathogen",
    "Recommendation",
    "RecommendationExtraction",
    "RegimenType",
    "SurveillanceStat",
    "check_id",
    "is_valid_id",
]

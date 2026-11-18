"""Build the core graph as processed CSV files (task T05).

Reads the seed data (``schema/scope.yaml``, ``schema/synonyms.csv``,
``data/curated/*.csv``) and the structured sources (AWaRe 2025, CARD, GLASS) and
writes ``nodes_<Label>.csv`` and ``edges_<TYPE>.csv`` into ``data/processed/``.

Run::

    python -m pipeline.build_core

``pipeline.load`` then validates and loads the files. Nothing here touches Neo4j.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import yaml

from pipeline.config import DATA_CURATED, DATA_PROCESSED, DATA_RAW, SCHEMA_DIR
from pipeline.models import EDGE_COLUMNS
from pipeline.validate import read_csv_rows, split_multi, write_csv_rows

AWARE_2025_FILE = DATA_RAW / "aware" / "WHO-AWaRe-classification-2025.xlsx"
AWARE_SHEET = "AWaRe classification 2025"
CARD_DIR = DATA_RAW / "card"
GLASS_FILE = DATA_RAW / "glass" / "glass_amr_pathogens.csv"
GLASS_MAP_FILE = SCHEMA_DIR / "glass_map.csv"

CURATED_SOURCE_ID = "curated-seed"
#: Above this many genes, CARD alleles are cut to those named in PMID.tsv.
CARD_GENE_LIMIT = 1000

# Titles, organisations, years and versions from data/SOURCES.md.
GUIDELINES: list[dict[str, Any]] = [
    {
        "id": "who-aware-book-2022",
        "title": "The WHO AWaRe (Access, Watch, Reserve) antibiotic book",
        "organisation": "World Health Organization",
        "year": 2022,
        "version": "First edition, 9 December 2022",
    },
    {
        "id": "icmr-treatment-guidelines-2019",
        "title": "Treatment Guidelines for Antimicrobial Use in Common Syndromes",
        "organisation": "Indian Council of Medical Research",
        "year": 2019,
        "version": "2nd edition, 2019",
    },
    {
        "id": "icmr-cr-gram-negative-2022",
        "title": (
            "Guidance on Diagnosis and Management of Carbapenem Resistant "
            "Gram-negative Infections"
        ),
        "organisation": "Indian Council of Medical Research",
        "year": 2022,
        "version": "March 2022",
    },
]

#: Curated file -> (edge type, start label, start id column, end label, end id column).
CURATED_EDGE_FILES: dict[str, tuple[str, str, str, str, str]] = {
    "pathogen_mechanism.csv": ("HAS_MECHANISM", "Pathogen", "pathogen_id", "Mechanism", "mechanism_id"),
    "mechanism_class.csv": ("CONFERS_RESISTANCE_TO", "Mechanism", "mechanism_id", "DrugClass", "class_id"),
    "mechanism_inactivates_drug.csv": ("INACTIVATES", "Mechanism", "mechanism_id", "Drug", "drug_id"),
    "intrinsic_resistance.csv": ("INTRINSICALLY_RESISTANT_TO", "Pathogen", "pathogen_id", "DrugClass", "class_id"),
}

NODE_COLUMNS: dict[str, list[str]] = {
    "Pathogen": ["id", "name", "gram_stain", "synonyms"],
    "Mechanism": ["id", "name", "type", "ambler_class"],
    "Gene": ["id", "name"],
    "Drug": ["id", "name", "aware_group", "synonyms"],
    "DrugClass": ["id", "name", "family"],
    "Recommendation": [
        "id", "text", "infection_site", "line_of_therapy", "patient_group", "regimen_type",
    ],
    "Guideline": ["id", "title", "organisation", "year", "version"],
    "SurveillanceStat": ["id", "country", "year", "pct_resistant", "n_tested"],
}


def _edge(
    start_label: str,
    start_id: str,
    end_label: str,
    end_id: str,
    source_id: str,
    method: str,
    **extra: Any,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "start_id": start_id,
        "start_label": start_label,
        "end_id": end_id,
        "end_label": end_label,
        "source_id": source_id,
        "method": method,
        "confidence": 1.0,
        "evidence_passage_id": "",
    }
    row.update(extra)
    return row


def _write_edges(rel_type: str, rows: list[dict[str, Any]], out_dir: Path) -> None:
    """Write ``edges_<TYPE>.csv`` with the contract columns first, then extras."""
    extras: list[str] = []
    for row in rows:
        for key in row:
            if key not in EDGE_COLUMNS and key not in extras:
                extras.append(key)
    write_csv_rows(out_dir / f"edges_{rel_type}.csv", rows, [*EDGE_COLUMNS, *extras])


def _write_nodes(label: str, rows: list[dict[str, Any]], out_dir: Path) -> None:
    write_csv_rows(out_dir / f"nodes_{label}.csv", rows, NODE_COLUMNS[label])


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------


def load_scope(path: Path = SCHEMA_DIR / "scope.yaml") -> dict[str, list[dict[str, Any]]]:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def load_synonyms(path: Path = SCHEMA_DIR / "synonyms.csv") -> dict[tuple[str, str], list[str]]:
    """``(entity_type, entity_id) -> synonyms``, without canonical rows, in file order."""
    result: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in read_csv_rows(path):
        if row["synonym_type"] == "canonical":
            continue
        syn = row["synonym"].strip()
        key = (row["entity_type"], row["entity_id"])
        if syn and syn not in result[key]:
            result[key].append(syn)
    return result


def build_seed_nodes(
    scope: dict[str, list[dict[str, Any]]], synonyms: dict[tuple[str, str], list[str]]
) -> dict[str, list[dict[str, Any]]]:
    """Pathogen, Mechanism, DrugClass and Drug nodes. ``class_id`` and ``id_verified`` are dropped."""
    nodes: dict[str, list[dict[str, Any]]] = {}
    nodes["Pathogen"] = [
        {
            "id": p["id"],
            "name": p["name"],
            "gram_stain": p.get("gram_stain", ""),
            "synonyms": synonyms.get(("Pathogen", p["id"]), []),
        }
        for p in scope["pathogens"]
    ]
    nodes["Mechanism"] = [
        {
            "id": m["id"],
            "name": m["name"],
            "type": m["type"],
            "ambler_class": m.get("ambler_class") or "",
        }
        for m in scope["mechanisms"]
    ]
    nodes["DrugClass"] = [
        {"id": c["id"], "name": c["name"], "family": c.get("family") or ""}
        for c in scope["drug_classes"]
    ]
    nodes["Drug"] = [
        {
            "id": d["id"],
            "name": d["name"],
            "aware_group": d.get("aware_group") or "Unclassified",
            "synonyms": synonyms.get(("Drug", d["id"]), []),
        }
        for d in scope["drugs"]
    ]
    nodes["Guideline"] = [dict(g) for g in GUIDELINES]
    return nodes


def build_in_class_edges(scope: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    return [
        _edge("Drug", d["id"], "DrugClass", d["class_id"], CURATED_SOURCE_ID, "curated")
        for d in scope["drugs"]
    ]


def build_curated_edges(curated_dir: Path = DATA_CURATED) -> dict[str, list[dict[str, Any]]]:
    """Edges from the four hand-curated files, keeping ``needs_review`` and ``notes``."""
    result: dict[str, list[dict[str, Any]]] = {}
    for filename, (rel, s_label, s_col, e_label, e_col) in CURATED_EDGE_FILES.items():
        rows = []
        for row in read_csv_rows(curated_dir / filename):
            rows.append(
                _edge(
                    s_label,
                    row[s_col].strip(),
                    e_label,
                    row[e_col].strip(),
                    CURATED_SOURCE_ID,
                    "curated",
                    needs_review=row["needs_review"].strip().lower(),
                    notes=row["notes"].strip(),
                    evidence_sources=row["source"].strip(),  # D36, '|'-separated tags
                )
            )
        result[rel] = rows
    return result


# ---------------------------------------------------------------------------
# AWaRe 2025 cross-check
# ---------------------------------------------------------------------------


def _clean_cell(value: Any) -> str:
    return str(value).replace("\xa0", " ").strip()


def _norm_name(name: str) -> str:
    """Compare drug names across scope.yaml and AWaRe: lower case, route suffix removed,
    ``/`` and spaces turned into hyphens."""
    name = _clean_cell(name).lower()
    name = re.sub(r"_(iv|oral)$", "", name)
    return re.sub(r"[\s/]+", "-", name)


def read_aware(path: Path = AWARE_2025_FILE) -> pd.DataFrame:
    frame = pd.read_excel(path, sheet_name=AWARE_SHEET, header=3, dtype=str, keep_default_na=False)
    frame.columns = [_clean_cell(c) for c in frame.columns]
    for column in frame.columns:
        frame[column] = frame[column].map(_clean_cell)
    return frame[frame["Antibiotic"] != ""].reset_index(drop=True)


def check_aware(scope: dict[str, list[dict[str, Any]]], aware: pd.DataFrame) -> dict[str, Any]:
    """Compare ``aware_group`` in scope.yaml with AWaRe 2025. ``scope.yaml`` is never changed.

    A drug is matched on its ATC code. When several AWaRe rows share the code, the row
    whose normalised name equals the drug's name wins, then the IV row (the contract
    takes the IV group when routes differ). A drug that is absent from AWaRe and
    ``Unclassified`` in scope counts as consistent.
    """
    by_atc: dict[str, list[dict[str, str]]] = defaultdict(list)
    for rec in aware.to_dict("records"):
        by_atc[rec["ATC code"]].append(rec)

    matches = mismatches = absent_ok = 0
    mismatch_list: list[dict[str, str]] = []
    absent_list: list[dict[str, str]] = []
    for drug in scope["drugs"]:
        candidates = by_atc.get(drug["id"], [])
        if len(candidates) > 1:
            candidates = [
                c for c in candidates if _norm_name(c["Antibiotic"]) == _norm_name(drug["name"])
            ] or candidates
            iv = [c for c in candidates if c["Antibiotic"].lower().endswith("_iv")]
            candidates = iv or candidates[:1]
        scope_group = drug.get("aware_group") or "Unclassified"
        if not candidates:
            if scope_group == "Unclassified":
                absent_ok += 1
                absent_list.append({"id": drug["id"], "name": drug["name"], "scope_group": scope_group})
            else:
                mismatches += 1
                mismatch_list.append(
                    {
                        "id": drug["id"],
                        "name": drug["name"],
                        "scope_group": scope_group,
                        "aware_2025": "(not in AWaRe 2025)",
                    }
                )
            continue
        aware_group = candidates[0]["Category"]
        if aware_group == scope_group:
            matches += 1
        else:
            mismatches += 1
            mismatch_list.append(
                {
                    "id": drug["id"],
                    "name": drug["name"],
                    "scope_group": scope_group,
                    "aware_2025": aware_group,
                    "aware_name": candidates[0]["Antibiotic"],
                }
            )
    return {
        "drugs_checked": len(scope["drugs"]),
        "matches": matches,
        "mismatches": mismatches,
        "mismatch_list": mismatch_list,
        "absent_and_unclassified": absent_ok,
        "absent_list": absent_list,
    }


# ---------------------------------------------------------------------------
# CARD genes
# ---------------------------------------------------------------------------


def build_card_genes(
    scope: dict[str, list[dict[str, Any]]], card_dir: Path = CARD_DIR
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Gene nodes and ENCODES edges for CARD alleles of the in-scope gene families.

    An allele qualifies when one of its AMR gene families is the ``ARO:`` accession of an
    in-scope mechanism and at least one of its sequences comes from an in-scope pathogen
    (exact NCBI taxon ID). If more than ``CARD_GENE_LIMIT`` alleles qualify, only those
    named in ``PMID.tsv`` are kept.
    """
    mechanism_ids = {m["id"] for m in scope["mechanisms"] if m["id"].startswith("ARO:")}
    taxa = {p["id"].split(":", 1)[1] for p in scope["pathogens"]}

    categories = pd.read_csv(
        card_dir / "aro_categories.tsv", sep="\t", dtype=str, keep_default_na=False
    )
    families = categories[categories["ARO Category"] == "AMR Gene Family"]
    family_acc = dict(zip(families["ARO Name"], families["ARO Accession"]))

    with (card_dir / "card.json").open(encoding="utf-8") as handle:
        card = json.load(handle)
    model_taxa: dict[str, set[str]] = {}
    for key, model in card.items():
        if key.startswith("_"):
            continue
        sequences = (model.get("model_sequences") or {}).get("sequence", {})
        model_taxa[str(model["model_id"])] = {
            str(seq["NCBI_taxonomy"]["NCBI_taxonomy_id"]) for seq in sequences.values()
        }

    index = pd.read_csv(card_dir / "aro_index.tsv", sep="\t", dtype=str, keep_default_na=False)
    genes: dict[str, dict[str, Any]] = {}
    encodes: dict[tuple[str, str], None] = {}
    for rec in index.to_dict("records"):
        fam_ids = [family_acc.get(f.strip()) for f in rec["AMR Gene Family"].split(";")]
        fam_ids = [f for f in fam_ids if f in mechanism_ids]
        if not fam_ids or not (model_taxa.get(rec["Model ID"], set()) & taxa):
            continue
        gene_id = rec["ARO Accession"]
        genes.setdefault(gene_id, {"id": gene_id, "name": rec["ARO Name"]})
        for fam in fam_ids:
            encodes.setdefault((gene_id, fam), None)

    candidates = len(genes)
    rule = "all qualifying alleles"
    if candidates > CARD_GENE_LIMIT:
        pmid = pd.read_csv(card_dir / "PMID.tsv", sep="\t", dtype=str, keep_default_na=False)
        named = set(pmid.loc[pmid["PMID"].str.strip() != "", "ARO Accession"])
        genes = {gid: g for gid, g in genes.items() if gid in named}
        encodes = {k: v for k, v in encodes.items() if k[0] in genes}
        rule = f"alleles named in PMID.tsv (candidates exceeded {CARD_GENE_LIMIT})"

    gene_rows = sorted(genes.values(), key=lambda g: g["id"])
    edge_rows = [
        _edge("Gene", gene_id, "Mechanism", fam, "card", "rule")
        for gene_id, fam in sorted(encodes)
    ]
    per_family = Counter(fam for _, fam in encodes)
    return (
        gene_rows,
        edge_rows,
        {
            "candidate_alleles": candidates,
            "genes_kept": len(gene_rows),
            "rule": rule,
            "genes_per_family": dict(sorted(per_family.items())),
        },
    )


# ---------------------------------------------------------------------------
# GLASS statistics
# ---------------------------------------------------------------------------

GLASS_ACINETOBACTER = "Acinetobacter spp."


def read_glass_map(path: Path = GLASS_MAP_FILE) -> dict[str, tuple[str, str]]:
    """``glass_name -> (target_label, target_id)``; blank targets are deliberately unmapped."""
    mapping: dict[str, tuple[str, str]] = {}
    for row in read_csv_rows(path):
        mapping[row["glass_name"].strip()] = (row["target_label"].strip(), row["target_id"].strip())
    return mapping


def build_glass(
    scope: dict[str, list[dict[str, Any]]],
    glass_path: Path = GLASS_FILE,
    map_path: Path = GLASS_MAP_FILE,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """SurveillanceStat nodes and their ABOUT_* edges from GLASS blood-culture rows.

    One stat per (country, year, pathogen, antibiotic). GLASS lists most keys twice, with a
    blank resistance-group column and with a group; the blank-group row is kept, and
    group-only keys use the first group in alphabetical order (see report ``value_conflicts``).
    """
    pathogen_ids = {p["name"]: p["id"] for p in scope["pathogens"]}
    glass_pathogens = dict(pathogen_ids)
    acinetobacter_id = next(
        (p["id"] for p in scope["pathogens"] if p["name"] == "Acinetobacter baumannii"), None
    )
    if acinetobacter_id:
        glass_pathogens[GLASS_ACINETOBACTER] = acinetobacter_id
    mapping = read_glass_map(map_path)
    scope_targets = {
        "Drug": {d["id"] for d in scope["drugs"]},
        "DrugClass": {c["id"] for c in scope["drug_classes"]},
    }
    not_in_scope: Counter[str] = Counter()  # mapped to an ID that scope.yaml does not have

    frame = pd.read_csv(glass_path, dtype=str, keep_default_na=False)
    total_rows = len(frame)
    frame = frame[
        (frame["DIM_MEMBER_1_CODE"] == "BLOOD")
        & frame["IND_CODE"].isin(["PERCENTAGERESISTANCE", "INTERPRETABLEAST"])
    ]
    in_scope = frame["DIM_MEMBER_2_CODE"].isin(glass_pathogens)
    skipped_pathogen = int((~in_scope).sum())
    frame = frame[in_scope]
    key = ["DIM_TIME", "DIM_GEO_CODE_ISO3", "DIM_MEMBER_2_CODE", "DIM_MEMBER_3_CODE"]
    frame = frame.assign(_grouped=(frame["DIM_MEMBER_5_CODE"] != "")).sort_values(
        ["_grouped", "DIM_MEMBER_5_CODE"], kind="stable"
    )

    pct = frame[frame["IND_CODE"] == "PERCENTAGERESISTANCE"]
    tested = frame[frame["IND_CODE"] == "INTERPRETABLEAST"]
    conflicts = int((pct.groupby(key)["VALUE_NUMERIC"].nunique() > 1).sum())
    chosen = pct.drop_duplicates(key, keep="first")
    tested_by_group = {
        tuple(r[k] for k in [*key, "DIM_MEMBER_5_CODE"]): r["VALUE_NUMERIC"]
        for r in tested.to_dict("records")
    }
    tested_by_key = {
        tuple(r[k] for k in key): r["VALUE_NUMERIC"]
        for r in tested.drop_duplicates(key, keep="first").to_dict("records")
    }

    stats: list[dict[str, Any]] = []
    edges: dict[str, list[dict[str, Any]]] = {"ABOUT_PATHOGEN": [], "ABOUT_DRUG": [], "ABOUT_CLASS": []}
    unmapped: Counter[str] = Counter()
    bad_rows: Counter[str] = Counter()
    seen_ids: set[str] = set()
    mapped_names: set[str] = set()
    for rec in chosen.to_dict("records"):
        name = rec["DIM_MEMBER_3_CODE"]
        target = mapping.get(name)
        if not target or not target[1]:
            unmapped[name] += 1
            continue
        if target[1] not in scope_targets.get(target[0], set()):
            not_in_scope[f"{name} -> {target[0]} {target[1]}"] += 1
            continue
        iso, year = rec["DIM_GEO_CODE_ISO3"], rec["DIM_TIME"]
        if not re.fullmatch(r"[A-Z]{3}", iso) or not re.fullmatch(r"[0-9]{4}", year):
            bad_rows["bad country or year"] += 1
            continue
        try:
            value = float(rec["VALUE_NUMERIC"])
        except ValueError:
            bad_rows["non-numeric value"] += 1
            continue
        if not 0 <= value <= 100:
            bad_rows["percentage outside 0-100"] += 1
            continue
        glass_pathogen = rec["DIM_MEMBER_2_CODE"]
        pathogen_id = glass_pathogens[glass_pathogen]
        target_label, target_id = target
        stat_id = f"GLASS:{iso}:{year}:{pathogen_id}:{target_id}"
        if stat_id in seen_ids:
            bad_rows["two GLASS names map to one stat id"] += 1
            continue
        seen_ids.add(stat_id)
        mapped_names.add(name)

        n_raw = tested_by_group.get(tuple(rec[k] for k in [*key, "DIM_MEMBER_5_CODE"])) or tested_by_key.get(
            tuple(rec[k] for k in key), ""
        )
        n_tested = str(int(float(n_raw))) if n_raw else ""
        stats.append(
            {
                "id": stat_id,
                "country": iso,
                "year": int(year),
                "pct_resistant": value,
                "n_tested": n_tested,
            }
        )
        extra = {"reported_taxon": GLASS_ACINETOBACTER} if glass_pathogen == GLASS_ACINETOBACTER else {}
        edges["ABOUT_PATHOGEN"].append(
            _edge("SurveillanceStat", stat_id, "Pathogen", pathogen_id, "glass", "rule", **extra)
        )
        rel = "ABOUT_DRUG" if target_label == "Drug" else "ABOUT_CLASS"
        edges[rel].append(_edge("SurveillanceStat", stat_id, target_label, target_id, "glass", "rule"))

    all_names = sorted(set(chosen["DIM_MEMBER_3_CODE"]))
    report = {
        "rows_in_file": total_rows,
        "stat_keys_in_scope": len(chosen),
        "stats_written": len(stats),
        "rows_skipped_other_pathogen": skipped_pathogen,
        "value_conflicts_between_group_rows": conflicts,
        "glass_names_seen": len(all_names),
        "glass_names_mapped": sorted(mapped_names),
        "glass_targets_not_in_scope": dict(sorted(not_in_scope.items())),
        "glass_names_unmapped": {n: c for n, c in sorted(unmapped.items())},
        "skipped_rows_by_reason": dict(bad_rows),
        "stats_per_pathogen": dict(
            Counter(r["id"].split(":", 3)[3].rsplit(":", 1)[0] for r in stats)
        ),
    }
    return stats, edges, report


# ---------------------------------------------------------------------------
# Curated recommendations (D32, D33)
# ---------------------------------------------------------------------------

RECOMMENDATIONS_FILE = DATA_CURATED / "recommendations_curated.csv"
PASSAGES_FILE = DATA_PROCESSED / "passages.jsonl"
#: confidence of a SUPPORTS edge: passage on the cited page / nearest earlier passage
SUPPORTS_CONFIDENCE_EXACT = 1.0
SUPPORTS_CONFIDENCE_NEAREST = 0.7


def infer_regimen_type(drug_ids: list[str]) -> str:
    """Used when the ``regimen_type`` column is missing or blank: one drug is ``single``,
    several are ``any-of`` (alternatives are the safe reading)."""
    return "single" if len(drug_ids) == 1 else "any-of"


def _heading_key(text: str) -> str:
    """Leading section number of a heading, for example ``10.4.5`` or ``42``; '' if none."""
    match = re.match(r"\s*(\d+(?:\.\d+)*)", text or "")
    return match.group(1) if match else ""


def _supporting_passages(
    passages: list[dict[str, Any]], source_page: int, source_section: str
) -> tuple[list[dict[str, Any]], float]:
    """Passages of one document that support a row cited on ``source_page``.

    Those on that page; if there are none, those on the nearest earlier page. When the
    cited section starts with a number, passages whose heading carries the same number
    are preferred (the rest are kept only if none match).
    """
    with_page = [p for p in passages if isinstance(p.get("page"), int)]
    exact = [p for p in with_page if p["page"] == source_page]
    confidence = SUPPORTS_CONFIDENCE_EXACT
    chosen = exact
    if not chosen:
        earlier = [p["page"] for p in with_page if p["page"] < source_page]
        if not earlier:
            return [], 0.0
        chosen = [p for p in with_page if p["page"] == max(earlier)]
        confidence = SUPPORTS_CONFIDENCE_NEAREST
    key = _heading_key(source_section)
    if key:
        same = [p for p in chosen if _heading_key(p.get("heading", "")) == key]
        chosen = same or chosen
    return chosen, confidence


def build_recommendations(
    scope: dict[str, list[dict[str, Any]]],
    recs_path: Path = RECOMMENDATIONS_FILE,
    passages_path: Path = PASSAGES_FILE,
    passage_ids: Optional[set[str]] = None,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """``Recommendation`` nodes and their FOR_PATHOGEN, FOR_MECHANISM, RECOMMENDS, FROM and
    SUPPORTS edges from ``recommendations_curated.csv``.

    Columns are read by name. ``mechanism_id`` may hold several ``|``-separated IDs;
    ``regimen_type`` may be missing (then it is inferred). SUPPORTS edges (``method`` ``rule``)
    link to ``passages.jsonl`` passages from the guideline's own document; when ``passage_ids``
    is given, only those passage IDs are linked.
    """
    nodes: list[dict[str, Any]] = []
    edges: dict[str, list[dict[str, Any]]] = {
        rel: [] for rel in ("FOR_PATHOGEN", "FOR_MECHANISM", "RECOMMENDS", "FROM", "SUPPORTS")
    }
    report: dict[str, Any] = {
        "recommendations": 0,
        "regimen_type_inferred": 0,
        "regimen_types": {},
        "rows_without_supporting_passage": [],
        "rows_with_nearest_earlier_passage": 0,
    }
    if not recs_path.is_file():
        report["note"] = f"{recs_path.name} not found; no recommendation files written"
        return nodes, edges, report

    by_doc: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if passages_path.is_file():
        with passages_path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    passage = json.loads(line)
                    if passage_ids is None or passage["id"] in passage_ids:
                        by_doc[passage["source_doc"]].append(passage)
    else:
        report["note"] = f"{passages_path.name} not found; no SUPPORTS edges"

    drug_ids_in_scope = {d["id"] for d in scope["drugs"]}
    for row in read_csv_rows(recs_path):
        rec_id = row["rec_id"].strip()
        drugs = list(dict.fromkeys(split_multi(row["drug_ids"])))
        mechanisms = list(dict.fromkeys(split_multi(row.get("mechanism_id", ""))))
        regimen = (row.get("regimen_type") or "").strip()
        if not regimen:
            regimen = infer_regimen_type(drugs)
            report["regimen_type_inferred"] += 1
        report["regimen_types"][regimen] = report["regimen_types"].get(regimen, 0) + 1
        nodes.append(
            {
                "id": rec_id,
                "text": row["text"].strip(),
                "infection_site": row["infection_site"].strip(),
                "line_of_therapy": row["line_of_therapy"].strip(),
                "patient_group": row["patient_group"].strip(),
                "regimen_type": regimen,
            }
        )
        guideline = row["guideline_id"].strip()
        edges["FOR_PATHOGEN"].append(
            _edge("Recommendation", rec_id, "Pathogen", row["pathogen_id"].strip(), CURATED_SOURCE_ID, "curated")
        )
        for mechanism in mechanisms:
            edges["FOR_MECHANISM"].append(
                _edge("Recommendation", rec_id, "Mechanism", mechanism, CURATED_SOURCE_ID, "curated")
            )
        for drug in drugs:
            if drug not in drug_ids_in_scope:
                report.setdefault("drugs_not_in_scope", []).append(f"{rec_id}: {drug}")
            edges["RECOMMENDS"].append(
                _edge("Recommendation", rec_id, "Drug", drug, CURATED_SOURCE_ID, "curated")
            )
        edges["FROM"].append(
            _edge("Recommendation", rec_id, "Guideline", guideline, CURATED_SOURCE_ID, "curated")
        )

        page = (row.get("source_page") or "").strip()
        found: list[dict[str, Any]] = []
        if page.isdigit():
            found, confidence = _supporting_passages(
                by_doc.get(guideline, []), int(page), row.get("source_section", "")
            )
        if not found:
            report["rows_without_supporting_passage"].append(rec_id)
            continue
        if confidence < SUPPORTS_CONFIDENCE_EXACT:
            report["rows_with_nearest_earlier_passage"] += 1
        for passage in found:
            edges["SUPPORTS"].append(
                _edge(
                    "Passage", passage["id"], "Recommendation", rec_id, guideline, "rule",
                )
                | {"confidence": confidence}
            )
    report["recommendations"] = len(nodes)
    return nodes, edges, report


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def build_core(out_dir: Path = DATA_PROCESSED) -> dict[str, Any]:
    """Write every core node and edge file into ``out_dir`` and return a build report."""
    out_dir.mkdir(parents=True, exist_ok=True)
    scope = load_scope()
    synonyms = load_synonyms()

    nodes = build_seed_nodes(scope, synonyms)
    edges: dict[str, list[dict[str, Any]]] = {"IN_CLASS": build_in_class_edges(scope)}
    edges.update(build_curated_edges())

    aware_report = check_aware(scope, read_aware())
    genes, encodes, card_report = build_card_genes(scope)
    nodes["Gene"] = genes
    edges["ENCODES"] = encodes
    stats, glass_edges, glass_report = build_glass(scope)
    nodes["SurveillanceStat"] = stats
    edges.update(glass_edges)

    passage_nodes = DATA_PROCESSED / "nodes_Passage.csv"
    known_passages = {r["id"] for r in read_csv_rows(passage_nodes)} if passage_nodes.is_file() else None
    rec_nodes, rec_edges, rec_report = build_recommendations(scope, passage_ids=known_passages)
    if rec_nodes:
        nodes["Recommendation"] = rec_nodes
        edges.update(rec_edges)

    for label, rows in nodes.items():
        _write_nodes(label, rows, out_dir)
    for rel_type, rows in edges.items():
        _write_edges(rel_type, rows, out_dir)

    return {
        "nodes": {label: len(rows) for label, rows in sorted(nodes.items())},
        "edges": {rel: len(rows) for rel, rows in sorted(edges.items())},
        "aware": aware_report,
        "card": card_report,
        "glass": glass_report,
        "recommendations": rec_report,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.build_core",
        description="Write the core nodes_*.csv and edges_*.csv files into data/processed/.",
    )
    parser.add_argument("--out", type=Path, default=DATA_PROCESSED, help="output directory")
    args = parser.parse_args(argv)
    report = build_core(args.out)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

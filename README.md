# AMR-Navigator

A knowledge graph and hybrid retrieval system that explains why an antibiotic is recommended or restricted for a resistant pathogen. Mini-project for the Knowledge Graph and Information Retrieval Systems course.

> **Not medical advice.** This is an educational tool. It does not replace susceptibility testing, local antibiograms or clinical judgement.

## Status

Under construction. Progress is tracked on the task board in [docs/ORCHESTRATION.md](docs/ORCHESTRATION.md).

## Documents

| Document | Contents |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Design, graph schema, retrieval method |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Design decisions and their reasons |
| [docs/PLAN.md](docs/PLAN.md) | Phases, milestones, risks |
| [docs/CONTRACTS.md](docs/CONTRACTS.md) | File formats, IDs, module interfaces |
| [docs/ORCHESTRATION.md](docs/ORCHESTRATION.md) | How the work is split across sessions, task board |

## Setup

Requires Python 3.11 and Docker Desktop.

```bash
python -m venv --system-site-packages .venv
```

```bash
.venv/Scripts/python -m pip install -r requirements.txt
```

```bash
docker compose up -d
```

```bash
.venv/Scripts/python -m pytest tests
```

Neo4j Browser is then at http://localhost:7474 (user `neo4j`, password from `.env.example`).

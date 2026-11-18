# AMR-Navigator: Orchestration

This project is built by several Claude sessions working in the same folder. One session is the orchestrator. The others are workers, each doing one task. Sessions do not share memory, so everything they need to know is in these Markdown files.

| File | Purpose | Who edits it |
|---|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | The design | Orchestrator |
| [DECISIONS.md](DECISIONS.md) | Decisions and their reasons | Orchestrator |
| [PLAN.md](PLAN.md) | Phases and milestones | Orchestrator |
| [CONTRACTS.md](CONTRACTS.md) | File formats, IDs and module interfaces that tasks share | Orchestrator |
| `docs/tasks/T<nn>-<name>.md` | The brief for one task | Orchestrator |
| `docs/handoffs/T<nn>-<name>.md` | What a worker built and found | The worker for that task |
| This file | Rules, waves and the task board | Orchestrator |

## Roles

- **Orchestrator:** makes decisions, writes briefs, owns the documents above and `pipeline/config.py`, reviews every handoff, and starts the next wave.
- **Worker:** completes one task brief, touches only the files that brief lists, and writes a handoff.

Model choice: **Opus 5.5** for clinical-domain judgement and query logic where an error is costly, **Sonnet 5.5** for general implementation, **Haiku 5.5** for small, fully specified tasks.

### Effort levels (D38)

Every worker session gets a reasoning effort chosen for its task, and **never above `high`**.

| Effort | Use for |
|---|---|
| `low` | Mechanical work with a complete specification: formatting, small fixes, re-running a step |
| `medium` | Normal implementation and data processing with clear contracts |
| `high` | Clinical-domain judgement, reasoning-query logic, integration where errors are hard to see, the final report |

The orchestrator may change a running worker's effort mid-session. It raises effort when a worker reports something hard or unexpected, or when a review sends back a subtle correction, and lowers it for follow-ups that are mechanical. A change applies from the worker's next turn. Workers who think their effort is wrong for what is left say so in their message or under "Requests to orchestrator"; they do not change it themselves.

## Rules for workers

1. **Read first:** this file, [CONTRACTS.md](CONTRACTS.md), your task brief, and the parts of [ARCHITECTURE.md](ARCHITECTURE.md) the brief names.
2. **Stay in your files.** Create or edit only the paths under "Files you own" in your brief. Other sessions are writing other files in this folder at the same time. You may read anything.
3. **Follow the contracts.** If a contract is wrong, unclear or missing something, do not deviate silently. Choose the closest option that still fits, and report it under "Requests to orchestrator" in your handoff.
4. **Never invent data.** Datasets come from the real sources. Domain facts you are not sure of are marked `needs_review`. Cite only sources you are confident exist.
5. **Keep the user private.** Do not put any name or email address in outbound requests. Use the client name `amr-navigator`.
6. **Use the project environment.** Run Python as `.venv/Scripts/python`. Do not install packages. If you need one that is not in `requirements.txt`, ask for it in your handoff and work around it.
7. **Test your work.** Put tests in `tests/test_<area>.py`. Run `.venv/Scripts/python -m pytest tests` before you finish and report the result as it is, including failures in files that are not yours.
8. **Be careful with shared state.** No git commands. Do not delete or move files you do not own. Do not stop or remove Docker containers you did not start. Other sessions use the same Neo4j database at the same time, so tests that write to it must use IDs unique to the test run and delete only what they created.
9. **Expect the GateGuard hook.** This machine has a hook that blocks the first Bash command and the first file created in each folder until you state a few facts in your message. State them and retry the same call. Do not disable the hook.
10. **Finish with a handoff.** Copy `docs/handoffs/TEMPLATE.md` to `docs/handoffs/<your task id and name>.md` and fill it in. Your final message is a short summary of that handoff.

## Waves

A wave is a set of tasks with no dependencies on each other, so they run in parallel. The orchestrator starts a wave only after reviewing the handoffs it depends on.

### Task board

Status values: `todo`, `running`, `review`, `done`, `blocked`.

Effort for wave 1 and the first runs of wave 2 was inherited from the orchestrator, before D38; the levels shown for those tasks apply to their follow-ups.

| ID | Task | Model | Effort | Depends on | Wave | Status |
|---|---|---|---|---|---|---|
| T00 | Scaffold, environment, contracts | Orchestrator | – | – | 0 | done |
| T01 | Schema, data models, validation, database helpers | Sonnet 5.5 | medium | T00 | 1 | done |
| T02 | Data acquisition and source inventory | Sonnet 5.5 | medium | T00 | 1 | done |
| T03 | Domain seed data: scope, synonyms, resistance facts | Opus 5.5 | high | T00 | 1 | done |
| T04 | Evaluation metric functions | Haiku 5.5 | low | T00 | 1 | done |
| T05 | Structured loaders and core graph build | Sonnet 5.5 | medium | T01, T02, T03 | 2 | done |
| T06 | PDF ingestion and section-aware chunking | Sonnet 5.5 | medium | T02 | 2 | done |
| T07 | Entity matcher and linker | Sonnet 5.5 | medium | T03, T06 | 2 | done |
| T08 | Curate guideline recommendations | Opus 5.5 | high | T02, T03 | 2 | done |
| T09 | Evaluation questions with gold answers | Opus 5.5 | medium | T02, T03 | 2 | done |
| T10 | Cypher templates and path output | Opus 5.5 | high | T05, T08 | 3 | done |
| T11 | BM25 and FAISS passage indexes | Sonnet 5.5 | medium | T06 | 3 | done |
| T12 | Query parser and intent rules | Sonnet 5.5 | medium | T07 | 3 | done |
| T13 | Recommendation extraction experiment | Sonnet 5.5 | medium | T06, T07, T08 | 3 | done |
| T14 | Fusion and answer builder | Sonnet 5.5 | high | T10, T11, T12 | 4 | done |
| T15 | Relevant passages for the evaluation questions | Opus 5.5 | medium | T09, T10, T11 | 4 | done |
| T16 | Streamlit app | Sonnet 5.5 | medium | T14 | 5 | todo |
| T17 | Evaluation runner and results | Sonnet 5.5 | medium | T04, T14, T15 | 5 | todo |
| T18 | Report, README and demo script | Opus 5.5 | high | T16, T17 | 6 | todo |

Waves map to the phases in [PLAN.md](PLAN.md): waves 0–1 are phase 1, wave 2 is phases 2–3, waves 3–4 are phase 4, wave 5 is phase 5, wave 6 is phase 6.

## Handoff review

For each handoff the orchestrator:

1. reads the handoff and checks the files it lists exist;
2. runs the test suite;
3. accepts the task, or sends corrections to the same worker session;
4. applies accepted "Requests to orchestrator" to the contracts or decisions;
5. updates the task board.

## Review log

| Date | Task | Outcome |
|---|---|---|
| 2026-11-17 | T04 | Accepted. 55 tests pass, and the functions matched values the orchestrator computed independently. Its four interpretation choices are accepted and recorded in CONTRACTS.md section 7. |
| 2026-11-18 | T01 | Accepted with follow-ups. 9 constraints and 4 indexes confirmed live. Asked for `ABOUT_CLASS` (D26) and unique IDs in its database tests, which failed once when another session ran them at the same time. |
| 2026-11-18 | T02, T03 | Both stopped at a usage limit before writing handoffs. Most files were on disk; both sessions were resumed. |
| 2026-11-18 | T01 | Done. `ABOUT_CLASS` added and database tests use per-run IDs. |
| 2026-11-18 | T02 | Accepted. All six sources downloaded automatically. Its requests are decided in D28, D30, D31. |
| 2026-11-18 | T03 | Accepted with a follow-up: class families, `ClassFamily` synonyms and `schema/phenotypes.csv` (D29). Orchestrator added `DrugClass.family` and `who-aware-2025` to `pipeline/models.py`. |

| 2026-11-18 | T05 | Accepted. Acceptance query re-run by the orchestrator on the live graph: KPC, NDM and OXA-48-like give T03's three sets (milestone M2). Follow-up: recommendations into the graph (D32), `evidence_sources` (D36), MRSA mapping (D35). |
| 2026-11-18 | T06 | Accepted. 1,428 passages, stable IDs. |
| 2026-11-18 | T07 | Accepted pending the corpus run, which needed T06's output; follow-up sent. |
| 2026-11-18 | T08 | Accepted. 80 recommendations; 11 conflicts with the seed data resolved by D34. Follow-up: `regimen_type` and co-producers (D33). |
| 2026-11-18 | T09 | Accepted. 40 questions with sourced gold answers. Follow-up: keywords for scoring fact and decline answers. |

| 2026-11-18 | T05, T07, T08, T09 | Follow-ups accepted. T07: 3,822 `MENTIONS` edges, 49 of 50 hand-checked links correct. Orchestrator corrected D35 (oxacillin is not in scope, so GLASS Oxacillin stays unmapped) and rebuilt the graph with `--clear`: 17,156 nodes, 35,445 edges, 0 rejected. Mechanism-specific recommendations for CRKP verified by query. |
| 2026-11-18 | T10–T13 | Accepted. Orchestrator ran the original question end to end (parser → graph search → text search): correct intent, entities and per-mechanism groups, but each group mixed recommended drugs with every non-excluded drug, so D39 splits them. D40–D42 decided. Orchestrator added pathogen short forms (`Kp`, `Ecoli` and others) to `schema/synonyms.csv`. Follow-ups: T08 (three data columns), T10 (read them, D39). |
| 2026-11-18 | T10 | Follow-up accepted. 713 tests pass (Neo4j running). Orchestrator re-ran the original question: recommended drugs per mechanism are KPC 12, NDM 12, OXA-48-like 11, VIM 7, matching the handoff, with not-excluded-only drugs listed apart (D39). `why_restricted` (colistin) and `recommendation_lookup` (MRSA bloodstream) also checked. Open item for the orchestrator: write `caveat`, `base_drug_ids` and `susceptible_only` onto `Recommendation` nodes in `pipeline/build_core.py`; until then graph search reads them from the CSV. |
| 2026-11-18 | T14, T15 | Both first sessions stopped without handoffs; restarted as fresh workers on the partial files. Both accepted. 725 tests pass. T14: `answer()` in five modes, same per-mechanism counts as T10 on the original question (milestone M4); contract row updated. T15: 2,084 pooled pairs judged, 345 relevant (113 grade 2); orchestrator spot-checked grade-2 passages for Q01, Q14, Q27. Rulings: D43 (Q38, Q33 gold kept), D44 (scoring rules for T17). |

Files of a task marked done belong to the orchestrator afterwards; a later brief may hand them to another task.

## Environment facts

- Windows 11, Python 3.11, virtual environment in `.venv` (built on the system packages, so `torch` and `sentence-transformers` are already available).
- Neo4j runs in Docker from `docker-compose.yml`, as the container `amr-navigator-neo4j`. Docker Desktop must be started by the user; if it is not running, database tests are skipped and the handoff says so. Leave the container running when you finish.
- The project is a git repository pushed to https://github.com/om8P/ResistanceRoute (public). Only the orchestrator commits and pushes; workers never run git commands. Downloaded data in `data/raw/` and generated files in `data/processed/` are not committed (D19).

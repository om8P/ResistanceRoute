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

| ID | Task | Model | Depends on | Wave | Status |
|---|---|---|---|---|---|
| T00 | Scaffold, environment, contracts | Orchestrator | – | 0 | done |
| T01 | Schema, data models, validation, database helpers | Sonnet 5.5 | T00 | 1 | done |
| T02 | Data acquisition and source inventory | Sonnet 5.5 | T00 | 1 | done |
| T03 | Domain seed data: scope, synonyms, resistance facts | Opus 5.5 | T00 | 1 | review (class-family follow-up) |
| T04 | Evaluation metric functions | Haiku 5.5 | T00 | 1 | done |
| T05 | Structured loaders and core graph build | Sonnet 5.5 | T01, T02, T03 | 2 | todo (after T03 follow-up) |
| T06 | PDF ingestion and section-aware chunking | Sonnet 5.5 | T02 | 2 | running |
| T07 | Entity matcher and linker | Sonnet 5.5 | T03, T06 | 2 | todo (after T03 follow-up) |
| T08 | Curate guideline recommendations | Opus 5.5 | T02, T03 | 2 | running |
| T09 | Evaluation questions with gold answers | Opus 5.5 | T02, T03 | 2 | running |
| T10 | Cypher templates and path output | Opus 5.5 | T05, T08 | 3 | todo |
| T11 | BM25 and FAISS passage indexes | Sonnet 5.5 | T06 | 3 | todo |
| T12 | Query parser and intent rules | Sonnet 5.5 | T07 | 3 | todo |
| T13 | Recommendation extraction experiment | Sonnet 5.5 | T06, T07, T08 | 3 | todo |
| T14 | Fusion and answer builder | Sonnet 5.5 | T10, T11, T12 | 4 | todo |
| T15 | Relevant passages for the evaluation questions | Opus 5.5 | T09, T10, T11 | 4 | todo |
| T16 | Streamlit app | Sonnet 5.5 | T14 | 5 | todo |
| T17 | Evaluation runner and results | Sonnet 5.5 | T04, T14, T15 | 5 | todo |
| T18 | Report, README and demo script | Opus 5.5 | T16, T17 | 6 | todo |

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

Files of a task marked done belong to the orchestrator afterwards; a later brief may hand them to another task.

## Environment facts

- Windows 11, Python 3.11, virtual environment in `.venv` (built on the system packages, so `torch` and `sentence-transformers` are already available).
- Neo4j runs in Docker from `docker-compose.yml`, as the container `amr-navigator-neo4j`. Docker Desktop must be started by the user; if it is not running, database tests are skipped and the handoff says so. Leave the container running when you finish.
- The project folder is not a git repository.

# Repository Map

| Path | Purpose |
|---|---|
| `campusflow/domain.py` | Product entities |
| `campusflow/repository.py` | SQLite persistence |
| `campusflow/service.py` | Business rules |
| `campusflow/api.py` | HTTP adapter |
| `factory_app/agent.py` | ADK root agent |
| `factory_app/agents.py` | Specialized agents |
| `factory_app/tools.py` | Bounded tools |
| `factory_app/prompts.py` | Agent contracts |
| `factory_app/run_state.py` | Run state machine and human gates |
| `factory_app/planning_runner.py` | Intake -> Planner orchestration |
| `factory_app/coding_runner.py` | Coder -> Test Analyst -> Verification Gate |
| `factory_app/verification.py` | Deterministic verification gate |
| `factory_app/review_runner.py` | Independent Reviewer + Security + deterministic scanners |
| `factory_app/evidence_runner.py` | Evidence consolidation and release-gate handoff |
| `change_requests/` | Work input |
| `scripts/` | Deterministic run/gate helpers |
| `scripts/run_coding.py` | CLI for the implementation slice |
| `scripts/run_review.py` | CLI for the review and security slice |
| `scripts/consolidate_evidence.py` | CLI for evidence and release-gate handoff |
| `tests/factory/` | Factory tests with fake agents ($0 Gemini) |
| `tests/` | Product, factory and eval tests |
| `runs/` | Generated evidence |

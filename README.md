# CampusFlow + Agentic Software Factory — Starter Repository

Starter repository for the UADY course **Ingeniería de Software asistida por IA**.

This repository deliberately separates two systems:

1. **`campusflow/`** — the software product the factory must evolve.
2. **`factory_app/`** — an initial Google ADK skeleton for the software factory.

The goal is not to build the fanciest application. The goal is to engineer a repeatable **Human + AI Software Factory** that can transform a Change Request into verifiable software evidence.

## Reference stack

- Python 3.11+
- Google ADK
- Gemini Developer API via Google AI Studio
- Google Agents CLI
- Git + GitHub
- pytest + ruff
- Semgrep / dependency audit / secret scan (students add/configure)
- GitHub Actions

No Google Cloud billing is required for the starter.

## Setup

```bash
uvx google-agents-cli setup
uv sync
cp .env.example .env
```

Set the Google AI Studio key in `.env`:

```bash
GOOGLE_API_KEY="..."
```

Baseline:

```bash
uv run pytest -q
uv run ruff check campusflow tests factory_app scripts
```

## Run the ADK starter

```bash
uv run adk run factory_app
```

or:

```bash
uv run adk web --port 8000
```

The root ADK workflow currently executes only **Intake -> Planner**. This is intentional: the factory must stop for a human plan approval before implementation.

Run the starter eval dataset with:

```bash
agents-cli eval run
```

## Start a factory run

```bash
uv run python scripts/start_run.py CR-001
uv run python scripts/run_planning.py CR-001
uv run python scripts/approve_gate.py CR-001 plan APPROVED "Plan reviewed" --by <name> --role tech_lead
uv run python scripts/show_run.py CR-001
```

`run_planning.py` runs Intake and then Planner, saves `01-intake-report.md` and
`03-implementation-plan.md` under `runs/CR-001/`, and stops at a human gate:

- Clear Change Request: status `AWAITING_PLAN_APPROVAL`. The Coder stays blocked until a
  human records `APPROVED` with `approve_gate.py` (who, role and reason are mandatory).
- Ambiguous Change Request (CR-005): status `AWAITING_CLARIFICATION`. The Planner does not
  run. The Product Owner answers with `approve_gate.py CR-005 requirements APPROVED "<policy>"
  --by <name> --role product_owner` and `run_planning.py` is run again with that answer.
- A failed model call (429/503) is retried with backoff. If it still fails, running the
  script again resumes from the last saved stage instead of repeating Intake.

Code that must wait for a human calls `factory_app.run_state.require_gate_approved(...)`.

## Student mission

Extend the starter until the factory supports:

```text
Change Request
    |
Intake Agent
    |
Planner Agent
    |
HUMAN GATE: Product Owner / Tech Lead
    |
Coder Agent
    |
Deterministic Verification
    |
+-------------------+
|                   |
Reviewer Agent   Security Agent
|                   |
+---------+---------+
          |
HUMAN REVIEW
          |
Fix (if required)
          |
Re-verification
          |
Re-review
          |
HUMAN RELEASE GATE
          |
PR Evidence
```

### Mandatory principles

- Coder and Reviewer must not share the same review context.
- Reviewer and Security are read-only during first-pass review.
- Requirements are the source of truth.
- Never weaken tests to obtain PASS.
- LLM output is not verification.
- Deterministic checks belong in deterministic tools.
- Important transitions must produce evidence.
- Human decisions must be explicit and auditable.
- Never send secrets or real personal data to the Gemini Free Tier.

## Initial Change Requests

1. `CR-001-waitlist.md`
2. `CR-002-authorization.md`
3. `CR-003-duplicate-registration.md`
4. `CR-004-csv-export.md`
5. `CR-005-ambiguous-priority.md`

CR-005 is intentionally ambiguous. A good factory must stop for clarification rather than inventing policy.

## Intentionally incomplete

Students still have to implement:

- the complete orchestrator;
- bounded Coder write tools;
- Git branch/diff/commit evidence;
- security scanner integration;
- human finding decisions;
- fix -> reverify -> rereview;
- release readiness;
- traceability and `factory-run.json`;
- expanded agent evals.

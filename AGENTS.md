# AGENTS.md — Repository Operating Contract

## Read first

1. `docs/REQUIREMENTS.md`
2. `docs/SPEC.md`
3. `docs/ARCHITECTURE.md`
4. active `change_requests/CR-*.md`
5. `docs/REPO_MAP.md`

## Source of truth

- Requirements / AC: `docs/REQUIREMENTS.md`.
- `SPEC.md` defines verifiable behavior without redefining requirements.
- Architecture constraints: `ARCHITECTURE.md`.
- Change Requests scope a specific run.

## Standard validation

```bash
python scripts/verify_repo.py
```

## Rules

- Do not invent requirements.
- Do not edit requirements/spec just to make code pass.
- Do not weaken tests.
- Keep changes scoped.
- Never expose secrets.
- Never merge automatically.
- Reviewer and Security are read-only on first review.

## Least privilege (in code, not only in prompts)

- `campusflow/` never imports `factory_app`. Business rules live in `campusflow/service.py`
  (`API -> Service -> Repository`).
- `Coder`: read is scoped; write only under `campusflow/` and `tests/`. Never write
  `docs/`, `runs/`, `factory_app/`, `scripts/` or `.env`.
- `Test Analyst`: read is scoped; write only under `tests/`. Never modify `campusflow/`.
- `Reviewer` and `Security`: 100% read-only. They get no write tool at all.
- No agent may weaken tests (`xfail`, `skip`, deleted assertions) or edit
  `docs/REQUIREMENTS.md` / `docs/SPEC.md` to force a PASS.
- The maximum automated status is `READY_FOR_HUMAN_MERGE`. No agent runs `git merge`.

## State machine and human gates

`runs/<CR-ID>/factory-state.json` is the single source of truth; the full transition table
and schema live in `docs/ARCHITECTURE.md`:

```text
INTAKE_PENDING -> AWAITING_CLARIFICATION | INTAKE_COMPLETE -> AWAITING_PLAN_APPROVAL
-> PLAN_APPROVED -> CODING_COMPLETE -> VERIFICATION_PASSED | VERIFICATION_FAILED
-> (Bloque 3) AWAITING_REVIEW_DECISIONS -> EVIDENCE_CONSOLIDATED
-> (Bloque 4) AWAITING_RELEASE_DECISION -> READY_FOR_HUMAN_MERGE
```

| Role | Gate | Decisions | Evidence |
|---|---|---|---|
| `product_owner` | `requirements` | `APPROVED`, `MODIFIED`, `REJECTED` | `02-human-requirement-decision.json` |
| `tech_lead` / `product_owner` | `plan` | `APPROVED`, `MODIFIED`, `REJECTED` | `04-human-plan-approval.json` |
| `reviewer` | `review` | `APPROVED`, `MODIFIED`, `REJECTED`, `DEFERRED` | `10-human-review-decisions.json` |
| `release_manager` | `release` | `APPROVED`, `MODIFIED`, `REJECTED`, `DEFERRED` | `15-release-decision.json` |

Only `scripts/approve_gate.py` records a decision (person, role and reason are mandatory).
Agents never approve, and a stage refuses to start until its gate is `APPROVED`.

## Agent contracts

| Agent | Allows | Denies | Output | Stops when |
|---|---|---|---|---|
| `intake` | read-only tools | every write | `01-intake-report.md` | business rule undefined (fail-closed) |
| `planner` | read-only tools | every write | `03-implementation-plan.md` | ambiguity remains |
| `coder` | `write_coder_file` in `campusflow/`, `tests/` | `docs/`, `runs/`, `factory_app/`, `scripts/`, `.env` | `05-coder-report.md` | plan gate not `APPROVED` |
| `tester` | `write_test_file` in `tests/`, deterministic verification | any write in `campusflow/` | `06-test-analysis.md` | PASS claimed without evidence |
| `reviewer` | read-only tools | every write | `08-review-report.md` | evidence insufficient |
| `security` | read-only tools + scanner output | every write | `09-security-report.md` | evidence insufficient |

Reviewer and Security run in clean sessions: they never see the Coder's history or claims as
proof, only requirements/spec/architecture, the CR, the plan, the `git diff` and
`07-verification.txt`.

## Stop conditions

Stop for human input when requirements conflict/are ambiguous, permissions are insufficient, an irreversible action is proposed, evidence is insufficient, or a dependency/API appears invented.

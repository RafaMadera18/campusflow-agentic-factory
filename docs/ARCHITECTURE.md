# Architecture

## Product

```text
FastAPI adapter
      |
      v
CampusFlowService        <- business rules
      |
      v
SQLiteCampusFlowRepository
      |
      v
SQLite
```

Rules: API does not implement business policy; Repository does not decide business policy; Service coordinates behavior.

## Factory

```text
Change Request -> Intake -> Planner -> HUMAN GATE -> Coder -> Verification
                                                   -> Reviewer + Security
                                                   -> HUMAN REVIEW
                                                   -> Fix / Re-review
                                                   -> HUMAN RELEASE
                                                   -> PR Evidence
```

The Reviewer must inspect requirements, architecture, changed code, tests, verification evidence and actual APIs/dependencies. It must not treat the Coder's own claims as proof.

## Run state machine

Every run lives in `runs/<CR-ID>/`. `factory-state.json` is the single source of truth. The
only value that moves a run forward is `status`, and the only way to cross a human gate is a
recorded decision (see `factory_app/run_state.py`).

```text
INITIALIZED  (documental: el instante en que se crea runs/<CR-ID>/; el JSON siempre nace
              en INTAKE_PENDING con la nota "run created" en history)
    |
    v
INTAKE_PENDING ----intake PROCEED----> INTAKE_COMPLETE ----plan escrito----> AWAITING_PLAN_APPROVAL
    |                                         |
    +----intake AMBIGUO----> AWAITING_CLARIFICATION
    |                              |
    |                              +--gate requirements APPROVED/MODIFIED--> INTAKE_PENDING (re-entra con la respuesta)
    |                              +--gate requirements REJECTED-----------> CR_REJECTED
    |
AWAITING_PLAN_APPROVAL --gate plan--> PLAN_APPROVED | PLAN_CHANGES_REQUESTED | PLAN_REJECTED
    |
PLAN_APPROVED ----Coder + Test Analyst----> CODING_COMPLETE
CODING_COMPLETE --Verification Gate OK----> VERIFICATION_PASSED
CODING_COMPLETE --Verification Gate FAIL--> VERIFICATION_FAILED
VERIFICATION_FAILED --(<= MAX_FIX_ATTEMPTS=2)--> CODING_COMPLETE   (fix acotado del Coder)
VERIFICATION_FAILED --(intentos agotados)----> se detiene; intervencion humana requerida

VERIFICATION_PASSED --> AWAITING_REVIEW_DECISIONS --> CODING_COMPLETE (fix) | EVIDENCE_CONSOLIDATED
EVIDENCE_CONSOLIDATED --> AWAITING_RELEASE_DECISION --gate release APPROVED--> READY_FOR_HUMAN_MERGE
```

Rules:

- `INITIALIZED` is documentary: `factory-state.json` never stores it; `create_run` starts the
  run at `INTAKE_PENDING`.
- The maximum automated status is `READY_FOR_HUMAN_MERGE`. No agent ever runs `git merge`.
- A stage that needs a human first calls `run_state.require_gate_approved(change_id, gate)`
  and is refused while the gate is not `APPROVED`.
- Re-invoking the coding runner from `VERIFICATION_FAILED` is a human action: the fix batch
  resets (`iterations = 0`) so the intervention actually buys a new bounded cycle.

### `factory-state.json` schema

| Field | Values |
|---|---|
| `change_id` | `CR-001` |
| `created_at` | ISO-8601 UTC |
| `status` | any status above |
| `human_gates` | `requirements`, `plan`, `review`, `release` → `PENDING` or a decision |
| `verification` | `NOT_RUN` \| `PASS` \| `FAIL` |
| `review` / `security` | `NOT_RUN` (runners of the next milestones) |
| `iterations` | verification failures in the current fix batch |
| `history` | every transition: `{at, to, note}` |

## Human roles and gates

| Role | Gate | Status that opens it | Decisions | Evidence file |
|---|---|---|---|---|
| `product_owner` | `requirements` | `AWAITING_CLARIFICATION` | `APPROVED`, `MODIFIED`, `REJECTED` | `02-human-requirement-decision.json` |
| `tech_lead` (también `product_owner`) | `plan` | `AWAITING_PLAN_APPROVAL` | `APPROVED`, `MODIFIED`, `REJECTED` | `04-human-plan-approval.json` |
| `reviewer` | `review` | `AWAITING_REVIEW_DECISIONS` | `APPROVED`, `MODIFIED`, `REJECTED`, `DEFERRED` | `10-human-review-decisions.json` |
| `release_manager` | `release` | `AWAITING_RELEASE_DECISION` | `APPROVED`, `MODIFIED`, `REJECTED`, `DEFERRED` | `15-release-decision.json` |

Only a person can record a decision (`scripts/approve_gate.py`), and every decision needs
`--by` and `--role`. A wrong role, a wrong status or an empty reason is refused. The `review`
and `release` gates are intentionally unavailable until their milestone: accepting them now
would create fake evidence.

## Agent contracts

| Agent | Input context (allow) | Write tools (allow) | Deny | Output in `runs/<CR-ID>/` | Stop conditions |
|---|---|---|---|---|---|
| `intake` | `00-change-request.md`, human clarifications, `list_repo_files`, `read_scoped_file` | none | any write | `01-intake-report.md` | missing/ambiguous business rule → `RECOMMENDATION: HUMAN_CLARIFICATION_REQUIRED` (fail-closed) |
| `planner` | CR + intake report + selective reads | none | any write | `03-implementation-plan.md` | unresolved ambiguity → stop and ask a human |
| `coder` | CR + approved plan + `git diff` + selective reads | `write_coder_file` (solo `campusflow/` y `tests/`) | `docs/`, `runs/`, `factory_app/`, `scripts/`, `.env`, weak tests | `05-coder-report.md` | plan gate not `APPROVED` → `GateNotApprovedError`; verification failure is a runner concern, never self-approved |
| `tester` | CR + plan + coder report + `run_baseline_verification` | `write_test_file` (solo `tests/`) | any write under `campusflow/` | `06-test-analysis.md` | never claims PASS without deterministic output |
| `reviewer` | `REQUIREMENTS.md`, `SPEC.md`, `ARCHITECTURE.md`, `00-change-request.md`, `03-implementation-plan.md`, `git diff`, `07-verification.txt` | none (read-only 100%) | any write, any code change | `08-review-report.md` | insufficient evidence → report, do not conclude |
| `security` | same inputs as reviewer + deterministic scanner output | none (read-only 100%) | any write, any code change | `09-security-report.md` | insufficient evidence → report, do not conclude |

Additional contract rules enforced in code:

- Context engineering: prompts carry the CR, the plan and a bounded `git diff`; never the
  whole repository. `docs/REPO_MAP.md` guides selective reads.
- Reviewer and Security run in clean, independent sessions: they never receive the Coder's
  history or reasoning, only the files listed above.
- Deterministic verification (`pytest`, `ruff`, then scanners) runs before any generative
  review; its raw output is `07-verification.txt`.

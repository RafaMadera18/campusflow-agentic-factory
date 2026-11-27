from google.adk.agents.llm_agent import LlmAgent

from .prompts import (
    CODER_INSTRUCTION,
    EVIDENCE_INSTRUCTION,
    INTAKE_INSTRUCTION,
    PLANNER_INSTRUCTION,
    REVIEWER_INSTRUCTION,
    SECURITY_INSTRUCTION,
    TEST_ANALYST_INSTRUCTION,
)
from .tools import (
    get_git_diff,
    list_repo_files,
    read_scoped_file,
    run_baseline_verification,
    write_coder_file,
    write_run_evidence,
    write_test_file,
)

GEMINI_MODEL = "gemini-3.8-flash"
READ_TOOLS = [list_repo_files, read_scoped_file]

intake_agent = LlmAgent(
    name="IntakeAgent",
    model=GEMINI_MODEL,
    description="Analyzes a Change Request and determines whether it is ready for planning.",
    instruction=INTAKE_INSTRUCTION,
    tools=READ_TOOLS,
    output_key="intake_report",
)

planner_agent = LlmAgent(
    name="PlannerAgent",
    model=GEMINI_MODEL,
    description="Creates an implementation plan without changing code.",
    instruction=PLANNER_INSTRUCTION + "\n\nIntake report:\n{intake_report}",
    tools=READ_TOOLS,
    output_key="implementation_plan",
)

# Least privilege is enforced by the tool list below: the Coder physically cannot write
# docs/, runs/, factory_app/, scripts/ or .env because those tools are never handed to it.
coder_agent = LlmAgent(
    name="CoderAgent",
    model=GEMINI_MODEL,
    description="Implements a human-approved plan inside campusflow/ and tests/ only.",
    instruction=CODER_INSTRUCTION + "\n\nApproved implementation plan:\n{implementation_plan}",
    tools=[*READ_TOOLS, write_coder_file, get_git_diff],
    output_key="coder_report",
)

test_analyst_agent = LlmAgent(
    name="TestAnalystAgent",
    model=GEMINI_MODEL,
    description="Adds tests under tests/ only and interprets deterministic evidence.",
    instruction=(
        TEST_ANALYST_INSTRUCTION
        + "\n\nApproved implementation plan:\n{implementation_plan}"
        + "\n\nCoder report:\n{coder_report}"
    ),
    tools=[*READ_TOOLS, write_test_file, run_baseline_verification],
    output_key="test_analysis",
)

reviewer_agent = LlmAgent(
    name="ReviewerAgent",
    model=GEMINI_MODEL,
    description="Independent read-only software reviewer.",
    instruction=REVIEWER_INSTRUCTION,
    tools=READ_TOOLS,
    output_key="review_report",
)

security_agent = LlmAgent(
    name="SecurityAgent",
    model=GEMINI_MODEL,
    description="Independent read-only security reviewer.",
    instruction=SECURITY_INSTRUCTION,
    tools=READ_TOOLS,
    output_key="security_report",
)

evidence_agent = LlmAgent(
    name="EvidenceAgent",
    model=GEMINI_MODEL,
    description="Consolidates evidence without making the final release decision.",
    instruction=EVIDENCE_INSTRUCTION,
    tools=[*READ_TOOLS, write_run_evidence],
    output_key="evidence_summary",
)

"""Unified prompt measurement for master (Step 0) vs feat/compact-design-agent-prompts (Step 1).

Measures Spec, Plan, and Task prompts against fixed, reproducible task fixtures
and project definition across 3 stack configurations.
"""
# ruff: noqa: E501, PLR0915, PLR2004, S101

from __future__ import annotations

import inspect
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FIXTURE_REQUIREMENT_PY = (
    "Create a small, self-contained Python utility for counting words in text.\n\n"
    "Context:\n"
    "- Python 3.10+, standard library only, no third-party dependencies.\n"
    "- Add new files only. Do not modify any existing file.\n\n"
    "Files to create:\n"
    "- text_utils/__init__.py (empty)\n"
    "- text_utils/word_count.py\n"
    "- tests/test_word_count.py (pytest)\n\n"
    "Functional requirements:\n"
    "1. Function count_words(text: str) -> int returns the number of words in text.\n"
    "2. A word is any run of non-whitespace characters. Leading, trailing and repeated "
    "whitespace (spaces, tabs, newlines) must not create extra words.\n"
    "3. Empty string or whitespace-only string returns 0.\n"
    "4. Function top_words(text: str, n: int = 3) -> list[tuple[str, int]] returns the n "
    "most frequent words as (word, count) pairs, case-insensitive, sorted by count descending, "
    'then alphabetically for ties. Strip leading/trailing punctuation from each word (".,;:!?").\n'
    "5. Both functions raise TypeError if text is not a str.\n"
    "6. top_words raises ValueError if n < 1.\n\n"
    "Acceptance criteria:\n"
    '- count_words("hello world") == 2\n'
    '- count_words("  a \\t b\\n\\nc  ") == 3\n'
    '- count_words("") == 0 and count_words("   ") == 0\n'
    '- top_words("the cat and the dog and the bird", 2) == [("the", 3), ("and", 2)]\n'
    '- top_words("Hello, hello! World.", 1) == [("hello", 2)]\n'
    '- count_words(123) raises TypeError; top_words("a", 0) raises ValueError\n'
    "- All tests in tests/test_word_count.py pass with pytest.\n\n"
    "Non-functional: type hints and a short docstring on each public function."
)

FIXTURE_SPEC_TEXT_PY = """## Background / Goal
Create a small, self-contained Python utility for counting words in text.

## Scope (in / out)
In scope: text_utils package with word counting and top words frequency.
Out of scope: external dependencies, GUI, file processing.

## Functional requirements
1. count_words(text: str) -> int
2. top_words(text: str, n: int = 3) -> list[tuple[str, int]]

## Non-functional requirements
Type hints, docstrings, Python 3.10+, files in text_utils/word_count.py and tests/test_word_count.py.

## Acceptance criteria
All tests pass with pytest.

## Open questions
None.

## Revision history
v1: Initial draft."""

FIXTURE_PLAN_TEXT_PY = """## Milestones
- M1: Implement core text_utils module (text_utils/word_count.py)
  - Deliverables: text_utils/__init__.py, text_utils/word_count.py
  - Acceptance criteria: count_words and top_words implemented
  - Depends on: none
- M2: Implement test suite with pytest (tests/test_word_count.py)
  - Deliverables: tests/test_word_count.py
  - Acceptance criteria: pytest passes
  - Depends on: M1"""

FIXTURE_REQUIREMENT_TS = (
    "Create a React bidding form component (CreateBiddingForm.tsx).\n\n"
    "Context:\n"
    "- TypeScript, React, Vite.\n"
    "- File: src/features/bidding/CreateBiddingForm.tsx.\n\n"
    "Functional requirements:\n"
    "1. Form allows entering auctionId, amount, and optional note.\n"
    "2. Validate amount must be positive and greater than current bid.\n"
    "3. Submit bid via POST /api/bids endpoint.\n"
    "4. Show confirmation banner or error notification.\n\n"
    "Acceptance criteria:\n"
    "- CreateBiddingForm renders with input fields and submit button.\n"
    "- Validates input values with inline error messages.\n"
    "- Unit tests in src/features/bidding/__tests__/CreateBiddingForm.test.tsx pass with vitest."
)

FIXTURE_SPEC_TEXT_TS = """## Background / Goal
Create CreateBiddingForm.tsx with React form validation and bid submission.

## Scope (in / out)
In scope: CreateBiddingForm.tsx component, validation, API submission.
Out of scope: Payment gateway processing.

## Functional requirements
1. Input fields for auctionId, amount, note.
2. Submit via POST /api/bids.

## Non-functional requirements
TypeScript, React hooks, proper form validation.

## Acceptance criteria
Form submits correctly and tests pass.

## Open questions
None.

## Revision history
v1: Initial draft."""

FIXTURE_PLAN_TEXT_TS = """## Milestones
- M1: Implement CreateBiddingForm component
  - Deliverables: src/features/bidding/CreateBiddingForm.tsx
  - Acceptance criteria: Component renders and validates input
  - Depends on: none
- M2: Implement test suite
  - Deliverables: src/features/bidding/__tests__/CreateBiddingForm.test.tsx
  - Acceptance criteria: Vitest tests pass
  - Depends on: M1"""

FIXTURE_REQUIREMENT_FS = (
    "Implement Auction Bidding feature with FastAPI backend and React frontend.\n\n"
    "Context:\n"
    "- Backend: Python 3.10+, FastAPI in src/api/auctions.py.\n"
    "- Frontend: TypeScript, React in src/features/bidding/CreateBiddingForm.tsx.\n\n"
    "Functional requirements:\n"
    "1. Backend endpoint POST /api/bids creates a bid and validates amount.\n"
    "2. Frontend form submits bid to backend and shows confirmation.\n"
    "3. Unit tests for both backend (pytest) and frontend (vitest).\n\n"
    "Acceptance criteria:\n"
    "- POST /api/bids returns 201 Created with bid ID.\n"
    "- CreateBiddingForm interacts with the endpoint successfully.\n"
    "- All backend and frontend tests pass."
)

FIXTURE_SPEC_TEXT_FS = """## Background / Goal
Auction bidding fullstack feature with FastAPI backend and React frontend.

## Scope (in / out)
In scope: POST /api/bids in FastAPI and CreateBiddingForm in React.
Out of scope: Payment gateway integration.

## Functional requirements
1. FastAPI endpoint POST /api/bids.
2. React form CreateBiddingForm.tsx.

## Non-functional requirements
Type hints in Python, strict TypeScript, responsive UI.

## Acceptance criteria
All tests pass.

## Open questions
None.

## Revision history
v1: Initial draft."""

FIXTURE_PLAN_TEXT_FS = """## Milestones
- M1: Implement FastAPI backend endpoint
  - Deliverables: src/api/auctions.py, tests/test_auctions.py
  - Acceptance criteria: pytest passes
  - Depends on: none
- M2: Implement React frontend form
  - Deliverables: src/features/bidding/CreateBiddingForm.tsx
  - Acceptance criteria: vitest passes
  - Depends on: M1"""

SAMPLE_FAULTY_REPLY = (
    "I understand your request. Here is a brief plan to count words.\n"
    "Could you please clarify if you want any additional punctuation stripped?"
)


FIXTURE_REQUIREMENT_VHPC_JAVA = (
    "Implement a Spring Boot REST endpoint POST /api/v1/allocations for GPU cluster allocation.\n\n"
    "Context:\n"
    "- Backend: Java 21, Spring Boot in src/main/java/com/vhpc/allocation/AllocationController.java.\n"
    "- Validate quota limits and return ProblemDetails on error.\n\n"
    "Acceptance criteria:\n"
    "- POST /api/v1/allocations returns 201 Created.\n"
    "- Authorization checks enforce tenant scope."
)

FIXTURE_SPEC_TEXT_VHPC_JAVA = """## Background / Goal
Implement POST /api/v1/allocations in Java Spring Boot for GPU cluster allocation.

## Scope (in / out)
In scope: AllocationController.java, DTO validation, tenant authorization.
Out of scope: Billing integration.

## Functional requirements
1. POST /api/v1/allocations creates allocation and returns 201 Created.

## Non-functional requirements
Java 21, Spring Boot, ProblemDetails error responses.

## Acceptance criteria
mvn test passes.

## Open questions
None.

## Revision history
v1: Initial draft."""

FIXTURE_PLAN_TEXT_VHPC_JAVA = """## Milestones
- M1: Implement AllocationController and DTOs
  - Deliverables: AllocationController.java, AllocationRequest.java
  - Acceptance criteria: mvn test passes
  - Depends on: none"""

FIXTURE_REQUIREMENT_VHPC_FS = (
    "Implement a GPU cluster allocation feature across backend and frontend.\n\n"
    "Context:\n"
    "- Backend: Java 21, Spring Boot in src/main/java/com/vhpc/allocation/AllocationController.java "
    "exposing POST /api/v1/allocations.\n"
    "- Frontend: React, TypeScript in frontend/src/features/allocations/AllocationForm.tsx.\n\n"
    "Acceptance criteria:\n"
    "- POST /api/v1/allocations validates quota limits and returns 201 Created.\n"
    "- AllocationForm.tsx submits the form and displays validation or error feedback."
)

FIXTURE_SPEC_TEXT_VHPC_FS = """## Background / Goal
Implement GPU cluster allocation in Java Spring Boot and React TypeScript.

## Scope (in / out)
In scope: AllocationController.java (POST /api/v1/allocations) and AllocationForm.tsx.
Out of scope: Billing integration.

## Functional requirements
1. Backend endpoint POST /api/v1/allocations validates quota and returns 201 Created.
2. Frontend AllocationForm.tsx collects allocation parameters and handles responses.

## Non-functional requirements
Java 21, Spring Boot, React TypeScript, ProblemDetails error responses.

## Acceptance criteria
mvn test and vitest pass.

## Open questions
None.

## Revision history
v1: Initial draft."""

FIXTURE_PLAN_TEXT_VHPC_FS = """## Milestones
- M1: Backend endpoint (AllocationController.java, AllocationRequest.java)
  - Deliverables: AllocationController.java, AllocationRequest.java
  - Acceptance criteria: mvn test passes
  - Depends on: none
- M2: Frontend form (AllocationForm.tsx)
  - Deliverables: frontend/src/features/allocations/AllocationForm.tsx
  - Acceptance criteria: vitest passes
  - Depends on: M1"""


@dataclass(frozen=True)
class PromptFixture:
    name: str
    requirement: str
    spec_text: str
    plan_text: str
    project_id: str = "myagent"


FIXTURES: list[PromptFixture] = [
    PromptFixture(
        "Fixture 1: Python thuần (word-count-util)",
        FIXTURE_REQUIREMENT_PY,
        FIXTURE_SPEC_TEXT_PY,
        FIXTURE_PLAN_TEXT_PY,
    ),
    PromptFixture(
        "Fixture 2: TypeScript / React (CreateBiddingForm)",
        FIXTURE_REQUIREMENT_TS,
        FIXTURE_SPEC_TEXT_TS,
        FIXTURE_PLAN_TEXT_TS,
    ),
    PromptFixture(
        "Fixture 3: Fullstack (FastAPI + React)",
        FIXTURE_REQUIREMENT_FS,
        FIXTURE_SPEC_TEXT_FS,
        FIXTURE_PLAN_TEXT_FS,
    ),
    PromptFixture(
        "Fixture 4: VHPC (Java Spring Boot)",
        FIXTURE_REQUIREMENT_VHPC_JAVA,
        FIXTURE_SPEC_TEXT_VHPC_JAVA,
        FIXTURE_PLAN_TEXT_VHPC_JAVA,
        project_id="vhpc",
    ),
    PromptFixture(
        "Fixture 5: VHPC Fullstack (Java Spring Boot + React TypeScript)",
        FIXTURE_REQUIREMENT_VHPC_FS,
        FIXTURE_SPEC_TEXT_VHPC_FS,
        FIXTURE_PLAN_TEXT_VHPC_FS,
        project_id="vhpc",
    ),
]


def _measure_spec(
    target_dir: Path, templates_dir: Path, project_context: dict[str, Any], req: str
) -> dict[str, Any]:
    from asf.agents.loading import load_spec_prompts, load_spec_template
    from asf.agents.spec.agent import _build_retry_messages
    from asf.agents.spec.prompts import SpecPromptContext, build_spec_messages

    spec_p = load_spec_prompts()
    spec_t = load_spec_template(templates_dir)
    spec_ctx = SpecPromptContext(
        prompts=spec_p,
        template=spec_t,
        requirement=req,
        language=None,
        project_context=project_context,
    )
    spec_m = build_spec_messages(spec_ctx)
    spec_sys = spec_m[0].content
    spec_user = spec_m[1].content
    spec_t1 = len(spec_sys) + len(spec_user)

    sig = inspect.signature(_build_retry_messages)
    if len(sig.parameters) == 3:
        spec_retry = _build_retry_messages(spec_m, SAMPLE_FAULTY_REPLY, ["## Background / Goal"])
    else:
        spec_retry = _build_retry_messages(spec_m, ["## Background / Goal"])
    spec_t2 = sum(len(m.content) for m in spec_retry)

    return {
        "sys": len(spec_sys),
        "user": len(spec_user),
        "turn1": spec_t1,
        "turn2": spec_t2,
        "retry_delta": spec_t2 - spec_t1,
        "sys_text": spec_sys,
        "user_text": spec_user,
    }


def _measure_plan(
    target_dir: Path, templates_dir: Path, project_context: dict[str, Any], spec_text: str
) -> dict[str, Any]:
    from asf.agents.loading import load_plan_prompts, load_plan_template
    from asf.agents.plan.prompts import PlanPromptContext, build_plan_messages

    spec_art = {"id": "spec-1", "version": "1", "content": {"text": spec_text}}
    plan_p = load_plan_prompts()
    plan_t = load_plan_template(templates_dir)
    plan_ctx = PlanPromptContext(
        prompts=plan_p,
        template=plan_t,
        spec_artifact=spec_art,
        language=None,
        project_context=project_context,
    )
    plan_m = build_plan_messages(plan_ctx)
    plan_sys = plan_m[0].content
    plan_user = plan_m[1].content
    plan_t1 = len(plan_sys) + len(plan_user)

    return {
        "sys": len(plan_sys),
        "user": len(plan_user),
        "turn1": plan_t1,
        "sys_text": plan_sys,
        "user_text": plan_user,
    }


def _measure_task(
    target_dir: Path,
    templates_dir: Path,
    project_context: dict[str, Any],
    fixture: PromptFixture,
) -> dict[str, Any]:
    from asf.agents.loading import load_task_prompts, load_task_template
    from asf.agents.task.prompts import TaskPromptContext, build_task_messages

    spec_art = {"id": "spec-1", "version": "1", "content": {"text": fixture.spec_text}}
    plan_art = {"id": "plan-1", "version": "1", "content": {"text": fixture.plan_text}}
    task_p = load_task_prompts()
    task_t = load_task_template(templates_dir)
    task_ctx = TaskPromptContext(
        prompts=task_p,
        template=task_t,
        spec_artifact=spec_art,
        plan_artifact=plan_art,
        language=None,
        project_context=project_context,
    )
    task_m = build_task_messages(task_ctx)
    task_sys = task_m[0].content
    task_user = task_m[1].content
    task_t1 = len(task_sys) + len(task_user)

    return {
        "sys": len(task_sys),
        "user": len(task_user),
        "turn1": task_t1,
        "sys_text": task_sys,
        "user_text": task_user,
    }


def measure_target(target_dir: Path, fixture: PromptFixture) -> dict[str, Any]:
    to_remove = [k for k in sys.modules if k.startswith("asf")]
    for k in to_remove:
        del sys.modules[k]

    sys.path.insert(0, str(target_dir / "src"))
    from asf.api.demo import DemoFactoryService
    from asf.configuration.loader import load_projects

    templates_dir = target_dir / "templates"
    demo = DemoFactoryService.__new__(DemoFactoryService)
    demo._projects_dir = target_dir / "projects"
    demo._skills_dir = target_dir / "skills"

    if fixture.project_id == "vhpc":
        profile = load_projects(demo._projects_dir)["vhpc"].to_contract()
        tech = profile.get("technology", {})
        flat_tech = [t for vals in tech.values() if isinstance(vals, list) for t in vals]
        demo._project_profiles = {"vhpc": profile}
        demo._projects = {"vhpc": {"technologies": flat_tech}}
        real_skills = demo._project_skills("vhpc")
        review_rules_content = demo._review_rules("vhpc")
    else:
        tech = {"backend": ["python", "fastapi"], "frontend": ["react", "typescript"]}
        demo._project_profiles = {
            "myagent": {
                "enabledSkills": ["security", "python", "react", "testing", "git"],
                "technology": tech,
            }
        }
        demo._projects = {}
        real_skills = demo._project_skills("myagent")
        review_rules_path = target_dir / "projects" / "rules" / "languages" / "typescript.md"
        review_rules_content = (
            review_rules_path.read_text("utf-8") if review_rules_path.exists() else ""
        )

    project_context = {
        "skills": real_skills,
        "reviewRules": review_rules_content,
        "technology": tech,
    }
    if fixture.project_id == "vhpc":
        design_budget = profile.get("configuration", {}).get("designRulesBudget")
        if isinstance(design_budget, dict):
            project_context["designRulesBudget"] = design_budget

    res: dict[str, Any] = {
        "spec": _measure_spec(target_dir, templates_dir, project_context, fixture.requirement),
        "plan": _measure_plan(target_dir, templates_dir, project_context, fixture.spec_text),
        "task": _measure_task(target_dir, templates_dir, project_context, fixture),
    }

    sys.path.remove(str(target_dir / "src"))
    return res


def extract_breakdown(sys_text: str, user_text: str, agent: str) -> dict[str, int]:
    rules_intro_keywords = ["Project standards", "Project development rules"]
    skills_intro_keyword = "Project skills"

    rules_idx = -1
    for kw in rules_intro_keywords:
        idx = sys_text.find(kw)
        if idx != -1:
            rules_idx = idx
            break

    skills_idx = sys_text.find(skills_intro_keyword)

    if rules_idx != -1 and skills_idx != -1:
        contract_len = rules_idx
        standards_len = skills_idx - rules_idx
        skills_len = len(sys_text) - skills_idx
    elif rules_idx != -1 and skills_idx == -1:
        contract_len = rules_idx
        standards_len = len(sys_text) - rules_idx
        skills_len = 0
    elif rules_idx == -1 and skills_idx != -1:
        contract_len = skills_idx
        standards_len = 0
        skills_len = len(sys_text) - skills_idx
    else:
        contract_len = len(sys_text)
        standards_len = 0
        skills_len = 0

    assert contract_len + standards_len + skills_len == len(sys_text)

    lang_idx = user_text.find("## Output language")
    proj_idx = user_text.find("## Project context")
    tmpl_idx = user_text.find("## Template")

    indices = [("req", 0)]
    if lang_idx != -1:
        indices.append(("lang", lang_idx))
    if proj_idx != -1:
        indices.append(("proj", proj_idx))
    if tmpl_idx != -1:
        indices.append(("tmpl", tmpl_idx))

    indices.sort(key=lambda x: x[1])

    breakdown: dict[str, int] = {
        "contract": contract_len,
        "standards": standards_len,
        "skills": skills_len,
        "sys_total": len(sys_text),
        "req": 0,
        "lang": 0,
        "proj": 0,
        "tmpl": 0,
        "user_total": len(user_text),
    }

    for i in range(len(indices)):
        name, start = indices[i]
        end = indices[i + 1][1] if i + 1 < len(indices) else len(user_text)
        breakdown[name] = end - start

    assert breakdown["req"] + breakdown["lang"] + breakdown["proj"] + breakdown["tmpl"] == len(
        user_text
    )
    return breakdown


def extract_loaded_rules_sections(sys_text: str) -> list[str]:
    start = -1
    for kw in ("Project standards", "Project development rules"):
        idx = sys_text.find(kw)
        if idx != -1:
            start = idx
            break
    if start == -1:
        return []
    end = sys_text.find("Project skills", start)
    block = sys_text[start:] if end == -1 else sys_text[start:end]
    return [line.strip() for line in block.splitlines() if line.startswith("## ")]


def _print_agent_breakdown(
    agent: str,
    master_res: dict[str, Any],
    branch_res: dict[str, Any],
) -> None:
    m_b = extract_breakdown(master_res[agent]["sys_text"], master_res[agent]["user_text"], agent)
    b_b = extract_breakdown(branch_res[agent]["sys_text"], branch_res[agent]["user_text"], agent)
    print(f"\n--- {agent.upper()} AGENT ---")
    print(f"Contract:        {m_b['contract']} -> {b_b['contract']}")
    print(f"Standards:       {m_b['standards']} -> {b_b['standards']}")
    print(f"Skills:          {m_b['skills']} -> {b_b['skills']}")
    print(f"-> System Total: {m_b['sys_total']} -> {b_b['sys_total']}")
    print(f"Req/Artifacts:   {m_b['req']} -> {b_b['req']}")
    print(f"Output Language: {m_b['lang']} -> {b_b['lang']}")
    print(f"Project Context: {m_b['proj']} -> {b_b['proj']}")
    print(f"Template:        {m_b['tmpl']} -> {b_b['tmpl']}")
    print(f"-> User Total:   {m_b['user_total']} -> {b_b['user_total']}")
    t1_m = master_res[agent]["turn1"]
    t1_b = branch_res[agent]["turn1"]
    pct1 = ((t1_b - t1_m) / t1_m) * 100
    print(f"-> Turn 1 Total: {t1_m} -> {t1_b} ({pct1:+.1f}%)")
    if "turn2" in master_res[agent]:
        t2_m = master_res[agent]["turn2"]
        t2_b = branch_res[agent]["turn2"]
        pct2 = ((t2_b - t2_m) / t2_m) * 100
        print(f"-> Turn 2 Total: {t2_m} -> {t2_b} ({pct2:+.1f}%)")
        print(
            f"-> Retry Delta:  +{master_res[agent]['retry_delta']} -> +{branch_res[agent]['retry_delta']}"
        )
    loaded = extract_loaded_rules_sections(branch_res[agent]["sys_text"])
    print(f"Rules Loaded:    {loaded if b_b['standards'] > 0 else []}")


def _print_fixture_results(
    fixture: PromptFixture, master_res: dict[str, Any], branch_res: dict[str, Any]
) -> None:
    print("\n=======================================================")
    print(f"=== {fixture.name.upper()} ===")
    print("=======================================================")
    for agent in ("spec", "plan", "task"):
        _print_agent_breakdown(agent, master_res, branch_res)


def main() -> None:
    current_root = Path(__file__).resolve().parent.parent
    master_root = current_root.parent / "MyAgents-master"

    for fixture in FIXTURES:
        master_res = measure_target(master_root, fixture)
        branch_res = measure_target(current_root, fixture)
        _print_fixture_results(fixture, master_res, branch_res)


if __name__ == "__main__":
    main()

# TASK Breakdown Specification

## Output Format
The LLM MUST return ONLY a JSON envelope with a single top-level key "tasks" containing an array of task objects.
No prose, no markdown, no code fences.

```json
{
  "tasks": [
    { ...task object... },
    { ...task object... }
  ]
}
```

## Task Object Fields (8 required, aliases shown)
| Field | Alias (JSON) | Type | Constraints |
|-------|--------------|------|-------------|
| id | "id" | string | Match `^T[1-9][0-9]*$`; sequential T1, T2, ... |
| title | "title" | string | Non-empty |
| milestone_ref | "milestoneRef" | string | Must match a PLAN milestone ID (e.g., "M1") |
| description | "description" | string | Non-empty |
| acceptance_criteria | "acceptanceCriteria" | list[string] | Non-empty list; each item non-empty string; no duplicates |
| depends_on | "dependsOn" | list[string] | Each item a lower-numbered task ID (e.g., "T1"); no self-deps; no duplicates |
| expected_files | "expectedFiles" | list[string] | Relative paths only; no drive letters, no "..", no backslashes, no empty segments, no control chars; no duplicates |
| verification_hint | "verificationHint" | string | Non-empty |

## Validation Rules (summary)
1. Envelope: object with exactly one key "tasks" (array).
2. Task IDs: strictly sequential T1..Tn (numeric: T10 after T9).
3. milestoneRef: must exist in the input PLAN; sequence across tasks must be non-decreasing.
4. dependsOn: only existing lower-numbered task IDs; no self-dependency.
5. Cross-milestone dependsOn allowed ONLY when the dependency task's milestone is the SAME or an ANCESTOR of the dependent task's milestone (transitive per PLAN dependencies).
6. Every PLAN milestone must have ≥1 task assigned.
7. Max 100 tasks total.
8. acceptanceCriteria: non-empty list of non-empty strings; no duplicates.
9. expectedFiles: relative POSIX paths; no drive letters, no "..", no backslashes, no empty segments, no control chars; no duplicates.
10. verificationHint: non-empty string.

## Worked Example (3 tasks across 2 milestones, with a dependency)
```json
{
  "tasks": [
    {
      "id": "T1",
      "title": "Create project scaffold",
      "milestoneRef": "M1",
      "description": "Initialize repository structure, configuration files, and CI pipeline.",
      "acceptanceCriteria": [
        "Repository builds successfully",
        "CI pipeline passes on main branch"
      ],
      "dependsOn": [],
      "expectedFiles": [
        "pyproject.toml",
        "src/__init__.py",
        ".gitlab-ci.yml"
      ],
      "verificationHint": "Run `pip install -e . && pytest` and verify CI passes"
    },
    {
      "id": "T2",
      "title": "Implement core module",
      "milestoneRef": "M1",
      "description": "Write the core business logic module with unit tests.",
      "acceptanceCriteria": [
        "All unit tests pass",
        "Code coverage ≥ 80%"
      ],
      "dependsOn": ["T1"],
      "expectedFiles": [
        "src/core/__init__.py",
        "src/core/logic.py",
        "tests/unit/test_core.py"
      ],
      "verificationHint": "Run `pytest tests/unit/test_core.py -v`"
    },
    {
      "id": "T3",
      "title": "Integrate with API layer",
      "milestoneRef": "M2",
      "description": "Wire core module into the FastAPI application and add integration tests.",
      "acceptanceCriteria": [
        "API endpoints return expected responses",
        "Integration tests pass"
      ],
      "dependsOn": ["T2"],
      "expectedFiles": [
        "src/api/routes.py",
        "tests/integration/test_api.py"
      ],
      "verificationHint": "Run `pytest tests/integration/test_api.py -v`"
    }
  ]
}
```

(Note: PLAN for this example must contain milestones M1 and M2 where M2 depends on M1, making M1 an ancestor of M2. The cross-milestone dependency T3→T2 is valid because M1 is ancestor of M2.)
3. Base the plan solely on the provided SPEC artifact and project context.
4. Break work into concrete milestones with clear deliverables and acceptance criteria.
5. Identify risks with specific mitigations, not generic statements.
6. List impacted components with file/module names where possible.
7. Under "## Milestones", define each milestone using this strict sub-structure:
   ### M1: <name>
   - Deliverables: ...
   - Acceptance criteria: ...
   - Depends on: none | M<n>, ...
   Milestone IDs must be unique and sequential (M1, M2, ...). Every milestone must have all three fields. "Depends on" must reference only existing earlier milestones (no cycles).
8. The "Linked SPEC" section must reference the provided SPEC artifact ID and version verbatim.
9. Do not invent facts, assumptions, or requirements beyond the provided SPEC and project context.
10. If details are ambiguous or unresolved, document them explicitly under the open questions section.
11. Return only the final markdown document. Do not wrap the response in conversational text or external greetings.